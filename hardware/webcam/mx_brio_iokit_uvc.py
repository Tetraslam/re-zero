#!/usr/bin/env python3
"""
MX Brio UVC Camera Control via macOS IOKit -- NO SUDO REQUIRED.

Controls UVC camera parameters (brightness, contrast, saturation, hue, sharpness,
gamma, gain, white balance, zoom, focus, exposure) by sending USB class-specific
control transfers through the IOKit framework's IOUSBDeviceInterface.

Approach:
  1. Find the USB device in the IORegistry by VID/PID (IOUSBHostDevice)
  2. Create an IOCFPlugInInterface via IOCreatePlugInInterfaceForService
  3. QueryInterface for IOUSBDeviceInterface (COM-style vtable)
  4. Call USBDeviceOpen / DeviceRequest / USBDeviceClose through the vtable
  5. UVC GET/SET requests go through the kernel driver -- no detach needed

Device: Logitech MX Brio (VID=0x046D, PID=0x0944)

Usage:
    python3 mx_brio_iokit_uvc.py              # Interactive menu
    python3 mx_brio_iokit_uvc.py --dump       # Dump all controls
    python3 mx_brio_iokit_uvc.py --demo       # Visual demo (open a camera app!)
    python3 mx_brio_iokit_uvc.py --probe      # Probe all unit IDs
    python3 mx_brio_iokit_uvc.py --set brightness 100
    python3 mx_brio_iokit_uvc.py --get brightness
"""

import sys
import struct
import ctypes
import ctypes.util
import time
import argparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VID = 0x046D
PID = 0x0944

# UVC request codes
UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81
UVC_GET_MIN = 0x82
UVC_GET_MAX = 0x83
UVC_GET_RES = 0x84
UVC_GET_DEF = 0x85

# UVC bmRequestType
UVC_REQ_TYPE_GET = 0xA1  # Class, Interface, Device-to-Host
UVC_REQ_TYPE_SET = 0x21  # Class, Interface, Host-to-Device

# Processing Unit (PU) control selectors
PU_BACKLIGHT_COMP     = 0x01
PU_BRIGHTNESS         = 0x02
PU_CONTRAST           = 0x03
PU_GAIN               = 0x04
PU_POWER_LINE_FREQ    = 0x05
PU_HUE                = 0x06
PU_SATURATION         = 0x07
PU_SHARPNESS          = 0x08
PU_GAMMA              = 0x09
PU_WB_TEMPERATURE     = 0x0A
PU_WB_TEMPERATURE_AUTO = 0x0B

# Camera Terminal (CT) control selectors
CT_AE_MODE            = 0x02
CT_AE_PRIORITY        = 0x03
CT_EXPOSURE_TIME_ABS  = 0x04
CT_FOCUS_ABS          = 0x06
CT_FOCUS_AUTO         = 0x08
CT_ZOOM_ABS           = 0x0B

# IOKit UUIDs (as CFUUIDBytes)
# kIOUSBDeviceUserClientTypeID = 9DC7B780-9EC0-11D4-A54F-000A27052861
# kIOCFPlugInInterfaceID       = C244E858-109C-11D4-91D4-0050E4C6426F
# kIOUSBDeviceInterfaceID      = 5C8187D0-9EF3-11D4-8B45-000A27052861

# IOUSBDeviceInterface vtable indices (IOUSBLib.h, verified empirically)
VTABLE_QUERY_INTERFACE = 1
VTABLE_ADD_REF = 2
VTABLE_RELEASE = 3
VTABLE_USB_DEVICE_OPEN = 8
VTABLE_USB_DEVICE_CLOSE = 9
VTABLE_GET_DEVICE_VENDOR = 13
VTABLE_GET_DEVICE_PRODUCT = 14
VTABLE_DEVICE_REQUEST = 26

# IOUSBDeviceInterface182 extended vtable (inherits above + adds more)
VTABLE_USB_DEVICE_OPEN_SEIZE = 29  # Forces exclusive access over kernel driver
VTABLE_DEVICE_REQUEST_TO = 30      # DeviceRequest with timeout

# IOUSBDeviceInterface UUIDs
# Base: 5C8187D0-9EF3-11D4-8B45-000A27052861
# 182:  3C9EE1EB-2402-11B2-8E7E-000A27801E86  (adds OpenSeize, timeout requests)
IOKIT_ABORTED = -536870163  # 0xe00002ed kIOReturnAborted

# ---------------------------------------------------------------------------
# ctypes structures
# ---------------------------------------------------------------------------

class CFUUIDBytes(ctypes.Structure):
    """16-byte UUID structure used by IOKit COM interfaces."""
    _fields_ = [(f'byte{i}', ctypes.c_uint8) for i in range(16)]


class IOUSBDevRequest(ctypes.Structure):
    """USB device request structure for control transfers."""
    _fields_ = [
        ('bmRequestType', ctypes.c_uint8),
        ('bRequest', ctypes.c_uint8),
        ('wValue', ctypes.c_uint16),
        ('wIndex', ctypes.c_uint16),
        ('wLength', ctypes.c_uint16),
        ('pData', ctypes.c_void_p),
        ('wLenDone', ctypes.c_uint32),
    ]


# Function pointer types for the COM vtable
QueryInterfaceFnType = ctypes.CFUNCTYPE(
    ctypes.c_int32,                    # HRESULT return
    ctypes.c_void_p,                   # self
    CFUUIDBytes,                       # iid (by value, 16 bytes)
    ctypes.POINTER(ctypes.c_void_p),   # ppv (out)
)

SimpleVoidFnType = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)
ReleaseFnType = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)
GetUInt16FnType = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16)
)
DeviceRequestFnType = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(IOUSBDevRequest)
)


# ---------------------------------------------------------------------------
# IOKit USB Device wrapper
# ---------------------------------------------------------------------------

class IOKitUSBDevice:
    """
    Low-level IOKit USB device access via IOCFPlugInInterface and
    IOUSBDeviceInterface. Works without sudo on macOS.
    """

    def __init__(self):
        self._iokit = ctypes.cdll.LoadLibrary(
            '/System/Library/Frameworks/IOKit.framework/IOKit'
        )
        self._cf = ctypes.cdll.LoadLibrary(
            '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'
        )
        self._libc = ctypes.CDLL(None)
        self._setup_prototypes()

        self._plugin_ptr = None        # IOCFPlugInInterface**
        self._plugin_vtable = None
        self._dev_intf_ptr = None      # IOUSBDeviceInterface**
        self._dev_vtable = None
        self._is_open = False
        self._has_seize = False

        self._fn_device_request = None
        self._fn_usb_close = None

    # -- Framework function prototypes ------------------------------------

    def _setup_prototypes(self):
        cf = self._cf
        iokit = self._iokit

        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
        ]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p

        cf.CFNumberCreate.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
        ]
        cf.CFNumberCreate.restype = ctypes.c_void_p

        cf.CFDictionarySetValue.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        ]
        cf.CFDictionarySetValue.restype = None

        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None

        cf.CFUUIDCreateFromString.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFUUIDCreateFromString.restype = ctypes.c_void_p

        iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]
        iokit.IOServiceMatching.restype = ctypes.c_void_p

        iokit.IOServiceGetMatchingServices.argtypes = [
            ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)
        ]
        iokit.IOServiceGetMatchingServices.restype = ctypes.c_int

        iokit.IOIteratorNext.argtypes = [ctypes.c_uint]
        iokit.IOIteratorNext.restype = ctypes.c_uint

        iokit.IOObjectRelease.argtypes = [ctypes.c_uint]
        iokit.IOObjectRelease.restype = ctypes.c_int

        iokit.IOCreatePlugInInterfaceForService.argtypes = [
            ctypes.c_uint,                       # service
            ctypes.c_void_p,                     # pluginType (CFUUIDRef)
            ctypes.c_void_p,                     # interfaceType (CFUUIDRef)
            ctypes.POINTER(ctypes.c_void_p),     # theInterface
            ctypes.POINTER(ctypes.c_int32),      # theScore
        ]
        iokit.IOCreatePlugInInterfaceForService.restype = ctypes.c_int

        self._libc.mach_task_self.restype = ctypes.c_uint

    # -- Helper: create CFUUIDRef from string -----------------------------

    def _cfuuid(self, uuid_str: bytes):
        s = self._cf.CFStringCreateWithCString(None, uuid_str, 0)
        u = self._cf.CFUUIDCreateFromString(None, s)
        self._cf.CFRelease(s)
        return u

    # -- Helper: read vtable from COM double-pointer ----------------------

    @staticmethod
    def _vtable(double_ptr):
        vtable_ptr = ctypes.cast(
            double_ptr, ctypes.POINTER(ctypes.c_void_p)
        )[0]
        return ctypes.cast(vtable_ptr, ctypes.POINTER(ctypes.c_void_p))

    # -- Find and open device ---------------------------------------------

    def open(self, vid=VID, pid=PID):
        """Find the USB device by VID/PID and open it for control transfers."""
        iokit = self._iokit
        cf = self._cf
        kCFNumberSInt32Type = 3

        # Build matching dictionary
        matching = iokit.IOServiceMatching(b'IOUSBHostDevice')
        if not matching:
            raise RuntimeError('IOServiceMatching returned NULL')

        vid_val = ctypes.c_int32(vid)
        pid_val = ctypes.c_int32(pid)
        vid_cf = cf.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(vid_val))
        pid_cf = cf.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(pid_val))
        vid_key = cf.CFStringCreateWithCString(None, b'idVendor', 0)
        pid_key = cf.CFStringCreateWithCString(None, b'idProduct', 0)

        cf.CFDictionarySetValue(matching, vid_key, vid_cf)
        cf.CFDictionarySetValue(matching, pid_key, pid_cf)
        cf.CFRelease(vid_cf)
        cf.CFRelease(pid_cf)
        cf.CFRelease(vid_key)
        cf.CFRelease(pid_key)

        # Find service
        iterator = ctypes.c_uint()
        kr = iokit.IOServiceGetMatchingServices(
            0, matching, ctypes.byref(iterator)
        )
        if kr != 0:
            raise RuntimeError(
                f'IOServiceGetMatchingServices failed: {kr:#010x}'
            )

        service = iokit.IOIteratorNext(iterator)
        iokit.IOObjectRelease(iterator)
        if service == 0:
            raise RuntimeError(
                f'USB device {vid:#06x}:{pid:#06x} not found in IORegistry. '
                'Is the camera connected?'
            )

        try:
            self._create_device_interface(service)
        finally:
            iokit.IOObjectRelease(service)

        self._open_device()

    def _create_device_interface(self, service):
        """Create IOCFPlugInInterface and query for IOUSBDeviceInterface."""
        plugin_type = self._cfuuid(b'9DC7B780-9EC0-11D4-A54F-000A27052861')
        iocf_type = self._cfuuid(b'C244E858-109C-11D4-91D4-0050E4C6426F')

        plugin = ctypes.c_void_p()
        score = ctypes.c_int32()
        kr = self._iokit.IOCreatePlugInInterfaceForService(
            service, plugin_type, iocf_type,
            ctypes.byref(plugin), ctypes.byref(score)
        )
        if kr != 0 or not plugin.value:
            raise RuntimeError(
                f'IOCreatePlugInInterfaceForService failed: {kr:#010x}. '
                'The IOUSBLib bundle may not be available.'
            )

        self._plugin_ptr = plugin.value
        self._plugin_vtable = self._vtable(plugin.value)

        # QueryInterface for IOUSBDeviceInterface182 (has OpenSeize + timeout)
        query_fn = QueryInterfaceFnType(self._plugin_vtable[VTABLE_QUERY_INTERFACE])
        # Try 182 first: 3C9EE1EB-2402-11B2-8E7E-000A27801E86
        iid_182 = CFUUIDBytes(
            0x3c, 0x9e, 0xe1, 0xeb, 0x24, 0x02, 0x11, 0xb2,
            0x8e, 0x7e, 0x00, 0x0a, 0x27, 0x80, 0x1e, 0x86
        )
        dev_intf = ctypes.c_void_p()
        hr = query_fn(plugin, iid_182, ctypes.byref(dev_intf))
        self._has_seize = (hr == 0 and dev_intf.value)

        if not self._has_seize:
            # Fall back to base IOUSBDeviceInterface
            iid_base = CFUUIDBytes(
                0x5c, 0x81, 0x87, 0xd0, 0x9e, 0xf3, 0x11, 0xd4,
                0x8b, 0x45, 0x00, 0x0a, 0x27, 0x05, 0x28, 0x61
            )
            dev_intf = ctypes.c_void_p()
            hr = query_fn(plugin, iid_base, ctypes.byref(dev_intf))
            if hr != 0 or not dev_intf.value:
                raise RuntimeError(
                    f'QueryInterface for IOUSBDeviceInterface failed: {hr:#010x}'
                )

        self._dev_intf_ptr = dev_intf.value
        self._dev_vtable = self._vtable(dev_intf.value)

        # Cache function pointers
        self._fn_device_request = DeviceRequestFnType(
            self._dev_vtable[VTABLE_DEVICE_REQUEST]
        )
        self._fn_usb_close = SimpleVoidFnType(
            self._dev_vtable[VTABLE_USB_DEVICE_CLOSE]
        )

    def _open_device(self):
        """Open device, using USBDeviceOpenSeize if available (forces exclusive access)."""
        if self._has_seize:
            # USBDeviceOpenSeize takes control even if kernel driver has it
            seize_fn = SimpleVoidFnType(
                self._dev_vtable[VTABLE_USB_DEVICE_OPEN_SEIZE]
            )
            kr = seize_fn(self._dev_intf_ptr)
            if kr == 0:
                self._is_open = True
                return
            # Fall through to regular open if seize fails

        open_fn = SimpleVoidFnType(self._dev_vtable[VTABLE_USB_DEVICE_OPEN])
        kr = open_fn(self._dev_intf_ptr)
        if kr != 0:
            err_msg = f'USBDeviceOpen failed: {kr:#010x}.'
            if kr == 0xe00002c5 or kr == -0x1ffffd3b:
                err_msg += (
                    ' Another process has exclusive access to the device.'
                    ' Try closing other camera apps.'
                )
            raise RuntimeError(err_msg)
        self._is_open = True

    def close(self):
        """Close the device and release interfaces."""
        if self._is_open and self._fn_usb_close and self._dev_intf_ptr:
            self._fn_usb_close(self._dev_intf_ptr)
            self._is_open = False

        if self._dev_intf_ptr and self._dev_vtable:
            release = ReleaseFnType(self._dev_vtable[VTABLE_RELEASE])
            release(self._dev_intf_ptr)
            self._dev_intf_ptr = None

        if self._plugin_ptr and self._plugin_vtable:
            release = ReleaseFnType(self._plugin_vtable[VTABLE_RELEASE])
            release(self._plugin_ptr)
            self._plugin_ptr = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # -- Verify identity --------------------------------------------------

    def get_vendor_product(self):
        """Return (vendor_id, product_id) to verify the device."""
        get_vendor = GetUInt16FnType(self._dev_vtable[VTABLE_GET_DEVICE_VENDOR])
        get_product = GetUInt16FnType(self._dev_vtable[VTABLE_GET_DEVICE_PRODUCT])
        v = ctypes.c_uint16()
        p = ctypes.c_uint16()
        get_vendor(self._dev_intf_ptr, ctypes.byref(v))
        get_product(self._dev_intf_ptr, ctypes.byref(p))
        return v.value, p.value

    # -- USB control transfer ---------------------------------------------

    def device_request(self, bm_request_type, b_request,
                       w_value, w_index, data_or_length):
        """
        Send a USB control transfer.

        For IN (device-to-host) requests: pass an integer length.
        Returns the received bytes.

        For OUT (host-to-device) requests: pass bytes data.
        Returns None.
        """
        if not self._is_open:
            raise RuntimeError('Device is not open')

        is_in = (bm_request_type & 0x80) != 0
        req = IOUSBDevRequest()
        req.bmRequestType = bm_request_type
        req.bRequest = b_request
        req.wValue = w_value
        req.wIndex = w_index

        if is_in:
            length = data_or_length if isinstance(data_or_length, int) else len(data_or_length)
            buf = ctypes.create_string_buffer(length)
            req.wLength = length
            req.pData = ctypes.cast(buf, ctypes.c_void_p)
            req.wLenDone = 0

            kr = self._fn_device_request(self._dev_intf_ptr, ctypes.byref(req))
            if kr != 0:
                return None
            return buf.raw[:req.wLenDone]
        else:
            data = data_or_length if isinstance(data_or_length, bytes) else bytes(data_or_length)
            buf = ctypes.create_string_buffer(data)
            req.wLength = len(data)
            req.pData = ctypes.cast(buf, ctypes.c_void_p)
            req.wLenDone = 0

            kr = self._fn_device_request(self._dev_intf_ptr, ctypes.byref(req))
            if kr != 0:
                return None
            return req.wLenDone


# ---------------------------------------------------------------------------
# UVC Controller
# ---------------------------------------------------------------------------

class UVCControl:
    """
    High-level UVC camera control through IOKit USB device requests.

    Auto-detects Processing Unit and Camera Terminal unit IDs by probing.
    """

    # Control definitions: (name, selector, byte_length, signed)
    PU_CONTROLS = [
        ('backlight_comp',      PU_BACKLIGHT_COMP,      2, False),
        ('brightness',          PU_BRIGHTNESS,          2, True),
        ('contrast',            PU_CONTRAST,            2, False),
        ('gain',                PU_GAIN,                2, False),
        ('power_line_freq',     PU_POWER_LINE_FREQ,     1, False),
        ('hue',                 PU_HUE,                 2, True),
        ('saturation',          PU_SATURATION,          2, False),
        ('sharpness',           PU_SHARPNESS,           2, False),
        ('gamma',               PU_GAMMA,               2, False),
        ('wb_temperature',      PU_WB_TEMPERATURE,      2, False),
        ('wb_temperature_auto', PU_WB_TEMPERATURE_AUTO, 1, False),
    ]

    CT_CONTROLS = [
        ('ae_mode',             CT_AE_MODE,             1, False),
        ('ae_priority',         CT_AE_PRIORITY,         1, False),
        ('exposure_time_abs',   CT_EXPOSURE_TIME_ABS,   4, False),
        ('focus_abs',           CT_FOCUS_ABS,           2, False),
        ('focus_auto',          CT_FOCUS_AUTO,          1, False),
        ('zoom_abs',            CT_ZOOM_ABS,            2, False),
    ]

    # Friendly names for display
    FRIENDLY_NAMES = {
        'backlight_comp':       'Backlight Compensation',
        'brightness':           'Brightness',
        'contrast':             'Contrast',
        'gain':                 'Gain',
        'power_line_freq':      'Power Line Frequency',
        'hue':                  'Hue',
        'saturation':           'Saturation',
        'sharpness':            'Sharpness',
        'gamma':                'Gamma',
        'wb_temperature':       'White Balance Temperature',
        'wb_temperature_auto':  'White Balance Auto',
        'ae_mode':              'Auto Exposure Mode',
        'ae_priority':          'Auto Exposure Priority',
        'exposure_time_abs':    'Exposure Time (absolute)',
        'focus_abs':            'Focus (absolute)',
        'focus_auto':           'Autofocus',
        'zoom_abs':             'Zoom (absolute)',
    }

    def __init__(self, vid=VID, pid=PID):
        self.vid = vid
        self.pid = pid
        self.usb = IOKitUSBDevice()
        self.pu_unit_id = None   # Processing Unit
        self.ct_unit_id = None   # Camera Terminal
        self.interface_num = 0   # Video Control interface number
        self._available_pu = {}  # name -> (selector, length, signed)
        self._available_ct = {}  # name -> (selector, length, signed)

    def open(self):
        """Open the device and auto-detect unit IDs."""
        self.usb.open(self.vid, self.pid)
        v, p = self.usb.get_vendor_product()
        if v != self.vid or p != self.pid:
            raise RuntimeError(
                f'Device VID/PID mismatch: got {v:#06x}:{p:#06x}, '
                f'expected {self.vid:#06x}:{self.pid:#06x}'
            )
        self._auto_detect_units()

    def close(self):
        """Close the device."""
        self.usb.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    # -- UVC protocol helpers ---------------------------------------------

    def _uvc_get(self, unit_id, selector, request, length):
        """Send a UVC GET request. Returns raw bytes or None."""
        return self.usb.device_request(
            UVC_REQ_TYPE_GET, request,
            (selector << 8), (unit_id << 8) | self.interface_num,
            length
        )

    def _uvc_set(self, unit_id, selector, data):
        """Send a UVC SET_CUR request. Returns wLenDone or None."""
        return self.usb.device_request(
            UVC_REQ_TYPE_SET, UVC_SET_CUR,
            (selector << 8), (unit_id << 8) | self.interface_num,
            data
        )

    def _decode(self, raw, length, signed):
        """Decode raw bytes to an integer."""
        if raw is None or len(raw) < length:
            return None
        fmt_map = {
            (1, False): '<B', (1, True): '<b',
            (2, False): '<H', (2, True): '<h',
            (4, False): '<I', (4, True): '<i',
        }
        fmt = fmt_map.get((length, signed))
        if fmt is None:
            return int.from_bytes(raw[:length], 'little', signed=signed)
        return struct.unpack(fmt, raw[:length])[0]

    def _encode(self, value, length, signed):
        """Encode an integer to bytes."""
        fmt_map = {
            (1, False): '<B', (1, True): '<b',
            (2, False): '<H', (2, True): '<h',
            (4, False): '<I', (4, True): '<i',
        }
        fmt = fmt_map.get((length, signed))
        if fmt is None:
            return value.to_bytes(length, 'little', signed=signed)
        return struct.pack(fmt, value)

    # -- Auto-detection ---------------------------------------------------

    def _auto_detect_units(self):
        """
        Probe unit IDs 1-12 to find the Processing Unit and Camera Terminal.

        Processing Unit: identified by a successful read of brightness (sel 0x02, 2 bytes)
        with a reasonable range (min != max, min >= 0).

        Camera Terminal: identified by a successful read of exposure (sel 0x04, 4 bytes)
        with a reasonable range.
        """
        print('  Auto-detecting UVC unit IDs...')

        for uid in range(1, 13):
            # Check for PU by reading brightness (selector 0x02, 2 bytes)
            if self.pu_unit_id is None:
                raw_cur = self._uvc_get(uid, PU_BRIGHTNESS, UVC_GET_CUR, 2)
                raw_min = self._uvc_get(uid, PU_BRIGHTNESS, UVC_GET_MIN, 2)
                raw_max = self._uvc_get(uid, PU_BRIGHTNESS, UVC_GET_MAX, 2)
                if (raw_cur and len(raw_cur) == 2 and
                    raw_min and len(raw_min) == 2 and
                    raw_max and len(raw_max) == 2):
                    cur = struct.unpack('<h', raw_cur)[0]
                    mn = struct.unpack('<h', raw_min)[0]
                    mx = struct.unpack('<h', raw_max)[0]
                    if mn != mx and mn >= 0 and mx > 0 and mn <= cur <= mx:
                        self.pu_unit_id = uid
                        print(f'    Processing Unit:  ID {uid}'
                              f'  (brightness {cur}, range {mn}-{mx})')

            # Check for CT by reading exposure (selector 0x04, 4 bytes)
            if self.ct_unit_id is None:
                raw_cur = self._uvc_get(uid, CT_EXPOSURE_TIME_ABS, UVC_GET_CUR, 4)
                raw_min = self._uvc_get(uid, CT_EXPOSURE_TIME_ABS, UVC_GET_MIN, 4)
                raw_max = self._uvc_get(uid, CT_EXPOSURE_TIME_ABS, UVC_GET_MAX, 4)
                if (raw_cur and len(raw_cur) == 4 and
                    raw_min and len(raw_min) == 4 and
                    raw_max and len(raw_max) == 4):
                    cur = struct.unpack('<I', raw_cur)[0]
                    mn = struct.unpack('<I', raw_min)[0]
                    mx = struct.unpack('<I', raw_max)[0]
                    # Also verify zoom works on this unit (CT has zoom, PU does not)
                    raw_zoom = self._uvc_get(uid, CT_ZOOM_ABS, UVC_GET_CUR, 2)
                    if mn < mx and mn > 0 and raw_zoom and len(raw_zoom) == 2:
                        self.ct_unit_id = uid
                        print(f'    Camera Terminal:  ID {uid}'
                              f'  (exposure {cur}, range {mn}-{mx})')

        # Discover which controls are available
        if self.pu_unit_id is not None:
            for name, sel, length, signed in self.PU_CONTROLS:
                raw = self._uvc_get(self.pu_unit_id, sel, UVC_GET_CUR, length)
                if raw and len(raw) == length:
                    self._available_pu[name] = (sel, length, signed)

        if self.ct_unit_id is not None:
            for name, sel, length, signed in self.CT_CONTROLS:
                raw = self._uvc_get(self.ct_unit_id, sel, UVC_GET_CUR, length)
                if raw and len(raw) == length:
                    self._available_ct[name] = (sel, length, signed)

        if self.pu_unit_id is None and self.ct_unit_id is None:
            print('    WARNING: No UVC units detected. Controls will not work.')
        else:
            pu_names = ', '.join(self._available_pu.keys()) or 'none'
            ct_names = ', '.join(self._available_ct.keys()) or 'none'
            print(f'    PU controls: {pu_names}')
            print(f'    CT controls: {ct_names}')

    # -- Generic get/set --------------------------------------------------

    def get_control(self, name):
        """
        Read a control's current, min, max, default, and resolution values.
        Returns dict with keys: current, min, max, default, res.
        """
        if name in self._available_pu:
            sel, length, signed = self._available_pu[name]
            unit_id = self.pu_unit_id
        elif name in self._available_ct:
            sel, length, signed = self._available_ct[name]
            unit_id = self.ct_unit_id
        else:
            return None

        result = {}
        for req_code, key in [
            (UVC_GET_CUR, 'current'),
            (UVC_GET_MIN, 'min'),
            (UVC_GET_MAX, 'max'),
            (UVC_GET_DEF, 'default'),
            (UVC_GET_RES, 'res'),
        ]:
            raw = self._uvc_get(unit_id, sel, req_code, length)
            result[key] = self._decode(raw, length, signed)

        return result

    def set_control(self, name, value):
        """Set a control to the specified value. Returns True on success."""
        if name in self._available_pu:
            sel, length, signed = self._available_pu[name]
            unit_id = self.pu_unit_id
        elif name in self._available_ct:
            sel, length, signed = self._available_ct[name]
            unit_id = self.ct_unit_id
        else:
            return False

        data = self._encode(value, length, signed)
        result = self._uvc_set(unit_id, sel, data)
        return result is not None

    def get_all_controls(self):
        """Read all available controls. Returns dict of name -> info dict."""
        controls = {}
        for name in list(self._available_pu.keys()) + list(self._available_ct.keys()):
            info = self.get_control(name)
            if info and info.get('current') is not None:
                controls[name] = info
        return controls

    # -- Convenience property methods -------------------------------------

    def get_brightness(self):
        return self.get_control('brightness')

    def set_brightness(self, val):
        return self.set_control('brightness', val)

    def get_contrast(self):
        return self.get_control('contrast')

    def set_contrast(self, val):
        return self.set_control('contrast', val)

    def get_saturation(self):
        return self.get_control('saturation')

    def set_saturation(self, val):
        return self.set_control('saturation', val)

    def get_hue(self):
        return self.get_control('hue')

    def set_hue(self, val):
        return self.set_control('hue', val)

    def get_sharpness(self):
        return self.get_control('sharpness')

    def set_sharpness(self, val):
        return self.set_control('sharpness', val)

    def get_gamma(self):
        return self.get_control('gamma')

    def set_gamma(self, val):
        return self.set_control('gamma', val)

    def get_gain(self):
        return self.get_control('gain')

    def set_gain(self, val):
        return self.set_control('gain', val)

    def get_wb_temperature(self):
        return self.get_control('wb_temperature')

    def set_wb_temperature(self, kelvin):
        return self.set_control('wb_temperature', kelvin)

    def set_wb_auto(self, on=True):
        return self.set_control('wb_temperature_auto', 1 if on else 0)

    def get_zoom(self):
        return self.get_control('zoom_abs')

    def set_zoom(self, val):
        return self.set_control('zoom_abs', val)

    def get_focus(self):
        return self.get_control('focus_abs')

    def set_focus(self, val):
        return self.set_control('focus_abs', val)

    def set_autofocus(self, on=True):
        return self.set_control('focus_auto', 1 if on else 0)

    def get_exposure(self):
        return self.get_control('exposure_time_abs')

    def set_exposure(self, val):
        return self.set_control('exposure_time_abs', val)

    def set_auto_exposure(self, on=True):
        # AE Mode: 1=Manual, 2=Auto, 4=Shutter Priority, 8=Aperture Priority
        return self.set_control('ae_mode', 8 if on else 1)

    def get_backlight_comp(self):
        return self.get_control('backlight_comp')

    def set_backlight_comp(self, val):
        return self.set_control('backlight_comp', val)

    # -- Probe all unit IDs -----------------------------------------------

    def probe_all_units(self, max_uid=12):
        """
        Probe all unit IDs and report what responds.
        Useful for reverse-engineering a camera's UVC descriptor layout.
        """
        all_controls = self.PU_CONTROLS + self.CT_CONTROLS
        results = {}

        for uid in range(1, max_uid + 1):
            unit_results = {}
            for name, sel, length, signed in all_controls:
                raw_cur = self._uvc_get(uid, sel, UVC_GET_CUR, length)
                if raw_cur and len(raw_cur) >= length:
                    raw_min = self._uvc_get(uid, sel, UVC_GET_MIN, length)
                    raw_max = self._uvc_get(uid, sel, UVC_GET_MAX, length)
                    raw_def = self._uvc_get(uid, sel, UVC_GET_DEF, length)
                    unit_results[name] = {
                        'current': self._decode(raw_cur, length, signed),
                        'min': self._decode(raw_min, length, signed),
                        'max': self._decode(raw_max, length, signed),
                        'default': self._decode(raw_def, length, signed),
                    }
            if unit_results:
                results[uid] = unit_results

        return results


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_control_line(name, info, friendly_names=None):
    """Format a single control's info as a readable string."""
    display_name = (friendly_names or {}).get(name, name)
    cur = info.get('current', '?')
    mn = info.get('min', '?')
    mx = info.get('max', '?')
    df = info.get('default', '?')
    return f'  {display_name:30s}  cur={cur!s:>6s}  min={mn!s:>6s}  max={mx!s:>6s}  def={df!s:>6s}'


def dump_all(uvc):
    """Print all current control values."""
    controls = uvc.get_all_controls()
    if not controls:
        print('  No controls available.')
        return

    print('\n  Processing Unit controls:')
    print('  ' + '-' * 78)
    for name in uvc._available_pu:
        if name in controls:
            print(format_control_line(name, controls[name], UVCControl.FRIENDLY_NAMES))

    print('\n  Camera Terminal controls:')
    print('  ' + '-' * 78)
    for name in uvc._available_ct:
        if name in controls:
            print(format_control_line(name, controls[name], UVCControl.FRIENDLY_NAMES))
    print()


def probe_all(uvc):
    """Probe and print all unit IDs."""
    print('\n  Probing UVC unit IDs 1-12...\n')
    results = uvc.probe_all_units()
    for uid, ctrls in sorted(results.items()):
        label = ''
        if uid == uvc.pu_unit_id:
            label = ' [Processing Unit]'
        elif uid == uvc.ct_unit_id:
            label = ' [Camera Terminal]'
        print(f'  Unit {uid}{label}:')
        for name, info in sorted(ctrls.items()):
            display_name = UVCControl.FRIENDLY_NAMES.get(name, name)
            cur = info.get('current', '?')
            mn = info.get('min', '?')
            mx = info.get('max', '?')
            df = info.get('default', '?')
            print(f'    {display_name:30s}  cur={cur!s:>6s}  min={mn!s:>6s}  max={mx!s:>6s}  def={df!s:>6s}')
        print()


# ---------------------------------------------------------------------------
# Demo mode
# ---------------------------------------------------------------------------

def run_demo(uvc):
    """
    Visual demo -- open Photo Booth or any camera app to watch the changes.
    Sweeps brightness, contrast, saturation, WB temperature, hue, zoom, focus.
    Restores everything to original values when done.
    """
    print('\n' + '=' * 70)
    print('  VISUAL UVC CONTROL DEMO')
    print('  >>> Open Photo Booth or any camera app to watch! <<<')
    print('=' * 70)

    dump_all(uvc)

    saved = {}  # name -> original value

    def save(name):
        info = uvc.get_control(name)
        if info and info.get('current') is not None:
            saved[name] = info['current']
        return info

    def restore(name):
        if name in saved:
            uvc.set_control(name, saved[name])

    def sweep(name, label, delay=0.15):
        info = save(name)
        if not info or info.get('current') is None:
            print(f'  {label}: not available')
            return
        cur, mn, mx = info['current'], info.get('min', 0), info.get('max', 255)
        if mn is None or mx is None or mn >= mx:
            print(f'  {label}: range unavailable')
            return
        step = max(1, (mx - mn) // 15)
        print(f'\n  [{label}] Sweeping {mn} -> {mx} (current: {cur})')
        for v in range(mn, mx + 1, step):
            uvc.set_control(name, v)
            time.sleep(delay)
        uvc.set_control(name, mx)
        time.sleep(0.5)
        for v in range(mx, mn - 1, -step):
            uvc.set_control(name, v)
            time.sleep(delay)
        restore(name)
        print(f'    Restored to {saved.get(name, "?")}')

    # Brightness
    sweep('brightness', 'BRIGHTNESS')

    # Contrast
    sweep('contrast', 'CONTRAST')

    # Saturation
    info = save('saturation')
    if info and info.get('current') is not None:
        mn = info.get('min', 0)
        mx = info.get('max', 255)
        print(f'\n  [SATURATION] B&W -> Vivid')
        uvc.set_saturation(mn or 0)
        print(f'    Desaturated (B&W): {mn}')
        time.sleep(2)
        uvc.set_saturation(mx or 255)
        print(f'    Oversaturated: {mx}')
        time.sleep(2)
        restore('saturation')
        print(f'    Restored to {saved.get("saturation", "?")}')

    # Hue
    sweep('hue', 'HUE', delay=0.1)

    # White balance temperature
    info_wb = save('wb_temperature')
    if info_wb and info_wb.get('current') is not None:
        mn = info_wb.get('min', 2800)
        mx = info_wb.get('max', 7500)
        print(f'\n  [WHITE BALANCE] Temperature sweep')
        uvc.set_wb_auto(False)
        time.sleep(0.3)
        print(f'    Warm ({mn}K - candlelight)...')
        uvc.set_wb_temperature(mn or 2800)
        time.sleep(2)
        print(f'    Cool ({mx}K - blue sky)...')
        uvc.set_wb_temperature(mx or 7500)
        time.sleep(2)
        restore('wb_temperature')
        uvc.set_wb_auto(True)
        print(f'    Auto WB restored')

    # Zoom
    info_z = save('zoom_abs')
    if info_z and info_z.get('current') is not None:
        mn = info_z.get('min', 100)
        mx = info_z.get('max', 400)
        print(f'\n  [ZOOM] {mn} -> {mx}')
        step = max(1, (mx - mn) // 15)
        for v in range(mn, mx + 1, step):
            uvc.set_zoom(v)
            time.sleep(0.2)
        uvc.set_zoom(mx)
        time.sleep(1)
        for v in range(mx, mn - 1, -step):
            uvc.set_zoom(v)
            time.sleep(0.2)
        restore('zoom_abs')
        print(f'    Restored to {saved.get("zoom_abs", "?")}')

    # Focus
    info_f = save('focus_abs')
    if info_f and info_f.get('current') is not None:
        mn = info_f.get('min', 0)
        mx = info_f.get('max', 255)
        print(f'\n  [FOCUS] Manual focus sweep {mn} -> {mx}')
        uvc.set_autofocus(False)
        time.sleep(0.3)
        step = max(1, (mx - mn) // 10)
        for v in range(mn, mx + 1, step):
            uvc.set_focus(v)
            time.sleep(0.3)
        time.sleep(0.5)
        uvc.set_autofocus(True)
        print(f'    Autofocus restored')

    # Exposure
    info_e = save('exposure_time_abs')
    if info_e and info_e.get('current') is not None:
        mn = info_e.get('min', 3)
        mx = info_e.get('max', 2047)
        print(f'\n  [EXPOSURE] Manual exposure {mn} -> {mx}')
        uvc.set_auto_exposure(False)
        time.sleep(0.3)
        uvc.set_exposure(mn or 3)
        print(f'    Short exposure (dark): {mn}')
        time.sleep(2)
        uvc.set_exposure(min(mx, 500))
        print(f'    Long exposure (bright): {min(mx, 500)}')
        time.sleep(2)
        uvc.set_auto_exposure(True)
        print(f'    Auto exposure restored')

    print('\n' + '=' * 70)
    print('  DEMO COMPLETE -- all settings restored')
    print('=' * 70 + '\n')


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

MENU_CONTROLS = [
    # (key, display name, control name, type)
    ('1',  'Brightness UP',        'brightness',       'up'),
    ('2',  'Brightness DOWN',      'brightness',       'down'),
    ('3',  'Contrast UP',          'contrast',         'up'),
    ('4',  'Contrast DOWN',        'contrast',         'down'),
    ('5',  'Saturation OFF (B&W)', 'saturation',       'min'),
    ('6',  'Saturation MAX',       'saturation',       'max'),
    ('7',  'Sharpness MIN',        'sharpness',        'min'),
    ('8',  'Sharpness MAX',        'sharpness',        'max'),
    ('9',  'Hue rotate',           'hue',              'sweep'),
    ('10', 'Gamma UP',             'gamma',            'up'),
    ('11', 'Gamma DOWN',           'gamma',            'down'),
    ('12', 'Gain UP',              'gain',             'up'),
    ('13', 'Gain DOWN',            'gain',             'down'),
    ('14', 'WB Warm (3000K)',      'wb_temperature',   'value:3000'),
    ('15', 'WB Cool (6500K)',      'wb_temperature',   'value:6500'),
    ('16', 'WB Auto ON',           'wb_temperature_auto', 'value:1'),
    ('17', 'Zoom IN',              'zoom_abs',         'up'),
    ('18', 'Zoom OUT',             'zoom_abs',         'down'),
    ('19', 'Focus NEAR',           'focus_abs',        'min'),
    ('20', 'Focus FAR',            'focus_abs',        'max'),
    ('21', 'Autofocus ON',         'focus_auto',       'value:1'),
    ('22', 'Autofocus OFF',        'focus_auto',       'value:0'),
    ('23', 'Exposure LONG',        'exposure_time_abs', 'up'),
    ('24', 'Exposure SHORT',       'exposure_time_abs', 'down'),
    ('25', 'Auto Exposure ON',     'ae_mode',          'value:8'),
    ('26', 'Auto Exposure OFF',    'ae_mode',          'value:1'),
    ('27', 'Backlight Comp ON',    'backlight_comp',   'value:1'),
    ('28', 'Backlight Comp OFF',   'backlight_comp',   'value:0'),
]


def interactive(uvc):
    """Run the interactive control menu."""
    print('\n  Current values:')
    dump_all(uvc)

    while True:
        print('-' * 70)
        print('  MX BRIO UVC CONTROL (IOKit, no sudo)')
        print('-' * 70)
        print('  Image Processing:')
        for item in MENU_CONTROLS[:13]:
            print(f'    {item[0]:>3s}  {item[1]}')
        print('  White Balance:')
        for item in MENU_CONTROLS[13:16]:
            print(f'    {item[0]:>3s}  {item[1]}')
        print('  Lens:')
        for item in MENU_CONTROLS[16:22]:
            print(f'    {item[0]:>3s}  {item[1]}')
        print('  Exposure:')
        for item in MENU_CONTROLS[22:28]:
            print(f'    {item[0]:>3s}  {item[1]}')
        print('  Other:')
        print('     d  Dump all controls')
        print('     p  Probe all unit IDs')
        print('     r  Reset all to defaults')
        print('     m  Run full demo')
        print('     q  Quit')
        print('-' * 70)

        try:
            choice = input('  > ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == 'q':
            break
        elif choice == 'd':
            dump_all(uvc)
            continue
        elif choice == 'p':
            probe_all(uvc)
            continue
        elif choice == 'r':
            reset_all_defaults(uvc)
            continue
        elif choice == 'm':
            run_demo(uvc)
            continue

        # Find the menu item
        item = None
        for mi in MENU_CONTROLS:
            if mi[0] == choice:
                item = mi
                break

        if item is None:
            print('  Invalid choice.')
            continue

        _, display, ctrl_name, action = item
        info = uvc.get_control(ctrl_name)
        if info is None or info.get('current') is None:
            print(f'  {display}: control not available')
            continue

        cur = info['current']
        mn = info.get('min', 0) or 0
        mx = info.get('max', 255) or 255
        step = max(1, (mx - mn) // 10)

        try:
            if action == 'up':
                new_val = min(cur + step, mx)
                uvc.set_control(ctrl_name, new_val)
                print(f'  {display}: {cur} -> {new_val}')
            elif action == 'down':
                new_val = max(cur - step, mn)
                uvc.set_control(ctrl_name, new_val)
                print(f'  {display}: {cur} -> {new_val}')
            elif action == 'min':
                uvc.set_control(ctrl_name, mn)
                print(f'  {display}: -> {mn}')
            elif action == 'max':
                uvc.set_control(ctrl_name, mx)
                print(f'  {display}: -> {mx}')
            elif action == 'sweep':
                print(f'  Sweeping {display}...')
                for v in range(mn, mx + 1, max(1, (mx - mn) // 20)):
                    uvc.set_control(ctrl_name, v)
                    time.sleep(0.08)
                uvc.set_control(ctrl_name, cur)
                print(f'  Restored to {cur}')
            elif action.startswith('value:'):
                val = int(action.split(':')[1])
                # For WB temperature, disable auto first
                if ctrl_name == 'wb_temperature':
                    uvc.set_wb_auto(False)
                    time.sleep(0.1)
                uvc.set_control(ctrl_name, val)
                print(f'  {display}: -> {val}')
        except Exception as e:
            print(f'  Error: {e}')

        print()


def reset_all_defaults(uvc):
    """Reset all controls to their default values."""
    print('  Resetting all controls to defaults...')

    # Restore auto modes first
    uvc.set_auto_exposure(True)
    uvc.set_autofocus(True)
    uvc.set_wb_auto(True)

    # Reset each control to its default
    all_names = list(uvc._available_pu.keys()) + list(uvc._available_ct.keys())
    for name in all_names:
        if name in ('ae_mode', 'focus_auto', 'wb_temperature_auto'):
            continue  # Already handled
        info = uvc.get_control(name)
        if info and info.get('default') is not None:
            uvc.set_control(name, info['default'])

    print('  All controls reset to defaults.')
    dump_all(uvc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='MX Brio UVC Camera Control via macOS IOKit (no sudo needed)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                        Interactive menu
  %(prog)s --dump                 Show all control values
  %(prog)s --demo                 Visual demo (open a camera app to watch!)
  %(prog)s --probe                Probe all UVC unit IDs
  %(prog)s --get brightness       Read brightness
  %(prog)s --set brightness 100   Set brightness to 100
  %(prog)s --set zoom_abs 200     Set zoom to 200
  %(prog)s --reset                Reset all controls to defaults

Control names:
  brightness, contrast, saturation, hue, sharpness, gamma, gain,
  wb_temperature, wb_temperature_auto, backlight_comp, power_line_freq,
  zoom_abs, focus_abs, focus_auto, exposure_time_abs, ae_mode, ae_priority
        """
    )
    parser.add_argument('--vid', type=lambda x: int(x, 0), default=VID,
                        help=f'USB Vendor ID (default: {VID:#06x})')
    parser.add_argument('--pid', type=lambda x: int(x, 0), default=PID,
                        help=f'USB Product ID (default: {PID:#06x})')
    parser.add_argument('--dump', action='store_true',
                        help='Dump all control values')
    parser.add_argument('--demo', action='store_true',
                        help='Run visual demo')
    parser.add_argument('--probe', action='store_true',
                        help='Probe all UVC unit IDs')
    parser.add_argument('--reset', action='store_true',
                        help='Reset all controls to defaults')
    parser.add_argument('--get', metavar='CONTROL',
                        help='Get a control value')
    parser.add_argument('--set', nargs=2, metavar=('CONTROL', 'VALUE'),
                        help='Set a control value')

    args = parser.parse_args()

    print('=' * 70)
    print('  LOGITECH MX BRIO -- UVC CONTROL via IOKit')
    print(f'  VID={args.vid:#06x} PID={args.pid:#06x} | No sudo required')
    print('=' * 70)

    uvc = UVCControl(vid=args.vid, pid=args.pid)
    try:
        uvc.open()
    except RuntimeError as e:
        print(f'\n  ERROR: {e}\n')
        sys.exit(1)

    print()

    try:
        if args.dump:
            dump_all(uvc)
        elif args.demo:
            run_demo(uvc)
        elif args.probe:
            probe_all(uvc)
        elif args.reset:
            reset_all_defaults(uvc)
        elif args.get:
            info = uvc.get_control(args.get)
            if info is None:
                print(f'  Control "{args.get}" not available.')
                all_names = list(uvc._available_pu.keys()) + list(uvc._available_ct.keys())
                print(f'  Available: {", ".join(all_names)}')
            else:
                friendly = UVCControl.FRIENDLY_NAMES.get(args.get, args.get)
                print(f'  {friendly}:')
                for k, v in info.items():
                    print(f'    {k:>10s}: {v}')
        elif args.set:
            ctrl_name, value_str = args.set
            try:
                value = int(value_str)
            except ValueError:
                print(f'  Invalid value: {value_str}')
                sys.exit(1)
            ok = uvc.set_control(ctrl_name, value)
            if ok:
                print(f'  {ctrl_name} set to {value}')
                # Read back
                info = uvc.get_control(ctrl_name)
                if info:
                    print(f'  Read back: {info.get("current")}')
            else:
                print(f'  Failed to set {ctrl_name}.')
                all_names = list(uvc._available_pu.keys()) + list(uvc._available_ct.keys())
                print(f'  Available: {", ".join(all_names)}')
        else:
            interactive(uvc)
    except KeyboardInterrupt:
        print('\n  Interrupted.')
    finally:
        uvc.close()
        print('  Device closed. Goodbye.')


if __name__ == '__main__':
    main()
