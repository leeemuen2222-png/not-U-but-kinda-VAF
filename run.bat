@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title UVAF Launcher

set "PYTHON_CMD="

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python 3 was not found.
    echo Install Python 3.10 or newer and enable "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo [INFO] Using: %PYTHON_CMD%
%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo [ERROR] UVAF requires Python 3.10 or newer.
    %PYTHON_CMD% --version
    echo.
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt was not found in:
    echo %CD%
    echo.
    pause
    exit /b 1
)

%PYTHON_CMD% -m pip --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] pip was not found. Installing pip...
    %PYTHON_CMD% -m ensurepip --upgrade
    if errorlevel 1 goto :install_failed
)

echo [INFO] Checking UVAF dependencies...
%PYTHON_CMD% -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :install_failed

echo [INFO] Verifying runtime modules...
%PYTHON_CMD% -c "import PySide6"
if errorlevel 1 goto :verify_failed

echo [INFO] Starting UVAF...
%PYTHON_CMD% main.py
set "APP_EXIT=%ERRORLEVEL%"

if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] UVAF exited with code %APP_EXIT%.
    echo Copy the error text above when reporting the problem.
    echo.
    pause
)

exit /b %APP_EXIT%

:install_failed
echo.
echo [ERROR] Dependency installation failed.
echo Check the network connection and the error text above.
echo.
pause
exit /b 1

:verify_failed
echo.
echo [ERROR] PySide6 still cannot be imported.
echo Copy the error text above when reporting the problem.
echo.
pause
exit /b 1
