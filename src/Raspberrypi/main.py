#!/usr/bin/env python3
# main.py — Infiltrometer Controller entry point

import logging
import os
import sys
import getpass

# ── User check ────────────────────────────────────────────────────────────────
if getpass.getuser() != "pi":
    print("Error: Infiltrometer Controller must be run as the 'pi' user.", file=sys.stderr)
    sys.exit(1)

# ── Qt platform detection ─────────────────────────────────────────────────────
# On the Pi, if no X display is available (e.g. booted to console or SSH),
# fall back to the Linux framebuffer directly.  The service file sets DISPLAY=:0
# when a graphical session is active; otherwise we choose linuxfb automatically.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "linuxfb")

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("/home/pi/infiltrometer.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("main")

# ── Import application modules ────────────────────────────────────────────────
from sensor_manager import SensorManager
from data_logger import DataLogger
from gui import launch_gui


def main():
    log.info("═" * 60)
    log.info("Infiltrometer Controller starting")
    log.info(f"Qt platform: {os.environ.get('QT_QPA_PLATFORM', 'xcb (default)')}")
    log.info(f"DISPLAY: {os.environ.get('DISPLAY', '(not set)')}")
    log.info("═" * 60)

    sensor_manager = SensorManager()
    data_logger    = DataLogger()

    # launch_gui blocks until the window is closed
    launch_gui(sensor_manager, data_logger)

    log.info("Application exited cleanly")


if __name__ == "__main__":
    main()
