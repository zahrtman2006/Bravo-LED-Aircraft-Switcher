#!/usr/bin/env python3
r"""
BravoLED Per-Aircraft Config Switcher
=====================================

BravoLED.exe only ever loads ONE file: config.json. It has no built-in
aircraft detection. This script adds that missing feature:

    1. Connects to MSFS via SimConnect and reads the current aircraft TITLE.
    2. Matches that title against a list of rules you define below.
    3. Copies the matching config_<name>.json over the active config.json.
    4. Restarts BravoLED.exe so it reloads the new config.

So you keep a small library of per-aircraft configs, and this script
swaps the right one in automatically whenever you change aircraft.

This file works two ways:
  * Run directly:  python bravo_config_switcher.py   (headless, logs to console)
  * Imported by bravo_switcher_gui.py, which runs main() in a background
    thread and shows the log in a window.

--------------------------------------------------------------------------
FOLDER LAYOUT (everything lives in the BravoLED folder)
--------------------------------------------------------------------------
    Community\BravoLED\
        BravoLED.exe
        config.json            <- ACTIVE config (this script overwrites it)
        config_default.json    <- fallback when nothing matches
        config_tbm930.json     <- your TBM 930 config
        config_c172.json       <- (add as many as you like)
        bravo_config_switcher.py   <- this script

IMPORTANT: config.json gets overwritten by this script. Treat your
config_*.json files as the "source of truth" and never hand-edit
config.json directly once this is running.

--------------------------------------------------------------------------
SETTINGS (settings.json)
--------------------------------------------------------------------------
Aircraft rules and the debug toggle live in settings.json in the BravoLED
folder, so they can be edited from the GUI (and by exe users) without
touching this script. The file looks like:

    {
        "debug": false,
        "rules": [
            {"match": "TBM 930", "config": "config_tbm930.json"}
        ]
    }

Settings are re-read on every poll, so edits take effect live without a
restart. If settings.json is missing it is created with sensible defaults.

DEBUG MODE: when "debug" is true, live SimVar values are printed to the log
every few seconds. Use it to see exactly what MSFS reports for oil pressure,
fuel pressure, etc. so you can tune your config thresholds, then turn it off.
"""

import os
import sys
import time
import json
import shutil
import logging
import subprocess

# --------------------------------------------------------------------------
# CONFIGURATION  --  edit this section to match your setup
# --------------------------------------------------------------------------

def _base_dir():
    """Folder the app actually lives in.
    When bundled with PyInstaller, __file__ points into a temporary
    extraction folder, so we use the real .exe location instead."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__)) or "."

BRAVO_DIR = _base_dir()

EXE_NAME       = "BravoLED.exe"
ACTIVE_CONFIG  = "config.json"           # the file BravoLED actually reads
DEFAULT_CONFIG = "config_default.json"   # fallback when no rule matches

# How often (seconds) to poll the sim for the current aircraft.
POLL_SECONDS = 3

# --------------------------------------------------------------------------
# SETTINGS  (settings.json holds the debug toggle and the aircraft rules)
# --------------------------------------------------------------------------
SETTINGS_FILE = "settings.json"

# Used only to seed settings.json the first time, if it doesn't exist yet.
DEFAULT_RULES = [
    {"match": "TBM 930",         "config": "config_tbm930.json"},
    {"match": "Cessna 172",      "config": "config_c172.json"},
    {"match": "Cessna Skyhawk",  "config": "config_c172.json"},
]


def load_settings():
    """Read settings.json from the BravoLED folder. Returns a dict with at
    least 'debug' (bool) and 'rules' (list of {match, config}) keys. Missing
    or malformed files fall back to defaults rather than crashing.

    Aircraft rules are checked TOP TO BOTTOM; the first rule whose 'match'
    substring appears in the aircraft TITLE wins (case-insensitive), so put
    more specific rules above more general ones."""
    path = full(SETTINGS_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as e:
        log.warning("Could not read %s (%s); using defaults.", SETTINGS_FILE, e)
        data = {}

    if not isinstance(data, dict):
        data = {}
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = list(DEFAULT_RULES)
    return {"debug": bool(data.get("debug", False)), "rules": rules}


def save_settings(settings):
    """Write the settings dict back to settings.json."""
    path = full(SETTINGS_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
        return True
    except OSError as e:
        log.error("Could not write %s: %s", SETTINGS_FILE, e)
        return False


# Which SimVars to print when debug mode is on.
# Add or remove entries to taste -- these match the labels in config.json.
# NOTE: engine vars are indexed (":1" = engine 1). For a multi-engine
# aircraft you could add ":2", ":3", etc. The library reads oil pressure
# natively in Psf and fuel pressure in Psi (shown in the labels below).
DEBUG_WATCH = [
    ("GENERAL ENG OIL PRESSURE:1",  "psf",              "Oil Pressure (eng1)"),
    ("GENERAL ENG OIL PRESSURE:2",  "psf",              "Oil Pressure (eng2)"),
    ("GENERAL ENG OIL PRESSURE:3",  "psf",              "Oil Pressure (eng3)"),
    ("GENERAL ENG OIL PRESSURE:4",  "psf",              "Oil Pressure (eng4)"),
    ("GENERAL ENG FUEL PRESSURE:1", "psi",              "Fuel Pressure (eng1)"),
    ("GENERAL ENG FUEL PRESSURE:2", "psi",              "Fuel Pressure (eng2)"),
    ("GENERAL ENG FUEL PRESSURE:3", "psi",              "Fuel Pressure (eng3)"),
    ("GENERAL ENG FUEL PRESSURE:4", "psi",              "Fuel Pressure (eng4)"),
    ("ENG ON FIRE:1",               "bool",             "Engine 1 Fire"),
    ("ENG ON FIRE:2",               "bool",             "Engine 2 Fire"),
    ("ENG ON FIRE:3",               "bool",             "Engine 3 Fire"),
    ("ENG ON FIRE:4",               "bool",             "Engine 4 Fire"),
    ("APU ON FIRE DETECTED",        "bool",             "APU Fire"),
    ("SUCTION PRESSURE",            "inhg",             "Suction"),
    ("ELECTRICAL TOTAL LOAD AMPS",  "Amperes",          "Amps"),
    ("GENERAL ENG STARTER:1",       "bool",             "Engine 1 Starter"),
    ("GENERAL ENG STARTER:2",       "bool",             "Engine 2 Starter"),
    ("GENERAL ENG STARTER:3",       "bool",             "Engine 3 Starter"),
    ("GENERAL ENG STARTER:4",       "bool",             "Engine 4 Starter"),
    ("PITOT HEAT",                  "bool",             "Pitot Heat"),
    ("PANEL ANTI ICE SWITCH",       "bool",             "Panel Anti-Ice"),
    ("BRAKE PARKING POSITION",      "bool",             "Parking Brake"),
    ("GEAR LEFT POSITION",          "percent over 100", "Gear L"),
    ("GEAR CENTER POSITION",        "percent over 100", "Gear C"),
    ("GEAR RIGHT POSITION",         "percent over 100", "Gear R"),
]

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
log = logging.getLogger("bravo-switcher")

# Only configure console logging when run directly. When imported by the GUI,
# the GUI attaches its own handler and configures output, and a console
# StreamHandler may point at a non-existent stream in a windowed .exe.
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def full(path_name):
    """Absolute path to a file inside the BravoLED folder."""
    return os.path.join(BRAVO_DIR, path_name)


def pick_config_for(title, rules=None):
    """Return the config filename that matches an aircraft TITLE, or the
    default if nothing matches. Rules are read live from settings.json unless
    a rules list is passed in."""
    if rules is None:
        rules = load_settings()["rules"]
    if title:
        lowered = title.lower()
        for rule in rules:
            if rule.get("match", "").lower() in lowered:
                return rule.get("config", DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def swap_config(config_name):
    """Copy config_<name>.json over the active config.json.
    Returns True if the active file actually changed."""
    src = full(config_name)
    dst = full(ACTIVE_CONFIG)

    if not os.path.exists(src):
        log.error("Config '%s' not found -- leaving current config in place.", config_name)
        return False

    # Skip the copy if the active config is already identical (avoids a
    # pointless BravoLED restart when the aircraft hasn't really changed).
    if os.path.exists(dst):
        try:
            with open(src, "rb") as a, open(dst, "rb") as b:
                if a.read() == b.read():
                    return False
        except OSError:
            pass  # if comparison fails, just proceed with the copy

    shutil.copyfile(src, dst)
    log.info("Swapped active config -> %s", config_name)
    return True


def restart_bravoled():
    """Kill any running BravoLED.exe and start it fresh so it reloads
    the config. Uses Windows taskkill so there are no extra dependencies."""
    exe_path = full(EXE_NAME)
    if not os.path.exists(exe_path):
        log.error("%s not found at %s", EXE_NAME, exe_path)
        return

    # Stop the existing instance (ignore "not running" errors).
    subprocess.run(
        ["taskkill", "/F", "/IM", EXE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)  # give it a moment to release the COM/SimConnect handle

    # Relaunch, detached, with its own folder as the working directory so
    # it finds config.json the same way it normally would.
    subprocess.Popen(
        [exe_path],
        cwd=BRAVO_DIR,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    log.info("Restarted %s", EXE_NAME)


# --------------------------------------------------------------------------
# SimConnect plumbing
# --------------------------------------------------------------------------
class SimConnectMissing(Exception):
    """Raised when the SimConnect library can't be imported."""


def connect_simconnect():
    """Try to connect to a running MSFS. Returns (sm, aq) or (None, None).
    Raises SimConnectMissing if the library itself isn't installed."""
    try:
        from SimConnect import SimConnect, AircraftRequests
    except ImportError as e:
        raise SimConnectMissing(str(e))

    try:
        sm = SimConnect()
        aq = AircraftRequests(sm, _time=2000)  # cache values for 2s
        return sm, aq
    except Exception:
        return None, None


def read_title(aq):
    """Read the current aircraft TITLE as a clean string, or '' if unavailable."""
    try:
        raw = aq.get("TITLE")
    except Exception:
        return ""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    return str(raw).strip()


def print_debug_simvars(aq):
    """Print live SimVar values to the log. Only called when debug mode is on.
    Reuses the existing AircraftRequests object (aq); the python-simconnect
    library keys variables by their datum name with spaces replaced by
    underscores (e.g. 'GENERAL ENG OIL PRESSURE' -> 'GENERAL_ENG_OIL_PRESSURE')."""
    lines = ["---- SimVar debug snapshot ----"]
    for datum, units, label in DEBUG_WATCH:
        try:
            key = datum.replace(" ", "_")
            val = aq.get(key)
            if val is None:
                val = "n/a (unknown var or no value yet)"
            elif isinstance(val, float):
                val = f"{val:.4f}"
            lines.append(f"  {label:<22} {val}  ({units})")
        except Exception as e:
            lines.append(f"  {label:<22} ERROR: {e}")
    lines.append("--------------------------------")
    for l in lines:
        log.info(l)


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------
def main(stop_event=None):
    """Run the switch loop. If stop_event (a threading.Event) is provided,
    the loop exits cleanly when it is set -- this is how the GUI stops it.
    Run with no argument for the standalone, run-forever behaviour."""

    def should_stop():
        return stop_event is not None and stop_event.is_set()

    def sleep_interruptible(seconds):
        # Sleep in small slices so Stop is responsive instead of waiting
        # out a full poll interval.
        end = time.time() + seconds
        while time.time() < end:
            if should_stop():
                return
            time.sleep(0.1)

    log.info("BravoLED config switcher starting.")
    log.info("Folder: %s", BRAVO_DIR)

    # Make sure settings.json exists so the GUI (and the user) have something
    # to edit, and log the initial debug state.
    if not os.path.exists(full(SETTINGS_FILE)):
        save_settings(load_settings())
    if load_settings()["debug"]:
        log.info("DEBUG MODE ON -- printing SimVar values periodically")

    # Sanity check the essentials up front.
    if not os.path.exists(full(DEFAULT_CONFIG)):
        log.warning("No %s found. Create one (copy your working config.json) "
                    "so there's a fallback when no aircraft rule matches.", DEFAULT_CONFIG)

    sm = aq = None
    last_title = None      # last aircraft title we acted on
    waiting_logged = False
    debug_counter = 0

    while not should_stop():
        # (Re)connect to the sim if needed.
        if aq is None:
            try:
                sm, aq = connect_simconnect()
            except SimConnectMissing as e:
                log.critical("The 'SimConnect' library isn't available (%s). "
                             "If running from source, run:  pip install SimConnect", e)
                return
            if aq is None:
                if not waiting_logged:
                    log.info("Waiting for MSFS / SimConnect ...")
                    waiting_logged = True
                sleep_interruptible(POLL_SECONDS)
                continue
            log.info("Connected to MSFS.")
            waiting_logged = False
            last_title = None  # force a fresh evaluation on (re)connect

        title = read_title(aq)

        # If we suddenly can't read anything, the sim probably closed.
        if not title:
            log.info("Lost the aircraft title (sim closed?). Will reconnect.")
            sm = aq = None
            sleep_interruptible(POLL_SECONDS)
            continue

        # Read settings fresh each poll so GUI edits (rules, debug) take
        # effect live without a restart.
        settings = load_settings()

        # Only act when the aircraft actually changes.
        if title != last_title:
            log.info("Aircraft detected: %s", title)
            target = pick_config_for(title, settings["rules"])
            if target == DEFAULT_CONFIG:
                log.info("No specific rule matched -> using %s", DEFAULT_CONFIG)
            if swap_config(target):
                restart_bravoled()
            last_title = title

        # Debug SimVar dump periodically when enabled.
        if settings["debug"]:
            debug_counter += 1
            if debug_counter >= 5:   # ~ every 5 polls
                print_debug_simvars(aq)
                debug_counter = 0
        else:
            debug_counter = 0

        sleep_interruptible(POLL_SECONDS)

    log.info("Switcher loop stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped by user.")