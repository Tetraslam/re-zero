#!/usr/bin/env python3
"""
Brio Demo - MX Brio SDK showcase.

Live video with effects + type a word and watch it flash as Morse code.

Keys:
  [ / ]         : Prev / next effect
  z / x         : Zoom in / out
  r             : Reset zoom
  h             : Flash "HELLO" in Morse (pauses video, flashes LED)
  n             : Flash "SOS" in Morse
  m             : Type a message → Morse on LED
  p             : Party mode (cycles patterns)
  l             : LED toggle
  s             : Save snapshot
  SPACE         : Stop LED / Morse
  q / ESC       : Quit
"""

import os
import sys
import time
import threading
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brio_sdk import Brio, EFFECTS
from mx_brio_morse import text_to_morse

# ── State ─────────────────────────────────────────────────────

effect_names = list(EFFECTS.keys())
effect_idx = 0
party_patterns = ["strobe", "pulse", "heartbeat", "disco", "countdown"]
party_idx = 0
led_on_manual = False

# Display messages
status_msg = ""
status_time = 0


def set_status(msg, duration=3.0):
    global status_msg, status_time
    status_msg = msg
    status_time = time.time() + duration


# ── HUD ──────────────────────────────────────────────────────

def draw_hud(frame, cam):
    h, w = frame.shape[:2]
    overlay = frame.copy()

    # Semi-transparent bar at bottom
    cv2.rectangle(overlay, (0, h - 90), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    y = h - 70
    font = cv2.FONT_HERSHEY_SIMPLEX
    sm = 0.45
    col = (0, 255, 0)
    dim = (120, 120, 120)

    # Line 1: Device + effect + zoom
    line1 = f"MX Brio 4K | Effect: {cam._effect} [{effect_idx+1}/{len(effect_names)}] | Zoom: {cam._zoom:.1f}x"
    if cam._morse_active:
        line1 += " | MORSE ACTIVE"
    cv2.putText(frame, line1, (10, y), font, sm, col, 1)

    # Line 2: Controls
    y += 22
    cv2.putText(frame, "[/] effects | z/x zoom | h hello | n sos | m type msg | p party | q quit",
                (10, y), font, 0.35, dim, 1)

    # Line 3: Status message
    y += 22
    if status_msg and time.time() < status_time:
        cv2.putText(frame, status_msg, (10, y), font, sm, (0, 200, 255), 1)

    # Zoom crosshair
    if cam._zoom > 1.01:
        cx, cy = w // 2, (h - 90) // 2
        cv2.line(frame, (cx - 20, cy), (cx + 20, cy), (0, 255, 0), 1)
        cv2.line(frame, (cx, cy - 20), (cx, cy + 20), (0, 255, 0), 1)
        cv2.putText(frame, f"{cam._zoom:.1f}x", (cx + 25, cy + 5), font, 0.5, (0, 255, 0), 1)

    # Title
    cv2.rectangle(frame, (0, 0), (w, 28), (0, 0, 0), -1)
    cv2.putText(frame, "MX BRIO SDK DEMO", (10, 19), font, 0.5, (0, 255, 0), 1)

    return frame


def draw_morse_screen(frame_shape, text, morse_str):
    """Draw a 'Morse active' screen while camera is paused."""
    h, w = frame_shape[:2]
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX

    cv2.putText(frame, "MORSE CODE", (w//2 - 150, h//2 - 80),
                font, 1.2, (0, 255, 255), 2)
    cv2.putText(frame, f'"{text.upper()}"', (w//2 - 200, h//2 - 20),
                font, 1.0, (255, 255, 255), 2)
    cv2.putText(frame, morse_str, (40, h//2 + 40),
                font, 0.6, (0, 255, 0), 1)
    cv2.putText(frame, "Watch the camera LED...", (w//2 - 180, h//2 + 100),
                font, 0.7, (0, 150, 255), 1)
    return frame


# ── Main ─────────────────────────────────────────────────────

def main():
    global effect_idx, party_idx, led_on_manual

    print("Starting MX Brio SDK Demo...")
    cam = Brio()
    info = cam.info()
    print(f"  Camera: {info['resolution']} @ {info['fps']:.0f}fps")
    print(f"  LED: {'yes' if info['led'] else 'no'}")
    print(f"  Mic: {'yes' if info['mic'] else 'no'}")
    print(f"  Effects: {len(info['effects_available'])}")
    print()

    cv2.namedWindow("Brio Demo", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Brio Demo", 1280, 720)

    snap_count = 0
    frame_shape = (720, 1280, 3)

    while True:
        # If morse is active (camera paused), show morse screen
        if cam._morse_active and cam._cap is None:
            morse_frame = draw_morse_screen(frame_shape, status_msg, "")
            cv2.imshow("Brio Demo", morse_frame)
            key = cv2.waitKey(30) & 0xFF
            if key == ord('q') or key == 27:
                cam.led_stop()
                break
            elif key == ord(' '):
                cam.led_stop()
            continue

        frame = cam.capture()
        if frame is None:
            # Camera might be reopening after morse
            time.sleep(0.05)
            continue

        frame_shape = frame.shape
        frame = draw_hud(frame, cam)
        cv2.imshow("Brio Demo", frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q') or key == 27:
            break

        # Effects
        elif key == ord('['):
            effect_idx = (effect_idx - 1) % len(effect_names)
            cam.effect(effect_names[effect_idx])
        elif key == ord(']'):
            effect_idx = (effect_idx + 1) % len(effect_names)
            cam.effect(effect_names[effect_idx])

        # Zoom
        elif key == ord('z'):
            cam.zoom(cam._zoom + 0.25)
        elif key == ord('x'):
            cam.zoom(max(1.0, cam._zoom - 0.25))
        elif key == ord('r'):
            cam.zoom(1.0)

        # Morse - pauses camera so LED is visible
        elif key == ord('h'):
            set_status("HELLO", 10)
            morse_str = text_to_morse("HELLO")
            print(f"Morse: HELLO -> {morse_str}")
            cam.morse("HELLO", wpm=12, pause_camera=True)

        elif key == ord('n'):
            set_status("SOS", 10)
            morse_str = text_to_morse("SOS")
            print(f"Morse: SOS -> {morse_str}")
            cam.morse("SOS", wpm=15, pause_camera=True)

        elif key == ord('m'):
            # Type in terminal
            print("Type your message (then press Enter):")
            msg = input("  > ").strip()
            if msg:
                morse_str = text_to_morse(msg)
                print(f"Morse: {msg} -> {morse_str}")
                set_status(msg, 30)
                cam.morse(msg, wpm=12, pause_camera=True)

        # Party - also pauses camera
        elif key == ord('p'):
            pattern = party_patterns[party_idx % len(party_patterns)]
            print(f"Party: {pattern}")
            set_status(f"Party: {pattern}", 10)
            cam.party_mode_live(pattern, pause_camera=True)
            party_idx += 1

        # LED toggle (only works when camera is not streaming)
        elif key == ord('l'):
            led_on_manual = not led_on_manual
            cam.led(led_on_manual)

        # Snapshot
        elif key == ord('s'):
            snap_count += 1
            path = f"/tmp/brio_demo_{snap_count}.jpg"
            cam.snapshot(path)
            print(f"Saved: {path}")
            set_status(f"Saved: {path}", 2)

        # Stop
        elif key == ord(' '):
            cam.led_stop()
            led_on_manual = False

    cam.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
