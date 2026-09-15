# 💻 Slimme Minidisk — Desktop Acquisition App

The desktop application connects to the ESP32 USB receiver and manages multi-sensor infiltration measurement sessions with real-time plotting and structured CSV data logging.

---

## 🚀 Installation & Launch

Requires Python 3.10+:

```powershell
# Install required dependencies
python -m pip install pyserial matplotlib

# Launch application
python minidisk_acquisition.py
```

---

## 📱 3-Screen Field Workflow

### Screen 1: Sensor Discovery & Selection
- Select the receiver COM/serial port and click **Connect**.
- Click **`🔍 Scan for sensors`** to query the receiver for all active wireless nodes.
- Click any row in the table to toggle its checkbox (**☑ / ☐**). Only checked sensors will be included in the measurement.
- Connected sensors are highlighted in green with live battery, distance, and last packet timestamp.
- Click **▶ Start measurement with selected sensors**.

### Screen 2: Campaign & Location Metadata Dialog
- **Campaign name**: Combobox that automatically remembers and autocompletes previously entered campaign names (e.g. `Morteau_2026`).
- **Location / Spot**: Unique identifier for the measurement point (e.g. `Plot_A_point_1`).
- **Notes**: Optional text saved into the CSV header.
- Clicking **OK** prompts for the CSV destination and opens the live measurement window.

### Screen 3: Live Measurement & Individual Infiltration Curves
- **Individual Matplotlib Subplots**: Each sensor has its own dedicated curve stacked vertically in a scrollable panel.
- **Inverted Y-Axis**: The Y-axis is inverted (distance in mm plotted downwards) to visually match the water meniscus dropping as infiltration progresses.
- **Per-Sensor Tension Input**: Each sensor row has an independent **Tension** input field ($cm\text{ }H_2O$) that can be updated at any time (e.g. `-0.5`, `-2`, `-5`). The current tension is saved synchronously with every distance reading.
- **Standby & Refill Handling**:
  - The live graph only plots when the sensor is in active measuring mode (`measuring = 1`).
  - Pausing a sensor (or refilling the infiltrometer tube) resets the graph view for that sensor to $t=0$, while all raw historical data remains safely preserved in the CSV file.
- Click **⏹ End measurement & save CSV** to finalize the file and return to Screen 1 for the next measurement spot.

---

## 📊 CSV File Format

Output CSV file naming: `{campaign}_{location}_{YYYYMMDD_HHMMSS}.csv`

| Column | Description |
|---|---|
| `timestamp` | ISO 8601 acquisition timestamp |
| `campaign` | Campaign name |
| `location` | Location / spot name |
| `notes` | Optional session notes |
| `sensor_name` | Human-readable node identity (e.g. `MINIDISK_01`) |
| `node_id` | Unique hardware node ID |
| `distance_mm` | Distance from sensor to water meniscus (mm) |
| `range_status` | VL53L4CD status code (0 = valid reading) |
| `tension_cm_h2o` | Applied suction tension in cm H₂O at the moment of reading |
| `battery_mv` | Node battery voltage in millivolts |
| `source_mac` | Node ESP-NOW MAC address |
