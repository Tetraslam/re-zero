"""
Brio SDK - Unified control for the Logitech MX Brio 4K.

    from brio_sdk import Brio

    cam = Brio()
    frame = cam.capture()
    cam.morse("HELLO")
    cam.zoom(200)
    cam.party_mode()
    cam.close()
"""

import os
import sys
import time
import threading
import subprocess
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mx_brio_morse import (
    MORSE, text_to_morse, morse_to_timeline, wpm_to_unit, decode_morse,
)

try:
    import hid
except ImportError:
    hid = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

VID, PID = 0x046D, 0x0944

# ── Effects ──────────────────────────────────────────────────────

def _fx_normal(f, _): return f
def _fx_grayscale(f, _):
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY); return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
def _fx_sepia(f, i):
    k = np.array([[.272,.534,.131],[.349,.686,.168],[.393,.769,.189]])
    s = np.clip(cv2.transform(f, k), 0, 255).astype(np.uint8)
    return cv2.addWeighted(s, min(i, 1.0), f, 1.0 - min(i, 1.0), 0)
def _fx_invert(f, _): return cv2.bitwise_not(f)
def _fx_contrast(f, i):
    a = 1.0 + i; return np.clip(a * f.astype(np.float32) - 128*(a-1), 0, 255).astype(np.uint8)
def _fx_dark(f, i):
    return np.clip(f.astype(np.float32) - 50*i, 0, 255).astype(np.uint8)
def _fx_bright(f, i):
    return np.clip(f.astype(np.float32) + 50*i, 0, 255).astype(np.uint8)
def _fx_saturate(f, i):
    h = cv2.cvtColor(f, cv2.COLOR_BGR2HSV).astype(np.float32)
    h[:,:,1] = np.clip(h[:,:,1]*(1+i), 0, 255); return cv2.cvtColor(h.astype(np.uint8), cv2.COLOR_HSV2BGR)
def _fx_desaturate(f, _):
    h = cv2.cvtColor(f, cv2.COLOR_BGR2HSV); h[:,:,1] = 0; return cv2.cvtColor(h, cv2.COLOR_HSV2BGR)
def _fx_hue(f, i):
    h = cv2.cvtColor(f, cv2.COLOR_BGR2HSV).astype(np.float32)
    h[:,:,0] = (h[:,:,0]+90*i)%180; return cv2.cvtColor(h.astype(np.uint8), cv2.COLOR_HSV2BGR)
def _fx_pixelate(f, i):
    h, w = f.shape[:2]; s = max(2, int(12*i))
    return cv2.resize(cv2.resize(f, (w//s, h//s), interpolation=cv2.INTER_LINEAR), (w, h), interpolation=cv2.INTER_NEAREST)
def _fx_blur(f, i):
    k = max(1, int(20*i))|1; return cv2.GaussianBlur(f, (k, k), 0)
def _fx_edges(f, i):
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.Canny(g, 50/i, 150/i), cv2.COLOR_GRAY2BGR)
def _fx_posterize(f, i):
    l = max(2, int(6-3*i)); d = 256//l; return (f//d*d+d//2).astype(np.uint8)
def _fx_thermal(f, _):
    return cv2.applyColorMap(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.COLORMAP_JET)
def _fx_emboss(f, _):
    return cv2.filter2D(f, -1, np.array([[-2,-1,0],[-1,1,1],[0,1,2]])) + 128
def _fx_sketch(f, _):
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.divide(g, 255 - cv2.GaussianBlur(cv2.bitwise_not(g), (21,21), 0), scale=256), cv2.COLOR_GRAY2BGR)

EFFECTS = {
    "normal": _fx_normal, "grayscale": _fx_grayscale, "sepia": _fx_sepia,
    "invert": _fx_invert, "contrast": _fx_contrast, "dark": _fx_dark,
    "bright": _fx_bright, "saturate": _fx_saturate, "desaturate": _fx_desaturate,
    "hue": _fx_hue, "pixelate": _fx_pixelate, "blur": _fx_blur,
    "edges": _fx_edges, "posterize": _fx_posterize, "thermal": _fx_thermal,
    "emboss": _fx_emboss, "sketch": _fx_sketch,
}

# ── LED patterns ─────────────────────────────────────────────────

PARTY_PATTERNS = {
    "strobe":   [(True, 0.05), (False, 0.05)] * 20,
    "pulse":    [(True, t/20) for t in range(1, 10)] + [(False, t/20) for t in range(1, 10)],
    "heartbeat":[(True, 0.15), (False, 0.1), (True, 0.3), (False, 0.5)] * 4,
    "sos":      None,  # handled by morse
    "disco":    [(True, 0.08), (False, 0.04), (True, 0.04), (False, 0.12),
                 (True, 0.15), (False, 0.06), (True, 0.03), (False, 0.2)] * 3,
    "countdown":[(True, 1.0), (False, 0.3)] + [(True, 0.5), (False, 0.2)] * 2 +
                [(True, 0.2), (False, 0.1)] * 4 + [(True, 0.05), (False, 0.05)] * 10,
}


# ── Brio SDK ─────────────────────────────────────────────────────

class Brio:
    """Unified MX Brio controller."""

    def __init__(self, auto_open=True):
        self._cap = None
        self._hid = None
        self._effect = "normal"
        self._intensity = 1.0
        self._zoom = 1.0
        self._led_thread = None
        self._led_stop = False
        self._morse_active = False
        self._mic_idx = None
        if auto_open:
            self.open()

    # ── Lifecycle ────────────────────────────────────────────────

    def open(self):
        self._open_camera()
        self._open_hid()
        self._find_mic()

    def close(self):
        self.led_stop()
        if self._hid:
            try:
                self._hid.write([0x08, 0x00])
                self._hid.close()
            except:
                pass
            self._hid = None
        if self._cap:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ── Camera ───────────────────────────────────────────────────

    def _open_camera(self):
        for idx in range(3):
            cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
            if not cap.isOpened():
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_FPS, 30)
            for _ in range(10):
                ret, _ = cap.read()
                if ret:
                    break
                time.sleep(0.15)
            else:
                cap.release()
                continue
            # verify 4K capable = Brio
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            if w >= 3840:
                self._cap = cap
                # drain stale frames
                for _ in range(5):
                    cap.read()
                return
            cap.release()
        # fallback
        self._cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

    def _open_hid(self):
        if not hid:
            return
        devices = hid.enumerate(VID, PID)
        # Find the Telephony usage page (0x000B) which has the Mute LED (Report 0x08)
        for d in devices:
            if d.get("usage_page") == 0x000B:
                self._hid = hid.device()
                self._hid.open_path(d["path"])
                return
        # Fallback: try first device
        if devices:
            self._hid = hid.device()
            self._hid.open_path(devices[0]["path"])

    def _find_mic(self):
        if not sd:
            return
        for i, d in enumerate(sd.query_devices()):
            if "brio" in d.get("name", "").lower() and d["max_input_channels"] > 0:
                self._mic_idx = i
                return

    # ── Video capture ────────────────────────────────────────────

    def capture(self, effect=None, intensity=None):
        """Capture a frame, apply current effect. Returns numpy BGR array."""
        if not self._cap or not self._cap.isOpened():
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        # digital zoom
        if self._zoom > 1.01:
            h, w = frame.shape[:2]
            zh, zw = int(h / self._zoom), int(w / self._zoom)
            y1, x1 = (h - zh) // 2, (w - zw) // 2
            frame = cv2.resize(frame[y1:y1+zh, x1:x1+zw], (w, h))
        # effect
        fx_name = effect or self._effect
        fx_int = intensity if intensity is not None else self._intensity
        fx_fn = EFFECTS.get(fx_name, _fx_normal)
        try:
            frame = fx_fn(frame, fx_int)
        except:
            pass
        return frame

    def snapshot(self, path="/tmp/brio_snapshot.jpg", effect=None):
        """Capture and save to file. Returns path."""
        frame = self.capture(effect=effect)
        if frame is not None:
            cv2.imwrite(path, frame)
        return path

    def resolution(self, w=1280, h=720):
        if self._cap:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

    # ── Effects ──────────────────────────────────────────────────

    def effect(self, name="normal", intensity=None):
        self._effect = name if name in EFFECTS else "normal"
        if intensity is not None:
            self._intensity = intensity
        return self._effect

    def effects(self):
        return list(EFFECTS.keys())

    # ── Zoom ─────────────────────────────────────────────────────

    def zoom(self, level=1.0):
        """Set digital zoom 1.0-4.0."""
        self._zoom = max(1.0, min(4.0, float(level)))
        return self._zoom

    # ── LED ──────────────────────────────────────────────────────

    def _led_write(self, on):
        if self._hid:
            try:
                self._hid.write([0x08, 0x01 if on else 0x00])
            except Exception as e:
                import sys
                print(f"[LED] write FAILED: {e}", file=sys.stderr)

    def led(self, on=True):
        self.led_stop()
        self._led_write(on)

    def led_stop(self):
        self._led_stop = True
        self._morse_active = False
        if self._led_thread:
            self._led_thread.join(timeout=3)
            self._led_thread = None
        self._led_stop = False
        self._led_write(False)

    def led_pattern(self, timeline):
        """Play a list of (on: bool, duration_s) tuples in background."""
        self.led_stop()
        def worker():
            for on, dur in timeline:
                if self._led_stop:
                    break
                self._led_write(on)
                time.sleep(dur)
            self._led_write(False)
        self._led_thread = threading.Thread(target=worker, daemon=True)
        self._led_thread.start()

    def party_mode(self, pattern="disco"):
        """Flash LED in a party pattern. Options: strobe, pulse, heartbeat, disco, countdown."""
        if pattern == "sos":
            self.morse("SOS")
            return
        tl = PARTY_PATTERNS.get(pattern, PARTY_PATTERNS["disco"])
        self.led_pattern(tl)

    # ── Morse ────────────────────────────────────────────────────

    def morse(self, text, wpm=12, blocking=False, pause_camera=False):
        """Flash Morse code on LED. Non-blocking by default.
        pause_camera=True releases the camera during flash so firmware
        doesn't force the LED on as a 'camera active' indicator.
        """
        self.led_stop()
        self._morse_active = True
        morse_str = text_to_morse(text)
        timeline = morse_to_timeline(morse_str, wpm_to_unit(wpm))

        def worker():
            # Release camera so firmware LED indicator is off
            if pause_camera and self._cap:
                self._cap.release()
                self._cap = None
                time.sleep(0.3)
            for on, dur in timeline:
                if self._led_stop or not self._morse_active:
                    break
                self._led_write(on)
                time.sleep(dur)
            self._led_write(False)
            self._morse_active = False
            # Reopen camera
            if pause_camera:
                self._open_camera()

        if blocking:
            worker()
        else:
            self._led_thread = threading.Thread(target=worker, daemon=True)
            self._led_thread.start()

    def party_mode_live(self, pattern="disco", pause_camera=False):
        """Party mode with optional camera pause for visible LED."""
        if pattern == "sos":
            self.morse("SOS", pause_camera=pause_camera)
            return
        self.led_stop()
        tl = PARTY_PATTERNS.get(pattern, PARTY_PATTERNS["disco"])

        def worker():
            if pause_camera and self._cap:
                self._cap.release()
                self._cap = None
                time.sleep(0.3)
            for on, dur in tl:
                if self._led_stop:
                    break
                self._led_write(on)
                time.sleep(dur)
            self._led_write(False)
            if pause_camera:
                self._open_camera()

        self._led_thread = threading.Thread(target=worker, daemon=True)
        self._led_thread.start()

    def morse_encode(self, text):
        """Just encode text to Morse string without flashing."""
        return text_to_morse(text)

    def morse_decode(self, morse_str):
        """Decode Morse string to text."""
        return decode_morse(morse_str)

    # ── Audio ────────────────────────────────────────────────────

    def mic_capture(self, seconds=2):
        """Record from Brio mic. Returns numpy float32 array (48kHz stereo)."""
        if not sd or self._mic_idx is None:
            return None
        audio = sd.rec(int(48000 * seconds), samplerate=48000, channels=2,
                       device=self._mic_idx, dtype="float32")
        sd.wait()
        return audio

    def mic_level(self):
        """Quick mic level read. Returns dBFS float."""
        audio = self.mic_capture(seconds=0.25)
        if audio is None:
            return -100.0
        rms = np.sqrt(np.mean(audio ** 2))
        return float(20 * np.log10(rms + 1e-10))

    def mic_volume(self, vol):
        """Set macOS input volume (0-100)."""
        subprocess.run(["osascript", "-e", f"set volume input volume {int(vol)}"],
                       capture_output=True)

    # ── Info ─────────────────────────────────────────────────────

    def info(self):
        """Device info dict."""
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self._cap else 0
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self._cap else 0
        fps = self._cap.get(cv2.CAP_PROP_FPS) if self._cap else 0
        return {
            "device": "Logitech MX Brio 4K",
            "vid_pid": f"{VID:04X}:{PID:04X}",
            "sensor": "Sony IMX415",
            "resolution": f"{w}x{h}",
            "fps": fps,
            "zoom": self._zoom,
            "effect": self._effect,
            "intensity": self._intensity,
            "led": self._hid is not None,
            "mic": self._mic_idx is not None,
            "morse_active": self._morse_active,
            "effects_available": self.effects(),
            "party_patterns": list(PARTY_PATTERNS.keys()),
        }

    def status(self):
        """Quick status."""
        return {
            "camera": self._cap is not None and self._cap.isOpened(),
            "hid": self._hid is not None,
            "mic": self._mic_idx is not None,
            "effect": self._effect,
            "zoom": self._zoom,
            "morse_active": self._morse_active,
        }
