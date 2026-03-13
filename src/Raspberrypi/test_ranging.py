import time
import smbus2

bus = smbus2.SMBus(1)
addr = 0x2a

def _read_bytes(reg16, length):
    reg_hi = (reg16 >> 8) & 0xFF
    reg_lo =  reg16       & 0xFF
    write = smbus2.i2c_msg.write(addr, [reg_hi, reg_lo])
    read = smbus2.i2c_msg.read(addr, length)
    bus.i2c_rdwr(write, read)
    return list(read)

def _write_byte(reg16, value):
    reg_hi = (reg16 >> 8) & 0xFF
    reg_lo =  reg16       & 0xFF
    bus.write_i2c_block_data(addr, reg_hi, [reg_lo, value])

print("Starting ranging...")
_write_byte(0x0087, 0x40) # start ranging

for i in range(10):
    time.sleep(0.1)
    
    # check data ready
    status = _read_bytes(0x0031, 1)[0]
    is_ready = bool(status & 0x01)
    print(f"[{i}] Data Ready: {is_ready} (status reg: {hex(status)})")
    
    if is_ready:
        result = _read_bytes(0x0089, 17)
        distance = (result[13] << 8) | result[14]
        print(f"    Raw bytes 13-14: {hex(result[13])} {hex(result[14])} -> Distance: {distance}mm")
        
        # clear interrupt
        _write_byte(0x0086, 0x01)

# stop ranging
_write_byte(0x0087, 0x00)
print("Done.")
