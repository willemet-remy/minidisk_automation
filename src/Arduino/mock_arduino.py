import os
import pty
import time
import math
import sys
import select

def main():
    master, slave = pty.openpty()
    port_name = os.ttyname(slave)
    print(f"Mock Arduino created on port: {port_name}")
    print("Keep this terminal open and connect your Python app to this port.")

    num_sensors = 6
    interval_ms = 5000
    start_time = time.time()
    last_send = start_time
    
    is_running = False

    try:
        while True:
            # 1. Non-blocking read from master
            r, _, _ = select.select([master], [], [], 0.05)
            if master in r:
                data = os.read(master, 1024).decode('utf-8', errors='ignore')
                # Process commands
                for line in data.split('\n'):
                    line = line.strip()
                    if line == "START":
                        print("Arduino: Received START")
                        is_running = True
                        os.write(master, b"ACK_START\r\n")
                    elif line == "PAUSE":
                        print("Arduino: Received PAUSE")
                        is_running = False
                        os.write(master, b"ACK_PAUSE\r\n")
                    elif line == "RESUME":
                        print("Arduino: Received RESUME")
                        is_running = True
                        os.write(master, b"ACK_RESUME\r\n")
                    elif line == "STOP":
                        print("Arduino: Received STOP")
                        is_running = False
                        os.write(master, b"ACK_STOP\r\n")

            # 2. Send data if running and interval elapsed
            current_time = time.time()
            if is_running and (current_time - last_send >= interval_ms / 1000.0):
                last_send = current_time
                elapsed_ms = int((current_time - start_time) * 1000)

                # Simulate infiltration curve (fast drop initially, then steady linear)
                # Curve: A * exp(-kt) + B*t + C
                # Let's say steady state slope is -0.05 cmH2O / sec
                # For sensor 0:
                t_sec = elapsed_ms / 1000.0
                cm0 = 20.0 * math.exp(-0.02 * t_sec) - (0.05 * t_sec) + 10.0
                
                # Back-calculate raw voltage based on cmH20
                # cmh2O = -pressurekPa * 10.19
                # pressurekPa = -cmh2O / 10.19
                # pressurekPa = (((10.0 / 5.0) * raw) - 5.0) * 6.89476
                p0 = -cm0 / 10.19
                raw0 = ((p0 / 6.89476) + 5.0) * (5.0 / 10.0)

                data_str = f"DATA,{elapsed_ms}"
                for i in range(num_sensors):
                    if i == 0:
                        cm_val, p_val, raw_val = cm0, p0, raw0
                    else:
                        cm_val, p_val, raw_val = (0.0, 0.0, 2.5) # static 2.5V
                        
                    data_str += f",{raw_val:.3f},{p_val:.3f},{cm_val:.3f}"
                
                data_str += "\r\n"
                os.write(master, data_str.encode('utf-8'))
                print(f"Sent: {data_str.strip()}")

    except KeyboardInterrupt:
        print("\nClosing mock Arduino.")
    finally:
        os.close(master)
        os.close(slave)

if __name__ == "__main__":
    main()
