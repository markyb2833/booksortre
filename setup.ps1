param(
    [switch]$SkipTests,
    [switch]$RefreshSeed,
    [switch]$Deploy
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$ParentRoot = Resolve-Path (Join-Path $ProjectRoot "..")
$VenvDir = Join-Path $ParentRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$InstanceDir = Join-Path $ProjectRoot "instance"
$LocalDb = Join-Path $InstanceDir "booksort.db"
$SeedDir = Join-Path $ProjectRoot "seed"
$SeedDb = Join-Path $SeedDir "booksort.seed.db"

Write-Host "BookSort setup starting..."

if (!(Test-Path $VenvPython)) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $python = Get-Command python -ErrorAction SilentlyContinue

    if ($pyLauncher) {
        & py -3.13 -m venv $VenvDir
    } elseif ($python) {
        & python -m venv $VenvDir
    } else {
        throw "Python was not found. Install Python 3.13, then run this script again."
    }
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Requirements

New-Item -ItemType Directory -Force -Path $InstanceDir, $SeedDir | Out-Null

if ((Test-Path $LocalDb) -and ($RefreshSeed -or !(Test-Path $SeedDb))) {
    Copy-Item -LiteralPath $LocalDb -Destination $SeedDb -Force
    Write-Host "Prepared seed database: seed\booksort.seed.db"
} elseif (!(Test-Path $LocalDb) -and (Test-Path $SeedDb)) {
    Copy-Item -LiteralPath $SeedDb -Destination $LocalDb
    Write-Host "Restored local database from seed\booksort.seed.db"
} elseif (!(Test-Path $LocalDb) -and !(Test-Path $SeedDb)) {
    Write-Host "No existing database found. The app will create an empty one on first start."
}

if (!$SkipTests) {
    Push-Location $ProjectRoot
    try {
        & $VenvPython -m unittest discover -s tests
        & $VenvPython -m compileall .
    } finally {
        Pop-Location
    }
}

if ($Deploy) {
    $railway = Get-Command railway -ErrorAction SilentlyContinue
    if (!$railway) {
        throw "Railway CLI was not found. Install it, log in with 'railway login', then rerun '.\setup.ps1 -Deploy'."
    }

    Push-Location $ProjectRoot
    try {
        & railway up
    } finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Local run: ..\.venv\Scripts\python.exe run.py"
Write-Host "Railway start command is configured in railway.json."
