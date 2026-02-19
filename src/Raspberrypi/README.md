# Infiltrometer Controller — Documentation

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
| Waveshare UPS Hat (C) for Raspberry Pi Zero 5V | LiPo power management + UPS | 1 |
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
3. Copy the infiltrometer folder to the Pi.
4. Run:
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
├── sensor_manager.py  MCP23017 + VL53L4CD driver
├── data_logger.py     CSV logging to USB stick
├── gui.py             PyQt5 GUI
└── setup.sh           Installation script
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
| Battery % not showing | Check PiJuice HAT is seated on GPIO header |
| GUI not starting | `journalctl -u infiltrometer -f` for logs |

---

## Adjustable Parameters (config.py)

| Parameter | Default | Description |
|---|---|---|
| `LOW_WATER_THRESHOLD_MM` | 20 | Trigger low water warning below this distance |
| `MEASUREMENT_INTERVALS` | [1,2,5,10,30,60] | Available intervals in GUI dropdown |
| `DEFAULT_INTERVAL` | 5 | Default measurement interval (seconds) |
| `USB_MOUNT_PATH` | /media/pi | Where USB sticks are mounted |
| `GRAPH_HISTORY` | 120 | Data points in live graph |
