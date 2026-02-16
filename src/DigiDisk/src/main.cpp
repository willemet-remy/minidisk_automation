#define SHUTDOWN_PIN 2 //D2 pin
#define INTERRUPT_PIN 3 //Normally no need
#include <wire.h>
#include <Arduino.h>
#include "SparkFun_VL53L1X.h" 

SFEVL53L1X distanceSensor(Wire, SHUTDOWN_PIN, INTERRUPT_PIN);

void setup(void)
{
  Wire.begin();

  Serial.begin(115200);
  pinMode(2, OUTPUT);
  digitalWrite(2, HIGH);
  Serial.println("VL53L1X Qwiic Test");
  Serial.println(distanceSensor.getSensorID());
  if (distanceSensor.init() == false)
    Serial.println("Sensor online!");

}

void loop(void)
{
  distanceSensor.startRanging(); //Write configuration bytes to initiate measurement
  int distance = distanceSensor.getDistance(); //Get the result of the measurement from the sensor
  distanceSensor.stopRanging();

  Serial.println("Distance(mm): ");
  Serial.print(distance);
  delay(2000);
}
