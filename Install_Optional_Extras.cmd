@echo off
title Install Optional Extras for PBI Doc Generator (.pbix, .xlsx & Corporate Web Sign-In)
cd /d "%~dp0"
echo Installing optional Python packages (pbixray, pandas, playwright) for your user account...
echo Note: Core Power BI Service scanning, .pbip/TMDL, Live Lineage, and MCP already work without these extras.
echo.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -m pip install --user "pbixray>=0.15.5" "pandas>=2.0.0,<3.0.0" "playwright>=1.40.0"
    goto :done
)
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python -m pip install --user "pbixray>=0.15.5" "pandas>=2.0.0,<3.0.0" "playwright>=1.40.0"
    goto :done
)
echo Python 3.10+ was not found on this machine.
echo Install Python from the Microsoft Store or https://www.python.org/downloads/ first.
pause
goto :eof

:done
echo.
echo Done! You can now double-click Start_Studio.cmd to launch Power BI Documentation Studio.
pause
