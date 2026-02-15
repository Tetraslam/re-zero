#!/usr/bin/env python3
"""
MX Brio USB HID Probe - Read vendor data and control LED.

Device: Logitech MX Brio (046d:0944)
Interface 2: HID with vendor-specific reports and LED control.
"""

import sys
import time
import struct

try:
    import hid
except ImportError:
    print("ERROR: pip install hidapi")
    sys.exit(1)

VENDOR_ID = 0x046D
PRODUCT_ID = 0x0944

# HID Report IDs from descriptor analysis
REPORTS = {
    0x40: {"name": "Vendor_FF00_Status", "type": "input", "size": 1, "desc": "2-bit status flags"},
    0x41: {"name": "Vendor_FF00_Ctrl", "type": "output", "size": 2, "desc": "2-byte vendor control output"},
    0x42: {"name": "Vendor_FF00_Data1", "type": "input", "size": 2, "desc": "2-byte vendor data"},
    0x43: {"name": "Vendor_FF00_Data2", "type": "input", "size": 2, "desc": "2-byte vendor data"},
    0x44: {"name": "Vendor_FF00_Ctrl2", "type": "output", "size": 4, "desc": "4-byte vendor control output"},
    0x45: {"name": "Vendor_FF00_Data3", "type": "input", "size": 1, "desc": "1-byte vendor data"},
    0x46: {"name": "Vendor_FF00_Data4", "type": "input", "size": 2, "desc": "2-byte vendor data"},
    0x47: {"name": "Vendor_FF00_Data5", "type": "input", "size": 2, "desc": "2-byte vendor data"},
    0x0A: {"name": "Vendor_FF01_Blob", "type": "input", "size": 31, "desc": "31-byte vendor data blob"},
    0x01: {"name": "Vendor_FF02_Button", "type": "input", "size": 1, "desc": "Button state"},
    0x55: {"name": "Logi_FFA1_Data", "type": "input", "size": 6, "desc": "6-byte Logitech proprietary"},
    0x9A: {"name": "Logi_FF99_Feature", "type": "feature", "size": 31, "desc": "31-byte Logitech feature r/w"},
    0x08: {"name": "Telephony_LED", "type": "both", "size": 1, "desc": "Phone Mute + Hook Switch input / Mute LED + Line output"},
}


def enumerate_devices():
    """List all Logitech HID devices."""
    print("=" * 70)
    print("ENUMERATING LOGITECH HID DEVICES")
    print("=" * 70)
    devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not devices:
        print(f"No devices found with VID=0x{VENDOR_ID:04X} PID=0x{PRODUCT_ID:04X}")
        print("\nTrying broader Logitech search (VID=0x046D)...")
        devices = hid.enumerate(VENDOR_ID)
        if not devices:
            print("No Logitech HID devices found at all.")
            return []

    for i, dev in enumerate(devices):
        print(f"\n--- Device {i} ---")
        print(f"  Path:          {dev['path']}")
        print(f"  VID:PID:       0x{dev['vendor_id']:04X}:0x{dev['product_id']:04X}")
        print(f"  Serial:        {dev['serial_number']}")
        print(f"  Product:       {dev['product_string']}")
        print(f"  Manufacturer:  {dev['manufacturer_string']}")
        print(f"  Interface:     {dev['interface_number']}")
        print(f"  Usage Page:    0x{dev['usage_page']:04X}")
        print(f"  Usage:         0x{dev['usage']:04X}")
    return devices


def read_feature_reports(device):
    """Try to read all feature reports."""
    print("\n" + "=" * 70)
    print("READING FEATURE REPORTS")
    print("=" * 70)

    # Feature report 0x9A (154) - Logitech FF99 proprietary, 31 bytes
    for report_id in [0x9A]:
        try:
            data = device.get_feature_report(report_id, 32)
            print(f"\n  Report 0x{report_id:02X} ({report_id}): {REPORTS.get(report_id, {}).get('desc', 'unknown')}")
            print(f"    Raw ({len(data)} bytes): {data.hex()}")
            print(f"    Bytes: {list(data)}")
        except Exception as e:
            print(f"\n  Report 0x{report_id:02X}: FAILED - {e}")


def read_input_reports(device, duration=5):
    """Read incoming HID input reports for a given duration."""
    print("\n" + "=" * 70)
    print(f"READING INPUT REPORTS FOR {duration} SECONDS")
    print("(Try pressing the mute button on the webcam, or moving it)")
    print("=" * 70)

    device.set_nonblocking(True)
    start = time.time()
    report_counts = {}

    while time.time() - start < duration:
        data = device.read(64)
        if data:
            report_id = data[0]
            report_counts[report_id] = report_counts.get(report_id, 0) + 1
            info = REPORTS.get(report_id, {"name": "Unknown", "desc": "?"})
            elapsed = time.time() - start
            print(f"\n  [{elapsed:6.2f}s] Report 0x{report_id:02X} ({info['name']}):")
            print(f"    Raw: {bytes(data).hex()}")
            print(f"    Dec: {list(data)}")
        time.sleep(0.01)

    print(f"\n  Reports received in {duration}s:")
    if report_counts:
        for rid, count in sorted(report_counts.items()):
            info = REPORTS.get(rid, {"name": "Unknown"})
            print(f"    0x{rid:02X} ({info['name']}): {count} reports")
    else:
        print("    None received (device idle)")


def try_vendor_feature_reads(device):
    """Brute-force read all possible feature report IDs to find hidden data."""
    print("\n" + "=" * 70)
    print("PROBING ALL FEATURE REPORT IDS (0x01-0xFF)")
    print("=" * 70)

    found = []
    for report_id in range(1, 256):
        try:
            data = device.get_feature_report(report_id, 64)
            if data and len(data) > 1:
                found.append((report_id, data))
                info = REPORTS.get(report_id, {"name": "Unknown", "desc": "?"})
                print(f"  0x{report_id:02X} ({report_id:3d}) [{info['name']:25s}]: {bytes(data).hex()}")
        except Exception:
            pass

    print(f"\n  Total readable feature reports: {len(found)}")
    return found


def toggle_led(device, state):
    """
    Toggle the Mute LED via Report ID 0x08.
    Report 0x08 output: bit 0 = Mute LED, bit 1 = Line indicator.
    """
    value = 0x01 if state else 0x00  # bit 0 = Mute LED
    data = [0x08, value]  # Report ID + 1 byte
    print(f"\n  Sending LED {'ON' if state else 'OFF'}: report=0x08, data={[hex(b) for b in data]}")
    try:
        result = device.write(data)
        print(f"  Write result: {result} bytes written")
        return result
    except Exception as e:
        print(f"  Write FAILED: {e}")
        return -1


def blink_led(device, count=5, interval=0.5):
    """Blink the mute LED on and off."""
    print("\n" + "=" * 70)
    print(f"BLINKING MUTE LED {count} TIMES")
    print("=" * 70)
    for i in range(count):
        print(f"  Blink {i+1}/{count} - ON")
        toggle_led(device, True)
        time.sleep(interval)
        print(f"  Blink {i+1}/{count} - OFF")
        toggle_led(device, False)
        time.sleep(interval)


def try_vendor_writes(device):
    """
    Try writing to vendor output reports to discover functionality.
    Report 0x41 (Vendor FF00): 2 bytes output
    Report 0x44 (Vendor FF00): 4 bytes output
    """
    print("\n" + "=" * 70)
    print("PROBING VENDOR OUTPUT REPORTS (READ-ONLY SAFE QUERIES)")
    print("=" * 70)

    # Try reading Report 0x41 as feature first
    for report_id in [0x41, 0x44]:
        try:
            data = device.get_feature_report(report_id, 32)
            print(f"  Feature read 0x{report_id:02X}: {bytes(data).hex()}")
        except Exception as e:
            print(f"  Feature read 0x{report_id:02X}: {e}")


def main():
    print("=" * 70)
    print("  LOGITECH MX BRIO (046D:0944) - HID INTERFACE PROBE")
    print("=" * 70)

    # Step 1: Enumerate
    devices = enumerate_devices()
    if not devices:
        return

    # Filter to MX Brio devices only
    brio_devices = [d for d in devices if d["product_id"] == PRODUCT_ID]
    if not brio_devices:
        print("\nNo MX Brio HID interfaces found.")
        return

    # Try each HID interface path
    for dev_info in brio_devices:
        path = dev_info["path"]
        usage_page = dev_info["usage_page"]
        print(f"\n{'#' * 70}")
        print(f"# Opening: Interface {dev_info['interface_number']}, "
              f"UsagePage=0x{usage_page:04X}, Usage=0x{dev_info['usage']:04X}")
        print(f"# Path: {path}")
        print(f"{'#' * 70}")

        try:
            device = hid.device()
            device.open_path(path)
            print(f"  Opened successfully!")

            # Read feature reports
            read_feature_reports(device)

            # Probe all feature report IDs
            try_vendor_feature_reads(device)

            # Try vendor output probing
            try_vendor_writes(device)

            # Read input reports
            read_input_reports(device, duration=3)

            # Try LED blink
            blink_led(device, count=3, interval=0.4)

            device.close()
            print(f"\n  Device closed.")

        except Exception as e:
            print(f"  FAILED to open: {e}")
            print(f"  (macOS may block HID access - try running with sudo)")

    print("\n" + "=" * 70)
    print("PROBE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
