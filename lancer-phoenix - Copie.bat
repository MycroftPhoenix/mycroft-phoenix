@echo off
rem LANCEUR Phoenix - Mycroft-Phoenix
rem Utilise le Python de Miniforge pour éviter les conflits WindowsApps

set MYPROJECT_DIR=D:\mycroft-phoenix
set PYTHON_EXE=C:\ProgramData\miniforge3\python.exe

rem Démarrage du pipeline Phoenix
"%PYTHON_EXE%" -%MYPROJECT_DIR%/mycroft/pipeline.py %*

rem Optionnel : démarrer l'interface web
rem "%PYTHON_EXE%" -%MYPROJECT_DIR%/mycroft/web/server.py