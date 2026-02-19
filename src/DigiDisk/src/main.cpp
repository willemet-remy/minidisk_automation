#define SHUTDOWN_PIN 2
#include <Wire.h>
#include <Arduino.h>
#include "SparkFun_VL53L1X.h"

SFEVL53L1X distanceSensor;

void setup(void)
{
  Serial.begin(115200);
  while (!Serial);

  Wire.begin();
  pinMode(SHUTDOWN_PIN, OUTPUT);

  // Reset sensor
  digitalWrite(SHUTDOWN_PIN, LOW);
  delay(10);
  digitalWrite(SHUTDOWN_PIN, HIGH);
  delay(100);
  Serial.println("Start sensor connection.");

  if (distanceSensor.begin() != 0)
  {
    Serial.println("Sensor failed to begin.");
    while (1);
  }

  Serial.print("Sensor ID: ");
  Serial.println(distanceSensor.getSensorID());

  Serial.println("Sensor online!");
}

void loop(void)
{
  distanceSensor.startRanging(); //Write configuration bytes to initiate measurement
  while (!distanceSensor.checkForDataReady())
  {
    delay(1);
  }
  int distance = distanceSensor.getDistance(); //Get the result of the measurement from the sensor
  distanceSensor.clearInterrupt();
  distanceSensor.stopRanging();

  Serial.print("Distance(mm): ");
  Serial.println(distance);
  delay(2000);
}