# Slimme Minidisk acquisition app

Connect the ESP32 receiver to a Windows, Linux, or macOS computer by USB and use this desktop program to observe sensor status and record CSV measurements.

## Install and run

```powershell
python -m pip install pyserial
python minidisk_acquisition.py
```

Select the receiver COM/serial port, click **Connect**, then wait for each node to send its status packet. The table uses the permanent `NODE_NAME` programmed into every sender and shows whether each sensor was seen in the last 180 seconds.

## Measurement workflow

1. Enter the measurement name, tension in hPa, and optional notes.
2. Click **Start measurement** and choose the CSV destination.
3. The program sends `START` to the USB receiver, which broadcasts it to all nodes.
4. When a node next wakes, it enters measuring mode and its valid readings are appended to the CSV.
5. Click **Pause** to stop sensor readings while retaining the current CSV session; the same button becomes **Resume**. Click **End and save CSV** to close it.

Battery nodes wake only every `SAMPLE_INTERVAL_SECONDS` (60 seconds by default). A command is therefore not immediate: it is received in the 700 ms listening window immediately after the node's next status packet. The app displays that state from node packets, not merely from the button click.

Each CSV row includes timestamp, measurement metadata, fixed sensor name, distance, VL53 range status, battery voltage (when enabled), and the sender MAC address.
