# gui.py — PyQt5 GUI for the Infiltrometer Controller
#
# Layout (800 × 480, touchscreen-optimised):
#
#  ┌──────────────────────────────────────────────────────────────────────────┐
#  │  HEADER: folder name │ #sensors │ interval │ Start All btn │ status/batt │
#  ├──────────────────────────────────────────────────────────────────────────┤
#  │                                                                          │
#  │   SENSOR GRID  (fills all available width, up to 4 columns)             │
#  │   Each tile: sensor name + status dot                                    │
#  │               distance reading (mm)                                      │
#  │               tension spin-box (cmH2O)                                   │
#  │               Start / Stop button (per-sensor)                           │
#  │                                                                          │
#  ├──────────────────────────────────────────────────────────────────────────┤
#  │  FOOTER: elapsed time │ row count │ warnings                             │
#  └──────────────────────────────────────────────────────────────────────────┘

import sys
import logging
import threading
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit,
    QGridLayout, QVBoxLayout, QHBoxLayout,
    QFrame, QSizePolicy, QMessageBox
)

from config import (
    WINDOW_TITLE, SCREEN_WIDTH, SCREEN_HEIGHT,
    FONT_FAMILY, MEASUREMENT_INTERVALS, DEFAULT_INTERVAL, MAX_SENSORS,
    COLOR_BG, COLOR_PANEL, COLOR_ACCENT, COLOR_WARNING, COLOR_ERROR,
    COLOR_TEXT, COLOR_TEXT_DIM, COLOR_OK
)

log = logging.getLogger(__name__)

# Colour used to dim a paused tile
COLOR_PAUSED_BG  = "#1A2230"
COLOR_PAUSED_FG  = "#4A5A6C"
COLOR_STOP_BTN   = COLOR_ERROR      # red
COLOR_START_BTN  = COLOR_ACCENT     # green


# ─────────────────────────────────────────────────────────────────────────────
# Signal bridge: lets the worker thread send data to the GUI thread safely
# ─────────────────────────────────────────────────────────────────────────────
class Signals(QObject):
    measurement_ready = pyqtSignal(dict)   # sensor_results dict
    error_occurred    = pyqtSignal(str)    # error message
    init_done         = pyqtSignal(list)   # list[bool] sensor online status


# ─────────────────────────────────────────────────────────────────────────────
# Sensor tile widget — one per sensor
# Each tile is self-contained: it holds the tension input and Start/Stop button.
# ─────────────────────────────────────────────────────────────────────────────
class SensorTile(QFrame):
    # Emitted when the user clicks the tile's Start/Stop button
    toggled = pyqtSignal(int, bool)   # (sensor_idx, is_now_running)

    def __init__(self, idx: int, parent=None):
        super().__init__(parent)
        self.idx = idx
        self._running = False   # local running state for this tile
        self._online = False
        self._tension_value: float = 0.0   # cmH2O, set via +/- buttons
        self._setup_ui()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setMinimumSize(170, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._apply_style(paused=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # ── Header row: name + status dot ──
        header = QHBoxLayout()
        self.lbl_name = QLabel(f"Sensor {self.idx + 1}")
        self.lbl_name.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11px; font-weight: bold; border: none;"
        )
        self.lbl_status = QLabel("●")
        self.lbl_status.setStyleSheet("color: #555; font-size: 14px; border: none;")
        header.addWidget(self.lbl_name)
        header.addStretch()
        header.addWidget(self.lbl_status)
        layout.addLayout(header)

        # ── Distance reading ──
        self.lbl_distance = QLabel("---")
        self.lbl_distance.setAlignment(Qt.AlignCenter)
        self.lbl_distance.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 22px; font-weight: bold; border: none;"
        )
        layout.addWidget(self.lbl_distance)

        # ── Unit ──
        self.lbl_unit = QLabel("mm")
        self.lbl_unit.setAlignment(Qt.AlignCenter)
        self.lbl_unit.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 10px; border: none;"
        )
        layout.addWidget(self.lbl_unit)

        # ── Tension input (cmH2O) — touchscreen +/- buttons ──
        _btn_css = f"""
            QPushButton {{
                background-color: #2C3E50; color: {COLOR_TEXT};
                border: 1px solid #3A4A5C; border-radius: 4px;
                font-size: 16px; font-weight: bold; min-width: 28px;
            }}
            QPushButton:pressed {{ background-color: #3A4A5C; }}
        """
        tension_row = QHBoxLayout()
        tension_row.setSpacing(4)

        self.btn_tension_minus = QPushButton("−")
        self.btn_tension_minus.setFixedSize(28, 24)
        self.btn_tension_minus.setStyleSheet(_btn_css)
        self.btn_tension_minus.clicked.connect(self._on_tension_minus)

        self.lbl_tension_val = QLabel("0.0 cmH₂O")
        self.lbl_tension_val.setAlignment(Qt.AlignCenter)
        self.lbl_tension_val.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 11px; border: none;"
        )

        self.btn_tension_plus = QPushButton("+")
        self.btn_tension_plus.setFixedSize(28, 24)
        self.btn_tension_plus.setStyleSheet(_btn_css)
        self.btn_tension_plus.clicked.connect(self._on_tension_plus)

        tension_row.addWidget(self.btn_tension_minus)
        tension_row.addWidget(self.lbl_tension_val, stretch=1)
        tension_row.addWidget(self.btn_tension_plus)
        layout.addLayout(tension_row)

        # ── Warning text ──
        self.lbl_warn = QLabel("")
        self.lbl_warn.setAlignment(Qt.AlignCenter)
        self.lbl_warn.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 9px; border: none;"
        )
        layout.addWidget(self.lbl_warn)

        # ── Per-sensor Start / Stop button ──
        self.btn_toggle = QPushButton("▶  Start")
        self.btn_toggle.setFixedHeight(30)
        self.btn_toggle.setEnabled(False)   # enabled after init
        self.btn_toggle.setStyleSheet(self._btn_style(COLOR_START_BTN))
        self.btn_toggle.clicked.connect(self._on_toggle)
        layout.addWidget(self.btn_toggle)

    # ── Tension button handlers ───────────────────────────────────────────────

    def _on_tension_plus(self):
        self._tension_value = round(min(500.0, self._tension_value + 0.5), 1)
        self.lbl_tension_val.setText(f"{self._tension_value:.1f} cmH\u2082O")

    def _on_tension_minus(self):
        self._tension_value = round(max(0.0, self._tension_value - 0.5), 1)
        self.lbl_tension_val.setText(f"{self._tension_value:.1f} cmH\u2082O")

    # ── Styling helpers ───────────────────────────────────────────────────────

    def _apply_style(self, paused: bool):
        bg = COLOR_PAUSED_BG if paused else COLOR_PANEL
        border = COLOR_PAUSED_FG if paused else "#3A4A5C"
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 8px;
            }}
        """)

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color}; color: white;
                border-radius: 5px; font-size: 12px; font-weight: bold;
                border: none;
            }}
            QPushButton:pressed {{ opacity: 0.8; }}
            QPushButton:disabled {{ background-color: #3A4A5C; color: #666; border: none; }}
        """

    # ── User interaction ──────────────────────────────────────────────────────

    def _on_toggle(self):
        self._running = not self._running
        self._refresh_button()
        self.toggled.emit(self.idx, self._running)

    def _refresh_button(self):
        if self._running:
            self.btn_toggle.setText("■  Stop")
            self.btn_toggle.setStyleSheet(self._btn_style(COLOR_STOP_BTN))
            self._apply_style(paused=False)
        else:
            self.btn_toggle.setText("▶  Start")
            self.btn_toggle.setStyleSheet(self._btn_style(COLOR_START_BTN))
            self._apply_style(paused=True)

    # ── Public API (called from MainWindow) ───────────────────────────────────

    def set_globally_started(self, started: bool):
        """Called when the global Start All / Stop All is pressed."""
        if not self._online:
            return
        if self._running != started:
            self._running = started
            self._refresh_button()
        self.btn_toggle.setEnabled(started or not started)  # always keep enabled

    def set_online(self, online: bool):
        self._online = online
        self.btn_toggle.setEnabled(online)
        if not online:
            self.lbl_status.setStyleSheet(
                f"color: {COLOR_ERROR}; font-size: 14px; border: none;"
            )
            self.lbl_distance.setText("OFF")
            self.lbl_distance.setStyleSheet(
                f"color: {COLOR_ERROR}; font-size: 22px; font-weight: bold; border: none;"
            )
            self.lbl_warn.setText("Not detected")

    def set_offline(self):
        self.lbl_status.setStyleSheet("color: #555; font-size: 14px; border: none;")
        self.lbl_distance.setText("---")
        self.lbl_distance.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 22px; font-weight: bold; border: none;"
        )
        self.lbl_warn.setText("")

    def update_reading(self, data: dict, online: bool):
        if not online:
            self.set_online(False)
            return

        dist  = data.get('distance_mm')
        fault = data.get('fault', False)
        low   = data.get('low_water', False)
        status = data.get('status', -1)

        # Status dot colour
        if fault:
            dot_color = COLOR_ERROR
        elif low:
            dot_color = COLOR_WARNING
        elif status == 0:
            dot_color = COLOR_OK
        else:
            dot_color = COLOR_WARNING
        self.lbl_status.setStyleSheet(
            f"color: {dot_color}; font-size: 14px; border: none;"
        )

        # Distance value
        if dist is not None:
            self.lbl_distance.setText(str(dist))
            dist_color = COLOR_WARNING if low else COLOR_TEXT
        else:
            self.lbl_distance.setText("ERR")
            dist_color = COLOR_ERROR
        self.lbl_distance.setStyleSheet(
            f"color: {dist_color}; font-size: 22px; font-weight: bold; border: none;"
        )

        # Warning text
        if fault:
            self.lbl_warn.setText("⚠ GPIO fault")
        elif low:
            self.lbl_warn.setText("⚠ Low water!")
        else:
            self.lbl_warn.setText("")

    @property
    def tension_cmH2O(self) -> float:
        return self._tension_value

    @property
    def is_running(self) -> bool:
        return self._running


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):

    def __init__(self, sensor_manager, data_logger):
        super().__init__()
        self.sm = sensor_manager
        self.dl = data_logger
        self.signals = Signals()

        self._globally_running = False   # True once "Start All" has been pressed
        self._worker_thread = None
        self._start_time = None
        self._row_count = 0
        self._sensor_online: list[bool] = [False] * MAX_SENSORS
        self._num_sensors = MAX_SENSORS  # will be set by the spinner

        self._setup_window()
        self._build_ui()
        self._connect_signals()

        # Clock timer
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

        # Initialise sensors in background (uses current spinner value)
        threading.Thread(target=self._init_sensors, daemon=True).start()

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowTitle(WINDOW_TITLE)
        self.setFixedSize(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.setWindowFlags(Qt.FramelessWindowHint)

        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(COLOR_BG))
        self.setPalette(palette)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_sensor_area(), stretch=1)
        root.addWidget(self._build_footer())

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {COLOR_PANEL}; border-bottom: 1px solid #3A4A5C;"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        # ── Folder name ──
        lbl_f = QLabel("Folder:")
        lbl_f.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        self.edit_folder = QLineEdit()
        self.edit_folder.setPlaceholderText("session_name")
        self.edit_folder.setFixedWidth(140)
        self.edit_folder.setStyleSheet(f"""
            QLineEdit {{
                background-color: #1E2A3A; color: {COLOR_TEXT};
                border: 1px solid #3A4A5C; border-radius: 4px;
                padding: 3px 6px; font-size: 12px;
            }}
        """)
        layout.addWidget(lbl_f)
        layout.addWidget(self.edit_folder)

        layout.addSpacing(6)

        # ── Number of sensors ──
        lbl_n = QLabel("Sensors:")
        lbl_n.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        self.spin_num_sensors = QSpinBox()
        self.spin_num_sensors.setRange(1, MAX_SENSORS)
        self.spin_num_sensors.setValue(MAX_SENSORS)
        self.spin_num_sensors.setFixedWidth(52)
        self.spin_num_sensors.setStyleSheet(f"""
            QSpinBox {{
                background-color: #1E2A3A; color: {COLOR_TEXT};
                border: 1px solid #3A4A5C; border-radius: 4px;
                padding: 3px; font-size: 12px;
            }}
        """)
        self.spin_num_sensors.valueChanged.connect(self._on_num_sensors_changed)
        layout.addWidget(lbl_n)
        layout.addWidget(self.spin_num_sensors)

        layout.addSpacing(6)

        # ── Measurement interval ──
        lbl_i = QLabel("Interval:")
        lbl_i.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        self.combo_interval = QComboBox()
        for s in MEASUREMENT_INTERVALS:
            self.combo_interval.addItem(f"{s} s", s)
        self.combo_interval.setCurrentIndex(MEASUREMENT_INTERVALS.index(DEFAULT_INTERVAL))
        self.combo_interval.setFixedWidth(72)
        self.combo_interval.setStyleSheet(f"""
            QComboBox {{
                background-color: #1E2A3A; color: {COLOR_TEXT};
                border: 1px solid #3A4A5C; border-radius: 4px;
                padding: 3px; font-size: 12px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #1E2A3A; color: {COLOR_TEXT};
            }}
        """)
        layout.addWidget(lbl_i)
        layout.addWidget(self.combo_interval)

        layout.addStretch()

        # ── Global Start All / Stop All ──
        self.btn_global = QPushButton("▶  Start All")
        self.btn_global.setFixedSize(120, 38)
        self.btn_global.setEnabled(False)
        self.btn_global.setStyleSheet(self._btn_style(COLOR_START_BTN))
        self.btn_global.clicked.connect(self._on_global_toggle)
        layout.addWidget(self.btn_global)

        layout.addSpacing(10)

        # ── Status + battery ──
        right = QVBoxLayout()
        right.setSpacing(2)
        self.lbl_init_status = QLabel("Initialising sensors…")
        self.lbl_init_status.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 10px;"
        )
        self.lbl_battery = QLabel("🔋 ---%")
        self.lbl_battery.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 10px;"
        )
        right.addWidget(self.lbl_init_status)
        right.addWidget(self.lbl_battery)
        layout.addLayout(right)

        return header

    # ── Sensor area ───────────────────────────────────────────────────────────

    def _build_sensor_area(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        self._grid = QGridLayout(container)
        self._grid.setContentsMargins(8, 8, 8, 4)
        self._grid.setSpacing(6)

        self.tiles: list[SensorTile] = []
        for i in range(MAX_SENSORS):
            tile = SensorTile(i)
            tile.toggled.connect(self._on_tile_toggled)
            row, col = divmod(i, 4)
            self._grid.addWidget(tile, row, col)
            self.tiles.append(tile)

        # Make all columns stretch equally
        for col in range(4):
            self._grid.setColumnStretch(col, 1)
        for row in range(2):
            self._grid.setRowStretch(row, 1)

        # Hide tiles beyond current sensor count
        self._refresh_tile_visibility()

        return container

    # ── Footer ────────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setFixedHeight(32)
        footer.setStyleSheet(
            f"background-color: {COLOR_PANEL}; border-top: 1px solid #3A4A5C;"
        )
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 0, 12, 0)

        self.lbl_elapsed = QLabel("Elapsed: --:--:--")
        self.lbl_elapsed.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11px;"
        )
        layout.addWidget(self.lbl_elapsed)

        layout.addStretch()

        self.lbl_file = QLabel("No session")
        self.lbl_file.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 10px;"
        )
        layout.addWidget(self.lbl_file)

        layout.addSpacing(16)

        self.lbl_rows = QLabel("Rows: 0")
        self.lbl_rows.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11px;"
        )
        layout.addWidget(self.lbl_rows)

        layout.addSpacing(16)

        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px;"
        )
        layout.addWidget(self.lbl_warnings)

        return footer

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color}; color: white;
                border-radius: 6px; font-size: 13px; font-weight: bold;
                border: none;
            }}
            QPushButton:pressed {{ background-color: #1A9C55; }}
            QPushButton:disabled {{ background-color: #3A4A5C; color: #666; }}
        """

    def _refresh_tile_visibility(self):
        n = self._num_sensors
        for i, tile in enumerate(self.tiles):
            tile.setVisible(i < n)

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self):
        self.signals.measurement_ready.connect(self._on_measurement)
        self.signals.error_occurred.connect(self._on_error)
        self.signals.init_done.connect(self._on_init_done)

    # ── Sensor count changed ──────────────────────────────────────────────────

    def _on_num_sensors_changed(self, value: int):
        if self._globally_running:
            # Don't allow changing sensor count mid-session
            self.spin_num_sensors.blockSignals(True)
            self.spin_num_sensors.setValue(self._num_sensors)
            self.spin_num_sensors.blockSignals(False)
            return
        self._num_sensors = value
        self._refresh_tile_visibility()

    # ── Sensor initialisation (runs in thread) ────────────────────────────────

    def _init_sensors(self):
        try:
            online = self.sm.initialise(num_sensors=self._num_sensors)
            self.signals.init_done.emit(online)
        except Exception as e:
            self.signals.error_occurred.emit(f"Init failed: {e}")

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_init_done(self, online: list):
        self._sensor_online = online + [False] * (MAX_SENSORS - len(online))
        count = sum(online)
        total = len(online)
        self.lbl_init_status.setText(f"✓ {count}/{total} sensors online")
        self.lbl_init_status.setStyleSheet(
            f"color: {COLOR_OK if count == total else COLOR_WARNING}; font-size: 10px;"
        )
        for i, tile in enumerate(self.tiles):
            if i < len(online):
                tile.set_online(online[i])
            else:
                tile.set_online(False)

        self.btn_global.setEnabled(count > 0)

    def _on_global_toggle(self):
        if not self._globally_running:
            self._start_session()
        else:
            self._stop_session()

    def _start_session(self):
        folder = self.edit_folder.text().strip() or "session"
        tensions = [t.tension_cmH2O for t in self.tiles]
        self.dl.set_tensions(tensions)
        try:
            filepath = self.dl.start_session(folder, self._num_sensors)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot create session file:\n{e}")
            return

        short = filepath.split("/")[-1]
        self.lbl_file.setText(short)

        self._globally_running = True
        self._start_time = datetime.now()
        self._row_count = 0

        # Start all tiles
        for tile in self.tiles[:self._num_sensors]:
            tile.set_globally_started(True)

        self.btn_global.setText("■  Stop All")
        self.btn_global.setStyleSheet(self._btn_style(COLOR_STOP_BTN))
        self.combo_interval.setEnabled(False)
        self.spin_num_sensors.setEnabled(False)
        self.edit_folder.setEnabled(False)

        interval = self.combo_interval.currentData()
        self._worker_thread = threading.Thread(
            target=self._measurement_loop, args=(interval,), daemon=True
        )
        self._worker_thread.start()

    def _stop_session(self):
        self._globally_running = False
        self.dl.stop_session()

        for tile in self.tiles:
            tile.set_globally_started(False)

        self.btn_global.setText("▶  Start All")
        self.btn_global.setStyleSheet(self._btn_style(COLOR_START_BTN))
        self.combo_interval.setEnabled(True)
        self.spin_num_sensors.setEnabled(True)
        self.edit_folder.setEnabled(True)
        self.lbl_file.setText("Session saved")

    def _on_tile_toggled(self, idx: int, is_running: bool):
        """
        Called when a single sensor tile's Start/Stop button is pressed.
        We just need to update the tension list when resuming,
        so the data logger picks up any changed value immediately.
        """
        if is_running:
            # User restarted this sensor — refresh tension value
            tensions = [t.tension_cmH2O for t in self.tiles]
            self.dl.set_tensions(tensions)
            log.info(f"Sensor {idx + 1} resumed, tension={tensions[idx]:.1f} cmH2O")
        else:
            log.info(f"Sensor {idx + 1} paused by user")

    def _on_measurement(self, results: dict):
        """Update UI with latest readings (called in GUI thread)."""
        warnings = []
        for i in range(self._num_sensors):
            data = results.get(i, {})
            self.tiles[i].update_reading(data, self._sensor_online[i])
            if data.get('low_water'):
                warnings.append(f"S{i+1}:LowWater")
            if data.get('fault'):
                warnings.append(f"S{i+1}:Fault")

        self._row_count += 1
        self.lbl_rows.setText(f"Rows: {self._row_count}")
        self.lbl_warnings.setText("  ".join(warnings))

    def _on_error(self, msg: str):
        log.error(msg)
        QMessageBox.critical(self, "Error", msg)

    # ── Measurement worker (background thread) ────────────────────────────────

    def _measurement_loop(self, interval: int):
        """
        Reads all active sensors each tick.
        Only writes CSV rows for sensors whose tile is currently running
        (not paused by the user).
        """
        while self._globally_running:
            t0 = time.monotonic()
            try:
                results = self.sm.read_all()

                # Determine which sensors are active (not paused)
                active = {
                    i for i in range(self._num_sensors)
                    if self.tiles[i].is_running
                }
                self.dl.write_row(results, active_sensors=active)
                self.signals.measurement_ready.emit(results)
            except Exception as e:
                self.signals.error_occurred.emit(str(e))

            elapsed = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _tick_clock(self):
        if self._globally_running and self._start_time:
            delta = datetime.now() - self._start_time
            h, rem = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            self.lbl_elapsed.setText(f"Elapsed: {h:02d}:{m:02d}:{s:02d}")
        self._update_battery()

    def _update_battery(self):
        try:
            from pijuice import PiJuice
            if not hasattr(self, '_pijuice'):
                self._pijuice = PiJuice(1, 0x14)
            level = self._pijuice.status.GetChargeLevel()
            if level.get('error') == 'NO_ERROR':
                pct = level['data']
                self.lbl_battery.setText(f"🔋 {pct}%")
                color = (
                    COLOR_OK if pct > 20
                    else COLOR_WARNING if pct > 10
                    else COLOR_ERROR
                )
                self.lbl_battery.setStyleSheet(f"color: {color}; font-size: 10px;")
        except Exception:
            pass

    # ── Safe close ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._globally_running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=3)
        self.dl.stop_session()
        self.sm.shutdown()
        event.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────
def launch_gui(sensor_manager, data_logger):
    app = QApplication(sys.argv)
    app.setFont(QFont(FONT_FAMILY, 11))

    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window,        QColor(COLOR_BG))
    palette.setColor(QPalette.WindowText,    QColor(COLOR_TEXT))
    palette.setColor(QPalette.Base,          QColor(COLOR_PANEL))
    palette.setColor(QPalette.AlternateBase, QColor(COLOR_PANEL))
    palette.setColor(QPalette.Text,          QColor(COLOR_TEXT))
    palette.setColor(QPalette.Button,        QColor(COLOR_PANEL))
    palette.setColor(QPalette.ButtonText,    QColor(COLOR_TEXT))
    app.setPalette(palette)

    window = MainWindow(sensor_manager, data_logger)
    window.show()
    sys.exit(app.exec_())
