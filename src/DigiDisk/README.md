# VL53L4CD Multi-Sensor Infiltrometer System

High-performance water level monitoring system using up to 10 VL53L4CD Time-of-Flight sensors for unsaturated soil conductivity measurements.

## Features

✅ **Flexible Sensor Configuration**: Support for 1-10 sensors (easily configurable)  
✅ **Fast Measurements**: Up to 50 Hz per sensor (20ms timing budget)  
✅ **Optimized for Short Range**: 2-50 cm measurement range  
✅ **High Accuracy**: ±1% typical, ±3mm @ 10cm  
✅ **Automatic Address Management**: Dynamic I2C address assignment  
✅ **Data Validation**: Built-in signal quality checks  
✅ **Moving Average Filter**: Optional noise reduction  
✅ **Comprehensive Diagnostics**: Detailed initialization and debug output  

## Hardware Requirements

- **Microcontroller**: ESP32-WROOM-32 DevKit C
- **Sensors**: 1-10x VL53L4CD ToF modules
- **Power**: 5V @ 1A power supply
- **Additional**: Pull-up resistors, decoupling capacitors (see wiring guide)

## Quick Start

### 1. Install PlatformIO

```bash
# Using VS Code
# Install PlatformIO IDE extension from VS Code marketplace

# Or using CLI
pip install platformio
```

### 2. Clone/Download Project

```bash
git clone <repository-url>
cd infiltrometer_project
```

### 3. Configure Number of Sensors

Edit `include/config.h`:

```cpp
// Change this line to match your sensor count (1-10)
#define NUM_SENSORS 3  // Example: using 3 sensors
```

### 4. Connect Hardware

Follow the detailed wiring guide in `docs/WIRING_GUIDE.md`

**Quick connection summary**:
- All sensors share I2C bus (GPIO 21/22)
- Each sensor has unique XSHUT pin (see config.h)
- 10kΩ pull-ups on SDA and SCL
- Decoupling caps on each sensor

### 5. Upload Firmware

```bash
# Using PlatformIO CLI
pio run --target upload

# Or using VS Code
# Click "Upload" button in PlatformIO toolbar
```

### 6. Monitor Output

```bash
# Using PlatformIO CLI
pio device monitor

# Or using VS Code
# Click "Serial Monitor" button in PlatformIO toolbar
```

Expected output:
```
╔═════════════════════════════════════════════════════════════════╗
║     VL53L4CD Multi-Sensor Infiltrometer System                 ║
║     Optimized for 2-50cm Water Level Measurement               ║
╚═════════════════════════════════════════════════════════════════╝

═══ SYSTEM INITIALIZATION ═══

▸ Initializing I2C: SDA=21, SCL=22, Freq=1000 kHz
  ✓ I2C initialized
...
```

## Configuration Options

All settings are in `include/config.h`:

### Basic Settings

```cpp
#define NUM_SENSORS 10              // Number of sensors (1-10)
#define I2C_FREQ 1000000           // I2C speed: 1 MHz (max)
#define TIMING_BUDGET_MS 20        // Measurement time per sensor
#define MEASUREMENT_INTERVAL_MS 50 // Read all sensors every 50ms
```

### Advanced Settings

```cpp
// Data validation
#define ENABLE_DATA_VALIDATION true
#define MIN_SIGNAL_KCPS 100        // Minimum acceptable signal
#define MAX_SIGMA_MM 15            // Maximum noise level

// Moving average filter
#define ENABLE_DATA_AVERAGING true
#define AVERAGING_WINDOW 5         // Number of samples to average

// Debug output
#define DEBUG_ENABLED true
#define DEBUG_INIT true            // Initialization details
#define DEBUG_MEASUREMENTS false   // Per-measurement details
```

### GPIO Pin Configuration

Default XSHUT pins (can be changed in config.h):

```cpp
const uint8_t XSHUT_PINS[10] = {
    25, 26, 27, 14, 12, 13, 15, 32, 33, 4
};
```

**Safe GPIOs for ESP32-WROOM**:
- ✅ Use: 4, 12-15, 25-27, 32-33
- ⚠️ Avoid: 0, 2, 5, 12, 15 (boot pins - test carefully)
- ❌ Never: 6-11 (flash pins), 34-39 (input only)

## Understanding the Output

### Initialization Output

```
┌─ Sensor 0 [Sensor_01] ─────────────────────────
│  Isolating sensor... ✓
│  Device detected... ✓
│  Sensor configured... ✓
│  Optimizing for short range... ✓
│  Address changed... ✓
│  Ranging started... ✓
└─ ✓ Sensor 0 initialized at address 0x30
```

### Measurement Output

```
────────────────────────────────────────────────────────────────
Measurement Cycle #20 (Rate: 20.0 Hz)
────────────────────────────────────────────────────────────────
Sensor_01 (0x30):  245 mm | Sig: 12456 kcps | Amb:   124 kcps | Status: 0
Sensor_02 (0x31):  182 mm | Sig: 15234 kcps | Amb:   156 kcps | Status: 0
Sensor_03 (0x32):  327 mm | Sig:  9876 kcps | Amb:   198 kcps | Status: 0
...
```

**Field meanings**:
- **Distance**: Measured distance in millimeters
- **Sig**: Signal strength in kilo-counts per second
- **Amb**: Ambient light level in kcps
- **Status**: 0 = valid, other values indicate errors

## Measurement Performance

### Timing Budget vs. Accuracy

| Timing Budget | Max Rate | Range (17%) | Accuracy |
|---------------|----------|-------------|----------|
| 10 ms | 100 Hz | 300 mm | ±5 mm |
| 20 ms | 50 Hz | 400 mm | ±3 mm |
| 33 ms | 30 Hz | 450 mm | ±2 mm |
| 50 ms | 20 Hz | 500 mm | ±1 mm |

### Distance vs. Target Reflectance

| Target | Max Range (20ms) | Signal @ 10cm |
|--------|------------------|---------------|
| White (88%) | 500 mm | Very High |
| Gray (50%) | 400 mm | High |
| Gray (17%) | 300 mm | Medium |
| Black (5%) | 150 mm | Low |

**For water surface**: Typical reflectance ~5-10% (similar to dark gray)

## Calibration (Optional)

The VL53L4CD has factory calibration, but you can improve accuracy:

### Offset Calibration

1. Place a gray target at known distance (e.g., 100mm)
2. Record measured distance
3. Calculate offset: `offset = measured - actual`
4. Subtract offset from all readings

### Temperature Compensation

Temperature affects ranging. The sensor has built-in compensation, but for highest accuracy:

1. Measure temperature with external sensor
2. Apply correction: `-0.02mm per °C`

## Troubleshooting

### Sensor Not Detected

**Symptoms**: `Device detection... ✗` in initialization

**Solutions**:
1. Check power connections (3.3V and GND)
2. Verify I2C pull-up resistors (10kΩ)
3. Confirm XSHUT pin wired correctly
4. Check I2C bus with scanner (enabled in config.h)

### Address Change Fails

**Symptoms**: `Address change... ✗`

**Solutions**:
1. Ensure only one sensor powered at a time
2. Check all other XSHUT pins are LOW
3. Verify I2C communication working
4. Try different I2C addresses (avoid 0x00-0x07, 0x78-0x7F)

### Noisy/Unstable Readings

**Symptoms**: Distance jumps erratically

**Solutions**:
1. Add decoupling capacitors (100nF + 4.7µF per supply pin)
2. Shorten I2C cable length
3. Enable moving average filter
4. Reduce I2C frequency to 400kHz
5. Check target reflectance (increase if too low)

### Intermittent Communication

**Symptoms**: Some sensors work, others don't

**Solutions**:
1. Check power supply capacity (needs 500mA minimum)
2. Add bulk capacitor (100µF) on 3.3V rail
3. Verify all ground connections
4. Test sensors individually
5. Check for I2C bus contention

### Wrong Distance Readings

**Symptoms**: Distance consistently off by fixed amount

**Solutions**:
1. Perform offset calibration
2. Check sensor orientation (should face target)
3. Verify target is in range (20-500mm)
4. Ensure clear line of sight
5. Check for IR interference (sunlight, other IR sources)

## Project Structure

```
infiltrometer_project/
├── include/
│   └── config.h              # All configuration settings
├── src/
│   └── main.cpp              # Main application code
├── docs/
│   ├── WIRING_GUIDE.md       # Detailed wiring instructions
│   └── README.md             # This file
├── platformio.ini            # PlatformIO configuration
└── README.md                 # Project overview
```

## API Reference (Key Functions)

### User-Modifiable Functions

```cpp
// Main loop function - add your data processing here
void loop() {
    readAllSensors();           // Read all sensors
    // Your code here:
    // - Send data over WiFi
    // - Log to SD card
    // - Control actuators
    // - Calculate infiltration rate
}
```

### Available Sensor Data

```cpp
for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (sensors[i].current_data.valid) {
        uint16_t distance = sensors[i].current_data.distance_mm;
        uint32_t signal = sensors[i].current_data.signal_kcps;
        uint8_t status = sensors[i].current_data.range_status;
        uint32_t timestamp = sensors[i].current_data.timestamp;
        
        // Get averaged distance (if enabled)
        uint16_t avg_distance = getAveragedDistance(i);
    }
}
```

## Adding Custom Features

### Example: WiFi Data Transmission

```cpp
// In setup(), after initializeSystem():
WiFi.begin("SSID", "password");

// In loop(), modify readAllSensors section:
if (measurement_count % 10 == 0) {  // Every 10 measurements
    String json = "{";
    for (uint8_t i = 0; i < NUM_SENSORS; i++) {
        if (sensors[i].initialized) {
            json += "\"sensor" + String(i) + "\":" + 
                    String(sensors[i].current_data.distance_mm) + ",";
        }
    }
    json += "}";
    // Send json via HTTP/MQTT
}
```

### Example: SD Card Logging

```cpp
#include <SD.h>

// In setup():
SD.begin(CS_PIN);
File dataFile = SD.open("data.csv", FILE_WRITE);
dataFile.println("timestamp,sensor,distance,signal,status");
dataFile.close();

// In loop():
File dataFile = SD.open("data.csv", FILE_APPEND);
for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (sensors[i].current_data.valid) {
        dataFile.printf("%lu,%d,%d,%lu,%d\n",
            millis(),
            i,
            sensors[i].current_data.distance_mm,
            sensors[i].current_data.signal_kcps,
            sensors[i].current_data.range_status
        );
    }
}
dataFile.close();
```

## Performance Optimization Tips

1. **Maximize Speed**:
   - Reduce `TIMING_BUDGET_MS` to 10-15ms
   - Set `INTER_MEASUREMENT_MS` to 0
   - Increase I2C to 1 MHz

2. **Maximize Range**:
   - Increase `TIMING_BUDGET_MS` to 50ms
   - Use white/reflective targets
   - Reduce ambient light

3. **Maximize Accuracy**:
   - Increase `TIMING_BUDGET_MS`
   - Enable averaging with large window
   - Perform offset calibration
   - Maintain stable temperature

## Known Limitations

- **Maximum sensors**: 10 (limited by available GPIO pins)
- **Maximum range**: ~500mm with white target, ~300mm with gray
- **Minimum range**: 20mm (closer distances unreliable)
- **I2C speed**: 1 MHz maximum (VL53L4CD limitation)
- **Sunlight**: Direct sunlight affects readings
- **Transparent surfaces**: Glass/water surface may have lower reflectance

## Contributing

For improvements or bug fixes:
1. Test thoroughly with actual hardware
2. Update documentation
3. Follow existing code style
4. Add comments for complex logic

## Support

For issues:
1. Check troubleshooting section
2. Verify wiring against guide
3. Test with single sensor first
4. Enable debug output
5. Check serial monitor for error messages

## License

[Your license here]

## References

- [VL53L4CD Datasheet](https://www.st.com/resource/en/datasheet/vl53l4cd.pdf)
- [ESP32-WROOM-32 Datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf)
- [PlatformIO Documentation](https://docs.platformio.org/)

## Version History

- **v1.0.0** (2024): Initial release
  - Support for 1-10 sensors
  - Optimized for 2-50cm range
  - Moving average filter
  - Comprehensive diagnostics

## Author

[Your name/organization]

## Acknowledgments

- STMicroelectronics for VL53L4CD sensor and Arduino library
- Espressif for ESP32 platform
- PlatformIO for development environment
