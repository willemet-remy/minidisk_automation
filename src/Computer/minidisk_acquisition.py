"""Desktop acquisition program for the Slimme Minidisk ESP-NOW receiver.

Requires Python 3.10+ and pyserial:  python -m pip install pyserial
"""
import csv
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


class AcquisitionApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Slimme Minidisk acquisition")
        self.minsize(900, 520)
        self.serial_port = None
        self.reader = None
        self.messages = queue.Queue()
        self.sensors = {}
        self.recording = False
        self.paused = False
        self.csv_file = None
        self.csv_writer = None
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.process_messages)
        self.after(1000, self.refresh_status)

    def _build_ui(self):
        top = ttk.Frame(self, padding=10); top.pack(fill="x")
        ttk.Label(top, text="Receiver port:").grid(row=0, column=0, sticky="w")
        self.port = tk.StringVar()
        self.port_box = ttk.Combobox(top, textvariable=self.port, width=22)
        self.port_box.grid(row=0, column=1, padx=5)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).grid(row=0, column=2, padx=3)
        self.connect_button = ttk.Button(top, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=0, column=3, padx=3)
        self.connection_text = tk.StringVar(value="Receiver: disconnected")
        ttk.Label(top, textvariable=self.connection_text).grid(row=0, column=4, padx=14, sticky="w")

        form = ttk.LabelFrame(self, text="Measurement information", padding=10); form.pack(fill="x", padx=10)
        ttk.Label(form, text="Measurement name:").grid(row=0, column=0, sticky="w")
        self.measurement_name = tk.StringVar()
        ttk.Entry(form, textvariable=self.measurement_name, width=30).grid(row=0, column=1, padx=5)
        ttk.Label(form, text="Tension (hPa):").grid(row=0, column=2, padx=(20, 0), sticky="w")
        self.tension = tk.StringVar()
        ttk.Entry(form, textvariable=self.tension, width=12).grid(row=0, column=3, padx=5)
        ttk.Label(form, text="Notes:").grid(row=1, column=0, pady=(8, 0), sticky="w")
        self.notes = tk.StringVar()
        ttk.Entry(form, textvariable=self.notes, width=75).grid(row=1, column=1, columnspan=3, pady=(8, 0), sticky="we")

        controls = ttk.Frame(self, padding=10); controls.pack(fill="x")
        self.start_button = ttk.Button(controls, text="Start measurement", command=self.start_measurement)
        self.start_button.pack(side="left", padx=3)
        self.pause_button = ttk.Button(controls, text="Pause", command=self.pause_measurement, state="disabled")
        self.pause_button.pack(side="left", padx=3)
        self.end_button = ttk.Button(controls, text="End and save CSV", command=self.end_measurement, state="disabled")
        self.end_button.pack(side="left", padx=3)
        self.session_text = tk.StringVar(value="No active measurement")
        ttk.Label(controls, textvariable=self.session_text).pack(side="left", padx=18)

        columns = ("name", "node", "connection", "mode", "distance", "battery", "last_seen")
        self.table = ttk.Treeview(self, columns=columns, show="headings", height=12)
        for column, title, width in [
            ("name", "Fixed sensor name", 170), ("node", "Node ID", 70),
            ("connection", "Connection", 110), ("mode", "Node mode", 105),
            ("distance", "Distance (mm)", 120), ("battery", "Battery (mV)", 115),
            ("last_seen", "Last packet", 180)]:
            self.table.heading(column, text=title); self.table.column(column, width=width, anchor="center")
        self.table.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.table.tag_configure("online", background="#dff0d8")
        self.table.tag_configure("offline", background="#f2dede")
        self.refresh_ports()

    def refresh_ports(self):
        if list_ports is None: return
        ports = [p.device for p in list_ports.comports()]
        self.port_box["values"] = ports
        if ports and not self.port.get(): self.port.set(ports[0])

    def toggle_connection(self):
        if self.serial_port: self.disconnect(); return
        if serial is None:
            messagebox.showerror("Missing package", "Install pyserial: python -m pip install pyserial")
            return
        try:
            self.serial_port = serial.Serial(self.port.get(), 115200, timeout=0.2)
        except Exception as error:
            messagebox.showerror("Cannot connect", str(error)); return
        self.reader = threading.Thread(target=self.read_serial, daemon=True); self.reader.start()
        self.connection_text.set(f"Receiver: connected to {self.port.get()}")
        self.connect_button.config(text="Disconnect")

    def disconnect(self):
        if self.serial_port: self.serial_port.close()
        self.serial_port = None
        self.connection_text.set("Receiver: disconnected")
        self.connect_button.config(text="Connect")

    def read_serial(self):
        while self.serial_port and self.serial_port.is_open:
            try:
                line = self.serial_port.readline().decode("utf-8", errors="replace").strip()
                if line: self.messages.put(line)
            except Exception as error:
                self.messages.put(f"ERROR,serial={error}"); return

    def send_command(self, command):
        if not self.serial_port or not self.serial_port.is_open:
            messagebox.showwarning("Receiver disconnected", "Connect the receiver before sending a command."); return False
        try:
            self.serial_port.write((command + "\n").encode("ascii")); return True
        except Exception as error:
            messagebox.showerror("Command failed", str(error)); return False

    def start_measurement(self):
        if self.recording: return
        if not self.measurement_name.get().strip():
            messagebox.showwarning("Measurement name", "Enter a measurement name."); return
        filename = filedialog.asksaveasfilename(
            title="Save measurement CSV", defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile=f"{self.measurement_name.get().strip()}_{datetime.now():%Y%m%d_%H%M%S}.csv")
        if not filename or not self.send_command("START"): return
        self.csv_file = open(Path(filename), "w", newline="", encoding="utf-8")
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=["timestamp", "measurement_name", "tension_hpa", "notes", "sensor_name", "node_id", "distance_mm", "range_status", "battery_mv", "source_mac"])
        self.csv_writer.writeheader(); self.csv_file.flush()
        self.recording = True; self.start_button.config(state="disabled"); self.pause_button.config(state="normal", text="Pause")
        self.end_button.config(state="normal"); self.session_text.set("Measurement active — START command sent")
        self.paused = False

    def pause_measurement(self):
        if not self.recording: return
        if self.paused:
            if self.send_command("START"):
                self.paused = False; self.pause_button.config(text="Pause")
                self.session_text.set("Resuming — command will apply when nodes next wake")
        elif self.send_command("PAUSE"):
            self.paused = True; self.pause_button.config(text="Resume")
            self.session_text.set("Paused — command will apply when nodes next wake")

    def end_measurement(self):
        if not self.recording: return
        self.send_command("END")
        self.csv_file.close(); self.csv_file = self.csv_writer = None; self.recording = False
        self.paused = False
        self.start_button.config(state="normal"); self.pause_button.config(state="disabled", text="Pause"); self.end_button.config(state="disabled")
        self.session_text.set("Measurement ended and CSV saved")

    @staticmethod
    def parse_data(line):
        if not line.startswith("DATA,"): return None
        values = {}
        for part in line[5:].split(","):
            if "=" in part:
                key, value = part.split("=", 1); values[key] = value
        return values if "name" in values and "node" in values else None

    def process_messages(self):
        while not self.messages.empty():
            line = self.messages.get_nowait(); data = self.parse_data(line)
            if not data: continue
            name = data["name"]; data["last_seen_epoch"] = time.time(); self.sensors[name] = data
            if self.recording and not self.paused and data.get("measuring") == "1" and data.get("distance_mm") != "NA":
                self.csv_writer.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"), "measurement_name": self.measurement_name.get().strip(), "tension_hpa": self.tension.get().strip(), "notes": self.notes.get().strip(), "sensor_name": name, "node_id": data.get("node"), "distance_mm": data.get("distance_mm"), "range_status": data.get("range_status"), "battery_mv": data.get("battery_mv"), "source_mac": data.get("source_mac")})
                self.csv_file.flush()
        self.after(100, self.process_messages)

    def refresh_status(self):
        now = time.time()
        for name, data in self.sensors.items():
            age = now - data["last_seen_epoch"]; online = age < 180  # Increase if sample interval is over one minute.
            values = (name, data.get("node"), "Connected" if online else "Not seen", "Measuring" if data.get("measuring") == "1" else "Paused", data.get("distance_mm"), data.get("battery_mv"), datetime.fromtimestamp(data["last_seen_epoch"]).strftime("%Y-%m-%d %H:%M:%S"))
            if self.table.exists(name): self.table.item(name, values=values, tags=("online" if online else "offline",))
            else: self.table.insert("", "end", iid=name, values=values, tags=("online" if online else "offline",))
        self.after(1000, self.refresh_status)

    def close(self):
        if self.recording and not messagebox.askyesno("Active measurement", "End and save the active CSV?"): return
        if self.recording: self.end_measurement()
        self.disconnect(); self.destroy()


if __name__ == "__main__":
    AcquisitionApp().mainloop()
