$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== Free AI Studio : installation =="

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker n'est pas installé. Consultez docs/INSTALLATION.md"
}

docker compose version | Out-Null

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env créé depuis .env.example"
}

$content = Get-Content ".env" -Raw
if ($content -notmatch "(?m)^WEBUI_SECRET_KEY=.+$") {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $secret = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $content = [regex]::Replace($content, "(?m)^WEBUI_SECRET_KEY=.*$", "WEBUI_SECRET_KEY=$secret")
    Set-Content ".env" $content -NoNewline
    Write-Host "WEBUI_SECRET_KEY générée."
}

$content = Get-Content ".env" -Raw
if ($content -notmatch "(?m)^FREE_TIER_MANAGER_KEY=.+$") {
    $bytes2 = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes2)
    $managerKey = -join ($bytes2 | ForEach-Object { $_.ToString("x2") })
    $content = [regex]::Replace($content, "(?m)^FREE_TIER_MANAGER_KEY=.*$", "FREE_TIER_MANAGER_KEY=$managerKey")
    Set-Content ".env" $content -NoNewline
    Write-Host "FREE_TIER_MANAGER_KEY générée."
}


foreach ($name in @("SANDBOX_MANAGER_KEY", "SANDBOX_WORKER_KEY")) {
    $content = Get-Content ".env" -Raw
    if ($content -notmatch "(?m)^$name=.+$") {
        $b = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Fill($b)
        $value = -join ($b | ForEach-Object { $_.ToString("x2") })
        $content = [regex]::Replace($content, "(?m)^$name=.*$", "$name=$value")
        if ($content -notmatch "(?m)^$name=") { $content += "`n$name=$value`n" }
        Set-Content ".env" $content -NoNewline
        Write-Host "$name générée."
    }
}

Write-Host "Téléchargement de l'image Open WebUI..."
docker compose pull

Write-Host ""
Write-Host "Installation prête. Lancez .\start.ps1"
Write-Host "Puis vérifiez avec .\scripts\self-test.ps1"

Write-Host "`nFree AI Studio (débutant) : http://127.0.0.1:8010/studio"
Write-Host "Chat : http://localhost:3000"
Write-Host "Sandbox : http://127.0.0.1:8020 (Modal-first si configure; boutons Colab/Kaggle conserves)"
