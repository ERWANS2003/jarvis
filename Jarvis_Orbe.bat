@echo off
rem Jarvis en orbe flottante sur le bureau, sans fenetre de console.
rem Clic : parler. Glisser : deplacer. Clic droit : menu (ecrire, quitter).
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" jarvis.py --orb --lang fr %*
) else (
    call "%~dp0Lancer_Jarvis.bat" --orb --lang fr %*
)
