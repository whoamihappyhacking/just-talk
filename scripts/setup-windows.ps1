param(
    [switch]$SkipDeps,
    [switch]$WithBuildTools,
    [string]$PythonId = "Python.Python.3.13",
    [string]$UvId = "AstralSoftware.uv"
)

$ErrorActionPreference = "Stop"
$pypiIndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
$pypiHost = "pypi.tuna.tsinghua.edu.cn"
$pipArgs = @("-i", $pypiIndexUrl, "--trusted-host", $pypiHost)

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

$hasWinget = Test-Command "winget"
if (-not $hasWinget) {
    Write-Warning "winget not found; skipping automatic installation steps."
}

if (-not (Test-Command "python")) {
    if ($hasWinget) {
        Write-Host "Installing Python via winget..."
        winget install --id $PythonId --source winget --accept-package-agreements --accept-source-agreements
    } else {
        Write-Error "python not found. Install Python 3.13+ from python.org or Microsoft Store, then re-run."
        exit 1
    }
} else {
    $pyVersion = & python --version 2>&1
    Write-Host "Python already installed: $pyVersion"
}

if (-not (Test-Command "uv")) {
    if ($hasWinget) {
        Write-Host "Installing uv via winget..."
        winget install --id $UvId --source winget --accept-package-agreements --accept-source-agreements
    } else {
        Write-Warning "uv not found; will use venv + pip for project dependencies."
    }
} else {
    $uvVersion = & uv --version 2>&1
    Write-Host "uv already installed: $uvVersion"
}

if ($SkipDeps) {
    Write-Host "Skipping project dependencies setup."
    exit 0
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not (Test-Path (Join-Path $repoRoot "pyproject.toml"))) {
    Write-Host "No pyproject.toml found under $repoRoot; skipping dependencies."
    exit 0
}

Set-Location $repoRoot

$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    Write-Host "Installing project dependencies with uv..."
    $env:UV_INDEX_URL = $pypiIndexUrl
    $env:PIP_INDEX_URL = $pypiIndexUrl
    $env:PIP_TRUSTED_HOST = $pypiHost
    uv sync --extra build
    exit $LASTEXITCODE
}

Write-Host "uv not available in current session; using venv + pip."
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$venvPython = Join-Path ".venv" "Scripts\\python.exe"
& $venvPython -m pip install -U @pipArgs pip

if (Test-Path "requirements.txt") {
    & $venvPython -m pip install -U @pipArgs -r requirements.txt
}

if ($WithBuildTools) {
    & $venvPython -m pip install -U @pipArgs pyinstaller pyinstaller-hooks-contrib
}

exit $LASTEXITCODE
