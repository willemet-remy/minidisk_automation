#pragma once

/*
 * Hardware configuration for one battery-powered VL53L4CD node.
 *
 * All I2C wires must stay inside the node enclosure (ideally < 20 cm).
 * The wireless link replaces the long I2C cable.
 */

#include <Arduino.h>

// Give every physical node a different number: 1, 2, 3, ...
#define NODE_ID 1
#define NODE_NAME "MINIDISK_01"  // Fixed identity: change only when commissioning a new node.

// ESP32-S3 DevKitC-1 defaults. Change these for another ESP32 Mini board.
#define I2C_SDA_PIN 8
#define I2C_SCL_PIN 9
#define VL53_XSHUT_PIN 6
#define I2C_CLOCK_HZ 400000UL

// Sampling interval. Deep sleep is used after each transmitted sample.
#define SAMPLE_INTERVAL_SECONDS 15UL
#define VL53_TIMING_BUDGET_MS 50
#define COMMAND_LISTEN_MS 700UL  // Node stays awake briefly after every status packet.
#define START_MEASURING_AFTER_FLASH false

// The ST library uses the VL53L4CD's 8-bit I2C address (0x52 = 0x29 7-bit).
#define VL53_DEFAULT_ADDRESS_8BIT 0x52

// ESP-NOW radio channel. All nodes and receiver must use this same channel.
#define ESPNOW_WIFI_CHANNEL 1

// Leave true for first tests. Set false for field deployment to reduce power use.
#define SERIAL_DEBUG true

// Battery measurement is optional. Set false when no voltage divider is fitted.
#define BATTERY_MONITOR_ENABLED false
#define BATTERY_ADC_PIN 4
// V_battery = V_adc * BATTERY_DIVIDER_RATIO. Example 100k/100k divider => 2.0.
#define BATTERY_DIVIDER_RATIO 2.0f

// Broadcast works immediately with a receiver on the same channel. It has no ACK.
// For acknowledged unicast, set USE_BROADCAST to false and enter receiver's STA MAC.
#define USE_BROADCAST true
static const uint8_t RECEIVER_MAC[6] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

// Packet identifier. Receiver discards other ESP-NOW traffic.
static constexpr uint32_t PACKET_MAGIC = 0x4D444B31UL;  // "MDK1"
static constexpr uint8_t PACKET_VERSION = 1;
static constexpr uint32_t COMMAND_MAGIC = 0x4D444B43UL; // "MDKC"
