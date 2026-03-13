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

## Warnings & Status Codes

When running the application, you may see warnings appear on the sensor tiles or the bottom panel.

| Warning / Status | Cause | Solution / Check |
|---|---|---|
| `⚠ GPIO fault` | Sensor detected a hardware interrupt/fault on its GPIO1 line. | Check wiring, ensure sensor is clean. Sometimes caused by power fluctuations. |
| `⚠ Low water!` | Distance measured is below `LOW_WATER_THRESHOLD_MM`. | Refill the water reservoir. |
| `⚠ Warning: [Text]` | The VL53L4CD sensor returned a non-zero status code (e.g. Signal failure, Out-of-bounds). | Check that the target is within range (up to 1.2m), the plexiglass is clean, and there is no direct sunlight blinding the sensor. |
| `Error` (Red dot) | Sensor completely stopped responding to I2C during measurement. | Check physical I2C (SDA/SCL) and power connections. |
| `MCP: ✗` | The MCP23017 multiplexer was not found. | Only 1 sensor can be used in this fallback mode. Check MCP wiring if you need multiple sensors. |

---

## Troubleshooting

| Problem | Check |
|---|---|
| Sensor not detected | Check XSHUT 10kΩ pull-down, verify SDA/SCL connections |
| All sensors fail init | Check I2C enabled (`i2cdetect -y 1`), check 4.7kΩ pull-ups |
| USB stick not found | Check `/media/pi/` for mount, try different USB stick |
| GUI not starting | `journalctl -u infiltrometer -f` for logs |

---

## FAQ & Technical Details

**What does the `mm` measurement represent?**
The `mm` value represents the corrected, true distance from the VL53L4CD sensor surface to the water/target surface. During calibration, the system calculates the impact of the plexiglass cover and optical crosstalk, and applies this correction directly to the sensor's hardware registers. This ensures the output is the actual, calibrated physical distance from the sensor to the target, rather than just a raw reading with a software offset.

**What is the communication delay between the sensor and the screen?**
The sensor requires roughly 50ms of "timing budget" per measurement to confidently calculate the distance. After that, I2C retrieval and GUI rendering take < 10ms. Therefore, the physical delay from the water level changing to the screen updating is approximately **50–60 milliseconds** plus the interval time you selected in the top bar.

**What is the advantage of lowering the I2C frequency?**
The system configures the I2C bus to 100 kHz (Standard Mode) rather than 400 kHz (Fast Mode). When running 8 sensors over relatively long wires, higher frequencies can cause signal degradation, cross-talk, and data corruption (I2C errors). Lowering the frequency makes the communication extremely stable and immune to wire capacitance, without noticeably affecting the measuring rate since the sensor bottleneck is its 50ms light-integration time.

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
