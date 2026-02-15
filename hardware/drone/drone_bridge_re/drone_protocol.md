## Drone protocol

Notes, taken by a real human, from Codex's findings.

- Drone broadcasts a Wi-Fi SSID `RADCLOFPV_xxxxxx` with router IP (?) `192.168.0.1`.
- Drone is listening on ports 40000, 50000, and 7070 over UDP.
  - Port 40000 is for commands.
  - Port 7070 is for video feed (from the drone).
- Drone is listening on ports 7060, 8060, and 9060 over TCP.
  - ACTUALLY it turns out Codex may have been lying to us and there is no TCP at all.

### Startup behavior

1. Connect to `RADCLOFPV_xxxxxx`. Set `192.168.0.1` as destination address.
2. Send a heartbeat every second to port 40000 over UDP:
   ```
   63 63 01 00 00 00 00
   ```
3. Send a 46-byte hello payload over TCP 7060:
   ```
   6c657765695f636d64 0002 00000001 0000000000000000000000000000000000000000000000000000000000
   ```
   Then start sending heartbeat frames every second:
   ```
   6c657765695f636d64 0001 00000000 0000000000000000000000000000000000000000000000000000000000
   ```
4. Send a 54-byte payload over port TCP 8060:
   ```
   6c657765695f636d64 0004 00000000 0000000000000008 0000000000000000000000000000000000000000 db8c9069 00000000
   ```
5. Listen over port 40000 for status reports from the drone.
6. Listen over port 7070 for video feed from the drone.

### Controlling the drone

Send UDP packets to port 40000 on the drone of length 15 bytes. Payloads start with ASCII `63 63` and generally have the format:

- `[0..1]` magic `63 63`
- `[2..3]` opcode u16le `0x000a`
- `[4]` reserved (observed `0x00`)
- `[5..6]` constant u16le `0x0008`
- `[7]` constant `0x66`
- `[8..11]` axes (center `0x80`)
- `[12]` flags (observed values below)
- `[13]` checksum: XOR of bytes `[8..12]`
- `[14]` terminator `0x99`
