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

# EXACTEMENT le dossier que monte docker-compose.gpu.yml, et il faut que les
# deux regles restent copie conforme : GPU_MODELES_DIR s'il est pose, sinon le
# cache Hugging Face du profil. Le dernier recours etait ici le volume Docker
# `modeles-gpu` et il ne l'est plus : depuis que le compose prend le cache du
# profil par defaut, telecharger dans le volume ferait descendre 34 Go dans un
# dossier que PLUS PERSONNE ne lit -- une heure de ligne pour rien, et le
# Studio continuerait a dire que les poids manquent.
$cacheHF = Join-Path $env:USERPROFILE ".cache\huggingface"
if ($env:GPU_MODELES_DIR) {
    $cible = $env:GPU_MODELES_DIR
} else {
    $cible = $cacheHF
    if (-not (Test-Path $cible)) { New-Item -ItemType Directory -Force -Path $cible | Out-Null }
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
