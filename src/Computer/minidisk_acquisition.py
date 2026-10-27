"""Slimme Minidisk — field infiltration acquisition app
=====================================================

Workflow
--------
1. Plug the USB receiver into the laptop, click *Connect* (green badge = receiver answering).
2. Power the nodes: they appear automatically in the sensor list (live distance shown).
3. Click *New session…*, enter the campaign / location / output folder.
4. In the field, start and stop each node with its button (hold 2 s):
   2 beeps = recording started, 3 beeps = recording stopped.
   Every recorded sample is saved immediately to the session CSV together with the
   tension (cm) currently selected for that sensor. Nodes can also be started/stopped
   from the session window.

Requires Python 3.9+ and:   python -m pip install pyserial matplotlib
"""

from __future__ import annotations

import csv
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - reported in the UI
    serial = None
    list_ports = None

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:  # pragma: no cover - reported in the UI
    HAS_MATPLOTLIB = False


APP_TITLE = "Slimme Minidisk"
SETTINGS_PATH = Path.home() / ".slimme_minidisk.json"
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "SlimmeMinidisk"
TENSION_VALUES = [str(i) for i in range(11)]       # 0 … 10 cm, 1 cm steps
NODE_ONLINE_TIMEOUT_S = 5.0                        # nodes transmit every second
RECEIVER_TIMEOUT_S = 5.0                           # receiver heartbeat every 2 s
COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
          "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]
CSV_FIELDS = ["pc_time", "campaign", "location", "operator", "notes",
              "sensor_name", "node_id", "run", "seq", "time_s",
              "distance_mm", "valid", "range_status", "n_avg", "tension_cm"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception:
        pass


def fmt_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text.strip()) or "session"


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_line(line: str) -> tuple[str, dict]:
    """'DATA,node=1,name=X' -> ('DATA', {'node': '1', 'name': 'X'}). Lines starting with # are ignored."""
    if not line or line.startswith("#"):
        return "", {}
    kind, _, rest = line.partition(",")
    fields: dict[str, str] = {}
    for part in rest.split(","):
        key, sep, value = part.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    return kind.strip(), fields


def open_folder(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showerror("Open folder", str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Serial link (background thread, never blocks the UI, auto-reconnects)
# ─────────────────────────────────────────────────────────────────────────────
class SerialLink:
    def __init__(self) -> None:
        self.lines: "queue.Queue[str]" = queue.Queue()
        self.events: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._port = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def is_open(self) -> bool:
        return self._port is not None

    def start(self, port_name: str) -> None:
        self.stop()
        self._stop = threading.Event()
        threading.Thread(target=self._run, args=(port_name, self._stop), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass

    def send(self, text: str) -> bool:
        with self._lock:
            port = self._port
            if port is None:
                return False
            try:
                port.write((text + "\n").encode("ascii"))
                return True
            except Exception:
                return False

    def _run(self, port_name: str, stop: threading.Event) -> None:
        first_attempt = True
        while not stop.is_set():
            try:
                port = serial.Serial(port_name, 115200, timeout=0.3, write_timeout=1.0)
            except Exception as exc:
                if first_attempt:
                    self.events.put(("error", str(exc)))
                    return
                self.events.put(("retry", str(exc)))
                stop.wait(3.0)
                continue
            if stop.is_set():
                port.close()
                return
            with self._lock:
                self._port = port
            first_attempt = False
            self.events.put(("open", port_name))
            buffer = b""
            try:
                while not stop.is_set():
                    chunk = port.read(port.in_waiting or 1)
                    if not chunk:
                        continue
                    buffer += chunk
                    while b"\n" in buffer:
                        raw, buffer = buffer.split(b"\n", 1)
                        line = raw.decode("utf-8", errors="replace").strip()
                        if line:
                            self.lines.put(line)
            except Exception as exc:
                if not stop.is_set():
                    self.events.put(("lost", str(exc)))
            with self._lock:
                if self._port is port:
                    self._port = None
            try:
                port.close()
            except Exception:
                pass
            stop.wait(2.0)  # then try to reconnect to the same port


# ─────────────────────────────────────────────────────────────────────────────
# Node model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class NodeState:
    node_id: int
    name: str
    mac: str = ""
    last_seen: float = 0.0
    recording: bool = False
    run: int = 0
    rec_s: float = 0.0
    distance: Optional[int] = None
    status: str = ""
    sensor_ok: bool = True
    last_seq: int = 0
    received: int = 0
    lost: int = 0

    def age(self) -> float:
        return time.time() - self.last_seen if self.last_seen else 1e9

    def online(self) -> bool:
        return self.age() < NODE_ONLINE_TIMEOUT_S

    def link_text(self) -> str:
        total = self.received + self.lost
        return f"{100.0 * self.received / total:.0f} %" if total else "—"

    def distance_text(self) -> str:
        if not self.sensor_ok:
            return "sensor missing"
        return f"{self.distance} mm" if self.distance is not None else "no echo"


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN 1 — Receiver connection & sensor overview
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE} — Sensors")
        self.geometry("980x520")
        self.minsize(860, 420)

        self.settings = load_settings()
        self.link = SerialLink()
        self.nodes: dict[int, NodeState] = {}
        self.selected: dict[int, bool] = {}
        self.listeners: list[Callable[[str, dict, Optional[NodeState]], None]] = []
        self.session: Optional[SessionWindow] = None

        self._link_state = "idle"          # idle | connecting | open | lost
        self._port_name = ""
        self._opened_at = 0.0
        self._receiver_seen = 0.0
        self._port_map: dict[str, str] = {}

        self._init_styles()
        self._build_ui()
        self._refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._pump)
        self.after(500, self._refresh)

    # ── UI ──────────────────────────────────────────────────────────────────
    def _init_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Big.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=26)

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Receiver", style="Title.TLabel").pack(side="left", padx=(0, 10))
        self._port_var = tk.StringVar()
        self._port_box = ttk.Combobox(top, textvariable=self._port_var, width=42, state="readonly")
        self._port_box.pack(side="left")
        ttk.Button(top, text="↻", width=3, command=self._refresh_ports).pack(side="left", padx=4)
        self._connect_btn = ttk.Button(top, text="Connect", command=self._toggle_connection)
        self._connect_btn.pack(side="left", padx=4)
        self._badge = tk.Label(top, text="⚪ Not connected", font=("Segoe UI", 10, "bold"), fg="#777777")
        self._badge.pack(side="left", padx=14)

        ttk.Separator(self).pack(fill="x", pady=(6, 0))

        head = ttk.Frame(self, padding=(12, 8, 12, 2))
        head.pack(fill="x")
        ttk.Label(head, text="Sensors in range", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="   Nodes appear automatically when powered on. Click a row to (de)select it.",
                  style="Hint.TLabel").pack(side="left")

        frame = ttk.Frame(self, padding=(12, 4))
        frame.pack(fill="both", expand=True)
        columns = ("sel", "name", "id", "signal", "state", "distance", "link", "last")
        self._tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="none")
        for col, title, width, anchor in [
            ("sel", "✔", 36, "center"), ("name", "Sensor", 150, "w"), ("id", "ID", 40, "center"),
            ("signal", "Signal", 120, "center"), ("state", "State", 150, "center"),
            ("distance", "Distance", 120, "center"), ("link", "Link quality", 95, "center"),
            ("last", "Last packet", 95, "center"),
        ]:
            self._tree.heading(col, text=title)
            self._tree.column(col, width=width, anchor=anchor, stretch=col in ("name", "state"))
        self._tree.tag_configure("recording", background="#ffe0e0")
        self._tree.tag_configure("online", background="#e8f5e9")
        self._tree.tag_configure("offline", background="#f2f2f2", foreground="#999999")
        self._tree.bind("<ButtonRelease-1>", self._on_row_click)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")

        bottom = ttk.Frame(self, padding=(12, 8, 12, 12))
        bottom.pack(fill="x")
        self._hint = tk.StringVar(value="Select the receiver port and click Connect.")
        ttk.Label(bottom, textvariable=self._hint, style="Hint.TLabel").pack(side="left")
        self._session_btn = ttk.Button(bottom, text="▶  New measurement session…", style="Accent.TButton",
                                       command=self._open_session_dialog, state="disabled")
        self._session_btn.pack(side="right", ipadx=8, ipady=3)

    # ── Ports & connection ──────────────────────────────────────────────────
    def _refresh_ports(self) -> None:
        if list_ports is None:
            return
        self._port_map.clear()
        values, best = [], None
        for p in sorted(list_ports.comports(), key=lambda p: p.device):
            label = f"{p.device} — {p.description}" if p.description else p.device
            values.append(label)
            self._port_map[label] = p.device
            desc = (p.description or "").lower()
            is_esp = getattr(p, "vid", None) in (0x303A, 0x10C4, 0x1A86) or "usb" in desc
            if best is None and is_esp and "bluetooth" not in desc:
                best = label
        self._port_box["values"] = values
        if self._port_var.get() not in values:
            self._port_var.set(best or (values[0] if values else ""))

    def _toggle_connection(self) -> None:
        if self._link_state != "idle":
            self.link.stop()
            self._link_state = "idle"
            self._connect_btn.config(text="Connect")
            return
        if serial is None:
            messagebox.showerror("Missing package", "Install pyserial:\n\n    python -m pip install pyserial")
            return
        port = self._port_map.get(self._port_var.get(), "")
        if not port:
            messagebox.showwarning("No port", "Select the receiver's serial port first.")
            return
        self._port_name = port
        self._link_state = "connecting"
        self._connect_btn.config(text="Disconnect")
        self.link.start(port)

    def _handle_link_event(self, kind: str, detail: str) -> None:
        if kind == "open":
            self._link_state = "open"
            self._opened_at = time.time()
            self.after(300, lambda: (self.link.send("STATUS"), self.link.send("LIST")))
        elif kind == "error":
            self._link_state = "idle"
            self._connect_btn.config(text="Connect")
            messagebox.showerror("Connection failed",
                                 f"Could not open {self._port_name}:\n\n{detail}\n\n"
                                 "Check the cable and close any other program using the port "
                                 "(Serial Monitor, PlatformIO upload…).")
        elif kind in ("lost", "retry") and self._link_state != "idle":
            self._link_state = "lost"

    # ── Message pump ────────────────────────────────────────────────────────
    def _pump(self) -> None:
        while True:
            try:
                kind, detail = self.link.events.get_nowait()
            except queue.Empty:
                break
            self._handle_link_event(kind, detail)

        for _ in range(5000):
            try:
                line = self.link.lines.get_nowait()
            except queue.Empty:
                break
            kind, fields = parse_line(line)
            if not kind:
                continue
            if kind in ("READY", "HB", "STATUS", "DATA", "NODE", "LIST_END", "ACK"):
                self._receiver_seen = time.time()
            node = None
            if kind == "DATA":
                node = self._update_from_data(fields)
            elif kind == "NODE":
                node = self._update_from_list(fields)
            for listener in list(self.listeners):
                try:
                    listener(kind, fields, node)
                except Exception as exc:  # never let one window break the pump
                    print("listener error:", exc, file=sys.stderr)
        self.after(100, self._pump)

    def _get_node(self, fields: dict) -> Optional[NodeState]:
        node_id = to_int(fields.get("node"))
        if node_id is None:
            return None
        node = self.nodes.get(node_id)
        if node is None:
            node = NodeState(node_id, fields.get("name", f"NODE_{node_id}"))
            self.nodes[node_id] = node
            self.selected.setdefault(node_id, True)
        node.name = fields.get("name", node.name)
        node.mac = fields.get("mac", node.mac)
        return node

    def _update_from_data(self, f: dict) -> Optional[NodeState]:
        node = self._get_node(f)
        if node is None:
            return None
        seq = to_int(f.get("seq"), 0)
        if node.last_seq and seq > node.last_seq + 1:
            node.lost += seq - node.last_seq - 1
        node.last_seq = seq
        node.received += 1
        node.last_seen = time.time()
        node.recording = f.get("rec") == "1"
        node.run = to_int(f.get("run"), node.run)
        node.rec_s = to_int(f.get("rec_ms"), 0) / 1000.0
        node.distance = to_int(f.get("distance_mm"))
        node.status = f.get("status", "")
        node.sensor_ok = f.get("sensor", "1") == "1"
        return node

    def _update_from_list(self, f: dict) -> Optional[NodeState]:
        node = self._get_node(f)
        if node is None:
            return None
        seen = time.time() - to_int(f.get("age_ms"), 0) / 1000.0
        if seen > node.last_seen:
            node.last_seen = seen
            node.recording = f.get("rec") == "1"
            node.run = to_int(f.get("run"), node.run)
            node.distance = to_int(f.get("distance_mm"))
            node.sensor_ok = f.get("sensor", "1") == "1"
        return node

    # ── Periodic refresh ────────────────────────────────────────────────────
    def _refresh(self) -> None:
        self._update_badge()
        self._update_table()
        self._update_controls()
        self.after(1000, self._refresh)

    def receiver_ok(self) -> bool:
        return self._link_state == "open" and time.time() - self._receiver_seen < RECEIVER_TIMEOUT_S

    def _update_badge(self) -> None:
        now = time.time()
        if self._link_state == "idle":
            text, color = "⚪ Not connected", "#777777"
        elif self._link_state == "connecting":
            text, color = f"🟡 Opening {self._port_name}…", "#e65100"
        elif self._link_state == "lost":
            text, color = "🔴 Receiver unplugged — reconnecting…", "#c62828"
        elif self.receiver_ok():
            text, color = f"🟢 Receiver connected ({self._port_name})", "#2e7d32"
        elif now - self._opened_at < 4:
            text, color = "🟡 Waiting for receiver…", "#e65100"
        else:
            text, color = "🟠 No answer — is this the receiver port? Re-flash it?", "#e65100"
        self._badge.config(text=text, fg=color)

    def _update_table(self) -> None:
        for node_id in sorted(self.nodes):
            node = self.nodes[node_id]
            online = node.online()
            if not node.last_seen:
                signal = "—"
            elif online:
                signal = "● In range"
            else:
                signal = f"✗ Lost ({fmt_duration(node.age())})"
            if node.recording:
                state = f"⏺ RECORDING  run {node.run}  {fmt_duration(node.rec_s)}"
            else:
                state = "Standby"
            values = (
                "☑" if self.selected.get(node_id) else "☐",
                node.name, node_id, signal, state,
                node.distance_text() if online else "—",
                node.link_text(),
                datetime.fromtimestamp(node.last_seen).strftime("%H:%M:%S") if node.last_seen else "—",
            )
            tag = "offline" if not online else ("recording" if node.recording else "online")
            iid = str(node_id)
            if self._tree.exists(iid):
                self._tree.item(iid, values=values, tags=(tag,))
            else:
                self._tree.insert("", "end", iid=iid, values=values, tags=(tag,))

    def _update_controls(self) -> None:
        connected = self.receiver_ok()
        session_open = self.session is not None
        self._session_btn.config(state="normal" if connected and not session_open else "disabled")
        if session_open:
            self._hint.set("A session is running — see the session window.")
        elif not connected:
            self._hint.set("Select the receiver port and click Connect.")
        elif not self.nodes:
            self._hint.set("Receiver OK. Power on the nodes — they appear here within a few seconds.")
        else:
            n = sum(1 for v in self.selected.values() if v)
            self._hint.set(f"{len(self.nodes)} sensor(s) found, {n} selected. "
                           "Start a session, then use the node buttons to record.")

    def _on_row_click(self, event: tk.Event) -> None:
        iid = self._tree.identify_row(event.y)
        if iid:
            node_id = int(iid)
            self.selected[node_id] = not self.selected.get(node_id, False)
            self._update_table()
            self._update_controls()

    # ── Session ─────────────────────────────────────────────────────────────
    def _open_session_dialog(self) -> None:
        SessionDialog(self)

    def start_session(self, info: dict) -> None:
        ids = [nid for nid in sorted(self.nodes) if self.selected.get(nid)]
        try:
            self.session = SessionWindow(self, info, ids)
        except OSError as exc:
            messagebox.showerror("Cannot create file", str(exc))
            self.session = None

    def session_closed(self) -> None:
        self.session = None

    def _on_close(self) -> None:
        if self.session is not None:
            if not self.session.end_session(ask=True):
                return
        self.link.stop()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN 2 — New session dialog
# ─────────────────────────────────────────────────────────────────────────────
class SessionDialog(tk.Toplevel):
    def __init__(self, app: MainWindow) -> None:
        super().__init__(app)
        self.app = app
        self.title("New measurement session")
        self.resizable(False, False)
        self.transient(app)

        settings = app.settings
        self._campaign = tk.StringVar(value=settings.get("last_campaign", ""))
        self._location = tk.StringVar()
        self._operator = tk.StringVar(value=settings.get("last_operator", ""))
        self._notes = tk.StringVar()
        self._folder = tk.StringVar(value=settings.get("output_dir", str(DEFAULT_OUTPUT_DIR)))
        self._preview = tk.StringVar()

        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="New measurement session", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        def row(r: int, label: str, widget: tk.Widget) -> None:
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="ew", pady=5)

        self._campaign_box = ttk.Combobox(body, textvariable=self._campaign, width=40,
                                          values=settings.get("campaigns", []))
        row(1, "Campaign *", self._campaign_box)
        row(2, "Location / plot *", ttk.Entry(body, textvariable=self._location, width=42))
        row(3, "Operator", ttk.Entry(body, textvariable=self._operator, width=42))
        row(4, "Notes", ttk.Entry(body, textvariable=self._notes, width=42))
        row(5, "Save in folder", ttk.Entry(body, textvariable=self._folder, width=42))
        ttk.Button(body, text="Browse…", command=self._browse).grid(row=5, column=2, padx=(6, 0))
        ttk.Label(body, textvariable=self._preview, style="Hint.TLabel").grid(
            row=6, column=1, columnspan=2, sticky="w")

        n = sum(1 for v in app.selected.values() if v)
        ttk.Label(body, style="Hint.TLabel", justify="left",
                  text=f"{n} sensor(s) selected. Sensors started with their button during the session\n"
                       "are added automatically.").grid(row=7, column=0, columnspan=3, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Start session", style="Accent.TButton", command=self._ok).pack(side="right")

        for var in (self._campaign, self._location):
            var.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self.geometry(f"+{app.winfo_rootx() + 80}+{app.winfo_rooty() + 60}")
        self.grab_set()
        self._campaign_box.focus_set()

    def _browse(self) -> None:
        folder = filedialog.askdirectory(parent=self, initialdir=self._folder.get() or str(Path.home()))
        if folder:
            self._folder.set(folder)

    def _file_name(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return f"{safe_name(self._campaign.get())}_{safe_name(self._location.get())}_{stamp}.csv"

    def _update_preview(self) -> None:
        self._preview.set(f"File: {self._file_name()}")

    def _ok(self) -> None:
        campaign, location = self._campaign.get().strip(), self._location.get().strip()
        if not campaign or not location:
            messagebox.showwarning("Missing information", "Campaign and location are required.", parent=self)
            return
        folder = Path(self._folder.get().strip() or DEFAULT_OUTPUT_DIR)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder", f"Cannot create folder:\n{exc}", parent=self)
            return
        settings = self.app.settings
        campaigns = [c for c in settings.get("campaigns", []) if c != campaign]
        settings["campaigns"] = [campaign] + campaigns[:19]
        settings["last_campaign"] = campaign
        settings["last_operator"] = self._operator.get().strip()
        settings["output_dir"] = str(folder)
        save_settings(settings)
        info = {"campaign": campaign, "location": location, "operator": self._operator.get().strip(),
                "notes": self._notes.get().strip(), "path": folder / self._file_name()}
        self.grab_release()
        self.destroy()
        self.app.start_session(info)


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN 3 — Session: one live card per sensor
# ─────────────────────────────────────────────────────────────────────────────
class SensorCard:
    """Live panel for one node: state, distance, tension selector, remote control and graph."""

    def __init__(self, session: "SessionWindow", parent: ttk.Frame, node: NodeState, color: str) -> None:
        self.session = session
        self.node_id = node.node_id
        self.name = node.name
        self.color = color
        self.recording = False
        self.run = 0
        self.run_samples = 0
        self.total_samples = 0
        self.runs_done = 0
        self.last_t = 0.0
        self.times: list[float] = []
        self.dists: list[int] = []
        self.markers: list[tuple[float, str]] = []
        self.placeholder = "Waiting for recording — hold the node button 2 s"
        self.dirty = True
        self._cmd_sent_at = 0.0

        self.frame = ttk.LabelFrame(parent, text=f"  {node.name}   (ID {node.node_id})  ", padding=(10, 6))
        self.frame.pack(fill="x", padx=10, pady=6)

        left = ttk.Frame(self.frame, width=250)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        top = ttk.Frame(left)
        top.pack(fill="x")
        tk.Label(top, text="■", fg=color, font=("Segoe UI", 16, "bold")).pack(side="left")
        self.pill = tk.Label(top, text="STANDBY", font=("Segoe UI", 9, "bold"), fg="white",
                             bg="#757575", padx=8, pady=2)
        self.pill.pack(side="left", padx=8)

        self.dist_var = tk.StringVar(value="—")
        ttk.Label(left, textvariable=self.dist_var, style="Big.TLabel").pack(anchor="w", pady=(6, 0))
        self.run_var = tk.StringVar(value="No recording yet")
        ttk.Label(left, textvariable=self.run_var).pack(anchor="w")
        self.link_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.link_var, style="Hint.TLabel").pack(anchor="w", pady=(0, 6))

        tension_row = ttk.Frame(left)
        tension_row.pack(fill="x", pady=2)
        ttk.Label(tension_row, text="Tension", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.tension = tk.StringVar(value="0")
        self.tension_box = ttk.Combobox(tension_row, textvariable=self.tension, values=TENSION_VALUES,
                                        width=4, state="readonly", justify="center", font=("Segoe UI", 11))
        self.tension_box.pack(side="left", padx=6)
        ttk.Label(tension_row, text="cm").pack(side="left")
        self.tension_box.bind("<<ComboboxSelected>>", self._on_tension_changed)
        # Mouse wheel over the selector scrolls the page instead of silently changing the tension.
        self.tension_box.bind("<MouseWheel>", lambda e: (session.on_wheel(e), "break")[1])

        self.cmd_btn = ttk.Button(left, text="▶ Start remotely", command=self._remote_toggle)
        self.cmd_btn.pack(anchor="w", pady=(8, 0))

        self.fig = self.ax = self.canvas = None
        if HAS_MATPLOTLIB:
            self.fig = Figure(figsize=(6.4, 2.3), dpi=96)
            self.fig.subplots_adjust(left=0.09, right=0.98, top=0.93, bottom=0.2)
            self.ax = self.fig.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame)
            self.canvas.get_tk_widget().pack(side="left", fill="both", expand=True)
            self.redraw()

    # ── Data ────────────────────────────────────────────────────────────────
    def on_sample(self, node: NodeState, f: dict) -> None:
        recording = f.get("rec") == "1"
        run = to_int(f.get("run"), 0)
        if recording:
            if not self.recording or run != self.run:
                self._start_run(run)
            t = to_int(f.get("rec_ms"), 0) / 1000.0
            dist = to_int(f.get("distance_mm"))
            self.last_t = t
            self.run_samples += 1
            self.total_samples += 1
            if dist is not None:
                self.times.append(t)
                self.dists.append(dist)
            self.session.write_row(node, f, t, dist, self.tension.get())
            self.dirty = True
        elif self.recording:
            self._end_run()

    def _start_run(self, run: int) -> None:
        if self.recording:
            self._end_run()
        self.recording = True
        self.run = run
        self.run_samples = 0
        self.last_t = 0.0
        self.times.clear()
        self.dists.clear()
        self.markers = [(0.0, self.tension.get())]
        self.session.log(f"{self.name}: recording started (run {run}, tension {self.tension.get()} cm)")
        self.dirty = True

    def _end_run(self) -> None:
        self.recording = False
        self.runs_done += 1
        self.session.log(f"{self.name}: run {self.run} stopped — {self.run_samples} samples, "
                         f"{fmt_duration(self.last_t)}")
        self.placeholder = (f"Run {self.run} saved ({self.run_samples} samples, {fmt_duration(self.last_t)}).\n"
                            "Hold the node button 2 s to start a new run.")
        self.times.clear()
        self.dists.clear()
        self.markers.clear()
        self.dirty = True

    def _on_tension_changed(self, _event=None) -> None:
        if self.recording:
            self.markers.append((self.last_t, self.tension.get()))
            self.session.log(f"{self.name}: tension set to {self.tension.get()} cm at {fmt_duration(self.last_t)}")
            self.dirty = True

    def _remote_toggle(self) -> None:
        node = self.session.app.nodes.get(self.node_id)
        recording = node.recording if node else self.recording
        cmd = "STOP" if recording else "START"
        if self.session.app.link.send(f"{cmd} {self.node_id}"):
            self._cmd_sent_at = time.time()
            self.cmd_btn.config(state="disabled", text="Sending…")
        else:
            messagebox.showwarning("Receiver", "Receiver not connected.", parent=self.session)

    # ── Display ─────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        node = self.session.app.nodes.get(self.node_id)
        online = node is not None and node.online()
        if node is None or not node.last_seen:
            self.pill.config(text="NOT SEEN", bg="#9e9e9e")
        elif not online:
            label = "REC · NO SIGNAL" if self.recording else "NO SIGNAL"
            self.pill.config(text=f"{label} {fmt_duration(node.age())}", bg="#ef6c00")
        elif self.recording:
            self.pill.config(text="⏺ RECORDING", bg="#c62828")
        else:
            self.pill.config(text="STANDBY", bg="#757575")

        self.dist_var.set(node.distance_text() if online else "—")
        if self.recording:
            self.run_var.set(f"Run {self.run}  ·  {fmt_duration(self.last_t)}  ·  {self.run_samples} samples")
        elif self.runs_done:
            self.run_var.set(f"{self.runs_done} run(s) saved  ·  {self.total_samples} samples")
        if node is not None and node.last_seen:
            self.link_var.set(f"Last packet {node.age():.0f} s ago  ·  link {node.link_text()}")

        if time.time() - self._cmd_sent_at > 3:
            busy = node.recording if node else self.recording
            self.cmd_btn.config(state="normal" if online else "disabled",
                                text="■ Stop remotely" if busy else "▶ Start remotely")
        if self.dirty:
            self.redraw()

    def redraw(self) -> None:
        self.dirty = False
        if self.ax is None:
            return
        ax = self.ax
        ax.cla()
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.tick_params(labelsize=8)
        ax.set_xlabel("Time since start (s)", fontsize=8)
        ax.set_ylabel("Distance (mm)", fontsize=8)
        if self.times:
            ax.plot(self.times, self.dists, color=self.color, linewidth=1.6, marker="o", markersize=2.5)
            for t, tension in self.markers:
                ax.axvline(t, color="#555555", linestyle="--", linewidth=0.8)
                ax.annotate(f"{tension} cm", xy=(t, 1.0), xycoords=("data", "axes fraction"),
                            xytext=(3, -11), textcoords="offset points", fontsize=7, color="#333333")
            ax.invert_yaxis()   # water level going down = curve going down
        else:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(0.5, 0.5, self.placeholder, transform=ax.transAxes, ha="center", va="center",
                    fontsize=9, color="#999999")
        self.canvas.draw_idle()


class SessionWindow(tk.Toplevel):
    def __init__(self, app: MainWindow, info: dict, node_ids: list[int]) -> None:
        super().__init__(app)
        self.app = app
        self.info = info
        self.path: Path = info["path"]
        self.ended = False
        self.cards: dict[int, SensorCard] = {}
        self.started = time.time()

        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS)
        self._writer.writeheader()
        self._file.flush()
        self.rows = 0

        self.title(f"{APP_TITLE} — {info['campaign']} / {info['location']}")
        self.geometry("1180x800")
        self.minsize(900, 560)
        self._build_ui()
        for node_id in node_ids:
            self._add_card(node_id)
        self.log(f"Session started — saving to {self.path}")

        app.listeners.append(self._on_message)
        self.bind_all("<MouseWheel>", self._on_global_wheel)
        self.protocol("WM_DELETE_WINDOW", lambda: self.end_session(ask=True))
        self.after(1000, self._tick)

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(14, 10, 14, 6))
        header.pack(fill="x")
        ttk.Label(header, text=f"{self.info['campaign']}  ·  {self.info['location']}",
                  style="Title.TLabel").pack(side="left")
        self._elapsed = tk.StringVar(value="00:00")
        ttk.Button(header, text="⏹  End session", style="Accent.TButton",
                   command=lambda: self.end_session(ask=True)).pack(side="right", ipadx=6)
        ttk.Button(header, text="📂 Open folder",
                   command=lambda: open_folder(self.path.parent)).pack(side="right", padx=8)
        ttk.Label(header, textvariable=self._elapsed, font=("Segoe UI", 11, "bold"),
                  foreground="#1565c0").pack(side="right", padx=8)
        ttk.Label(header, text="Session time").pack(side="right")

        info = ttk.Frame(self, padding=(14, 0, 14, 6))
        info.pack(fill="x")
        self._file_var = tk.StringVar()
        ttk.Label(info, textvariable=self._file_var, style="Hint.TLabel").pack(side="left")
        ttk.Label(info, style="Hint.TLabel",
                  text="Start / stop = hold the node button 2 s  (2 beeps = start, 3 beeps = stop)"
                  ).pack(side="right")
        ttk.Separator(self).pack(fill="x")

        # Event log at the bottom
        log_frame = ttk.Frame(self, padding=(14, 4, 14, 8))
        log_frame.pack(fill="x", side="bottom")
        ttk.Label(log_frame, text="Events", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._log = tk.Listbox(log_frame, height=4, font=("Consolas", 9), activestyle="none")
        self._log.pack(fill="x")

        # Scrollable list of sensor cards
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(outer, highlightthickness=0)
        vbar = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._content = ttk.Frame(self._canvas)
        window = self._canvas.create_window((0, 0), window=self._content, anchor="nw")
        self._content.bind("<Configure>",
                           lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(window, width=e.width))
        self._empty = ttk.Label(self._content, style="Hint.TLabel", padding=30,
                                text="No sensor yet. Press and hold the button of a node for 2 s:\n"
                                     "it will appear here and start recording.")
        self._empty.pack()

    def on_wheel(self, event: tk.Event) -> None:
        self._canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_global_wheel(self, event: tk.Event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is not None and str(widget).startswith(str(self._canvas)):
            self.on_wheel(event)

    def _add_card(self, node_id: int) -> SensorCard:
        node = self.app.nodes.get(node_id) or NodeState(node_id, f"NODE_{node_id}")
        if self._empty is not None:
            self._empty.destroy()
            self._empty = None
        card = SensorCard(self, self._content, node, COLORS[len(self.cards) % len(COLORS)])
        self.cards[node_id] = card
        return card

    def log(self, text: str) -> None:
        self._log.insert("end", f"{datetime.now():%H:%M:%S}  {text}")
        self._log.see("end")

    # ── Data ────────────────────────────────────────────────────────────────
    def _on_message(self, kind: str, fields: dict, node: Optional[NodeState]) -> None:
        if self.ended or node is None:
            return
        if kind == "ACK":
            return
        if kind != "DATA":
            return
        card = self.cards.get(node.node_id)
        if card is None:
            if fields.get("rec") != "1":
                return
            card = self._add_card(node.node_id)
            self.log(f"{node.name} joined the session (started with its button)")
        card.on_sample(node, fields)

    def write_row(self, node: NodeState, f: dict, t: float, dist: Optional[int], tension: str) -> None:
        if self.ended:
            return
        self._writer.writerow({
            "pc_time": datetime.now().isoformat(timespec="milliseconds"),
            "campaign": self.info["campaign"], "location": self.info["location"],
            "operator": self.info["operator"], "notes": self.info["notes"],
            "sensor_name": node.name, "node_id": node.node_id, "run": f.get("run", ""),
            "seq": f.get("seq", ""), "time_s": f"{t:.1f}",
            "distance_mm": "" if dist is None else dist, "valid": 0 if dist is None else 1,
            "range_status": f.get("status", ""), "n_avg": f.get("n", ""), "tension_cm": tension,
        })
        self._file.flush()
        self.rows += 1

    def _tick(self) -> None:
        if self.ended:
            return
        self._elapsed.set(fmt_duration(time.time() - self.started))
        self._file_var.set(f"💾 {self.path}   —   {self.rows} rows saved")
        for card in self.cards.values():
            card.refresh()
        self.after(1000, self._tick)

    # ── End ─────────────────────────────────────────────────────────────────
    def end_session(self, ask: bool) -> bool:
        if self.ended:
            return True
        recording = [c for c in self.cards.values() if c.recording]
        if ask:
            if recording:
                names = ", ".join(c.name for c in recording)
                answer = messagebox.askyesnocancel(
                    "End session",
                    f"Still recording: {names}.\n\nStop these nodes remotely before closing?\n"
                    "(No = leave them running; data after closing is not saved.)", parent=self)
                if answer is None:
                    return False
                if answer:
                    for card in recording:
                        self.app.link.send(f"STOP {card.node_id}")
            elif not messagebox.askyesno("End session", "End this session and close the file?", parent=self):
                return False

        self.ended = True
        try:
            self._file.close()
        except Exception:
            pass
        if self._on_message in self.app.listeners:
            self.app.listeners.remove(self._on_message)
        self.unbind_all("<MouseWheel>")
        self.app.session_closed()

        summary = "\n".join(f"  {c.name}: {c.runs_done + (1 if c.recording else 0)} run(s), "
                            f"{c.total_samples} samples" for c in self.cards.values()) or "  (no data)"
        if messagebox.askyesno("Session saved", f"Saved {self.rows} rows to:\n{self.path}\n\n{summary}\n\n"
                                                "Open the folder?", parent=self):
            open_folder(self.path.parent)
        self.destroy()
        return True


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = MainWindow()
    if serial is None:
        messagebox.showerror("Missing package", "pyserial is not installed:\n\n    python -m pip install pyserial")
    elif not HAS_MATPLOTLIB:
        messagebox.showwarning("Missing package",
                               "matplotlib is not installed — graphs are disabled.\n\n"
                               "    python -m pip install matplotlib")
    app.mainloop()
