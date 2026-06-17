<#
  build_installer.ps1
  Assembles a portable, embedded Python 3.11.9 runtime + the Forge backend
  into src-tauri/resources, then builds a zero-dependency MSI installer.

  Run from the project root:
      powershell -ExecutionPolicy Bypass -File build_installer.ps1
#>

$ErrorActionPreference = "Stop"

$PythonVersion   = "3.11.9"
$PythonZipUrl    = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl       = "https://bootstrap.pypa.io/get-pip.py"

$ProjectRoot     = Get-Location
$ResourcesDir    = Join-Path $ProjectRoot "src-tauri\resources"
$PythonDir       = Join-Path $ResourcesDir "python"
$BackendSrcDir   = Join-Path $ProjectRoot "python_backend"
$BackendDestDir  = Join-Path $ResourcesDir "python_backend"
$ConfigTemplate  = Join-Path $ProjectRoot "config.template.json"
$TempDir         = Join-Path $env:TEMP "forge_build_$([guid]::NewGuid())"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# ── 0. Sanity checks ────────────────────────────────────────────────────────
Write-Step "Running sanity checks"

if (-not (Test-Path $BackendSrcDir)) {
    throw "python_backend\ not found. Run this script from the project root."
}
if (-not (Test-Path $ConfigTemplate)) {
    throw "config.template.json not found at project root."
}
$reqFile = Join-Path $ProjectRoot "python_backend\requirements-embed.txt"
if (-not (Test-Path $reqFile)) {
    throw @"
requirements-embed.txt not found in python_backend\.
Create it — same as requirements.txt but without dev-only tools
(pyinstaller, pytest, etc.). It is the dependency list that gets
baked into the MSI's embedded Python.
"@
}

New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

# ── 1. Clean previous resources ─────────────────────────────────────────────
Write-Step "Cleaning previous build output"
if (Test-Path $ResourcesDir) { Remove-Item -Recurse -Force $ResourcesDir }
New-Item -ItemType Directory -Force -Path $PythonDir       | Out-Null
New-Item -ItemType Directory -Force -Path $BackendDestDir  | Out-Null

# ── 2. Download + extract embeddable Python ─────────────────────────────────
Write-Step "Downloading embeddable Python $PythonVersion"
$pythonZipPath = Join-Path $TempDir "python-embed.zip"
Invoke-WebRequest -Uri $PythonZipUrl -OutFile $pythonZipPath
Expand-Archive -Path $pythonZipPath -DestinationPath $PythonDir -Force

# ── 3. Enable site-packages (disabled by default in the embeddable distro) ──
Write-Step "Enabling site-packages in the embedded interpreter"
$pthFile = Get-ChildItem -Path $PythonDir -Filter "python3*._pth" | Select-Object -First 1
if (-not $pthFile) { throw "Could not locate the ._pth file in the embedded distro." }
(Get-Content $pthFile.FullName) -replace '^\s*#\s*import site', 'import site' |
    Set-Content $pthFile.FullName

# ── 4. Bootstrap pip ─────────────────────────────────────────────────────────
Write-Step "Installing pip into the embedded interpreter"
$getPipPath = Join-Path $TempDir "get-pip.py"
Invoke-WebRequest -Uri $GetPipUrl -OutFile $getPipPath
& "$PythonDir\python.exe" $getPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip.py failed (exit code $LASTEXITCODE)." }

# ── 5. Install runtime dependencies ─────────────────────────────────────────
Write-Step "Installing Python dependencies (this can take a few minutes)"
& "$PythonDir\python.exe" -m pip install -r $reqFile --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit code $LASTEXITCODE)." }

# Note: Chromium is intentionally NOT installed here. Per the chosen
# distribution strategy, app.py downloads it into the user's profile on
# first launch (see _ensure_playwright_chromium in app.py) so the MSI
# itself stays small and still requires no developer tooling to install.

# ── 6. Copy the backend source (app.py, agent.py, tools/, etc.) ─────────────
Write-Step "Copying backend source into resources"

# $ErrorActionPreference must be set to Continue around robocopy because
# robocopy uses non-zero exit codes (1-7) to signal SUCCESS (e.g. "files
# copied", "nothing to do"), which PowerShell's "Stop" mode misreads as
# errors and aborts the script. We capture the code ourselves and only
# treat codes >= 8 as genuine failures.
$ErrorActionPreference = "Continue"
robocopy $BackendSrcDir $BackendDestDir /E `
    /XD ".venv" "chrome_profile" "__pycache__" `
    /XF "requirements.txt" "requirements-embed.txt" "*.pyc"
$robocopyExit = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($robocopyExit -ge 8) {
    throw "robocopy failed while copying python_backend (exit code $robocopyExit)."
}

Copy-Item $ConfigTemplate (Join-Path $ResourcesDir "config.template.json") -Force

# ── 7. Trim build artifacts to keep the MSI lean ────────────────────────────
Write-Step "Cleaning up build artifacts"
Remove-Item -Force (Join-Path $PythonDir "get-pip.py") -ErrorAction SilentlyContinue

# Remove all __pycache__ dirs under the entire resources tree
# (covers both the embedded Python's Lib/ tree and the copied backend)
Get-ChildItem -Path $ResourcesDir -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Remove .pyc files anywhere under resources (belt-and-suspenders)
Get-ChildItem -Path $ResourcesDir -Recurse -File -Filter "*.pyc" |
    Remove-Item -Force -ErrorAction SilentlyContinue

# ── 8. Frontend deps (only if missing) ──────────────────────────────────────
if (-not (Test-Path (Join-Path $ProjectRoot "node_modules"))) {
    Write-Step "Installing frontend dependencies"
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit code $LASTEXITCODE)." }
}

# ── 9. Build — MSI only ─────────────────────────────────────────────────────
Write-Step "Building MSI installer"
npx tauri build --bundles msi --config src-tauri/tauri.release.conf.json
if ($LASTEXITCODE -ne 0) { throw "tauri build failed (exit code $LASTEXITCODE)." }

# ── 10. Report output ────────────────────────────────────────────────────────
Write-Step "Done"
$msiDir = Join-Path $ProjectRoot "src-tauri\target\release\bundle\msi"
Write-Host "Installer output: $msiDir" -ForegroundColor Green
Get-ChildItem $msiDir -Filter "*.msi" | ForEach-Object {
    Write-Host " - $($_.FullName)" -ForegroundColor Green
}

# ── Cleanup temp dir ─────────────────────────────────────────────────────────
Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue