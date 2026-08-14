@echo off
setlocal
set PYTHON=C:\ProgramData\miniforge3\python.exe
set APP=D:\mycroft-phoenix
set SCRIPT=%APP%\mycroft\audio\voice_loop.py

cd /d "%APP%"

if "%~1"=="" goto :run
if /i "%~1"=="setup" goto :setup
if /i "%~1"=="diagnostic" goto :diagnostic
if /i "%~1"=="autodetect" goto :autodetect
goto :usage

:setup
"%PYTHON%" "%SCRIPT%" --setup
goto :eof

:diagnostic
"%PYTHON%" "%SCRIPT%" --diagnostic
goto :eof

:autodetect
"%PYTHON%" "%SCRIPT%" --autodetect
goto :eof

:run
"%PYTHON%" "%SCRIPT%"
goto :eof

:usage
echo Usage: lancer-phoenix [setup ^| diagnostic ^| autodetect]
echo   (sans argument) : lance la boucle vocale
goto :eof
