from smbus2 import SMBus, i2c_msg
import time

def read_vl53_result(bus, addr):
    # Try different read methods to see what VL53L4CD actually answers to
    reg_hi, reg_lo = 0x00, 0x89 # RESULT_BLOCK_START
    
    print("Method 1: i2c_rdwr (Repeated Start)")
    try:
        w = i2c_msg.write(addr, [reg_hi, reg_lo])
        r = i2c_msg.read(addr, 17)
        bus.i2c_rdwr(w, r)
        print(" ->", list(r))
    except Exception as e:
        print(" -> Error:", e)

    print("\nMethod 2: write_i2c_block then read_byte")
    try:
        bus.write_i2c_block_data(addr, reg_hi, [reg_lo])
        # read_i2c_block_data forces a command byte (offset). 
        # If we send 0x00 it moves the pointer to 0x0000. 
        # Let's try reading byte-by-byte instead if block read fails
        res = [bus.read_byte(addr) for _ in range(17)]
        print(" ->", res)
    except Exception as e:
        print(" -> Error:", e)

with SMBus(1) as bus:
    # Use default address or 0x2A if changed
    addr = 0x2A 
    try:
        bus.read_byte(0x2A)
    except:
        addr = 0x29
    
    print(f"Testing VL53L4CD at 0x{addr:02X}")
    read_vl53_result(bus, addr)
