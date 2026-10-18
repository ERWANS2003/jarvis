@echo off
rem ===========================================================================
rem  Jarvis - lanceur double-clic
rem ===========================================================================
rem  Double-clique ce fichier pour demarrer l'assistant.
rem  La fenetre graphique s'ouvre par defaut.
rem  Tous les arguments de jarvis.py sont transmis :
rem
rem      run.bat --lang fr       en francais
rem      run.bat --no-gui        console avec micro
rem      run.bat --text          sans micro ni voix (console)
rem      run.bat --help          toutes les options
rem ===========================================================================

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   L'environnement virtuel est absent.
    echo   Lance d'abord :  powershell -ExecutionPolicy Bypass -File install.ps1
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -u jarvis.py %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo   Jarvis s'est arrete avec le code %CODE%.
    pause
)

endlocal & exit /b %CODE%
