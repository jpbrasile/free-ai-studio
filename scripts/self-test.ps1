$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python est requis pour l'auto-test." }
if ($python.Name -eq "py.exe" -or $python.Name -eq "py") { & $python.Source -3 "scripts/self-test.py" } else { & $python.Source "scripts/self-test.py" }
exit $LASTEXITCODE
