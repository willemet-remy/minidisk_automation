# ESP32-S3-N16R8 Wiring Guide for VL53L4CD Multi-Sensor System

## Board Specifications

**Your Board**: Heemol ESP32-S3-N16R8 DevKitC-1
- **MCU**: ESP32-S3-WROOM-1 module
- **Flash**: 16MB
- **PSRAM**: 8MB
- **USB**: Native USB-C (CDC/JTAG)
- **Wireless**: WiFi 2.4GHz + Bluetooth 5.0 LE
- **Antenna**: PCB antenna + 2.4G + IPEX connector

## Pin Mapping for ESP32-S3

### I2C Connection (Shared by All Sensors)

```
ESP32-S3 Pin          Function    →  All VL53L4CD Sensors
─────────────────────────────────────────────────────────
GPIO 8 (Default SDA)  I2C Data    →  Pin 9 (SDA) on all sensors
GPIO 9 (Default SCL)  I2C Clock   →  Pin 10 (SCL) on all sensors
```

**Important for ESP32-S3**:
- GPIO 8 and 9 are the default I2C pins
- Add 10kΩ pull-up resistors from SDA to 3.3V
- Add 10kΩ pull-up resistors from SCL to 3.3V
- Only ONE set of pull-ups needed for the entire I2C bus

### XSHUT Pin Assignments (Individual per Sensor)

```
ESP32-S3 GPIO    →  Sensor #   →  VL53L4CD Pin 5 (XSHUT)
────────────────────────────────────────────────────────
GPIO 1           →  Sensor 0   →  XSHUT
GPIO 2           →  Sensor 1   →  XSHUT
GPIO 3           →  Sensor 2   →  XSHUT
GPIO 4           →  Sensor 3   →  XSHUT
GPIO 5           →  Sensor 4   →  XSHUT
GPIO 6           →  Sensor 5   →  XSHUT
GPIO 7           →  Sensor 6   →  XSHUT
GPIO 10          →  Sensor 7   →  XSHUT
GPIO 11          →  Sensor 8   →  XSHUT
GPIO 12          →  Sensor 9   →  XSHUT
```

### Power Connections (Each Sensor)

```
VL53L4CD Pin      →  Connection
──────────────────────────────────
Pin 11 (AVDD)     →  3.3V + 100nF + 4.7µF to GND
Pin 1 (AVDDVCSEL) →  3.3V + 100nF + 4.7µF to GND
Pin 2 (AVSSVCSEL) →  GND
Pin 3 (GND)       →  GND
Pin 4 (GND2)      →  GND
Pin 6 (GND3)      →  GND
Pin 12 (GND4)     →  GND
Pin 8 (DNC)       →  **LEAVE FLOATING** (Do NOT connect!)
Pin 7 (GPIO1)     →  Optional (not used in this firmware)
```

## ESP32-S3 Pinout Reference

```
                    ESP32-S3 DevKitC-1
                    ┌──────────────────┐
                    │                  │
              GND ──┤ 1            40 ├── GND
             3.3V ──┤ 2            39 ├── GPIO46
              RST ──┤ 3            38 ├── GPIO45
              IO4 ──┤ 4  ●     ●   37 ├── GPIO0 (BOOT)
              IO5 ──┤ 5            36 ├── GPIO35
              IO6 ──┤ 6            35 ├── GPIO36
              IO7 ──┤ 7            34 ├── GPIO37
             IO15 ──┤ 8            33 ├── GPIO38
             IO16 ──┤ 9            32 ├── GPIO39
             IO17 ──┤10            31 ├── GPIO40
             IO18 ──┤11            30 ├── GPIO41
        IO8 (SDA) ──┤12            29 ├── GPIO42
        IO9 (SCL) ──┤13            28 ├── RXD0
             IO46 ──┤14            27 ├── TXD0
              IO3 ──┤15            26 ├── GPIO2
              IO10 ──┤16            25 ├── GPIO1
              IO11 ──┤17            24 ├── GPIO44
              IO12 ──┤18            23 ├── GPIO43
              IO13 ──┤19            22 ├── GPIO19 (USB D-)
              IO14 ──┤20            21 ├── GPIO20 (USB D+)
                    └──────────────────┘
                          USB-C
```

## Complete Wiring Diagram

### Single Sensor Connection

```
ESP32-S3 DevKitC-1          VL53L4CD Sensor
┌─────────────┐            ┌──────────────────┐
│             │            │  VL53L4CD ToF    │
│ 3.3V  ──────┼────┬───────┤ Pin 11 (AVDD)    │
│             │    │       │                  │
│             │  100nF     │                  │
│             │    ║       │                  │
│             │  4.7µF     │                  │
│             │    ║       │                  │
│             │    │       │                  │
│ GND   ──────┼────┴───────┤ Pin 3 (GND)      │
│             │    │       │ Pin 4 (GND2)     │
│             │    │       │ Pin 6 (GND3)     │
│             │    │       │ Pin 12 (GND4)    │
│             │    │       │                  │
│             │    │  ┌────┤ Pin 1 (AVDDVCSEL)│
│             │    │  │    │                  │
│             │  100nF│    │                  │
│             │    ║  │    │                  │
│             │  4.7µF│    │                  │
│             │    ║  │    │                  │
│             │    └──┘    │                  │
│             │            │ Pin 2 (AVSSVCSEL)├── GND
│             │            │                  │
│ GPIO8 ──────┼────────────┤ Pin 9 (SDA)      │
│   (SDA)     │     10kΩ   │                  │
│             │      to    │                  │
│             │     3.3V   │                  │
│             │            │                  │
│ GPIO9 ──────┼────────────┤ Pin 10 (SCL)     │
│   (SCL)     │     10kΩ   │                  │
│             │      to    │                  │
│             │     3.3V   │                  │
│             │            │                  │
│ GPIO1 ──────┼────────────┤ Pin 5 (XSHUT)    │
│             │            │                  │
│             │            │ Pin 7 (GPIO1)    │─ (optional, unused)
│             │            │                  │
│             │            │ Pin 8 (DNC)      │─ **LEAVE FLOATING!**
│             │            │                  │
└─────────────┘            └──────────────────┘
```

### Multi-Sensor System (10 Sensors)

```
ESP32-S3                   Sensor 0    Sensor 1    Sensor 2    ...  Sensor 9
┌─────────────┐
│ 3.3V  ──────┼───────┬──────┬──────────┬──────────┬────────────────┬──────
│             │       │      │          │          │                │
│ GND   ──────┼───────┴──────┴──────────┴──────────┴────────────────┴──────
│             │       │      │          │          │                │
│ GPIO8 ──────┼───────┼──────┼──────────┼──────────┼────────────────┼──────
│   (SDA)     │       │      │          │          │                │
│             │    10kΩ to 3.3V         │          │                │
│             │       │      │          │          │                │
│ GPIO9 ──────┼───────┼──────┼──────────┼──────────┼────────────────┼──────
│   (SCL)     │       │      │          │          │                │
│             │    10kΩ to 3.3V         │          │                │
│             │       │      │          │          │                │
│ GPIO1 ──────┼───────┤      │          │          │                │
│             │     XSHUT    │          │          │                │
│             │       │      │          │          │                │
│ GPIO2 ──────┼───────┼──────┤          │          │                │
│             │       │    XSHUT        │          │                │
│             │       │      │          │          │                │
│ GPIO3 ──────┼───────┼──────┼──────────┤          │                │
│             │       │      │        XSHUT        │                │
│             │       │      │          │          │                │
│ GPIO4 ──────┼───────┼──────┼──────────┼──────────┤                │
│  ...        │       │      │          │        XSHUT               │
│ GPIO12 ─────┼───────┼──────┼──────────┼──────────┼────────────────┤
│             │       │      │          │          │              XSHUT
└─────────────┘
```

## ESP32-S3 Specific Notes

### ⚠️ Important GPIO Considerations

**Safe GPIOs for XSHUT** (Used in config):
- ✅ GPIO 1-7, 10-18 (General purpose, safe to use)
- ✅ GPIO 21, 33-37, 38-42, 45-46 (Also available if needed)

**GPIOs to AVOID**:
- ❌ GPIO 0: Boot button (use with caution)
- ❌ GPIO 8-9: I2C bus (reserved for SDA/SCL)
- ❌ GPIO 19-20: USB D-/D+ (native USB)
- ❌ GPIO 26-32: Reserved for PSRAM (N16R8 has PSRAM)
- ❌ GPIO 43-44: UART0 (serial console)

### USB Connection

Your ESP32-S3 has **native USB**:
- Uses GPIO 19 (D-) and GPIO 20 (D+) internally
- No need for external USB-UART chip
- Serial monitor works directly via USB-C
- Can act as USB device (CDC, MSC, HID, etc.)

### Power Considerations

**ESP32-S3 Power Consumption**:
- Active (WiFi TX): ~180 mA
- Active (no WiFi): ~40 mA
- 10 sensors: ~240 mA
- **Total system**: ~280-420 mA average, ~600 mA peak

**Power Supply Options**:
1. **USB-C**: 5V from USB (easiest for development)
2. **External**: 5V @ 1A regulator → 5V pin
3. **Battery**: 3.7V LiPo → 5V boost converter → 5V pin

### WiFi Antenna

Your board has three antenna options:
1. **PCB antenna** (built-in, default)
2. **External 2.4GHz antenna** (higher gain)
3. **IPEX connector** (for external antenna)

To use external antenna, you may need to move a 0Ω resistor (check board documentation).

## Component Requirements

### Per Sensor (10 sensors total)
- 2× 100nF ceramic capacitors (AVDD and AVDDVCSEL to GND)
- 2× 4.7µF ceramic capacitors (AVDD and AVDDVCSEL to GND)

### System-Wide
- 1× 10kΩ resistor (SDA pull-up to 3.3V)
- 1× 10kΩ resistor (SCL pull-up to 3.3V)
- 1× 100µF electrolytic capacitor (3.3V rail to GND, near ESP32)

### Total Component List
- 40× ceramic capacitors (20× 100nF + 20× 4.7µF)
- 2× 10kΩ resistors
- 1× 100µF capacitor
- Breadboard or custom PCB
- Jumper wires (22-24 AWG recommended)

## Breadboard Assembly Guide

### Step 1: Power Rails
1. Connect ESP32-S3 3.3V pin to breadboard positive rail
2. Connect ESP32-S3 GND to breadboard ground rail
3. Add 100µF capacitor across rails (near ESP32)

### Step 2: I2C Bus
1. Connect GPIO 8 to a dedicated breadboard row (SDA)
2. Connect GPIO 9 to another row (SCL)
3. Add 10kΩ pull-up from SDA row to 3.3V rail
4. Add 10kΩ pull-up from SCL row to 3.3V rail

### Step 3: Sensor 0 (Test First)
1. Insert VL53L4CD into breadboard
2. Connect Pin 11 (AVDD) → 3.3V rail
3. Connect Pin 1 (AVDDVCSEL) → 3.3V rail
4. Connect Pins 2,3,4,6,12 (all GND) → GND rail
5. Add 100nF capacitor near Pin 11 to GND
6. Add 4.7µF capacitor near Pin 11 to GND
7. Add 100nF capacitor near Pin 1 to GND
8. Add 4.7µF capacitor near Pin 1 to GND
9. Connect Pin 9 (SDA) → SDA row
10. Connect Pin 10 (SCL) → SCL row
11. Connect Pin 5 (XSHUT) → GPIO 1
12. **Leave Pin 8 floating** (do NOT connect)

### Step 4: Test Single Sensor
1. Upload firmware with `NUM_SENSORS = 1`
2. Open serial monitor (115200 baud)
3. Verify sensor initializes successfully
4. Check distance readings

### Step 5: Add More Sensors
Repeat Step 3 for each additional sensor:
- Sensor 1: XSHUT → GPIO 2
- Sensor 2: XSHUT → GPIO 3
- Sensor 3: XSHUT → GPIO 4
- ... and so on

Update `NUM_SENSORS` in config.h as you add sensors.

## Wiring Checklist

Before powering on:
- [ ] 3.3V connected to all sensor AVDD pins (Pin 11)
- [ ] 3.3V connected to all sensor AVDDVCSEL pins (Pin 1)
- [ ] All GND pins connected (Pins 2, 3, 4, 6, 12 on each sensor)
- [ ] Pin 8 (DNC) on all sensors is NOT connected
- [ ] GPIO 8 connected to all sensor SDA pins (Pin 9)
- [ ] GPIO 9 connected to all sensor SCL pins (Pin 10)
- [ ] 10kΩ pull-ups on SDA and SCL lines
- [ ] Each sensor has 4 capacitors installed
- [ ] Each XSHUT pin goes to unique GPIO
- [ ] 100µF bulk capacitor on 3.3V rail
- [ ] No shorts between 3.3V and GND (verify with multimeter!)

## Testing Procedure

### 1. Single Sensor Test
```cpp
// In config.h
#define NUM_SENSORS 1
```
Upload, verify Sensor 0 works

### 2. Add Sensors Incrementally
```cpp
// In config.h
#define NUM_SENSORS 2  // Then 3, 4, etc.
```
Upload after each addition

### 3. Full System Test
```cpp
// In config.h
#define NUM_SENSORS 10
```
Upload, verify all 10 sensors work

## Expected Serial Output

```
╔═════════════════════════════════════════════════════════════════╗
║     VL53L4CD Multi-Sensor Infiltrometer System                 ║
║     ESP32-S3-N16R8 DevKitC-1                                   ║
║     Optimized for 2-50cm Water Level Measurement               ║
╚═════════════════════════════════════════════════════════════════╝

═══ SYSTEM INITIALIZATION ═══

▸ Initializing I2C: SDA=8, SCL=9, Freq=1000 kHz
  ✓ I2C initialized

▸ Configuring 10 XSHUT pins:
  GPIO 1 → Sensor 0
  GPIO 2 → Sensor 1
  ...
  GPIO 12 → Sensor 9
  ✓ All XSHUT pins configured

═══ SENSOR INITIALIZATION SEQUENCE ═══

┌─ Sensor 0 [Sensor_01] ─────────────────────────
│  Device detected... ✓
│  Sensor configured... ✓
│  Address changed... ✓
│  Ranging started... ✓
└─ ✓ Sensor 0 initialized at address 0x30

[Repeat for all 10 sensors]

═══ INITIALIZATION SUMMARY ═══
Sensors initialized: 10 / 10
Success rate: 100.0%
Status: ALL SENSORS OPERATIONAL ✓

✓ SYSTEM READY - Starting measurements...
```

## Troubleshooting ESP32-S3 Specific Issues

### Serial Monitor Shows Nothing
- **Cause**: USB CDC not enabled
- **Solution**: Already configured in platformio.ini with `ARDUINO_USB_CDC_ON_BOOT=1`
- **Alternative**: Press BOOT + RESET buttons

### Upload Fails
- **Solution 1**: Hold BOOT button during upload
- **Solution 2**: Press BOOT, then RESET, then release BOOT
- **Solution 3**: Try different USB cable (data cable, not charge-only)

### PSRAM Warning
- Your board has PSRAM (8MB) which is already configured
- If you see PSRAM errors, it's usually harmless for this application

### WiFi Interference
- VL53L4CD uses IR (~940nm), WiFi uses 2.4GHz
- No interference expected
- Can use WiFi simultaneously for data transmission

## PCB Design Tips for ESP32-S3

If designing a custom PCB:
1. Use USB-C connector for power and programming
2. Add auto-reset circuit (DTR/RTS)
3. Include 10µF capacitor on EN pin
4. Add ESD protection on USB lines
5. Keep I2C traces short and parallel
6. Use ground plane under all sensors
7. Consider antenna keep-out zone

## Power Optimization for Battery Operation

ESP32-S3 has excellent power management:
```cpp
// Add to setup() for battery operation:
esp_sleep_enable_timer_wakeup(60 * 1000000); // Wake every 60 seconds
// Take readings
esp_deep_sleep_start(); // Sleep between readings
```

With this approach:
- Active: ~280 mA for ~2 seconds
- Sleep: ~10 µA
- Average: ~10-20 mA (depending on wake interval)

## Next Steps

1. Wire one sensor following this guide
2. Upload firmware with `NUM_SENSORS = 1`
3. Verify it works
4. Add sensors one by one
5. Test full 10-sensor system
6. Deploy in your infiltrometer application

Your ESP32-S3-N16R8 is perfect for this application with plenty of GPIO, PSRAM for data buffering, and WiFi for remote monitoring!
