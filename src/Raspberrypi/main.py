#!/usr/bin/env python3
# main.py — Infiltrometer Controller entry point

import logging
import sys

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
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
    log.info("═" * 60)

    sensor_manager = SensorManager()
    data_logger    = DataLogger()

    # launch_gui blocks until the window is closed
    launch_gui(sensor_manager, data_logger)

    log.info("Application exited cleanly")


if __name__ == "__main__":
    main()
