## Goal

- We have two ESP32s connected to this computer.
- We have an iPhone with the RADCLOFPV app that, when the phone is connected to the drone's Wi-Fi, can control the drone through a specialized protocol.

## What we want

- ESP32 #1 = spoof AP endpoint: advertises SSID RADCLOFPV_676767, IP 192.168.0.1, listens on UDP 40000/50000 + TCP 7060/8060/9060, forwards everything over USB serial (binary framed) to the host (laptop)
- ESP32 #2 = drone STA endpoint: joins the real drone SSID (which is RADCLOFPV_839819), opens outbound UDP/TCP to the drone, forwards everything received from ESP32 #1 over USB serial (same framing) to send to the drone over Wi-Fi.
- Framework = Python bridge: connects to both serial ports, auto-scans then bridges TCP/UDP both directions and creates logs.
- Common serial protocol

## Notes from inital research

- App sends UDP 6000 -> 40000 with 7-byte packets starting 63 63 ... (0100, 0501, 0502 variants).
- App uses “lewei” framing over TCP:
  - 7060: lewei_cmd type 2 then repeating type 1 heartbeats.
  - 8060: lewei_cmd type 4 frames (54 bytes in our capture).
- SSID collision: AP and real drone should NOT have the same SSD; use RADCLOFPV_676767 as the spoof AP's SSID

## Where we are now

- Ports: AP ESP32 is /dev/ttyUSB0, STA ESP32 is /dev/ttyUSB1.
- After you implement, I want to be able to connect my phone to RADCLOFPV_676767 and open the RADCLOFPV app and fly the drone.

## Status (working)

As of `logs/serial_07.txt`, phone control works end-to-end:

`iPhone app -> ESP32 AP (RADCLOFPV_676767) -> USB serial -> host bridge -> USB serial -> ESP32 STA (joins RADCLOFPV_839819) -> drone`

Key evidence in the logs:

- Phone sends UDP control to `40000` (e.g. `udp: first_rx ... -> 40000 len=7`).
- Drone responds on UDP `40000` (STA logs `udp: first_rx_from_drone(nonvideo) ... port=40000 len=106`).
- AP forwards that response back to the phone (AP logs `udp: first_tx ... src=40000 len=106`).
- Drone video (`UDP src port 7070`) is intentionally dropped at the STA (`udp: drop_video ...`), and the drop counter climbs (`udp_drop_video=...`) so UART bandwidth stays available for control-plane traffic.

### Differences that made it work

1. **Drop drone video on the STA (UDP src port `7070`).**
   - Forwarding JPEG video over `921600` baud serial will saturate the link and introduce massive latency/jitter.
   - We now drop `7070` at the STA and log `udp_drop_video` in the heartbeat.

2. **Stable TCP connection IDs per listening port.**
   - AP now uses `conn_id = listening_port` for TCP (`7060`, `8060`, `9060`) instead of the phone's ephemeral source port.
   - This stops connection churn and keeps the STA side state stable across app reconnects.

3. **Stop upstream thrash on phone reconnect.**
   - When the app reconnects to the AP TCP server, the AP replaces the phone-side socket without forcing an upstream close.

4. **STA retries TCP connects without tearing down state.**
   - The STA no longer causes the AP to close phone TCP just because the drone-side TCP open failed.
   - TCP connect attempts log timing/bind details (e.g. `dt=... bind_ok=... local=...`) to diagnose drone behavior.

## Build / flash

Arduino CLI is assumed (`arduino-cli`) with an ESP32 core installed.

1. Flash AP ESP32 (spoof SSID `RADCLOFPV_676767`) on `/dev/ttyUSB0`:

```bash
make ap_flash
```

2. Flash STA ESP32 (joins drone SSID `RADCLOFPV_839819`) on `/dev/ttyUSB1`:

```bash
make sta_flash
```

## Run bridge

This repo is `uv`-friendly.

```bash
uv sync
uv run drone-bridge
```

Defaults assume `/dev/ttyUSB0` is AP and `/dev/ttyUSB1` is STA at `921600` baud, and write logs under `logs/`.
