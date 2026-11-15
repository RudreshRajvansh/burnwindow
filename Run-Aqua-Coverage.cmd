@echo off
cd /d "%~dp0"
python fetch_validation_sources.py aqua --output "%LOCALAPPDATA%\BurnWindow\earthdata-cache"
if errorlevel 1 goto finished
python reproduce_validation.py aqua --cache "%LOCALAPPDATA%\BurnWindow\earthdata-cache" --run-directory "%LOCALAPPDATA%\BurnWindow\validation-runs\aqua-%RANDOM%-%RANDOM%"
:finished
pause
