param(
    [string]$BinaryName = "just-talk-win64",
    [string]$Icon = "icon.ico",
    [switch]$Console
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$env:JT_BINARY_NAME = $BinaryName
$env:JT_ONEFILE = "1"
$env:JT_CONSOLE = if ($Console) { "1" } else { "0" }

if (Test-Path $Icon) {
    $env:JT_ICON = $Icon
} else {
    Remove-Item Env:JT_ICON -ErrorAction SilentlyContinue
    Write-Warning "Icon not found at '$Icon'; building without icon."
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    uv sync --extra build
    uv run pyinstaller just_talk.spec
    exit $LASTEXITCODE
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "python not found. Install uv or Python 3.13+."
    exit 1
}

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$venvPython = Join-Path ".venv" "Scripts\\python.exe"
& $venvPython -m pip install -U pip
& $venvPython -m pip install -U -r requirements.txt pyinstaller pyinstaller-hooks-contrib
& $venvPython -m pyinstaller just_talk.spec
exit $LASTEXITCODE
