# Infiltrometer Automation - Minidisk

## Description
This project aims to automate an infiltrometer system for soil hydraulic measurements.
The main objectives are:

1. **Automated Mariotte Bottle (ILVO/LLN)**
   - Actively regulate hydraulic head (tension)
   - Modular and field-ready design

2. **Data Acquisition System for the infiltrometer (ILVO)**
   - Continuous, high-accuracy measurement
   - Field-ready and modular design
   - Cost-friendly

3. **Coding Framework for Data Integration (ILVO/LLN)**
   - Integrates Minidisk measurements with the automated Mariotte bottle
   - Modular code adaptable to different measurement protocols
   - Algorithm to detect constant flow and change the tension

4. **Guidelines for Laboratory and Field Work (?)**
   - Standardized procedures for setup, operation, and data collection
   - Recommendations for reliable and repeatable measurements

## To do 
- Find the best idea for the mariotte bottles that is cost-friendly. Try to define this idea

---

## Repository Structure

---

## Design Concepts

| Objective Number | Idea | Description | Pros | Cons | Comments |
|-----------|------|-------------|------|------|---------|
| 1 | Vacuum pump + pressure sensor | Actively control tension via vacuum pump | Fast response, precise control | Higher cost, higher power demand | Suitable for lab setups |
| 1 | Servo + threaded lift system | Physically adjust tension in Mariotte bottles | Simple, robust concept | Sensitive to horizontal alignment | Potential for field deployment |
| 2 | SD card logging | Local storage of sensor data | Reliable, simple | Manual data retrieval | Ideal for remote field sites |
| 2 | Wireless transmission (ESP32/Raspberry Pi) | Real-time data access | Continuous monitoring | | Useful for hand free system |
| 2 | Caps modification | Connect Mariotte bottles to the bottom and top cap with sensors | Simplifies design, supports different acrylic tube size | - | |

![Servo + threaded lift system]("minidisk_automation/Figures/Mariotte_Cylinder.gif")
---
## Material links
| Objective Number | Components | Description | Pros | Cons | Comments |
|-----------|------|-------------|------|------|---------|
| 1 | [Differential pressure sensors](https://www.mouser.be/ProductDetail/Honeywell/ABP2DDAN001PD2A3XX?qs=pUKx8fyJudBCfXbaK3v%252BwQ%3D%3D) | Low cost differential pressure | | | 3.3V |
| 2 | [ToF sensors : L53L4CD](https://community.st.com/t5/mems-and-sensors/how-to-choose-a-time-of-flight-sensor/ta-p/49721) | Low cost and ~mm resolution|Possibility to give an adress | | 3.3V |
| 1 | [Sevo motors](https://www.digikey.be/en/products/filter/motors-ac-dc/178?s=N4IgjCBcpgLFoDGUBmBDANgZwKYBoQB7KAbXADYBOWKkAgDgHYBWWegBjouvua48rty8AgCYw7UY0pdxkjl0axxUxeSZgZYifTD1ZO5lpD1R7WO04MzAZkrHRsSs3rkQAXQIAHAC5QQAMo%2BAE4AlgB2AOYgAL4EejYIIMiQ6Nj4RKQgNjYszIwe3n6QgSER0XHglKrQyaiYuATEkGQ5NsyShSC%2B-kFhUbGVolm4wQBuhAAEALaEPoTBWF1utaEAJv4AtBIQRf5cPgCeXjj%2BaFjIMTFAA) | | | | |

---

##  Questions
- Can a single Mariotte bottle serve multiple Minidisks, or is it preferable to provide active control for each Minidisk individually?  
Would it be a nice to try to develop a system that can have different regulated tension ports. For example, different chambers with several servos + threated lift system

---

## Potential Improvements
- Mechanical system to decide infiltration start time across devices. Would permit the setup configuration and then the start of the measurement  
- Tripod or stabilizing connectors for field Minidisk deployment  

---

## Authors
- **Rémy Willemet** – Remy.Willemet@ilvo.vlaanderen.be  
- **Aurelien Lengrend** - Aurelien.Lengrand@uclouvain.be
- **Daniel Wardak** - Daniel.Wardak@uclouvain.be

---

## License
MIT License  

---

## Status
🚧 In Progress  