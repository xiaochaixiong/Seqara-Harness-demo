param([string]$PythonPath='')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
 if(-not (Test-Path '.venv/Scripts/python.exe')){
  if($PythonPath){ & $PythonPath -m venv .venv }else{ & py -3.14 -m venv .venv }
  if($LASTEXITCODE -ne 0){throw 'Python environment creation failed'}
 }
 & ./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
 if($LASTEXITCODE -ne 0){throw 'Dependency installation failed'}
 & npm.cmd ci --prefix runtime
 if($LASTEXITCODE -ne 0){throw 'Runtime dependency installation failed'}
 & node scripts/build-brand.cjs
 if($LASTEXITCODE -ne 0){throw 'Runtime compatibility patch failed'}
} finally {Pop-Location}
