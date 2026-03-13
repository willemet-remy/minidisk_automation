const int sensorAnalogPins[6] = {A1, A2, A3, A4, A5, A6}; // Analog pins for Vread
String sensorLabels[6] = {"S1", "S2", "S3", "S4", "S5", "S6"};  // Labels for CSV

String plotName;
unsigned long startMillis;
unsigned long intervalMs = 5000; // in milliseconds every 15sec
String hinput; // in cm H20
unsigned long timeMeasure = 60000*30;  // in milliseconds every 5mins
unsigned long elapsed = 0;

bool measurementRunning = false;

// Forward declarations
String readLine();
void showMenu();
void startMeasurementSession();

void setup() {
  Serial.begin(9600);
  startMeasurementSession();
}

void startMeasurementSession() {
  showMenu();

  startMillis = millis();
  Serial.println("time_ms,plot,tension,sensor_id,pressure_kPa,cmH20,raw_V");  // CSV header
  measurementRunning = true;
}

float readsensor(int i) {
  float value = 0;
  for (int j = 0; j <= 9; j++) { // take 10 readings and calculate mean value
  value +=  analogRead(sensorAnalogPins[i]);
  delay(100);
  }
  value = (value/10.0)* (5.0/1023.0); // To have a voltage and mean
  return (value);
}

void loop() {

  if (measurementRunning) {
    delay(1000);  // Sensor warm-up

    for (int i = 0; i < 6; i++) {
      float raw = readsensor(i);                                                                      

      //float pressurekPa = (((raw-0.1*5.0)*(5.0-5.0))/(0.8*5.0)-5.0)* 6.89476;
      float pressurekPa = (((10.0/5)*raw) -5) * 6.89476;
      //float pressurekPa = ((raw - 0.5) * (10.0 / 4.0)) * 6.89476;
      float cmh2O = -pressurekPa *10.19;
      elapsed = millis() - startMillis;

      Serial.print(elapsed);
      Serial.print(",");
      Serial.print(plotName);
      Serial.print(",");
      Serial.print(hinput);
      Serial.print(",");
      Serial.print(hinput);
      Serial.print(sensorLabels[i]);
      Serial.print(",");
      Serial.print(pressurekPa, DEC);
      Serial.print(",");
      Serial.print(cmh2O, DEC);
      Serial.print(",");
      Serial.println(raw, DEC);
         }


    delay(intervalMs);

    if (elapsed > timeMeasure) {
      Serial.println("Measurement completed.");
      measurementRunning = false;
    }
  } else {
    // Not measuring: wait a bit, then restart measurement session (go back to menu)
    delay(1000);
    startMeasurementSession();
  }
}

void showMenu() {
  Serial.println("==== Slim Minidisk Logger Setup ====");
  // Enter plot name
  Serial.print("Enter plot name: ");
  plotName = readLine();
  plotName.trim(); // to remove the withe space
  Serial.println(plotName);
  Serial.print("Enter tension applied: ");
  hinput = readLine();
  Serial.println(hinput);
  hinput.trim();
}

String readLine() {
  while (Serial.available() == 0) {
    delay(10);
  }
  return Serial.readStringUntil('\n');
}
