#!/usr/bin/env python3
r"""
BravoLED Switcher - GUI
=======================

A small control panel for bravo_config_switcher.py. It can:

    - Start / Stop the switcher.
    - Show whether MSFS / SimConnect is connected.
    - Show the currently detected aircraft.
    - Show which config is currently active.
    - Stream the switcher's live log into a scrolling window.

It runs the switcher as a background process and reads its output, so the
plain command-line script keeps working on its own too. No extra libraries
are needed for the GUI itself -- it uses tkinter, which ships with Python.

USAGE
-----
    1. Keep this file in the SAME folder as bravo_config_switcher.py
       (i.e. inside the BravoLED folder).
    2. Make sure the SimConnect library is installed:  pip install SimConnect
    3. Run:  python bravo_switcher_gui.py
       (double-clicking also works if .py is associated with Python; for a
        window with no console, rename it to bravo_switcher_gui.pyw)
"""

import os
import sys
import queue
import threading
import subprocess

import tkinter as tk
from tkinter import ttk, scrolledtext

# --------------------------------------------------------------------------
# Locate the switcher script (expected next to this file).
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
SWITCHER = os.path.join(HERE, "bravo_config_switcher.py")

# Colors for a clean, readable dark log panel.
BG      = "#1e1e1e"
PANEL   = "#252526"
FG      = "#d4d4d4"
ACCENT  = "#4ec9b0"
DIM     = "#808080"
WARN    = "#dcdcaa"
ERR     = "#f48771"
OKGREEN = "#6a9955"


class SwitcherGUI:
    def __init__(self, root):
        self.root = root
        self.proc = None                 # the running subprocess, or None
        self.reader_thread = None
        self.line_queue = queue.Queue()  # log lines from the reader thread

        root.title("BravoLED Config Switcher")
        root.configure(bg=BG)
        root.minsize(620, 460)

        self._build_header()
        self._build_status()
        self._build_log()
        self._build_buttons()

        # Pump the log queue into the UI ~10x/second.
        self.root.after(100, self._drain_queue)
        # Make sure we clean up the subprocess on close.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if not os.path.exists(SWITCHER):
            self._log("ERROR  Could not find bravo_config_switcher.py next to this GUI.")
            self._log("       Put both files in your BravoLED folder.")

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
        self.log = scrolledtext.ScrolledText(
            wrap, bg="#141414", fg=FG, insertbackground=FG,
            font=("Consolas", 9), wrap="word", relief="flat",
            borderwidth=0, height=14)
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        self.log.tag_config("warn", foreground=WARN)
        self.log.tag_config("err",  foreground=ERR)
        self.log.tag_config("ok",   foreground=OKGREEN)

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
        if self.proc is not None:
            return
        if not os.path.exists(SWITCHER):
            self._log("ERROR  bravo_config_switcher.py not found; cannot start.")
            return

        # -u = unbuffered, so log lines arrive immediately. stderr is merged
        # into stdout because Python's logging writes to stderr by default.
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-u", SWITCHER],
                cwd=HERE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self._log("ERROR  Failed to start switcher: %s" % e)
            self.proc = None
            return

        self.reader_thread = threading.Thread(
            target=self._read_output, args=(self.proc,), daemon=True)
        self.reader_thread.start()

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.run_dot.config(text="\u25cf  Running", fg=OKGREEN)
        self.var_conn.set("starting...")

    def stop(self):
        if self.proc is None:
            return
        try:
            self.proc.terminate()
        except Exception:
            pass
        self.proc = None
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.run_dot.config(text="\u25cf  Stopped", fg=DIM)
        self.var_conn.set("-")
        self._log("--- switcher stopped ---")

    # ------------------------------------------------------- output plumbing
    def _read_output(self, proc):
        """Runs in a background thread: pushes each output line onto a queue."""
        try:
            for line in iter(proc.stdout.readline, ""):
                self.line_queue.put(line.rstrip("\n"))
        except Exception:
            pass
        finally:
            self.line_queue.put("__PROCESS_ENDED__")

    def _drain_queue(self):
        """Runs on the UI thread: moves queued lines into the log + status."""
        try:
            while True:
                line = self.line_queue.get_nowait()
                if line == "__PROCESS_ENDED__":
                    if self.proc is not None:
                        self._log("--- switcher process ended ---")
                        self.stop()
                    continue
                self._log(line)
                self._update_status_from(line)
        except queue.Empty:
            pass
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
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self):
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    # Slightly nicer ttk theming where available (harmless if it fails).
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    SwitcherGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
