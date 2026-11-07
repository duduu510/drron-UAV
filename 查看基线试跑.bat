@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if not exist "build\baseline-demo\latest-summary.json" (
  echo Baseline result not found. See README.md.
  pause
  exit /b 1
)
start "VDE-Inspect Baseline" ".venv\Scripts\pythonw.exe" -m vde_inspect.app --workspace "%~dp0build\baseline-demo" --open-latest-result
