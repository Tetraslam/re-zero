import serial.tools.list_ports
import time

BAUD_RATE = 250_000
# /dev/cu.usbserial-AV0JXPUD

def test_ports():
    print("Ports found: ")
    ports = serial.tools.list_ports.comports()

    for port in ports:
        print("{port.device}: {port.description} [manufacturer: {port.manufacturer}]".format(port=port))
    if (len(ports) == 0):
        print("No ports found. Make sure your board is plugged in and turned on?")
    print()

    for port in ports:

        test_port = input("test port '{port.device}'? (y/n/exit) ".format(port=port))

        while (test_port == "y"):

            try:
                ser = serial.Serial(port.device, BAUD_RATE, write_timeout=4)
                print("\twatch for a flashing green `TX` light")

                for i in range(10):
                    ser.write(bytes("Hello, World!", 'utf-8'))
                    time.sleep(0.5)

                print("Test completed\n")
            except Exception as e:
                print("Test failed with: {}\n".format(e))

            test_port = input("REPEAT test for '{port.device}'? (y/n/exit) ".format(port=port))

        if (test_port == "exit"):
            exit()


test_ports()