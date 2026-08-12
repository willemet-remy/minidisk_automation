# Infiltrometer Controller — Documentation

> **Wireless sensor-node update (2026):** Long I2C cables to remote VL53 sensors are not reliable. The supported next architecture is one battery-powered ESP32 + VL53L4CD at each measurement location, communicating with an ESP-NOW receiver near the Raspberry Pi. The complete, buildable node and receiver firmware plus wiring and commissioning instructions are in [src/Esp32/README.md](src/Esp32/README.md). The documentation below describes the original wired Raspberry Pi prototype.

## Wireless ESP32 measurement system

The current development direction is a wireless system with one local VL53L4CD per ESP32 node. I2C remains inside each node enclosure (ideally under 20 cm); ESP-NOW replaces the long I2C cable. A USB-powered ESP32 receiver is connected to a computer running the acquisition application.

```
LiPo -> protected 3.3 V regulator -> ESP32 node <--- short I2C ---> VL53L4CD
                                      |
                                      | ESP-NOW, same radio channel
                                      v
                         ESP32 receiver -> USB serial -> computer application
```

### Included software

| Component | Location | Purpose |
|---|---|---|
| ESP32 node + receiver firmware | [src/Esp32](src/Esp32) | VL53L4CD measurement, deep sleep, ESP-NOW communication, and control relay. |
| Python acquisition application | [src/Computer](src/Computer) | Live monitoring, metadata, Start/Pause/Resume/End control, and CSV logging. |

### Node hardware and wiring

Each measurement node needs an ESP32-S3 Mini/DevKit, one 3.3 V-safe VL53L4CD breakout, a protected LiPo/Li-ion cell, and a regulator capable of powering an ESP32 radio burst. Do **not** connect a LiPo cell directly to the 3.3 V pins.

The default configuration targets the ESP32-S3 DevKitC-1:

| ESP32 pin | VL53L4CD pin | Purpose |
|---|---|---|
| 3V3 | VIN/VDD | Sensor supply |
| GND | GND | Local common ground |
| GPIO 8 | SDA | Local I2C data |
| GPIO 9 | SCL | Local I2C clock |
| GPIO 7 | XSHUT | Sensor standby during node deep sleep |

Check whether the sensor breakout already contains I2C pull-ups before adding resistors. One effective pull-up pair, typically 4.7–10 kOhm to 3.3 V, is required per local bus.

### Configure and flash the firmware

Edit [src/Esp32/include/config.h](src/Esp32/include/config.h) before each node is flashed:

1. Set a unique `NODE_ID`.
2. Give it a permanent `NODE_NAME`, for example `MINIDISK_01`. This is the name shown by the application and saved to CSV.
3. Verify the I2C/XSHUT pins for the exact ESP32 Mini board.
4. Set `SAMPLE_INTERVAL_SECONDS` and, if fitted, configure the battery-voltage divider.

Build the two PlatformIO environments from `src/Esp32`:

```powershell
# Keep this receiver connected to the computer.
pio run -e receiver --target upload

# Flash one sensor node; change NODE_ID and NODE_NAME for every physical node.
pio run -e node --target upload
```

All nodes and the receiver must use the same ESP-NOW channel. Broadcast mode is enabled for commissioning. For a field deployment, the ESP32 documentation explains how to switch to unicast using the receiver MAC address.

### Computer acquisition and CSV logging

Connect the receiver through USB, then install and start the Python application:

```powershell
python -m pip install pyserial
cd src\Computer
python minidisk_acquisition.py
```

The application lets the user choose the receiver serial port, view the permanent sensor name, connection state, node mode, distance, battery voltage, and last received packet. Start a session by entering a measurement name, tension (hPa), and optional notes, then choose a CSV output location. Each saved row contains the metadata, sensor identity, distance, VL53 range status, battery voltage, and sender MAC address.

Start, Pause/Resume, and End commands are sent from the application to the USB receiver and broadcast to the nodes. Since battery nodes sleep between samples, a command is applied during the listening window after the node's next wake-up; with the default configuration this can take up to 60 seconds. The application shows the state that the node actually reports.

For full application instructions, see [src/Computer/README.md](src/Computer/README.md). For detailed ESP32 configuration, commissioning, and limitations, see [src/Esp32/README.md](src/Esp32/README.md).

---

## Original wired Raspberry Pi prototype

## Overview

Controls 8 × VL53L4CD time-of-flight sensors connected to a Raspberry Pi via I2C.
XSHUT and GPIO1 lines are managed through an MCP23017 I2C GPIO expander.
Measurements are logged to CSV on a USB stick.

---

## Hardware Bill of Materials

| Component | Purpose | Qty |
|---|---|---|
| Raspberry Pi Zero | Main controller | 1 |
| Waveshare 7" Control Panel for Raspberry Pi 4 | User interface | 1 |
| VL53L4CD breakout | Distance sensor | 8 |
| MCP23017-E/SP (DIP-28) | XSHUT + GPIO1 I/O expander | 1 |
| INA219 | Battery Voltage/Current I2C Monitor | 1 |
| LiPo 3.7V ≥ 5000 mAh | Battery | 1 |
| 4.7 kΩ resistor | I2C SDA/SCL pull-ups | 2 |
| 10 kΩ resistor | XSHUT pull-downs | 8 |
| 100 nF ceramic cap | Decoupling per sensor | 10 |
| USB-A OTG adapter (micro USB) | USB stick access | 1 |
| USB stick ≥ 16 GB | Data storage | 1 |
| Micro SD ≥ 16 GB Class 10 | RPi OS | 1 |

---

## Wiring

### I2C Bus (all devices share SDA/SCL)

```
RPi GPIO2 (SDA, pin 3) ──┬── 4.7kΩ to 3.3V
                          ├── MCP23017 pin 13 (SDA)
                          └── All 8 × VL53L4CD SDA

RPi GPIO3 (SCL, pin 5) ──┬── 4.7kΩ to 3.3V
                          ├── MCP23017 pin 12 (SCL)
                          └── All 8 × VL53L4CD SCL
```

### MCP23017 Address Pins

```
A0 (pin 15) → GND
A1 (pin 16) → GND
A2 (pin 17) → GND
→ I2C address = 0x20
RESET (pin 18) → 3.3V
VDD (pin 28) → 3.3V
VSS (pin 9)  → GND
```

### MCP23017 Port A → XSHUT Lines

```
GPA0 (pin 21) → XSHUT sensor 0   (+ 10kΩ to GND)
GPA1 (pin 22) → XSHUT sensor 1   (+ 10kΩ to GND)
GPA2 (pin 23) → XSHUT sensor 2   ...
GPA3 (pin 24) → XSHUT sensor 3
GPA4 (pin 25) → XSHUT sensor 4
GPA5 (pin 26) → XSHUT sensor 5
GPA6 (pin 27) → XSHUT sensor 6
GPA7 (pin 28) → XSHUT sensor 7   (+ 10kΩ to GND)
```

### MCP23017 Port B → GPIO1 Lines

```
GPB0 (pin 1) → GPIO1 sensor 0   (open-drain, pulled up internally)
GPB1 (pin 2) → GPIO1 sensor 1
...
GPB7 (pin 8) → GPIO1 sensor 7
```

### VL53L4CD per sensor

```
VDD   → 3.3V (+ 100nF cap to GND)
GND   → GND
SDA   → I2C bus
SCL   → I2C bus
XSHUT → MCP23017 GPA[n]
GPIO1 → MCP23017 GPB[n]
```

---

## I2C Address Map

| Address | Device |
|---|---|
| 0x14 | PiJuice HAT |
| 0x20 | MCP23017 |
| 0x2A | Sensor 0 (assigned at boot) |
| 0x2B | Sensor 1 |
| 0x2C | Sensor 2 |
| 0x2D | Sensor 3 |
| 0x2E | Sensor 4 |
| 0x2F | Sensor 5 |
| 0x30 | Sensor 6 |
| 0x31 | Sensor 7 |

---

## Software Installation

1. Flash Raspberry Pi OS **with Desktop** (Bookworm 64-bit) to SD card.
2. Boot, connect to network briefly (for apt).
3. Copy the infiltrometer folder to the Pi:
   `scp -r /home/remy/Documents/minidisk_automation/src/Raspberrypi remy@raspberrypi_ip:/Documents/minidisk`
4. Run the setup script to create a local virtual environment (`venv`) and install dependencies:
   ```bash
   cd /path/to/infiltrometer
   bash setup.sh
   sudo reboot
   ```

After reboot, the GUI launches automatically on the touchscreen.

---

## File Structure

```
infiltrometer/
├── main.py            Entry point
├── config.py          All constants (addresses, thresholds, colours)
├── sensor_manager.py  MCP23017 + VL53L4CD driver + Calibration Logic
├── data_logger.py     CSV logging to USB stick
├── gui.py             PyQt5 GUI (Measurement & Calibration Dialog)
├── INA219.py          I2C Battery Monitor driver
├── calibration.json   Saved Offset and Xtalk profiles (Auto-generated)
└── setup.sh           Installation script (venv + systemd)
```

---

## CSV Output Format

Saved to USB stick as `infiltrometer_YYYYMMDD_HHMMSS.csv`:

```
timestamp, sensor_0_mm, ..., sensor_7_mm, tension_0_hPa, ..., tension_7_hPa, fault_0, ..., fault_7, low_water_0, ..., low_water_7
2025-06-01 09:00:00, 142, 138, ..., 50.0, 50.0, ..., 0, 0, ..., 0, 0, ...
```

- **sensor_N_mm**: measured water distance in mm (blank = error)
- **tension_N_hPa**: applied tension entered in GUI
- **fault_N**: 1 if GPIO1 fault line asserted
- **low_water_N**: 1 if distance below threshold (default 20 mm)

---

## Troubleshooting

| Problem | Check |
|---|---|
| Sensor not detected | Check XSHUT 10kΩ pull-down, verify SDA/SCL connections |
| All sensors fail init | Check I2C enabled (`i2cdetect -y 1`), check 4.7kΩ pull-ups |
| USB stick not found | Check `/media/pi/` for mount, try different USB stick |
| Battery % not showing | Check INA219 wiring to I2C and `0x43` address |
| GUI not starting | `journalctl -u infiltrometer -f` for logs |

---

## Adjustable Parameters (config.py)

| Parameter | Default | Description |
|---|---|---|
| `LOW_WATER_THRESHOLD_MM` | 400 | Trigger low water warning below this distance |
| `MEASUREMENT_INTERVALS` | [1,2,5,10,30,60,300] | Available intervals in GUI dropdown |
| `DEFAULT_INTERVAL` | 5 | Default measurement interval (seconds) |
| `STEADY_STATE_WINDOW_S` | 30 | Seconds to test for distance shift |
| `STEADY_STATE_TOLERANCE_MM` | 1.0 | Allowed mm of shift to show steady state (Green dot) |

---

## VL53L4CD Calibration Protocol
For accurate readings through 2mm plexiglass against a 17% white reflecting target:
1. Hit **Start All** to verify the sensors connect, then hit **Stop All**.
2. Click **[🔧 Calibrate]** in the GUI.
3. Select your physical sensor (Sensor 1 - 8) and input the true distance from the sensor to the target.
4. The system calculates and saves the `Offset` and `Xtalk` compensation to `calibration.json`.
5. These profiles are automatically applied on every startup!
