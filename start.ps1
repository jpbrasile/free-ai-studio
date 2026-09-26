$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    throw ".env absent. Lancez .\install.ps1"
}

# --- La carte de la maison, si elle existe ------------------------------------
# Pendant de `start.sh` et de `scripts/demarrer.ps1` : la surcouche
# docker-compose.gpu.yml n'est ajoutee QUE si une carte repond. Une reservation
# `driver: nvidia` sur une machine sans carte fait ECHOUER `docker compose up`,
# et le debutant sans carte -- le cas le plus courant -- ne doit jamais
# rencontrer ce message : sans carte, la commande reste exactement celle d'avant.
#
# Corrige le 26/09/2026 (PLAN.md, SP-CARTE-DEBRANCHEE-AU-REDEMARRAGE). Ce
# lanceur faisait un `docker compose up -d` nu : sur une machine AVEC carte, il
# recreait le gestionnaire sans SANDBOX_WORKER_GPU_URL, le Studio disait
# calmement << pas de carte branchee >> pendant que sandbox-worker-gpu tournait
# a cote, et le clip partait chez le loueur (~0,24 $ mesure le 22/09).
# `tests/test_lanceurs_surcouche.py` compare les lanceurs sur ce point.
# Code de retour teste, jamais la seule presence du binaire ; try/catch parce
# que, sous $ErrorActionPreference = "Stop", une ligne d'erreur de nvidia-smi
# deviendrait une exception.
$argsCompose = @("compose", "-f", "docker-compose.yml")
$carte = $null
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    try {
        $releve = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
        if ($LASTEXITCODE -eq 0 -and $releve) { $carte = ($releve | Select-Object -First 1).Trim() }
    } catch { $carte = $null }
}
if ($carte) {
    $argsCompose += @("-f", "docker-compose.gpu.yml")
    Write-Host "Carte graphique vue : $carte"

    # Le meme dossier de poids que demarrer.ps1 et start.sh : la variable
    # d'abord, le cache du profil ensuite, et le .env n'est jamais modifie.
    $cacheHF = Join-Path $env:USERPROFILE ".cache\huggingface"
    if ($env:GPU_MODELES_DIR) {
        $modeles = $env:GPU_MODELES_DIR
        Write-Host "   Modeles pris la ou vous les gardez : $modeles"
    } elseif (Test-Path (Join-Path $cacheHF "hub")) {
        $modeles = $cacheHF
        $env:GPU_MODELES_DIR = $cacheHF
        Write-Host "   Modeles deja telecharges reutilises : $cacheHF"
    } else {
        $modeles = $cacheHF
    }
    $poids = Join-Path $modeles "hub\models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
    if (-not (Test-Path $poids)) {
        Write-Host "   Carte presente, mais le modele video (34 Go) n'est pas telecharge."
        Write-Host "   Les clips partiront sur une machine louee tant qu'il manque."
        Write-Host "   Pour le descendre une fois : scripts\telecharger-modele-video.ps1"
    }
}

& docker @($argsCompose + @("up", "-d"))
& docker @($argsCompose + @("ps"))

# Veilleur de mise a jour : c'est lui qui rend le bouton « Mettre a jour » de la
# page Studio capable d'agir. Il tourne sous votre compte, sans fenetre, repart
# seul a chaque ouverture de session et ne se lance jamais en double ; il ne
# touche a rien tant que vous n'avez pas clique. Sans lui, le bouton renvoie
# vers le double-clic sur demarrer.cmd. Guillemets autour du chemin : sans eux,
# un dossier avec une espace coupe l'appel en deux.
$veilleuse = Join-Path $PSScriptRoot "scripts\maj-veilleuse.ps1"
if (Test-Path $veilleuse) {
    Start-Process -FilePath "powershell" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", ('"' + $veilleuse + '"')) `
        -WorkingDirectory $PSScriptRoot -WindowStyle Hidden | Out-Null
    Write-Host "Veilleur de mise a jour lance (sans fenetre)."
}

# Sonde de la carte : dit au Studio qui d'autre se sert de la carte graphique
# (config\etat-carte-hote.json). Sans elle, la carte est comptee prise et les
# clips partent sur une machine louee. Elle ne se lance jamais en double.
$sonde = Join-Path $PSScriptRoot "scripts\sonde-carte.ps1"
if (Test-Path $sonde) {
    Start-Process -FilePath "powershell" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", ('"' + $sonde + '"')) `
        -WorkingDirectory $PSScriptRoot -WindowStyle Hidden | Out-Null
    Write-Host "Sonde de la carte lancee (sans fenetre)."
}

Write-Host ""
Write-Host "Free AI Studio / Open WebUI : http://localhost:3000"

Write-Host "`nFree AI Studio (débutant) : http://127.0.0.1:8010/studio"
Write-Host "Chat : http://localhost:3000"
Write-Host "Sandbox : http://127.0.0.1:8020"

Write-Host "Vérification : .\scripts\self-test.ps1"
