"""
Drone coordinate tracker — camera frames via WebSocket, XYZ coordinates out.

Camera captures frames → sends JPEG over WebSocket to Modal GPU →
YOLO detects objects → pinhole back-projection computes XYZ in meters →
sends coordinates back over same WebSocket.

Run:
    modal serve hardware/drone/tracking/app.py
    modal deploy hardware/drone/tracking/app.py
"""

import json
import math
import time
from pathlib import Path

import modal

app = modal.App("drone-coordinate-tracker")

this_dir = Path(__file__).parent.resolve()

gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("python3-opencv")
    .pip_install(
        "fastapi[standard]==0.115.12",
        "opencv-python==4.11.0.86",
        "ultralytics>=8.3.0",
        "numpy",
    )
    .add_local_dir(this_dir / "frontend", remote_path="/frontend")
)

CACHE_VOLUME = modal.Volume.from_name("drone-tracker-cache", create_if_missing=True)
CACHE_PATH = Path("/cache")

# ---------------------------------------------------------------------------
# Known real-world object widths in meters (used for depth estimation)
# ---------------------------------------------------------------------------
DEFAULT_OBJECT_WIDTHS = {
    "person": 0.45,
    "cup": 0.08,
    "bottle": 0.07,
    "cell phone": 0.075,
    "laptop": 0.35,
    "keyboard": 0.40,
    "mouse": 0.06,
    "remote": 0.05,
    "book": 0.15,
    "chair": 0.45,
    "tv": 0.90,
    "monitor": 0.55,
    "car": 1.80,
    "truck": 2.50,
    "bicycle": 0.60,
    "motorcycle": 0.80,
    "bus": 2.55,
    "dog": 0.30,
    "cat": 0.20,
    "backpack": 0.30,
    "handbag": 0.25,
    "suitcase": 0.45,
}


class CameraModel:
    """Pinhole camera model for back-projecting 2D detections to 3D coordinates.

    Math:
        z = (fx * W_real) / bbox_width_pixels
        x = (px - cx) * z / fx
        y = (py - cy) * z / fy

    Default intrinsics assume 60° horizontal FoV at 640x480.
    """

    def __init__(self, frame_w=640, frame_h=480, hfov_deg=60.0):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.hfov_deg = hfov_deg
        self._compute_intrinsics()
        self.object_widths = dict(DEFAULT_OBJECT_WIDTHS)

    def _compute_intrinsics(self):
        self.fx = self.frame_w / (2.0 * math.tan(math.radians(self.hfov_deg / 2.0)))
        self.fy = self.fx  # square pixels assumed
        self.cx = self.frame_w / 2.0
        self.cy = self.frame_h / 2.0

    def set_frame_size(self, w, h):
        if w != self.frame_w or h != self.frame_h:
            scale = w / self.frame_w
            self.frame_w = w
            self.frame_h = h
            self.fx *= scale
            self.fy *= scale
            self.cx = w / 2.0
            self.cy = h / 2.0

    def set_intrinsics(self, fx, fy, cx, cy):
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy

    def estimate_depth(self, bbox_width_px, class_name):
        """Estimate depth z (meters) from bounding box width and known object size."""
        real_width = self.object_widths.get(class_name)
        if real_width is None or bbox_width_px <= 0:
            return None
        return (self.fx * real_width) / bbox_width_px

    def backproject(self, px, py, z):
        """Back-project pixel (px, py) at depth z to 3D (x, y, z) in meters."""
        x = (px - self.cx) * z / self.fx
        y = (py - self.cy) * z / self.fy
        return x, y, z

    def calibrate_from_measurement(self, bbox_width_px, known_distance, known_width):
        """Derive fx from a known measurement: object of known_width at known_distance."""
        if bbox_width_px > 0 and known_width > 0 and known_distance > 0:
            self.fx = (bbox_width_px * known_distance) / known_width
            self.fy = self.fx
            return self.fx
        return None

    def get_intrinsics(self):
        return {
            "fx": round(self.fx, 2),
            "fy": round(self.fy, 2),
            "cx": round(self.cx, 2),
            "cy": round(self.cy, 2),
            "frame_w": self.frame_w,
            "frame_h": self.frame_h,
        }


class TemporalFilter:
    """Per-class exponential moving average filter for smoothing coordinates."""

    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self._state = {}  # class_name -> (x, y, z)

    def update(self, class_name, x, y, z):
        if class_name in self._state:
            px, py, pz = self._state[class_name]
            x = self.alpha * x + (1 - self.alpha) * px
            y = self.alpha * y + (1 - self.alpha) * py
            z = self.alpha * z + (1 - self.alpha) * pz
        self._state[class_name] = (x, y, z)
        return x, y, z

    def reset(self):
        self._state.clear()

    def set_alpha(self, alpha):
        self.alpha = max(0.05, min(1.0, alpha))


@app.cls(
    image=gpu_image,
    gpu="T4",
    volumes={CACHE_PATH: CACHE_VOLUME},
    timeout=3600,
    region="us-east",
    scaledown_window=120,
)
@modal.concurrent(target_inputs=2, max_inputs=4)
class DroneTracker:
    @modal.enter()
    def setup(self):
        from ultralytics import YOLO

        model_path = CACHE_PATH / "yolov8n.pt"
        if not model_path.exists():
            self.model = YOLO("yolov8n.pt")
            import shutil
            shutil.copy("yolov8n.pt", model_path)
            CACHE_VOLUME.commit()
        else:
            self.model = YOLO(str(model_path))

        self.camera = CameraModel()
        self.filter = TemporalFilter(alpha=0.3)
        self.frame_count = 0
        self.calibrating = False
        self.calib_class = None
        self.calib_distance = None
        self.calib_width = None
        print("YOLO model loaded, pinhole camera ready.")

    def process_frame(self, jpeg_bytes):
        """Decode JPEG, run YOLO, back-project to 3D coordinates in meters."""
        import cv2
        import numpy as np

        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return []

        h, w = img.shape[:2]
        self.camera.set_frame_size(w, h)
        self.frame_count += 1
        results = self.model(img, verbose=False, conf=0.3)
        coords = []

        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                cls_name = self.model.names[cls_id]

                # Pixel center of bounding box
                px = (x1 + x2) / 2.0
                py = (y1 + y2) / 2.0
                bbox_w = x2 - x1

                # Pinhole depth estimation
                z = self.camera.estimate_depth(bbox_w, cls_name)
                has_depth = z is not None

                if has_depth:
                    x_m, y_m, z_m = self.camera.backproject(px, py, z)
                    x_m, y_m, z_m = self.filter.update(cls_name, x_m, y_m, z_m)
                else:
                    # Unknown object — normalized coords, no depth
                    x_m = (px / w) - 0.5
                    y_m = (py / h) - 0.5
                    z_m = -1.0

                entry = {
                    "x": round(float(x_m), 4),
                    "y": round(float(y_m), 4),
                    "z": round(float(z_m), 3),
                    "confidence": round(conf, 3),
                    "class": cls_name,
                    "has_depth": has_depth,
                    "bbox": [
                        round(float(x1)), round(float(y1)),
                        round(float(x2)), round(float(y2)),
                    ],
                }

                # Calibration mode: capture bbox width for the target class
                if self.calibrating and cls_name == self.calib_class:
                    new_fx = self.camera.calibrate_from_measurement(
                        bbox_w, self.calib_distance, self.calib_width
                    )
                    if new_fx:
                        entry["calibration_result"] = {
                            "fx": round(new_fx, 2),
                            "class": cls_name,
                            "bbox_width_px": round(float(bbox_w), 1),
                        }
                        self.calibrating = False
                        print(f"Calibrated: fx={new_fx:.2f} from {cls_name} "
                              f"(bbox_w={bbox_w:.0f}px, dist={self.calib_distance}m)")

                coords.append(entry)

        if coords and self.frame_count % 30 == 0:
            p = coords[0]
            tag = "3D" if p["has_depth"] else "2D"
            print(f"[F{self.frame_count}][{tag}] {p['class']}: "
                  f"x={p['x']:.3f}m y={p['y']:.3f}m z={p['z']:.2f}m")

        return coords

    def handle_command(self, msg):
        """Handle JSON commands from the frontend via WebSocket."""
        cmd = msg.get("cmd")

        if cmd == "calibrate_start":
            self.calibrating = True
            self.calib_class = msg.get("class", "cup")
            self.calib_distance = float(msg.get("distance", 1.0))
            self.calib_width = float(msg.get("width", 0.08))
            print(f"Calibration started: {self.calib_class} "
                  f"width={self.calib_width}m dist={self.calib_distance}m")
            return {"status": "calibrating", "class": self.calib_class}

        elif cmd == "calibrate_cancel":
            self.calibrating = False
            print("Calibration cancelled")
            return {"status": "cancelled"}

        elif cmd == "set_intrinsics":
            self.camera.set_intrinsics(
                float(msg["fx"]), float(msg["fy"]),
                float(msg["cx"]), float(msg["cy"]),
            )
            print(f"Intrinsics updated: fx={msg['fx']} fy={msg['fy']}")
            return {"status": "ok", "intrinsics": self.camera.get_intrinsics()}

        elif cmd == "set_object_width":
            cls = msg.get("class")
            width = float(msg.get("width", 0))
            if cls and width > 0:
                self.camera.object_widths[cls] = width
                print(f"Object width set: {cls} = {width}m")
            return {"status": "ok"}

        elif cmd == "set_filter_alpha":
            self.filter.set_alpha(float(msg.get("alpha", 0.3)))
            return {"status": "ok", "alpha": self.filter.alpha}

        elif cmd == "get_intrinsics":
            return {"intrinsics": self.camera.get_intrinsics()}

        elif cmd == "reset_filter":
            self.filter.reset()
            return {"status": "ok"}

        return {"error": f"unknown command: {cmd}"}

    @modal.asgi_app()
    def web(self):
        from fastapi import FastAPI, WebSocket
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles

        web_app = FastAPI()
        tracker = self

        web_app.mount("/static", StaticFiles(directory="/frontend"))

        @web_app.get("/")
        async def root():
            html = open("/frontend/index.html").read()
            return HTMLResponse(content=html)

        @web_app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await websocket.accept()
            print("WebSocket connected")
            try:
                while True:
                    msg = await websocket.receive()

                    if msg.get("bytes"):
                        # Binary = JPEG frame
                        coords = tracker.process_frame(msg["bytes"])
                        await websocket.send_text(json.dumps({
                            "type": "frame",
                            "timestamp": time.time(),
                            "frame": tracker.frame_count,
                            "objects": coords,
                            "intrinsics": tracker.camera.get_intrinsics(),
                        }))

                    elif msg.get("text"):
                        # Text = JSON command
                        try:
                            cmd_msg = json.loads(msg["text"])
                            result = tracker.handle_command(cmd_msg)
                            await websocket.send_text(json.dumps({
                                "type": "command_result",
                                **result,
                            }))
                        except json.JSONDecodeError:
                            pass

            except Exception as e:
                print(f"WebSocket closed: {type(e).__name__}: {e}")

        return web_app
