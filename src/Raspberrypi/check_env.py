import sys
import os

print(f"=== Environment Debug ===")
print(f"Executable: {sys.executable}")
print(f"Python Version: {sys.version}")

# Check if smbus2 or adafruit library is importable in this environment
try:
    import smbus2
    print(f"smbus2 found at: {smbus2.__file__}")
except ImportError:
    print("smbus2 NOT IMPORTABLE")

try:
    import adafruit_vl53l4cd
    print(f"adafruit_vl53l4cd found at: {adafruit_vl53l4cd.__file__}")
except ImportError:
    print("adafruit_vl53l4cd NOT IMPORTABLE")

# Check I2C access
try:
    fd = os.open("/dev/i2c-1", os.O_RDWR)
    print("I2C-1 Access: SUCCESS (Can read/write)")
    os.close(fd)
except Exception as e:
    print(f"I2C-1 Access: FAILED -> {e}")

print("=========================")
