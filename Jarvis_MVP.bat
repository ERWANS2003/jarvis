@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Jarvis MVP
rem Version de presentation : installe ce qui manque, verifie tout, puis lance l'orbe.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto env
set "BASE="
for /f "delims=" %%P in ('py -3.11 -c "import sys;print(sys.executable)" 2^>nul') do set "BASE=%%P"
if not defined BASE set "BASE=python"
echo Premiere installation, avec %BASE% ...
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Mvp -Python "%BASE%"
if errorlevel 1 goto failed

:env
if exist ".env" goto check
copy /y ".env.example" ".env" >nul

:check
".venv\Scripts\python.exe" verifier_mvp.py
if errorlevel 1 goto failed
start "" ".venv\Scripts\pythonw.exe" jarvis.py --config jarvis.mvp.yaml --orb
exit /b 0

:failed
echo.
echo Jarvis n'a pas demarre : relis le message ci-dessus.
pause
exit /b 1
