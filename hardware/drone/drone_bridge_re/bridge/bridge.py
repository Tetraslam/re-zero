import argparse
import json
import threading
import time
import queue
from pathlib import Path
from typing import Dict, Optional, Tuple, Callable

import serial
from serial.tools import list_ports

from .serial_frame import Decoder, Frame, SfType


def _now() -> float:
    return time.time()

def _hex_head(b: bytes, n: int = 32) -> str:
    if not b:
        return ""
    return b[:n].hex()


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


def pump(name: str, src: serial.Serial, dst: serial.Serial, log, stop_evt: threading.Event, print_logs: bool, print_hello: bool, cap: Optional[CaptureWriter]):
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
    ap.add_argument("--tap-udp", type=int, default=30, help="Print first N UDP frames per direction (for protocol debugging).")
    ap.add_argument("--tap-tcp", type=int, default=30, help="Print first N TCP_DATA frames per direction (for protocol debugging).")
    ap.add_argument("--tap-bytes", type=int, default=64, help="Bytes of payload to include for --tap-* (hex).")
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
    # Attach tap config to logger callable so pump threads can access without globals.
    try:
        setattr(logger, "_tap_udp_left", int(args.tap_udp))  # type: ignore[attr-defined]
        setattr(logger, "_tap_tcp_left", int(args.tap_tcp))  # type: ignore[attr-defined]
        setattr(logger, "_tap_bytes", int(args.tap_bytes))   # type: ignore[attr-defined]
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
    ser_ap = serial.Serial(ap_dev, baudrate=args.baud, timeout=0, write_timeout=0.2, dsrdtr=False, rtscts=False)
    ser_sta = serial.Serial(sta_dev, baudrate=args.baud, timeout=0, write_timeout=0.2, dsrdtr=False, rtscts=False)
    # Avoid toggling lines that can reset ESP32 on some USB-serial adapters.
    try:
        ser_ap.dtr = False
        ser_ap.rts = False
    except Exception:
        pass
    try:
        ser_sta.dtr = False
        ser_sta.rts = False
    except Exception:
        pass

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
    t1 = threading.Thread(target=pump, args=("AP->STA", ser_ap, ser_sta, logger, stop_evt, print_logs, args.print_hello, cap), daemon=True)
    t2 = threading.Thread(target=pump, args=("STA->AP", ser_sta, ser_ap, logger, stop_evt, print_logs, args.print_hello, cap), daemon=True)
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


if __name__ == "__main__":
    main()
