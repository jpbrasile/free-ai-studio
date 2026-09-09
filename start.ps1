$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    throw ".env absent. Lancez .\install.ps1"
}

docker compose up -d
docker compose ps
Write-Host ""
Write-Host "Free AI Studio / Open WebUI : http://localhost:3000"

Write-Host "`nFree AI Studio (débutant) : http://127.0.0.1:8010/studio"
Write-Host "Chat : http://localhost:3000"
Write-Host "Sandbox : http://127.0.0.1:8020"

Write-Host "Vérification : .\scripts\self-test.ps1"
