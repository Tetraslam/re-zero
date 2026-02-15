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

## Build / Flash

Arduino CLI is assumed (`arduino-cli`) with an ESP32 core installed.

1. Flash AP ESP32 (spoof SSID `RADCLOFPV_676767`) on `/dev/ttyUSB0`:

```bash
make ap_flash
```

2. Flash STA ESP32 (joins drone SSID `RADCLOFPV_839819`) on `/dev/ttyUSB1`:

```bash
make sta_flash
```

## Run Bridge

This repo is `uv`-friendly.

```bash
uv sync
uv run drone-bridge --ap /dev/ttyUSB0 --sta /dev/ttyUSB1 --baud 921600 --logdir logs
```

If you omit `--ap/--sta`, the bridge will try to  auto-detect the ports by waiting for periodic `HELLO` frames from each ESP32.
