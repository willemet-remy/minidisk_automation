# data_logger.py — CSV data logging to USB stick (or fallback local dir)

import os
import csv
import glob
import logging
from datetime import datetime
from config import (
    USB_MOUNT_PATH, FALLBACK_DATA_DIR,
    CSV_DELIMITER, CSV_TIMESTAMP_FORMAT, NUM_SENSORS
)

log = logging.getLogger(__name__)


def find_usb_path() -> str:
    """
    Return path to first available USB stick mount point.
    RPi OS (Bookworm) auto-mounts to /media/pi/<label>.
    Falls back to FALLBACK_DATA_DIR.
    """
    candidates = glob.glob(os.path.join(USB_MOUNT_PATH, "*"))
    for path in candidates:
        if os.path.ismount(path) and os.access(path, os.W_OK):
            log.info(f"USB stick found at {path}")
            return path
    log.warning(f"No USB stick found under {USB_MOUNT_PATH}, using {FALLBACK_DATA_DIR}")
    os.makedirs(FALLBACK_DATA_DIR, exist_ok=True)
    return FALLBACK_DATA_DIR


class DataLogger:
    """
    Writes one CSV file per measurement session.

    File name format: infiltrometer_YYYYMMDD_HHMMSS.csv

    CSV columns:
        timestamp, sensor_0_mm, sensor_1_mm, ..., sensor_7_mm,
        tension_0_hPa, tension_1_hPa, ..., tension_7_hPa,
        fault_0, fault_1, ..., fault_7
    """

    SENSOR_COLS   = [f"sensor_{i}_mm"      for i in range(NUM_SENSORS)]
    TENSION_COLS  = [f"tension_{i}_hPa"    for i in range(NUM_SENSORS)]
    FAULT_COLS    = [f"fault_{i}"          for i in range(NUM_SENSORS)]
    LOW_WATER_COLS= [f"low_water_{i}"      for i in range(NUM_SENSORS)]

    HEADER = ["timestamp"] + SENSOR_COLS + TENSION_COLS + FAULT_COLS + LOW_WATER_COLS

    def __init__(self):
        self._file = None
        self._writer = None
        self._filepath = None
        self._tensions: list[float] = [0.0] * NUM_SENSORS

    # ── Configuration ─────────────────────────────────────────────────────────

    def set_tensions(self, tensions: list[float]):
        """Store applied tension (hPa) per minidisk, called from GUI."""
        self._tensions = list(tensions)

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def start_session(self) -> str:
        """Open a new CSV file. Returns the file path."""
        if self._file:
            self.stop_session()

        data_dir = find_usb_path()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"infiltrometer_{timestamp_str}.csv"
        self._filepath = os.path.join(data_dir, filename)

        self._file = open(self._filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=self.HEADER,
            delimiter=CSV_DELIMITER
        )
        self._writer.writeheader()
        self._file.flush()
        log.info(f"Session started → {self._filepath}")
        return self._filepath

    def stop_session(self):
        """Flush and close the current CSV file."""
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None
            self._writer = None
            log.info(f"Session stopped. File saved: {self._filepath}")

    # ── Writing ───────────────────────────────────────────────────────────────

    def write_row(self, sensor_results: dict):
        """
        Write one measurement row.
        sensor_results is the dict returned by SensorManager.read_all().
        """
        if not self._writer:
            log.warning("write_row called but no active session")
            return

        now = datetime.now().strftime(CSV_TIMESTAMP_FORMAT)
        row = {"timestamp": now}

        for i in range(NUM_SENSORS):
            data = sensor_results.get(i, {})
            row[f"sensor_{i}_mm"]     = data.get("distance_mm", "")
            row[f"tension_{i}_hPa"]   = self._tensions[i]
            row[f"fault_{i}"]         = int(data.get("fault", False))
            row[f"low_water_{i}"]     = int(data.get("low_water", False))

        self._writer.writerow(row)
        self._file.flush()   # ensure data is written even if power is cut

    # ── Utilities ─────────────────────────────────────────────────────────────

    @property
    def filepath(self) -> str | None:
        return self._filepath

    @property
    def is_active(self) -> bool:
        return self._file is not None
