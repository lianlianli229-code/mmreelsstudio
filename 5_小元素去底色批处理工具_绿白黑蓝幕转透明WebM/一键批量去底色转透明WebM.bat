@echo off
set "PY_EXE=C:\Users\Clara\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"
set "FACTORY_PY=C:\Users\Clara\reels-studio\scripts\official_rembg_batch_factory.py"
if exist "%~dp0official_rembg_batch_factory.py" set "FACTORY_PY=%~dp0official_rembg_batch_factory.py"
"%PY_EXE%" -X utf8 "%FACTORY_PY%" --interactive --default-dir "%~dp0." "%~1"
echo.
pause
