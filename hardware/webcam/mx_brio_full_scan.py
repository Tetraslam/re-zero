#!/usr/bin/env python3
"""
MX Brio Full Register Scan - Systematically probe all function codes
on the HID++ feature report and map the device's internal registers.
"""

import sys
import time
import json

try:
    import hid
except ImportError:
    print("ERROR: pip install hidapi")
    sys.exit(1)

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
    """Send a feature report query and read the response."""
    payload = [REPORT_ID, func, sub, param] + [0x00] * (REPORT_SIZE - 4)
    dev.send_feature_report(payload)
    time.sleep(0.02)
    return dev.get_feature_report(REPORT_ID, 64)


def scan_all_functions(dev):
    """Scan all 256 function codes and find which ones return unique data."""
    print("=" * 70)
    print("FULL FUNCTION CODE SCAN (0x00 - 0xFF)")
    print("=" * 70)

    baseline = bytes(query_feature(dev, 0x00))
    unique_responses = {}

    for func in range(256):
        try:
            resp = bytes(query_feature(dev, func))
            # Check if response differs from baseline or has non-zero data beyond header
            if resp != baseline:
                unique_responses[func] = resp
                data_preview = resp[:16].hex()
                print(f"  [0x{func:02X}] UNIQUE: {data_preview}...")
        except Exception:
            pass

    print(f"\n  Unique responses: {len(unique_responses)} out of 256 function codes")
    print(f"  Baseline: {baseline[:16].hex()}")

    return unique_responses


def deep_scan_function(dev, func):
    """For a function that returns data, scan all sub-function codes."""
    print(f"\n  Deep scanning function 0x{func:02X}...")
    results = {}
    baseline = bytes(query_feature(dev, func, 0x00))

    for sub in range(256):
        try:
            resp = bytes(query_feature(dev, func, sub))
            if resp != baseline or sub == 0:
                results[sub] = resp
                if resp != baseline:
                    print(f"    Sub 0x{sub:02X}: {resp[:16].hex()}")
        except Exception:
            pass

    return results


def scan_function_with_params(dev, func, sub=0):
    """Scan parameter byte for a given function+sub."""
    print(f"\n  Param scan for func=0x{func:02X}, sub=0x{sub:02X}...")
    results = {}
    baseline = bytes(query_feature(dev, func, sub, 0x00))

    for param in range(256):
        try:
            resp = bytes(query_feature(dev, func, sub, param))
            if resp != baseline or param == 0:
                results[param] = resp
                if resp != baseline:
                    print(f"    Param 0x{param:02X}: {resp[:16].hex()}")
        except Exception:
            pass

    return results


def extract_readable_strings(data):
    """Try to find ASCII strings in response data."""
    result = []
    current = ""
    for b in data:
        if 32 <= b < 127:
            current += chr(b)
        else:
            if len(current) >= 3:
                result.append(current)
            current = ""
    if len(current) >= 3:
        result.append(current)
    return result


def monitor_changes(dev, duration=10):
    """
    Continuously poll feature report 0x9A and report any changes.
    This can detect state changes from camera activity.
    """
    print("\n" + "=" * 70)
    print(f"POLLING FEATURE REPORT 0x9A FOR CHANGES ({duration}s)")
    print(">>> Move the camera, cover lens, change lighting <<<")
    print("=" * 70)

    prev = bytes(dev.get_feature_report(REPORT_ID, 64))
    start = time.time()
    changes = []

    # Also poll function 0x10 which returned interesting data
    prev_f10 = bytes(query_feature(dev, 0x10))

    while time.time() - start < duration:
        try:
            curr = bytes(dev.get_feature_report(REPORT_ID, 64))
            if curr != prev:
                elapsed = time.time() - start
                changes.append((elapsed, "0x9A_default", curr))
                print(f"  [{elapsed:6.2f}s] Default changed: {curr[:16].hex()}")
                # Show which bytes changed
                diffs = [i for i in range(min(len(prev), len(curr))) if prev[i] != curr[i]]
                print(f"           Changed bytes: {diffs}")
                print(f"           Old: {[prev[i] for i in diffs]}")
                print(f"           New: {[curr[i] for i in diffs]}")
                prev = curr

            curr_f10 = bytes(query_feature(dev, 0x10))
            if curr_f10 != prev_f10:
                elapsed = time.time() - start
                changes.append((elapsed, "0x10", curr_f10))
                print(f"  [{elapsed:6.2f}s] Func 0x10 changed: {curr_f10[:16].hex()}")
                diffs = [i for i in range(min(len(prev_f10), len(curr_f10))) if prev_f10[i] != curr_f10[i]]
                print(f"           Changed bytes: {diffs}")
                print(f"           Old: {[prev_f10[i] for i in diffs]}")
                print(f"           New: {[curr_f10[i] for i in diffs]}")
                prev_f10 = curr_f10

        except Exception as e:
            print(f"  Poll error: {e}")

        time.sleep(0.1)

    print(f"\n  Total changes detected: {len(changes)}")
    return changes


def main():
    print("=" * 70)
    print("  LOGITECH MX BRIO - FULL REGISTER SCAN")
    print("=" * 70)

    dev = open_device()
    print("  Device opened.\n")

    # Phase 1: Scan all function codes
    unique = scan_all_functions(dev)

    # Phase 2: Deep scan each unique function
    all_results = {}
    for func in sorted(unique.keys()):
        sub_results = deep_scan_function(dev, func)
        all_results[func] = sub_results

        # If any sub-functions returned unique data, scan params too
        for sub, resp in sub_results.items():
            if sub != 0:  # Non-default sub
                scan_function_with_params(dev, func, sub)

    # Phase 3: Try to interpret the data
    print("\n" + "=" * 70)
    print("DATA INTERPRETATION")
    print("=" * 70)

    for func, data in unique.items():
        strings = extract_readable_strings(data)
        print(f"\n  Function 0x{func:02X}: {data[:20].hex()}")
        print(f"    Bytes 3-4 as uint16 LE: {data[3] | (data[4] << 8)}")
        print(f"    Bytes 3-4 as uint16 BE: {(data[3] << 8) | data[4]}")
        if strings:
            print(f"    ASCII strings: {strings}")
        # Try interpreting as various data types
        if len(data) >= 6:
            print(f"    Bytes 3-6: {list(data[3:7])}")

    # Phase 4: Monitor for live changes
    monitor_changes(dev, duration=10)

    dev.close()
    print("\n  Done.")


if __name__ == "__main__":
    main()
