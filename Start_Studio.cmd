@echo off
title Power BI Documentation & Live Lineage Studio
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -m pbi_catalog.cli studio
    goto :eof
)
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python -m pbi_catalog.cli studio
    goto :eof
)
echo Python 3.10+ was not found on this machine.
echo Install Python from the Microsoft Store or https://www.python.org/downloads/ and run Start_Studio.cmd again.
pause
