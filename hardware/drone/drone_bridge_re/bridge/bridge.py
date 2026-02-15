import argparse
import json
import os
import re
import threading
import time
import queue
from pathlib import Path
from typing import Dict, Optional, Tuple, Callable

import serial
from serial.tools import list_ports
import termios

from .serial_frame import Decoder, Frame, SfType


def _now() -> float:
    return time.time()

def _hex_head(b: bytes, n: int = 32) -> str:
    if not b:
        return ""
    return b[:n].hex()

def _disable_hupcl(ser: serial.Serial, label: str) -> None:
    """
    Many ESP32 dev boards auto-reset when the serial port is opened/closed due to
    DTR/RTS wiring. Disabling HUPCL reduces resets on close/reopen by preventing
    the kernel from dropping modem control lines on last close.
    """
    try:
        fd = ser.fileno()
        attr = termios.tcgetattr(fd)
        # c_cflag is index 2.
        attr[2] = attr[2] & ~termios.HUPCL
        termios.tcsetattr(fd, termios.TCSANOW, attr)
    except Exception:
        # Best-effort only; never fail the bridge because of this.
        return


def _typ_name(t: int) -> str:
    return {
        SfType.HELLO: "HELLO",
        SfType.LOG: "LOG",
        SfType.UDP: "UDP",
        SfType.TCP_OPEN: "TCP_OPEN",
        SfType.TCP_OPEN_OK: "TCP_OPEN_OK",
        SfType.TCP_OPEN_FAIL: "TCP_OPEN_FAIL",
        SfType.TCP_DATA: "TCP_DATA",
        SfType.TCP_CLOSE: "TCP_CLOSE",
    }.get(t, f"0x{t:02x}")


def scan_ports(baud: int, timeout_s: float = 3.0) -> Tuple[str, str]:
    # Identify AP and STA ports by waiting for periodic HELLO frames.
    candidates = [p.device for p in list_ports.comports()]
    if not candidates:
        raise SystemExit("No serial ports found.")

    found: Dict[str, str] = {}  # role -> device
    for dev in candidates:
        try:
            ser = serial.Serial(dev, baudrate=baud, timeout=0.1, write_timeout=0.1)
        except Exception:
            continue
        dec = Decoder()
        try:
            deadline = _now() + timeout_s
            while _now() < deadline and len(found) < 2:
                data = ser.read(4096)
                if data:
                    dec.feed(data)
                    while True:
                        out = dec.pop()
                        if not out:
                            break
                        fr, _raw = out
                        if fr.type != SfType.HELLO:
                            continue
                        try:
                            who = fr.payload.decode("ascii", errors="ignore").strip()
                        except Exception:
                            who = ""
                        if who in ("AP", "STA") and who not in found:
                            found[who] = dev
                            break
                else:
                    time.sleep(0.02)
        finally:
            ser.close()

    if "AP" not in found or "STA" not in found:
        raise SystemExit(f"Auto-scan failed. Found roles: {found}. Pass --ap and --sta explicitly.")
    return found["AP"], found["STA"]

def identify_role(ser: serial.Serial, timeout_s: float = 2.6) -> Optional[str]:
    dec = Decoder()
    deadline = _now() + timeout_s
    while _now() < deadline:
        n = getattr(ser, "in_waiting", 0) or 0
        data = ser.read(n if n else 4096)
        if data:
            dec.feed(data)
            while True:
                out = dec.pop()
                if not out:
                    break
                fr, _raw = out
                if fr.type != SfType.HELLO:
                    continue
                try:
                    who = fr.payload.decode("ascii", errors="ignore").strip()
                except Exception:
                    who = ""
                if who in ("AP", "STA"):
                    return who
        else:
            time.sleep(0.01)
    return None


def make_logger(logdir: Path, enabled: bool) -> Callable[[str, str, Frame], None]:
    if not enabled:
        def _noop(_direction: str, _dev: str, _fr: Frame) -> None:
            return
        return _noop

    logdir.mkdir(parents=True, exist_ok=True)
    fp = (logdir / f"bridge_{int(time.time())}.jsonl").open("a", buffering=1024 * 1024)
    q: "queue.Queue[dict]" = queue.Queue(maxsize=10000)
    stop = threading.Event()

    def _worker():
        last_flush = _now()
        while not stop.is_set():
            try:
                rec = q.get(timeout=0.2)
            except queue.Empty:
                rec = None
            if rec is not None:
                fp.write(json.dumps(rec) + "\n")
            now = _now()
            if now - last_flush > 1.0:
                fp.flush()
                last_flush = now

    t = threading.Thread(target=_worker, name="jsonl-logger", daemon=True)
    t.start()

    def log(direction: str, dev: str, fr: Frame):
        rec = {
            "ts": _now(),
            "dir": direction,
            "dev": dev,
            "type": _typ_name(fr.type),
            "conn": fr.conn,
            "port": fr.port,
            "len": len(fr.payload),
            "payload_hex": fr.payload[:96].hex(),
        }
        try:
            q.put_nowait(rec)
        except queue.Full:
            # Drop logs under load to preserve latency.
            pass

    # Expose a best-effort atexit style stopper via attribute.
    log._stop = stop  # type: ignore[attr-defined]
    log._fp = fp      # type: ignore[attr-defined]
    return log


class ProtoLogger:
    """
    Focused protocol logger for reverse engineering.

    Writes a compact JSONL stream of:
    - phone -> drone commands (UDP 40000/50000, TCP 7060/8060/9060)
    - drone -> phone non-video telemetry (UDP 40000/50000, TCP responses)

    This is separate from the generic bridge JSONL to keep the data set small and
    easy to diff between test runs.
    """

    def __init__(self, logdir: Path) -> None:
        logdir.mkdir(parents=True, exist_ok=True)
        self.path = logdir / f"proto_{int(time.time())}.jsonl"
        self._fp = self.path.open("a", buffering=1024 * 1024)
        self._q: "queue.Queue[dict]" = queue.Queue(maxsize=20000)
        self._stop = threading.Event()
        self._t0 = _now()

        def _worker() -> None:
            last_flush = _now()
            while not self._stop.is_set():
                try:
                    rec = self._q.get(timeout=0.2)
                except queue.Empty:
                    rec = None
                if rec is not None:
                    self._fp.write(json.dumps(rec) + "\n")
                now = _now()
                if now - last_flush > 1.0:
                    try:
                        self._fp.flush()
                    except Exception:
                        pass
                    last_flush = now

        self._thr = threading.Thread(target=_worker, name="proto-logger", daemon=True)
        self._thr.start()

        self._ssid_re = re.compile(rb"RADCLOFPV_[0-9]+")

    def close(self) -> None:
        try:
            self._stop.set()
        except Exception:
            pass
        try:
            self._fp.flush()
            self._fp.close()
        except Exception:
            pass

    @staticmethod
    def _u16le(b: bytes) -> Optional[int]:
        if len(b) < 2:
            return None
        return int.from_bytes(b[:2], "little", signed=False)

    @staticmethod
    def _u16be(b: bytes) -> Optional[int]:
        if len(b) < 2:
            return None
        return int.from_bytes(b[:2], "big", signed=False)

    @staticmethod
    def _u32le(b: bytes) -> Optional[int]:
        if len(b) < 4:
            return None
        return int.from_bytes(b[:4], "little", signed=False)

    @staticmethod
    def _u32be(b: bytes) -> Optional[int]:
        if len(b) < 4:
            return None
        return int.from_bytes(b[:4], "big", signed=False)

    def want(self, direction: str, fr: Frame) -> bool:
        # direction is the pump name: "AP->STA" or "STA->AP".
        if fr.type == SfType.UDP and fr.port in (40000, 50000):
            return True
        if fr.type in (SfType.TCP_OPEN, SfType.TCP_OPEN_OK, SfType.TCP_OPEN_FAIL, SfType.TCP_CLOSE, SfType.TCP_DATA) and fr.port in (7060, 8060, 9060):
            return True
        return False

    def _parse_udp_cc(self, payload: bytes) -> dict:
        # Many observed UDP payloads start with 0x63 0x63 ("cc").
        out: dict = {}
        if len(payload) >= 2 and payload[0] == 0x63 and payload[1] == 0x63:
            out["cc"] = True
            if len(payload) >= 3:
                out["cc_type_u8"] = payload[2]
            if len(payload) >= 4:
                out["cc_b3_u8"] = payload[3]
            if len(payload) >= 5:
                out["cc_u16le_3"] = self._u16le(payload[3:5])
            if len(payload) >= 7:
                out["cc_u16le_5"] = self._u16le(payload[5:7])
            if len(payload) >= 7:
                out["cc_u32le_3"] = self._u32le(payload[3:7])
        return out

    def _parse_tcp_lewei(self, payload: bytes) -> dict:
        out: dict = {}
        if payload.startswith(b"lewei_cmd"):
            out["lewei_cmd"] = True
            # Heuristic: the next two bytes appear to be a big-endian u16 command type
            # (observed 0x0001, 0x0002, 0x0004).
            if len(payload) >= 11:
                out["cmd_type_u16be"] = self._u16be(payload[9:11])
            if len(payload) >= 15:
                out["cmd_word0_u32be"] = self._u32be(payload[11:15])
        return out

    def _extract_ssid(self, payload: bytes) -> Optional[str]:
        m = self._ssid_re.search(payload)
        if not m:
            return None
        try:
            return m.group(0).decode("ascii", errors="replace")
        except Exception:
            return None

    def emit(self, direction: str, dev: str, fr: Frame) -> None:
        if not self.want(direction, fr):
            return

        flow: str
        if direction == "AP->STA":
            flow = "phone->drone"
        elif direction == "STA->AP":
            flow = "drone->phone"
        else:
            flow = direction

        transport = "udp" if fr.type == SfType.UDP else "tcp"
        typ = _typ_name(fr.type)
        payload = fr.payload or b""

        kind = f"{flow}:{transport}"

        rec: dict = {
            "ts": _now(),
            "t_rel_ms": int((_now() - self._t0) * 1000),
            "flow": flow,
            "kind": kind,
            "sf_dir": direction,
            "dev": dev,
            "transport": transport,
            "sf_type": typ,
            "conn": fr.conn,
            "port": fr.port,
            "len": len(payload),
        }

        # Payload capture: full for small messages, truncated otherwise.
        if payload:
            if len(payload) <= 512:
                rec["payload_hex"] = payload.hex()
            else:
                rec["payload_head_hex"] = payload[:128].hex()

        if transport == "udp":
            # For UDP:
            # - phone->drone: conn = phone_src_port, port = drone_dst_port
            # - drone->phone: conn = phone_dst_port, port = drone_src_port
            if flow == "phone->drone":
                rec["phone_src_port"] = fr.conn
                rec["drone_dst_port"] = fr.port
            elif flow == "drone->phone":
                rec["phone_dst_port"] = fr.conn
                rec["drone_src_port"] = fr.port
            rec.update(self._parse_udp_cc(payload))
            # Convenience: treat bytes[2:4] as an opcode-like field (u16le) when present.
            if len(payload) >= 4:
                rec["cc_opcode_u16le_2"] = self._u16le(payload[2:4])
            ssid = self._extract_ssid(payload)
            if ssid:
                rec["ssid"] = ssid
        else:
            rec["tcp_port"] = fr.port
            rec.update(self._parse_tcp_lewei(payload))

        try:
            self._q.put_nowait(rec)
        except queue.Full:
            # Drop under load; protocol logging must not affect forwarding latency.
            pass


class CaptureWriter:
    """
    Writes raw framed bytes to disk for later offline decoding.
    Intended to capture handshake/control traffic without relying on stdout taps.
    """

    def __init__(self, logdir: Path):
        logdir.mkdir(parents=True, exist_ok=True)
        self.path = logdir / f"capture_{int(time.time())}.sf.bin"
        self._fp = self.path.open("ab", buffering=1024 * 1024)
        self._lock = threading.Lock()
        self._bytes = 0
        self._max_bytes = 50 * 1024 * 1024
        self._udp_ports = {40000, 50000}  # exclude 7070 video spam

    def want(self, fr: Frame) -> bool:
        if fr.type in (SfType.TCP_OPEN, SfType.TCP_OPEN_OK, SfType.TCP_OPEN_FAIL, SfType.TCP_DATA, SfType.TCP_CLOSE):
            return True
        if fr.type == SfType.UDP and fr.port in self._udp_ports:
            return True
        return False

    def write(self, fr: Frame, raw: bytes) -> None:
        if not raw:
            return
        if not self.want(fr):
            return
        with self._lock:
            if self._bytes + len(raw) > self._max_bytes:
                return
            self._fp.write(raw)
            self._bytes += len(raw)

    def close(self) -> None:
        with self._lock:
            try:
                self._fp.flush()
                self._fp.close()
            except Exception:
                pass


def pump(name: str, src: serial.Serial, dst: serial.Serial, log, proto: Optional[ProtoLogger], stop_evt: threading.Event, print_logs: bool, print_hello: bool, cap: Optional[CaptureWriter]):
    dec = Decoder()
    tap_udp_left = 0
    tap_tcp_left = 0
    tap_bytes = 0
    tap_ports: Optional[set[int]] = None
    # Video is huge (UDP src port 7070). Bridging it over two USB serial links at 921600 baud
    # is not physically possible at full rate. Rate-limit so the app can at least show a few FPS.
    video_port = 7070
    video_pps = 25  # packets per second forwarded per pump direction
    video_tokens = float(video_pps)
    video_last = _now()
    # Optional attributes set by main() for low-overhead packet peeks.
    try:
        tap_udp_left = getattr(log, "_tap_udp_left", 0)  # type: ignore[attr-defined]
        tap_tcp_left = getattr(log, "_tap_tcp_left", 0)  # type: ignore[attr-defined]
        tap_bytes = getattr(log, "_tap_bytes", 32)        # type: ignore[attr-defined]
        tap_ports = getattr(log, "_tap_ports", None)      # type: ignore[attr-defined]
    except Exception:
        pass

    # Rate-limited live prints for command RE (stdout should not become the log).
    # Commands are fully captured in proto_*.jsonl; stdout is a concise view.
    cmd_last_by_key: Dict[Tuple[int, int], bytes] = {}
    cmd_rep_by_key: Dict[Tuple[int, int], int] = {}
    cmd_last_print_by_key: Dict[Tuple[int, int], float] = {}
    cmd_repeat_flush_s = 1.0  # emit a summary for repeats at most once per second
    cmd_print_static = False
    try:
        cmd_print_static = bool(getattr(log, "_cmd_print_static", False))  # type: ignore[attr-defined]
    except Exception:
        cmd_print_static = False

    tel_last_print_s = 0.0
    tel_min_interval_s = 1.0  # show at most ~1 drone->phone packet per second

    while not stop_evt.is_set():
        try:
            n = getattr(src, "in_waiting", 0) or 0
            if n <= 0:
                time.sleep(0.0005)
                continue
            data = src.read(n)
        except Exception:
            break

        dec.feed(data)
        while True:
            out = dec.pop()
            if not out:
                break
            fr, raw = out
            if cap is not None:
                try:
                    cap.write(fr, raw)
                except Exception:
                    pass
            if fr.type == SfType.LOG:
                if print_logs:
                    try:
                        txt = fr.payload.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        txt = fr.payload.hex()
                    # Keep stdout useful: suppress repetitive Wi-Fi heartbeat spam by default.
                    if txt.startswith("wifi: hb"):
                        pass
                    else:
                        print(f"[{name}] {src.port} LOG: {txt}", flush=True)
            elif fr.type == SfType.HELLO:
                if print_hello:
                    try:
                        who = fr.payload.decode("ascii", errors="replace").strip()
                    except Exception:
                        who = fr.payload.hex()
                    print(f"[{name}] {src.port} HELLO: {who}", flush=True)
            elif fr.type == SfType.UDP:
                if name == "STA->AP" and fr.port == video_port:
                    now = _now()
                    dt = now - video_last
                    if dt > 0:
                        video_tokens = min(float(video_pps), video_tokens + dt * float(video_pps))
                        video_last = now
                    if video_tokens < 1.0:
                        # Drop excess video packets to keep control plane responsive.
                        continue
                    video_tokens -= 1.0
                if tap_udp_left > 0 and (tap_ports is None or fr.port in tap_ports):
                    tap_udp_left -= 1
                    print(
                        f"[{name}] {src.port} UDP conn={fr.conn} port={fr.port} len={len(fr.payload)} head={_hex_head(fr.payload, tap_bytes)}",
                        flush=True,
                    )
                # Phone->drone commands (stdout):
                # - Default: only print on payload change (so neutral/static repeats don't spam).
                # - Optional: if cmd_print_static is enabled, also print repeat summaries.
                if name == "AP->STA" and fr.port in (40000, 50000):
                    now = _now()
                    p = fr.payload or b""
                    key = (fr.conn, fr.port)
                    prev = cmd_last_by_key.get(key)

                    if prev is None:
                        cmd_last_by_key[key] = p
                        cmd_rep_by_key[key] = 1
                        cmd_last_print_by_key[key] = now
                        op = None
                        if len(p) >= 4 and p[0] == 0x63 and p[1] == 0x63:
                            op = int.from_bytes(p[2:4], "little", signed=False)
                        op_s = f" op=0x{op:04x}" if op is not None else ""
                        print(f"[CMD] udp dst={fr.port} phone_src={fr.conn} len={len(p)}{op_s} head={_hex_head(p, 24)}", flush=True)
                    elif p == prev:
                        cmd_rep_by_key[key] = cmd_rep_by_key.get(key, 1) + 1
                        if cmd_print_static:
                            last_p = cmd_last_print_by_key.get(key, 0.0)
                            if now - last_p >= cmd_repeat_flush_s:
                                reps = cmd_rep_by_key.get(key, 1)
                                op = None
                                if len(p) >= 4 and p[0] == 0x63 and p[1] == 0x63:
                                    op = int.from_bytes(p[2:4], "little", signed=False)
                                op_s = f" op=0x{op:04x}" if op is not None else ""
                                print(
                                    f"[CMD] udp dst={fr.port} phone_src={fr.conn} len={len(p)}{op_s} head={_hex_head(p, 24)} (x{reps})",
                                    flush=True,
                                )
                                cmd_rep_by_key[key] = 0
                                cmd_last_print_by_key[key] = now
                    else:
                        # Payload changed: emit previous repeat count if we haven't already, then emit new payload.
                        reps = cmd_rep_by_key.get(key, 0)
                        if cmd_print_static and reps > 1:
                            print(f"[CMD] udp dst={fr.port} phone_src={fr.conn} (previous repeated x{reps})", flush=True)
                        cmd_last_by_key[key] = p
                        cmd_rep_by_key[key] = 1
                        cmd_last_print_by_key[key] = now
                        op = None
                        if len(p) >= 4 and p[0] == 0x63 and p[1] == 0x63:
                            op = int.from_bytes(p[2:4], "little", signed=False)
                        op_s = f" op=0x{op:04x}" if op is not None else ""
                        print(f"[CMD] udp dst={fr.port} phone_src={fr.conn} len={len(p)}{op_s} head={_hex_head(p, 24)}", flush=True)

                # Show a small sample of drone->phone telemetry (non-video).
                if name == "STA->AP" and fr.port in (40000, 50000):
                    now = _now()
                    if now - tel_last_print_s >= tel_min_interval_s:
                        tel_last_print_s = now
                        p = fr.payload or b""
                        cc = (len(p) >= 2 and p[0] == 0x63 and p[1] == 0x63)
                        cc_type = p[2] if len(p) >= 3 else None
                        cc_s = f" cc_type=0x{cc_type:02x}" if (cc and cc_type is not None) else ""
                        print(
                            f"[TEL] udp src={fr.port} phone_dst={fr.conn} len={len(p)}{cc_s} head={_hex_head(p, 24)}",
                            flush=True,
                        )
                try:
                    dst.write(raw)
                except Exception:
                    stop_evt.set()
                    break
            elif fr.type == SfType.TCP_DATA:
                if tap_tcp_left > 0 and (tap_ports is None or fr.port in tap_ports):
                    tap_tcp_left -= 1
                    print(
                        f"[{name}] {src.port} TCP_DATA conn={fr.conn} port={fr.port} len={len(fr.payload)} head={_hex_head(fr.payload, tap_bytes)}",
                        flush=True,
                    )
                try:
                    dst.write(raw)
                except Exception:
                    stop_evt.set()
                    break
            else:
                try:
                    dst.write(raw)
                except Exception:
                    stop_evt.set()
                    break
            if proto is not None:
                try:
                    proto.emit(name, src.port, fr)
                except Exception:
                    pass
            try:
                log(name, src.port, fr)
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser()
    # User preference: don't require CLI flags for useful output. Defaults are set to a
    # "debug but flyable" level; you can still override via args if needed.
    ap.add_argument("--ap", default="/dev/ttyUSB0", help="AP ESP32 serial device (default: /dev/ttyUSB0; falls back to auto-scan if missing)")
    ap.add_argument("--sta", default="/dev/ttyUSB1", help="STA ESP32 serial device (default: /dev/ttyUSB1; falls back to auto-scan if missing)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--logdir", default="logs")
    ap.add_argument("--no-print-logs", action="store_true", help="Disable printing of LOG frames to stdout.")
    ap.add_argument("--print-hello", action="store_true", help="Also print HELLO frames (usually noise/backlog).")
    ap.add_argument("--print-cmd-static", action="store_true", help="Also print repeated/static phone->drone command packets (normally suppressed).")
    ap.add_argument("--tap-udp", type=int, default=0, help="Print first N UDP frames per direction (for protocol debugging).")
    ap.add_argument("--tap-tcp", type=int, default=0, help="Print first N TCP_DATA frames per direction (for protocol debugging).")
    ap.add_argument("--tap-bytes", type=int, default=48, help="Bytes of payload to include for --tap-* (hex).")
    ap.add_argument("--tap-ports", default="40000,50000,7070,7060,8060,9060", help="Comma-separated destination ports filter for --tap-*.")
    ap.add_argument("--no-jsonl", action="store_true", help="Disable JSONL logging to disk (lower latency).")
    ap.add_argument("--no-autofix-roles", action="store_true", help="Disable auto-swapping if --ap/--sta are swapped.")
    args = ap.parse_args()

    ap_dev = args.ap
    sta_dev = args.sta
    # If the default devices aren't present (or user passed None somehow), fall back to auto-scan.
    if not ap_dev or not sta_dev or (not Path(ap_dev).exists()) or (not Path(sta_dev).exists()):
        ap_dev, sta_dev = scan_ports(args.baud)

    logdir = Path(args.logdir)
    logger = make_logger(logdir, enabled=(not args.no_jsonl))
    cap = CaptureWriter(logdir)
    proto = ProtoLogger(logdir)
    # Attach tap config to logger callable so pump threads can access without globals.
    try:
        setattr(logger, "_tap_udp_left", int(args.tap_udp))  # type: ignore[attr-defined]
        setattr(logger, "_tap_tcp_left", int(args.tap_tcp))  # type: ignore[attr-defined]
        setattr(logger, "_tap_bytes", int(args.tap_bytes))   # type: ignore[attr-defined]
        setattr(logger, "_cmd_print_static", bool(args.print_cmd_static))  # type: ignore[attr-defined]
        ports = set()
        if args.tap_ports.strip():
            for part in args.tap_ports.split(","):
                part = part.strip()
                if not part:
                    continue
                ports.add(int(part))
        setattr(logger, "_tap_ports", ports if ports else None)  # type: ignore[attr-defined]
    except Exception:
        pass

    print(f"bridge: ap={ap_dev} sta={sta_dev} baud={args.baud} logdir={logdir} capture={cap.path}", flush=True)
    # timeout=0 (non-blocking) for lowest latency. Use in_waiting to avoid busy waits.
    ser_ap = serial.Serial(ap_dev, baudrate=args.baud, timeout=0, write_timeout=0.2, dsrdtr=False, rtscts=False, exclusive=True)
    ser_sta = serial.Serial(sta_dev, baudrate=args.baud, timeout=0, write_timeout=0.2, dsrdtr=False, rtscts=False, exclusive=True)
    _disable_hupcl(ser_ap, "ap")
    _disable_hupcl(ser_sta, "sta")

    role_ap = identify_role(ser_ap, timeout_s=6.0)
    role_sta = identify_role(ser_sta, timeout_s=6.0)
    print(f"bridge: roles ap_role={role_ap} sta_role={role_sta}", flush=True)
    if not args.no_autofix_roles:
        if role_ap == "STA" and role_sta == "AP":
            print("bridge: warning: --ap/--sta appear swapped; auto-swapping", flush=True)
            ser_ap, ser_sta = ser_sta, ser_ap
            ap_dev, sta_dev = sta_dev, ap_dev
            role_ap, role_sta = role_sta, role_ap
        elif role_ap is not None and role_sta is not None and role_ap == role_sta:
            print("bridge: warning: both ports report the same role; you may have flashed the same sketch to both ESP32s", flush=True)
        elif role_ap is None or role_sta is None:
            print("bridge: note: role detect incomplete (no HELLO seen within timeout); continuing anyway", flush=True)

    stop_evt = threading.Event()
    print_logs = (not args.no_print_logs)
    print(f"bridge: proto_log={proto.path}", flush=True)
    t1 = threading.Thread(target=pump, args=("AP->STA", ser_ap, ser_sta, logger, proto, stop_evt, print_logs, args.print_hello, cap), daemon=True)
    t2 = threading.Thread(target=pump, args=("STA->AP", ser_sta, ser_ap, logger, proto, stop_evt, print_logs, args.print_hello, cap), daemon=True)
    t1.start()
    t2.start()

    try:
        while t1.is_alive() and t2.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        try:
            ser_ap.close()
        except Exception:
            pass
        try:
            ser_sta.close()
        except Exception:
            pass
        try:
            stop = getattr(logger, "_stop", None)
            fp = getattr(logger, "_fp", None)
            if stop is not None:
                stop.set()
            if fp is not None:
                fp.flush()
                fp.close()
        except Exception:
            pass
        try:
            cap.close()
        except Exception:
            pass
        try:
            proto.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
