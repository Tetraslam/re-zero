import serial
import csv
import time
import sys

# ================= CONFIGURATION =================
# 1. BLUETOOTH PORT (ESP32)
# Windows Example: "COM5" 
# Mac Example: "/dev/cu.ESP32_CPA_Target-ESP32SPP"
ESP_PORT  = "/dev/cu.ESP32_CPA_Target" 

# 2. USB PORT (FPGA)
# Windows Example: "COM3"
# Mac Example: "/dev/cu.usbserial-AV0JXPUD"
FPGA_PORT = "/dev/cu.usbserial-AV0JXPUD"

# 3. SETTINGS
BAUD_ESP  = 115200
BAUD_FPGA = 250000        # Must match your Verilog UART speed
TRACES_TO_CAPTURE = 10000 # [Source 1] suggests 10k-20k for high SNR
SAMPLES_PER_TRACE = 50    # How many measurements to keep per encryption
# =================================================

def hamming_weight(n):
    """Counts the number of '1's in the integer (0-64)."""
    return bin(n).count('1')

def run_capture():
    print(f"--- INITIALIZING CPA CAPTURE ---")
    print(f"ESP32 (Bluetooth): {ESP_PORT}")
    print(f"FPGA  (USB)      : {FPGA_PORT}")
    
    # 1. Connect to ESP32 (The Plaintext Source)
    try:
        esp = serial.Serial(ESP_PORT, BAUD_ESP, timeout=2) # 2s timeout
        esp.reset_input_buffer() 
        print("Connected to ESP32.")
    except Exception as e:
        print(f"ERROR: Could not connect to ESP32. Is Bluetooth paired? {e}")
        return

    # 2. Connect to FPGA (The Power Sensor)
    try:
        fpga = serial.Serial(FPGA_PORT, BAUD_FPGA, timeout=2)
        fpga.reset_input_buffer()
        print("Connected to FPGA.")
    except Exception as e:
        print(f"ERROR: Could not connect to FPGA. {e}")
        return

    print("\nREADY. Press the BOOT button on the ESP32 to start streaming...")
    
    # 3. Open CSV File
    filename = 'cpa_dataset.csv'
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header: PT_0..15 (Input) + Sample_0..49 (Power)
        header = [f"PT_{i}" for i in range(16)] + [f"Sample_{i}" for i in range(SAMPLES_PER_TRACE)]
        writer.writerow(header)

        print(f"Capturing {TRACES_TO_CAPTURE} traces...")

        # --- MAIN LOOP ---
        for i in range(TRACES_TO_CAPTURE):            
            # STEP A: WAIT FOR PLAINTEXT (With Timeout Fix)
            pt_bytes = []
            while True:
                try:
                    # Read line (will timeout after 2s if silent)
                    line = esp.readline().decode('utf-8', errors='ignore').strip()
                    print(line)
                    
                    # If empty (timeout), just loop again
                    if not line:
                        continue 
                        
                    # If valid data
                    if line.startswith("PT:"):
                        # Parse "PT:00AABB..." -> [0, 170, 187...]
                        hex_content = line.split(":")[1] 
                        # Chunk into bytes
                        pt_bytes = [int(hex_content[j:j+2], 16) for j in range(0, len(hex_content), 2)]
                        
                        # Verify integrity
                        if len(pt_bytes) == 16:
                            break # Go to Step B
                        else:
                            print(f"Warning: Corrupt Plaintext ({len(pt_bytes)} bytes). Skipping.")
                            
                except Exception as e:
                    # Handle disconnects or serial errors gracefully
                    pass

            # STEP B: CAPTURE POWER TRACE
            # ESP32 has triggered the FPGA. Read the stream.
            # We need SAMPLES_PER_TRACE * 8 bytes (since 1 sample = 64 bits = 8 bytes)
            bytes_needed = SAMPLES_PER_TRACE * 8
            trace_samples = []
            
            raw_data = fpga.read(bytes_needed)
            
            # Parse raw bytes into Hamming Weights
            # Your dump shows 64-bit binary strings [Source 3]. 
            # We compress "000...111" -> Integer(24)
            for j in range(0, len(raw_data), 8):
                chunk = raw_data[j:j+8]
                if len(chunk) == 8:
                    hw = sum(hamming_weight(b) for b in chunk)
                    trace_samples.append(hw)

            # Pad with zeros if FPGA sent incomplete data
            while len(trace_samples) < SAMPLES_PER_TRACE:
                trace_samples.append(0)

            # STEP C: SAVE
            writer.writerow(pt_bytes + trace_samples)
            
            # UI Update
            if i % 10 == 0:
                print(f"Captured {i}/{TRACES_TO_CAPTURE} ... Last HW: {trace_samples[2] if len(trace_samples)>10 else '?'}", end='\r')

    print(f"\n\nSUCCESS! Saved to {filename}")
    esp.close()
    fpga.close()

if __name__ == "__main__":
    run_capture()