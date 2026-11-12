@echo off
title Power BI Documentation & Live Lineage Studio
cd /d "%~dp0"

set "PY_CMD="
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 set "PY_CMD=py"
if "%PY_CMD%"=="" (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 set "PY_CMD=python"
)

if "%PY_CMD%"=="" (
    echo Python 3.10+ was not found on this machine.
    echo Tip: Non-technical users can download PBI_Doc_Generator_Windows_Portable.zip from GitHub Releases (no Python needed),
    echo or install Python 3.10+ from the Microsoft Store / https://www.python.org/downloads/
    pause
    goto :eof
)

%PY_CMD% -c "import pbixray, pandas, playwright" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo First-time setup: installing required Python libraries ^(pbixray, pandas, playwright^)...
    %PY_CMD% -m pip install --user -r requirements.txt
)

echo Starting Power BI Documentation ^& Live Lineage Studio...
echo Keep this window open while using Studio in your browser ^(close this window to stop the local server^).
%PY_CMD% launcher.py studio
