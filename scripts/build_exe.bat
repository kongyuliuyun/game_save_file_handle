@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ========================================
echo  GameSaveBackup - Build EXE
echo ========================================
echo.

REM Use clean venv to avoid system package conflicts (e.g. pathlib)
if not exist ".venv_build" (
    echo [INFO] Creating clean virtual environment...
    python -m venv .venv_build
)

call .venv_build\Scripts\activate.bat

echo [INFO] Installing dependencies...
pip install pyyaml bypy pyinstaller -q 2>nul

echo [INFO] Building...
echo.

REM Find Tcl/Tk DLLs from parent Python installation
for /f "delims=" %%i in ('python -c "import sys; print(sys.base_prefix)"') do set "BASE=%%i"

REM Convert PNG to ICO if needed (requires Pillow):
REM   pip install Pillow -q
REM   python -c "from PIL import Image; img=Image.open('img/icon.png'); img.save('img/icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)], bitmap_format='bmp')"

set "ICON_PARAM="
if exist "img\icon.ico" set "ICON_PARAM=--icon img\icon.ico"

pyinstaller --onefile --windowed --name "GameSaveBackup" %ICON_PARAM% --add-data "config\config.yaml;config" --add-data "img\icon.ico;img" --collect-all tkinter --collect-all bypy --add-binary "%BASE%\Library\bin\tcl86t.dll;." --add-binary "%BASE%\Library\bin\tk86t.dll;." --add-binary "%BASE%\Library\bin\libssl-1_1-x64.dll;." --add-binary "%BASE%\Library\bin\libcrypto-1_1-x64.dll;." --hidden-import yaml --clean gui/app.py

echo.
echo ========================================
echo  Build complete!
echo  EXE: dist\GameSaveBackup.exe
echo  Put config.yaml next to the exe.
echo ========================================
pause
