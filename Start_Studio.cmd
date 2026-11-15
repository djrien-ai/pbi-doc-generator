@echo off
setlocal
title Power BI Documentation ^& Live Lineage Studio
cd /d "%~dp0"

set "PY_CMD="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=.venv\Scripts\python.exe"
)
if not defined PY_CMD (
    py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py"
)
if not defined PY_CMD (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if defined PY_CMD goto :have_python

echo Python 3.10+ was not found on this machine.
echo Tip: Non-technical users can download PBI_Doc_Generator_Windows_Portable.zip from GitHub Releases ^(no Python needed^),
echo or install Python 3.10+ from the Microsoft Store / https://www.python.org/downloads/
pause
exit /b 1

:have_python
"%PY_CMD%" -c "import pbixray, pandas, playwright" >nul 2>nul
if not errorlevel 1 goto :launch_studio

echo First-time setup: installing required Python libraries ^(pbixray, pandas, playwright^)...
"%PY_CMD%" -c "import subprocess, sys; extra = [] if sys.prefix != sys.base_prefix else ['--user']; raise SystemExit(subprocess.call([sys.executable, '-m', 'pip', 'install', *extra, '-r', 'requirements.txt']))"
if errorlevel 1 (
    echo Failed to install required Python packages.
    pause
    exit /b 1
)

:launch_studio
echo Starting Power BI Documentation ^& Live Lineage Studio...
echo Keep this window open while using Studio in your browser ^(close this window to stop the local server^).
"%PY_CMD%" launcher.py studio %*
if errorlevel 1 pause
