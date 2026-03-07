# gui.py — PyQt5 GUI for the Infiltrometer Controller
#
# Layout (800 × 480, touchscreen-optimised):
#
#  ┌──────────────────────────────────────────────────────────────────────────┐
#  │  HEADER: folder name │ #sensors │ interval │ Start All btn │ status/batt │
#  ├──────────────────────────────────────────────────────────────────────────┤
#  │                                                                          │
#  │   SENSOR GRID  (fills all available width, up to 4 columns)              │
#  │   Each tile: sensor name + status dot                                    │
#  │               distance reading (mm)                                      │
#  │               tension spin-box (cmH2O)                                   │
#  │               Start / Stop button (per-sensor)                           │
#  │                                                                          │
#  ├──────────────────────────────────────────────────────────────────────────┤
#  │  FOOTER: elapsed time │ row count │ warnings                             │
#  └──────────────────────────────────────────────────────────────────────────┘

import sys
import os
import logging
import threading
import time
from datetime import datetime
from collections import deque

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QDialog,
    QGridLayout, QVBoxLayout, QHBoxLayout, QFormLayout, QDialogButtonBox,
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
# Virtual on-screen keyboard (touchscreen input)
# ─────────────────────────────────────────────────────────────────────────────
class VirtualKeyboard(QObject):
    """Pop-up QWERTY keyboard dialog for touchscreen text entry."""

    # Emitted when the user confirms; carries the final text string.
    confirmed = pyqtSignal(str)

    # Key layout rows
    _ROWS = [
        list("1234567890"),
        list("qwertyuiop"),
        list("asdfghjkl"),
        list("zxcvbnm"),
    ]

    def __init__(self, initial_text: str = "", parent=None):
        super().__init__(parent)
        self._text = initial_text
        self._dialog = None
        self._lbl = None

    # ── Public ────────────────────────────────────────────────────────────────

    def exec(self) -> str:
        """Show keyboard dialog; returns the entered text (or original on cancel)."""

        dlg = QDialog()
        dlg.setWindowTitle("Enter name")
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        dlg.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_BG};
                border: 2px solid #3A4A5C;
                border-radius: 10px;
            }}
        """)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        # ── Text display ──
        self._lbl = QLabel(self._text or " ")
        self._lbl.setMinimumWidth(340)
        self._lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._lbl.setStyleSheet(f"""
            QLabel {{
                background-color: #1E2A3A;
                color: {COLOR_TEXT};
                border: 1px solid #3A4A5C;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 16px;
                min-height: 32px;
            }}
        """)
        root.addWidget(self._lbl)

        # ── Key rows ──
        btn_css = f"""
            QPushButton {{
                background-color: #2C3E50;
                color: {COLOR_TEXT};
                border: 1px solid #3A4A5C;
                border-radius: 5px;
                font-size: 15px;
                font-weight: bold;
                min-width: 36px;
                min-height: 36px;
                padding: 0;
            }}
            QPushButton:pressed {{ background-color: {COLOR_ACCENT}; }}
        """
        special_css = f"""
            QPushButton {{
                background-color: #1E3A52;
                color: {COLOR_TEXT};
                border: 1px solid #3A4A5C;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
                min-height: 36px;
                padding: 0 10px;
            }}
            QPushButton:pressed {{ background-color: {COLOR_ACCENT}; }}
        """

        for row in self._ROWS:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(4)
            row_layout.addStretch()
            for ch in row:
                btn = QPushButton(ch.upper())
                btn.setStyleSheet(btn_css)
                btn.setFocusPolicy(Qt.NoFocus)
                btn.clicked.connect(lambda _, c=ch: self._press_char(c))
                row_layout.addWidget(btn)
            row_layout.addStretch()
            root.addLayout(row_layout)

        # ── Special keys row ──
        special_row = QHBoxLayout()
        special_row.setSpacing(4)
        special_row.addStretch()

        btn_space = QPushButton("SPACE")
        btn_space.setStyleSheet(special_css)
        btn_space.setMinimumWidth(120)
        btn_space.setFocusPolicy(Qt.NoFocus)
        btn_space.clicked.connect(lambda: self._press_char("_"))
        special_row.addWidget(btn_space)

        btn_back = QPushButton("⌫")
        btn_back.setStyleSheet(special_css)
        btn_back.setFocusPolicy(Qt.NoFocus)
        btn_back.clicked.connect(self._press_backspace)
        special_row.addWidget(btn_back)

        btn_clear = QPushButton("CLR")
        btn_clear.setStyleSheet(special_css)
        btn_clear.setFocusPolicy(Qt.NoFocus)
        btn_clear.clicked.connect(self._press_clear)
        special_row.addWidget(btn_clear)

        btn_ok = QPushButton("✔ OK")
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
                min-height: 36px;
                padding: 0 14px;
            }}
            QPushButton:pressed {{ background-color: #1A9C55; }}
        """)
        btn_ok.setFocusPolicy(Qt.NoFocus)
        btn_ok.clicked.connect(dlg.accept)
        special_row.addWidget(btn_ok)

        btn_cancel = QPushButton("✖")
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ERROR};
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
                min-height: 36px;
                padding: 0 10px;
            }}
            QPushButton:pressed {{ background-color: #A00; }}
        """)
        btn_cancel.setFocusPolicy(Qt.NoFocus)
        btn_cancel.clicked.connect(dlg.reject)
        special_row.addWidget(btn_cancel)

        special_row.addStretch()
        root.addLayout(special_row)

        dlg.adjustSize()
        # Centre on screen
        if dlg.parent():
            geo = dlg.parent().geometry()
            dlg.move(
                geo.x() + (geo.width() - dlg.width()) // 2,
                geo.y() + (geo.height() - dlg.height()) // 2,
            )

        result = dlg.exec_()
        return self._text if result == QDialog.Accepted else None

    # ── Key handlers ──────────────────────────────────────────────────────────

    def _press_char(self, ch: str):
        self._text += ch
        self._refresh_label()

    def _press_backspace(self):
        self._text = self._text[:-1]
        self._refresh_label()

    def _press_clear(self):
        self._text = ""
        self._refresh_label()

    def _refresh_label(self):
        if self._lbl:
            self._lbl.setText(self._text or " ")


class TappableLineEdit(QLineEdit):
    """QLineEdit that opens VirtualKeyboard when tapped on a touchscreen."""

    def __init__(self, *args, main_window_ref=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._main_window_ref = main_window_ref

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        parent = self._main_window_ref
        kb = VirtualKeyboard(initial_text=self.text(), parent=parent)
        result = kb.exec()
        if result is not None:
            self.setText(result)


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
    """A single sensor tile showing tension, distance, and status."""
    toggled = pyqtSignal(int, bool)
    calibrate_requested = pyqtSignal(int)
    
    def __init__(self, idx: int, parent=None):
        super().__init__(parent)
        self.idx = idx
        self._running = False   # local running state for this tile
        self._online = False
        self._tension_value: float = 0.0   # cmH2O, set via +/- buttons
        self._history = deque()
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
        
        self.btn_status = QPushButton("Offline")
        self.btn_status.setFixedSize(50, 18)
        self.btn_status.setStyleSheet(
            "background-color: transparent; color: #555; border: 1px solid #555; border-radius: 4px; font-size: 10px; font-weight: bold;"
        )

        self.lbl_name = QLabel(f"Sensor {self.idx + 1}")
        self.lbl_name.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11px; font-weight: bold; border: none; text-align: left;"
        )

        self.lbl_steady = QLabel("Steady ●")
        self.lbl_steady.setStyleSheet("color: #AAAAAA; font-size: 11px; border: none;")
        self.lbl_steady.setToolTip("Steady State Indicator (Green = Steady, Red = Shifting)")
        
        header.addWidget(self.btn_status)
        header.addSpacing(6)
        header.addWidget(self.lbl_name)
        header.addStretch()
        header.addWidget(self.lbl_steady)
        layout.addLayout(header)

        # ── Distance reading & Unit ──
        dist_layout = QHBoxLayout()
        dist_layout.setSpacing(4)
        dist_layout.addStretch()
        
        self.lbl_distance = QLabel("---")
        self.lbl_distance.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_distance.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 24px; font-weight: bold; border: none;"
        )
        dist_layout.addWidget(self.lbl_distance)

        self.lbl_unit = QLabel("mm")
        self.lbl_unit.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.lbl_unit.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11px; border: none; padding-bottom: 4px;"
        )
        dist_layout.addWidget(self.lbl_unit)
        dist_layout.addStretch()
        
        layout.addLayout(dist_layout)

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
            self.btn_status.setText("Error")
            self.btn_status.setStyleSheet(
                f"background-color: transparent; color: {COLOR_ERROR}; border: 1px solid {COLOR_ERROR}; border-radius: 4px; font-size: 10px; font-weight: bold;"
            )
            self.lbl_distance.setText("OFF")
            self.lbl_distance.setStyleSheet(
                f"color: {COLOR_ERROR}; font-size: 24px; font-weight: bold; border: none;"
            )
            self.lbl_warn.setText("Not detected")

    def set_offline(self):
        self.btn_status.setText("Offline")
        self.btn_status.setStyleSheet(
            "background-color: transparent; color: #555; border: 1px solid #555; border-radius: 4px; font-size: 10px; font-weight: bold;"
        )
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
            btn_text  = "Fault"
        elif low:
            dot_color = COLOR_WARNING
            btn_text  = "Low"
        elif status == 0:
            dot_color = COLOR_OK
            btn_text  = "Online"
        else:
            dot_color = COLOR_WARNING
            btn_text  = "Warn"

        self.btn_status.setText(btn_text)
        self.btn_status.setStyleSheet(
            f"background-color: transparent; color: {dot_color}; border: 1px solid {dot_color}; border-radius: 4px; font-size: 10px; font-weight: bold;"
        )

        # Distance value and Steady State calculation
        if dist is not None:
            self.lbl_distance.setText(str(dist))
            dist_color = COLOR_WARNING if low else COLOR_TEXT
            
            # Steady state tracking
            from config import STEADY_STATE_WINDOW_S, STEADY_STATE_TOLERANCE_MM
            now = time.time()
            self._history.append((now, dist))
            
            # Prune old readings outside the window
            while self._history and now - self._history[0][0] > STEADY_STATE_WINDOW_S:
                self._history.popleft()
            
            # We must have at least enough data spanning > 50% of the window to judge
            if len(self._history) > 2 and (now - self._history[0][0]) >= (STEADY_STATE_WINDOW_S / 2.0):
                dists = [h[1] for h in self._history]
                shift = max(dists) - min(dists)
                if shift <= STEADY_STATE_TOLERANCE_MM:
                    self.lbl_steady.setStyleSheet(f"color: {COLOR_OK}; font-size: 11px; border: none;")
                else:
                    self.lbl_steady.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 11px; border: none;")
            else:
                self.lbl_steady.setStyleSheet("color: #AAAAAA; font-size: 11px; border: none;")
                
        else:
            self.lbl_distance.setText("ERR")
            dist_color = COLOR_ERROR
            self.lbl_steady.setStyleSheet("color: #AAAAAA; font-size: 11px; border: none;")
            
        self.lbl_distance.setStyleSheet(
            f"color: {dist_color}; font-size: 22px; font-weight: bold; border: none;"
        )

        # Warning text
        status_text = data.get('status_text', '')
        if fault:
            self.lbl_warn.setText("⚠ GPIO fault")
        elif low:
            self.lbl_warn.setText("⚠ Low water!")
        elif status != 0 and status_text:
            self.lbl_warn.setText(f"⚠ {status_text}")
        else:
            self.lbl_warn.setText("")

    @property
    def tension_cmH2O(self) -> float:
        return self._tension_value

    @property
    def is_running(self) -> bool:
        return self._running


class CalibrationDialog(QDialog):
    def __init__(self, parent=None, active_sensors=None, preselected_idx=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrate Sensor")
        self.setFixedSize(320, 240)
        self.setStyleSheet(f"background-color: {COLOR_BG}; color: {COLOR_TEXT};")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        
        title = QLabel("Sensor Calibration")
        title.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        form = QFormLayout()
        self.combo_sensor = QComboBox()
        self.combo_sensor.setStyleSheet(f"background-color: {COLOR_PANEL}; color: {COLOR_TEXT}; padding: 4px;")
        
        if active_sensors:
            for idx in active_sensors:
                self.combo_sensor.addItem(f"Sensor {idx + 1}", idx)
            
            if preselected_idx is not None and preselected_idx in active_sensors:
                index = self.combo_sensor.findData(preselected_idx)
                if index >= 0:
                    self.combo_sensor.setCurrentIndex(index)
        
        self.spin_dist = QSpinBox()
        self.spin_dist.setRange(50, 1000)
        self.spin_dist.setValue(100)
        self.spin_dist.setSuffix(" mm")
        self.spin_dist.setStyleSheet(f"background-color: {COLOR_PANEL}; color: {COLOR_TEXT}; padding: 4px;")
        
        form.addRow("Target Sensor:", self.combo_sensor)
        form.addRow("True Distance:", self.spin_dist)
        layout.addLayout(form)
        
        self.lbl_status = QLabel("Place sensor on plexiglass\nover 17% white target.")
        self.lbl_status.setStyleSheet("color: #AAAAAA; font-size: 10px; font-style: italic;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_status)
        
        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.button(QDialogButtonBox.Ok).setText("Run Calibration")
        bbox.setStyleSheet(f"QPushButton {{ background-color: {COLOR_PANEL}; color: {COLOR_TEXT}; padding: 6px; border-radius: 4px; border: 1px solid #3A4A5C; }}")
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def get_data(self):
        return self.combo_sensor.currentData(), self.spin_dist.value()


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):

    def __init__(self, sensor_manager, data_logger):
        super().__init__()
        self.sm = sensor_manager
        self.dl = data_logger
        self.signals = Signals()

        self._globally_running = False   # True once sensors are connected & running
        self._sensors_connected = False  # True once init succeeded at least once
        self._worker_thread = None
        self._start_time = None
        self._row_count = 0
        self._battery_tick = 30  # Counter for 30s battery update interval
        self._sensor_online: list[bool] = [False] * MAX_SENSORS
        from config import NUM_SENSORS
        self._num_sensors = NUM_SENSORS  # read from config

        self._setup_window()
        self._build_ui()
        self._connect_signals()

        # Clock timer
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

        # Do NOT auto-init sensors — wait for user to press Start
        log.info("Ready. Set folder name, sensor count, interval, then press ▶ Start All.")

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
        self.edit_folder = TappableLineEdit(main_window_ref=self)
        self.edit_folder.setPlaceholderText("session_name")
        self.edit_folder.setReadOnly(True)   # prevent native keyboard from popping up
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

        layout.addSpacing(6)
        self.btn_usb = QPushButton("🖴")
        self.btn_usb.setCursor(Qt.PointingHandCursor)
        self.btn_usb.setStyleSheet(f"background: transparent; border: none; color: {COLOR_TEXT_DIM}; font-size: 16px;")
        self.btn_usb.setToolTip("Checking USB...")
        self.btn_usb.clicked.connect(self._on_usb_clicked)
        layout.addWidget(self.btn_usb)

        layout.addStretch()

        # ── Global Start All / Stop All (Aligned Right) ──
        self.btn_global = QPushButton("▶  Start All")
        self.btn_global.setFixedSize(120, 38)
        self.btn_global.setEnabled(True)   # always enabled; init happens on press
        self.btn_global.setStyleSheet(self._btn_style(COLOR_START_BTN))
        self.btn_global.clicked.connect(self._on_global_toggle)
        layout.addWidget(self.btn_global)
        
        layout.addSpacing(6)
        
        self.btn_calibrate = QPushButton("🔧 Calibrate")
        self.btn_calibrate.setFixedSize(110, 38)
        self.btn_calibrate.setStyleSheet(self._btn_style("#2C3E50"))
        self.btn_calibrate.clicked.connect(lambda: self._on_calibrate())
        layout.addWidget(self.btn_calibrate)

        layout.addSpacing(10)

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
        
        self.lbl_online_count = QLabel("Online: 0/0")
        self.lbl_online_count.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11px;"
        )
        layout.addWidget(self.lbl_online_count)

        layout.addSpacing(16)

        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px;"
        )
        layout.addWidget(self.lbl_warnings)
        
        layout.addSpacing(16)
        
        self.lbl_battery = QLabel("🔋 ---%")
        self.lbl_battery.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_battery)
        
        layout.addSpacing(16)

        # ── Number of sensors (Touch-friendly +/-) ──
        lbl_n = QLabel("Sensors:")
        lbl_n.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(lbl_n)

        _btn_css = f"""
            QPushButton {{
                background-color: #2C3E50; color: {COLOR_TEXT};
                border: 1px solid #3A4A5C; border-radius: 4px;
                font-size: 16px; font-weight: bold; min-width: 24px; height: 20px;
                padding-bottom: 2px;
            }}
            QPushButton:pressed {{ background-color: #3A4A5C; }}
        """

        self.btn_sensor_minus = QPushButton("−")
        self.btn_sensor_minus.setFixedSize(24, 20)
        self.btn_sensor_minus.setStyleSheet(_btn_css)
        self.btn_sensor_minus.clicked.connect(self._on_sensor_minus)
        layout.addWidget(self.btn_sensor_minus)

        self.lbl_num_sensors = QLabel(str(self._num_sensors))
        self.lbl_num_sensors.setAlignment(Qt.AlignCenter)
        self.lbl_num_sensors.setFixedWidth(16)
        self.lbl_num_sensors.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 11px; font-weight: bold;")
        layout.addWidget(self.lbl_num_sensors)

        self.btn_sensor_plus = QPushButton("+")
        self.btn_sensor_plus.setFixedSize(24, 20)
        self.btn_sensor_plus.setStyleSheet(_btn_css)
        self.btn_sensor_plus.clicked.connect(self._on_sensor_plus)
        layout.addWidget(self.btn_sensor_plus)

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

    def _on_sensor_minus(self):
        if self._globally_running:
            return  # block changes mid-session
        if self._num_sensors > 1:
            self._num_sensors -= 1
            self.lbl_num_sensors.setText(str(self._num_sensors))
            self._on_num_sensors_changed(self._num_sensors)

    def _on_sensor_plus(self):
        if self._globally_running:
            return  # block changes mid-session
        if self._num_sensors < MAX_SENSORS:
            self._num_sensors += 1
            self.lbl_num_sensors.setText(str(self._num_sensors))
            self._on_num_sensors_changed(self._num_sensors)

    def _on_num_sensors_changed(self, value: int):
        self._refresh_tile_visibility()

    # ── Sensor initialisation (runs in thread) ────────────────────────────────────

    def _init_sensors(self):
        """Initialise sensors with live progress sent back to the GUI log panel."""
        def _cb(msg: str):
            pass

        try:
            online = self.sm.initialise(
                num_sensors=self._num_sensors,
                progress_cb=_cb,
            )
            self.signals.init_done.emit(online)
        except Exception as e:
            self.signals.init_done.emit([])


    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_init_done(self, online: list):
        self._sensor_online = online + [False] * (MAX_SENSORS - len(online))
        count = sum(online)
        total = len(online)
        self._sensors_connected = count > 0
        for i, tile in enumerate(self.tiles):
            if i < len(online):
                tile.set_online(online[i])
            else:
                tile.set_online(False)

        if count > 0:
            # Sensors are up — proceed directly into the session
            self._launch_session()
        else:
            # Nothing online — re-enable the button so user can retry
            self.btn_global.setText("▶  Start All")
            self.btn_global.setStyleSheet(self._btn_style(COLOR_START_BTN))
            self.btn_global.setEnabled(True)
            self.combo_interval.setEnabled(True)
            self.btn_sensor_minus.setEnabled(True)
            self.btn_sensor_plus.setEnabled(True)
            self.edit_folder.setEnabled(True)
            if not any(online):
                log.warning("⚠ No sensors detected. Check wiring and press Start All to retry.")

    def _on_global_toggle(self):
        if not self._globally_running:
            # Disable controls and start async init+connect
            self.btn_global.setText("⏳ Connecting…")
            self.btn_global.setEnabled(False)
            self.btn_global.setStyleSheet(self._btn_style(COLOR_TEXT_DIM))
            self.combo_interval.setEnabled(False)
            self.btn_sensor_minus.setEnabled(False)
            self.btn_sensor_plus.setEnabled(False)
            self.edit_folder.setEnabled(False)
            threading.Thread(target=self._init_sensors, daemon=True).start()
        else:
            self._stop_session()

    def _launch_session(self):
        """Start the measurement session (called after sensors are confirmed online)."""
        folder = self.edit_folder.text().strip() or "session"
        tensions = [t.tension_cmH2O for t in self.tiles]
        self.dl.set_tensions(tensions)
        try:
            filepath = self.dl.start_session(folder, self._num_sensors)
        except Exception as e:
            log.error(f"Cannot create session file: {e}")
            self.btn_global.setText("▶  Start All")
            self.btn_global.setStyleSheet(self._btn_style(COLOR_START_BTN))
            self.btn_global.setEnabled(True)
            self.combo_interval.setEnabled(True)
            self.btn_sensor_minus.setEnabled(True)
            self.btn_sensor_plus.setEnabled(True)
            self.edit_folder.setEnabled(True)
            return

        short = filepath.split("/")[-1]
        self.lbl_file.setText(f"…/{os.path.basename(filepath)}")
        log.info(f"Session file: {filepath}")

        self._globally_running = True
        self._start_time = time.time()
        self._row_count = 0

        # Start all tiles
        for tile in self.tiles[:self._num_sensors]:
            tile.set_globally_started(True)

        self.btn_global.setText("■  Stop All")
        self.btn_global.setStyleSheet(self._btn_style(COLOR_STOP_BTN))
        self.btn_global.setEnabled(True)

        interval = self.combo_interval.currentData()
        log.info(f"Measurement started — interval {interval}s")
        self._worker_thread = threading.Thread(
            target=self._measurement_loop, args=(interval,), daemon=True
        )
        self._worker_thread.start()

    def _start_session(self):
        """Legacy alias kept for safety (not used in main flow any more)."""
        self._launch_session()


    def _stop_session(self):
        self._globally_running = False
        self._sensors_connected = False
        self.dl.stop_session()

        for tile in self.tiles:
            tile.set_globally_started(False)
            tile.set_offline()   # reset tile UI to idle state

        self.btn_global.setText("▶  Start All")
        self.btn_global.setStyleSheet(self._btn_style(COLOR_START_BTN))
        self.btn_global.setEnabled(True)
        self.combo_interval.setEnabled(True)
        self.btn_sensor_minus.setEnabled(True)
        self.btn_sensor_plus.setEnabled(True)
        self.edit_folder.setEnabled(True)
        self.lbl_file.setText("Session saved")
        log.info("Session stopped. Sensors disconnected.")

    def _on_calibrate(self, sensor_idx: int = None):
        if self._globally_running:
            QMessageBox.warning(self, "Error", "Cannot calibrate while a measurement session is running! Please click Stop All first.")
            return

        active_sensors = [i for i, s in enumerate(self._sensor_online) if s]
        if not active_sensors:
            QMessageBox.warning(self, "Error", "No sensors are currently online to calibrate. Please press 'Start All' so the system connects to them first, then Stop it to calibrate.")
            return

        dlg = CalibrationDialog(self, active_sensors, preselected_idx=sensor_idx)
        if dlg.exec_() == QDialog.Accepted:
            selected_idx, dist_mm = dlg.get_data()
            def _calib_thread():
                try:
                    log.info(f"🔧 Calibrating Sensor {selected_idx+1} at {dist_mm} mm... (Takes ~5s)")
                    res = self.sm.run_calibration(selected_idx, dist_mm)
                    # We could emit a signal if we wanted to update GUI right away,
                    # but we'll just log it for now
                    if res and "result_offset_mm" in res:
                        log.info(f"  ✓ S{selected_idx+1} Calibrated! Offset={res['result_offset_mm']}mm, Xtalk={res['result_xtalk_kcps']/1000.0:.1f}kcps")
                        self.signals.measurement_ready.emit({}) # trigger a generic UI refresh if needed
                except Exception as e:
                    log.error(f"  ✗ Calibration failed: {e}")
            import threading
            threading.Thread(target=_calib_thread, daemon=True).start()
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
        """Displays error internally instead of generic popups."""
        log.error(msg)

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
                log.error(f"Measurement error: {e}")
                
            elapsed = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _tick_clock(self):
        if self._globally_running and self._start_time:
            delta_sec = time.time() - self._start_time
            h, rem = divmod(int(delta_sec), 3600)
            m, s = divmod(rem, 60)
            self.lbl_elapsed.setText(f"Elapsed: {h:02d}:{m:02d}:{s:02d}")
        
        self._update_online_count()
        
        # Only update battery every 30 seconds to minimize I2C traffic
        self._battery_tick += 1
        
        if self._battery_tick % 5 == 0:
            self._update_usb_status()
            
        if self._battery_tick >= 30:
            self._update_battery()
            self._battery_tick = 0

    def _update_online_count(self):
        active = sum(1 for i in range(self._num_sensors) if getattr(self.tiles[i], '_online', False))
        self.lbl_online_count.setText(f"Online: {active}/{self._num_sensors}")

    def _on_usb_clicked(self):
        if getattr(self, '_usb_mounted_path', None):
            QMessageBox.information(
                self, "USB Connection", 
                f"USB Drive is connected!\nData logs are being written to:\n{self._usb_mounted_path}"
            )
        else:
            QMessageBox.warning(
                self, "USB Connection", 
                "No USB drive detected.\nData logs will be written to internal storage."
            )

    def _update_usb_status(self):
        from config import USB_MOUNT_PATH
        # Check if any folder exists inside the pure mount path (which Pi OS automounts to /media/username/USB_NAME)
        # We can just check if there are subdirectories in the mount path since automount mounts *inside* it
        try:
            self._usb_mounted_path = None
            if os.path.exists(USB_MOUNT_PATH):
                # RPi OS auto-mounts specific drive names inside /media/USER.
                # If there are entries in this dir, a USB is likely plugged in.
                entries = os.listdir(USB_MOUNT_PATH)
                if entries:
                    self._usb_mounted_path = os.path.join(USB_MOUNT_PATH, entries[0])
                    
            if self._usb_mounted_path:
                self.btn_usb.setStyleSheet(f"background: transparent; border: none; color: {COLOR_ACCENT}; font-size: 16px;")
                self.btn_usb.setToolTip("USB Drive Connected (Logs will save to USB)")
            else:
                self.btn_usb.setStyleSheet(f"background: transparent; border: none; color: {COLOR_TEXT_DIM}; font-size: 16px;")
                self.btn_usb.setToolTip("No USB Drive (Logs will save to internal SD card)")
        except Exception:
            pass

    def _update_battery(self):
        try:
            from INA219 import INA219
            from config import INA219_ADDR
            if not hasattr(self, '_ina219'):
                self._ina219 = INA219(addr=INA219_ADDR)
            
            bus_voltage = self._ina219.getBusVoltage_V()
            # Formula from INA219.py example: (V - 3) / 1.2 * 100
            pct = (bus_voltage - 3) / 1.2 * 100
            pct = max(0, min(100, pct))
            
            self.lbl_battery.setText(f"🔋 {pct:3.1f}%")
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
