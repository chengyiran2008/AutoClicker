@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Prefer the system Python 3.13 that ships with tkinter (no console window)
set "PYW=C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe"
if exist "%PYW%" goto launch

for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if not "%PYW%"=="" goto launch

echo [ERROR] pythonw.exe not found. Please install Python 3.10+ with tcl/tk.
echo You can also run manually:  python main.py
pause
exit /b 1

:launch
start "" "%PYW%" "%~dp0main.py"
exit /b 0
