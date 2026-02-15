#!/usr/bin/env python3
"""
MX Brio Quick Scan - Fast function code scan + UVC camera control query.
"""

import sys
import time
import json
import subprocess

try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

VENDOR_ID = 0x046D
PRODUCT_ID = 0x0944
REPORT_ID = 0x9A
REPORT_SIZE = 32


def open_device():
    devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not devices:
        sys.exit("No MX Brio found!")
    dev = hid.device()
    dev.open_path(devices[0]["path"])
    return dev


def query_feature(dev, func, sub=0x00, param=0x00):
    payload = [REPORT_ID, func, sub, param] + [0x00] * (REPORT_SIZE - 4)
    dev.send_feature_report(payload)
    time.sleep(0.015)
    return bytes(dev.get_feature_report(REPORT_ID, 64))


def scan_functions(dev):
    """Scan all 256 function codes quickly."""
    print("=" * 70)
    print("FUNCTION CODE SCAN (0x00-0xFF) on Feature Report 0x9A")
    print("=" * 70)

    baseline = query_feature(dev, 0x00)
    unique = {}

    for func in range(256):
        try:
            resp = query_feature(dev, func)
            if resp != baseline:
                unique[func] = resp
        except Exception:
            pass

    print(f"\n  Baseline (func 0x00): {baseline[:20].hex()}")
    print(f"  Unique responses found: {len(unique)}\n")

    for func, resp in sorted(unique.items()):
        # Show differences from baseline
        diffs = []
        for i in range(min(len(baseline), len(resp))):
            if baseline[i] != resp[i]:
                diffs.append((i, baseline[i], resp[i]))
        print(f"  Func 0x{func:02X} ({func:3d}): {resp[:20].hex()}")
        print(f"    Changed bytes: {[(f'[{i}] {old:#x}->{new:#x}' ) for i, old, new in diffs]}")

    return unique


def probe_uvc_controls(dev):
    """
    Try to read UVC camera controls using macOS AVFoundation via ffmpeg.
    Also try the vendor output reports with specific Logitech UVC XU patterns.
    """
    print("\n" + "=" * 70)
    print("UVC CAMERA CONTROL PROBE")
    print("=" * 70)

    # Check if ffmpeg is available for camera query
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=5
        )
        output = result.stderr
        print("\n  AVFoundation devices:")
        for line in output.split("\n"):
            if "video" in line.lower() or "brio" in line.lower() or "[" in line:
                print(f"    {line.strip()}")
    except FileNotFoundError:
        print("  ffmpeg not found - skipping AVFoundation probe")
    except Exception as e:
        print(f"  ffmpeg probe failed: {e}")


def read_all_input_reports_fast(dev, duration=5):
    """Fast poll for any input reports."""
    print(f"\n" + "=" * 70)
    print(f"FAST INPUT REPORT MONITOR ({duration}s)")
    print(">>> Interact with camera: buttons, privacy shutter, cover lens <<<")
    print("=" * 70)

    dev.set_nonblocking(True)
    start = time.time()
    reports = []

    while time.time() - start < duration:
        data = dev.read(64)
        if data:
            elapsed = time.time() - start
            report_id = data[0]
            raw = bytes(data)
            reports.append((elapsed, report_id, raw))
            print(f"  [{elapsed:5.2f}s] Report 0x{report_id:02X} ({len(data)} bytes): {raw.hex()}")

            # Decode known reports
            if report_id == 0x08:
                mute = data[1] & 0x01
                hook = (data[1] >> 1) & 0x01
                print(f"           Phone Mute={mute}, Hook Switch={hook}")
            elif report_id == 0x40:
                bit0 = data[1] & 0x01
                bit1 = (data[1] >> 1) & 0x01
                print(f"           Status bit0={bit0}, bit1={bit1}")
            elif report_id == 0x55:
                print(f"           Logitech FFA1 data: {list(data[1:7])}")
            elif report_id == 0x0A:
                print(f"           Vendor FF01 blob: {list(data[1:8])}...")
            elif report_id == 0x01:
                print(f"           Button value: {data[1]}")

        time.sleep(0.002)

    dev.set_nonblocking(False)
    print(f"\n  Total reports: {len(reports)}")
    return reports


def led_demo(dev):
    """Quick LED control demo."""
    print("\n" + "=" * 70)
    print("LED CONTROL DEMO")
    print("=" * 70)

    # SOS pattern in morse code: ... --- ...
    morse_sos = [
        # S: short short short
        (0.15, True), (0.1, False),
        (0.15, True), (0.1, False),
        (0.15, True), (0.3, False),
        # O: long long long
        (0.4, True), (0.1, False),
        (0.4, True), (0.1, False),
        (0.4, True), (0.3, False),
        # S: short short short
        (0.15, True), (0.1, False),
        (0.15, True), (0.1, False),
        (0.15, True), (0.3, False),
    ]

    print("  Sending SOS in morse code via Mute LED...")
    for duration, state in morse_sos:
        dev.write([0x08, 0x01 if state else 0x00])
        time.sleep(duration)

    # Also try bit 1 (Line indicator)
    print("  Testing Line indicator (bit 1)...")
    for i in range(3):
        dev.write([0x08, 0x02])
        time.sleep(0.3)
        dev.write([0x08, 0x00])
        time.sleep(0.3)

    # Both together
    print("  Both LEDs together...")
    for i in range(3):
        dev.write([0x08, 0x03])
        time.sleep(0.3)
        dev.write([0x08, 0x00])
        time.sleep(0.3)

    dev.write([0x08, 0x00])
    print("  LED demo complete.")


def write_results(unique_funcs):
    """Save scan results to JSON."""
    output = {
        "device": "Logitech MX Brio",
        "vid_pid": "046D:0944",
        "serial": "2527LVV0U2L8",
        "sensor": "Sony IMX415 (1/2.8 inch)",
        "usb_interfaces": {
            "0": "UVC Video Control",
            "1": "UVC Video Streaming",
            "2": "HID (vendor controls + LED + telephony)",
            "3": "Vendor Specific (0xFF/0xFF) - proprietary",
            "4": "USB Audio Control",
            "5": "USB Audio Streaming",
        },
        "hid_feature_report_0x9A": {
            "baseline": "9a 00 00 01 01 (firmware 1.1?)",
            "responsive_functions": {
                f"0x{func:02X}": data.hex() for func, data in unique_funcs.items()
            },
        },
        "controllable": {
            "mute_led": "Report 0x08, bit 0 (OUTPUT)",
            "line_indicator": "Report 0x08, bit 1 (OUTPUT)",
            "vendor_output_41": "Report 0x41, 2 bytes (OUTPUT, function unknown)",
            "vendor_output_44": "Report 0x44, 4 bytes (OUTPUT, function unknown)",
        },
        "readable": {
            "phone_mute_button": "Report 0x08, bit 0 (INPUT)",
            "hook_switch": "Report 0x08, bit 1 (INPUT)",
            "vendor_status": "Report 0x40, 2 bits (INPUT)",
            "vendor_data": "Reports 0x42-0x47 (INPUT, various sizes)",
            "vendor_blob": "Report 0x0A, 31 bytes (INPUT)",
            "logitech_data": "Report 0x55, 6 bytes (INPUT)",
            "button": "Report 0x01, 1 byte (INPUT)",
        },
    }

    with open("/Users/mouadtiahi/re-zero/hardware/webcam/mx_brio_scan_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\n  Results saved to mx_brio_scan_results.json")


def main():
    print("=" * 70)
    print("  LOGITECH MX BRIO - QUICK SCAN + LED DEMO")
    print("  046D:0944 | Sony IMX415 | USB 3.0")
    print("=" * 70)

    dev = open_device()
    print("  Device opened.\n")

    # 1. Scan all function codes
    unique = scan_functions(dev)

    # 2. Probe UVC
    probe_uvc_controls(dev)

    # 3. LED demo
    led_demo(dev)

    # 4. Monitor input reports
    read_all_input_reports_fast(dev, duration=5)

    # 5. Save results
    write_results(unique)

    dev.close()
    print("\n  Done.")


if __name__ == "__main__":
    main()
