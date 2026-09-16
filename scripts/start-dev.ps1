$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskPython=Join-Path $taskRoot '.venv/Scripts/python.exe'
if(-not (Test-Path -LiteralPath $taskPython)){throw 'Run scripts/setup-dev.ps1 first.'}
$env:NV_DESKTOP_ROOT=$taskRoot
$env:NV_DESKTOP_DATA=Join-Path $env:APPDATA 'SeqaraHarnessDemo'
& $taskPython (Join-Path $taskRoot 'native/desktop.py')
exit $LASTEXITCODE
