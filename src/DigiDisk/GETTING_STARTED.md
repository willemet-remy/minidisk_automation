# Getting Started - ESP32-S3-N16R8 Version

## 🚀 Your Board: Heemol ESP32-S3-N16R8 DevKitC-1

This is the ESP32-S3 optimized version with proper pin assignments for your board.

## What's Different for ESP32-S3?

✅ **I2C Pins**: GPIO 8 (SDA) and GPIO 9 (SCL)  
✅ **XSHUT Pins**: GPIO 1-7, 10-12 (safe pins selected)  
✅ **USB**: Native USB-C (no USB-UART chip needed)  
✅ **Power**: More powerful with PSRAM support  

## Quick Setup (5 Steps)

### 1. Install PlatformIO
- Install VS Code
- Add PlatformIO IDE extension
- Wait for installation to complete

### 2. Configure Sensors
Edit `include/config.h`:
```cpp
#define NUM_SENSORS 10  // Change to your count (1-10)
```

### 3. Wire Hardware
**I2C (shared by all sensors)**:
```
ESP32-S3 GPIO 8  → All sensors Pin 9 (SDA) + 10kΩ to 3.3V
ESP32-S3 GPIO 9  → All sensors Pin 10 (SCL) + 10kΩ to 3.3V
```

**XSHUT (one per sensor)**:
```
GPIO 1  → Sensor 0
GPIO 2  → Sensor 1
GPIO 3  → Sensor 2
GPIO 4  → Sensor 3
GPIO 5  → Sensor 4
GPIO 6  → Sensor 5
GPIO 7  → Sensor 6
GPIO 10 → Sensor 7
GPIO 11 → Sensor 8
GPIO 12 → Sensor 9
```

**Power (each sensor)**:
```
3.3V → Pin 1, Pin 11 (with 100nF + 4.7µF caps each)
GND  → Pin 2, 3, 4, 6, 12 (all GND pins!)
```

📄 See `docs/ESP32_S3_WIRING_GUIDE.md` for complete details  
📄 Print `docs/QUICK_REFERENCE_S3.md` for easy reference

### 4. Upload Firmware
1. Connect ESP32-S3 via USB-C
2. Open project in VS Code
3. Click Upload (→) in PlatformIO toolbar
4. If upload fails: Hold BOOT button during upload

### 5. Monitor Output
- Click Serial Monitor (🔌) in PlatformIO
- Baud rate: 115200
- You should see initialization sequence

## Expected Output

```
╔═════════════════════════════════════════════════════════════════╗
║     VL53L4CD Multi-Sensor Infiltrometer System                 ║
║     ESP32-S3-N16R8 DevKitC-1                                   ║
╚═════════════════════════════════════════════════════════════════╝

═══ SYSTEM INITIALIZATION ═══

▸ Initializing I2C: SDA=8, SCL=9, Freq=1000 kHz
  ✓ I2C initialized

▸ Configuring 10 XSHUT pins:
  GPIO 1 → Sensor 0
  GPIO 2 → Sensor 1
  ...
```

## ESP32-S3 Specific Tips

### Serial Monitor Blank?
- Press RESET button on board
- USB CDC is enabled by default
- May take 1-2 seconds to appear

### Upload Fails?
- **Hold BOOT button** during upload
- Try different USB cable (must be data cable)
- Check drivers installed

### Want to Use WiFi?
The code is ready - just add in `main.cpp`:
```cpp
#include <WiFi.h>

void setup() {
    // ... after initializeSystem()
    WiFi.begin("YourSSID", "YourPassword");
}
```

### Battery Operation?
ESP32-S3 has excellent sleep modes:
```cpp
esp_sleep_enable_timer_wakeup(60 * 1000000); // 60 seconds
// Take measurements
esp_deep_sleep_start();
```

## Pin Reference Table

| Function | ESP32-S3 GPIO | Notes |
|----------|---------------|-------|
| SDA | 8 | I2C data + 10kΩ pull-up |
| SCL | 9 | I2C clock + 10kΩ pull-up |
| XSHUT 0 | 1 | Sensor 0 shutdown |
| XSHUT 1 | 2 | Sensor 1 shutdown |
| XSHUT 2 | 3 | Sensor 2 shutdown |
| XSHUT 3 | 4 | Sensor 3 shutdown |
| XSHUT 4 | 5 | Sensor 4 shutdown |
| XSHUT 5 | 6 | Sensor 5 shutdown |
| XSHUT 6 | 7 | Sensor 6 shutdown |
| XSHUT 7 | 10 | Sensor 7 shutdown |
| XSHUT 8 | 11 | Sensor 8 shutdown |
| XSHUT 9 | 12 | Sensor 9 shutdown |

## Common Issues

### Problem: "Device detected... ✗"
✅ Check 3.3V and GND connections  
✅ Verify I2C pull-ups (10kΩ)  
✅ Check XSHUT wiring  

### Problem: "Address change... ✗"
✅ Ensure only one sensor powered  
✅ Check other XSHUT pins are LOW  
✅ Verify I2C communication works  

### Problem: Upload hangs
✅ Hold BOOT button during upload  
✅ Use quality USB-C cable  
✅ Try different USB port  

### Problem: Wrong readings
✅ Check sensor orientation  
✅ Verify decoupling capacitors  
✅ Enable averaging in config.h  

## Testing Procedure

**Start with 1 sensor**:
```cpp
// config.h
#define NUM_SENSORS 1
```
Upload → Test → Works? ✓

**Add sensors incrementally**:
```cpp
#define NUM_SENSORS 2  // then 3, 4, 5...
```

**Full system**:
```cpp
#define NUM_SENSORS 10
```

## Optimization Settings

### For Speed (50 Hz)
```cpp
#define TIMING_BUDGET_MS 10
#define MEASUREMENT_INTERVAL_MS 20
```

### For Accuracy
```cpp
#define TIMING_BUDGET_MS 50
#define ENABLE_DATA_AVERAGING true
#define AVERAGING_WINDOW 10
```

### For Battery Life
```cpp
#define TIMING_BUDGET_MS 33
#define MEASUREMENT_INTERVAL_MS 1000
// Add deep sleep in main.cpp
```

## Component Checklist

For 10 sensors:
- [ ] 40× ceramic capacitors (20× 100nF + 20× 4.7µF)
- [ ] 2× 10kΩ resistors (I2C pull-ups)
- [ ] 1× 100µF capacitor (bulk power)
- [ ] 1× ESP32-S3-N16R8 board
- [ ] 10× VL53L4CD sensors
- [ ] Breadboard or PCB
- [ ] USB-C cable (data, not charge-only!)
- [ ] 5V @ 1A power supply

## Your ESP32-S3 Advantages

✅ **16MB Flash**: Lots of room for code  
✅ **8MB PSRAM**: Buffer sensor data  
✅ **WiFi + BLE 5.0**: Wireless connectivity  
✅ **USB-C Native**: Easy programming  
✅ **240 MHz**: Fast processing  
✅ **Low Power**: Great for battery  

## Next Steps

1. ✅ Wire first sensor
2. ✅ Upload with NUM_SENSORS = 1
3. ✅ Verify it works
4. ✅ Add more sensors
5. ✅ Deploy in infiltrometer
6. ➕ Add WiFi data logging
7. ➕ Add web interface
8. ➕ Add battery + sleep mode

## Documentation

- **Wiring Details**: `docs/ESP32_S3_WIRING_GUIDE.md`
- **Quick Ref**: `docs/QUICK_REFERENCE_S3.md` (print!)
- **Full Docs**: `README.md`
- **Config**: `include/config.h`

## Success Checklist

- [ ] PlatformIO installed
- [ ] Project opens in VS Code
- [ ] NUM_SENSORS set in config.h
- [ ] Hardware wired correctly
- [ ] Firmware uploads successfully
- [ ] Serial monitor shows output
- [ ] All sensors initialize ✓
- [ ] Readings make sense
- [ ] System runs continuously

**Once complete, your system is ready!**

---

**Board**: ESP32-S3-N16R8 DevKitC-1  
**Sensors**: VL53L4CD (up to 10)  
**Platform**: PlatformIO + Arduino
