@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Jarvis - lanceur

rem ===========================================================================
rem  Jarvis - lanceur tout-en-un (double-clic)
rem ===========================================================================
rem  Ce fichier se debrouille tout seul :
rem    1. se place dans le dossier du projet ;
rem    2. choisit un interpreteur (l'environnement .venv, sinon Python) ;
rem    3. cree .env depuis .env.example s'il manque, et le fait remplir ;
rem    4. ouvre l'interface graphique, en francais par defaut.
rem
rem  Tous les arguments de jarvis.py passent tels quels :
rem
rem    Lancer_Jarvis.bat --lang en       interface en anglais
rem    Lancer_Jarvis.bat --no-gui        console avec micro
rem    Lancer_Jarvis.bat --text          clavier seul, sans micro ni voix
rem    Lancer_Jarvis.bat --list_tools    liste les outils disponibles
rem    Lancer_Jarvis.bat --help          toutes les options
rem ===========================================================================

cd /d "%~dp0"
echo.
echo   ============================================
echo     Jarvis - assistant personnel
echo   ============================================
echo.

rem --- 1. Choisir l'interpreteur ---------------------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo   [X] Python est introuvable.
    echo.
    echo       Installe Python 3.11 ou plus, puis relance ce fichier.
    echo       Pour creer l'environnement du projet :
    echo           powershell -ExecutionPolicy Bypass -File install.ps1
    echo.
    pause
    exit /b 1
)
if "%PY%"==".venv\Scripts\python.exe" (
    echo   [1/4] Environnement du projet : .venv
) else (
    echo   [1/4] Environnement du projet absent : utilisation de %PY%
    echo         Pour l'installer : powershell -ExecutionPolicy Bypass -File install.ps1
)

rem --- 2. Verifier les dependances essentielles -------------------------------
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo   [2/4] Tkinter absent : la fenetre ne pourra pas s'ouvrir,
    echo         Jarvis basculera en mode console.
) else (
    echo   [2/4] Affichage graphique disponible.
)

rem --- 3. Verifier le fichier .env (cle API) ---------------------------------
if not exist ".env" (
    echo   [3/4] Aucun fichier .env : aucune cle API n'est configuree.
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo         Un modele vient d'etre cree : .env
        echo         Renseigne la ligne OPENROUTER_API_KEY, enregistre,
        echo         puis relance ce fichier.
        echo.
        pause
        start "" notepad ".env"
        exit /b 1
    )
    echo         Cree un fichier .env avec la ligne OPENROUTER_API_KEY.
    echo.
    pause
    exit /b 1
)
echo   [3/4] Fichier .env trouve.

rem --- 4. Demarrer -----------------------------------------------------------
set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=--lang fr"

echo   [4/4] Demarrage de Jarvis (modele et langue lus depuis .env)...
echo.
%PY% -u jarvis.py %ARGS%
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo   Jarvis s'est arrete avec le code %CODE%.
    echo   Relis le message ci-dessus : il indique la cause.
    echo.
    pause
)

endlocal & exit /b %CODE%
