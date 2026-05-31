@echo off
REM ============================================================
REM  BravoLED Switcher - launcher
REM  Double-click this to open the switcher control panel.
REM  Keep it in the same folder as bravo_switcher_gui.py.
REM ============================================================

cd /d "%~dp0"

REM Use pythonw (no console window) if available, otherwise fall back to python.
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "bravo_switcher_gui.py"
) else (
    start "" python "bravo_switcher_gui.py"
)
