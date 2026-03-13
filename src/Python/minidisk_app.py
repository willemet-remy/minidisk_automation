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
    QLabel, QPushButton, QComboBox, QLineEdit, QGridLayout, QGroupBox, QMessageBox
)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QFont

import serial
import serial.tools.list_ports

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
    
    def __init__(self, port, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial_port = None
        self.running = True
        
    def run(self):
        try:
            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=1)
            # Drain input
            self.serial_port.reset_input_buffer()
            
            while self.running:
                if self.serial_port.in_waiting > 0:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
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
                                pass # Corrupted line, ignore
        except Exception as e:
            self.error_occurred.emit(str(e))
            
    def send_command(self, cmd):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.write(f"{cmd}\n".encode('utf-8'))
            
    def stop(self):
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()

class MinidiskApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Slim Minidisk Automation")
        self.resize(800, 600)
        
        self.serial_thread = None
        self.csv_file = None
        self.csv_writer = None
        
        self.history_time = [deque(maxlen=SLOPE_WINDOW_SIZE) for _ in range(NUM_SENSORS)]
        self.history_val  = [deque(maxlen=SLOPE_WINDOW_SIZE) for _ in range(NUM_SENSORS)]
        self.history_slopes = [deque(maxlen=VARIATION_WINDOW) for _ in range(NUM_SENSORS)]
        
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
        
        ctrl_layout.addWidget(QLabel("Plot Name:"), 1, 0)
        self.le_plot = QLineEdit()
        self.le_plot.setText("Plot_A")
        ctrl_layout.addWidget(self.le_plot, 1, 1, 1, 2)
        
        ctrl_layout.addWidget(QLabel("Tension (cmH2O):"), 2, 0)
        self.le_tension = QLineEdit()
        self.le_tension.setText("-2.0")
        ctrl_layout.addWidget(self.le_tension, 2, 1, 1, 2)
        
        ctrl_group.setLayout(ctrl_layout)
        main_layout.addWidget(ctrl_group)
        
        # --- Action Buttons ---
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ START")
        self.btn_start.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px;")
        self.btn_start.clicked.connect(self.start_measurement)
        
        self.btn_pause = QPushButton("⏸ PAUSE")
        self.btn_pause.setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold; padding: 10px;")
        self.btn_pause.clicked.connect(self.pause_measurement)
        self.btn_pause.setEnabled(False)
        
        self.btn_stop = QPushButton("■ STOP && SAVE")
        self.btn_stop.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px;")
        self.btn_stop.clicked.connect(self.stop_measurement)
        self.btn_stop.setEnabled(False)
        
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_stop)
        main_layout.addLayout(btn_layout)
        
        # --- Sensor Readings Grid ---
        sensor_group = QGroupBox("Live Sensor Data")
        self.sensor_grid = QGridLayout()
        
        self.lbl_cm = []
        self.lbl_slope = []
        self.lbl_certitude = []
        
        for i in range(NUM_SENSORS):
            box = QGroupBox(f"Sensor {i+1}")
            bl = QVBoxLayout()
            
            lbl_val = QLabel("0.00 cmH₂O")
            lbl_val.setFont(QFont("Arial", 16, QFont.Bold))
            lbl_val.setAlignment(Qt.AlignCenter)
            self.lbl_cm.append(lbl_val)
            
            lbl_s = QLabel("Slope: --")
            lbl_s.setAlignment(Qt.AlignCenter)
            self.lbl_slope.append(lbl_s)
            
            lbl_c = QLabel("Stability: --")
            lbl_c.setAlignment(Qt.AlignCenter)
            self.lbl_certitude.append(lbl_c)
            
            bl.addWidget(lbl_val)
            bl.addWidget(lbl_s)
            bl.addWidget(lbl_c)
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
            
    def start_measurement(self):
        port = self.cb_ports.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "No COM port selected.")
            return
            
        if self.serial_thread is None or not self.serial_thread.isRunning():
            self.serial_thread = SerialReaderThread(port)
            self.serial_thread.data_received.connect(self.on_data_received)
            self.serial_thread.error_occurred.connect(self.on_serial_error)
            self.serial_thread.start()
            
            # Create CSV
            plot_name = self.le_plot.text().strip()
            tension = self.le_tension.text().strip()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"minidisk_{plot_name}_{timestamp}.csv"
            
            try:
                self.csv_file = open(filename, 'w', newline='')
                self.csv_writer = csv.writer(self.csv_file)
                # Header
                header = ["timestamp_ms", "plot_name", "tension_applied"]
                for i in range(NUM_SENSORS):
                    header.extend([f"S{i+1}_raw_V", f"S{i+1}_pressure_kPa", f"S{i+1}_cmH2O"])
                self.csv_writer.writerow(header)
            except Exception as e:
                QMessageBox.critical(self, "File Error", f"Could not create CSV file: {e}")
                self.serial_thread.stop()
                self.serial_thread = None
                return
                
        # Send START command
        self.serial_thread.send_command("START")
        
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.le_plot.setEnabled(False)
        self.le_tension.setEnabled(False)
        
        for i in range(NUM_SENSORS):
            self.history_time[i].clear()
            self.history_val[i].clear()
            self.history_slopes[i].clear()
            self.lbl_certitude[i].setStyleSheet("color: black;")
            
    def pause_measurement(self):
        if self.btn_pause.text() == "⏸ PAUSE":
            self.serial_thread.send_command("PAUSE")
            self.btn_pause.setText("▶ RESUME")
            self.btn_pause.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 10px;")
        else:
            self.serial_thread.send_command("RESUME")
            self.btn_pause.setText("⏸ PAUSE")
            self.btn_pause.setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold; padding: 10px;")
            
    def stop_measurement(self):
        if self.serial_thread:
            self.serial_thread.send_command("STOP")
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
            
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText("⏸ PAUSE")
        self.le_plot.setEnabled(True)
        self.le_tension.setEnabled(True)
        
        QMessageBox.information(self, "Finished", "Measurement stopped and saved.")
        
    def on_data_received(self, elapsed_ms, raw, p, cm):
        # Update CSV
        if self.csv_writer:
            row = [elapsed_ms, self.le_plot.text(), self.le_tension.text()]
            for i in range(NUM_SENSORS):
                row.extend([raw[i], p[i], cm[i]])
            self.csv_writer.writerow(row)
            self.csv_file.flush()
            
        # Update GUI
        t_sec = elapsed_ms / 1000.0
        for i in range(NUM_SENSORS):
            self.lbl_cm[i].setText(f"{cm[i]:.2f} cmH₂O")
            
            self.history_time[i].append(t_sec)
            self.history_val[i].append(cm[i])
            
            if len(self.history_time[i]) >= SLOPE_WINDOW_SIZE:
                slope, r_sq = calculate_linear_regression(self.history_time[i], self.history_val[i])
                self.lbl_slope[i].setText(f"Slope: {slope:.3f} cm/s")
                
                self.history_slopes[i].append(slope)
                
                if len(self.history_slopes[i]) >= VARIATION_WINDOW:
                    # Calculate std dev of slopes as "variation"
                    mean_slope = sum(self.history_slopes[i]) / VARIATION_WINDOW
                    variance = sum((s - mean_slope)**2 for s in self.history_slopes[i]) / VARIATION_WINDOW
                    std_dev = math.sqrt(variance)
                    
                    self.lbl_certitude[i].setText(f"Var: {std_dev:.4f}  (R²: {r_sq:.2f})")
                    
                    # Highlight if very stable
                    if std_dev < 0.005 and r_sq > 0.90:
                        self.lbl_certitude[i].setStyleSheet("color: #27ae60; font-weight: bold;") # Green
                    else:
                        self.lbl_certitude[i].setStyleSheet("color: #c0392b;") # Red
                
    def on_serial_error(self, err_msg):
        QMessageBox.critical(self, "Serial Error", err_msg)
        self.stop_measurement()

    def closeEvent(self, event):
        self.stop_measurement()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MinidiskApp()
    window.show()
    sys.exit(app.exec_())
