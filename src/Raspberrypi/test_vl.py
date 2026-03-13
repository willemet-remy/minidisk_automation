import smbus2
from smbus2 import SMBus, i2c_msg

def read_id(bus, addr):
    reg = 0x010F
    reg_hi = (reg >> 8) & 0xFF
    reg_lo = reg & 0xFF
    print("\n--- Testing 0x010F (Model ID, expected 235/0xEB) ---")

    try:
        w = i2c_msg.write(addr, [reg_hi, reg_lo])
        r = i2c_msg.read(addr, 1)
        bus.i2c_rdwr(w, r)
        print("i2c_rdwr result:", list(r))
    except Exception as e:
        print("i2c_rdwr error:", e)

    try:
        bus.write_i2c_block_data(addr, reg_hi, [reg_lo])
        val = bus.read_byte(addr)
        print("write_i2c_block + read_byte result:", val)
    except Exception as e:
        print("write_i2c_block + read_byte error:", e)

with SMBus(1) as bus:
    for addr in range(0x20, 0x30):
        try:
            bus.read_byte(addr)
            if addr == 0x20: continue # skip MCP23017
            print(f"Found device at 0x{addr:02X}")
            read_id(bus, addr)
            break
        except:
            pass
