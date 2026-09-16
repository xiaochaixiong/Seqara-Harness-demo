$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
 $taskPython=Join-Path $taskRoot '.venv/Scripts/python.exe'
 if(-not (Test-Path $taskPython)){throw 'Run scripts/setup-dev.ps1 first'}
 & $taskPython -m PyInstaller --noconfirm --distpath backend-bin --workpath outputs/worker-build scripts/worker.spec
 if($LASTEXITCODE -ne 0){throw 'Worker build failed'}
} finally {Pop-Location}
