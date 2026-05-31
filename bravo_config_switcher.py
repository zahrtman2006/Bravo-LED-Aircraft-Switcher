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
ONE-TIME SETUP
--------------------------------------------------------------------------
    1. Install Python 3 (you've already got it).
    2. Install the SimConnect library:
           pip install SimConnect
    3. Drop this script in the BravoLED folder.
    4. Make your config_default.json (copy your current working config.json).
    5. Make per-aircraft configs (config_tbm930.json, etc.).
    6. Edit the AIRCRAFT_RULES list below to match your fleet.
    7. Run it:  python bravo_config_switcher.py

Leave it running in the background while you fly. Start it before or
after MSFS, it'll wait for the sim and reconnect on its own.

--------------------------------------------------------------------------
DEBUG MODE
--------------------------------------------------------------------------
Set DEBUG_SIMVARS = True below to print live SimVar values every few
seconds. Use this to see exactly what MSFS is reporting for oil pressure,
fuel pressure, etc. so you can tune your config thresholds.
Turn it off again once you have your numbers dialled in.
"""

import os
import sys
import time
import shutil
import logging
import subprocess

# --------------------------------------------------------------------------
# CONFIGURATION  --  edit this section to match your setup
# --------------------------------------------------------------------------

# The script assumes it lives in the BravoLED folder. If you'd rather run it
# from somewhere else, hard-code the folder path here instead of "".
BRAVO_DIR = os.path.dirname(os.path.abspath(__file__)) or "."

EXE_NAME       = "BravoLED.exe"
ACTIVE_CONFIG  = "config.json"           # the file BravoLED actually reads
DEFAULT_CONFIG = "config_default.json"   # fallback when no rule matches

# How often (seconds) to poll the sim for the current aircraft.
POLL_SECONDS = 3

# --------------------------------------------------------------------------
# DEBUG MODE
# Set to True to print live SimVar values every POLL_SECONDS.
# Useful for finding the real oil/fuel pressure values MSFS reports so you
# can set the right thresholds in your per-aircraft config files.
# Turn off again once your thresholds are dialled in.
# --------------------------------------------------------------------------
DEBUG_SIMVARS = True

# Which SimVars to print when DEBUG_SIMVARS is True.
# Add or remove entries to taste -- these match the labels in config.json.
# NOTE: engine vars are indexed (":1" = engine 1). For a multi-engine
# aircraft you could add ":2", ":3", etc. The library reads oil pressure
# natively in Psf and fuel pressure in Psi (shown in the labels below).
DEBUG_WATCH = [
    ("GENERAL ENG OIL PRESSURE:1",  "psf",              "Oil pressure (eng1)"),
    ("GENERAL ENG FUEL PRESSURE:1", "psi",              "Fuel pressure (eng1)"),
    ("SUCTION PRESSURE",            "inhg",             "Suction"),
    ("ELECTRICAL TOTAL LOAD AMPS",  "Amperes",          "Amps"),
    ("BRAKE PARKING POSITION",      "bool",             "Parking brake"),
    ("GEAR LEFT POSITION",          "percent over 100", "Gear L"),
    ("GEAR CENTER POSITION",        "percent over 100", "Gear C"),
    ("GEAR RIGHT POSITION",         "percent over 100", "Gear R"),
]

# Aircraft matching rules, checked TOP TO BOTTOM. The first rule whose
# "match" substring appears in the aircraft TITLE wins. Matching is
# case-insensitive. Put more specific rules ABOVE more general ones.
#
#   "match"  -> a piece of the aircraft.cfg TITLE string to look for
#   "config" -> which config_*.json to load when it matches
#
# To find an aircraft's exact TITLE, just load it in MSFS and watch this
# script's log output -- it prints the title every time it changes.
AIRCRAFT_RULES = [
    {"match": "TBM 930",         "config": "config_tbm930.json"},
    {"match": "Cessna 172",      "config": "config_c172.json"},
    {"match": "Cessna Skyhawk",  "config": "config_c172.json"},
    # add more lines here as you build configs, e.g.:
    # {"match": "Baron G58",     "config": "config_baron58.json"},
    # {"match": "PMDG 737",      "config": "config_b738.json"},
]

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bravo-switcher")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def full(path_name):
    """Absolute path to a file inside the BravoLED folder."""
    return os.path.join(BRAVO_DIR, path_name)


def pick_config_for(title):
    """Return the config filename that matches an aircraft TITLE, or the
    default if nothing matches."""
    if title:
        lowered = title.lower()
        for rule in AIRCRAFT_RULES:
            if rule["match"].lower() in lowered:
                return rule["config"]
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
def connect_simconnect():
    """Try to connect to a running MSFS. Returns (sm, aq) or (None, None)."""
    try:
        from SimConnect import SimConnect, AircraftRequests
    except ImportError:
        log.critical("The 'SimConnect' library isn't installed. Run:  pip install SimConnect")
        sys.exit(1)

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
    """Print live SimVar values to the log. Only called when DEBUG_SIMVARS=True.
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
def main():
    log.info("BravoLED config switcher starting.")
    log.info("Folder: %s", BRAVO_DIR)
    if DEBUG_SIMVARS:
        log.info("DEBUG MODE ON -- printing SimVar values every %ds", POLL_SECONDS)

    # Sanity check the essentials up front.
    if not os.path.exists(full(DEFAULT_CONFIG)):
        log.warning("No %s found. Create one (copy your working config.json) "
                    "so there's a fallback when no aircraft rule matches.", DEFAULT_CONFIG)

    sm = aq = None
    last_title = None      # last aircraft title we acted on
    waiting_logged = False
    debug_counter = 0

    while True:
        # (Re)connect to the sim if needed.
        if aq is None:
            sm, aq = connect_simconnect()
            if aq is None:
                if not waiting_logged:
                    log.info("Waiting for MSFS / SimConnect ...")
                    waiting_logged = True
                time.sleep(POLL_SECONDS)
                continue
            log.info("Connected to MSFS.")
            waiting_logged = False
            last_title = None  # force a fresh evaluation on (re)connect

        title = read_title(aq)

        # If we suddenly can't read anything, the sim probably closed.
        if not title:
            log.info("Lost the aircraft title (sim closed?). Will reconnect.")
            sm = aq = None
            time.sleep(POLL_SECONDS)
            continue

        # Only act when the aircraft actually changes.
        if title != last_title:
            log.info("Aircraft detected: %s", title)
            target = pick_config_for(title)
            if target == DEFAULT_CONFIG:
                log.info("No specific rule matched -> using %s", DEFAULT_CONFIG)
            if swap_config(target):
                restart_bravoled()
            last_title = title

        # Debug SimVar dump every POLL_SECONDS when enabled.
        if DEBUG_SIMVARS:
            debug_counter += 1
            # Print every 5 polls (~15s at default) so the log isn't wall-to-wall numbers.
            if debug_counter >= 5:
                print_debug_simvars(aq)
                debug_counter = 0

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped by user.")
