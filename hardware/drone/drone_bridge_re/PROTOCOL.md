# Protocol: ESP32 AP/STA proxy framing and forwarding

This document specifies the on-wire behavior between:

- **ESP32 AP**: spoof access point (`RADCLOFPV_676767`, `192.168.0.1`)
- **ESP32 STA**: station that joins the real drone SSID (`RADCLOFPV_839819`)
- **Host bridge**: a byte-forwarder over two USB serial ports

The goal is to make the phone believe it is talking directly to the drone at `192.168.0.1`, while the proxy forwards control traffic with low latency and provides useful logs.

## Topology and roles

- Phone connects to **ESP32 AP** (SoftAP).
- **ESP32 STA** connects to the **real drone AP** (Wi-Fi station).
- The host connects to both ESP32s via USB serial and forwards framed messages both directions:
  - AP serial <-> host <-> STA serial

## Serial framing (SF)

All traffic between each ESP32 and the host uses a binary frame format. The host bridge forwards frames without needing to interpret payloads.

**Byte order:** little-endian for all u16 fields.

**Frame layout:**

```
magic[2]      = 0xD0 0xB0
inner_len_u16 = number of bytes from ver..crc16 inclusive
ver_u8        = 0x01
type_u8       = message type (SfType)
conn_u16      = connection id (meaning depends on type/direction)
port_u16      = TCP port or UDP port (meaning depends on type/direction)
paylen_u16    = payload length in bytes
payload[...]  = payload bytes
crc16_u16     = CRC16-CCITT (poly 0x1021, init 0xFFFF) over ver..payload
```

**Types:**

- `0x01` `SF_HELLO`: ASCII role string (`AP` or `STA`)
- `0x03` `SF_LOG`: UTF-8 log line (no newline)
- `0x02` `SF_UDP`: UDP datagram
- `0x10` `SF_TCP_OPEN`: request outbound TCP connect on STA
- `0x11` `SF_TCP_OPEN_OK`: outbound TCP connected
- `0x12` `SF_TCP_OPEN_FAIL`: outbound TCP connect failed
- `0x13` `SF_TCP_DATA`: TCP payload bytes
- `0x14` `SF_TCP_CLOSE`: close TCP connection

Implementations:

- ESP32: `esp32_ap/serial_frame.h`, `esp32_sta/serial_frame.h`
- Host: `bridge/serial_frame.py`

## Connection ID conventions

### TCP: stable `conn_id` = listening port

For TCP, the AP assigns a stable `conn_id` equal to the AP listening port:

- `conn_id = 7060` for the app's TCP session to port 7060
- `conn_id = 8060` for the app's TCP session to port 8060
- `conn_id = 9060` for the app's TCP session to port 9060

This avoids churn caused by the phone's ephemeral source ports during reconnect storms.

### UDP: `conn_id` is a phone-side port

For UDP, `conn_id` always represents a phone UDP port:

- Phone -> AP: `conn_id = phone_src_port`
- STA -> AP (drone -> phone): `conn_id = phone_dst_port` (the mirrored port)

## UDP forwarding

### Phone -> AP (Wi-Fi) -> STA (serial)

The AP listens on UDP ports `40000` and `50000`.

When the AP receives a datagram from the phone:

- Input (Wi-Fi):
  - src: `phone_ip:phone_src_port`
  - dst: `192.168.0.1:{40000|50000}`
- Output (serial frame to STA):
  - `type = SF_UDP`
  - `conn = phone_src_port`
  - `port = dst_port` (40000 or 50000)
  - `payload = UDP payload bytes`

The AP also records `last_phone_ip` from the most recent UDP/TCP activity; this IP is used as the destination for drone->phone UDP sends.

### STA -> drone (Wi-Fi)

When the STA receives `SF_UDP` from serial:

- `conn` is interpreted as `phone_src_port`
- `port` is interpreted as `drone_dst_port` (40000/50000)

The STA maintains a pool of UDP sockets keyed by `phone_src_port`:

- It binds a local UDP socket on `phone_src_port`.
- It sends the payload to `drone_ip:drone_dst_port`.

This mirrors the phone's UDP source port onto the drone network.

### Drone -> STA (Wi-Fi) -> AP (serial)

When the STA receives a UDP datagram from the drone on a mirrored socket:

- Input (Wi-Fi):
  - src: `drone_ip:drone_src_port` (commonly `40000`, `50000`, or `7070`)
  - dst: `192.168.0.2:phone_port` (local port equals mirrored phone port)
- Output (serial frame to AP):
  - `type = SF_UDP`
  - `conn = phone_port`
  - `port = drone_src_port`
  - `payload = UDP payload bytes`

### AP -> phone (Wi-Fi)

When the AP receives `SF_UDP` from serial:

- `conn` is interpreted as `phone_dst_port`
- `port` is interpreted as `udp_src_port` to use when sending to the phone

Send to:

- dst: `last_phone_ip:phone_dst_port`
- src: `192.168.0.1:udp_src_port`

The AP has dedicated sockets bound to `40000` and `50000`. For any other `udp_src_port`, it creates/binds an additional UDP socket so the packet appears to come from that source port.

## TCP forwarding

### Phone -> AP (Wi-Fi) -> STA (serial)

The AP listens on TCP ports `7060`, `8060`, `9060`.

On accept:

- The AP allocates/updates a slot for the port.
- It sends `SF_TCP_OPEN(conn_id=port, port=port)` to the STA.
- Any bytes read from the phone socket are forwarded as:
  - `SF_TCP_DATA(conn_id=port, port=port, payload=data)`

On phone reconnect:

- The AP replaces the phone-side socket for that listening port.
- The AP does not force the STA to close; upstream state is allowed to persist/retry.

### STA -> drone (Wi-Fi)

On `SF_TCP_OPEN`:

- The STA starts (or continues) an outbound connect attempt to `drone_ip:port`.
- On success it emits `SF_TCP_OPEN_OK(conn_id, port)`.
- On failure it emits `SF_TCP_OPEN_FAIL(conn_id, port)`.
- While connecting, incoming `SF_TCP_DATA` from the AP is buffered (best-effort) and flushed after `OPEN_OK`.

Source port binding:

- Default behavior is to bind local TCP port to `conn_id` (so `7060->7060`, `8060->8060`).
- The STA logs `bind_ok` and the actual selected local port.
- On repeated timeouts, the STA may switch to ephemeral source ports as a fallback (see firmware logs for `bind_mode`).

### Drone -> STA -> AP -> phone

If the outbound TCP connect succeeds:

- Drone->STA bytes are forwarded as `SF_TCP_DATA(conn_id, port, payload=data)` to the AP.
- The AP writes these bytes to the phone's TCP socket for that port.

If the outbound TCP connect fails:

- The AP keeps the phone-side TCP socket open (to reduce app reconnect thrash).
- The AP may continue to accept phone bytes and forward them to the STA (which may buffer/drop depending on state).

## Video traffic (UDP 7070)

The drone streams JPEG video over UDP with source port `7070`.

Forwarding full-rate video over `921600` baud USB serial is not feasible. The STA therefore drops `drone_src_port=7070` packets at the source and counts them in the heartbeat (`udp_drop_video`).

If video forwarding is required, it needs a different transport (faster serial, direct Wi-Fi forwarding without USB, compression/transcoding on-device, or strict frame-level downsampling before serial).

## Logging

- `SF_LOG` lines are intended to be human-readable and stable.
- AP logs:
  - phone association events (AP station connect/disconnect)
  - first UDP receive per port (`udp: first_rx ...`)
  - first UDP transmit per port (`udp: first_tx ...`)
  - TCP accept/replace/close events
- STA logs:
  - Wi-Fi join progress, connect/disconnect reasons, `GOT_IP`
  - `wifi: hb ... udp_tx=... udp_rx=... udp_drop_video=...`
  - first drone UDP receive (non-video) and first video drop
  - TCP connect attempts and results with timing/bind details

## Host bridge expectations

The host bridge must:

- Open both serial ports at `921600` baud.
- Forward raw SF frames bidirectionally without modification.
- Avoid printing/logging synchronously in a way that blocks the forwarding path.
- Optionally persist a JSONL log and a filtered raw capture (e.g. keep TCP + UDP 40000/50000, drop 7070).

