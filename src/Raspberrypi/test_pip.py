import time
import board
import busio
import adafruit_vl53l4cd

print("Initializing I2C...")
i2c = busio.I2C(board.SCL, board.SDA)

print("Connecting to sensor at default address (0x2a or 0x29?)...")
# Note: we might need to scan first or specify address, but let's try 0x2a 
# because adafruit uses 0x29 as default. Wait, our scan showed 0x2a, 0x2b...
# Let's try 0x2a.

try:
    vl53 = adafruit_vl53l4cd.VL53L4CD(i2c, address=0x2a)
    print("Sensor found at 0x2a!")
    vl53.start_ranging()
    
    for i in range(10):
        while not vl53.data_ready:
            pass
        vl53.clear_interrupt()
        print(f"[{i}] Distance: {vl53.distance} cm")
except Exception as e:
    print(f"Failed: {e}")
