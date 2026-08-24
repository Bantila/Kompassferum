@echo off
rem Zapusk stenda "Kompas" bez nastroyki ExecutionPolicy.
rem Mozhno dvazhdy shchelknut po faylu ili vyzvat iz terminala:
rem     .\"local deploy\start.bat"
rem     .\"local deploy\start.bat" -Restart
rem     .\"local deploy\start.bat" -Port 8001
chcp 65001 > nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
