$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
 & node scripts/build-brand.cjs
 if($LASTEXITCODE -ne 0){throw 'Brand build failed'}
 & npm.cmd test
 if($LASTEXITCODE -ne 0){throw 'Node tests failed'}
 $env:QT_QPA_PLATFORM='offscreen'
 & ./.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
 if($LASTEXITCODE -ne 0){throw 'Python tests failed'}
 & ./.venv/Scripts/python.exe scripts/audit-public.py
 if($LASTEXITCODE -ne 0){throw 'Public audit failed'}
} finally {Pop-Location}
