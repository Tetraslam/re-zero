# Protocol: ESP32 AP/STA proxy framing and forwarding

This repository implements a two-ESP32 proxy so a phone app can control a drone as if it were directly connected to the drone's Wi-Fi.

Components:

- ESP32 AP: spoof access point `RADCLOFPV_676767`, gateway `192.168.0.1`
- ESP32 STA: joins the real drone SSID (e.g. `RADCLOFPV_839819`) and talks to the drone at `192.168.0.1`
- Host bridge: forwards framed bytes between the AP and STA over two USB serial ports

## Topology and roles

Packet path:

- Phone <-> ESP32 AP (Wi-Fi)
- ESP32 AP <-> host bridge <-> ESP32 STA (serial, framed)
- ESP32 STA <-> drone (Wi-Fi)

The AP side presents the phone-facing services:

- UDP: 40000, 50000
- TCP: 7060, 8060, 9060

## Serial framing (SF)

All serial traffic between each ESP32 and the host uses a binary framing format. The host does not need to interpret payloads to forward traffic.

Byte order: little-endian for all `u16` fields.

Frame layout:

```text
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

Types:

- `0x01` `SF_HELLO`: ASCII role string (`AP` or `STA`)
- `0x02` `SF_UDP`: one UDP datagram
- `0x03` `SF_LOG`: one UTF-8 log line (no trailing newline)
- `0x10` `SF_TCP_OPEN`: request outbound TCP connect on STA
- `0x11` `SF_TCP_OPEN_OK`: outbound TCP connected
- `0x12` `SF_TCP_OPEN_FAIL`: outbound TCP connect failed
- `0x13` `SF_TCP_DATA`: TCP payload bytes
- `0x14` `SF_TCP_CLOSE`: close TCP connection

Implementations:

- ESP32: `esp32_ap/serial_frame.h`, `esp32_sta/serial_frame.h`
- Host: `bridge/serial_frame.py`

## Connection identifiers

`conn_u16` is used to correlate state across the serial bridge.

TCP:

- `conn_id` is stable and equals the listening port on the AP: 7060/8060/9060.
- Rationale: the phone uses ephemeral source ports; stable IDs prevent reconnect churn from creating unbounded upstream state.

UDP:

- `conn_id` equals the phone UDP port being mirrored.
  - Phone -> drone: `conn_id = phone_src_port`
  - Drone -> phone: `conn_id = phone_dst_port`

## UDP forwarding

### Phone -> AP -> STA (serial)

The AP listens on UDP ports 40000 and 50000. For each received phone datagram:

- AP emits `SF_UDP(conn=phone_src_port, port=dst_port, payload=udp_payload)`
- AP updates `last_phone_ip` from the packet source; this IP is used for drone->phone sends.

### STA -> drone (Wi-Fi)

On `SF_UDP(conn=phone_src_port, port=drone_dst_port)` the STA:

- binds (or reuses) a local UDP socket bound to `phone_src_port`
- sends the payload to `drone_ip:drone_dst_port`

This mirrors the phone source port onto the drone network.

### Drone -> STA -> AP (serial)

When the STA receives a UDP datagram on a mirrored socket:

- STA emits `SF_UDP(conn=local_port, port=drone_src_port, payload=udp_payload)`

Where:

- `conn` is the local port (mirrored phone port)
- `port` is the drone's UDP source port

### AP -> phone (Wi-Fi)

On `SF_UDP(conn=phone_dst_port, port=udp_src_port)` the AP sends:

- dst: `last_phone_ip:phone_dst_port`
- src: `192.168.0.1:udp_src_port`

The AP uses sockets bound to 40000/50000 and creates additional bound sockets as needed so packets appear to originate from the correct source port.

## TCP forwarding

### Phone -> AP -> STA (serial)

The AP listens on TCP ports 7060/8060/9060.

On accept:

- AP emits `SF_TCP_OPEN(conn_id=listen_port, port=listen_port)`
- AP forwards phone bytes as `SF_TCP_DATA(conn_id=listen_port, port=listen_port, payload=data)`

On phone reconnect (same listen port):

- AP replaces the phone-side socket for that port
- AP does not force-close the STA side; STA retry state is allowed to converge

### STA -> drone (Wi-Fi)

On `SF_TCP_OPEN` the STA attempts an outbound connect to `drone_ip:port`.

- Success: `SF_TCP_OPEN_OK(conn_id, port)`
- Failure: `SF_TCP_OPEN_FAIL(conn_id, port)`
- While connecting: incoming `SF_TCP_DATA` from the AP is buffered (best-effort) and flushed after `OPEN_OK`.

The STA attempts to bind the local source port to `conn_id` (so the drone sees `192.168.0.2:<port>`). If bind fails, it falls back to an ephemeral local port.

### Drone -> STA -> AP -> phone

Once connected:

- STA forwards drone bytes as `SF_TCP_DATA(conn_id, port, payload)`
- AP writes those bytes to the current phone TCP socket for that port

## UDP 40000 control messages (`cc`)

The app's flight control uses UDP destination port 40000. Payloads commonly start with ASCII `63 63` (`"cc"`).

### `cc` heartbeat (7 bytes)

```text
63 63 01 00 00 00 00
```

Opcode `0x0001` (little-endian), sent around 1 Hz while connected.

### `cc` control report (15 bytes)

```text
63 63 0a 00 00 08 00 66  a0 a1 a2 a3  flags  csum  99
```

Offsets:

- `[0..1]` magic `63 63`
- `[2..3]` opcode u16le `0x000a`
- `[4]` reserved (observed `0x00`)
- `[5..6]` constant u16le `0x0008`
- `[7]` constant `0x66`
- `[8..11]` axes (center `0x80`)
- `[12]` flags (observed values below)
- `[13]` checksum: XOR of bytes `[8..12]`
- `[14]` terminator `0x99`

Axes:

- `a0 = payload[8]`: right stick horizontal (strafe/roll)
- `a1 = payload[9]`: right stick vertical (forward/back)
- `a2 = payload[10]`: left stick vertical (throttle)
- `a3 = payload[11]`: left stick horizontal (yaw/turn)

No separate "speed mode" or "sensitivity" opcode has been identified in the captured control plane. The UI setting appears to change how the app scales axis bytes around center.

Observed right stick scaling presets (for `a0` and `a1`, centered at `0x80`):

- 100%: approximately `0x01..0xff` (max delta `0x7f`)
- 60%: approximately `0x44..0xbc` (max delta `0x3c`)
- 30%: approximately `0x58..0xa8` (max delta `0x28`)

These ranges were observed while moving only the right stick (with throttle and yaw near neutral). Whether the same scaling is applied to throttle (`a2`) and yaw (`a3`) is not yet established.

Flags (`payload[12]`), observed so far:

- `0x00`: no action
- `0x01`: takeoff (button press/hold generates repeated control reports with this value)
- `0x02`: land (button press/hold generates repeated control reports with this value)
- `0x03`: observed; meaning unknown
- `0x04`: stop / e-stop
- `0x10`: gyro calibrate
- `0x80`: headless mode (toggle/hold behavior not yet confirmed)

Gravity sensor / tilt mode:

- No flag bit has been identified.
- When the on-screen gravity sensor control is toggled with sticks neutral, the app alternates between `a0=0x80` and `a0=0x81` while keeping `flags=0x00`. This likely encodes a mode bit in the LSB of `a0` when near center.

Trim (left/right roll):

- No flag bit has been identified.
- The app sends left/right roll trim adjustments as repeated `0x000a` control reports with `a0=a1=a2=0x80`, `flags=0x00`, and `a3` stepping away from center.
- Observed range: `a3` from `0x50` (full left trim) through `0x80` (center) to `0xb0` (full right trim), typically in steps of 1 per UI press/repeat.
- This reuses the `a3` byte; consumers should treat `a3` as the raw on-wire value and infer \"trim\" vs \"yaw stick\" from context (e.g., other axes at neutral and small deltas around `0x80`).

Trim (left/right strafe):

- No flag bit has been identified.
- The app sends left/right strafe trim adjustments as repeated `0x000a` control reports with `a1=a2=0x80`, `flags=0x00`, and:
  - `a0` stepping away from center (trim value)
  - `a3` held constant at `0xb0` (marker; observed)
- Observed range: `a0` from `0x50` (full left trim) through `0x80` (center) to `0xb0` (full right trim), typically in steps of 1 per UI press/repeat.

Trim (forward/back):

- No flag bit has been identified.
- The app sends forward/back trim adjustments as repeated `0x000a` control reports with `a2=0x80`, `flags=0x00`, and:
  - `a1` stepping away from center (trim value)
  - `a0` held constant at `0xb0` (marker; observed)
  - `a3` held constant at `0xb0` (marker; observed)
- Observed range: `a1` from `0x50` (full back trim) through `0x80` (center) to `0xb0` (full forward trim), typically in steps of 1 per UI press/repeat.

### `cc` control report examples

All examples below are the UDP payload bytes (15 bytes), not SF frames.

Neutral sticks, no flags:

```text
63 63 0a 00 00 08 00 66  80 80 80 80  00 00 99
```

Takeoff / land / stop (neutral axes, flags set):

```text
takeoff: 63 63 0a 00 00 08 00 66  80 80 80 80  01 01 99
land:    63 63 0a 00 00 08 00 66  80 80 80 80  02 02 99
unk_03:  63 63 0a 00 00 08 00 66  80 80 80 80  03 03 99
stop:    63 63 0a 00 00 08 00 66  80 80 80 80  04 04 99
```

Gyro calibrate / headless mode (neutral axes, flags set):

```text
gyro_cal:  63 63 0a 00 00 08 00 66  80 80 80 80  10 10 99
headless:  63 63 0a 00 00 08 00 66  80 80 80 80  80 80 99
```

Gravity sensor toggle (observed as `a0` LSB, neutral otherwise):

```text
off: 63 63 0a 00 00 08 00 66  80 80 80 80  00 00 99
on:  63 63 0a 00 00 08 00 66  81 80 80 80  00 01 99
```

Trim examples:

```text
roll_trim_left:     63 63 0a 00 00 08 00 66  80 80 80 50  00 d0 99
roll_trim_right:    63 63 0a 00 00 08 00 66  80 80 80 b0  00 30 99

strafe_trim_left:   63 63 0a 00 00 08 00 66  50 80 80 b0  00 e0 99
strafe_trim_right:  63 63 0a 00 00 08 00 66  b0 80 80 b0  00 00 99

fb_trim_back:       63 63 0a 00 00 08 00 66  b0 50 80 b0  00 d0 99
fb_trim_forward:    63 63 0a 00 00 08 00 66  b0 b0 80 b0  00 30 99
```

### Drone status (`cc` type 0x01, 106 bytes)

The drone periodically sends a 106-byte `cc` message from UDP source port 40000 to the phone (mirrored port).

Observed prefix:

```text
63 63 01 ss 00 63 00 52 41 44 43 4c 4f 46 50 56 ...
```

Fields identified:

- `payload[0..1] = 0x63 0x63`
- `payload[2] = 0x01` (type)
- `payload[3] = ss` (sequence counter; increments each packet)
- ASCII SSID string `RADCLOFPV_<digits>` appears in the payload (null-terminated).

In the current captures this packet is otherwise invariant; no attitude/gyro/IR sensor fields have been identified in it.

## Video traffic (UDP 7070)

The drone streams JPEG video over UDP with source port 7070. This project does not forward full-rate video over USB serial.

Default behavior:

- STA drops UDP packets with `drone_src_port=7070` and increments `udp_drop_video`.

## Logging and captures

Artifacts:

- `logs/proto_*.jsonl`: protocol-focused (phone->drone commands and selected drone->phone telemetry)
- `logs/bridge_*.jsonl`: generic SF frame log (truncated payloads)
- `logs/capture_*.sf.bin`: raw framed bytes (filtered to control-relevant traffic)

Stdout is intended to be low volume. Protocol truth is the `proto_*.jsonl` stream.
