# data_logger.py — CSV data logging to USB stick (or fallback local dir)

import os
import csv
import glob
import logging
from datetime import datetime
from config import (
    USB_MOUNT_PATH, FALLBACK_DATA_DIR,
    CSV_DELIMITER, CSV_TIMESTAMP_FORMAT, MAX_SENSORS
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
    Stored inside: <base_dir>/<folder_name>/

    CSV columns (for num_sensors sensors):
        timestamp,
        sensor_0_mm, …, sensor_N_mm,
        tension_0_cmH2O, …, tension_N_cmH2O,
        fault_0, …, fault_N,
        low_water_0, …, low_water_N
    """

    def __init__(self):
        self._file = None
        self._writer = None
        self._filepath = None
        self._num_sensors: int = MAX_SENSORS
        self._tensions: list[float] = [0.0] * MAX_SENSORS
        self._header: list[str] = []

    # ── Configuration ─────────────────────────────────────────────────────────

    def set_tensions(self, tensions: list[float]):
        """Store applied tension (cmH2O) per sensor, called from GUI."""
        self._tensions = list(tensions)

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def start_session(
        self,
        folder_name: str,
        num_sensors: int,
        base_dir: str | None = None,
    ) -> str:
        """
        Open a new CSV file inside <base_dir>/<folder_name>/.
        Returns the file path.

        Args:
            folder_name:  name of the subfolder to create/use.
            num_sensors:  how many sensors are active this session.
            base_dir:     override base directory (default: USB or fallback).
        """
        if self._file:
            self.stop_session()

        self._num_sensors = num_sensors

        # Build column headers for this session
        self._header = (
            ["timestamp"]
            + [f"sensor_{i}_mm"       for i in range(num_sensors)]
            + [f"tension_{i}_cmH2O"   for i in range(num_sensors)]
            + [f"fault_{i}"           for i in range(num_sensors)]
            + [f"low_water_{i}"       for i in range(num_sensors)]
        )

        if base_dir is None:
            base_dir = find_usb_path()

        # Create session subfolder
        session_dir = os.path.join(base_dir, folder_name.strip() or "session")
        os.makedirs(session_dir, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"infiltrometer_{timestamp_str}.csv"
        self._filepath = os.path.join(session_dir, filename)

        self._file = open(self._filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=self._header,
            delimiter=CSV_DELIMITER,
            extrasaction="ignore",
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

    def write_row(self, sensor_results: dict, active_sensors: set | None = None):
        """
        Write one measurement row.

        Args:
            sensor_results:  dict returned by SensorManager.read_all().
            active_sensors:  set of sensor indices that are currently active
                             (not paused). If None, all sensors are written.
                             Paused sensors get empty strings for their columns.
        """
        if not self._writer:
            log.warning("write_row called but no active session")
            return

        if active_sensors is None:
            active_sensors = set(range(self._num_sensors))

        now = datetime.now().strftime(CSV_TIMESTAMP_FORMAT)
        row: dict = {"timestamp": now}

        for i in range(self._num_sensors):
            if i in active_sensors:
                data = sensor_results.get(i, {})
                row[f"sensor_{i}_mm"]      = data.get("distance_mm", "")
                row[f"tension_{i}_cmH2O"]  = self._tensions[i] if i < len(self._tensions) else ""
                row[f"fault_{i}"]          = int(data.get("fault", False))
                row[f"low_water_{i}"]      = int(data.get("low_water", False))
            else:
                # Sensor is paused — leave blank
                row[f"sensor_{i}_mm"]      = ""
                row[f"tension_{i}_cmH2O"]  = ""
                row[f"fault_{i}"]          = ""
                row[f"low_water_{i}"]      = ""

        self._writer.writerow(row)
        self._file.flush()   # ensure data is written even if power is cut

    # ── Utilities ─────────────────────────────────────────────────────────────

    @property
    def filepath(self) -> str | None:
        return self._filepath

    @property
    def is_active(self) -> bool:
        return self._file is not None
