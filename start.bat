@echo off
rem MSFS ATC: set everything up (first start) and open the app.
rem   start.bat                set up if needed, then open the app window
rem   start.bat --browser      open the app in the normal browser instead (this console shows messages, Ctrl+C ends)
rem   start.bat --setup-only   only create .venv and install the requirements
setlocal EnableExtensions
cd /d "%~dp0"
set "VENV_PY=.venv\Scripts\python.exe"

rem --- 1. Python and the virtual environment ------------------------------------------------------------------
if exist "%VENV_PY%" goto check_venv
call :find_python
if errorlevel 1 goto no_python
echo Creating the virtual environment in .venv with %PYTHON% (first start only) ...
"%PYTHON%" -m venv .venv
if errorlevel 1 goto venv_failed

:check_venv
"%VENV_PY%" -c "import sys" >nul 2>&1
if errorlevel 1 goto venv_broken

rem --- 2. Requirements: installed again only when requirements.txt has changed --------------------------------
fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if not errorlevel 1 goto requirements_ok
echo Installing the requirements (takes a few minutes the first time) ...
"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto pip_failed
copy /y requirements.txt .venv\requirements.installed >nul
:requirements_ok

if /i "%~1"=="--setup-only" (
    echo Setup complete.
    exit /b 0
)

rem --- 3. MSFS: only a note here, the app itself shows a clear message as well --------------------------------
tasklist /fi "imagename eq FlightSimulator.exe" 2>nul | find /i "FlightSimulator.exe" >nul
if errorlevel 1 echo Note: MSFS is not running. Start it and load a flight, or practise with "Without MSFS".

rem --- 4. Start: without a console window (pythonw), or in this console for --browser and other options -------
if "%~1"=="" (
    start "" ".venv\Scripts\pythonw.exe" -m atc.app
    exit /b 0
)
"%VENV_PY%" -m atc.app %*
exit /b %errorlevel%


:find_python
rem The py launcher (python.org installer) first, then python on PATH. "python" can also be the Microsoft Store
rem alias that only opens the Store, so a candidate only counts if it really reports Python 3.12 or newer.
for %%P in ("py -3" "python") do (
    %%~P -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%E in ('%%~P -c "import sys; print(sys.executable)"') do set "PYTHON=%%E"
        exit /b 0
    )
)
exit /b 1

:no_python
echo.
echo Python 3.12 or newer was not found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run start.bat again.
goto fail

:venv_failed
echo.
echo Could not create the virtual environment in .venv (see the message above).
goto fail

:venv_broken
echo.
echo The .venv folder doesn't work any more (was the project folder moved or Python updated?).
echo Delete the .venv folder and run start.bat again: it is created again automatically.
goto fail

:pip_failed
echo.
echo Installing the requirements failed (see the messages above).
echo Check the internet connection and run start.bat again.
goto fail

:fail
echo.
pause
exit /b 1
