#!/usr/bin/env python3
"""Parse the MX Brio HID Report Descriptor and display human-readable output."""

# Raw HID Report Descriptor bytes extracted from IORegistry
RAW_DESCRIPTOR = bytes.fromhex(
    "0600ff0901a1018540150025010902750195018106090375019501810695068101"
    "8541150026ff00090195027508910285420901810285430901810285440901950"
    "491028545090181028546950209018102854709018102c00601ff0901a101850a"
    "150026ff000901951f75088102c00602ff0901a1010509190129011500257f850"
    "1950175088102c006a1ff0903a1018555150026ff000903950675088102c00699"
    "ff0903a101859a0903150026ff00951f75080903b20201c0050b0905a10185081"
    "5002501092f750195018106092075019501812295068101050885080909750195"
    "019122050b092a75019501912295069101c0"
)

# HID descriptor item tags
ITEM_TYPES = {
    0x04: "Usage Page",
    0x08: "Usage",
    0x14: "Logical Minimum",
    0x24: "Logical Maximum",
    0x34: "Physical Minimum",
    0x44: "Physical Maximum",
    0x54: "Unit Exponent",
    0x64: "Unit",
    0x74: "Report Size",
    0x80: "Input",
    0x84: "Report ID",
    0x90: "Output",
    0x94: "Report Count",
    0xA0: "Collection",
    0xB0: "Feature",
    0xC0: "End Collection",
}

USAGE_PAGES = {
    0x01: "Generic Desktop",
    0x07: "Keyboard/Keypad",
    0x08: "LED",
    0x09: "Button",
    0x0B: "Telephony",
    0x0C: "Consumer",
    0x0D: "Digitizer",
    0x20: "Sensor",
    0xFF00: "Vendor Defined (0xFF00)",
    0xFF01: "Vendor Defined (0xFF01)",
    0xFF02: "Vendor Defined (0xFF02)",
    0xFF99: "Vendor Defined (0xFF99) - Logitech Proprietary",
    0xFFA1: "Vendor Defined (0xFFA1) - Logitech Proprietary",
}

TELEPHONY_USAGES = {
    0x01: "Phone",
    0x05: "Headset",
    0x06: "Handset",
    0x20: "Hook Switch",
    0x2A: "Line",
    0x2F: "Phone Mute",
    0x42: "Ring",
}

LED_USAGES = {
    0x09: "Mute",
    0x17: "Off-Hook",
    0x18: "Ring",
}

COLLECTION_TYPES = {
    0x00: "Physical",
    0x01: "Application",
    0x02: "Logical",
}

INPUT_FLAGS = {
    0: ("Data", "Constant"),
    1: ("Array", "Variable"),
    2: ("Absolute", "Relative"),
    3: ("No Wrap", "Wrap"),
    4: ("Linear", "Non-Linear"),
    5: ("Preferred State", "No Preferred"),
    6: ("No Null", "Null State"),
    7: ("Non-Volatile", "Volatile"),
}


def decode_input_flags(value):
    flags = []
    for bit, (off, on) in INPUT_FLAGS.items():
        if value & (1 << bit):
            flags.append(on)
        else:
            flags.append(off)
    return ", ".join(flags)


def parse_descriptor(data):
    i = 0
    indent = 0
    current_usage_page = 0

    print("=" * 70)
    print("LOGITECH MX BRIO - HID REPORT DESCRIPTOR ANALYSIS")
    print("=" * 70)
    print(f"Total descriptor length: {len(data)} bytes\n")

    while i < len(data):
        byte = data[i]

        if byte == 0xC0:  # End Collection (no data)
            indent -= 1
            print(f"{'  ' * indent}End Collection")
            i += 1
            continue

        # Parse item header
        size = byte & 0x03
        if size == 3:
            size = 4
        item_type = byte & 0xFC

        # Read value
        value = 0
        if size == 1 and i + 1 < len(data):
            value = data[i + 1]
        elif size == 2 and i + 2 < len(data):
            value = data[i + 1] | (data[i + 2] << 8)
        elif size == 4 and i + 4 < len(data):
            value = (
                data[i + 1]
                | (data[i + 2] << 8)
                | (data[i + 3] << 16)
                | (data[i + 4] << 24)
            )

        prefix = "  " * indent

        if item_type == 0x04:  # Usage Page
            current_usage_page = value
            page_name = USAGE_PAGES.get(value, f"Unknown (0x{value:04X})")
            print(f"{prefix}Usage Page: {page_name} (0x{value:04X})")

        elif item_type == 0x08:  # Usage
            usage_name = ""
            if current_usage_page == 0x0B:
                usage_name = TELEPHONY_USAGES.get(value, "")
            elif current_usage_page == 0x08:
                usage_name = LED_USAGES.get(value, "")
            extra = f" [{usage_name}]" if usage_name else ""
            print(f"{prefix}Usage: 0x{value:02X}{extra}")

        elif item_type == 0x18:  # Usage Minimum
            print(f"{prefix}Usage Minimum: 0x{value:02X}")

        elif item_type == 0x28:  # Usage Maximum
            print(f"{prefix}Usage Maximum: 0x{value:02X}")

        elif item_type == 0x14:  # Logical Minimum
            print(f"{prefix}Logical Minimum: {value}")

        elif item_type == 0x24:  # Logical Maximum
            print(f"{prefix}Logical Maximum: {value}")

        elif item_type == 0x74:  # Report Size
            print(f"{prefix}Report Size: {value} bits")

        elif item_type == 0x94:  # Report Count
            print(f"{prefix}Report Count: {value}")

        elif item_type == 0x84:  # Report ID
            print(f"\n{prefix}--- Report ID: {value} (0x{value:02X}) ---")

        elif item_type == 0x80:  # Input
            flags = decode_input_flags(value)
            print(f"{prefix}Input: ({flags}) [0x{value:02X}]")

        elif item_type == 0x90:  # Output
            flags = decode_input_flags(value)
            print(f"{prefix}Output: ({flags}) [0x{value:02X}]")

        elif item_type == 0xB0:  # Feature
            flags = decode_input_flags(value)
            print(f"{prefix}Feature: ({flags}) [0x{value:02X}]")

        elif item_type == 0xA0:  # Collection
            coll_name = COLLECTION_TYPES.get(value, f"Unknown (0x{value:02X})")
            print(f"{prefix}Collection: {coll_name}")
            indent += 1

        elif item_type == 0x54:  # Unit Exponent
            print(f"{prefix}Unit Exponent: {value}")

        else:
            print(
                f"{prefix}Unknown item: tag=0x{item_type:02X}, size={size}, value=0x{value:X}"
            )

        i += 1 + size

    print("\n" + "=" * 70)
    print("INTERFACE SUMMARY")
    print("=" * 70)
    print("""
Device: Logitech MX Brio
Vendor ID:  0x046D (1133)
Product ID: 0x0944 (2372)
Serial:     2527LVV0U2L8

USB Interfaces found:
  [0] Video Control  (UVC) - Camera controls, extension units
  [1] Video Streaming (UVC) - Video data
  [2] HID - Vendor controls, LED, telephony buttons
  [3] Vendor Specific (0xFF/0xFF) - Proprietary (firmware?)
  [4] Audio Control - Microphone control
  [5] Audio Streaming - Microphone data

HID Report IDs detected:
  Report 0x40 (64)  - Vendor 0xFF00: 2 bits input (flags/status)
  Report 0x41 (65)  - Vendor 0xFF00: 2 bytes feature (write)
  Report 0x42 (66)  - Vendor 0xFF00: 2 bytes input (read)
  Report 0x43 (67)  - Vendor 0xFF00: 2 bytes input (read)
  Report 0x44 (68)  - Vendor 0xFF00: 4 bytes input (read)
  Report 0x45 (69)  - Vendor 0xFF00: 1 byte input (read)
  Report 0x46 (70)  - Vendor 0xFF00: 2 bytes input (read)
  Report 0x47 (71)  - Vendor 0xFF00: 2 bytes input (read)
  Report 0x0A (10)  - Vendor 0xFF01: 31 bytes input (read)
  Report 0x01 (1)   - Vendor 0xFF02: 1 byte input (Button page)
  Report 0x55 (85)  - Vendor 0xFFA1: 6 bytes input (read)
  Report 0x9A (154) - Vendor 0xFF99: 31 bytes feature (read/write)
  Report 0x08 (8)   - Telephony: Phone Mute, Hook Switch, LED Mute control

Controllable outputs:
  Report 0x08 - LED Usage 0x09 (Mute LED) - 1 bit OUTPUT
  Report 0x08 - Telephony Usage 0x2A (Line) - 1 bit OUTPUT
""")


if __name__ == "__main__":
    parse_descriptor(RAW_DESCRIPTOR)
