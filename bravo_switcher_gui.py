#!/usr/bin/env python3
r"""
BravoLED Switcher - GUI
=======================

A small control panel for the BravoLED config switcher. It can:

    - Start / Stop the switcher.
    - Show whether MSFS / SimConnect is connected.
    - Show the currently detected aircraft.
    - Show which config is currently active.
    - Stream the switcher's live log into a scrolling window.

It imports the switcher and runs it in a background thread, capturing its
log output directly. This works the same whether you run this file with
Python or as a bundled .exe. The plain command-line switcher
(bravo_config_switcher.py) still works on its own too.

No extra libraries are needed for the GUI itself -- it uses tkinter, which
ships with Python. The only third-party dependency is SimConnect (used by
the switcher).

USAGE
-----
    From source:  python bravo_switcher_gui.py
    Bundled:      double-click BravoSwitcher.exe
"""

import sys
import queue
import logging
import threading

import tkinter as tk
from tkinter import ttk, scrolledtext

# The switcher module (same folder when running from source; bundled when frozen).
import bravo_config_switcher as switcher

# Colors for a clean, readable dark log panel.
BG      = "#1e1e1e"
PANEL   = "#252526"
FG      = "#d4d4d4"
ACCENT  = "#4ec9b0"
DIM     = "#808080"
WARN    = "#dcdcaa"
ERR     = "#f48771"
OKGREEN = "#6a9955"


class QueueLogHandler(logging.Handler):
    """A logging handler that pushes formatted records onto a queue for the GUI."""
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put(self.format(record))
        except Exception:
            pass


class SwitcherGUI:
    def __init__(self, root):
        self.root = root
        self.thread = None
        self.stop_event = None
        self.line_queue = queue.Queue()

        # Route the switcher's logger into our queue, and NOWHERE else
        # (so a windowed .exe never tries to write to a missing console).
        self.log_handler = QueueLogHandler(self.line_queue)
        self.log_handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.addHandler(self.log_handler)
        root_logger.setLevel(logging.INFO)
        switcher.log.handlers.clear()        # ensure no stray stream handler
        switcher.log.propagate = True

        root.title("BravoLED Config Switcher")
        root.configure(bg=BG)
        root.minsize(620, 460)

        self._build_header()
        self._build_status()
        self._build_log()
        self._build_buttons()

        self.root.after(100, self._drain_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----------------------------------------------------------------- UI
    def _build_header(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(bar, text="BravoLED Config Switcher", bg=BG, fg=FG,
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        self.run_dot = tk.Label(bar, text="\u25cf  Stopped", bg=BG, fg=DIM,
                                 font=("Segoe UI", 10, "bold"))
        self.run_dot.pack(side="right")

    def _build_status(self):
        box = tk.Frame(self.root, bg=PANEL)
        box.pack(fill="x", padx=14, pady=6)

        self.var_conn     = tk.StringVar(value="-")
        self.var_aircraft = tk.StringVar(value="-")
        self.var_config   = tk.StringVar(value="-")

        self._status_row(box, "SimConnect",        self.var_conn,     0)
        self._status_row(box, "Detected aircraft", self.var_aircraft, 1)
        self._status_row(box, "Active config",     self.var_config,   2)
        box.columnconfigure(1, weight=1)

    def _status_row(self, parent, label, var, row):
        tk.Label(parent, text=label, bg=PANEL, fg=DIM,
                 font=("Segoe UI", 9), anchor="w", width=18).grid(
            row=row, column=0, sticky="w", padx=(12, 8), pady=4)
        tk.Label(parent, textvariable=var, bg=PANEL, fg=ACCENT,
                 font=("Consolas", 10), anchor="w").grid(
            row=row, column=1, sticky="we", padx=(0, 12), pady=4)

    def _build_log(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True, padx=14, pady=6)
        tk.Label(wrap, text="Log", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.log_widget = scrolledtext.ScrolledText(
            wrap, bg="#141414", fg=FG, insertbackground=FG,
            font=("Consolas", 9), wrap="word", relief="flat",
            borderwidth=0, height=14)
        self.log_widget.pack(fill="both", expand=True)
        self.log_widget.configure(state="disabled")
        self.log_widget.tag_config("warn", foreground=WARN)
        self.log_widget.tag_config("err",  foreground=ERR)
        self.log_widget.tag_config("ok",   foreground=OKGREEN)

    def _build_buttons(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=14, pady=(4, 12))

        self.btn_start = tk.Button(bar, text="Start", width=12,
                                   command=self.start,
                                   bg="#0e639c", fg="white", relief="flat",
                                   activebackground="#1177bb",
                                   font=("Segoe UI", 10, "bold"))
        self.btn_start.pack(side="left")

        self.btn_stop = tk.Button(bar, text="Stop", width=12,
                                  command=self.stop, state="disabled",
                                  bg="#5a1d1d", fg="white", relief="flat",
                                  activebackground="#7a2626",
                                  font=("Segoe UI", 10, "bold"))
        self.btn_stop.pack(side="left", padx=(8, 0))

        tk.Button(bar, text="Clear log", width=12, command=self._clear_log,
                  bg=PANEL, fg=FG, relief="flat", activebackground="#333",
                  font=("Segoe UI", 10)).pack(side="right")

    # ------------------------------------------------------------- actions
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=switcher.main, args=(self.stop_event,), daemon=True)
        self.thread.start()

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.run_dot.config(text="\u25cf  Running", fg=OKGREEN)
        self.var_conn.set("starting...")

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.run_dot.config(text="\u25cf  Stopped", fg=DIM)
        self.var_conn.set("-")

    # ------------------------------------------------------- queue plumbing
    def _drain_queue(self):
        """Runs on the UI thread: moves queued log lines into the log + status."""
        try:
            while True:
                line = self.line_queue.get_nowait()
                self._log(line)
                self._update_status_from(line)
        except queue.Empty:
            pass

        # If the worker thread ended on its own (e.g. SimConnect missing),
        # reset the buttons.
        if self.thread and not self.thread.is_alive() and self.btn_stop["state"] == "normal":
            self.stop()

        self.root.after(100, self._drain_queue)

    def _update_status_from(self, line):
        low = line.lower()
        if "connected to msfs" in low:
            self.var_conn.set("connected")
        elif "waiting for msfs" in low:
            self.var_conn.set("waiting for sim")
        elif "lost the aircraft title" in low or "sim closed" in low:
            self.var_conn.set("disconnected")
            self.var_aircraft.set("-")
        if "aircraft detected:" in low:
            self.var_aircraft.set(line.split("Aircraft detected:")[-1].strip())
        if "swapped active config ->" in low:
            self.var_config.set(line.split("->")[-1].strip())
        elif "using config_default.json" in low:
            self.var_config.set("config_default.json")

    # ------------------------------------------------------------ log helpers
    def _log(self, text):
        tag = None
        up = text.upper()
        if "ERROR" in up or "CRITICAL" in up:
            tag = "err"
        elif "WARNING" in up or "WARN" in up:
            tag = "warn"
        elif "CONNECTED TO MSFS" in up or "SWAPPED ACTIVE CONFIG" in up:
            tag = "ok"
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n", tag or ())
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _clear_log(self):
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def _on_close(self):
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    SwitcherGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
