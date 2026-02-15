from __future__ import annotations

import dataclasses
import struct
from typing import Optional, Tuple


MAGIC = b"\xD0\xB0"
VER = 0x01


class SfType:
    HELLO = 0x01
    LOG = 0x03
    UDP = 0x02

    TCP_OPEN = 0x10
    TCP_OPEN_OK = 0x11
    TCP_OPEN_FAIL = 0x12
    TCP_DATA = 0x13
    TCP_CLOSE = 0x14


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    # CRC16-CCITT (poly 0x1021, init 0xFFFF), no final xor.
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


@dataclasses.dataclass(frozen=True)
class Frame:
    type: int
    conn: int
    port: int
    payload: bytes


class Decoder:
    def __init__(self, max_frame: int = 4096) -> None:
        self._buf = bytearray()
        self._max_frame = max_frame

    def feed(self, data: bytes) -> None:
        self._buf += data
        if len(self._buf) > (self._max_frame * 2):
            # Avoid unbounded growth on garbage.
            del self._buf[:-self._max_frame]

    def pop(self) -> Optional[Tuple[Frame, bytes]]:
        # Returns (parsed_frame, raw_frame_bytes) or None.
        while True:
            if len(self._buf) < 4:
                return None

            # Resync on MAGIC.
            mi = self._buf.find(MAGIC)
            if mi == -1:
                self._buf.clear()
                return None
            if mi > 0:
                del self._buf[:mi]
                if len(self._buf) < 4:
                    return None

            inner_len = struct.unpack_from("<H", self._buf, 2)[0]
            if inner_len < 10 or inner_len > self._max_frame:
                # Drop first byte and resync.
                del self._buf[:1]
                continue

            total_len = 4 + inner_len
            if len(self._buf) < total_len:
                return None

            raw = bytes(self._buf[:total_len])
            ver, typ, conn, port, paylen = struct.unpack_from("<BBHHH", raw, 4)
            if ver != VER or (8 + paylen + 2) != inner_len:
                del self._buf[:1]
                continue

            payload = raw[12 : 12 + paylen]
            want_crc = struct.unpack_from("<H", raw, 12 + paylen)[0]
            crc = 0xFFFF
            crc = crc16_ccitt(raw[4:12], crc)
            crc = crc16_ccitt(payload, crc)
            if crc != want_crc:
                del self._buf[:1]
                continue

            del self._buf[:total_len]
            return Frame(type=typ, conn=conn, port=port, payload=payload), raw


def encode_frame(typ: int, conn: int, port: int, payload: bytes) -> bytes:
    if payload is None:
        payload = b""
    hdr = struct.pack("<BBHHH", VER, typ, conn & 0xFFFF, port & 0xFFFF, len(payload) & 0xFFFF)
    crc = 0xFFFF
    crc = crc16_ccitt(hdr, crc)
    crc = crc16_ccitt(payload, crc)
    inner_len = len(hdr) + len(payload) + 2
    pre = MAGIC + struct.pack("<H", inner_len)
    return pre + hdr + payload + struct.pack("<H", crc)
