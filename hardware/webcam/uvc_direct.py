#!/usr/bin/env python3
"""
Direct UVC control via libusb. Requires sudo on macOS.
Detaches kernel driver, reads/sets UVC controls, re-attaches.
"""
import sys
import struct
import time

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("pip install pyusb")

VID, PID = 0x046D, 0x0944

dev = usb.core.find(idVendor=VID, idProduct=PID)
if not dev:
    sys.exit("MX Brio not found!")

print(f"Device: {dev.product} ({dev.serial_number})")

# Detach kernel driver from Video Control interface
reattach = False
try:
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
        reattach = True
        print("Kernel driver detached from interface 0")
except usb.core.USBError as e:
    print(f"Cannot detach kernel driver: {e}")
    print("Run with: sudo python3 uvc_direct.py")
    sys.exit(1)


def uvc_get(unit, sel, req, length):
    return bytes(dev.ctrl_transfer(0xA1, req, sel << 8, (unit << 8) | 0, length, 1000))


def uvc_set(unit, sel, data):
    dev.ctrl_transfer(0x21, 0x01, sel << 8, (unit << 8) | 0, data, 1000)


def read_ctrl(unit, sel, length=2, signed=True):
    fmt = {1: ('<b', '<B'), 2: ('<h', '<H'), 4: ('<i', '<I')}[length]
    f = fmt[0] if signed else fmt[1]
    result = {}
    for req, name in [(0x81, 'cur'), (0x82, 'min'), (0x83, 'max'), (0x85, 'def')]:
        try:
            data = uvc_get(unit, sel, req, length)
            result[name] = struct.unpack(f, data)[0]
        except:
            result[name] = None
    return result


def write_ctrl(unit, sel, val, length=2):
    fmt = {1: '<b', 2: '<h', 4: '<i'}[length]
    uvc_set(unit, sel, struct.pack(fmt, val))


# Auto-detect unit IDs by probing
print("\nProbing all unit IDs (1-10) for UVC controls...")

PU_CONTROLS = [
    ("Backlight Comp", 0x01, 2), ("Brightness", 0x02, 2),
    ("Contrast", 0x03, 2), ("Gain", 0x04, 2),
    ("Power Line Freq", 0x05, 1), ("Hue", 0x06, 2),
    ("Saturation", 0x07, 2), ("Sharpness", 0x08, 2),
    ("Gamma", 0x09, 2), ("WB Temperature", 0x0A, 2),
    ("WB Auto", 0x0B, 1),
]

CT_CONTROLS = [
    ("AE Mode", 0x02, 1), ("Exposure Abs", 0x04, 4),
    ("Focus Abs", 0x06, 2), ("Focus Auto", 0x08, 1),
    ("Zoom Abs", 0x0B, 2),
]

pu_unit = None
ct_unit = None

for uid in range(1, 11):
    # Check for PU controls
    r = read_ctrl(uid, 0x02, 2)  # Brightness
    if r['cur'] is not None:
        print(f"\n  Found Processing Unit at ID {uid}:")
        pu_unit = uid
        for name, sel, length in PU_CONTROLS:
            r = read_ctrl(uid, sel, length)
            if r['cur'] is not None:
                print(f"    {name:20s}: cur={r['cur']:6}  min={r['min']}  max={r['max']}  def={r['def']}")

    # Check for CT controls
    r = read_ctrl(uid, 0x04, 4)  # Exposure
    if r['cur'] is not None and ct_unit is None:
        print(f"\n  Found Camera Terminal at ID {uid}:")
        ct_unit = uid
        for name, sel, length in CT_CONTROLS:
            r = read_ctrl(uid, sel, length)
            if r['cur'] is not None:
                print(f"    {name:20s}: cur={r['cur']:6}  min={r['min']}  max={r['max']}  def={r['def']}")

if pu_unit is None and ct_unit is None:
    print("  No UVC controls found at any unit ID!")
else:
    # Demo: sweep brightness
    if pu_unit:
        b = read_ctrl(pu_unit, 0x02, 2)
        if b['cur'] is not None and b['min'] is not None and b['max'] is not None:
            orig = b['cur']
            print(f"\n--- BRIGHTNESS DEMO ---")
            print(f"  Sweeping {b['min']} -> {b['max']} (current: {orig})")
            step = max(1, (b['max'] - b['min']) // 20)
            for v in range(b['min'], b['max'] + 1, step):
                write_ctrl(pu_unit, 0x02, v)
                time.sleep(0.1)
            time.sleep(0.5)
            for v in range(b['max'], b['min'] - 1, -step):
                write_ctrl(pu_unit, 0x02, v)
                time.sleep(0.1)
            write_ctrl(pu_unit, 0x02, orig)
            print(f"  Restored to {orig}")

        # Saturation B&W
        s = read_ctrl(pu_unit, 0x07, 2)
        if s['cur'] is not None:
            orig_s = s['cur']
            print(f"\n--- SATURATION DEMO ---")
            print(f"  Setting B&W (saturation = {s['min']})...")
            write_ctrl(pu_unit, 0x07, s['min'])
            time.sleep(2)
            print(f"  Max saturation ({s['max']})...")
            write_ctrl(pu_unit, 0x07, s['max'])
            time.sleep(2)
            write_ctrl(pu_unit, 0x07, orig_s)
            print(f"  Restored to {orig_s}")

# Re-attach kernel driver
if reattach:
    print("\nRe-attaching kernel driver...")
    try:
        dev.attach_kernel_driver(0)
        print("  Done! Camera should be back in apps.")
    except:
        print("  Re-attach failed. Unplug and replug the camera.")

print("\nComplete.")
