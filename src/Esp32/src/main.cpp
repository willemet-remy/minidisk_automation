/*
 * Slimme Minidisk — ESP-NOW firmware (sensor node + USB receiver)
 * ================================================================
 *
 *  NODE      (default build)       : VL53L4CD distance sensor + button + buzzer.
 *  RECEIVER  (-DROLE_RECEIVER)     : USB dongle that relays node data to the PC app.
 *
 * Field workflow
 * --------------
 *  1. Power the node            -> 1 beep  (+ 1 long beep if the distance sensor is missing)
 *  2. Hold the button 2 s       -> 2 beeps, RECORDING starts (new run, time restarts at 0)
 *  3. Hold the button 2 s again -> 3 beeps, recording STOPS (node returns to standby)
 *  The PC app can also start/stop a node remotely.
 *
 * Data flow & robustness
 * ----------------------
 *  - The sensor ranges continuously (50 ms budget). All valid readings collected during
 *    one sample interval (1 s) are averaged into ONE sample -> smooth water-level signal.
 *  - Every second the node broadcasts a packet containing the newest sample AND the
 *    previous ones (HISTORY_LEN). If a packet is lost, the next one fills the gap.
 *    The receiver de-duplicates by sequence number, so the PC receives every sample once.
 *  - Sensor problems never block the radio: the node keeps transmitting (distance marked
 *    invalid) and re-initialises the sensor in the background.
 *
 * Receiver serial protocol (115200 baud, one line per message)
 * ------------------------------------------------------------
 *  Output  READY,mac=..,channel=..
 *          HB,uptime_ms=..,nodes=..                       (heartbeat every 2 s)
 *          DATA,node=..,name=..,run=..,seq=..,rec=0|1,rec_ms=..,distance_mm=..|NA,
 *               status=..,n=..,sensor=0|1,uptime_ms=..,mac=..
 *          NODE,... / LIST_END                            (answer to LIST)
 *          ACK,cmd=START|STOP,target=..                   (answer to START/STOP)
 *          # ...                                          (human readable, ignore)
 *  Input   LIST | STATUS | HELP | START <id|ALL> | STOP <id|ALL>
 */

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Wire.h>
#include "config.h"

#ifndef ROLE_RECEIVER
#include <vl53l4cd_class.h>
#endif

// ─────────────────────────────────────────────────────────────────────────────
// Shared protocol
// ─────────────────────────────────────────────────────────────────────────────
enum Command : uint8_t { COMMAND_NONE = 0, COMMAND_START = 1, COMMAND_STOP = 2 };

static constexpr uint8_t SAMPLE_FLAG_VALID = 0x01;
static constexpr uint8_t SAMPLE_FLAG_RECORDING = 0x02;
static constexpr uint8_t HISTORY_LEN = 5;

struct __attribute__((packed)) Sample {
  uint32_t seq;          // Increments every sample since boot (starts at 1)
  uint32_t rec_ms;       // Time since recording start (0 in standby)
  uint16_t distance_mm;  // Averaged distance
  uint8_t range_status;  // 0 = OK; otherwise last VL53 status (255 = sensor missing)
  uint8_t flags;         // SAMPLE_FLAG_*
  uint8_t n_avg;         // Number of raw readings averaged
};

struct __attribute__((packed)) NodePacket {
  uint32_t magic;
  uint8_t version;
  uint8_t node_id;
  char node_name[16];
  uint16_t run_id;       // Increments each time recording starts
  uint32_t uptime_ms;
  uint8_t sensor_ok;
  uint8_t count;         // Valid entries in samples[]
  Sample samples[HISTORY_LEN];  // samples[0] = newest
};

struct __attribute__((packed)) ControlPacket {
  uint32_t magic;
  uint8_t version;
  uint8_t target_node_id;  // 0 = all nodes
  uint8_t command;
};

static_assert(sizeof(NodePacket) <= ESP_NOW_MAX_DATA_LEN, "Node packet too large");

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static void printMac(const uint8_t *mac) {
  Serial.printf("%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void configureSerial() {
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT && ARDUINO_USB_MODE
  // Native USB: never block the firmware when no computer is reading the port
  // (battery-powered node in the field).
  Serial.setTxTimeoutMs(0);
#endif
}

static bool startRadio() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();  // Never try to join stored Wi-Fi networks (would hop channels)
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(ESPNOW_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);
  WiFi.setTxPower(RADIO_TX_POWER);

  if (esp_now_init() != ESP_OK) return false;

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST_MAC, 6);
  peer.channel = 0;  // current channel
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  const esp_err_t res = esp_now_add_peer(&peer);
  return res == ESP_OK || res == ESP_ERR_ESPNOW_EXIST;
}

static uint8_t currentChannel() {
  uint8_t primary = 0;
  wifi_second_chan_t second;
  esp_wifi_get_channel(&primary, &second);
  return primary;
}

// Non-blocking line reader for USB serial commands.
static bool readSerialLine(String &out) {
  static String buffer;
  while (Serial.available()) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c == '\n') {
      out = buffer;
      buffer = "";
      out.trim();
      return out.length() > 0;
    }
    if (buffer.length() < 64) buffer += c;
  }
  return false;
}

#ifdef ROLE_RECEIVER
// ═════════════════════════════════════════════════════════════════════════════
// RECEIVER
// ═════════════════════════════════════════════════════════════════════════════

struct RxItem {
  uint8_t mac[6];
  NodePacket packet;
};

struct TrackedNode {
  bool used;
  uint8_t node_id;
  char name[17];
  uint8_t mac[6];
  uint32_t last_seq;
  uint32_t last_uptime_ms;
  uint32_t last_seen_ms;
  uint32_t samples;
  uint32_t lost;
  uint16_t run_id;
  bool recording;
  bool sensor_ok;
  bool valid;
  uint16_t distance_mm;
};

static constexpr size_t MAX_NODES = 20;
static TrackedNode nodes[MAX_NODES];
static QueueHandle_t rxQueue = nullptr;
static volatile uint32_t rxDropped = 0;

// Runs in the Wi-Fi task: copy and return immediately (no Serial here!).
static void onDataReceived(const uint8_t *mac, const uint8_t *data, int len) {
  if (len != static_cast<int>(sizeof(NodePacket)) || rxQueue == nullptr) return;
  RxItem item;
  memcpy(item.mac, mac, 6);
  memcpy(&item.packet, data, sizeof(NodePacket));
  if (item.packet.magic != PACKET_MAGIC || item.packet.version != PACKET_VERSION) return;
  if (xQueueSend(rxQueue, &item, 0) != pdTRUE) rxDropped++;
}

static TrackedNode *findOrCreateNode(uint8_t nodeId) {
  TrackedNode *freeSlot = nullptr;
  for (auto &n : nodes) {
    if (n.used && n.node_id == nodeId) return &n;
    if (!n.used && freeSlot == nullptr) freeSlot = &n;
  }
  if (freeSlot) {
    memset(freeSlot, 0, sizeof(TrackedNode));
    freeSlot->used = true;
    freeSlot->node_id = nodeId;
  }
  return freeSlot;
}

static size_t nodeCount() {
  size_t c = 0;
  for (auto &n : nodes) c += n.used ? 1 : 0;
  return c;
}

static void emitSample(const TrackedNode &node, const NodePacket &p, const Sample &s) {
  const bool valid = s.flags & SAMPLE_FLAG_VALID;
  Serial.printf("DATA,node=%u,name=%s,run=%u,seq=%lu,rec=%d,rec_ms=%lu,distance_mm=",
                node.node_id, node.name, p.run_id, static_cast<unsigned long>(s.seq),
                (s.flags & SAMPLE_FLAG_RECORDING) ? 1 : 0, static_cast<unsigned long>(s.rec_ms));
  if (valid) Serial.print(s.distance_mm); else Serial.print("NA");
  Serial.printf(",status=%u,n=%u,sensor=%u,uptime_ms=%lu,mac=", s.range_status, s.n_avg,
                p.sensor_ok, static_cast<unsigned long>(p.uptime_ms));
  printMac(node.mac);
  Serial.println();
}

static void handlePacket(const RxItem &item) {
  const NodePacket &p = item.packet;
  TrackedNode *node = findOrCreateNode(p.node_id);
  if (!node || p.count == 0 || p.count > HISTORY_LEN) return;

  memcpy(node->mac, item.mac, 6);
  memcpy(node->name, p.node_name, 16);
  node->name[16] = '\0';
  for (char *c = node->name; *c; ++c) if (*c == ',' || *c == '=') *c = '_';

  // Node rebooted? (uptime went backwards or sequence restarted)
  if (p.uptime_ms + 2000 < node->last_uptime_ms || p.samples[0].seq + HISTORY_LEN < node->last_seq) {
    Serial.printf("# node %u rebooted\n", p.node_id);
    node->last_seq = 0;
  }
  node->last_uptime_ms = p.uptime_ms;
  node->last_seen_ms = millis();
  node->run_id = p.run_id;
  node->sensor_ok = p.sensor_ok;

  // Emit samples oldest -> newest, skipping the ones already forwarded.
  for (int i = p.count - 1; i >= 0; --i) {
    const Sample &s = p.samples[i];
    if (s.seq <= node->last_seq) continue;
    if (node->last_seq != 0 && s.seq > node->last_seq + 1) node->lost += s.seq - node->last_seq - 1;
    emitSample(*node, p, s);
    node->last_seq = s.seq;
    node->samples++;
    node->recording = s.flags & SAMPLE_FLAG_RECORDING;
    node->valid = s.flags & SAMPLE_FLAG_VALID;
    node->distance_mm = s.distance_mm;
  }
}

static void sendCommand(Command cmd, uint8_t target) {
  const ControlPacket packet = {COMMAND_MAGIC, PACKET_VERSION, target, cmd};
  // Broadcast has no ACK: repeat a few times (commands are idempotent on the node).
  for (int i = 0; i < 3; ++i) {
    esp_now_send(BROADCAST_MAC, reinterpret_cast<const uint8_t *>(&packet), sizeof(packet));
    delay(15);
  }
}

static void printList() {
  const uint32_t now = millis();
  for (auto &n : nodes) {
    if (!n.used) continue;
    Serial.printf("NODE,node=%u,name=%s,run=%u,rec=%d,distance_mm=", n.node_id, n.name, n.run_id,
                  n.recording ? 1 : 0);
    if (n.valid) Serial.print(n.distance_mm); else Serial.print("NA");
    Serial.printf(",sensor=%u,age_ms=%lu,samples=%lu,lost=%lu,mac=", n.sensor_ok ? 1 : 0,
                  static_cast<unsigned long>(now - n.last_seen_ms), static_cast<unsigned long>(n.samples),
                  static_cast<unsigned long>(n.lost));
    printMac(n.mac);
    Serial.println();
  }
  Serial.println("LIST_END");
}

static void printStatus() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  Serial.printf("STATUS,uptime_ms=%lu,channel=%u,nodes=%u,rx_dropped=%lu,mac=", millis(), currentChannel(),
                static_cast<unsigned>(nodeCount()), static_cast<unsigned long>(rxDropped));
  printMac(mac);
  Serial.println();
}

static void printHelp() {
  Serial.println("# Commands: LIST | STATUS | START <id|ALL> | STOP <id|ALL> | HELP");
}

static void processCommands() {
  String line;
  if (!readSerialLine(line)) return;
  line.toUpperCase();

  if (line == "LIST" || line == "SCAN" || line == "NODES") { printList(); return; }
  if (line == "STATUS") { printStatus(); return; }
  if (line == "HELP" || line == "?") { printHelp(); return; }

  Command cmd = COMMAND_NONE;
  String arg;
  if (line.startsWith("START")) { cmd = COMMAND_START; arg = line.substring(5); }
  else if (line.startsWith("STOP")) { cmd = COMMAND_STOP; arg = line.substring(4); }
  else if (line.startsWith("PAUSE")) { cmd = COMMAND_STOP; arg = line.substring(5); }

  if (cmd == COMMAND_NONE) { Serial.println("ERROR,unknown_command"); return; }
  arg.trim();
  if (arg.length() == 0) { Serial.println("ERROR,missing_target (use START <id> or START ALL)"); return; }
  const uint8_t target = (arg == "ALL") ? 0 : static_cast<uint8_t>(arg.toInt());
  if (arg != "ALL" && target == 0) { Serial.println("ERROR,bad_target"); return; }

  sendCommand(cmd, target);
  Serial.printf("ACK,cmd=%s,target=%u\n", cmd == COMMAND_START ? "START" : "STOP", target);
}

void setup() {
  configureSerial();
  delay(300);
  rxQueue = xQueueCreate(32, sizeof(RxItem));

  Serial.println("# Slimme Minidisk receiver");
  if (!startRadio()) {
    Serial.println("ERROR,radio_init_failed");
    return;
  }
  esp_now_register_recv_cb(onDataReceived);

  uint8_t mac[6];
  WiFi.macAddress(mac);
  Serial.print("READY,mac=");
  printMac(mac);
  Serial.printf(",channel=%u\n", currentChannel());
  printHelp();
}

void loop() {
  RxItem item;
  while (rxQueue && xQueueReceive(rxQueue, &item, 0) == pdTRUE) handlePacket(item);

  processCommands();

  static uint32_t lastHeartbeat = 0;
  if (millis() - lastHeartbeat >= 2000) {
    lastHeartbeat = millis();
    Serial.printf("HB,uptime_ms=%lu,nodes=%u\n", lastHeartbeat, static_cast<unsigned>(nodeCount()));
  }
  delay(2);
}

#else
// ═════════════════════════════════════════════════════════════════════════════
// SENSOR NODE
// ═════════════════════════════════════════════════════════════════════════════

static char nodeName[16];

// Recording state
static bool recording = false;
static uint16_t runId = 0;
static uint32_t recStartMs = 0;
static volatile Command pendingCommand = COMMAND_NONE;

// Sampling state
static uint32_t sequence = 0;
static Sample history[HISTORY_LEN];
static uint8_t historyCount = 0;
static uint32_t lastSampleMs = 0;
static uint32_t accSum = 0;
static uint16_t accCount = 0;
static uint16_t lastRawDistance = 0;
static uint8_t lastRawStatus = 255;

// Sensor state
static VL53L4CD *sensor = nullptr;
static bool sensorOk = false;
static uint32_t lastSensorAttemptMs = 0;
static uint16_t sensorErrors = 0;

// ── Buzzer ──────────────────────────────────────────────────────────────────
static void buzzerWrite(bool on) {
#if BUZZER_ENABLED
  digitalWrite(BUZZER_PIN, (on == BUZZER_ACTIVE_HIGH) ? HIGH : LOW);
#endif
}

static void beep(int times, uint32_t onMs = BUZZER_BEEP_DURATION_MS, uint32_t offMs = BUZZER_BEEP_PAUSE_MS) {
#if BUZZER_ENABLED
  for (int i = 0; i < times; ++i) {
    buzzerWrite(true);
    delay(onMs);
    buzzerWrite(false);
    if (i < times - 1) delay(offMs);
  }
#endif
}

// ── Distance sensor ─────────────────────────────────────────────────────────
static bool sensorPresentOnBus() {
  Wire.beginTransmission(0x29);
  return Wire.endTransmission() == 0;
}

static bool initSensor() {
  lastSensorAttemptMs = millis();
  if (!sensor) sensor = new VL53L4CD(&Wire, VL53_XSHUT_PIN);
  sensor->begin();          // XSHUT low -> hardware reset
  delay(5);
  sensor->VL53L4CD_On();    // XSHUT high (+10 ms boot delay inside the library)
  delay(5);
  if (!sensorPresentOnBus()) {
    if (SERIAL_DEBUG) Serial.println("# [sensor] no device at 0x29 (check wiring)");
    return false;
  }
  if (sensor->VL53L4CD_SensorInit() != VL53L4CD_ERROR_NONE ||
      sensor->VL53L4CD_SetRangeTiming(VL53_TIMING_BUDGET_MS, 0) != VL53L4CD_ERROR_NONE ||
      sensor->VL53L4CD_StartRanging() != VL53L4CD_ERROR_NONE) {
    if (SERIAL_DEBUG) Serial.println("# [sensor] initialisation failed");
    return false;
  }
  sensorErrors = 0;
  if (SERIAL_DEBUG) Serial.println("# [sensor] VL53L4CD ranging");
  return true;
}

static bool statusAccepted(uint8_t status) {
  if (status == 0) return true;
  return VL53_ACCEPT_WARNING_STATUS && (status == 1 || status == 2);
}

// Called continuously from loop(): never waits for the sensor.
static void pollSensor() {
  if (!sensorOk) {
    if (millis() - lastSensorAttemptMs >= SENSOR_RETRY_MS) sensorOk = initSensor();
    return;
  }
  static uint32_t lastPoll = 0;
  if (millis() - lastPoll < 5) return;
  lastPoll = millis();

  uint8_t ready = 0;
  if (sensor->VL53L4CD_CheckForDataReady(&ready) != VL53L4CD_ERROR_NONE) {
    if (++sensorErrors > 50) {
      if (SERIAL_DEBUG) Serial.println("# [sensor] too many I2C errors, re-initialising");
      sensorOk = false;
    }
    return;
  }
  if (!ready) return;

  VL53L4CD_Result_t result = {};
  if (sensor->VL53L4CD_GetResult(&result) == VL53L4CD_ERROR_NONE) {
    sensorErrors = 0;
    lastRawStatus = result.range_status;
    lastRawDistance = result.distance_mm;
    if (statusAccepted(result.range_status) && result.distance_mm > 0) {
      accSum += result.distance_mm;
      accCount++;
    }
  }
  sensor->VL53L4CD_ClearInterrupt();
}

// ── Sampling & radio ────────────────────────────────────────────────────────
static void sendPacket() {
  NodePacket p = {};
  p.magic = PACKET_MAGIC;
  p.version = PACKET_VERSION;
  p.node_id = NODE_ID;
  strncpy(p.node_name, nodeName, sizeof(p.node_name) - 1);
  p.run_id = runId;
  p.uptime_ms = millis();
  p.sensor_ok = sensorOk ? 1 : 0;
  p.count = historyCount;
  memcpy(p.samples, history, sizeof(Sample) * historyCount);
  esp_now_send(BROADCAST_MAC, reinterpret_cast<const uint8_t *>(&p), sizeof(p));
}

static void takeSample() {
  Sample s = {};
  s.seq = ++sequence;
  s.rec_ms = recording ? millis() - recStartMs : 0;
  if (accCount > 0) {
    s.distance_mm = static_cast<uint16_t>((accSum + accCount / 2) / accCount);
    s.flags |= SAMPLE_FLAG_VALID;
    s.range_status = 0;
  } else {
    s.distance_mm = lastRawDistance;
    s.range_status = sensorOk ? lastRawStatus : 255;
  }
  s.n_avg = static_cast<uint8_t>(min<uint16_t>(accCount, 255));
  if (recording) s.flags |= SAMPLE_FLAG_RECORDING;
  accSum = 0;
  accCount = 0;

  // Shift history (newest first)
  memmove(&history[1], &history[0], sizeof(Sample) * (HISTORY_LEN - 1));
  history[0] = s;
  if (historyCount < HISTORY_LEN) historyCount++;

  sendPacket();

  if (SERIAL_DEBUG) {
    Serial.printf("# [tx] seq=%lu %s t=%.1fs dist=", static_cast<unsigned long>(s.seq),
                  recording ? "REC" : "standby", s.rec_ms / 1000.0f);
    if (s.flags & SAMPLE_FLAG_VALID) Serial.printf("%u mm (n=%u)\n", s.distance_mm, s.n_avg);
    else Serial.printf("NA (status=%u)\n", s.range_status);
  }
}

static void setRecording(bool on, const char *source) {
  if (recording == on) return;
  if (on) {
    beep(2);
    runId++;
    recording = true;
    recStartMs = millis();
    accSum = 0;
    accCount = 0;
  } else {
    recording = false;
    beep(3);
  }
  if (SERIAL_DEBUG) Serial.printf("# [state] %s run %u (%s)\n", on ? "START" : "STOP", runId, source);
  lastSampleMs = millis();
  takeSample();  // Inform the receiver immediately
}

// ── Remote commands (ESP-NOW) ───────────────────────────────────────────────
static void onControlReceived(const uint8_t *, const uint8_t *data, int len) {
  if (len != static_cast<int>(sizeof(ControlPacket))) return;
  ControlPacket c;
  memcpy(&c, data, sizeof(c));
  if (c.magic != COMMAND_MAGIC || c.version != PACKET_VERSION) return;
  if (c.target_node_id != 0 && c.target_node_id != NODE_ID) return;
  if (c.command == COMMAND_START || c.command == COMMAND_STOP) pendingCommand = static_cast<Command>(c.command);
}

// ── Button (hold 2 s to toggle) ─────────────────────────────────────────────
static void handleButton() {
#if BUTTON_ENABLED
  static uint32_t pressStart = 0;
  static bool pressed = false;
  static bool fired = false;
  const bool down = digitalRead(BUTTON_PIN) == LOW;
  if (down && !pressed) {
    pressed = true;
    fired = false;
    pressStart = millis();
  } else if (down && !fired && millis() - pressStart >= BUTTON_HOLD_TIME_MS) {
    fired = true;
    setRecording(!recording, "button");
  } else if (!down) {
    pressed = false;
  }
#endif
}

// ── USB debug commands ──────────────────────────────────────────────────────
static void processUsbCommands() {
  String line;
  if (!readSerialLine(line)) return;
  line.toUpperCase();
  if (line == "START") setRecording(true, "usb");
  else if (line == "STOP" || line == "PAUSE") setRecording(false, "usb");
  else if (line == "BEEP") beep(1);
  else if (line == "STATUS") {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    Serial.printf("# %s id=%u %s run=%u sensor=%s ch=%u seq=%lu last_raw=%u mm status=%u mac=", nodeName,
                  NODE_ID, recording ? "RECORDING" : "STANDBY", runId, sensorOk ? "OK" : "MISSING",
                  currentChannel(), static_cast<unsigned long>(sequence), lastRawDistance, lastRawStatus);
    printMac(mac);
    Serial.println();
  } else Serial.println("# Commands: STATUS | START | STOP | BEEP");
}

void setup() {
  configureSerial();
#ifdef NODE_NAME
  strncpy(nodeName, NODE_NAME, sizeof(nodeName) - 1);
#else
  snprintf(nodeName, sizeof(nodeName), "MINIDISK_%02u", static_cast<unsigned>(NODE_ID));
#endif

#if BUZZER_ENABLED
  pinMode(BUZZER_PIN, OUTPUT);
  buzzerWrite(false);
#endif
#if BUTTON_ENABLED
  pinMode(BUTTON_PIN, INPUT_PULLUP);
#endif
  beep(1, 200);  // Power-on

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(I2C_CLOCK_HZ);
  Wire.setTimeOut(20);  // Never hang on a stuck I2C bus
  sensorOk = initSensor();
  if (!sensorOk) {
    delay(150);
    beep(1, 800);  // Long beep = distance sensor not detected (keeps retrying)
  }

  if (!startRadio()) {
    Serial.println("# [radio] ESP-NOW init failed");
  }
  esp_now_register_recv_cb(onControlReceived);

  if (SERIAL_DEBUG) {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    Serial.printf("# %s (id %u) ready on channel %u, sensor %s, mac ", nodeName, NODE_ID, currentChannel(),
                  sensorOk ? "OK" : "MISSING");
    printMac(mac);
    Serial.println("\n# Hold the button 2 s to start/stop recording.");
  }
  lastSampleMs = millis();
}

void loop() {
  pollSensor();
  handleButton();
  processUsbCommands();

  if (pendingCommand != COMMAND_NONE) {
    const Command c = pendingCommand;
    pendingCommand = COMMAND_NONE;
    setRecording(c == COMMAND_START, "remote");
  }

  if (millis() - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs += SAMPLE_INTERVAL_MS;
    if (millis() - lastSampleMs > SAMPLE_INTERVAL_MS) lastSampleMs = millis();  // catch up after beeps
    takeSample();
  }
  delay(1);
}

#endif
