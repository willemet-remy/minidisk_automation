#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_sleep.h>
#include <Wire.h>
#include "config.h"

#ifndef ROLE_RECEIVER
#include <vl53l4cd_class.h>
#endif

enum Command : uint8_t { COMMAND_NONE = 0, COMMAND_START = 1, COMMAND_PAUSE = 2 };

struct __attribute__((packed)) MeasurementPacket {
  uint32_t magic;
  uint8_t version;
  uint8_t node_id;
  char node_name[16];
  uint32_t sequence;
  uint32_t uptime_ms;
  uint16_t distance_mm;
  uint8_t range_status;
  uint16_t battery_mv;
  uint8_t flags; // bit 0 valid distance, bit 1 battery enabled, bit 2 measuring
};

struct __attribute__((packed)) ControlPacket {
  uint32_t magic;
  uint8_t version;
  uint8_t target_node_id; // 0 = all nodes
  uint8_t command;
};

static_assert(sizeof(MeasurementPacket) <= ESP_NOW_MAX_DATA_LEN, "Measurement packet is too large");

static void printMac(const uint8_t *mac) {
  Serial.printf("%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static bool startEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  if (esp_wifi_set_channel(ESPNOW_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE) != ESP_OK ||
      esp_now_init() != ESP_OK) return false;
  return true;
}

static bool addBroadcastPeer() {
  const uint8_t address[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, address, sizeof(peer.peer_addr));
  peer.channel = ESPNOW_WIFI_CHANNEL;
  return esp_now_add_peer(&peer) == ESP_OK || esp_now_is_peer_exist(address);
}

#ifdef ROLE_RECEIVER

static bool sendCommand(Command command) {
  ControlPacket packet = {COMMAND_MAGIC, PACKET_VERSION, 0, command};
  const uint8_t broadcast[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  return esp_now_send(broadcast, reinterpret_cast<const uint8_t *>(&packet), sizeof(packet)) == ESP_OK;
}

static void onDataReceived(const uint8_t *sourceMac, const uint8_t *data, int length) {
  if (length != sizeof(MeasurementPacket)) return;
  MeasurementPacket packet = {};
  memcpy(&packet, data, sizeof(packet));
  if (packet.magic != PACKET_MAGIC || packet.version != PACKET_VERSION) return;
  packet.node_name[sizeof(packet.node_name) - 1] = '\0';
  Serial.print("DATA,node="); Serial.print(packet.node_id);
  Serial.print(",name="); Serial.print(packet.node_name);
  Serial.print(",sequence="); Serial.print(packet.sequence);
  Serial.print(",uptime_ms="); Serial.print(packet.uptime_ms);
  Serial.print(",measuring="); Serial.print((packet.flags & 0x04) ? 1 : 0);
  Serial.print(",distance_mm="); if (packet.flags & 0x01) Serial.print(packet.distance_mm); else Serial.print("NA");
  Serial.print(",range_status="); Serial.print(packet.range_status);
  Serial.print(",battery_mv="); if (packet.flags & 0x02) Serial.print(packet.battery_mv); else Serial.print("NA");
  Serial.print(",source_mac="); printMac(sourceMac); Serial.println();
}

static void readComputerCommands() {
  if (!Serial.available()) return;
  String command = Serial.readStringUntil('\n');
  command.trim(); command.toUpperCase();
  Command radioCommand = COMMAND_NONE;
  if (command == "START") radioCommand = COMMAND_START;
  if (command == "PAUSE" || command == "END") radioCommand = COMMAND_PAUSE;
  if (radioCommand == COMMAND_NONE) { Serial.println("ERROR,unknown_command"); return; }
  Serial.printf("EVENT,command=%s,queued=%d\n", command.c_str(), sendCommand(radioCommand) ? 1 : 0);
}

void setup() {
  Serial.begin(115200); delay(500);
  if (!startEspNow() || !addBroadcastPeer()) { Serial.println("ERROR,espnow_initialization_failed"); return; }
  esp_now_register_recv_cb(onDataReceived);
  uint8_t mac[6]; WiFi.macAddress(mac);
  Serial.print("READY,receiver_mac="); printMac(mac); Serial.println();
}
void loop() { readComputerCommands(); delay(5); }

#else

RTC_DATA_ATTR static uint32_t sequence = 0;
RTC_DATA_ATTR static bool measuring = START_MEASURING_AFTER_FLASH;
static volatile Command pendingCommand = COMMAND_NONE;

static void onControlReceived(const uint8_t *, const uint8_t *data, int length) {
  if (length != sizeof(ControlPacket)) return;
  ControlPacket packet = {};
  memcpy(&packet, data, sizeof(packet));
  if (packet.magic == COMMAND_MAGIC && packet.version == PACKET_VERSION &&
      (packet.target_node_id == 0 || packet.target_node_id == NODE_ID) &&
      (packet.command == COMMAND_START || packet.command == COMMAND_PAUSE)) {
    pendingCommand = static_cast<Command>(packet.command);
  }
}

static uint16_t readBatteryMillivolts() {
#if BATTERY_MONITOR_ENABLED
  analogReadResolution(12);
  return static_cast<uint16_t>(analogReadMilliVolts(BATTERY_ADC_PIN) * BATTERY_DIVIDER_RATIO);
#else
  return 0;
#endif
}

static bool readDistance(MeasurementPacket &packet) {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN); Wire.setClock(I2C_CLOCK_HZ);
  VL53L4CD sensor(&Wire, VL53_XSHUT_PIN);
  sensor.begin(); sensor.VL53L4CD_On();
  if (sensor.VL53L4CD_SensorInit() != VL53L4CD_ERROR_NONE ||
      sensor.VL53L4CD_SetRangeTiming(VL53_TIMING_BUDGET_MS, 0) != VL53L4CD_ERROR_NONE ||
      sensor.VL53L4CD_StartRanging() != VL53L4CD_ERROR_NONE) { sensor.VL53L4CD_Off(); return false; }
  uint8_t ready = 0;
  const uint32_t deadline = millis() + VL53_TIMING_BUDGET_MS + 250;
  while (!ready && millis() < deadline) {
    if (sensor.VL53L4CD_CheckForDataReady(&ready) != VL53L4CD_ERROR_NONE) break;
    delay(5);
  }
  VL53L4CD_Result_t result = {};
  const bool ok = ready && sensor.VL53L4CD_GetResult(&result) == VL53L4CD_ERROR_NONE;
  if (ok) { packet.distance_mm = result.distance_mm; packet.range_status = result.range_status; if (result.range_status == 0) packet.flags |= 0x01; sensor.VL53L4CD_ClearInterrupt(); }
  sensor.VL53L4CD_StopRanging(); sensor.VL53L4CD_Off();
  return ok;
}

static void sleepUntilNextSample() {
  Serial.flush();
  esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(SAMPLE_INTERVAL_SECONDS) * 1000000ULL);
  esp_deep_sleep_start();
}

void setup() {
  Serial.begin(115200); delay(250);
  MeasurementPacket packet = {};
  packet.magic = PACKET_MAGIC; packet.version = PACKET_VERSION; packet.node_id = NODE_ID;
  strncpy(packet.node_name, NODE_NAME, sizeof(packet.node_name) - 1);
  packet.sequence = ++sequence; packet.uptime_ms = millis(); packet.range_status = 255;
  if (measuring) { packet.flags |= 0x04; readDistance(packet); }
#if BATTERY_MONITOR_ENABLED
  packet.flags |= 0x02; packet.battery_mv = readBatteryMillivolts();
#endif
  if (startEspNow() && addBroadcastPeer()) {
    esp_now_register_recv_cb(onControlReceived);
    const uint8_t broadcast[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    esp_now_send(broadcast, reinterpret_cast<const uint8_t *>(&packet), sizeof(packet));
    const uint32_t deadline = millis() + COMMAND_LISTEN_MS;
    while (millis() < deadline) delay(10);
  }
  if (pendingCommand == COMMAND_START) measuring = true;
  if (pendingCommand == COMMAND_PAUSE) measuring = false;
  if (SERIAL_DEBUG) Serial.printf("%s: %s\n", NODE_NAME, measuring ? "measuring" : "paused");
  sleepUntilNextSample();
}
void loop() {}

#endif
