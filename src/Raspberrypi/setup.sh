#!/bin/bash
# setup.sh — Run once on the Raspberry Pi to install dependencies and configure autostart
# Usage: bash setup.sh

set -e
echo "=== Infiltrometer Setup ==="

# ── 1. System packages ────────────────────────────────────────────────────────
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-smbus \
    python3-pyqt5 \
    i2c-tools \
    git

# ── 2. Python packages ────────────────────────────────────────────────────────
pip3 install --break-system-packages smbus2 vl53l4cd pijuice

# ── 3. Enable I2C ─────────────────────────────────────────────────────────────
sudo raspi-config nonint do_i2c 0
# Also ensure 100 kHz I2C speed (safe for 8 sensors on long wires)
if ! grep -q "dtparam=i2c_arm_baudrate" /boot/firmware/config.txt; then
    echo "dtparam=i2c_arm_baudrate=100000" | sudo tee -a /boot/firmware/config.txt
fi

# ── 4. Create data fallback directory ─────────────────────────────────────────
mkdir -p /home/pi/infiltrometer_data

# ── 5. Copy app to /home/pi/infiltrometer ────────────────────────────────────
DEST=/home/pi/infiltrometer
mkdir -p "$DEST"
cp *.py "$DEST/"
chmod +x "$DEST/main.py"

# ── 6. Autostart on boot (via systemd, not cron, so GUI has display access) ──
SERVICE_FILE=/etc/systemd/system/infiltrometer.service
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Infiltrometer Controller GUI
After=graphical.target
Wants=graphical.target

[Service]
User=pi
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/pi/.Xauthority
WorkingDirectory=/home/pi/infiltrometer
ExecStart=/usr/bin/python3 /home/pi/infiltrometer/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable infiltrometer.service
echo ""
echo "=== Setup complete ==="
echo "Reboot to start the application automatically."
echo "To start now: sudo systemctl start infiltrometer"
echo "To view logs: journalctl -u infiltrometer -f"
