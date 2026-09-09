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

# UTF-8 sans BOM : préserve les accents des commentaires du .env sur PowerShell 5.1,
# dont Get-Content/Set-Content utilisent sinon l'encodage ANSI de la machine.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$envPath = Join-Path $PSScriptRoot ".env"

function New-HexSecret {
    param([int]$ByteCount = 32)
    $bytes = New-Object byte[] $ByteCount
    # RandomNumberGenerator::Fill n'existe que sur .NET Core (PowerShell 7+).
    # Create().GetBytes() existe sur .NET Framework 4.x (PowerShell 5.1) ET sur .NET Core.
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return (-join ($bytes | ForEach-Object { $_.ToString("x2") }))
}

foreach ($name in @("WEBUI_SECRET_KEY", "FREE_TIER_MANAGER_KEY", "SANDBOX_MANAGER_KEY", "SANDBOX_WORKER_KEY")) {
    $content = [System.IO.File]::ReadAllText($envPath, $utf8NoBom)
    if ($content -notmatch "(?m)^$name=.+$") {
        $value = New-HexSecret 32
        $content = [regex]::Replace($content, "(?m)^$name=.*$", "$name=$value")
        if ($content -notmatch "(?m)^$name=") { $content += "`n$name=$value`n" }
        [System.IO.File]::WriteAllText($envPath, $content, $utf8NoBom)
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
