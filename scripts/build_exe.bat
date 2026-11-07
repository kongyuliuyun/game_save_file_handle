@echo off
setlocal

REM Always build from the project root (parent of this script directory).
cd /d "%~dp0.."
if errorlevel 1 (
    echo [ERROR] Cannot switch to project root: %~dp0..
    pause
    exit /b 1
)
if not exist "run_gui.py" (
    echo [ERROR] run_gui.py not found in %CD%
    echo [ERROR] Keep this script inside the project's scripts directory.
    pause
    exit /b 1
)
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found in %CD%
    pause
    exit /b 1
)

echo ========================================
echo  GameSaveBackup 2.0.1 - Build EXE
echo ========================================
echo.

REM Use a clean virtual environment to avoid conflicting packages in the
REM base Python installation (for example the old pathlib backport).
if not exist ".venv_build" (
    echo [INFO] Creating clean virtual environment...
    python -m venv .venv_build
    if errorlevel 1 goto :error
)

call ".venv_build\Scripts\activate.bat"
if errorlevel 1 goto :error

echo [INFO] Installing dependencies...
python -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 goto :error

echo [INFO] Building...
echo.
python -m PyInstaller GameSaveBackup.spec --clean
if errorlevel 1 goto :error

echo.
echo ========================================
echo  Build complete!
echo  EXE: dist\GameSaveBackup.exe
echo  Optional: put config.yaml next to the exe to customize settings.
echo ========================================
pause
exit /b 0

:error
echo.
echo [ERROR] Build failed.
pause
exit /b 1
