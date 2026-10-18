# ===========================================================================
#  Jarvis - fabrication d'un executable autonome (optionnel)
# ===========================================================================
#
#  Produit un dossier dist\Jarvis\ contenant Jarvis.exe, qui n'a plus besoin
#  de Python ni de l'environnement virtuel sur la machine cible.
#
#  Usage :
#    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
#    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -OneFile
#    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Windowed
#    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Clean
#
#  Remarques :
#  - PyInstaller n'est pas une dependance du projet : ce script l'installe
#    dans .venv au premier lancement.
#  - L'executable embarque le paquet jarvis_core, le dossier plugins et les
#    fichiers .env.example / README.md, mais PAS le fichier .env (ta cle API
#    reste sur ta machine : place un .env a cote de Jarvis.exe).
#  - Par defaut la console reste visible (journal utile et mode --no-gui) ;
#    -Windowed la masque pour ne garder que la fenetre graphique.
#  - La reconnaissance vocale utilisant les services Google, l'assistant a
#    besoin d'Internet ; le mode hors-ligne (Whisper/Ollama) fonctionne si tu
#    as installe requirements-optional.txt AVANT de fabriquer l'executable.
# ===========================================================================

[CmdletBinding()]
param(
    [switch]$OneFile,        # un seul fichier .exe (plus lent au demarrage)
    [switch]$Windowed,       # masque la console : fenetre graphique seule
    [switch]$Clean,          # supprime build\ et dist\ avant de reconstruire
    [string]$Name = "Jarvis"
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "L'environnement virtuel est absent. Lance d'abord install.ps1."
}

if ($Clean) {
    foreach ($dir in @("build", "dist")) {
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    }
    if (Test-Path "$Name.spec") { Remove-Item "$Name.spec" -Force }
}

# --- 1. PyInstaller ------------------------------------------------------- #
Write-Host "==> Verification de PyInstaller" -ForegroundColor Cyan
& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    installation de PyInstaller..." -ForegroundColor Yellow
    & $python -m pip install "pyinstaller>=6.0"
}
Write-Host "    PyInstaller disponible" -ForegroundColor Green

# --- 2. Options de compilation -------------------------------------------- #
# Les paquets LangChain/LangGraph se chargent dynamiquement : il faut les
# collecter en entier, sinon l'executable echoue au premier appel au modele.
$args_list = @(
    "--noconfirm",
    "--name", $Name,
    "--add-data", "plugins;plugins",
    "--add-data", ".env.example;.",
    "--add-data", "README.md;.",
    "--collect-all", "langchain_core",
    "--collect-all", "langgraph",
    "--collect-all", "langchain",
    "--collect-all", "pyttsx3",
    "--hidden-import", "speech_recognition",
    "--hidden-import", "pyaudio",
    "--hidden-import", "yaml",
    "--hidden-import", "requests",
    "--hidden-import", "tkinter",
    "--hidden-import", "tkinter.filedialog",
    "--hidden-import", "tkinter.messagebox",
    "--hidden-import", "tkinter.font",
    "--hidden-import", "tkinter.scrolledtext"
)

if ($Windowed) {
    $args_list += "--windowed"
    Write-Host "==> Console masquee (-Windowed)" -ForegroundColor Cyan
} else {
    $args_list += "--console"
}

if ($OneFile) {
    $args_list += "--onefile"
    Write-Host "==> Mode : un seul fichier" -ForegroundColor Cyan
} else {
    $args_list += "--onedir"
    Write-Host "==> Mode : dossier (demarrage plus rapide)" -ForegroundColor Cyan
}

# --- 3. Compilation ------------------------------------------------------- #
Write-Host "==> Compilation (cela peut prendre plusieurs minutes)" -ForegroundColor Cyan
& $python -m PyInstaller @args_list jarvis.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller a echoue (code $LASTEXITCODE)."
}

# --- 4. Finition ---------------------------------------------------------- #
$target = if ($OneFile) { Join-Path $PSScriptRoot "dist\$Name.exe" }
          else { Join-Path $PSScriptRoot "dist\$Name" }

foreach ($extra in @("run.bat", "README.md", ".env.example")) {
    if (Test-Path $extra) {
        Copy-Item $extra (Join-Path $target "") -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Executable cree : $target" -ForegroundColor Green
Write-Host "N'oublie pas de placer un fichier .env a cote de l'executable." -ForegroundColor Cyan
