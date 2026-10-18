# Lance l'assistant Jarvis.
# Cles API, modele et langue sont lus depuis le fichier .env (non versionne).
# La voix est detectee automatiquement selon la langue (--lang en|fr).
#
# Par defaut, ce script ouvre la fenetre graphique (Horizon 6).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 --lang fr
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 --no-gui
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 --ptt --no-bargein
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 --text
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 --local_model llama3.2

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# --- Verifier l'environnement virtuel ---
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "L'environnement virtuel est absent." -ForegroundColor Yellow
    Write-Host "Lance d'abord : powershell -ExecutionPolicy Bypass -File .\install.ps1" -ForegroundColor Yellow
    exit 1
}

# --- Charger les variables du fichier .env ---
if (Test-Path .env) {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
        }
    }
}

# --- Avertir seulement si aucune cle n'est disponible --------------------- #
# (un modele local via Ollama ou --local_model fonctionne sans cle).
$hasKey = @('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'JARVIS_API_KEY',
            'GROQ_API_KEY') | Where-Object {
    -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_))
}
$usesLocal = ($args -contains '--local_model') -or
             (-not [string]::IsNullOrWhiteSpace($env:JARVIS_LOCAL_MODEL))
if (-not $hasKey -and -not $usesLocal) {
    Write-Host "Aucune cle API trouvee : Jarvis tentera un modele local, ou l'indiquera a l'ecran." -ForegroundColor Yellow
    Write-Host "Renseigne OPENROUTER_API_KEY dans .env (voir .env.example), ou lance avec --local_model." -ForegroundColor Yellow
}

& ".\.venv\Scripts\python.exe" -u jarvis.py @args
exit $LASTEXITCODE
