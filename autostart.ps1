# ===========================================================================
#  Jarvis - demarrage automatique avec Windows
# ===========================================================================
#
#  Cree (ou retire) un raccourci dans le dossier « Demarrage » de l'utilisateur,
#  afin que Jarvis se lance a chaque ouverture de session.
#
#  Usage :
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Gui
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -ExtraArgs "--lang fr"
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Remove
#
#  Par defaut le raccourci lance run.bat en mode texte, dans une fenetre
#  reduite : le micro n'est donc pas monopolise au demarrage. Utilise -Gui
#  pour ouvrir directement la fenetre graphique.
# ===========================================================================

[CmdletBinding()]
param(
    [switch]$Remove,                       # retire le demarrage automatique
    [switch]$Gui,                          # lance la fenetre graphique
    [string]$ExtraArgs = "",               # arguments supplementaires
    [string]$Name = "Jarvis.lnk"           # nom du raccourci
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$runBat = Join-Path $PSScriptRoot "run.bat"
$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup $Name

if ($Remove) {
    if (Test-Path $link) {
        Remove-Item $link -Force
        Write-Host "Demarrage automatique retire ($link)." -ForegroundColor Green
    } else {
        Write-Host "Aucun demarrage automatique a retirer." -ForegroundColor Yellow
    }
    exit 0
}

if (-not (Test-Path $runBat)) {
    throw "run.bat est introuvable dans $PSScriptRoot."
}

if (-not (Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"))) {
    throw "L'environnement virtuel est absent. Lance d'abord install.ps1."
}

$arguments = if ($Gui) { "--gui $ExtraArgs" } else { "--text $ExtraArgs" }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $runBat
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Arguments = $arguments.Trim()
$shortcut.WindowStyle = 7            # 7 = fenetre reduite
$shortcut.Description = "Assistant vocal Jarvis"
$shortcut.Save()

Write-Host "Demarrage automatique installe." -ForegroundColor Green
Write-Host "    raccourci : $link"
Write-Host "    commande  : run.bat $($shortcut.Arguments)"
Write-Host ""
Write-Host "Pour le retirer : powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Remove" -ForegroundColor Cyan
