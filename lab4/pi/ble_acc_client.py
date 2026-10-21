#!/usr/bin/env python3
"""Lab 4 BLE central (GATT client) on Raspberry Pi.

Connects to the STM32 IoT node (GATT server), sets the accelerometer
sampling frequency via characteristic B, enables notifications on
characteristic A and prints the 3-axis acceleration.
Option (b): also subscribes to characteristic C and prints a message
each time the LSM6DSL detects significant motion.

While running, type a number + Enter (e.g. 20) to change the sampling
frequency, or q + Enter to quit.

Usage:
    sudo python3 ble_acc_client.py                 # scan for JJLDY_1
    sudo python3 ble_acc_client.py --freq 20
    sudo python3 ble_acc_client.py --quiet          # one line per second
    sudo python3 ble_acc_client.py --addr 02:80:E1:00:34:12
"""
import argparse
import select
import struct
import sys
import time

from bluepy.btle import (BTLEException, DefaultDelegate, Peripheral,
                         Scanner, UUID)

DEVICE_NAME = "JJLDY_1"
SERVICE_UUID = UUID("12345678-1234-5678-1234-56789abc0000")
ACC_UUID = UUID("12345678-1234-5678-1234-56789abc0001")   # A: x/y/z, Notify
FREQ_UUID = UUID("12345678-1234-5678-1234-56789abc0002")  # B: Hz, Write
SIGMOT_UUID = UUID("12345678-1234-5678-1234-56789abc0003")  # C: event count, Notify
CCCD_UUID = UUID(0x2902)


class AccDelegate(DefaultDelegate):
    """Called by bluepy each time the STM32 sends a notification."""

    def __init__(self, acc_handle, sigmot_handle=None, quiet=False):
        DefaultDelegate.__init__(self)
        self.acc_handle = acc_handle
        self.sigmot_handle = sigmot_handle
        self.quiet = quiet
        self.count = 0
        self.t0 = time.time()

    def handleNotification(self, cHandle, data):
        if cHandle == self.sigmot_handle and len(data) == 2:
            (count,) = struct.unpack("<H", data)
            print(f"\n*** SIGNIFICANT MOTION detected! (#{count}) "
                  f"at {time.strftime('%H:%M:%S')} ***\n")
            return
        if cHandle != self.acc_handle or len(data) != 6:
            return
        # 3 x int16, little-endian, unit: mg
        x, y, z = struct.unpack("<hhh", data)
        if not self.quiet:
            print(f"x={x:6d}  y={y:6d}  z={z:6d}  (mg)")

        # Print the measured notification rate once per second
        self.count += 1
        dt = time.time() - self.t0
        if dt >= 1.0:
            if self.quiet:
                print(f"x={x:6d}  y={y:6d}  z={z:6d}  (mg)   "
                      f"[{self.count / dt:.1f} notifications/s]")
            else:
                print(f"--- received {self.count / dt:.1f} notifications/s ---")
            self.count = 0
            self.t0 = time.time()


def scan_for_device(name, timeout):
    print(f"Scanning {timeout:.0f}s for '{name}' ...")
    for dev in Scanner().scan(timeout):
        if dev.getValueText(9) == name:  # 9 = Complete Local Name
            print(f"Found {name}: {dev.addr} ({dev.addrType}), RSSI={dev.rssi} dB")
            return dev.addr, dev.addrType
    return None, None


def write_freq(freq_char, hz):
    freq_char.write(struct.pack("<H", hz), withResponse=True)  # uint16 LE
    print(f">>> sampling frequency set to {hz} Hz")


def main():
    # Flush every line even when piped (e.g. "| tee client.log")
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description="Lab 4 BLE accelerometer client")
    parser.add_argument("--addr", help="STM32 BLE address (skip scanning)")
    parser.add_argument("--name", default=DEVICE_NAME, help="device name to scan for")
    parser.add_argument("--freq", type=int, default=10, help="sampling frequency in Hz (1-100)")
    parser.add_argument("--scan-time", type=float, default=5.0)
    parser.add_argument("--quiet", action="store_true",
                        help="print one line per second instead of every sample")
    args = parser.parse_args()

    addr, addr_type = args.addr, "random"
    if addr is None:
        addr, addr_type = scan_for_device(args.name, args.scan_time)
        if addr is None:
            sys.exit(f"'{args.name}' not found. Is the board advertising (press RESET)?")

    print("Connecting ...")
    dev = Peripheral(addr, addr_type)
    try:
        svc = dev.getServiceByUUID(SERVICE_UUID)
        acc_char = svc.getCharacteristics(ACC_UUID)[0]
        freq_char = svc.getCharacteristics(FREQ_UUID)[0]
        sigmot_chars = svc.getCharacteristics(SIGMOT_UUID)  # option (b), may be absent
        sigmot_char = sigmot_chars[0] if sigmot_chars else None
        print("Connected. Service and characteristics found.")

        dev.setDelegate(AccDelegate(acc_char.getHandle(),
                                    sigmot_char.getHandle() if sigmot_char else None,
                                    args.quiet))

        # 1) Characteristic B: assign the sampling frequency
        write_freq(freq_char, args.freq)

        # 2) Characteristic A: write 0x0001 to its CCCD to enable notifications
        cccd = acc_char.getDescriptors(forUUID=CCCD_UUID)[0]
        cccd.write(b"\x01\x00", withResponse=True)

        # 3) Characteristic C (option b): enable significant motion notifications
        if sigmot_char:
            sigmot_char.getDescriptors(forUUID=CCCD_UUID)[0].write(b"\x01\x00", withResponse=True)
            print("Significant motion notifications enabled.")
        else:
            print("(No significant motion characteristic on this firmware.)")
        print("Notifications enabled. Type a frequency + Enter to change it, q to quit.\n")

        while True:
            dev.waitForNotifications(0.05)

            # Non-blocking check for keyboard input
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline().strip()
                if line.lower() in ("q", "quit", "exit"):
                    break
                if line.isdigit() and 1 <= int(line) <= 100:
                    write_freq(freq_char, int(line))
                elif line:
                    print("Enter an integer between 1 and 100, or q")
    except KeyboardInterrupt:
        pass
    except BTLEException as e:
        print(f"BLE error: {e}")
    finally:
        try:
            dev.disconnect()
        except BTLEException:
            pass
        print("Disconnected.")


if __name__ == "__main__":
    main()
