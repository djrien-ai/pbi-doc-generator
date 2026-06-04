@echo off
title PBI Metadata Extractor
echo ============================================
echo   PBI Metadata Extractor
echo   Data Documentation Generator
echo ============================================
echo.

:: Find Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python is niet gevonden. Installeer Python 3.10+ en voeg het toe aan PATH.
    pause
    exit /b 1
)

:: Launch the GUI
python "%~dp0gui.py"

if %ERRORLEVEL% neq 0 (
    echo.
    echo Er is een fout opgetreden. Controleer of alle bestanden aanwezig zijn.
    pause
)
