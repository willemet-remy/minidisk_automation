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

// ─────────────────────────────────────────────────────────────────────────────
// RECEIVER IMPLEMENTATION (Tracks and Scans all Active Nodes)
// ─────────────────────────────────────────────────────────────────────────────

struct TrackedNode {
  uint8_t mac[6];
  uint8_t node_id;
  char node_name[16];
  uint32_t last_seen_ms;
  uint32_t packets_received;
  uint32_t last_sequence;
  uint16_t last_distance_mm;
  uint8_t last_range_status;
  uint16_t last_battery_mv;
  bool is_measuring;
  bool is_valid_distance;
  bool has_battery;
};

static constexpr size_t MAX_TRACKED_NODES = 20;
static TrackedNode trackedNodes[MAX_TRACKED_NODES];
static size_t trackedNodesCount = 0;

static bool sendCommand(Command command, uint8_t targetNodeId = 0) {
  ControlPacket packet = {COMMAND_MAGIC, PACKET_VERSION, targetNodeId, command};
  const uint8_t broadcast[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  return esp_now_send(broadcast, reinterpret_cast<const uint8_t *>(&packet), sizeof(packet)) == ESP_OK;
}

static void updateTrackedNode(const uint8_t *mac, const MeasurementPacket &packet) {
  int nodeIndex = -1;
  for (size_t i = 0; i < trackedNodesCount; ++i) {
    if (memcmp(trackedNodes[i].mac, mac, 6) == 0 || trackedNodes[i].node_id == packet.node_id) {
      nodeIndex = static_cast<int>(i);
      break;
    }
  }

  if (nodeIndex < 0 && trackedNodesCount < MAX_TRACKED_NODES) {
    nodeIndex = static_cast<int>(trackedNodesCount++);
  }

  if (nodeIndex >= 0) {
    TrackedNode &node = trackedNodes[nodeIndex];
    memcpy(node.mac, mac, 6);
    node.node_id = packet.node_id;
    strncpy(node.node_name, packet.node_name, sizeof(node.node_name) - 1);
    node.node_name[sizeof(node.node_name) - 1] = '\0';
    node.last_seen_ms = millis();
    node.packets_received++;
    node.last_sequence = packet.sequence;
    node.last_distance_mm = packet.distance_mm;
    node.last_range_status = packet.range_status;
    node.last_battery_mv = packet.battery_mv;
    node.is_valid_distance = (packet.flags & 0x01) != 0;
    node.has_battery = (packet.flags & 0x02) != 0;
    node.is_measuring = (packet.flags & 0x04) != 0;
  }
}

static void printScannedNodes() {
  const uint32_t now = millis();
  Serial.println("\n══════════════════════════════════════════════════════════════════════");
  Serial.printf(" DISCOVERED SENSORS / NODES SCAN REPORT (Total: %u)\n", static_cast<unsigned>(trackedNodesCount));
  Serial.println("══════════════════════════════════════════════════════════════════════");
  Serial.println(" ID | Sensor Name     | State     | Distance | Battery | Last Seen | Packets");
  Serial.println("----+-----------------+-----------+----------+---------+-----------+--------");

  for (size_t i = 0; i < trackedNodesCount; ++i) {
    const TrackedNode &node = trackedNodes[i];
    const uint32_t ageSec = (now - node.last_seen_ms) / 1000UL;
    const char *stateStr = node.is_measuring ? "MEASURING" : "STANDBY  ";

    char distStr[16];
    if (node.is_valid_distance) snprintf(distStr, sizeof(distStr), "%4u mm", node.last_distance_mm);
    else snprintf(distStr, sizeof(distStr), "   NA   ");

    char battStr[16];
    if (node.has_battery) snprintf(battStr, sizeof(battStr), "%4u mV", node.last_battery_mv);
    else snprintf(battStr, sizeof(battStr), "   NA   ");

    Serial.printf(" %02u | %-15s | %s | %s | %s | %4u s ago | %6u\n",
                  node.node_id, node.node_name, stateStr, distStr, battStr, ageSec, node.packets_received);

    // Machine-readable scan output for software integration
    Serial.printf("SCAN_NODE,node=%u,name=%s,measuring=%d,distance_mm=%u,battery_mv=%u,age_sec=%u,mac=",
                  node.node_id, node.node_name, node.is_measuring ? 1 : 0,
                  node.is_valid_distance ? node.last_distance_mm : 0,
                  node.has_battery ? node.last_battery_mv : 0, ageSec);
    printMac(node.mac);
    Serial.println();
  }
  Serial.println("══════════════════════════════════════════════════════════════════════\n");
}

static void onDataReceived(const uint8_t *sourceMac, const uint8_t *data, int length) {
  if (length != sizeof(MeasurementPacket)) return;
  MeasurementPacket packet = {};
  memcpy(&packet, data, sizeof(packet));
  if (packet.magic != PACKET_MAGIC || packet.version != PACKET_VERSION) return;
  packet.node_name[sizeof(packet.node_name) - 1] = '\0';

  updateTrackedNode(sourceMac, packet);

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

static void printReceiverHelp() {
  Serial.println("\n╔═════════════════════════════════════════════════════════════════╗");
  Serial.println("║                RECEIVER USB DEBUG COMMANDS                      ║");
  Serial.println("╠═════════════════════════════════════════════════════════════════╣");
  Serial.println("║  SCAN / NODES / LIST  : Print & upload all discovered sensors   ║");
  Serial.println("║  START [node_id]      : Broadcast/send START command to nodes   ║");
  Serial.println("║  PAUSE / STOP         : Broadcast/send PAUSE command to nodes   ║");
  Serial.println("║  STATUS               : Show receiver uptime and active nodes   ║");
  Serial.println("║  CLEAR                : Clear the tracked sensors list          ║");
  Serial.println("║  HELP / ?             : Display this command menu               ║");
  Serial.println("╚═════════════════════════════════════════════════════════════════╝\n");
}

static void processReceiverCommands() {
  if (!Serial.available()) return;
  String command = Serial.readStringUntil('\n');
  command.trim();
  if (command.length() == 0) return;

  String upper = command;
  upper.toUpperCase();

  if (upper == "HELP" || upper == "?") {
    printReceiverHelp();
    return;
  }

  if (upper == "SCAN" || upper == "NODES" || upper == "LIST" || upper == "SENSORS") {
    printScannedNodes();
    return;
  }

  if (upper == "STATUS") {
    uint8_t mac[6]; WiFi.macAddress(mac);
    Serial.printf("STATUS: Receiver Uptime=%lu ms | Channel=%d | Tracked Nodes=%u | MAC=",
                  millis(), ESPNOW_WIFI_CHANNEL, static_cast<unsigned>(trackedNodesCount));
    printMac(mac);
    Serial.println();
    return;
  }

  if (upper == "CLEAR") {
    trackedNodesCount = 0;
    Serial.println("STATUS: Tracked nodes list cleared.");
    return;
  }

  Command radioCommand = COMMAND_NONE;
  uint8_t targetNode = 0;

  if (upper.startsWith("START")) {
    radioCommand = COMMAND_START;
    if (upper.length() > 5) targetNode = static_cast<uint8_t>(upper.substring(5).toInt());
  } else if (upper.startsWith("PAUSE") || upper.startsWith("STOP") || upper.startsWith("END")) {
    radioCommand = COMMAND_PAUSE;
    if (upper.length() > 5) targetNode = static_cast<uint8_t>(upper.substring(5).toInt());
  }

  if (radioCommand != COMMAND_NONE) {
    const bool sent = sendCommand(radioCommand, targetNode);
    Serial.printf("EVENT,command=%s,target=%u,queued=%d\n",
                  radioCommand == COMMAND_START ? "START" : "PAUSE", targetNode, sent ? 1 : 0);
  } else {
    Serial.println("ERROR,unknown_command (Type HELP or ? for commands)");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n╔═════════════════════════════════════════════════════════════════╗");
  Serial.println("║            SLIMME MINIDISK - ESP-NOW RECEIVER                   ║");
  Serial.println("╚═════════════════════════════════════════════════════════════════╝");

  if (!startEspNow() || !addBroadcastPeer()) {
    Serial.println("ERROR,espnow_initialization_failed");
    return;
  }
  esp_now_register_recv_cb(onDataReceived);

  uint8_t mac[6];
  WiFi.macAddress(mac);
  Serial.print("READY,receiver_mac="); printMac(mac);
  Serial.printf(",channel=%d\n", ESPNOW_WIFI_CHANNEL);
  Serial.println("Type 'HELP' or 'SCAN' for USB cable debug commands.\n");
}

void loop() {
  processReceiverCommands();
  delay(5);
}

#else

// ─────────────────────────────────────────────────────────────────────────────
// SENSOR NODE IMPLEMENTATION (Sender with Cable Debug CLI & Button)
// ─────────────────────────────────────────────────────────────────────────────

static uint32_t sequence = 0;
static bool measuring = false; // Always start in Standby
static volatile Command pendingCommand = COMMAND_NONE;

static VL53L4CD *vl53Sensor = nullptr;
static bool vl53Initialized = false;

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

static void initMeasurementLed() {
#if MEASUREMENT_LED_ENABLED
  pinMode(MEASUREMENT_LED_PIN, OUTPUT);
  // Blink twice when ESP32 powers on
  for (int i = 0; i < 2; ++i) {
    digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? HIGH : LOW);
    delay(150);
    digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? LOW : HIGH);
    delay(150);
  }
  // Explicitly OFF in standby
  digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? LOW : HIGH);
#endif
}

static void updateMeasurementLed(bool isMeasuring) {
#if MEASUREMENT_LED_ENABLED
  if (isMeasuring) {
    // Slow blink when measuring (500ms ON / 500ms OFF)
    static uint32_t lastBlinkTime = 0;
    static bool ledState = false;
    const uint32_t now = millis();
    if (now - lastBlinkTime >= MEASUREMENT_LED_BLINK_INTERVAL_MS) {
      lastBlinkTime = now;
      ledState = !ledState;
      digitalWrite(MEASUREMENT_LED_PIN, (ledState == MEASUREMENT_LED_ACTIVE_HIGH) ? HIGH : LOW);
    }
  } else {
    // Explicitly OFF in standby
    digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? LOW : HIGH);
  }
#endif
}

static void initButton() {
#if BUTTON_ENABLED
  pinMode(BUTTON_PIN, INPUT_PULLUP);
#endif
}

static bool startSensor() {
  if (vl53Initialized) return true;
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(I2C_CLOCK_HZ);
  if (!vl53Sensor) {
    vl53Sensor = new VL53L4CD(&Wire, VL53_XSHUT_PIN);
  }
  vl53Sensor->begin();
  vl53Sensor->VL53L4CD_On();
  if (vl53Sensor->VL53L4CD_SensorInit() != VL53L4CD_ERROR_NONE) {
    Serial.println("[VL53] Error: SensorInit failed. Check I2C wiring (SDA/SCL) and XSHUT pin.");
    vl53Sensor->VL53L4CD_Off();
    return false;
  }
  vl53Sensor->VL53L4CD_SetRangeTiming(VL53_TIMING_BUDGET_MS, 0);
  if (vl53Sensor->VL53L4CD_StartRanging() != VL53L4CD_ERROR_NONE) {
    Serial.println("[VL53] Error: StartRanging failed.");
    vl53Sensor->VL53L4CD_Off();
    return false;
  }
  vl53Initialized = true;
  Serial.println("[VL53] Sensor initialized and ranging started successfully.");
  return true;
}

static void stopSensor() {
  if (vl53Initialized && vl53Sensor) {
    vl53Sensor->VL53L4CD_StopRanging();
    vl53Sensor->VL53L4CD_Off();
    vl53Initialized = false;
    Serial.println("[VL53] Sensor stopped and powered off.");
  }
}

static void setMeasuringState(bool active) {
  if (measuring == active) return;
  measuring = active;
  if (measuring) {
    Serial.println("\n[STATE] Measurement STARTED (LED blinking slowly)");
    startSensor();
  } else {
    Serial.println("\n[STATE] Measurement STOPPED (Standby mode, LED OFF)");
    stopSensor();
#if MEASUREMENT_LED_ENABLED
    digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? LOW : HIGH);
#endif
  }
}

static void handleButton() {
#if BUTTON_ENABLED
  static uint32_t pressStartTime = 0;
  static bool wasPressed = false;
  static bool holdTriggered = false;

  const bool isPressed = (digitalRead(BUTTON_PIN) == LOW);
  if (isPressed) {
    if (!wasPressed) {
      wasPressed = true;
      pressStartTime = millis();
      holdTriggered = false;
      Serial.println("[BUTTON] Pressed... hold for 2s to toggle measurement");
    } else if (!holdTriggered && (millis() - pressStartTime >= BUTTON_HOLD_TIME_MS)) {
      holdTriggered = true;
      Serial.println("[BUTTON] 2-second hold triggered!");
      setMeasuringState(!measuring);
#if MEASUREMENT_LED_ENABLED
      // Quick flash to confirm button hold action
      digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? HIGH : LOW);
      delay(120);
      digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? LOW : HIGH);
#endif
    }
  } else {
    wasPressed = false;
    holdTriggered = false;
  }
#endif
}

static void scanVl53I2cBus() {
  pinMode(VL53_XSHUT_PIN, OUTPUT);
  digitalWrite(VL53_XSHUT_PIN, HIGH);  // LPn/XSHUT is active low.
  delay(20);

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000UL);
  Serial.printf("\n[I2C] Scanning bus: SDA=GPIO%d SCL=GPIO%d XSHUT=GPIO%d\n",
                I2C_SDA_PIN, I2C_SCL_PIN, VL53_XSHUT_PIN);
  bool foundAnyDevice = false;
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  ✓ I2C device found at address: 0x%02X%s\n", address,
                    address == 0x29 ? " (VL53L4CD ToF Sensor Detected!)" : "");
      foundAnyDevice = true;
    }
  }
  if (!foundAnyDevice) {
    Serial.println("  ✗ No I2C devices found. Check 3.3V, GND, SDA, SCL, and pull-up resistors.");
  }
  Serial.println();
}

static bool readDistance(MeasurementPacket &packet) {
  if (!startSensor()) return false;
  uint8_t ready = 0;
  const uint32_t deadline = millis() + VL53_TIMING_BUDGET_MS + 250;
  while (!ready && millis() < deadline) {
    if (vl53Sensor->VL53L4CD_CheckForDataReady(&ready) != VL53L4CD_ERROR_NONE) {
      break;
    }
    delay(5);
  }
  VL53L4CD_Result_t result = {};
  if (ready && vl53Sensor->VL53L4CD_GetResult(&result) == VL53L4CD_ERROR_NONE) {
    packet.distance_mm = result.distance_mm;
    packet.range_status = result.range_status;
    if (result.range_status == 0) packet.flags |= 0x01;
    vl53Sensor->VL53L4CD_ClearInterrupt();
    if (SERIAL_DEBUG) {
      Serial.printf("[DISTANCE] distance=%u mm | status=%u (%s)\n",
                    result.distance_mm, result.range_status,
                    result.range_status == 0 ? "VALID" : "INVALID/OUT OF RANGE");
    }
    return true;
  }
  return false;
}

static void sendMeasurementSample() {
  MeasurementPacket packet = {};
  packet.magic = PACKET_MAGIC;
  packet.version = PACKET_VERSION;
  packet.node_id = NODE_ID;
  strncpy(packet.node_name, NODE_NAME, sizeof(packet.node_name) - 1);
  packet.sequence = ++sequence;
  packet.uptime_ms = millis();
  packet.range_status = 255;
  if (measuring) {
    packet.flags |= 0x04;
    readDistance(packet);
  }
#if BATTERY_MONITOR_ENABLED
  packet.flags |= 0x02;
  packet.battery_mv = readBatteryMillivolts();
#endif
  const uint8_t broadcast[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  esp_now_send(broadcast, reinterpret_cast<const uint8_t *>(&packet), sizeof(packet));
  if (SERIAL_DEBUG) {
    Serial.printf("[TX] Node=%s (ID=%u) | Seq=%u | Mode=%s | Dist=%u mm | Battery=%u mV\n",
                  NODE_NAME, NODE_ID, packet.sequence,
                  measuring ? "MEASURING" : "STANDBY",
                  (packet.flags & 0x01) ? packet.distance_mm : 0,
                  packet.battery_mv);
  }
}

static void printNodeHelp() {
  Serial.println("\n╔═════════════════════════════════════════════════════════════════╗");
  Serial.println("║              SENSOR NODE USB CABLE DEBUG COMMANDS               ║");
  Serial.println("╠═════════════════════════════════════════════════════════════════╣");
  Serial.println("║  STATUS / INFO  : Show live node state, mode, and battery       ║");
  Serial.println("║  START          : Start measurement locally                     ║");
  Serial.println("║  STOP / PAUSE   : Stop measurement (return to Standby)          ║");
  Serial.println("║  SCAN / I2C     : Run I2C bus scan to verify sensor at 0x29     ║");
  Serial.println("║  DISTANCE / READ: Read a single distance sample immediately     ║");
  Serial.println("║  LED            : Test measurement LED (3 blinks)               ║");
  Serial.println("║  PING           : Send an immediate ESP-NOW packet              ║");
  Serial.println("║  HELP / ?       : Display this command menu                     ║");
  Serial.println("╚═════════════════════════════════════════════════════════════════╝\n");
}

static void processNodeCableCommands() {
  if (!Serial.available()) return;
  String command = Serial.readStringUntil('\n');
  command.trim();
  if (command.length() == 0) return;

  String upper = command;
  upper.toUpperCase();

  if (upper == "HELP" || upper == "?") {
    printNodeHelp();
    return;
  }

  if (upper == "STATUS" || upper == "INFO") {
    uint8_t mac[6]; WiFi.macAddress(mac);
    Serial.printf("\n[NODE STATUS] Node ID=%u | Name=%s | Mode=%s\n",
                  NODE_ID, NODE_NAME, measuring ? "MEASURING (Active)" : "STANDBY");
    Serial.printf("  Uptime: %lu ms | Sequence: %u | Battery: %u mV\n",
                  millis(), sequence, readBatteryMillivolts());
    Serial.print("  MAC: "); printMac(mac); Serial.printf(" | Channel: %d\n", ESPNOW_WIFI_CHANNEL);
    Serial.printf("  Pins: SDA=GPIO%d, SCL=GPIO%d, XSHUT=GPIO%d, LED=GPIO%d, Button=GPIO%d\n\n",
                  I2C_SDA_PIN, I2C_SCL_PIN, VL53_XSHUT_PIN, MEASUREMENT_LED_PIN, BUTTON_PIN);
    return;
  }

  if (upper == "START") {
    setMeasuringState(true);
    return;
  }

  if (upper == "STOP" || upper == "PAUSE") {
    setMeasuringState(false);
    return;
  }

  if (upper == "SCAN" || upper == "I2C") {
    scanVl53I2cBus();
    return;
  }

  if (upper == "DISTANCE" || upper == "READ") {
    MeasurementPacket tempPacket = {};
    if (readDistance(tempPacket)) {
      Serial.printf("[READ] Valid Distance: %u mm (Range Status: %u)\n", tempPacket.distance_mm, tempPacket.range_status);
    } else {
      Serial.println("[READ] Sensor read failed or no target in range.");
    }
    return;
  }

  if (upper == "LED") {
    Serial.println("[LED] Testing indicator LED (3 blinks)...");
#if MEASUREMENT_LED_ENABLED
    for (int i = 0; i < 3; ++i) {
      digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? HIGH : LOW);
      delay(200);
      digitalWrite(MEASUREMENT_LED_PIN, MEASUREMENT_LED_ACTIVE_HIGH ? LOW : HIGH);
      delay(200);
    }
#endif
    Serial.println("[LED] Test complete.");
    return;
  }

  if (upper == "PING") {
    sendMeasurementSample();
    return;
  }

  Serial.println("ERROR,unknown_command (Type HELP or ? for commands)");
}

static void sleepUntilNextSample() {
  Serial.flush();
  esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(SAMPLE_INTERVAL_SECONDS) * 1000000ULL);
  esp_deep_sleep_start();
}

void setup() {
  Serial.begin(115200);
  const uint32_t serialDeadline = millis() + 1500;
  while (!Serial && millis() < serialDeadline) delay(10);
  delay(300);

  Serial.println("\n╔═════════════════════════════════════════════════════════════════════════╗");
  Serial.printf("║       SLIMME MINIDISK - SENSOR NODE SELF-DIAGNOSTIC (ID %02d)             ║\n", NODE_ID);
  Serial.println("╚═════════════════════════════════════════════════════════════════════════╝");

  Serial.printf("[SYSTEM] Node Name: %s | Node ID: %u | Firmware: v%d\n", NODE_NAME, NODE_ID, PACKET_VERSION);
  Serial.printf("[SYSTEM] ESP32 Chip Model: %s | Free Heap: %u bytes\n", ESP.getChipModel(), ESP.getFreeHeap());

  // 1. Initialize LED
  initMeasurementLed();
  Serial.printf("[HARDWARE] Measurement LED configured on GPIO %d (Blinked 2x on boot)\n", MEASUREMENT_LED_PIN);

  // 2. Initialize Button
  initButton();
#if BUTTON_ENABLED
  const int buttonRaw = digitalRead(BUTTON_PIN);
  Serial.printf("[HARDWARE] Button configured on GPIO %d (State: %s / Raw: %d)\n",
                BUTTON_PIN, buttonRaw == LOW ? "PRESSED" : "RELEASED (OK)", buttonRaw);
#endif

  // 3. I2C & Sensor Check
  Serial.printf("[I2C BUS] Pins: SDA=GPIO%d, SCL=GPIO%d, XSHUT=GPIO%d, Speed=%lu kHz\n",
                I2C_SDA_PIN, I2C_SCL_PIN, VL53_XSHUT_PIN, I2C_CLOCK_HZ / 1000UL);
  scanVl53I2cBus();

#if VL53_I2C_DIAGNOSTIC
  Serial.println("[DIAG] Continuous I2C diagnostic mode enabled.");
  return;
#endif

  // 4. Test Sensor Init
  Serial.print("[SENSOR] Testing VL53L4CD connection... ");
  if (startSensor()) {
    Serial.println("✓ SUCCESS: Sensor initialized and ranging active!");
    MeasurementPacket testPacket = {};
    if (readDistance(testPacket)) {
      Serial.printf("  ✓ Sample test reading: %u mm (Status: %u)\n", testPacket.distance_mm, testPacket.range_status);
    }
    stopSensor(); // Put back into Standby
  } else {
    Serial.println("✗ FAILED to initialize VL53L4CD sensor.");
    Serial.println("  --> Check: (1) 3.3V & GND power to sensor (2) SDA & SCL swapped? (3) XSHUT wiring (4) I2C pullups (4.7k-10k)");
  }

  // 5. ESP-NOW Initialization
  Serial.print("[WIRELESS] Initializing ESP-NOW radio... ");
  if (!startEspNow() || !addBroadcastPeer()) {
    Serial.println("✗ FAILED: ESP-NOW initialization failed!");
    return;
  }
  esp_now_register_recv_cb(onControlReceived);

  uint8_t mac[6];
  WiFi.macAddress(mac);
  Serial.print("✓ OK | MAC: "); printMac(mac);
  Serial.printf(" | Channel: %d\n", ESPNOW_WIFI_CHANNEL);

  // Send initial standby packet so receiver discovers this node immediately
  Serial.print("[WIRELESS] Broadcasting initial standby discovery packet... ");
  sendMeasurementSample();
  Serial.println("✓ Sent.");

  Serial.println("\n─────────────────────────────────────────────────────────────────────────");
  Serial.println(" [STATUS] Node is in STANDBY mode (LED OFF).");
  Serial.println("  • Hold button for 2 seconds to START measurement (LED will blink slowly).");
  Serial.println("  • Or type 'HELP' or '?' for interactive USB cable debug commands.");
  Serial.println("─────────────────────────────────────────────────────────────────────────\n");

#if USE_DEEP_SLEEP
  const uint32_t deadline = millis() + COMMAND_LISTEN_MS;
  while (millis() < deadline) delay(10);
  if (pendingCommand == COMMAND_START) measuring = true;
  if (pendingCommand == COMMAND_PAUSE) measuring = false;
  if (SERIAL_DEBUG) Serial.printf("%s: %s\n", NODE_NAME, measuring ? "measuring" : "paused");
  sleepUntilNextSample();
#endif
}

void loop() {
#if VL53_I2C_DIAGNOSTIC
  delay(2000);
  scanVl53I2cBus();
#elif !USE_DEEP_SLEEP
  processNodeCableCommands();
  handleButton();

  if (pendingCommand != COMMAND_NONE) {
    if (pendingCommand == COMMAND_START) setMeasuringState(true);
    if (pendingCommand == COMMAND_PAUSE) setMeasuringState(false);
    pendingCommand = COMMAND_NONE;
  }

  updateMeasurementLed(measuring);

  static uint32_t lastSampleTime = 0;
  const uint32_t now = millis();
  if (now - lastSampleTime >= SAMPLE_INTERVAL_MS) {
    lastSampleTime = now;
    sendMeasurementSample();
  }
  delay(10);
#endif
}

#endif
