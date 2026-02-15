"""
Drone coordinate tracker — WebRTC video in, x/y/z coordinates out.

Uses YOLO object detection on a Modal GPU to track objects in webcam video
and stream normalized (x, y, z) coordinates back via a WebRTC data channel.

x, y: normalized pixel position [0, 1] of the detected object center
z: estimated relative depth from bounding box area (larger box = closer = smaller z)

Run:
    modal serve hardware/drone/tracking/app.py    # dev mode
    modal deploy hardware/drone/tracking/app.py   # persistent endpoint
"""

import json
import time
from pathlib import Path

import modal

from .modal_webrtc import ModalWebRtcPeer, ModalWebRtcSignalingServer

# --- Modal setup ---

app = modal.App("drone-coordinate-tracker")

tracking_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("python3-opencv", "ffmpeg")
    .pip_install(
        "aiortc==1.14.0",
        "fastapi==0.115.12",
        "shortuuid==1.0.13",
        "opencv-python==4.11.0.86",
        "ultralytics>=8.3.0",
        "numpy",
    )
)

CACHE_VOLUME = modal.Volume.from_name(
    "drone-tracker-cache", create_if_missing=True
)
CACHE_PATH = Path("/cache")

# --- Coordinate tracker peer ---


@app.cls(
    image=tracking_image,
    gpu="T4",
    volumes={CACHE_PATH: CACHE_VOLUME},
    timeout=3600,
    region="us-east",
)
@modal.concurrent(target_inputs=2, max_inputs=4)
class CoordinateTracker(ModalWebRtcPeer):
    async def initialize(self):
        from ultralytics import YOLO

        model_path = CACHE_PATH / "yolov8n.pt"
        if not model_path.exists():
            self.model = YOLO("yolov8n.pt")
            import shutil

            shutil.copy("yolov8n.pt", model_path)
            CACHE_VOLUME.commit()
        else:
            self.model = YOLO(str(model_path))

        self.data_channels = {}
        # Reference bbox area for z estimation (calibrate to your setup).
        # bbox_area / frame_area at 1 meter distance. Default assumes object
        # fills ~10% of frame at 1m.
        self.ref_area_fraction = 0.10
        self.ref_distance = 1.0  # meters

    async def setup_streams(self, peer_id: str):
        from aiortc import MediaStreamTrack

        pc = self.pcs[peer_id]

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(
                f"Tracker {self.id}: connection to {peer_id} = "
                f"{pc.connectionState}"
            )

        @pc.on("datachannel")
        def on_datachannel(channel):
            print(f"Tracker {self.id}: data channel '{channel.label}' from {peer_id}")
            self.data_channels[peer_id] = channel

            @channel.on("message")
            def on_message(msg):
                # Client can send config (e.g. target class, ref distance)
                try:
                    data = json.loads(msg)
                    if "ref_distance" in data:
                        self.ref_distance = float(data["ref_distance"])
                    if "ref_area_fraction" in data:
                        self.ref_area_fraction = float(data["ref_area_fraction"])
                except Exception:
                    pass

        @pc.on("track")
        def on_track(track: MediaStreamTrack):
            print(f"Tracker {self.id}: received {track.kind} from {peer_id}")
            output_track = _make_coordinate_track(
                track, self.model, self.data_channels, peer_id, self
            )
            pc.addTrack(output_track)

            @track.on("ended")
            async def on_ended():
                print(f"Tracker {self.id}: track from {peer_id} ended")


def _make_coordinate_track(source, model, data_channels, peer_id, tracker):
    """Build a MediaStreamTrack subclass that runs YOLO and emits coordinates."""
    import cv2
    from aiortc import MediaStreamTrack
    from av import VideoFrame

    class CoordinateVideoTrack(MediaStreamTrack):
        kind = "video"

        def __init__(self):
            super().__init__()
            self._source = source
            self._model = model
            self._data_channels = data_channels
            self._peer_id = peer_id
            self._tracker = tracker
            self._frame_count = 0

        async def recv(self) -> VideoFrame:
            frame = await self._source.recv()
            img = frame.to_ndarray(format="bgr24")
            h, w = img.shape[:2]
            self._frame_count += 1

            results = self._model(img, verbose=False, conf=0.3)
            coords = []

            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cls_name = self._model.names[cls_id]

                    cx = (x1 + x2) / 2.0 / w
                    cy = (y1 + y2) / 2.0 / h

                    bbox_area = (x2 - x1) * (y2 - y1)
                    area_fraction = bbox_area / (w * h)
                    if area_fraction > 0:
                        z = self._tracker.ref_distance * (
                            self._tracker.ref_area_fraction / area_fraction
                        ) ** 0.5
                    else:
                        z = float("inf")

                    coords.append({
                        "x": round(float(cx), 4),
                        "y": round(float(cy), 4),
                        "z": round(float(z), 3),
                        "confidence": round(conf, 3),
                        "class": cls_name,
                        "bbox": [
                            round(float(x1)), round(float(y1)),
                            round(float(x2)), round(float(y2)),
                        ],
                    })

                    cv2.rectangle(
                        img, (int(x1), int(y1)), (int(x2), int(y2)),
                        (0, 255, 0), 2,
                    )
                    label = f"{cls_name} ({cx:.2f},{cy:.2f},{z:.2f}m)"
                    cv2.putText(
                        img, label, (int(x1), int(y1) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2,
                    )

            channel = self._data_channels.get(self._peer_id)
            if channel and channel.readyState == "open":
                channel.send(json.dumps({
                    "timestamp": time.time(),
                    "frame": self._frame_count,
                    "objects": coords,
                }))

            new_frame = VideoFrame.from_ndarray(img, format="bgr24")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base
            return new_frame

    return CoordinateVideoTrack()


# --- Signaling server ---

this_dir = Path(__file__).parent.resolve()

server_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]==0.115.4", "shortuuid==1.0.13")
    .add_local_dir(this_dir / "frontend", remote_path="/frontend")
)


@app.cls(image=server_image)
class TrackerServer(ModalWebRtcSignalingServer):
    def get_modal_peer_class(self):
        return CoordinateTracker

    def initialize(self):
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles

        self.web_app.mount("/static", StaticFiles(directory="/frontend"))

        @self.web_app.get("/")
        async def root():
            html = open("/frontend/index.html").read()
            return HTMLResponse(content=html)
