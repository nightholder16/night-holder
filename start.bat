@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Offers Bot

echo.
echo === Offers Bot ===
echo.

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)

if not defined PY (
    echo [ERROR] Python not found. Install Python 3.10+ and try again.
    pause
    exit /b 1
)

set "VPY="
if exist ".venv\Scripts\python.exe" (
    set "VPY=.venv\Scripts\python.exe"
) else (
    echo [1/2] Creating virtual environment .venv ...
    %PY% -m venv .venv
    if exist ".venv\Scripts\python.exe" set "VPY=.venv\Scripts\python.exe"
)

if defined VPY (
    echo [2/2] Installing dependencies ...
    "%VPY%" -m pip install --upgrade pip --quiet
    "%VPY%" -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo.
    echo Starting bot, Ctrl+C to stop ...
    "%VPY%" bot.py %*
) else (
    echo.
    echo Could not create .venv, using system Python.
    echo Installing dependencies ...
    %PY% -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo.
    echo Starting bot, Ctrl+C to stop ...
    %PY% bot.py %*
)

echo.
echo Bot stopped.
pause
