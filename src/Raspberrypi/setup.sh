#!/bin/bash
# setup.sh — Run once on the Raspberry Pi to install dependencies and configure autostart
# Usage: bash setup.sh

set -e
echo "=== Infiltrometer Setup ==="
echo "Created by Rémy Willemet =="
echo "First version 2027-03-27 == "
echo "============================"

# ── 1. System packages ────────────────────────────────────────────────────────
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-smbus \
    python3-pyqt5 \
    i2c-tools \
    git



# ── 2. Enable I2C ─────────────────────────────────────────────────────────────
sudo raspi-config nonint do_i2c 0
# Also ensure 100 kHz I2C speed (safe for 8 sensors on long wires)
if ! grep -q "dtparam=i2c_arm_baudrate" /boot/firmware/config.txt; then
    echo "dtparam=i2c_arm_baudrate=100000" | sudo tee -a /boot/firmware/config.txt
fi

# ── 3. Create data fallback directory ─────────────────────────────────────────
mkdir -p /home/pi/infiltrometer_data

# ── 4. Copy app to /home/pi/infiltrometer and setup venv ────────────────────
DEST=/home/pi/infiltrometer
mkdir -p "$DEST"
if [ "$PWD" != "$DEST" ]; then
    rsync -a --ignore-existing *.py "$DEST/"
    chmod +x "$DEST/main.py"
fi

# Create and populate local venv inside the destination directory
if [ ! -d "$DEST/venv" ]; then
    python3 -m venv --system-site-packages "$DEST/venv"
fi
"$DEST/venv/bin/pip" install smbus2 adafruit-circuitpython-vl53l4cd

# ── 5. Autostart on boot (via desktop autostart) ─────────────────────────────
mkdir -p /home/pi/.config/autostart
mkdir -p /home/pi/Desktop
DESKTOP_FILE=/home/pi/.config/autostart/infiltrometer.desktop
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Infiltrometer Controller
Exec=lxterminal --geometry=120x40 -e bash -c "/home/pi/infiltrometer/venv/bin/python /home/pi/infiltrometer/main.py; echo 'App closed or crashed.'; read -p 'Press Enter to close'"
Path=/home/pi/infiltrometer
Icon=/home/pi/infiltrometer/logo.png
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
chmod +x "$DESKTOP_FILE"

# Copy shortcut to Desktop for manual launch
cp "$DESKTOP_FILE" /home/pi/Desktop/infiltrometer.desktop
chmod +x /home/pi/Desktop/infiltrometer.desktop
echo ""
echo "=== Setup complete ==="
echo "Reboot to start the application automatically."
echo "To view logs anytime: tail -f /home/pi/infiltrometer.log"
