#!/usr/bin/env python3
"""
MX Brio Live Camera Demo - OpenCV approach.
Captures frames via cv2.VideoCapture, applies real-time effects,
displays in OpenCV window. Keyboard controls for effects.
"""

import sys
import os
import time
import threading
import numpy as np
import cv2

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

log("Starting MX Brio Live Demo (OpenCV)...")

try:
    import hid
    HAS_HID = True
except ImportError:
    HAS_HID = False

VID, PID = 0x046D, 0x0944

# ── Globals ──────────────────────────────────────────────────────

current_effect = "Normal"
intensity = 1.0
led_dev = None
led_blinking = False

# ── Effect functions ─────────────────────────────────────────────

def fx_normal(frame, _):
    return frame

def fx_grayscale(frame, _):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

def fx_sepia(frame, intensity):
    kernel = np.array([
        [0.272, 0.534, 0.131],
        [0.349, 0.686, 0.168],
        [0.393, 0.769, 0.189],
    ])
    sepia = cv2.transform(frame, kernel)
    sepia = np.clip(sepia, 0, 255).astype(np.uint8)
    alpha = min(intensity, 1.0)
    return cv2.addWeighted(sepia, alpha, frame, 1.0 - alpha, 0)

def fx_invert(frame, _):
    return cv2.bitwise_not(frame)

def fx_contrast(frame, intensity):
    alpha = 1.0 + intensity  # contrast multiplier
    return np.clip(alpha * frame.astype(np.float32) - 128 * (alpha - 1), 0, 255).astype(np.uint8)

def fx_dark(frame, intensity):
    beta = -50 * intensity
    return np.clip(frame.astype(np.float32) + beta, 0, 255).astype(np.uint8)

def fx_bright(frame, intensity):
    beta = 50 * intensity
    return np.clip(frame.astype(np.float32) + beta, 0, 255).astype(np.uint8)

def fx_saturate(frame, intensity):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + intensity), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

def fx_desaturate(frame, _):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = 0
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def fx_hue(frame, intensity):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + 90 * intensity) % 180
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

def fx_pixelate(frame, intensity):
    h, w = frame.shape[:2]
    scale = max(2, int(12 * intensity))
    small = cv2.resize(frame, (w // scale, h // scale), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

def fx_blur(frame, intensity):
    ksize = max(1, int(20 * intensity)) | 1  # must be odd
    return cv2.GaussianBlur(frame, (ksize, ksize), 0)

def fx_edges(frame, intensity):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50 / intensity, 150 / intensity)
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

def fx_posterize(frame, intensity):
    levels = max(2, int(6 - 3 * intensity))
    div = 256 // levels
    return (frame // div * div + div // 2).astype(np.uint8)

def fx_thermal(frame, intensity):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.applyColorMap(gray, cv2.COLORMAP_JET)

def fx_emboss(frame, _):
    kernel = np.array([[-2, -1, 0], [-1, 1, 1], [0, 1, 2]])
    return cv2.filter2D(frame, -1, kernel) + 128

def fx_sketch(frame, _):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    inv = cv2.bitwise_not(gray)
    blur = cv2.GaussianBlur(inv, (21, 21), 0)
    sketch = cv2.divide(gray, 255 - blur, scale=256)
    return cv2.cvtColor(sketch, cv2.COLOR_GRAY2BGR)

EFFECTS = {
    ord('1'): ("Normal",        fx_normal),
    ord('2'): ("Grayscale",     fx_grayscale),
    ord('3'): ("Sepia",         fx_sepia),
    ord('4'): ("Invert",        fx_invert),
    ord('5'): ("High Contrast", fx_contrast),
    ord('6'): ("Dark",          fx_dark),
    ord('7'): ("Bright",        fx_bright),
    ord('8'): ("Saturate",      fx_saturate),
    ord('9'): ("Hue Shift",     fx_hue),
    ord('0'): ("Pixelate",      fx_pixelate),
    ord('b'): ("Blur",          fx_blur),
    ord('e'): ("Edges",         fx_edges),
    ord('p'): ("Posterize",     fx_posterize),
    ord('d'): ("Desaturate",    fx_desaturate),
    ord('t'): ("Thermal",       fx_thermal),
    ord('m'): ("Emboss",        fx_emboss),
    ord('s'): ("Sketch",        fx_sketch),
}

# ── LED ──────────────────────────────────────────────────────────

def toggle_led():
    global led_blinking
    if not led_dev:
        log("  LED: not available")
        return
    if led_blinking:
        led_blinking = False
        log("  LED: blink OFF")
    else:
        led_blinking = True
        def blink():
            while led_blinking:
                try:
                    led_dev.write([0x08, 0x01])
                    time.sleep(0.5)
                    led_dev.write([0x08, 0x00])
                    time.sleep(0.5)
                except:
                    break
        threading.Thread(target=blink, daemon=True).start()
        log("  LED: blink ON")

# ── Find camera ──────────────────────────────────────────────────

def find_and_open_brio():
    """Find the MX Brio using AVFoundation name lookup, open with OpenCV."""
    # Use AVFoundation to find correct index by name (no resolution probing)
    brio_idx = None
    try:
        import AVFoundation as AVF
        devices = AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo)
        for i, d in enumerate(devices):
            name = str(d.localizedName())
            log(f"  [{i}] {name}")
            if "brio" in name.lower():
                brio_idx = i
    except ImportError:
        log("  AVFoundation not available, trying index 0")

    if brio_idx is None:
        brio_idx = 0
        log(f"  WARN: Brio not found by name, trying index {brio_idx}")
    else:
        log(f"  -> MX Brio at AVFoundation index {brio_idx}")

    # Open with OpenCV - try the found index and nearby indices
    for idx in [brio_idx, 1 - brio_idx]:  # try found index first, then the other
        log(f"  Trying OpenCV index {idx}...")
        cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            log(f"  [{idx}] failed to open")
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)

        # Test if we can actually grab frames
        ok = False
        for attempt in range(20):
            ret, frame = cap.read()
            if ret:
                log(f"  [{idx}] first frame at attempt {attempt + 1}: {frame.shape}")
                ok = True
                break
            time.sleep(0.15)

        if ok:
            # Check if this looks like a 4K-capable camera (Brio)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            is_brio = w >= 3840
            # Set back to 720p
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            tag = "MX Brio (4K confirmed)" if is_brio else "MacBook camera"
            log(f"  [{idx}] identified as: {tag}")
            if is_brio:
                return cap
            # If not Brio, keep as fallback but try next index
            cap.release()
        else:
            log(f"  [{idx}] no frames after 20 attempts")
            cap.release()

    # Last resort: just open whatever works
    log("  Fallback: opening first available camera")
    cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
    return cap if cap.isOpened() else None

# ── Main ─────────────────────────────────────────────────────────

def main():
    global current_effect, intensity, led_dev, led_blinking

    log("Finding cameras...")
    cap = find_and_open_brio()
    if cap is None or not cap.isOpened():
        log("FATAL: Cannot open camera")
        return

    # Set to 1280x720
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    log(f"  Resolution: {w}x{h} @ {fps:.0f}fps")

    # Quick warmup - drain any stale frames
    for _ in range(5):
        cap.read()

    # LED
    if HAS_HID:
        try:
            devices = hid.enumerate(VID, PID)
            if devices:
                led_dev = hid.device()
                led_dev.open_path(devices[0]["path"])
                log("  LED ready")
        except Exception as e:
            log(f"  LED failed: {e}")

    # Window
    win_name = "MX Brio Live"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, 1280, 720)

    current_effect = "Normal"
    current_fn = fx_normal
    frame_count = 0

    log("")
    log("=" * 55)
    log("  LIVE - Press keys in the video window:")
    log("  1=Normal 2=Grayscale 3=Sepia 4=Invert")
    log("  5=HiContrast 6=Dark 7=Bright 8=Saturate")
    log("  9=HueShift 0=Pixelate b=Blur e=Edges")
    log("  p=Posterize d=Desaturate t=Thermal")
    log("  m=Emboss s=Sketch")
    log("  +/-=Intensity  l=LED blink  q=Quit")
    log("=" * 55)
    log("")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                log("Frame grab failed, retrying...")
                time.sleep(0.1)
                continue

            frame_count += 1

            # Apply current effect
            try:
                display = current_fn(frame, intensity)
            except Exception as e:
                if frame_count <= 3:
                    log(f"  Effect error: {e}")
                display = frame

            # HUD overlay
            label = f"{current_effect} | intensity={intensity:.1f} | {w}x{h} | frame {frame_count}"
            cv2.putText(display, label, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            cv2.imshow(win_name, display)

            # Key handling (1ms wait = ~1000fps cap, actual fps limited by camera)
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q') or key == 27:  # q or ESC
                log("Quit")
                break
            elif key in EFFECTS:
                current_effect, current_fn = EFFECTS[key]
                log(f"  Effect: {current_effect}")
            elif key in (ord('+'), ord('=')):
                intensity = min(intensity + 0.2, 3.0)
                log(f"  Intensity: {intensity:.1f}")
            elif key == ord('-'):
                intensity = max(intensity - 0.2, 0.2)
                log(f"  Intensity: {intensity:.1f}")
            elif key == ord('l'):
                toggle_led()
            elif key != 255:  # 255 = no key pressed
                log(f"  Unknown key: {key} ('{chr(key) if 32 <= key < 127 else '?'}')")

    except KeyboardInterrupt:
        log("Interrupted")
    finally:
        log("Cleaning up...")
        cap.release()
        cv2.destroyAllWindows()
        led_blinking = False
        if led_dev:
            try:
                led_dev.write([0x08, 0x00])
                led_dev.close()
            except:
                pass
        log(f"Total frames: {frame_count}")
        log("Done.")


if __name__ == "__main__":
    main()
