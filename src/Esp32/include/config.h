#pragma once

/*
 * Slimme Minidisk — hardware & protocol configuration
 * ---------------------------------------------------
 * Shared by the sensor nodes and the USB receiver.
 *
 * Node identity: every node needs a UNIQUE NODE_ID. The easiest way is to flash
 * with a dedicated PlatformIO environment, which sets -DNODE_ID for you:
 *     pio run -e node1 -t upload      (MINIDISK_01)
 *     pio run -e node2 -t upload      (MINIDISK_02)  ...
 */

#include <Arduino.h>
#include <WiFi.h>

// ── Node identity ────────────────────────────────────────────────────────────
#ifndef NODE_ID
#define NODE_ID 1            // Default when flashing the generic "node" environment
#endif
// NODE_NAME defaults to "MINIDISK_<id>" (e.g. MINIDISK_01). Define it to override.

// ── Pins (ESP32-C3 node) ─────────────────────────────────────────────────────
#define I2C_SDA_PIN 8
#define I2C_SCL_PIN 9
#define VL53_XSHUT_PIN 6
#define I2C_CLOCK_HZ 400000UL

#define BUZZER_ENABLED true
#define BUZZER_PIN 1
#define BUZZER_ACTIVE_HIGH true
#define BUZZER_BEEP_DURATION_MS 150UL
#define BUZZER_BEEP_PAUSE_MS 100UL

#define BUTTON_ENABLED true
#define BUTTON_PIN 2                 // Push button between GPIO 2 and GND
#define BUTTON_HOLD_TIME_MS 2000UL   // Hold 2 s to START / STOP recording

// ── Measurement ──────────────────────────────────────────────────────────────
#define SAMPLE_INTERVAL_MS 1000UL    // One averaged sample is transmitted every second
#define VL53_TIMING_BUDGET_MS 50     // Each raw ranging takes 50 ms (≈ 20 readings averaged per sample)
#define VL53_ACCEPT_WARNING_STATUS true  // Accept range status 1/2 (sigma/signal warnings) — common on water
#define SENSOR_RETRY_MS 5000UL       // Retry sensor initialisation every 5 s if it is missing

// ── Radio (ESP-NOW) ──────────────────────────────────────────────────────────
#define ESPNOW_WIFI_CHANNEL 1        // Nodes and receiver MUST use the same channel
// Many ESP32-C3 "Mini/Super Mini" boards have a poor antenna layout and fail to
// transmit reliably at full power. 8.5 dBm is the well-known fix and still gives
// tens of metres of range. Try WIFI_POWER_19_5dBm on boards with a good antenna.
#define RADIO_TX_POWER WIFI_POWER_8_5dBm

// Print debug information on the USB serial port (harmless in the field).
#define SERIAL_DEBUG true

// ── Protocol identifiers (do not change unless you reflash every device) ────
static constexpr uint32_t PACKET_MAGIC = 0x4D444B31UL;   // "MDK1"
static constexpr uint8_t PACKET_VERSION = 2;
static constexpr uint32_t COMMAND_MAGIC = 0x4D444B43UL;  // "MDKC"
