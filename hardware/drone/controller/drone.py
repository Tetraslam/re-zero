import socket
import threading
import time
from dataclasses import dataclass


DRONE_IP_DEFAULT = "192.168.0.1"
DRONE_UDP_PORT = 40000

# These match what we observed in the phone->drone traffic:
# - heartbeat stream from UDP src port 6000
# - control stream from UDP src port 5010
HB_SRC_PORT = 6000
CTRL_SRC_PORT = 5010

HB_PAYLOAD = bytes.fromhex("63630100000000")  # cc opcode 0x0001

FLAG_TAKEOFF = 0x01
FLAG_LAND = 0x02
FLAG_ESTOP = 0x04
FLAG_GYRO_CALIB = 0x10
FLAG_HEADLESS = 0x80


def build_cc_control(x: int = 0x80, y: int = 0x80, z: int = 0x80, w: int = 0x80, flags: int = 0x00) -> bytes:
    """
    cc opcode 0x000a (15 bytes):
      63 63 0a 00 00 08 00 66  x y z w  flags  xor  99
    """
    x &= 0xFF
    y &= 0xFF
    z &= 0xFF
    w &= 0xFF
    flags &= 0xFF
    p = bytearray(15)
    p[0:2] = b"cc"
    p[2:4] = (0x000A).to_bytes(2, "little")
    p[4] = 0x00
    p[5:7] = (0x0008).to_bytes(2, "little")
    p[7] = 0x66
    p[8] = x
    p[9] = y
    p[10] = z
    p[11] = w
    p[12] = flags
    p[13] = p[8] ^ p[9] ^ p[10] ^ p[11] ^ p[12]
    p[14] = 0x99
    return bytes(p)


def _mk_udp_socket(bind_ip: str, bind_port: int, connect_dst: tuple[str, int]) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    s.bind((bind_ip, bind_port))
    # UDP connect so the kernel picks an egress route and a concrete source IP.
    s.connect(connect_dst)
    s.setblocking(False)
    return s


@dataclass
class Axes:
    x: int = 0x80
    y: int = 0x80
    z: int = 0x80
    w: int = 0x80
    flags: int = 0x00


class DroneLink:
    """
    Notebook-friendly controller:
    - call .start() once (starts heartbeat + control loops)
    - call .set_axes() / .pulse_flags() / .takeoff() / .land() from other cells
    """

    def __init__(
        self,
        drone_ip: str = DRONE_IP_DEFAULT,
        bind_ip: str = "0.0.0.0",
        hb_hz: float = 1.0,
        ctrl_hz: float = 22.3,
        verbose: bool = True,
    ) -> None:
        self.drone_ip = drone_ip
        self.bind_ip = bind_ip
        self.hb_hz = float(hb_hz)
        self.ctrl_hz = float(ctrl_hz)
        self.verbose = bool(verbose)

        self._dst = (self.drone_ip, DRONE_UDP_PORT)
        self._hb_sock: socket.socket | None = None
        self._ctrl_sock: socket.socket | None = None

        self._axes = Axes()
        self._axes_lock = threading.Lock()

        self._stop_evt = threading.Event()
        self._tel_evt = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self, wait_for_telemetry: bool = True, telemetry_timeout_s: float = 3.0) -> "DroneLink":
        if self._hb_sock is not None or self._ctrl_sock is not None:
            raise RuntimeError("already started")

        self._hb_sock = _mk_udp_socket(self.bind_ip, HB_SRC_PORT, self._dst)
        self._ctrl_sock = _mk_udp_socket(self.bind_ip, CTRL_SRC_PORT, self._dst)

        if self.verbose:
            print(f"[HB] local={self._hb_sock.getsockname()} -> {self.drone_ip}:{DRONE_UDP_PORT} hz={self.hb_hz}", flush=True)
            print(f"[CTRL] local={self._ctrl_sock.getsockname()} -> {self.drone_ip}:{DRONE_UDP_PORT} hz={self.ctrl_hz}", flush=True)

        self._stop_evt.clear()
        self._tel_evt.clear()

        t_hb = threading.Thread(target=self._hb_loop, name="drone-hb", daemon=True)
        t_rx = threading.Thread(target=self._rx_loop, name="drone-rx", daemon=True)
        t_ctrl = threading.Thread(target=self._ctrl_loop, name="drone-ctrl", daemon=True)
        self._threads = [t_hb, t_rx, t_ctrl]
        for t in self._threads:
            t.start()

        if wait_for_telemetry:
            if self.verbose:
                print("[CTRL] waiting for telemetry...", flush=True)
            ok = self._tel_evt.wait(timeout=float(telemetry_timeout_s))
            if self.verbose:
                print(f"[CTRL] telemetry {'seen' if ok else 'NOT seen'}; control stream running", flush=True)
        return self

    def stop(self) -> None:
        self._stop_evt.set()
        for t in self._threads:
            t.join(timeout=0.3)
        self._threads.clear()
        if self._hb_sock is not None:
            try:
                self._hb_sock.close()
            except Exception:
                pass
            self._hb_sock = None
        if self._ctrl_sock is not None:
            try:
                self._ctrl_sock.close()
            except Exception:
                pass
            self._ctrl_sock = None

    def set_axes(self, *, x: int | None = None, y: int | None = None, z: int | None = None, w: int | None = None, flags: int | None = None) -> None:
        with self._axes_lock:
            if x is not None:
                self._axes.x = int(x) & 0xFF
            if y is not None:
                self._axes.y = int(y) & 0xFF
            if z is not None:
                self._axes.z = int(z) & 0xFF
            if w is not None:
                self._axes.w = int(w) & 0xFF
            if flags is not None:
                self._axes.flags = int(flags) & 0xFF

    def neutral(self) -> None:
        self.set_axes(x=0x80, y=0x80, z=0x80, w=0x80, flags=0x00)

    def pulse_flags(self, flags: int, duration_s: float = 0.35) -> None:
        flags &= 0xFF
        with self._axes_lock:
            old = self._axes.flags
            self._axes.flags = flags
        time.sleep(float(duration_s))
        with self._axes_lock:
            self._axes.flags = old

    def takeoff(self, duration_s: float = 0.35) -> None:
        self.pulse_flags(FLAG_TAKEOFF, duration_s=duration_s)

    def land(self, duration_s: float = 0.35) -> None:
        self.pulse_flags(FLAG_LAND, duration_s=duration_s)

    def estop(self, duration_s: float = 0.35) -> None:
        self.pulse_flags(FLAG_ESTOP, duration_s=duration_s)

    def gyro_calibrate(self, duration_s: float = 0.7) -> None:
        self.pulse_flags(FLAG_GYRO_CALIB, duration_s=duration_s)

    def _hb_loop(self) -> None:
        assert self._hb_sock is not None
        if self.hb_hz <= 0:
            return
        dt = 1.0 / self.hb_hz
        next_t = time.monotonic()
        while not self._stop_evt.is_set():
            now = time.monotonic()
            if now < next_t:
                time.sleep(next_t - now)
            else:
                next_t = now
            next_t += dt
            try:
                self._hb_sock.send(HB_PAYLOAD)
            except Exception:
                time.sleep(0.05)

    def _ctrl_loop(self) -> None:
        assert self._ctrl_sock is not None
        if self.ctrl_hz <= 0:
            return
        dt = 1.0 / self.ctrl_hz
        next_t = time.monotonic()
        while not self._stop_evt.is_set():
            now = time.monotonic()
            if now < next_t:
                time.sleep(next_t - now)
            else:
                next_t = now
            next_t += dt

            with self._axes_lock:
                a = self._axes
                payload = build_cc_control(a.x, a.y, a.z, a.w, a.flags)
            try:
                self._ctrl_sock.send(payload)
            except Exception:
                time.sleep(0.01)

    def _rx_loop(self) -> None:
        assert self._hb_sock is not None
        last_print = 0.0
        while not self._stop_evt.is_set():
            try:
                data, (ip, src_port) = self._hb_sock.recvfrom(4096)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except Exception:
                time.sleep(0.05)
                continue

            if ip != self.drone_ip:
                continue
            if src_port == 7070:
                continue
            if src_port == DRONE_UDP_PORT:
                self._tel_evt.set()

            if self.verbose and (time.time() - last_print) >= 1.0:
                last_print = time.time()
                print(f"[RX] udp src={src_port} len={len(data)} head={data[:16].hex()}", flush=True)


def start_drone(drone_ip: str = DRONE_IP_DEFAULT, *, verbose: bool = True) -> DroneLink:
    return DroneLink(drone_ip=drone_ip, verbose=verbose).start()

