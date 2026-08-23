@echo off
rem Zapusk stenda "Kompas" bez nastroyki ExecutionPolicy.
rem Mozhno dvazhdy shchelknut po faylu ili vyzvat iz terminala:
rem     .\start.bat
rem     .\start.bat -Restart
rem     .\start.bat -Port 8001
chcp 65001 > nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
