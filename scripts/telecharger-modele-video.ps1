# Telecharge une seule fois les poids du modele video de la maison (34 Go).
#
# Pourquoi il faut un script pour ca : le bac a sable qui fabrique les clips est
# sur un reseau SANS internet -- c'est ce qui rend sur d'y executer du code
# quelconque. Il ne peut donc pas telecharger les poids lui-meme. Ce script
# lance un conteneur qui a le droit d'aller sur le reseau, et qui ecrit dans le
# MEME dossier que le bac a sable lira ensuite.
#
# A lancer depuis le dossier du Studio :
#   powershell -ExecutionPolicy Bypass -File scripts\telecharger-modele-video.ps1
$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
Set-Location $Racine

Write-Host ""
Write-Host "  Modele video de la maison -- telechargement unique" -ForegroundColor Cyan
Write-Host "  Environ 34 Go. Comptez une demi-heure a une heure selon la ligne."
Write-Host ""

# Le meme dossier que celui monte par docker-compose.gpu.yml : le cache Hugging
# Face du profil s'il existe (celui qu'un modele deja telecharge a rempli),
# sinon le volume Docker `modeles-gpu`.
$cacheHF = Join-Path $env:USERPROFILE ".cache\huggingface"
if ($env:GPU_MODELES_DIR) {
    $cible = $env:GPU_MODELES_DIR
} elseif (Test-Path (Join-Path $cacheHF "hub")) {
    $cible = $cacheHF
} else {
    $cible = "modeles-gpu"          # nom de volume Docker, pas un chemin
}
Write-Host "  Destination : $cible"

# L'image du bac a sable GPU porte deja huggingface_hub : rien a installer.
$image = "free-ai-studio-sandbox-worker-gpu"
$existe = & docker image inspect $image 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  L'image du bac a sable GPU n'existe pas encore." -ForegroundColor Yellow
    Write-Host "  Lancez d'abord le Studio (scripts\demarrer.ps1) sur une machine qui a une carte."
    exit 2
}

# --user root : le cache du profil appartient a l'utilisateur Windows ; le
# compte non privilegie de l'image ne peut pas toujours y ecrire. La lecture,
# elle, fonctionne, et c'est tout ce dont le bac a sable a besoin ensuite.
& docker run --rm `
    -v "${cible}:/cache/huggingface" `
    -v "${Racine}\scripts:/scripts:ro" `
    -e HF_HOME=/cache/huggingface `
    -e HF_HUB_DISABLE_XET=1 `
    -e PYTHONUNBUFFERED=1 `
    --user root `
    $image python /scripts/telecharger_modele_video.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "  Fait. Le prochain clip partira sur la carte de cet ordinateur, gratuitement." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  Le telechargement a echoue (code $LASTEXITCODE). Relancez : il reprend ou il s'est arrete." -ForegroundColor Red
}
exit $LASTEXITCODE
