$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    throw ".env absent. Lancez .\install.ps1"
}

docker compose up -d
docker compose ps

# Veilleur de mise a jour : c'est lui qui rend le bouton « Mettre a jour » de la
# page Studio capable d'agir. Il tourne sous votre compte, dans sa propre
# fenetre, et ne touche a rien tant que vous n'avez pas clique. Sans lui, le
# bouton renvoie simplement vers le double-clic sur mettre-a-jour.cmd.
$veilleuse = Join-Path $PSScriptRoot "scripts\maj-veilleuse.ps1"
if (Test-Path $veilleuse) {
    Start-Process -FilePath "powershell" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $veilleuse) `
        -WorkingDirectory $PSScriptRoot | Out-Null
    Write-Host "Veilleur de mise a jour lance (fenetre separee)."
}

Write-Host ""
Write-Host "Free AI Studio / Open WebUI : http://localhost:3000"

Write-Host "`nFree AI Studio (débutant) : http://127.0.0.1:8010/studio"
Write-Host "Chat : http://localhost:3000"
Write-Host "Sandbox : http://127.0.0.1:8020"

Write-Host "Vérification : .\scripts\self-test.ps1"
