import sys
import os
import csv
import time
import math
from datetime import datetime
from collections import deque
import threading

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QGridLayout, QGroupBox, QMessageBox,
    QTextEdit
)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QFont, QColor, QTextCursor

import serial
import serial.tools.list_ports
import pyqtgraph as pg

NUM_SENSORS = 6
SLOPE_WINDOW_SIZE = 10  # Calculate slope over the last 10 measurements
VARIATION_WINDOW = 5    # Look at the std dev of the last 5 slopes

def calculate_linear_regression(x, y):
    n = len(x)
    if n < 2: return 0, 0
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xx = sum(xi*xi for xi in x)
    sum_xy = sum(xi*yi for xi, yi in zip(x, y))
    denominator = (n * sum_xx - sum_x**2)
    if denominator == 0: return 0, 0
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    
    # Calculate R-squared
    y_mean = sum_y / n
    ss_tot = sum((yi - y_mean)**2 for yi in y)
    ss_res = sum((yi - (slope*xi + (sum_y - slope*sum_x)/n))**2 for xi, yi in zip(x, y))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    return slope, r_squared

class SerialReaderThread(QThread):
    data_received = pyqtSignal(int, list, list, list) # elapsed_ms, raw[], p[], cm[]
    error_occurred = pyqtSignal(str)
    debug_message = pyqtSignal(str)
    connection_status = pyqtSignal(bool)
    
    def __init__(self, port, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial_port = None
        self.running = True
        
    def run(self):
        try:
            self.debug_message.emit(f"Connecting to {self.port} at {self.baudrate} baud...")
            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=1)
            self.serial_port.reset_input_buffer()
            self.connection_status.emit(True)
            self.debug_message.emit("Successfully connected to USB.")
            
            while self.running:
                if self.serial_port.in_waiting > 0:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        if line.startswith("DATA"):
                            parts = line.split(',')
                            if len(parts) >= 1 + 1 + (NUM_SENSORS * 3): # DATA, ms, [raw, p, cm] * 6
                                try:
                                    elapsed_ms = int(parts[1])
                                    raw = []
                                    p = []
                                    cm = []
                                    idx = 2
                                    for _ in range(NUM_SENSORS):
                                        raw.append(float(parts[idx]))
                                        p.append(float(parts[idx+1]))
                                        cm.append(float(parts[idx+2]))
                                        idx += 3
                                    self.data_received.emit(elapsed_ms, raw, p, cm)
                                except ValueError:
                                    self.debug_message.emit(f"Parse Error on line: {line}")
                        else:
                            self.debug_message.emit(f"Arduino: {line}")
        except Exception as e:
            self.connection_status.emit(False)
            self.error_occurred.emit(str(e))
            self.debug_message.emit(f"Error: {e}")
            
    def send_command(self, cmd):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.write(f"{cmd}\n".encode('utf-8'))
            self.debug_message.emit(f"Tx: {cmd}")
            
    def stop(self):
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.connection_status.emit(False)
        self.debug_message.emit("Disconnected USB.")

class MinidiskApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Slim Minidisk Automation")
        self.resize(900, 750)
        
        self.serial_thread = None
        self.csv_file = None
        self.csv_writer = None
        
        self.history_time = [deque(maxlen=SLOPE_WINDOW_SIZE) for _ in range(NUM_SENSORS)]
        self.history_val  = [deque(maxlen=SLOPE_WINDOW_SIZE) for _ in range(NUM_SENSORS)]
        self.history_slopes = [deque(maxlen=VARIATION_WINDOW) for _ in range(NUM_SENSORS)]
        
        self.pending_observations = [None] * NUM_SENSORS
        
        # Track per-sensor pause state
        self.sensor_paused = [True] * NUM_SENSORS
        self.measurement_active = False
        
        self.init_ui()
        self.refresh_ports()
        
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # --- Top Control Panel ---
        ctrl_group = QGroupBox("Configuration")
        ctrl_layout = QGridLayout()
        
        ctrl_layout.addWidget(QLabel("COM Port:"), 0, 0)
        self.cb_ports = QComboBox()
        ctrl_layout.addWidget(self.cb_ports, 0, 1)
        
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        ctrl_layout.addWidget(self.btn_refresh, 0, 2)
        
        self.btn_connect = QPushButton("Connect USB")
        self.btn_connect.setStyleSheet("font-weight: bold;")
        self.btn_connect.clicked.connect(self.toggle_connection)
        ctrl_layout.addWidget(self.btn_connect, 0, 3)
        
        self.lbl_usb_status = QLabel("Disconnected")
        self.lbl_usb_status.setStyleSheet("color: red; font-weight: bold;")
        ctrl_layout.addWidget(self.lbl_usb_status, 0, 4)
        
        ctrl_layout.addWidget(QLabel("Plot Name:"), 1, 0)
        self.le_plot = QLineEdit()
        self.le_plot.setText("Plot_A")
        ctrl_layout.addWidget(self.le_plot, 1, 1, 1, 4)
        
        ctrl_group.setLayout(ctrl_layout)
        main_layout.addWidget(ctrl_group)
        
        # --- Action Buttons ---
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ START MEASUREMENT")
        self.btn_start.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px;")
        self.btn_start.clicked.connect(self.start_measurement)
        self.btn_start.setEnabled(False) # Require connection first
        
        self.btn_stop = QPushButton("■ STOP && SAVE")
        self.btn_stop.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px;")
        self.btn_stop.clicked.connect(self.stop_measurement)
        self.btn_stop.setEnabled(False)
        
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        main_layout.addLayout(btn_layout)
        
        # --- Sensor Readings Grid ---
        sensor_group = QGroupBox("Live Sensor Data")
        self.sensor_grid = QGridLayout()
        
        self.lbl_cm = []
        self.lbl_slope = []
        self.lbl_certitude = []
        self.btn_sensor_pause = []
        
        self.le_tensions = []
        
        self.plots = []
        self.curves_data = []
        self.curves_reg = []
        
        self.le_observations = []
        self.btn_observations = []
        
        for i in range(NUM_SENSORS):
            box = QGroupBox(f"Sensor {i+1}")
            bl = QVBoxLayout()
            
            # Tension Input for this specific sensor
            tension_layout = QHBoxLayout()
            tension_layout.addWidget(QLabel("Tension:"))
            le_t = QLineEdit("-2.0")
            le_t.setMaximumWidth(60)
            tension_layout.addWidget(le_t)
            tension_layout.addWidget(QLabel("cmH₂O"))
            self.le_tensions.append(le_t)
            bl.addLayout(tension_layout)
            
            # Observation Input
            obs_layout = QHBoxLayout()
            obs_layout.addWidget(QLabel("Observed Height:"))
            le_obs = QLineEdit()
            le_obs.setMaximumWidth(60)
            le_obs.setPlaceholderText("cm")
            obs_layout.addWidget(le_obs)
            
            btn_obs = QPushButton("Log")
            btn_obs.setMaximumWidth(40)
            btn_obs.clicked.connect(lambda checked, idx=i: self.log_observation(idx))
            obs_layout.addWidget(btn_obs)
            
            self.le_observations.append(le_obs)
            self.btn_observations.append(btn_obs)
            bl.addLayout(obs_layout)
            
            # Info row Layout
            info_layout = QHBoxLayout()
            
            lbl_val = QLabel("0.00 cmH₂O")
            lbl_val.setFont(QFont("Arial", 12, QFont.Bold))
            lbl_val.setAlignment(Qt.AlignCenter)
            self.lbl_cm.append(lbl_val)
            info_layout.addWidget(lbl_val)
            
            lbl_s = QLabel("Slope: --")
            lbl_s.setAlignment(Qt.AlignCenter)
            self.lbl_slope.append(lbl_s)
            info_layout.addWidget(lbl_s)
            
            lbl_c = QLabel("Stability: --")
            lbl_c.setAlignment(Qt.AlignCenter)
            self.lbl_certitude.append(lbl_c)
            info_layout.addWidget(lbl_c)
            
            plot = pg.PlotWidget(title=f"S{i+1} H₂O")
            plot.setLabel('left', 'cmH2O')
            plot.setLabel('bottom', 'Time (s)')
            plot.showGrid(x=True, y=True)
            plot.setBackground('w')
            plot.setMinimumHeight(200) # Increased height
            
            curve_data = plot.plot(pen=pg.mkPen('b', width=2), name="Measurement")
            curve_reg = plot.plot(pen=pg.mkPen('r', width=2, style=Qt.DashLine), name="Regression")
            
            self.plots.append(plot)
            self.curves_data.append(curve_data)
            self.curves_reg.append(curve_reg)
            
            btn_sp = QPushButton("Paused")
            btn_sp.setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold;")
            btn_sp.clicked.connect(lambda checked, idx=i: self.toggle_sensor_pause(idx))
            btn_sp.setEnabled(False)
            self.btn_sensor_pause.append(btn_sp)
            
            bl.addLayout(info_layout)
            bl.addWidget(plot)
            bl.addWidget(btn_sp)
            box.setLayout(bl)
            
            row, col = divmod(i, 3)
            self.sensor_grid.addWidget(box, row, col)
            
        sensor_group.setLayout(self.sensor_grid)
        main_layout.addWidget(sensor_group)
        
    def refresh_ports(self):
        self.cb_ports.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.cb_ports.addItem(p.device)
            
    def log_debug(self, msg):
        time_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{time_str}] {msg}")
            
    def toggle_connection(self):
        if self.serial_thread and self.serial_thread.isRunning():
            # Disconnect
            self.stop_measurement() # Stop any active logging
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
            self.btn_connect.setText("Connect USB")
            self.cb_ports.setEnabled(True)
            self.btn_refresh.setEnabled(True)
            self.btn_start.setEnabled(False)
        else:
            # Connect
            port = self.cb_ports.currentText()
            if not port:
                QMessageBox.warning(self, "Error", "No COM port selected.")
                return
                
            self.serial_thread = SerialReaderThread(port)
            self.serial_thread.data_received.connect(self.on_data_received)
            self.serial_thread.error_occurred.connect(self.on_serial_error)
            self.serial_thread.debug_message.connect(self.log_debug)
            self.serial_thread.connection_status.connect(self.on_connection_status)
            self.serial_thread.start()
            
            self.btn_connect.setText("Disconnect")
            self.cb_ports.setEnabled(False)
            self.btn_refresh.setEnabled(False)
            
    def on_connection_status(self, connected):
        if connected:
            self.lbl_usb_status.setText("Connected")
            self.lbl_usb_status.setStyleSheet("color: green; font-weight: bold;")
            self.btn_start.setEnabled(not self.measurement_active)
        else:
            self.lbl_usb_status.setText("Disconnected")
            self.lbl_usb_status.setStyleSheet("color: red; font-weight: bold;")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.btn_connect.setText("Connect USB")
            self.cb_ports.setEnabled(True)
            self.btn_refresh.setEnabled(True)

    def log_observation(self, idx):
        val = self.le_observations[idx].text().strip()
        if val:
            self.pending_observations[idx] = val
            self.le_observations[idx].clear()
            self.log_debug(f"Sensor {idx+1} Manual Observation Logged: {val} cm")

    def toggle_sensor_pause(self, idx):
        self.sensor_paused[idx] = not self.sensor_paused[idx]
        if self.sensor_paused[idx]:
            self.btn_sensor_pause[idx].setText("Paused")
            self.btn_sensor_pause[idx].setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold;")
            self.le_tensions[idx].setEnabled(True)  # Allow editing tension
            self.log_debug(f"Sensor {idx+1} Paused. (Data will be ignored in CSV)")
        else:
            self.btn_sensor_pause[idx].setText("Active")
            self.btn_sensor_pause[idx].setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
            self.le_tensions[idx].setEnabled(False) # Lock tension
            self.log_debug(f"Sensor {idx+1} Resumed.")
            # Clear graph when resuming
            self.history_time[idx].clear()
            self.history_val[idx].clear()
            self.history_slopes[idx].clear()
            self.curves_data[idx].setData([], [])
            self.curves_reg[idx].setData([], [])
            
    def start_measurement(self):
        if not self.serial_thread or not self.serial_thread.isRunning():
            QMessageBox.warning(self, "Error", "Not connected to USB.")
            return
            
        plot_name = self.le_plot.text().strip()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"minidisk_{plot_name}_{timestamp}.csv"
        
        try:
            self.csv_file = open(filename, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            
            # Header
            header = ["timestamp_ms", "plot_name"]
            for i in range(NUM_SENSORS):
                header.extend([f"S{i+1}_tension", f"S{i+1}_raw_V", f"S{i+1}_pressure_kPa", f"S{i+1}_cmH2O", f"S{i+1}_obs_height_cm"])
            self.csv_writer.writerow(header)
            self.log_debug(f"Started Measurement. Logging to: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "File Error", f"Could not create CSV file: {e}")
            return
            
        self.measurement_active = True
        self.serial_thread.send_command("START")
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.le_plot.setEnabled(False)
        
        for i in range(NUM_SENSORS):
            self.btn_sensor_pause[i].setEnabled(True)
            self.pending_observations[i] = None
            self.le_observations[i].clear()
            self.history_time[i].clear()
            self.history_val[i].clear()
            self.history_slopes[i].clear()
            self.curves_data[i].setData([], [])
            self.curves_reg[i].setData([], [])
            self.lbl_certitude[i].setStyleSheet("color: black;")
            
    def stop_measurement(self):
        if self.serial_thread and self.serial_thread.isRunning():
            self.serial_thread.send_command("STOP")
            
        self.measurement_active = False
            
        if self.csv_file:
            saved_name = self.csv_file.name
            self.csv_file.close()
            self.csv_file = None
            self.log_debug(f"CSV file saved and closed: {saved_name}")
            QMessageBox.information(self, "Measurement Saved", f"Measurement successfully stopped and saved to:\n{os.path.abspath(saved_name)}")
            
        self.btn_start.setEnabled(True) # Can start new test without disconnecting USB
        self.btn_stop.setEnabled(False)
        self.le_plot.setEnabled(True)
        
        for i in range(NUM_SENSORS):
            self.le_tensions[i].setEnabled(True)
            self.btn_sensor_pause[i].setEnabled(False)
            
    def on_data_received(self, elapsed_ms, raw, p, cm):
        if not self.measurement_active:
            return
            
        # Update CSV
        if self.csv_writer:
            row = [elapsed_ms, self.le_plot.text()]
            for i in range(NUM_SENSORS):
                tension_val = self.le_tensions[i].text().strip()
                
                obs_val = ""
                if self.pending_observations[i] is not None:
                    obs_val = self.pending_observations[i]
                    self.pending_observations[i] = None
                    
                if self.sensor_paused[i]:
                    row.extend([tension_val, "", "", "", obs_val]) # Blanks for paused sensors
                else:
                    row.extend([tension_val, raw[i], p[i], cm[i], obs_val])
            self.csv_writer.writerow(row)
            self.csv_file.flush()
            
        # Update GUI
        t_sec = elapsed_ms / 1000.0
        for i in range(NUM_SENSORS):
            if self.sensor_paused[i]:
                continue
                
            self.lbl_cm[i].setText(f"{cm[i]:.2f} cmH₂O")
            
            self.history_time[i].append(t_sec)
            self.history_val[i].append(cm[i])
            
            self.curves_data[i].setData(list(self.history_time[i]), list(self.history_val[i]))
            
            if len(self.history_time[i]) >= SLOPE_WINDOW_SIZE:
                slope, r_sq = calculate_linear_regression(self.history_time[i], self.history_val[i])
                self.lbl_slope[i].setText(f"Slope: {slope:.3f} cm/s")
                
                # Draw regression line
                start_x = self.history_time[i][0]
                end_x = self.history_time[i][-1]
                mean_x = sum(self.history_time[i]) / len(self.history_time[i])
                mean_y = sum(self.history_val[i]) / len(self.history_val[i])
                c = mean_y - slope * mean_x
                start_y = slope * start_x + c
                end_y = slope * end_x + c
                self.curves_reg[i].setData([start_x, end_x], [start_y, end_y])
                
                self.history_slopes[i].append(slope)
                
                if len(self.history_slopes[i]) >= VARIATION_WINDOW:
                    mean_slope = sum(self.history_slopes[i]) / VARIATION_WINDOW
                    variance = sum((s - mean_slope)**2 for s in self.history_slopes[i]) / VARIATION_WINDOW
                    std_dev = math.sqrt(variance)
                    
                    self.lbl_certitude[i].setText(f"Var: {std_dev:.4f}  (R²: {r_sq:.2f})")
                    
                    if std_dev < 0.005 and r_sq > 0.90:
                        self.lbl_certitude[i].setStyleSheet("color: #27ae60; font-weight: bold;") # Green
                    else:
                        self.lbl_certitude[i].setStyleSheet("color: #c0392b;") # Red
                
    def on_serial_error(self, err_msg):
        self.log_debug(f"Serial Error: {err_msg}")
        QMessageBox.critical(self, "Serial Error", err_msg)
        self.stop_measurement()

    def closeEvent(self, event):
        self.stop_measurement()
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MinidiskApp()
    window.show()
    sys.exit(app.exec_())
