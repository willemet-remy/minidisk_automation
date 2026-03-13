#include <Arduino.h>
#include <Wire.h>
#include <vl53l4cd_class.h>
#include "config.h"

// ===== DATA STRUCTURES =====

struct SensorData {
    uint16_t distance_mm;
    uint32_t signal_kcps;
    uint32_t ambient_kcps;
    uint16_t sigma_mm;
    uint8_t range_status;
    uint32_t timestamp;
    bool valid;
};

struct SensorState {
    VL53L4CD* sensor;
    bool initialized;
    bool ranging;
    uint8_t i2c_address;
    SensorData current_data;
    // For averaging
    uint16_t distance_buffer[AVERAGING_WINDOW];
    uint8_t buffer_index;
    bool buffer_filled;
};

// ===== GLOBAL VARIABLES =====
SensorState sensors[NUM_SENSORS];
uint32_t last_measurement_time = 0;
uint32_t measurement_count = 0;
bool system_initialized = false;

// ===== FUNCTION PROTOTYPES =====
void initializeSystem();
bool initializeSensor(uint8_t sensor_index);
bool changeSensorI2CAddress(VL53L4CD* sensor, uint8_t new_address);
void shutdownAllSensors();
void startupSensor(uint8_t sensor_index);
bool verifyI2CDevice(uint8_t address);
void scanI2CBus();
void configureSensorForShortRange(VL53L4CD* sensor);
void readAllSensors();
void readSensor(uint8_t sensor_index);
void updateMovingAverage(uint8_t sensor_index, uint16_t new_distance);
uint16_t getAveragedDistance(uint8_t sensor_index);
void printSystemStatus();
void printSensorData(uint8_t sensor_index);
void printInitProgress(uint8_t sensor_index, const char* step, bool success);

// ===== SETUP =====
void setup() {
    Serial.begin(115200);
    delay(2000);  // Wait for serial monitor
    
    Serial.println("\n\n");
    Serial.println("╔═════════════════════════════════════════════════════════════════╗");
    Serial.println("║     VL53L4CD Multi-Sensor Infiltrometer System                 ║");
    Serial.println("║     Optimized for 2-50cm Water Level Measurement               ║");
    Serial.println("╚═════════════════════════════════════════════════════════════════╝");
    Serial.println();
    
    initializeSystem();
    
    if (system_initialized) {
        Serial.println("\n✓ SYSTEM READY - Starting measurements...\n");
        printSystemStatus();
    } else {
        Serial.println("\n✗ SYSTEM INITIALIZATION FAILED");
        Serial.println("Please check connections and reset the device.\n");
    }
}

// ===== MAIN LOOP =====
void loop() {
    if (!system_initialized) {
        delay(1000);
        return;
    }
    
    uint32_t current_time = millis();
    
    // Read sensors at configured interval
    if (current_time - last_measurement_time >= MEASUREMENT_INTERVAL_MS) {
        last_measurement_time = current_time;
        measurement_count++;
        
        readAllSensors();
        
        // Print data every 20 measurements (adjust as needed)
        if (measurement_count % 20 == 0) {
            Serial.println("\n────────────────────────────────────────────────────────────────");
            Serial.printf("Measurement Cycle #%lu (Rate: %.1f Hz)\n", 
                         measurement_count, 1000.0 / MEASUREMENT_INTERVAL_MS);
            Serial.println("────────────────────────────────────────────────────────────────");
            
            for (uint8_t i = 0; i < NUM_SENSORS; i++) {
                if (sensors[i].initialized && sensors[i].current_data.valid) {
                    printSensorData(i);
                }
            }
            Serial.println("────────────────────────────────────────────────────────────────\n");
        }
    }
}

// ===== SYSTEM INITIALIZATION =====
void initializeSystem() {
    Serial.println("═══ SYSTEM INITIALIZATION ═══\n");
    
    // Initialize sensor states
    for (uint8_t i = 0; i < NUM_SENSORS; i++) {
        sensors[i].sensor = nullptr;
        sensors[i].initialized = false;
        sensors[i].ranging = false;
        sensors[i].i2c_address = SENSOR_I2C_ADDRESSES[i];
        sensors[i].buffer_index = 0;
        sensors[i].buffer_filled = false;
        memset(sensors[i].distance_buffer, 0, sizeof(sensors[i].distance_buffer));
    }
    
    // Initialize I2C
    Serial.printf("▸ Initializing I2C: SDA=%d, SCL=%d, Freq=%d kHz\n", 
                  I2C_SDA, I2C_SCL, I2C_FREQ / 1000);
    Wire.begin(I2C_SDA, I2C_SCL);
    Wire.setClock(I2C_FREQ);
    Wire.setTimeOut(1000);  // 1 second timeout
    delay(100);
    Serial.println("  ✓ I2C initialized\n");
    
    // Scan I2C bus before initialization
    if (DEBUG_I2C_SCAN) {
        Serial.println("▸ Scanning I2C bus (before initialization):");
        scanI2CBus();
        Serial.println();
    }
    
    // Configure all XSHUT pins
    Serial.printf("▸ Configuring %d XSHUT pins:\n", NUM_SENSORS);
    for (uint8_t i = 0; i < NUM_SENSORS; i++) {
        pinMode(XSHUT_PINS[i], OUTPUT);
        digitalWrite(XSHUT_PINS[i], LOW);  // Start with all sensors shut down
        Serial.printf("  GPIO %d → Sensor %d\n", XSHUT_PINS[i], i);
    }
    delay(100);
    Serial.println("  ✓ All XSHUT pins configured\n");
    
    // Initialize each sensor sequentially
    Serial.println("═══ SENSOR INITIALIZATION SEQUENCE ═══\n");
    
    uint8_t successful_init = 0;
    
    for (uint8_t i = 0; i < NUM_SENSORS; i++) {
        Serial.printf("┌─ Sensor %d [%s] ─────────────────────────\n", i, SENSOR_NAMES[i]);
        
        if (initializeSensor(i)) {
            successful_init++;
            Serial.printf("└─ ✓ Sensor %d initialized at address 0x%02X\n\n", 
                         i, sensors[i].i2c_address);
        } else {
            Serial.printf("└─ ✗ Sensor %d initialization FAILED\n\n", i);
        }
        
        delay(50);  // Small delay between sensor initializations
    }
    
    // Scan I2C bus after initialization
    if (DEBUG_I2C_SCAN) {
        Serial.println("▸ Scanning I2C bus (after initialization):");
        scanI2CBus();
        Serial.println();
    }
    
    // Summary
    Serial.println("═══ INITIALIZATION SUMMARY ═══");
    Serial.printf("Sensors initialized: %d / %d\n", successful_init, NUM_SENSORS);
    Serial.printf("Success rate: %.1f%%\n", (successful_init * 100.0) / NUM_SENSORS);
    
    system_initialized = (successful_init > 0);
    
    if (successful_init == NUM_SENSORS) {
        Serial.println("Status: ALL SENSORS OPERATIONAL ✓");
    } else if (successful_init > 0) {
        Serial.println("Status: PARTIAL SUCCESS (some sensors failed) ⚠");
    } else {
        Serial.println("Status: COMPLETE FAILURE ✗");
    }
}

// ===== INDIVIDUAL SENSOR INITIALIZATION =====
bool initializeSensor(uint8_t sensor_index) {
    if (sensor_index >= NUM_SENSORS) {
        return false;
    }
    
    // Step 1: Shutdown all sensors except this one
    if (DEBUG_INIT) printInitProgress(sensor_index, "Isolating sensor", true);
    shutdownAllSensors();
    startupSensor(sensor_index);
    delay(10);  // Wait for boot (VL53L4CD boot time ~1.2ms)
    
    // Step 2: Verify sensor at default address
    if (DEBUG_INIT) Serial.printf("│  Checking default address 0x%02X...\n", DEFAULT_I2C_ADDRESS);
    if (!verifyI2CDevice(DEFAULT_I2C_ADDRESS)) {
        if (DEBUG_INIT) printInitProgress(sensor_index, "Device detection", false);
        return false;
    }
    if (DEBUG_INIT) printInitProgress(sensor_index, "Device detected", true);
    
    // Step 3: Create sensor object
    sensors[sensor_index].sensor = new VL53L4CD(&Wire, -1);
    if (sensors[sensor_index].sensor == nullptr) {
        if (DEBUG_INIT) printInitProgress(sensor_index, "Memory allocation", false);
        return false;
    }
    
    // Step 4: Begin sensor communication
    if (DEBUG_INIT) Serial.printf("│  Initializing communication...\n");
    VL53L4CD_ERROR status = sensors[sensor_index].sensor->begin();
    if (status != VL53L4CD_ERROR_NONE) {
        if (DEBUG_INIT) printInitProgress(sensor_index, "Communication init", false);
        delete sensors[sensor_index].sensor;
        sensors[sensor_index].sensor = nullptr;
        return false;
    }
    
    // Step 5: Initialize sensor for ranging
    if (DEBUG_INIT) Serial.printf("│  Configuring sensor registers...\n");
    status = sensors[sensor_index].sensor->VL53L4CD_SensorInit();
    if (status != VL53L4CD_ERROR_NONE) {
        if (DEBUG_INIT) printInitProgress(sensor_index, "Sensor init", false);
        delete sensors[sensor_index].sensor;
        sensors[sensor_index].sensor = nullptr;
        return false;
    }
    if (DEBUG_INIT) printInitProgress(sensor_index, "Sensor configured", true);
    
    // Step 6: Configure for short-range, high-speed operation
    if (DEBUG_INIT) Serial.printf("│  Optimizing for short range...\n");
    configureSensorForShortRange(sensors[sensor_index].sensor);
    
    // Step 7: Change I2C address
    if (DEBUG_INIT) Serial.printf("│  Changing address: 0x%02X → 0x%02X...\n", 
                                  DEFAULT_I2C_ADDRESS, sensors[sensor_index].i2c_address);
    if (!changeSensorI2CAddress(sensors[sensor_index].sensor, sensors[sensor_index].i2c_address)) {
        if (DEBUG_INIT) printInitProgress(sensor_index, "Address change", false);
        delete sensors[sensor_index].sensor;
        sensors[sensor_index].sensor = nullptr;
        return false;
    }
    delay(10);
    
    // Step 8: Verify new address
    if (!verifyI2CDevice(sensors[sensor_index].i2c_address)) {
        if (DEBUG_INIT) printInitProgress(sensor_index, "Address verification", false);
        delete sensors[sensor_index].sensor;
        sensors[sensor_index].sensor = nullptr;
        return false;
    }
    if (DEBUG_INIT) printInitProgress(sensor_index, "Address changed", true);
    
    // Step 9: Start ranging
    if (DEBUG_INIT) Serial.printf("│  Starting continuous ranging...\n");
    status = sensors[sensor_index].sensor->VL53L4CD_StartRanging();
    if (status != VL53L4CD_ERROR_NONE) {
        if (DEBUG_INIT) printInitProgress(sensor_index, "Start ranging", false);
        sensors[sensor_index].initialized = true;  // Mark as initialized even if ranging fails
        sensors[sensor_index].ranging = false;
        return false;
    }
    
    if (DEBUG_INIT) printInitProgress(sensor_index, "Ranging started", true);
    
    sensors[sensor_index].initialized = true;
    sensors[sensor_index].ranging = true;
    
    return true;
}

// ===== CONFIGURE SENSOR FOR SHORT RANGE =====
void configureSensorForShortRange(VL53L4CD* sensor) {
    if (sensor == nullptr) return;
    
    // Set timing budget (measurement time per range)
    sensor->VL53L4CD_SetRangeTiming(TIMING_BUDGET_MS, INTER_MEASUREMENT_MS);
    
    // For 2-50cm range, we want:
    // - Fast measurements
    // - High accuracy
    // - Good signal strength
    // The default settings are already quite good for this range
}

// ===== I2C ADDRESS CHANGE =====
bool changeSensorI2CAddress(VL53L4CD* sensor, uint8_t new_address) {
    if (sensor == nullptr) {
        return false;
    }
    
    VL53L4CD_ERROR status = sensor->VL53L4CD_SetI2CAddress(new_address);
    return (status == VL53L4CD_ERROR_NONE);
}

// ===== XSHUT CONTROL =====
void shutdownAllSensors() {
    for (uint8_t i = 0; i < NUM_SENSORS; i++) {
        digitalWrite(XSHUT_PINS[i], LOW);
    }
}

void startupSensor(uint8_t sensor_index) {
    if (sensor_index < NUM_SENSORS) {
        digitalWrite(XSHUT_PINS[sensor_index], HIGH);
    }
}

// ===== I2C VERIFICATION =====
bool verifyI2CDevice(uint8_t address) {
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();
    return (error == 0);
}

void scanI2CBus() {
    uint8_t device_count = 0;
    Serial.println("  Scanning addresses 0x00 - 0x7F:");
    
    for (uint8_t addr = 0; addr < 128; addr++) {
        Wire.beginTransmission(addr);
        uint8_t error = Wire.endTransmission();
        
        if (error == 0) {
            Serial.printf("  ✓ Device found at 0x%02X\n", addr);
            device_count++;
        }
    }
    
    Serial.printf("  Total devices found: %d\n", device_count);
}

// ===== READ ALL SENSORS =====
void readAllSensors() {
    for (uint8_t i = 0; i < NUM_SENSORS; i++) {
        if (sensors[i].initialized && sensors[i].ranging) {
            readSensor(i);
        }
    }
}

// ===== READ INDIVIDUAL SENSOR =====
void readSensor(uint8_t sensor_index) {
    if (sensor_index >= NUM_SENSORS || sensors[sensor_index].sensor == nullptr) {
        return;
    }
    
    VL53L4CD_Result_t results;
    uint8_t data_ready = 0;
    
    // Check if new data is available
    VL53L4CD_ERROR status = sensors[sensor_index].sensor->VL53L4CD_CheckForDataReady(&data_ready);
    
    if (status != VL53L4CD_ERROR_NONE) {
        sensors[sensor_index].current_data.valid = false;
        return;
    }
    
    if (data_ready) {
        // Read measurement results
        status = sensors[sensor_index].sensor->VL53L4CD_GetResult(&results);
        
        if (status == VL53L4CD_ERROR_NONE) {
            // Update sensor data
            sensors[sensor_index].current_data.distance_mm = results.distance_mm;
            sensors[sensor_index].current_data.range_status = results.range_status;
            sensors[sensor_index].current_data.timestamp = millis();
            
            // Calculate signal and ambient per SPAD
            if (results.number_of_spad > 0) {
                sensors[sensor_index].current_data.signal_kcps = 
                    results.signal_per_spad_kcps / results.number_of_spad;
                sensors[sensor_index].current_data.ambient_kcps = 
                    results.ambient_per_spad_kcps / results.number_of_spad;
            } else {
                sensors[sensor_index].current_data.signal_kcps = 0;
                sensors[sensor_index].current_data.ambient_kcps = 0;
            }
            
            // Sigma is already in mm
            sensors[sensor_index].current_data.sigma_mm = results.sigma_mm / 65536;  // Convert from fixed point
            
            // Validate measurement
            bool range_valid = IS_VALID_RANGE(results.distance_mm);
            bool signal_valid = IS_VALID_SIGNAL(sensors[sensor_index].current_data.signal_kcps);
            bool status_valid = (results.range_status == 0);  // 0 = valid range
            
            sensors[sensor_index].current_data.valid = 
                ENABLE_DATA_VALIDATION ? (range_valid && signal_valid && status_valid) : true;
            
            // Update moving average
            if (ENABLE_DATA_AVERAGING && sensors[sensor_index].current_data.valid) {
                updateMovingAverage(sensor_index, results.distance_mm);
            }
            
            if (DEBUG_MEASUREMENTS) {
                Serial.printf("[%d] Dist:%4dmm Sig:%5lu Status:%d Valid:%d\n",
                             sensor_index,
                             results.distance_mm,
                             sensors[sensor_index].current_data.signal_kcps,
                             results.range_status,
                             sensors[sensor_index].current_data.valid);
            }
        } else {
            sensors[sensor_index].current_data.valid = false;
        }
        
        // Clear interrupt to allow next measurement
        sensors[sensor_index].sensor->VL53L4CD_ClearInterrupt();
    }
}

// ===== MOVING AVERAGE FILTER =====
void updateMovingAverage(uint8_t sensor_index, uint16_t new_distance) {
    sensors[sensor_index].distance_buffer[sensors[sensor_index].buffer_index] = new_distance;
    sensors[sensor_index].buffer_index = (sensors[sensor_index].buffer_index + 1) % AVERAGING_WINDOW;
    
    if (sensors[sensor_index].buffer_index == 0) {
        sensors[sensor_index].buffer_filled = true;
    }
}

uint16_t getAveragedDistance(uint8_t sensor_index) {
    if (!ENABLE_DATA_AVERAGING) {
        return sensors[sensor_index].current_data.distance_mm;
    }
    
    uint8_t count = sensors[sensor_index].buffer_filled ? AVERAGING_WINDOW : sensors[sensor_index].buffer_index;
    if (count == 0) return sensors[sensor_index].current_data.distance_mm;
    
    uint32_t sum = 0;
    for (uint8_t i = 0; i < count; i++) {
        sum += sensors[sensor_index].distance_buffer[i];
    }
    
    return sum / count;
}

// ===== PRINTING FUNCTIONS =====
void printSystemStatus() {
    Serial.println("\n┌─ SYSTEM STATUS ──────────────────────────────────────┐");
    Serial.printf("│ Active sensors: %d / %d\n", NUM_SENSORS, NUM_SENSORS);
    Serial.printf("│ Measurement rate: %.1f Hz (%d ms interval)\n", 
                  1000.0 / MEASUREMENT_INTERVAL_MS, MEASUREMENT_INTERVAL_MS);
    Serial.printf("│ Range: %d - %d mm\n", RANGE_MIN_MM, RANGE_MAX_MM);
    Serial.printf("│ Timing budget: %d ms\n", TIMING_BUDGET_MS);
    Serial.printf("│ Data validation: %s\n", ENABLE_DATA_VALIDATION ? "Enabled" : "Disabled");
    Serial.printf("│ Averaging: %s", ENABLE_DATA_AVERAGING ? "Enabled" : "Disabled");
    if (ENABLE_DATA_AVERAGING) {
        Serial.printf(" (window: %d)\n", AVERAGING_WINDOW);
    } else {
        Serial.println();
    }
    Serial.println("└──────────────────────────────────────────────────────┘");
}

void printSensorData(uint8_t sensor_index) {
    if (sensor_index >= NUM_SENSORS) return;
    
    uint16_t display_distance = ENABLE_DATA_AVERAGING ? 
        getAveragedDistance(sensor_index) : 
        sensors[sensor_index].current_data.distance_mm;
    
    Serial.printf("%s (0x%02X): %4d mm | Sig: %5lu kcps | Amb: %5lu kcps | Status: %d\n",
                  SENSOR_NAMES[sensor_index],
                  sensors[sensor_index].i2c_address,
                  display_distance,
                  sensors[sensor_index].current_data.signal_kcps,
                  sensors[sensor_index].current_data.ambient_kcps,
                  sensors[sensor_index].current_data.range_status);
}

void printInitProgress(uint8_t sensor_index, const char* step, bool success) {
    Serial.printf("│  %s... %s\n", step, success ? "✓" : "✗");
}
