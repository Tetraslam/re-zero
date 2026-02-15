#!/usr/bin/env python3
"""
MX Brio Deep Probe - Logitech HID++ protocol & vendor feature exploration.

Attempts to communicate using Logitech's HID++ 2.0 protocol and explores
all vendor-specific feature reports to extract device information.
"""

import sys
import time

try:
    import hid
except ImportError:
    print("ERROR: pip install hidapi")
    sys.exit(1)

VENDOR_ID = 0x046D
PRODUCT_ID = 0x0944


def open_device():
    """Open the MX Brio HID device."""
    devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not devices:
        print("No MX Brio found!")
        sys.exit(1)
    dev = hid.device()
    dev.open_path(devices[0]["path"])
    return dev


def read_feature_0x9A_variants(dev):
    """
    Probe Feature Report 0x9A with different write payloads.

    The 0x9A report (Vendor 0xFF99) is read/write (Feature type).
    We can write different "query" bytes and read the response.
    This is likely a Logitech device info / configuration register.
    """
    print("=" * 70)
    print("PROBING FEATURE REPORT 0x9A (Logitech FF99 Protocol)")
    print("=" * 70)

    # First, read the default state
    try:
        data = dev.get_feature_report(0x9A, 64)
        print(f"\n  Default read: {bytes(data).hex()}")
        print(f"  Decoded:      {list(data[:10])}...")
    except Exception as e:
        print(f"  Default read failed: {e}")

    # Try sending different function codes in the feature report
    # Format: [report_id, function_code, sub_function, params...]
    queries = [
        # Query device info / firmware version patterns
        ([0x9A, 0x00, 0x00, 0x00], "Query: null"),
        ([0x9A, 0x01, 0x00, 0x00], "Query: func 0x01"),
        ([0x9A, 0x02, 0x00, 0x00], "Query: func 0x02"),
        ([0x9A, 0x03, 0x00, 0x00], "Query: func 0x03"),
        ([0x9A, 0x10, 0x00, 0x00], "Query: func 0x10"),
        ([0x9A, 0x11, 0x00, 0x00], "Query: func 0x11"),
        ([0x9A, 0x20, 0x00, 0x00], "Query: func 0x20"),
        ([0x9A, 0xFF, 0x00, 0x00], "Query: func 0xFF"),
        # Try reading different "register" addresses
        ([0x9A, 0x00, 0x01, 0x00], "Register 0x01"),
        ([0x9A, 0x00, 0x02, 0x00], "Register 0x02"),
        ([0x9A, 0x00, 0x03, 0x00], "Register 0x03"),
        ([0x9A, 0x00, 0x10, 0x00], "Register 0x10"),
        ([0x9A, 0x00, 0x20, 0x00], "Register 0x20"),
        ([0x9A, 0x00, 0xFF, 0x00], "Register 0xFF"),
    ]

    results = {}
    for query_data, desc in queries:
        try:
            # Pad to 32 bytes (report size)
            padded = query_data + [0x00] * (32 - len(query_data))
            dev.send_feature_report(padded)
            time.sleep(0.05)
            response = dev.get_feature_report(0x9A, 64)
            response_bytes = bytes(response)
            results[desc] = response_bytes
            # Only print if response differs from default or has non-zero data
            if any(b != 0 for b in response[3:]):
                print(f"\n  {desc}:")
                print(f"    Sent: {bytes(query_data).hex()}")
                print(f"    Recv: {response_bytes.hex()}")
                print(f"    Data: {list(response[:16])}")
            else:
                print(f"  {desc}: {response_bytes[:8].hex()}... (mostly zeros)")
        except Exception as e:
            print(f"  {desc}: FAILED - {e}")

    return results


def probe_output_reports(dev):
    """
    Try writing to vendor output reports (0x41 and 0x44) with query patterns.
    These are on Vendor Usage Page 0xFF00.

    Report 0x41: 2 bytes output
    Report 0x44: 4 bytes output
    """
    print("\n" + "=" * 70)
    print("PROBING VENDOR OUTPUT REPORTS (0xFF00)")
    print("=" * 70)

    # Report 0x41 - 2 byte output
    print("\n  --- Report 0x41 (2 bytes) ---")
    for val in [0x00, 0x01, 0x02, 0xFF]:
        try:
            data = [0x41, val, 0x00]
            result = dev.write(data)
            time.sleep(0.05)
            # Try to read any response
            dev.set_nonblocking(True)
            resp = dev.read(64)
            dev.set_nonblocking(False)
            resp_str = bytes(resp).hex() if resp else "no response"
            print(f"    Write [0x41, 0x{val:02X}, 0x00] -> {result} bytes, resp: {resp_str}")
        except Exception as e:
            print(f"    Write [0x41, 0x{val:02X}] FAILED: {e}")

    # Report 0x44 - 4 byte output
    print("\n  --- Report 0x44 (4 bytes) ---")
    for b1, b2, b3, b4 in [(0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0xFF, 0, 0, 0)]:
        try:
            data = [0x44, b1, b2, b3, b4]
            result = dev.write(data)
            time.sleep(0.05)
            dev.set_nonblocking(True)
            resp = dev.read(64)
            dev.set_nonblocking(False)
            resp_str = bytes(resp).hex() if resp else "no response"
            print(f"    Write [0x44, {b1:02X}, {b2:02X}, {b3:02X}, {b4:02X}] -> {result} bytes, resp: {resp_str}")
        except Exception as e:
            print(f"    Write FAILED: {e}")


def continuous_monitor(dev, duration=8):
    """
    Monitor all HID input reports for a longer period.
    User should interact with the camera (press buttons, cover lens, etc.)
    """
    print("\n" + "=" * 70)
    print(f"MONITORING ALL INPUT REPORTS FOR {duration} SECONDS")
    print(">>> INTERACT WITH THE CAMERA NOW! <<<")
    print("    - Press any button on the webcam")
    print("    - Open/close the privacy shutter")
    print("    - Cover the lens with your hand")
    print("    - Wave in front of the camera")
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
            print(f"  [{elapsed:6.2f}s] Report 0x{report_id:02X}: {raw.hex()}")
            print(f"           Decoded: {list(data)}")
        time.sleep(0.005)

    dev.set_nonblocking(False)

    print(f"\n  Total reports captured: {len(reports)}")
    if reports:
        unique_ids = set(r[1] for r in reports)
        print(f"  Unique report IDs: {[f'0x{r:02X}' for r in sorted(unique_ids)]}")
    return reports


def led_pattern_test(dev):
    """
    Test LED control with different bit patterns on Report 0x08.
    Bit 0 = Mute LED, Bit 1 = Line indicator.
    """
    print("\n" + "=" * 70)
    print("LED CONTROL TEST - REPORT 0x08")
    print("=" * 70)

    patterns = [
        (0b00, "All OFF"),
        (0b01, "Mute LED ON, Line OFF"),
        (0b10, "Mute LED OFF, Line ON"),
        (0b11, "Both ON"),
        (0b00, "All OFF"),
    ]

    for value, desc in patterns:
        try:
            result = dev.write([0x08, value])
            print(f"  {desc:30s} -> write({[0x08, value]}) = {result}")
            time.sleep(0.8)
        except Exception as e:
            print(f"  {desc:30s} -> FAILED: {e}")

    # Rapid blink pattern
    print("\n  Rapid blink test (10 cycles):")
    for i in range(10):
        dev.write([0x08, 0x01])
        time.sleep(0.1)
        dev.write([0x08, 0x00])
        time.sleep(0.1)
    print("  Done blinking!")

    # Leave LED off
    dev.write([0x08, 0x00])


def dump_device_info(dev):
    """Try to extract device firmware version and other info."""
    print("\n" + "=" * 70)
    print("DEVICE INFORMATION EXTRACTION")
    print("=" * 70)

    # The device exposes string descriptors
    try:
        mfg = dev.get_manufacturer_string()
        prod = dev.get_product_string()
        serial = dev.get_serial_number_string()
        print(f"  Manufacturer: {mfg or '(not set)'}")
        print(f"  Product:      {prod}")
        print(f"  Serial:       {serial}")
    except Exception as e:
        print(f"  String descriptors: {e}")

    # Try to extract firmware version from feature report
    # The 0x9A report data [9a, 00, 00, 01, 01, ...] might encode version
    try:
        data = dev.get_feature_report(0x9A, 64)
        print(f"\n  Feature 0x9A raw: {bytes(data[:16]).hex()}")
        # Interpret bytes 3-4 as version
        if len(data) >= 5:
            print(f"  Possible firmware version: {data[3]}.{data[4]}")
            print(f"  Byte interpretation:")
            for i, b in enumerate(data[:10]):
                print(f"    [{i:2d}] 0x{b:02X} ({b:3d}) {'=' + chr(b) if 32 <= b < 127 else ''}")
    except Exception as e:
        print(f"  Feature 0x9A: {e}")


def main():
    print("=" * 70)
    print("  LOGITECH MX BRIO - DEEP HID PROBE")
    print("  Device: 046D:0944 | Serial: 2527LVV0U2L8")
    print("=" * 70)

    dev = open_device()
    print("  Device opened.\n")

    # 1. Device info
    dump_device_info(dev)

    # 2. Feature report exploration
    read_feature_0x9A_variants(dev)

    # 3. Output report probing
    probe_output_reports(dev)

    # 4. LED test
    led_pattern_test(dev)

    # 5. Monitor for input events
    continuous_monitor(dev, duration=8)

    dev.close()
    print("\n  Device closed.")
    print("=" * 70)
    print("DEEP PROBE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
