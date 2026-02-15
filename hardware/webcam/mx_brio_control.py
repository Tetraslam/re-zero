#!/usr/bin/env python3
"""
MX Brio Control Panel - Direct hardware control with visible results.

Combines:
  - HID: LED control, register reads, vendor commands
  - AVFoundation: Resolution switching, focus mode, frame rate
  - IOKit UVC: Brightness, contrast, saturation, hue, sharpness, gain, WB temp,
               zoom, focus, exposure (no sudo required)

Usage:
    python3 mx_brio_control.py          # Interactive menu
    python3 mx_brio_control.py --demo   # Auto-run visible demo
"""

import os
import sys
import time

# ── HID ──────────────────────────────────────────────────────────────
try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

# ── AVFoundation ─────────────────────────────────────────────────────
try:
    import AVFoundation as AVF
    import CoreMedia
    HAS_AVF = True
except ImportError:
    HAS_AVF = False

# ── IOKit UVC (import from sibling module) ───────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from mx_brio_iokit_uvc import UVCControl
    HAS_IOKIT_UVC = True
except ImportError:
    HAS_IOKIT_UVC = False

VENDOR_ID = 0x046D
PRODUCT_ID = 0x0944


# ═══════════════════════════════════════════════════════════════════
# HID CONTROLLER
# ═══════════════════════════════════════════════════════════════════

class BrioHID:
    def __init__(self):
        self.dev = None

    def open(self):
        devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
        if not devices:
            raise RuntimeError("MX Brio HID not found!")
        self.dev = hid.device()
        self.dev.open_path(devices[0]["path"])
        return self

    def close(self):
        if self.dev:
            self.dev.close()

    def set_led(self, mute=False, line=False):
        val = (0x01 if mute else 0) | (0x02 if line else 0)
        self.dev.write([0x08, val])

    def blink_sos(self):
        dot, dash, gap, lgap = 0.12, 0.35, 0.1, 0.25
        for ch in "... --- ...":
            if ch == '.':
                self.set_led(mute=True); time.sleep(dot)
                self.set_led(); time.sleep(gap)
            elif ch == '-':
                self.set_led(mute=True); time.sleep(dash)
                self.set_led(); time.sleep(gap)
            elif ch == ' ':
                time.sleep(lgap)

    def blink(self, hz=5, duration=3):
        interval = 1.0 / (hz * 2)
        end = time.time() + duration
        while time.time() < end:
            self.set_led(mute=True); time.sleep(interval)
            self.set_led(); time.sleep(interval)

    def read_register(self, func):
        payload = [0x9A, func, 0x00, 0x00] + [0x00] * 28
        self.dev.send_feature_report(payload)
        time.sleep(0.02)
        return bytes(self.dev.get_feature_report(0x9A, 64))

    def firmware_version(self):
        d = self.read_register(0x00)
        return f"{d[3]}.{d[4]}"


# ═══════════════════════════════════════════════════════════════════
# UVC CONTROL (via IOKit - no sudo required)
# ═══════════════════════════════════════════════════════════════════

class BrioUVC:
    """UVC control via IOKit USB device requests. No sudo needed."""

    def __init__(self):
        self.dev = None  # UVCControl instance
        self._ctrl = None

    def open(self):
        if not HAS_IOKIT_UVC:
            print("  IOKit UVC module not available (mx_brio_iokit_uvc.py missing)")
            return False
        try:
            self._ctrl = UVCControl(vid=VENDOR_ID, pid=PRODUCT_ID)
            self._ctrl.open()
            self.dev = self._ctrl  # for truthy checks
            return True
        except Exception as e:
            print(f"  IOKit UVC open failed: {e}")
            self._ctrl = None
            return False

    def close(self):
        if self._ctrl:
            self._ctrl.close()
            self._ctrl = None
            self.dev = None

    def _get(self, name):
        if not self._ctrl:
            return {"current": None, "min": None, "max": None, "default": None}
        info = self._ctrl.get_control(name)
        return info or {"current": None, "min": None, "max": None, "default": None}

    def _set(self, name, val):
        if not self._ctrl:
            return False
        return self._ctrl.set_control(name, val)

    # Convenience methods matching the old API
    def get_brightness(self):   return self._get('brightness')
    def set_brightness(self, v): return self._set('brightness', v)
    def get_contrast(self):     return self._get('contrast')
    def set_contrast(self, v):  return self._set('contrast', v)
    def get_saturation(self):   return self._get('saturation')
    def set_saturation(self, v): return self._set('saturation', v)
    def get_hue(self):          return self._get('hue')
    def set_hue(self, v):       return self._set('hue', v)
    def get_sharpness(self):    return self._get('sharpness')
    def set_sharpness(self, v): return self._set('sharpness', v)
    def get_gamma(self):        return self._get('gamma')
    def set_gamma(self, v):     return self._set('gamma', v)
    def get_gain(self):         return self._get('gain')
    def set_gain(self, v):      return self._set('gain', v)
    def get_wb_temp(self):      return self._get('wb_temperature')
    def set_wb_temp(self, k):   return self._set('wb_temperature', k)
    def set_wb_auto(self, on=True): return self._set('wb_temperature_auto', 1 if on else 0)
    def get_backlight_comp(self): return self._get('backlight_comp')
    def set_backlight_comp(self, v): return self._set('backlight_comp', v)
    def get_zoom(self):         return self._get('zoom_abs')
    def set_zoom(self, v):      return self._set('zoom_abs', v)
    def get_focus(self):        return self._get('focus_abs')
    def set_focus(self, v):     return self._set('focus_abs', v)
    def set_autofocus(self, on=True): return self._set('focus_auto', 1 if on else 0)
    def get_exposure(self):     return self._get('exposure_time_abs')
    def set_exposure(self, v):  return self._set('exposure_time_abs', v)
    def set_auto_exposure(self, on=True): return self._set('ae_mode', 8 if on else 1)

    def get_pu_control(self, selector, length=2):
        # Map old selector constants to new control names
        SEL_MAP = {0x01: 'backlight_comp', 0x02: 'brightness', 0x03: 'contrast',
                   0x04: 'gain', 0x05: 'power_line_freq', 0x06: 'hue',
                   0x07: 'saturation', 0x08: 'sharpness', 0x09: 'gamma',
                   0x0A: 'wb_temperature', 0x0B: 'wb_temperature_auto'}
        name = SEL_MAP.get(selector)
        return self._get(name) if name else {"current": None}

    def set_pu_control(self, selector, value, length=2):
        SEL_MAP = {0x01: 'backlight_comp', 0x02: 'brightness', 0x03: 'contrast',
                   0x04: 'gain', 0x05: 'power_line_freq', 0x06: 'hue',
                   0x07: 'saturation', 0x08: 'sharpness', 0x09: 'gamma',
                   0x0A: 'wb_temperature', 0x0B: 'wb_temperature_auto'}
        name = SEL_MAP.get(selector)
        return self._set(name, value) if name else False

    def dump_all(self):
        """Read all UVC controls and display them."""
        if not self._ctrl:
            print("    UVC not connected")
            return {}
        controls = self._ctrl.get_all_controls()
        names = UVCControl.FRIENDLY_NAMES if hasattr(UVCControl, 'FRIENDLY_NAMES') else {}
        for name, info in controls.items():
            display = names.get(name, name)
            cur = info.get("current", "?")
            mn = info.get("min", "?")
            mx = info.get("max", "?")
            df = info.get("default", "?")
            print(f"    {display:25s}: {str(cur):>6s} (range: {mn} - {mx}, default: {df})")
        return controls


# ═══════════════════════════════════════════════════════════════════
# AVFoundation CAMERA (resolution + format switching)
# ═══════════════════════════════════════════════════════════════════

class BrioAVF:
    def __init__(self):
        self.device = None
        self.session = None

    def find(self):
        if not HAS_AVF:
            return None
        for dev in AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo):
            if "brio" in str(dev.localizedName()).lower():
                self.device = dev
                return dev
        return None

    def start_session(self):
        if not self.device:
            return
        try:
            self.session = AVF.AVCaptureSession.alloc().init()
            inp, err = AVF.AVCaptureDeviceInput.deviceInputWithDevice_error_(self.device, None)
            if inp and self.session.canAddInput_(inp):
                self.session.addInput_(inp)
            self.session.startRunning()
            time.sleep(0.5)
        except Exception as e:
            print(f"  Session error: {e}")

    def stop_session(self):
        if self.session:
            self.session.stopRunning()

    def set_resolution(self, w, h):
        if not self.device:
            return False
        try:
            ok, _ = self.device.lockForConfiguration_(None)
            if not ok:
                return False
            for fmt in self.device.formats():
                dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(fmt.formatDescription())
                if dims.width == w and dims.height == h:
                    self.device.setActiveFormat_(fmt)
                    self.device.unlockForConfiguration()
                    return True
            self.device.unlockForConfiguration()
            return False
        except Exception:
            return False

    def get_resolution(self):
        if not self.device:
            return "N/A"
        try:
            fmt = self.device.activeFormat()
            dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(fmt.formatDescription())
            return f"{dims.width}x{dims.height}"
        except Exception:
            return "?"


# ═══════════════════════════════════════════════════════════════════
# DEMO
# ═══════════════════════════════════════════════════════════════════

def run_demo(hid_dev, uvc, avf):
    print("\n" + "=" * 70)
    print("  VISIBLE CONTROLS DEMO")
    print("  >>> Open Photo Booth or any camera app to watch! <<<")
    print("=" * 70)

    # ── Device Info ──────────────────────────────────────────────
    print(f"\n[INFO] Firmware: {hid_dev.firmware_version()}")
    print(f"  Resolution: {avf.get_resolution()}")

    if uvc.dev:
        print("\n  UVC Controls:")
        uvc.dump_all()

    # ── LED Demo ─────────────────────────────────────────────────
    print("\n[LED] Morse SOS on webcam LED...")
    hid_dev.blink_sos()
    time.sleep(0.3)
    print("  Alternating LEDs...")
    for _ in range(5):
        hid_dev.set_led(mute=True); time.sleep(0.15)
        hid_dev.set_led(line=True); time.sleep(0.15)
    hid_dev.set_led()

    if not uvc.dev:
        print("\n  UVC not available. Demo limited to LED.")
        return

    # ── Brightness Sweep ─────────────────────────────────────────
    b = uvc.get_brightness()
    if b and b["current"] is not None:
        orig = b["current"]
        mn, mx = b.get("min", 0), b.get("max", 255)
        print(f"\n[BRIGHTNESS] Sweeping {mn} -> {mx} (current: {orig})")
        # Go dark
        for v in range(orig, mn, -max(1, (orig - mn) // 10)):
            uvc.set_brightness(v)
            time.sleep(0.15)
        uvc.set_brightness(mn)
        time.sleep(0.5)
        # Go bright
        for v in range(mn, mx, max(1, (mx - mn) // 10)):
            uvc.set_brightness(v)
            time.sleep(0.15)
        uvc.set_brightness(mx)
        time.sleep(0.5)
        # Restore
        uvc.set_brightness(orig)
        print(f"  Restored to {orig}")

    # ── Contrast Sweep ───────────────────────────────────────────
    c = uvc.get_contrast()
    if c and c["current"] is not None:
        orig = c["current"]
        mn, mx = c.get("min", 0), c.get("max", 255)
        print(f"\n[CONTRAST] Sweeping {mn} -> {mx}")
        uvc.set_contrast(mn); time.sleep(1)
        uvc.set_contrast(mx); time.sleep(1)
        uvc.set_contrast(orig)
        print(f"  Restored to {orig}")

    # ── Saturation Sweep ─────────────────────────────────────────
    s = uvc.get_saturation()
    if s and s["current"] is not None:
        orig = s["current"]
        mn, mx = s.get("min", 0), s.get("max", 255)
        print(f"\n[SATURATION] Sweeping {mn} -> {mx}")
        print("  Desaturated (B&W)...")
        uvc.set_saturation(mn); time.sleep(2)
        print("  Oversaturated...")
        uvc.set_saturation(mx); time.sleep(2)
        uvc.set_saturation(orig)
        print(f"  Restored to {orig}")

    # ── White Balance Temperature ────────────────────────────────
    wb = uvc.get_wb_temp()
    if wb and wb["current"] is not None:
        orig = wb["current"]
        mn, mx = wb.get("min", 2800), wb.get("max", 6500)
        print(f"\n[WHITE BALANCE] Color temperature sweep")
        uvc.set_wb_auto(False)
        time.sleep(0.3)
        print(f"  Warm ({mn}K - candlelight)...")
        uvc.set_wb_temp(mn); time.sleep(2)
        print(f"  Cool ({mx}K - blue sky)...")
        uvc.set_wb_temp(mx); time.sleep(2)
        print(f"  Neutral ({orig}K)...")
        uvc.set_wb_temp(orig); time.sleep(0.5)
        uvc.set_wb_auto(True)
        print("  Auto WB restored")

    # ── Hue Rotation ─────────────────────────────────────────────
    h = uvc.get_hue()
    if h and h["current"] is not None:
        orig = h["current"]
        mn, mx = h.get("min", -180), h.get("max", 180)
        print(f"\n[HUE] Color rotation sweep")
        for v in range(mn, mx, max(1, (mx - mn) // 20)):
            uvc.set_hue(v)
            time.sleep(0.1)
        uvc.set_hue(orig)
        print(f"  Restored to {orig}")

    # ── Zoom ─────────────────────────────────────────────────────
    z = uvc.get_zoom()
    if z and z["current"] is not None:
        orig = z["current"]
        mn, mx = z.get("min", 100), z.get("max", 400)
        print(f"\n[ZOOM] Digital zoom {mn} -> {mx}")
        for v in range(mn, mx, max(1, (mx - mn) // 15)):
            uvc.set_zoom(v)
            time.sleep(0.2)
        uvc.set_zoom(mx); time.sleep(1)
        uvc.set_zoom(orig)
        print(f"  Restored to {orig}")

    # ── Focus ────────────────────────────────────────────────────
    f = uvc.get_focus()
    if f and f["current"] is not None:
        orig = f["current"]
        mn, mx = f.get("min", 0), f.get("max", 255)
        print(f"\n[FOCUS] Manual focus sweep")
        uvc.set_autofocus(False)
        time.sleep(0.3)
        for v in range(mn, mx, max(1, (mx - mn) // 10)):
            uvc.set_focus(v)
            time.sleep(0.3)
        uvc.set_autofocus(True)
        print("  Autofocus restored")

    # ── Resolution Switch ────────────────────────────────────────
    print(f"\n[RESOLUTION] Switching...")
    for w, h in [(3840, 2160), (1920, 1080), (1280, 720)]:
        if avf.set_resolution(w, h):
            print(f"  {w}x{h} -> Active: {avf.get_resolution()}")
            time.sleep(1.5)

    # ── LED + Brightness Combo ───────────────────────────────────
    b = uvc.get_brightness()
    if b and b["current"] is not None:
        print(f"\n[COMBO] LED synced with brightness strobe!")
        orig = b["current"]
        mn, mx = b.get("min", 0), b.get("max", 255)
        for _ in range(6):
            hid_dev.set_led(mute=True)
            uvc.set_brightness(mx)
            time.sleep(0.3)
            hid_dev.set_led()
            uvc.set_brightness(mn)
            time.sleep(0.3)
        uvc.set_brightness(orig)

    hid_dev.set_led()
    print("\n" + "=" * 70)
    print("  DEMO COMPLETE")
    print("=" * 70)


# ═══════════════════════════════════════════════════════════════════
# INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════

def interactive(hid_dev, uvc, avf):
    avf.start_session()
    time.sleep(1)

    # Read initial UVC state
    uvc_available = uvc.dev is not None
    if uvc_available:
        print("\n  Current UVC state:")
        uvc.dump_all()

    while True:
        print("\n" + "─" * 60)
        print("  MX BRIO CONTROL PANEL")
        print("─" * 60)
        print("  LED:")
        print("    1  LED ON         2  LED OFF")
        print("    3  SOS morse      4  Rapid blink")
        if uvc_available:
            print("  Image (VISIBLE in camera feed):")
            print("    5  Brightness UP    6  Brightness DOWN")
            print("    7  Contrast UP      8  Contrast DOWN")
            print("    9  Saturation OFF  10  Saturation MAX")
            print("   11  WB Warm (3000K) 12  WB Cool (6500K)")
            print("   13  WB Auto        14  Hue rotate")
            print("   15  Sharpness MIN  16  Sharpness MAX")
            print("  Lens:")
            print("   17  Zoom IN        18  Zoom OUT")
            print("   19  Focus NEAR     20  Focus FAR")
            print("   21  Autofocus ON   22  Autofocus OFF")
            print("  Exposure:")
            print("   23  Exposure LONG  24  Exposure SHORT")
            print("   25  Auto exposure")
        print("  Format:")
        print("   26  720p   27  1080p   28  4K")
        print("  Other:")
        print("   29  Dump all UVC     30  Run full demo")
        print("   31  Reset all defaults")
        print("    q  Quit")
        print("─" * 60)

        try:
            c = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        try:
            if c == 'q':
                break
            elif c == '1': hid_dev.set_led(mute=True); print("  ON")
            elif c == '2': hid_dev.set_led(); print("  OFF")
            elif c == '3': hid_dev.blink_sos(); print("  Done")
            elif c == '4': hid_dev.blink(5, 3); print("  Done")
            elif c == '5':
                b = uvc.get_brightness()
                if b["current"] is not None:
                    new = min(b["current"] + max(1, (b["max"] - b["min"]) // 10), b["max"])
                    uvc.set_brightness(new); print(f"  Brightness: {new}")
            elif c == '6':
                b = uvc.get_brightness()
                if b["current"] is not None:
                    new = max(b["current"] - max(1, (b["max"] - b["min"]) // 10), b["min"])
                    uvc.set_brightness(new); print(f"  Brightness: {new}")
            elif c == '7':
                v = uvc.get_contrast()
                if v["current"] is not None:
                    new = min(v["current"] + max(1, (v["max"] - v["min"]) // 10), v["max"])
                    uvc.set_contrast(new); print(f"  Contrast: {new}")
            elif c == '8':
                v = uvc.get_contrast()
                if v["current"] is not None:
                    new = max(v["current"] - max(1, (v["max"] - v["min"]) // 10), v["min"])
                    uvc.set_contrast(new); print(f"  Contrast: {new}")
            elif c == '9':
                s = uvc.get_saturation()
                if s["min"] is not None:
                    uvc.set_saturation(s["min"]); print(f"  Saturation: {s['min']} (B&W)")
            elif c == '10':
                s = uvc.get_saturation()
                if s["max"] is not None:
                    uvc.set_saturation(s["max"]); print(f"  Saturation: {s['max']} (vivid)")
            elif c == '11':
                uvc.set_wb_auto(False); time.sleep(0.1)
                uvc.set_wb_temp(3000); print("  WB: 3000K (warm)")
            elif c == '12':
                uvc.set_wb_auto(False); time.sleep(0.1)
                uvc.set_wb_temp(6500); print("  WB: 6500K (cool)")
            elif c == '13':
                uvc.set_wb_auto(True); print("  WB: Auto")
            elif c == '14':
                h = uvc.get_hue()
                if h["current"] is not None:
                    mn, mx = h["min"], h["max"]
                    print("  Rotating hue...")
                    for v in range(mn, mx, max(1, (mx - mn) // 20)):
                        uvc.set_hue(v); time.sleep(0.08)
                    uvc.set_hue(h.get("default", 0))
                    print("  Done")
            elif c == '15':
                s = uvc.get_sharpness()
                if s["min"] is not None:
                    uvc.set_sharpness(s["min"]); print(f"  Sharpness: {s['min']} (soft)")
            elif c == '16':
                s = uvc.get_sharpness()
                if s["max"] is not None:
                    uvc.set_sharpness(s["max"]); print(f"  Sharpness: {s['max']} (crisp)")
            elif c == '17':
                z = uvc.get_zoom()
                if z["current"] is not None:
                    step = max(1, (z["max"] - z["min"]) // 10)
                    new = min(z["current"] + step, z["max"])
                    uvc.set_zoom(new); print(f"  Zoom: {new}")
            elif c == '18':
                z = uvc.get_zoom()
                if z["current"] is not None:
                    step = max(1, (z["max"] - z["min"]) // 10)
                    new = max(z["current"] - step, z["min"])
                    uvc.set_zoom(new); print(f"  Zoom: {new}")
            elif c == '19':
                uvc.set_autofocus(False); time.sleep(0.1)
                f = uvc.get_focus()
                if f["min"] is not None:
                    uvc.set_focus(f["min"]); print(f"  Focus: NEAR ({f['min']})")
            elif c == '20':
                uvc.set_autofocus(False); time.sleep(0.1)
                f = uvc.get_focus()
                if f["max"] is not None:
                    uvc.set_focus(f["max"]); print(f"  Focus: FAR ({f['max']})")
            elif c == '21':
                uvc.set_autofocus(True); print("  Autofocus ON")
            elif c == '22':
                uvc.set_autofocus(False); print("  Autofocus OFF (locked)")
            elif c == '23':
                uvc.set_auto_exposure(False); time.sleep(0.1)
                e = uvc.get_exposure()
                if e["max"] is not None:
                    uvc.set_exposure(e["max"]); print(f"  Exposure: {e['max']} (long/bright)")
            elif c == '24':
                uvc.set_auto_exposure(False); time.sleep(0.1)
                e = uvc.get_exposure()
                if e["min"] is not None:
                    uvc.set_exposure(e["min"]); print(f"  Exposure: {e['min']} (short/dark)")
            elif c == '25':
                uvc.set_auto_exposure(True); print("  Auto exposure ON")
            elif c == '26': avf.set_resolution(1280, 720); print(f"  {avf.get_resolution()}")
            elif c == '27': avf.set_resolution(1920, 1080); print(f"  {avf.get_resolution()}")
            elif c == '28': avf.set_resolution(3840, 2160); print(f"  {avf.get_resolution()}")
            elif c == '29':
                print("\n  UVC Control Dump:")
                uvc.dump_all()
            elif c == '30':
                run_demo(hid_dev, uvc, avf)
            elif c == '31':
                uvc.set_wb_auto(True)
                uvc.set_autofocus(True)
                uvc.set_auto_exposure(True)
                for name in ['brightness', 'contrast', 'saturation', 'hue',
                             'sharpness', 'gamma', 'gain']:
                    info = uvc._get(name)
                    if info.get("default") is not None:
                        uvc._set(name, info["default"])
                hid_dev.set_led()
                print("  All controls reset to defaults")
            else:
                print("  Invalid choice")
        except Exception as e:
            print(f"  Error: {e}")


def main():
    mode = "--demo" if "--demo" in sys.argv else "interactive"

    print("=" * 70)
    print("  LOGITECH MX BRIO - HARDWARE CONTROL PANEL")
    print("  046D:0944 | Sony IMX415 | USB 3.0 SuperSpeed")
    print("=" * 70)

    hid_dev = BrioHID()
    hid_dev.open()
    print(f"  HID:    Connected (firmware {hid_dev.firmware_version()})")

    uvc = BrioUVC()
    if uvc.open():
        print(f"  UVC:    Connected (IOKit, no sudo)")
    else:
        print(f"  UVC:    Not available (limited controls)")

    avf = BrioAVF()
    if avf.find():
        print(f"  Camera: {avf.device.localizedName()}")
    else:
        print(f"  Camera: Not found via AVFoundation")

    try:
        if mode == "--demo":
            avf.start_session()
            time.sleep(1)
            run_demo(hid_dev, uvc, avf)
        else:
            interactive(hid_dev, uvc, avf)
    finally:
        hid_dev.set_led()
        avf.stop_session()
        uvc.close()
        hid_dev.close()
        print("\n  Cleaned up. Goodbye.")


if __name__ == "__main__":
    main()
