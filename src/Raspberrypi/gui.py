# gui.py — PyQt5 GUI for the Infiltrometer Controller
#
# Layout (800 × 480, touchscreen-optimised):
#
#  ┌──────────────────────────────────────────────────────────────┐
#  │  HEADER: title, status bar, battery %                        │
#  ├──────────────────────────────────────────────────────────────┤
#  │  LEFT PANEL (config)     │  RIGHT PANEL (live readings)      │
#  │  - Interval selector     │  - 8 × sensor tile                │
#  │  - Tension inputs (×8)   │    (distance, status icon)        │
#  │  - Start / Stop button   │                                   │
#  │  - File path label       │                                   │
#  ├──────────────────────────────────────────────────────────────┤
#  │  BOTTOM: elapsed time, row count, warnings                   │
#  └──────────────────────────────────────────────────────────────┘

import sys
import logging
import threading
import time
from datetime import datetime, timedelta

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QGridLayout, QVBoxLayout, QHBoxLayout,
    QFrame, QSizePolicy, QMessageBox, QScrollArea
)

from config import (
    WINDOW_TITLE, SCREEN_WIDTH, SCREEN_HEIGHT,
    FONT_FAMILY, MEASUREMENT_INTERVALS, DEFAULT_INTERVAL, NUM_SENSORS,
    COLOR_BG, COLOR_PANEL, COLOR_ACCENT, COLOR_WARNING, COLOR_ERROR,
    COLOR_TEXT, COLOR_TEXT_DIM, COLOR_OK
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Signal bridge: lets the worker thread send data to the GUI thread safely
# ─────────────────────────────────────────────────────────────────────────────
class Signals(QObject):
    measurement_ready = pyqtSignal(dict)   # sensor_results dict
    error_occurred    = pyqtSignal(str)    # error message
    init_done         = pyqtSignal(list)   # list[bool] sensor online status


# ─────────────────────────────────────────────────────────────────────────────
# Sensor tile widget — one per sensor
# ─────────────────────────────────────────────────────────────────────────────
class SensorTile(QFrame):
    def __init__(self, idx: int, parent=None):
        super().__init__(parent)
        self.idx = idx
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedSize(175, 100)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_PANEL};
                border: 2px solid #3A4A5C;
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        # Header row: sensor number + status dot
        header = QHBoxLayout()
        self.lbl_name = QLabel(f"Sensor {self.idx + 1}")
        self.lbl_name.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px; font-weight: bold; border: none;")
        self.lbl_status = QLabel("●")
        self.lbl_status.setStyleSheet(f"color: #555; font-size: 14px; border: none;")
        header.addWidget(self.lbl_name)
        header.addStretch()
        header.addWidget(self.lbl_status)
        layout.addLayout(header)

        # Distance reading
        self.lbl_distance = QLabel("---")
        self.lbl_distance.setAlignment(Qt.AlignCenter)
        self.lbl_distance.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 22px; font-weight: bold; border: none;")
        layout.addWidget(self.lbl_distance)

        # Unit + warning label
        self.lbl_unit = QLabel("mm")
        self.lbl_unit.setAlignment(Qt.AlignCenter)
        self.lbl_unit.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 10px; border: none;")
        layout.addWidget(self.lbl_unit)

        # Warning text
        self.lbl_warn = QLabel("")
        self.lbl_warn.setAlignment(Qt.AlignCenter)
        self.lbl_warn.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 9px; border: none;")
        layout.addWidget(self.lbl_warn)

    def update_reading(self, data: dict, online: bool):
        if not online:
            self.lbl_status.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 14px; border: none;")
            self.lbl_distance.setText("OFF")
            self.lbl_distance.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 22px; font-weight: bold; border: none;")
            self.lbl_warn.setText("Not detected")
            return

        dist = data.get('distance_mm')
        fault = data.get('fault', False)
        low = data.get('low_water', False)
        status = data.get('status', -1)

        # Status dot
        if fault:
            dot_color = COLOR_ERROR
        elif low:
            dot_color = COLOR_WARNING
        elif status == 0:
            dot_color = COLOR_OK
        else:
            dot_color = COLOR_WARNING
        self.lbl_status.setStyleSheet(f"color: {dot_color}; font-size: 14px; border: none;")

        # Distance value
        if dist is not None:
            self.lbl_distance.setText(str(dist))
            dist_color = COLOR_WARNING if low else COLOR_TEXT
        else:
            self.lbl_distance.setText("ERR")
            dist_color = COLOR_ERROR
        self.lbl_distance.setStyleSheet(f"color: {dist_color}; font-size: 22px; font-weight: bold; border: none;")

        # Warning text
        if fault:
            self.lbl_warn.setText("⚠ GPIO fault")
        elif low:
            self.lbl_warn.setText("⚠ Low water!")
        else:
            self.lbl_warn.setText("")

    def set_offline(self):
        self.lbl_status.setStyleSheet("color: #555; font-size: 14px; border: none;")
        self.lbl_distance.setText("---")
        self.lbl_distance.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 22px; font-weight: bold; border: none;")
        self.lbl_warn.setText("")


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):

    def __init__(self, sensor_manager, data_logger):
        super().__init__()
        self.sm = sensor_manager
        self.dl = data_logger
        self.signals = Signals()
        self._running = False
        self._worker_thread = None
        self._start_time = None
        self._row_count = 0
        self._sensor_online = [False] * NUM_SENSORS

        self._setup_window()
        self._build_ui()
        self._connect_signals()

        # Clock timer (updates elapsed time label every second)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

        # Initialise sensors in background
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

        body = QHBoxLayout()
        body.setContentsMargins(8, 8, 8, 0)
        body.setSpacing(8)
        body.addWidget(self._build_left_panel(), stretch=0)
        body.addWidget(self._build_right_panel(), stretch=1)
        root.addLayout(body)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setFixedHeight(44)
        header.setStyleSheet(f"background-color: {COLOR_PANEL}; border-bottom: 1px solid #3A4A5C;")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 0, 12, 0)

        title = QLabel(WINDOW_TITLE)
        title.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 15px; font-weight: bold;")
        layout.addWidget(title)
        layout.addStretch()

        self.lbl_init_status = QLabel("Initialising sensors…")
        self.lbl_init_status.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 11px;")
        layout.addWidget(self.lbl_init_status)

        layout.addSpacing(20)

        self.lbl_battery = QLabel("🔋 ---%")
        self.lbl_battery.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self.lbl_battery)

        return header

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFixedWidth(200)
        panel.setStyleSheet(f"background-color: {COLOR_PANEL}; border-radius: 8px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── Measurement interval ──
        lbl_int = QLabel("Interval")
        lbl_int.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(lbl_int)

        self.combo_interval = QComboBox()
        for s in MEASUREMENT_INTERVALS:
            self.combo_interval.addItem(f"{s} s", s)
        self.combo_interval.setCurrentIndex(MEASUREMENT_INTERVALS.index(DEFAULT_INTERVAL))
        self.combo_interval.setStyleSheet(f"""
            QComboBox {{
                background-color: #1E2A3A; color: {COLOR_TEXT};
                border: 1px solid #3A4A5C; border-radius: 4px;
                padding: 4px; font-size: 13px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #1E2A3A; color: {COLOR_TEXT};
            }}
        """)
        layout.addWidget(self.combo_interval)

        layout.addSpacing(4)

        # ── Tension inputs ──
        lbl_tension = QLabel("Applied tension (hPa)")
        lbl_tension.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(lbl_tension)

        self.tension_spinboxes: list[QDoubleSpinBox] = []
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none; background: transparent;")
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(4)

        for i in range(NUM_SENSORS):
            row = QHBoxLayout()
            lbl = QLabel(f"S{i+1}:")
            lbl.setFixedWidth(24)
            lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 9999.0)
            spin.setDecimals(1)
            spin.setValue(0.0)
            spin.setSuffix(" hPa")
            spin.setStyleSheet(f"""
                QDoubleSpinBox {{
                    background-color: #1E2A3A; color: {COLOR_TEXT};
                    border: 1px solid #3A4A5C; border-radius: 4px;
                    padding: 2px; font-size: 12px;
                }}
            """)
            row.addWidget(lbl)
            row.addWidget(spin)
            scroll_layout.addLayout(row)
            self.tension_spinboxes.append(spin)

        scroll_area.setWidget(scroll_widget)
        scroll_area.setFixedHeight(180)
        layout.addWidget(scroll_area)

        layout.addStretch()

        # ── Start / Stop button ──
        self.btn_start_stop = QPushButton("▶  Start")
        self.btn_start_stop.setFixedHeight(44)
        self.btn_start_stop.setStyleSheet(self._btn_style(COLOR_ACCENT))
        self.btn_start_stop.clicked.connect(self._on_start_stop)
        layout.addWidget(self.btn_start_stop)

        # ── File label ──
        self.lbl_file = QLabel("No session")
        self.lbl_file.setWordWrap(True)
        self.lbl_file.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 9px;")
        layout.addWidget(self.lbl_file)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("background-color: transparent;")
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        self.tiles: list[SensorTile] = []
        for i in range(NUM_SENSORS):
            tile = SensorTile(i)
            row, col = divmod(i, 4)
            grid.addWidget(tile, row, col)
            self.tiles.append(tile)

        return panel

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setFixedHeight(34)
        footer.setStyleSheet(f"background-color: {COLOR_PANEL}; border-top: 1px solid #3A4A5C;")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 0, 12, 0)

        self.lbl_elapsed = QLabel("Elapsed: --:--:--")
        self.lbl_elapsed.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self.lbl_elapsed)

        layout.addStretch()

        self.lbl_rows = QLabel("Rows: 0")
        self.lbl_rows.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self.lbl_rows)

        layout.addSpacing(16)

        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 11px;")
        layout.addWidget(self.lbl_warnings)

        return footer

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color}; color: white;
                border-radius: 6px; font-size: 14px; font-weight: bold;
            }}
            QPushButton:pressed {{ background-color: #1A9C55; }}
            QPushButton:disabled {{ background-color: #3A4A5C; color: #666; }}
        """

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self):
        self.signals.measurement_ready.connect(self._on_measurement)
        self.signals.error_occurred.connect(self._on_error)
        self.signals.init_done.connect(self._on_init_done)

    # ── Sensor initialisation (runs in thread) ────────────────────────────────

    def _init_sensors(self):
        try:
            online = self.sm.initialise()
            self.signals.init_done.emit(online)
        except Exception as e:
            self.signals.error_occurred.emit(f"Init failed: {e}")

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_init_done(self, online: list):
        self._sensor_online = online
        count = sum(online)
        self.lbl_init_status.setText(f"✓ {count}/{NUM_SENSORS} sensors online")
        self.lbl_init_status.setStyleSheet(
            f"color: {COLOR_OK if count == NUM_SENSORS else COLOR_WARNING}; font-size: 11px;"
        )
        for i, tile in enumerate(self.tiles):
            if not online[i]:
                tile.set_offline()
        self.btn_start_stop.setEnabled(count > 0)

    def _on_start_stop(self):
        if not self._running:
            self._start_measurement()
        else:
            self._stop_measurement()

    def _start_measurement(self):
        tensions = [spin.value() for spin in self.tension_spinboxes]
        self.dl.set_tensions(tensions)
        filepath = self.dl.start_session()
        self.lbl_file.setText(filepath.split("/")[-1])

        self._running = True
        self._start_time = datetime.now()
        self._row_count = 0

        self.btn_start_stop.setText("■  Stop")
        self.btn_start_stop.setStyleSheet(self._btn_style(COLOR_ERROR))
        self.combo_interval.setEnabled(False)

        interval = self.combo_interval.currentData()
        self._worker_thread = threading.Thread(
            target=self._measurement_loop, args=(interval,), daemon=True
        )
        self._worker_thread.start()

    def _stop_measurement(self):
        self._running = False
        self.dl.stop_session()
        self.btn_start_stop.setText("▶  Start")
        self.btn_start_stop.setStyleSheet(self._btn_style(COLOR_ACCENT))
        self.combo_interval.setEnabled(True)
        self.lbl_file.setText("Session saved")

    def _on_measurement(self, results: dict):
        """Update UI with latest readings (called in GUI thread)."""
        warnings = []
        for i in range(NUM_SENSORS):
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
        while self._running:
            t0 = time.monotonic()
            try:
                results = self.sm.read_all()
                self.dl.write_row(results)
                self.signals.measurement_ready.emit(results)
            except Exception as e:
                self.signals.error_occurred.emit(str(e))

            # Sleep for remainder of interval
            elapsed = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _tick_clock(self):
        if self._running and self._start_time:
            delta = datetime.now() - self._start_time
            h, rem = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            self.lbl_elapsed.setText(f"Elapsed: {h:02d}:{m:02d}:{s:02d}")

        # Try to get battery level from PiJuice
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
                color = COLOR_OK if pct > 20 else COLOR_WARNING if pct > 10 else COLOR_ERROR
                self.lbl_battery.setStyleSheet(f"color: {color}; font-size: 11px;")
        except Exception:
            pass   # PiJuice not available or not connected

    # ── Safe close ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._running = False
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

    # Force dark background
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(COLOR_BG))
    palette.setColor(QPalette.WindowText,      QColor(COLOR_TEXT))
    palette.setColor(QPalette.Base,            QColor(COLOR_PANEL))
    palette.setColor(QPalette.AlternateBase,   QColor(COLOR_PANEL))
    palette.setColor(QPalette.Text,            QColor(COLOR_TEXT))
    palette.setColor(QPalette.Button,          QColor(COLOR_PANEL))
    palette.setColor(QPalette.ButtonText,      QColor(COLOR_TEXT))
    app.setPalette(palette)

    window = MainWindow(sensor_manager, data_logger)
    window.show()
    sys.exit(app.exec_())
