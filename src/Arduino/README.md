# Minidisk Automation

This directory contains the complete software suite for the Minidisk Infiltrometer, including the Arduino (PlatformIO) firmware and the Python Desktop Application.

## 1. Hardware Requirements
*   Arduino Nano (ATmega328P)
*   6x Analog Pressure Sensors connected to pins `A1` through `A6`.

## 2. Directory Structure
*   `src/main.cpp`: The non-blocking C++ firmware for the Arduino. It samples sensors every 5 seconds and streams the values over Serial.
*   `minidisk_app.py`: The PyQt5 Desktop Application used to connect, log data accurately, and determine steady-state certitude.
*   `mock_arduino.py`: A Python script to simulate an Arduino on your computer for testing the GUI without physical hardware.

## 3. How to Install and Flash Firmware

We use **PlatformIO** (an extension for VS Code) to manage the Arduino firmware:
1. Open this `Arduino/` folder in VS Code.
2. Install the PlatformIO extension if you haven't already.
3. Plug in your Arduino Nano via USB.
4. Click the PlatformIO **Upload** button (the `→` arrow in the bottom blue toolbar). This will compile the C++ code and flash it to the Arduino.

## 4. How to use the Python App

### Prerequisites
Make sure you have the required Python libraries installed:
```bash
pip3 install PyQt5 pyserial
```

### Running the App
1. Plug your Arduino Nano via USB.
2. Open a terminal in this directory and run:
   ```bash
   python3 minidisk_app.py
   ```
3. In the app:
   *   Select the **COM Port** from the dropdown and click **Connect USB**.
   *   Enter your **Plot Name**.
   *   Enter the **Tension** (in cmH2O) for each active sensor.
   *   Click **START MEASUREMENT**.

### Features and Controls
*   **Live Sensor Data**: The app displays real-time cmH₂O values for all 6 sensors.
*   **Stability indicator (Var & R²)**: The app intelligently calculates the slope over a shifting 50-second window. The Variation (`Var`) tells you how steady the slope is. If the `Var` goes below `0.005` and the `R²` fit is strong, the text will turn **Bright Green**, signaling you have likely reached *steady-state infiltration*.
*   **Per-Sensor Pause**: You can click the green **Active** button on any sensor to pause it. Its data will temporarily stop logging (saving blank columns in the CSV) while letting the remaining sensors continue. You can change the *Tension* value while paused, and resume immediately!
*   **Stop & Save**: When finished, press **STOP & SAVE** to gracefully close the `.csv` file. 

## 5. Simulating the Arduino (Testing)
If you want to test the GUI without water or a real Arduino:
1. Open a terminal and run `python3 mock_arduino.py`.
2. It will tell you the mock port name (e.g. `/dev/pts/X`). Keep this running.
3. Open a second terminal and run `python3 minidisk_app.py`.
4. Select the mock port from the dropdown, connect, and hit Start. Watch the green steady-state indicators kick in automatically!

## 6. Pressure-sensor calibration analysis

`analyse_pressure_calibration.py` fits each sensor against the manually logged
water-height observations in a calibration CSV and produces a graph with its
linear equation, R², RMSE, and PASS/FAIL result. It uses the latest
`minidisk_*Calibration*.csv` by default:

```bash
python analyse_pressure_calibration.py
```

Outputs are written to `calibration_analysis/`. A sensor passes by default when
R² is at least 0.98, RMSE is at most 1 cm, and the calibration spans at least
0.05 V. The thresholds can be overridden with the script options.
