@echo off
title Stop HemoGrid
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Stop
echo HemoGrid stopped.
timeout /t 2 >nul
