"""Slimme Minidisk — Field Infiltration Campaign Acquisition App
=============================================================
3-screen workflow for minidisk infiltrometer field campaigns.

Requires Python 3.10+ and:
    python -m pip install pyserial matplotlib
"""

from __future__ import annotations

import csv
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ─────────────────────────────────────────────────────────────────────────────
# Colours used per sensor line in the graph
# ─────────────────────────────────────────────────────────────────────────────
_LINE_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]
_LINE_DASHES = ["-", "--", "-.", ":", (0, (3, 1, 1, 1))]


# ─────────────────────────────────────────────────────────────────────────────
# Shared serial state
# ─────────────────────────────────────────────────────────────────────────────
class SerialBus:
    """Owns the serial port and reader thread; shared across windows."""

    def __init__(self) -> None:
        self.port: Optional[serial.Serial] = None
        self.messages: queue.Queue = queue.Queue()
        self._reader: Optional[threading.Thread] = None

    def connect(self, port_name: str) -> None:
        self.port = serial.Serial(port_name, 115200, timeout=0.2)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def disconnect(self) -> None:
        if self.port:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None

    def send(self, command: str) -> bool:
        if not self.port or not self.port.is_open:
            return False
        try:
            self.port.write((command + "\n").encode("ascii"))
            return True
        except Exception:
            return False

    def is_open(self) -> bool:
        return bool(self.port and self.port.is_open)

    def _read_loop(self) -> None:
        while self.port and self.port.is_open:
            try:
                line = self.port.readline().decode("utf-8", errors="replace").strip()
                if line:
                    self.messages.put(line)
            except Exception:
                return


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def parse_packet(line: str) -> Optional[dict]:
    """Parse a DATA,... or SCAN_NODE,... serial line into a dict."""
    if line.startswith("DATA,"):
        prefix = 5
    elif line.startswith("SCAN_NODE,"):
        prefix = 10
    else:
        return None

    values: dict = {}
    for part in line[prefix:].split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            values[k] = v

    if "name" not in values or "node" not in values:
        return None

    # Normalise zeros from SCAN_NODE responses
    if values.get("distance_mm") == "0":
        values["distance_mm"] = "NA"
    if values.get("battery_mv") == "0":
        values["battery_mv"] = "NA"

    return values


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN 1 — Sensor Selection
# ─────────────────────────────────────────────────────────────────────────────
class SensorSelectionApp(tk.Tk):
    """Main window: connect to receiver, discover sensors, select & start."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Slimme Minidisk — Sensor Selection")
        self.minsize(820, 460)
        self.resizable(True, True)

        self.bus = SerialBus()
        self.sensors: dict = {}               # name → latest packet dict
        self.checked: dict = {}               # name → tk.BooleanVar
        self._measurement_open = False
        self._known_campaigns: list = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._process_messages)
        self.after(1000, self._refresh_table)

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # Connection bar
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Receiver port:").pack(side="left")
        self._port_var = tk.StringVar()
        self._port_box = ttk.Combobox(bar, textvariable=self._port_var, width=20)
        self._port_box.pack(side="left", padx=4)
        ttk.Button(bar, text="Refresh", command=self._refresh_ports).pack(side="left", padx=2)
        self._connect_btn = ttk.Button(bar, text="Connect", command=self._toggle_connection)
        self._connect_btn.pack(side="left", padx=2)
        self._status_var = tk.StringVar(value="Receiver: disconnected")
        ttk.Label(bar, textvariable=self._status_var, foreground="#555").pack(side="left", padx=14)

        # Scan bar
        scan_bar = ttk.Frame(self, padding=(10, 0))
        scan_bar.pack(fill="x")
        ttk.Button(scan_bar, text="🔍  Scan for sensors", command=self._scan).pack(side="right", padx=4, pady=4)
        ttk.Label(scan_bar, text="Click a row to check/uncheck it. Checked sensors are included in the measurement.",
                  foreground="#555").pack(side="left")

        # Sensor table
        frame = ttk.Frame(self, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        cols = ("checked", "name", "node", "connection", "mode", "distance", "battery", "last_seen")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse", height=12)
        for col, title, width, anchor in [
            ("checked",    "✔",              30,  "center"),
            ("name",       "Sensor name",    160, "w"),
            ("node",       "Node ID",         60, "center"),
            ("connection", "Connection",     110, "center"),
            ("mode",       "Mode",            90, "center"),
            ("distance",   "Distance (mm)",  115, "center"),
            ("battery",    "Battery (mV)",   105, "center"),
            ("last_seen",  "Last packet",    160, "center"),
        ]:
            self._tree.heading(col, text=title)
            self._tree.column(col, width=width, anchor=anchor)

        self._tree.tag_configure("online_checked",    background="#c8e6c9")
        self._tree.tag_configure("online_unchecked",  background="#e8f5e9")
        self._tree.tag_configure("offline_checked",   background="#ffcdd2")
        self._tree.tag_configure("offline_unchecked", background="#f5f5f5", foreground="#999")
        self._tree.bind("<ButtonRelease-1>", self._on_row_click)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        # Bottom bar
        bottom = ttk.Frame(self, padding=(10, 8))
        bottom.pack(fill="x")
        self._start_btn = ttk.Button(
            bottom, text="▶  Start measurement with selected sensors",
            command=self._open_campaign_dialog, state="disabled"
        )
        self._start_btn.pack(side="right")
        self._hint_var = tk.StringVar(value="Connect the receiver, then scan for sensors.")
        ttk.Label(bottom, textvariable=self._hint_var, foreground="#555").pack(side="left")

        self._refresh_ports()

    # ── Port / connection ────────────────────────────────────────────────────
    def _refresh_ports(self) -> None:
        if list_ports is None:
            return
        ports = [p.device for p in list_ports.comports()]
        self._port_box["values"] = ports
        if ports and not self._port_var.get():
            self._port_var.set(ports[0])

    def _toggle_connection(self) -> None:
        if self.bus.is_open():
            self.bus.disconnect()
            self._status_var.set("Receiver: disconnected")
            self._connect_btn.config(text="Connect")
            return
        if serial is None:
            messagebox.showerror("Missing package", "Install pyserial:\n  python -m pip install pyserial")
            return
        try:
            self.bus.connect(self._port_var.get())
        except Exception as exc:
            messagebox.showerror("Connection error", str(exc))
            return
        self._status_var.set(f"Receiver: connected to {self._port_var.get()}")
        self._connect_btn.config(text="Disconnect")
        self.after(500, self._scan)

    # ── Scan / message loop ──────────────────────────────────────────────────
    def _scan(self) -> None:
        if not self.bus.is_open():
            messagebox.showwarning("Not connected", "Connect to the receiver first.")
            return
        self.bus.send("SCAN")
        self._hint_var.set("Scanning for wireless sensors…")

    def _process_messages(self) -> None:
        while not self.bus.messages.empty():
            line = self.bus.messages.get_nowait()
            data = parse_packet(line)
            if data:
                name = data["name"]
                data["last_seen_epoch"] = time.time()
                self.sensors[name] = data
                if name not in self.checked:
                    self.checked[name] = tk.BooleanVar(value=True)
        self._update_start_button()
        self.after(200, self._process_messages)

    # ── Table ────────────────────────────────────────────────────────────────
    def _on_row_click(self, _event: tk.Event) -> None:
        selected = self._tree.focus()
        if selected and selected in self.checked:
            var = self.checked[selected]
            var.set(not var.get())
            self._refresh_table()

    def _refresh_table(self) -> None:
        now = time.time()
        for name, data in self.sensors.items():
            age = now - data.get("last_seen_epoch", 0)
            online = age < 30
            checked = self.checked.get(name, tk.BooleanVar(value=True)).get()
            if online and checked:
                tag = "online_checked"
            elif online:
                tag = "online_unchecked"
            elif checked:
                tag = "offline_checked"
            else:
                tag = "offline_unchecked"
            values = (
                "☑" if checked else "☐",
                name,
                data.get("node", "?"),
                "● Connected" if online else "✗ Not seen",
                "Measuring" if data.get("measuring") == "1" else "Standby",
                data.get("distance_mm", "NA"),
                data.get("battery_mv", "NA"),
                datetime.fromtimestamp(data["last_seen_epoch"]).strftime("%H:%M:%S"),
            )
            if self._tree.exists(name):
                self._tree.item(name, values=values, tags=(tag,))
            else:
                self._tree.insert("", "end", iid=name, values=values, tags=(tag,))
        self._update_start_button()
        self.after(1000, self._refresh_table)

    def _update_start_button(self) -> None:
        any_checked = any(v.get() for v in self.checked.values())
        state = "normal" if (any_checked and not self._measurement_open) else "disabled"
        self._start_btn.config(state=state)
        if self._measurement_open:
            self._hint_var.set("Measurement in progress — close the measurement window first.")
        elif any_checked:
            n = sum(v.get() for v in self.checked.values())
            self._hint_var.set(f"{n} sensor(s) selected. Click 'Start measurement' to begin.")
        else:
            self._hint_var.set("Check at least one sensor to start a measurement.")

    # ── Launch campaign dialog ───────────────────────────────────────────────
    def _open_campaign_dialog(self) -> None:
        selected = [name for name, var in self.checked.items() if var.get()]
        if not selected:
            messagebox.showwarning("No sensors", "Check at least one sensor.")
            return
        CampaignDialog(self, selected, self._known_campaigns, self.bus, self.sensors)

    def open_measurement(self, campaign: str, location: str, notes: str,
                          sensors: list) -> None:
        if campaign not in self._known_campaigns:
            self._known_campaigns.append(campaign)
        self._measurement_open = True
        self._start_btn.config(state="disabled")
        win = MeasurementWindow(self, campaign, location, notes, sensors, self.bus, self.sensors)
        win.on_close_callback = self._on_measurement_closed

    def _on_measurement_closed(self) -> None:
        self._measurement_open = False
        self._update_start_button()

    # ── Close ────────────────────────────────────────────────────────────────
    def _on_close(self) -> None:
        if self._measurement_open:
            if not messagebox.askyesno("Measurement active",
                                        "A measurement is still running. End it and close?"):
                return
        self.bus.disconnect()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN 2 — Campaign / Location Dialog
# ─────────────────────────────────────────────────────────────────────────────
class CampaignDialog(tk.Toplevel):
    """Popup: enter campaign name (remembered), location, notes → open Screen 3."""

    def __init__(self, parent: SensorSelectionApp, sensors: list,
                 known_campaigns: list, bus: SerialBus,
                 sensor_data: dict) -> None:
        super().__init__(parent)
        self.title("New Measurement")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self._parent = parent
        self._sensors = sensors
        self._known_campaigns = known_campaigns
        self._bus = bus
        self._sensor_data = sensor_data

        self._build_ui()
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
        self._campaign_box.focus_set()

    def _build_ui(self) -> None:
        pad = {"padx": 14, "pady": 6}
        form = ttk.Frame(self, padding=20)
        form.pack()

        ttk.Label(form, text="Campaign name:", anchor="e", width=18).grid(
            row=0, column=0, sticky="e", **pad)
        self._campaign_var = tk.StringVar(
            value=self._known_campaigns[-1] if self._known_campaigns else "")
        self._campaign_box = ttk.Combobox(form, textvariable=self._campaign_var,
                                           values=self._known_campaigns, width=32)
        self._campaign_box.grid(row=0, column=1, sticky="we", **pad)

        ttk.Label(form, text="Location / spot:", anchor="e", width=18).grid(
            row=1, column=0, sticky="e", **pad)
        self._location_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._location_var, width=34).grid(
            row=1, column=1, sticky="we", **pad)

        ttk.Label(form, text="Notes (optional):", anchor="e", width=18).grid(
            row=2, column=0, sticky="e", **pad)
        self._notes_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._notes_var, width=34).grid(
            row=2, column=1, sticky="we", **pad)

        ttk.Label(form, text="Selected sensors:", anchor="e", width=18).grid(
            row=3, column=0, sticky="ne", **pad)
        sensors_text = "\n".join(f"• {s}" for s in self._sensors)
        ttk.Label(form, text=sensors_text, justify="left",
                  foreground="#1f77b4").grid(row=3, column=1, sticky="w", **pad)

        ttk.Separator(form, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="we", pady=8)

        btn_row = ttk.Frame(form)
        btn_row.grid(row=5, column=0, columnspan=2)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(btn_row, text="OK  ▶", command=self._ok).pack(side="left", padx=6)

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())

    def _ok(self) -> None:
        campaign = self._campaign_var.get().strip()
        location = self._location_var.get().strip()
        notes = self._notes_var.get().strip()
        if not campaign:
            messagebox.showwarning("Campaign name", "Please enter a campaign name.", parent=self)
            return
        if not location:
            messagebox.showwarning("Location", "Please enter a location / spot name.", parent=self)
            return
        self.destroy()
        self._parent.open_measurement(campaign, location, notes, self._sensors)


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN 3 — Live Measurement Graph Window
# ─────────────────────────────────────────────────────────────────────────────
class MeasurementWindow(tk.Toplevel):
    """Live graph window: one graph per sensor, rich status row, measures-only plotting."""

    def __init__(self, parent, campaign, location, notes, sensor_names, bus, sensor_data):
        super().__init__(parent)
        self.title(f"Measurement — {campaign} / {location}")
        self.minsize(920, 600)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._parent = parent
        self._campaign = campaign
        self._location = location
        self._notes = notes
        self._sensor_names = sensor_names
        self._bus = bus
        self._shared_sensor_data = sensor_data
        self.on_close_callback = lambda: None

        self._start_time = time.time()
        self._ended = False
        self._csv_file = None
        self._csv_writer = None
        self._csv_path = None

        # Per-sensor state dict
        self._sensor_state = {}
        for i, name in enumerate(sensor_names):
            self._sensor_state[name] = {
                "times": [],            # elapsed-s list — only current measuring session
                "distances": [],        # mm list — only current measuring session
                "tension_var": tk.StringVar(value="0"),
                "was_measuring": False, # used to detect standby<->measuring transitions
                "last_distance": "—",
                "last_seen": 0.0,
                "last_node_id": "?",
                "last_battery": "NA",
                "last_mode": "Standby",
                "color": _LINE_COLORS[i % len(_LINE_COLORS)],
                "sv_mode": None,        # tk.StringVar for mode label
                "sv_dist": None,        # tk.StringVar for distance label
                "sv_batt": None,        # tk.StringVar for battery label
                "sv_age":  None,        # tk.StringVar for last-packet-age label
                "ax": None,             # matplotlib Axes
                "line": None,           # matplotlib Line2D
                "canvas": None,         # FigureCanvasTkAgg
            }

        self._open_csv()
        if self._csv_file is None:
            self.on_close_callback()
            self.destroy()
            return

        self._build_ui()
        self.after(200, self._process_messages)
        self.after(1000, self._update_display)
        self.after(1000, self._update_elapsed)

    # ── CSV ──────────────────────────────────────────────────────────────────
    def _open_csv(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        def safe(s): return s.replace(" ", "_").replace("/", "-")
        filename = f"{safe(self._campaign)}_{safe(self._location)}_{timestamp}.csv"
        path_str = filedialog.asksaveasfilename(
            parent=self, title="Save measurement CSV", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")], initialfile=filename)
        if not path_str:
            return
        self._csv_path = Path(path_str)
        self._csv_file = open(self._csv_path, "w", newline="", encoding="utf-8")
        fieldnames = ["timestamp", "campaign", "location", "notes",
                      "sensor_name", "node_id", "distance_mm", "range_status",
                      "tension_cm_h2o", "battery_mv", "source_mac"]
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=fieldnames)
        self._csv_writer.writeheader()
        self._csv_file.flush()

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Fixed header
        hdr = ttk.Frame(self, padding=(12, 6))
        hdr.pack(fill="x", side="top")
        ttk.Label(hdr, text=f"Campaign: {self._campaign}", font=("", 10, "bold")).pack(side="left")
        ttk.Label(hdr, text=f"  |  Location: {self._location}").pack(side="left")
        if self._notes:
            ttk.Label(hdr, text=f"  |  Notes: {self._notes}", foreground="#555").pack(side="left")
        self._elapsed_var = tk.StringVar(value="00:00:00")
        ttk.Label(hdr, textvariable=self._elapsed_var, foreground="#1565C0",
                  font=("", 10, "bold")).pack(side="right")
        ttk.Label(hdr, text="Elapsed: ").pack(side="right")

        # Fixed bottom bar
        bottom = ttk.Frame(self, padding=(10, 6))
        bottom.pack(fill="x", side="bottom")
        self._end_btn = ttk.Button(bottom, text="⏹  End measurement & save CSV",
                                   command=self._end_measurement)
        self._end_btn.pack(side="right")
        ttk.Label(bottom, text="Graphs show only the current measuring session. "
                  "All data is always saved to CSV.", foreground="#888").pack(side="left")
        ttk.Separator(self, orient="horizontal").pack(fill="x", side="bottom")

        # Scrollable content area
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, side="top")
        vscroll = ttk.Scrollbar(outer, orient="vertical")
        vscroll.pack(side="right", fill="y")
        self._scroll_canvas = tk.Canvas(outer, yscrollcommand=vscroll.set, highlightthickness=0)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        vscroll.config(command=self._scroll_canvas.yview)
        self._content = ttk.Frame(self._scroll_canvas)
        self._content_id = self._scroll_canvas.create_window((0, 0), window=self._content, anchor="nw")
        self._content.bind("<Configure>", lambda e: self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all")))
        self._scroll_canvas.bind("<Configure>", lambda e: self._scroll_canvas.itemconfig(
            self._content_id, width=e.width))
        self._scroll_canvas.bind_all("<MouseWheel>",
            lambda e: self._scroll_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        if not HAS_MATPLOTLIB:
            ttk.Label(self._content,
                      text="⚠  matplotlib not installed.\n  python -m pip install matplotlib",
                      foreground="red", font=("", 11)).pack(padx=20, pady=20)

        for name in self._sensor_names:
            self._build_sensor_panel(name)

    def _build_sensor_panel(self, name):
        state = self._sensor_state[name]
        color = state["color"]

        panel = ttk.LabelFrame(self._content, padding=(8, 6))
        panel.pack(fill="x", padx=10, pady=6, expand=True)

        # Status row
        sr = ttk.Frame(panel)
        sr.pack(fill="x")

        tk.Label(sr, text="■", fg=color, font=("", 16, "bold")).pack(side="left", padx=(0, 6))
        ttk.Label(sr, text=name, font=("", 10, "bold"), width=18, anchor="w").pack(side="left")

        ttk.Label(sr, text="Node:", foreground="#777").pack(side="left", padx=(10, 2))
        sv_node = tk.StringVar(value="?")
        ttk.Label(sr, textvariable=sv_node, foreground="#333", width=4).pack(side="left")
        state["sv_node"] = sv_node

        sv_mode = tk.StringVar(value="⬜ Waiting")
        state["sv_mode"] = sv_mode
        ttk.Label(sr, textvariable=sv_mode, width=16, anchor="w").pack(side="left", padx=(12, 0))

        ttk.Label(sr, text="Distance:", foreground="#777").pack(side="left", padx=(12, 2))
        sv_dist = tk.StringVar(value="—")
        state["sv_dist"] = sv_dist
        ttk.Label(sr, textvariable=sv_dist, width=8, anchor="e", font=("", 9, "bold")).pack(side="left")
        ttk.Label(sr, text="mm", foreground="#777").pack(side="left", padx=(2, 12))

        ttk.Label(sr, text="Battery:", foreground="#777").pack(side="left", padx=(0, 2))
        sv_batt = tk.StringVar(value="NA")
        state["sv_batt"] = sv_batt
        ttk.Label(sr, textvariable=sv_batt, width=6, anchor="e").pack(side="left")
        ttk.Label(sr, text="mV", foreground="#777").pack(side="left", padx=(2, 12))

        ttk.Label(sr, text="Last packet:", foreground="#777").pack(side="left", padx=(0, 2))
        sv_age = tk.StringVar(value="—")
        state["sv_age"] = sv_age
        ttk.Label(sr, textvariable=sv_age, width=12).pack(side="left")

        # Tension — right-aligned
        ttk.Label(sr, text="cm H₂O", foreground="#333").pack(side="right", padx=(0, 6))
        ttk.Entry(sr, textvariable=state["tension_var"], width=7, justify="center").pack(side="right")
        ttk.Label(sr, text="Tension:", foreground="#333", font=("", 9, "bold")).pack(side="right", padx=(10, 2))

        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=(4, 4))

        # Individual graph
        if HAS_MATPLOTLIB:
            fig = Figure(figsize=(7, 2.1), dpi=96)
            ax = fig.add_subplot(111)
            ax.set_xlabel("Elapsed time (s)", fontsize=8)
            ax.set_ylabel("Distance (mm)", fontsize=8)
            ax.tick_params(labelsize=7)
            ax.invert_yaxis()
            ax.grid(True, linestyle="--", alpha=0.4)
            ax.set_title(f"{name} — measuring sessions only",
                         fontsize=8, loc="left", color=color)
            ax.text(0.5, 0.5, "Waiting for measuring mode…",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=9, color="#bbb")
            (line,) = ax.plot([], [], color=color, linewidth=1.8, marker="o", markersize=3)
            fig.tight_layout(pad=0.8)
            canvas = FigureCanvasTkAgg(fig, master=panel)
            canvas.get_tk_widget().pack(fill="x", expand=True)
            canvas.draw()
            state["ax"] = ax
            state["line"] = line
            state["canvas"] = canvas

    # ── Message processing ───────────────────────────────────────────────────
    def _process_messages(self):
        if self._ended:
            return
        while not self._bus.messages.empty():
            raw = self._bus.messages.get_nowait()
            data = parse_packet(raw)
            if not data:
                continue
            name = data["name"]
            if name not in self._sensor_state:
                continue

            state = self._sensor_state[name]
            now = time.time()
            is_measuring = data.get("measuring") == "1"
            dist_str = data.get("distance_mm", "NA")
            was_measuring = state["was_measuring"]

            # Always update metadata
            state["last_seen"] = now
            state["last_node_id"] = data.get("node", "?")
            state["last_battery"] = data.get("battery_mv", "NA")
            state["last_mode"] = "Measuring" if is_measuring else "Standby"

            # Update shared sensor data for Screen 1
            data["last_seen_epoch"] = now
            self._shared_sensor_data[name] = data

            # Detect standby transition → clear graph buffers
            if was_measuring and not is_measuring:
                state["times"].clear()
                state["distances"].clear()
                state["was_measuring"] = False

            elif is_measuring:
                state["was_measuring"] = True
                # Record and plot only valid distances
                if dist_str != "NA":
                    try:
                        dist_mm = int(dist_str)
                    except ValueError:
                        dist_mm = None
                    if dist_mm is not None:
                        elapsed = now - self._start_time
                        state["times"].append(elapsed)
                        state["distances"].append(dist_mm)
                        state["last_distance"] = dist_mm
                        # CSV row
                        if self._csv_writer:
                            self._csv_writer.writerow({
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "campaign": self._campaign,
                                "location": self._location,
                                "notes": self._notes,
                                "sensor_name": name,
                                "node_id": data.get("node", ""),
                                "distance_mm": dist_mm,
                                "range_status": data.get("range_status", ""),
                                "tension_cm_h2o": state["tension_var"].get().strip(),
                                "battery_mv": data.get("battery_mv", ""),
                                "source_mac": data.get("source_mac", ""),
                            })
                            self._csv_file.flush()

        self.after(200, self._process_messages)

    # ── Display update (labels + graphs every 1 s) ───────────────────────────
    def _update_display(self):
        if self._ended:
            return
        now = time.time()
        for name, state in self._sensor_state.items():
            age = (now - state["last_seen"]) if state["last_seen"] else 9999

            sv_node = state.get("sv_node")
            if sv_node:
                sv_node.set(state["last_node_id"])

            sv_mode = state.get("sv_mode")
            if sv_mode:
                if state["last_seen"] == 0.0:
                    sv_mode.set("⬜ Waiting")
                elif state["last_mode"] == "Measuring":
                    sv_mode.set("🟢 Measuring")
                elif age < 30:
                    sv_mode.set("⚪ Standby")
                else:
                    sv_mode.set(f"🔴 Lost ({int(age)}s)")

            sv_dist = state.get("sv_dist")
            if sv_dist:
                d = state["last_distance"]
                sv_dist.set(str(d) if d != "—" else "—")

            sv_batt = state.get("sv_batt")
            if sv_batt:
                sv_batt.set(str(state["last_battery"]))

            sv_age = state.get("sv_age")
            if sv_age:
                if state["last_seen"] == 0.0:
                    sv_age.set("—")
                elif age < 60:
                    sv_age.set(f"{int(age)}s ago")
                else:
                    sv_age.set(datetime.fromtimestamp(state["last_seen"]).strftime("%H:%M:%S"))

            # Per-sensor graph
            if HAS_MATPLOTLIB and state.get("ax") is not None:
                ax = state["ax"]
                line = state["line"]
                canvas = state["canvas"]
                times = state["times"]
                distances = state["distances"]

                if times:
                    ax.texts.clear()
                    line.set_data(times, distances)
                    ax.relim()
                    ax.autoscale_view()
                elif state["last_seen"] > 0 and state["last_mode"] == "Standby":
                    line.set_data([], [])
                    if not ax.texts:
                        ax.text(0.5, 0.5, "Paused — graph cleared\n(data saved in CSV)",
                                transform=ax.transAxes, ha="center", va="center",
                                fontsize=9, color="#bbb")
                    ax.relim()
                    ax.autoscale_view()

                canvas.draw_idle()

        self.after(1000, self._update_display)

    # ── Elapsed timer ─────────────────────────────────────────────────────────
    def _update_elapsed(self):
        if self._ended:
            return
        secs = int(time.time() - self._start_time)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        self._elapsed_var.set(f"{h:02d}:{m:02d}:{s:02d}")
        self.after(1000, self._update_elapsed)

    # ── End / Close ──────────────────────────────────────────────────────────
    def _end_measurement(self):
        if self._ended:
            return
        self._ended = True
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None
        if HAS_MATPLOTLIB:
            for name, state in self._sensor_state.items():
                ax = state.get("ax")
                canvas = state.get("canvas")
                if ax and canvas:
                    ax.set_title(f"{name} — ended", fontsize=8,
                                 loc="left", color=state["color"])
                    canvas.draw()
        self._end_btn.config(text="✖  Close", command=self._on_close)
        if self._csv_path:
            messagebox.showinfo("Measurement saved",
                                f"Data saved to:\n{self._csv_path}", parent=self)

    def _on_close(self):
        if not self._ended:
            if not messagebox.askyesno("End measurement?",
                                       "End the measurement and save CSV before closing?",
                                       parent=self):
                return
            self._end_measurement()
        self.on_close_callback()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not HAS_MATPLOTLIB:
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showwarning(
            "Missing dependency",
            "matplotlib is not installed. The app will run but graphs will not display.\n\n"
            "Install it with:\n    python -m pip install matplotlib"
        )
        _root.destroy()

    app = SensorSelectionApp()
    app.mainloop()
