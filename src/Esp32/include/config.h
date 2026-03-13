#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// ===== SENSOR CONFIGURATION =====
// Adjust this to change the number of sensors (1-10 supported)
#define NUM_SENSORS 10

// I2C Configuration for ESP32-S3
// Using default I2C pins for ESP32-S3
#define I2C_SDA 8   // GPIO8 - Default SDA for ESP32-S3
#define I2C_SCL 9   // GPIO9 - Default SCL for ESP32-S3
#define I2C_FREQ 1000000  // 1MHz for fast communication (max for VL53L4CD)

// Default I2C address of VL53L4CD before reassignment
#define DEFAULT_I2C_ADDRESS 0x52

// ===== XSHUT PIN ASSIGNMENTS FOR ESP32-S3 =====
// GPIO pins for XSHUT control (one per sensor)
// ESP32-S3 safe GPIOs (avoiding strapping pins and USB pins)
// Safe to use: 1-7, 10-21, 33-46
// Avoid: 0 (boot button), 8-9 (I2C), 19-20 (USB), 26-32 (PSRAM), 43-44 (UART)
const uint8_t XSHUT_PINS[NUM_SENSORS] = {
    1,   // Sensor 0
    2,   // Sensor 1
    3,   // Sensor 2
    4,   // Sensor 3
    5,   // Sensor 4
    6,   // Sensor 5
    7,   // Sensor 6
    10,  // Sensor 7
    11,  // Sensor 8
    12   // Sensor 9
};

// ===== NEW I2C ADDRESSES =====
// Each sensor gets a unique address (must be different from 0x52)
// Valid range: 0x08 to 0x77 (avoiding reserved addresses)
const uint8_t SENSOR_I2C_ADDRESSES[NUM_SENSORS] = {
    0x30,  // Sensor 0
    0x31,  // Sensor 1
    0x32,  // Sensor 2
    0x33,  // Sensor 3
    0x34,  // Sensor 4
    0x35,  // Sensor 5
    0x36,  // Sensor 6
    0x37,  // Sensor 7
    0x38,  // Sensor 8
    0x39   // Sensor 9
};

// ===== RANGING CONFIGURATION =====
// Optimized for 2-50cm range
#define TIMING_BUDGET_MS 20           // 20ms for fast, accurate readings (50Hz max rate)
#define INTER_MEASUREMENT_MS 0        // Continuous mode (back-to-back measurements)
#define RANGE_MIN_MM 20              // Minimum expected range (2cm)
#define RANGE_MAX_MM 500             // Maximum expected range (50cm)

// ===== MEASUREMENT CONFIGURATION =====
#define MEASUREMENT_INTERVAL_MS 50    // Read all sensors every 50ms (20Hz)
#define ENABLE_DATA_VALIDATION true   // Enable range and signal quality checks
#define MIN_SIGNAL_KCPS 100          // Minimum signal strength for valid reading
#define MAX_SIGMA_MM 15              // Maximum sigma (noise) for valid reading

// ===== DEBUG CONFIGURATION =====
#define DEBUG_ENABLED true            // Enable detailed debug output
#define DEBUG_INIT true              // Debug initialization sequence
#define DEBUG_MEASUREMENTS false      // Debug each measurement (verbose)
#define DEBUG_I2C_SCAN true          // Debug I2C bus scanning

// ===== OPTIONAL FEATURES =====
#define ENABLE_INTERRUPT_MODE false   // Use GPIO1 interrupt (not implemented in this version)
#define ENABLE_DATA_AVERAGING true    // Enable moving average filter
#define AVERAGING_WINDOW 5           // Number of samples to average

// ===== SENSOR NAMES =====
// Optional: Human-readable names for each sensor location
const char* SENSOR_NAMES[NUM_SENSORS] = {
    "Sensor_01",
    "Sensor_02",
    "Sensor_03",
    "Sensor_04",
    "Sensor_05",
    "Sensor_06",
    "Sensor_07",
    "Sensor_08",
    "Sensor_09",
    "Sensor_10"
};

// ===== VALIDATION MACROS =====
#define IS_VALID_RANGE(dist) ((dist) >= RANGE_MIN_MM && (dist) <= RANGE_MAX_MM)
#define IS_VALID_SIGNAL(sig) ((sig) >= MIN_SIGNAL_KCPS)

#endif // CONFIG_H
