# ===========================================================================
#  Jarvis - demarrage automatique avec Windows
# ===========================================================================
#
#  Cree (ou retire) un raccourci dans le dossier « Demarrage » de l'utilisateur,
#  afin que Jarvis se lance a chaque ouverture de session.
#
#  Usage :
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1            # orbe
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Gui       # fenetre
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Text      # console
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -ExtraArgs "--lang en"
#    powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Remove
#
#  Par defaut, Jarvis demarre en orbe flottante sur le bureau, sans fenetre de
#  console (pythonw.exe) : dis « Hey Jarvis » ou appuie sur Ctrl+Espace.
#  -Gui ouvre la fenetre graphique, -Text la console clavier (fenetre reduite).
# ===========================================================================

[CmdletBinding()]
param(
    [switch]$Remove,                       # retire le demarrage automatique
    [switch]$Gui,                          # lance la fenetre graphique
    [switch]$Text,                         # console clavier, sans micro
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

$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"))) {
    throw "L'environnement virtuel est absent. Lance d'abord install.ps1."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Assistant vocal Jarvis"

if ($Gui -or $Text) {
    $mode = if ($Gui) { "--gui" } else { "--text" }
    $shortcut.TargetPath = $runBat
    $shortcut.Arguments = "$mode --lang fr $ExtraArgs".Trim()
    $shortcut.WindowStyle = 7        # 7 = fenetre reduite
} else {
    # Orbe : pythonw.exe n'ouvre aucune fenetre de console.
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "jarvis.py --orb --lang fr $ExtraArgs".Trim()
    $shortcut.WindowStyle = 1
}
$shortcut.Save()

Write-Host "Demarrage automatique installe." -ForegroundColor Green
Write-Host "    raccourci : $link"
Write-Host "    commande  : $($shortcut.TargetPath) $($shortcut.Arguments)"
Write-Host ""
Write-Host "Pour le retirer : powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Remove" -ForegroundColor Cyan
