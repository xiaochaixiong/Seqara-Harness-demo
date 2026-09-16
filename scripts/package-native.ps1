param([string]$PythonPath='', [switch]$SkipBuild)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
 if(-not $PythonPath){$PythonPath=Join-Path $taskRoot '.venv/Scripts/python.exe'}
 if(-not $SkipBuild){
 if(-not (Test-Path -LiteralPath $PythonPath)){throw 'Run scripts/setup-dev.ps1 or pass -PythonPath'}
 & $PythonPath scripts/build-app-icon.py
 if($LASTEXITCODE -ne 0){throw 'Application icon build failed'}
 & node scripts/build-brand.cjs
 if($LASTEXITCODE -ne 0){throw 'Brand build failed'}
 & $PythonPath -m PyInstaller --noconfirm --distpath backend-bin --workpath outputs/worker-build scripts/worker.spec
 if($LASTEXITCODE -ne 0){throw 'Worker build failed'}
 & $PythonPath -m PyInstaller --noconfirm --distpath native-bin --workpath outputs/native-build scripts/native.spec
 if($LASTEXITCODE -ne 0){throw 'Native build failed'}
 }
 & $PythonPath scripts/package-public.py
 if($LASTEXITCODE -ne 0){throw 'Public packaging failed'}
} finally {Pop-Location}
