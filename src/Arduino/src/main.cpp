#include <Arduino.h>

const int NUM_SENSORS = 6;
const int sensorAnalogPins[NUM_SENSORS] = {A1, A2, A3, A4, A5, A6};

unsigned long intervalMs = 5000; // in milliseconds
unsigned long lastMeasureMs = 0;
bool isRunning = false;
bool isPaused = false;

// Function to read sensor with internal averaging
float readSensor(int index) {
  long sum = 0;
  // Take 10 rapid readings
  for (int j = 0; j < 10; j++) {
    sum += analogRead(sensorAnalogPins[index]);
    delay(5); // 5ms delay per read -> 50ms total per sensor.
  }
  float avg = (sum / 10.0);
  float voltage = avg * (5.0 / 1023.0);
  return voltage;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for serial port to connect
  }
  Serial.println("READY");
}

void loop() {
  // 1. Check Serial for incoming commands
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    
    if (cmd == "START") {
      isRunning = true;
      isPaused = false;
      lastMeasureMs = millis(); // align the next measurement
      Serial.println("ACK_START");
    } else if (cmd == "PAUSE") {
      isPaused = true;
      Serial.println("ACK_PAUSE");
    } else if (cmd == "RESUME") {
      if (isRunning) {
        isPaused = false;
        lastMeasureMs = millis();
        Serial.println("ACK_RESUME");
      }
    } else if (cmd == "STOP") {
      isRunning = false;
      isPaused = false;
      Serial.println("ACK_STOP");
    }
  }

  // 2. Non-blocking measurement execution
  if (isRunning && !isPaused) {
    unsigned long currentMs = millis();
    
    if (currentMs - lastMeasureMs >= intervalMs) {
      lastMeasureMs = currentMs;

      // Output string format: DATA,timestamp_ms,raw0,p0,cm0,raw1,p1,cm1,...
      Serial.print("DATA,");
      Serial.print(currentMs);

      for (int i = 0; i < NUM_SENSORS; i++) {
        float raw = readSensor(i);
        // Formulas from the original sketch
        // float pressurekPa = (((raw-0.1*5.0)*(5.0-5.0))/(0.8*5.0)-5.0)* 6.89476;
        float pressurekPa = (((10.0 / 5.0) * raw) - 5.0) * 6.89476;
        float cmh2O = -pressurekPa * 10.19;

        Serial.print(",");
        Serial.print(raw, 3);
        Serial.print(",");
        Serial.print(pressurekPa, 3);
        Serial.print(",");
        Serial.print(cmh2O, 3);
      }
      Serial.println();
    }
  }
}
