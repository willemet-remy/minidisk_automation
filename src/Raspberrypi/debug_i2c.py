import time
import smbus2

bus = smbus2.SMBus(1)

def scan_i2c():
    print("Scanning I2C bus...")
    found = []
    for addr in range(0x03, 0x78):
        try:
            bus.write_quick(addr)
            found.append(hex(addr))
        except Exception:
            pass
    print(f"Found devices at: {found}")
    return found

def test_sensor(addr):
    print(f"\nTesting sensor at {hex(addr)}...")
    try:
        # Try to read Model ID (register 0x010F, expected 0xEB)
        # We'll use the i2c_rdwr method for atomic transaction
        write = smbus2.i2c_msg.write(addr, [0x01, 0x0F])
        read = smbus2.i2c_msg.read(addr, 1)
        bus.i2c_rdwr(write, read)
        model_id = list(read)[0]
        print(f"Model ID Configuration (0x010F): {hex(model_id)}")
        
        # Check system status
        write = smbus2.i2c_msg.write(addr, [0x00, 0xE5]) # System status
        read = smbus2.i2c_msg.read(addr, 1)
        bus.i2c_rdwr(write, read)
        sys_status = list(read)[0]
        print(f"System status (0x00E5): {hex(sys_status)}")
        
    except Exception as e:
        print(f"Failed to communicate with sensor at {hex(addr)}: {e}")

if __name__ == "__main__":
    devices = scan_i2c()
    for dev in devices:
        test_sensor(int(dev, 16))
