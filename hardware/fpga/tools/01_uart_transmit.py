import serial
import os

SERIAL_PORT_NAME = "/dev/cu.usbserial-AV0JXPUD"
BAUD_RATE = 250_000

ser = serial.Serial(SERIAL_PORT_NAME, BAUD_RATE)
print("Serial port initialized")

BYTES_PER_LINE = 8
data = []
print("Reading UART data... (Press Ctrl+C to stop and save)")

try:
    while True:
        if not len(b := ser.read()):
            continue
        data.append(b[0])
        if len(data) % 8 == 0:
            print(f"Received {len(data)} bytes...")
except KeyboardInterrupt:
    print(f"\n\nStopped! Received {len(data)} total bytes")

if data:
    # Check if first chunk is 7 bytes and discard it
    if len(data) >= 8 and len(data) % 8 == 7:
        print("Discarding first 7 bytes (incomplete chunk)")
        data = data[7:]
    
    output_path = os.path.expanduser("~/Desktop/tds_dump.txt")
    with open(output_path, "w") as f:
        for i in range(0, len(data), BYTES_PER_LINE):
            chunk = data[i:i+BYTES_PER_LINE]
            # Convert each byte to 8-bit binary string, LSB first (reverse bit order)
            bit_chunk = "".join(f"{x:08b}"[::-1] for x in chunk)
            f.write(bit_chunk + "\n")
    
    total_lines = (len(data) + BYTES_PER_LINE - 1) // BYTES_PER_LINE
    last_line_bytes = len(data) % BYTES_PER_LINE or BYTES_PER_LINE
    print(f"Saved to tds_dump.txt ({total_lines} lines, last line has {last_line_bytes} bytes)")
else:
    print("No data received")