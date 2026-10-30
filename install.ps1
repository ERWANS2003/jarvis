# ===========================================================================
#  Jarvis - installation en une commande (Windows, PowerShell)
# ===========================================================================
#
#  Usage :
#    powershell -ExecutionPolicy Bypass -File .\install.ps1
#    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Optional
#    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Mvp
#
#  Ce script :
#    1. verifie que Python 3.10+ est disponible ;
#    2. cree l'environnement virtuel .venv ;
#    3. installe les dependances (requirements.txt) ;
#    4. installe en plus les briques hors-ligne (-Optional), ou seulement celles
#       de la version de presentation (-Mvp) ;
#    5. cree le fichier .env a partir de .env.example s'il manque ;
#    6. verifie que l'assistant demarre (--version).
# ===========================================================================

[CmdletBinding()]
param(
    [switch]$Optional,              # installe aussi requirements-optional.txt
    [switch]$Mvp,                   # installe requirements-mvp.txt et les voix manquantes
    [string]$Python = "python"      # interpreteur a utiliser
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "    $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "    $text" -ForegroundColor Yellow }

# --- 1. Python ------------------------------------------------------------ #
Write-Step "Verification de Python"
try {
    $version = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
} catch {
    throw "Python est introuvable. Installe-le depuis https://www.python.org/downloads/ puis relance ce script."
}
$parts = $version.Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    throw "Python 3.10 ou plus recent est requis (trouve : $version)."
}
Write-Ok "Python $version"

# --- 2. Environnement virtuel --------------------------------------------- #
$venv = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
if (Test-Path $venvPython) {
    Write-Step "Environnement virtuel deja present (.venv)"
} else {
    Write-Step "Creation de l'environnement virtuel (.venv)"
    & $Python -m venv $venv
    Write-Ok "cree"
}

# --- 3. Dependances ------------------------------------------------------- #
Write-Step "Mise a jour de pip"
& $venvPython -m pip install --upgrade pip --quiet

Write-Step "Installation des dependances (requirements.txt)"
& $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
Write-Ok "dependances principales installees"

if ($Optional) {
    Write-Step "Installation des dependances hors-ligne (requirements-optional.txt)"
    & $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements-optional.txt")
    Write-Ok "briques hors-ligne installees (Whisper, WebRTC VAD, pystray, Piper, openWakeWord)"

    Write-Step "Telechargement du mot d'activation « Jarvis » (Vosk) et de la voix Piper"
    $voskDir = Join-Path $PSScriptRoot "voices\vosk"
    New-Item -ItemType Directory -Force $voskDir | Out-Null
    $voskZip = Join-Path $voskDir "vosk-model-small-fr-0.22.zip"
    Invoke-WebRequest "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip" -OutFile $voskZip
    Expand-Archive $voskZip -DestinationPath $voskDir -Force
    Remove-Item $voskZip
    & $venvPython -c "import openwakeword.utils as u; u.download_models(model_names=['hey_jarvis_v0.1'])"
    & $venvPython -m piper.download_voices --download-dir (Join-Path $PSScriptRoot "voices") fr_FR-siwis-medium fr_FR-upmc-medium
    Write-Ok "voix installees (siwis, upmc : jessica et pierre) ; choix dans le menu Reglages de l'orbe"
} elseif ($Mvp) {
    Write-Step "Installation de la version de presentation (requirements-mvp.txt)"
    & $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements-mvp.txt")
    Write-Ok "orbe 3D, voix Piper et mot d'activation installes"

    $voicesDir = Join-Path $PSScriptRoot "voices"
    $voskDir = Join-Path $voicesDir "vosk"
    if (-not (Test-Path (Join-Path $voskDir "vosk-model-small-fr-0.22"))) {
        Write-Step "Telechargement du mot d'activation (Vosk)"
        New-Item -ItemType Directory -Force $voskDir | Out-Null
        $voskZip = Join-Path $voskDir "vosk-model-small-fr-0.22.zip"
        Invoke-WebRequest "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip" -OutFile $voskZip
        Expand-Archive $voskZip -DestinationPath $voskDir -Force
        Remove-Item $voskZip
    }
    if (-not (Test-Path (Join-Path $voicesDir "fr_FR-siwis-medium.onnx"))) {
        Write-Step "Telechargement de la voix Piper"
        & $venvPython -m piper.download_voices --download-dir $voicesDir fr_FR-siwis-medium
    }
} else {
    Write-Warn "briques hors-ligne ignorees (relance avec -Optional pour les ajouter)"
}

# --- 4. Fichier .env ------------------------------------------------------ #
Write-Step "Configuration des cles API"
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Write-Ok ".env deja present (inchange)"
} else {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile
    Write-Warn ".env cree a partir de .env.example : ouvre-le et renseigne ta cle API."
}

# --- 5. Verification ------------------------------------------------------ #
Write-Step "Verification de l'installation"
& $venvPython (Join-Path $PSScriptRoot "jarvis.py") --version
Write-Ok "Jarvis est installe"

Write-Host ""
Write-Host "Pour demarrer :" -ForegroundColor Cyan
Write-Host "    .\run.bat                 # conversation vocale"
Write-Host "    .\run.bat --text          # sans micro ni voix"
Write-Host "    .\run.bat --lang fr       # en francais"
Write-Host "    .\run.bat --gui           # fenetre graphique"
Write-Host "    .\run.bat --show_config   # afficher la configuration resolue"
Write-Host ""
Write-Host "Pour un demarrage automatique : .\autostart.ps1" -ForegroundColor Cyan
Write-Host ""
