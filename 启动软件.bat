@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python environment missing. See README.md.
  pause
  exit /b 1
)
start "VDE-Inspect" ".venv\Scripts\pythonw.exe" -m vde_inspect.app
