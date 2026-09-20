# Ce que le Studio occupe sur cet ordinateur, application par application --
# et comment en rendre une partie.
#
# Jumeau exact de `scripts/ressources.sh` ; `tests/test_ressources.py` garde les
# deux alignes.
#
# POURQUOI CE N'EST PAS UN BOUTON DANS LA PAGE, et ce n'est pas un detail.
# Vider une image ou un volume Docker demande la prise `/var/run/docker.sock`.
# La donner au service qui sert les pages, c'est donner les pleins pouvoirs sur
# la machine a n'importe quelle page -- et au code que le bac a sable execute,
# dont c'est tout le metier d'etre quelconque. Le Studio ne la monte nulle part,
# et ce script est la reponse : la personne lance elle-meme la commande, avec
# ses propres droits, le temps de la commande.
#
# NE SUPPRIME RIEN SANS ARGUMENT. Sans -Vider, il mesure et il affiche.
#
#   powershell -ExecutionPolicy Bypass -File scripts\ressources.ps1
#   ... -Vider <cle>     en rendre une ligne
#   ... -Vider tout      toutes les lignes telechargees
#   ... -Oui             sans poser la question (scripts)
param([string]$Vider = "", [switch]$Oui)
$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
Set-Location $Racine

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "  Docker n'est pas installe sur cette machine : rien a mesurer."
    exit 2
}

# --- tailles ----------------------------------------------------------------
# Docker rend ses tailles de volume en texte (<< 2.144GB >>, << 819.1MB >>).
function EnOctets([string]$t) {
    if (-not $t) { return 0 }
    if ($t -match '^([\d\.]+)\s*GB$') { return [int64]([double]$Matches[1] * 1e9) }
    if ($t -match '^([\d\.]+)\s*MB$') { return [int64]([double]$Matches[1] * 1e6) }
    if ($t -match '^([\d\.]+)\s*kB$') { return [int64]([double]$Matches[1] * 1e3) }
    if ($t -match '^([\d\.]+)\s*B$')  { return [int64][double]$Matches[1] }
    return 0
}
function Lisible([int64]$o) {
    if ($o -ge 1GB) { return ("{0:N2} Go" -f ($o / 1GB)) }
    if ($o -ge 1MB) { return ("{0:N1} Mo" -f ($o / 1MB)) }
    if ($o -gt 0)   { return ("{0:N0} ko" -f ($o / 1KB)) }
    return "-"
}
function TailleImage([string]$nom) {
    $s = & docker image inspect $nom --format '{{.Size}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $s) { return [int64]0 }
    return [int64]$s
}
function TailleDossier([string]$chemin) {
    if (-not (Test-Path -LiteralPath $chemin)) { return [int64]0 }
    $m = Get-ChildItem -LiteralPath $chemin -Recurse -File -Force -ErrorAction SilentlyContinue |
         Measure-Object -Property Length -Sum
    if ($null -eq $m.Sum) { return [int64]0 }
    return [int64]$m.Sum
}
# Un seul appel a `docker system df -v` : il est lent.
$volumes = @{}
try {
    $json = & docker system df -v --format '{{json .Volumes}}' 2>$null
    if ($json) { foreach ($v in ($json | ConvertFrom-Json)) { $volumes[$v.Name] = EnOctets $v.Size } }
} catch { }
function TailleVolume([string]$nom) { if ($volumes.ContainsKey($nom)) { return [int64]$volumes[$nom] } return [int64]0 }

# --- ou sont les choses -----------------------------------------------------
if ($env:GPU_MODELES_DIR) { $cache = $env:GPU_MODELES_DIR }
else { $cache = Join-Path $env:USERPROFILE ".cache\huggingface" }
$poidsVideo = Join-Path $cache "hub\models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
$projet = (Split-Path -Leaf $Racine).ToLower() -replace '[^a-z0-9_-]', ''

$oPoids  = TailleDossier $poidsVideo
$oImgGpu = TailleImage "free-ai-studio-sandbox-worker-gpu"
$oImgChat = [int64]0
foreach ($id in (& docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | Where-Object { $_ -match 'open-webui' } | ForEach-Object { ($_ -split ' ')[1] } | Sort-Object -Unique)) {
    $oImgChat += TailleImage $id
}
$oImgStudio = [int64]0
foreach ($i in @("free-ai-studio-free-tier-manager", "free-ai-studio-sandbox-manager", "free-ai-studio-sandbox-worker")) {
    $oImgStudio += TailleImage $i
}
$oWhisper = TailleVolume "${projet}_whisper-modeles"
$oTravail = TailleVolume "${projet}_sandbox-data"
$oConvers = TailleVolume "${projet}_open-webui-data"

$totalTelecharge = $oPoids + $oImgGpu + $oImgChat + $oImgStudio + $oWhisper
$totalTravail = $oTravail + $oConvers

# --- affichage --------------------------------------------------------------
Write-Host ""
Write-Host "  Place occupee par le Studio sur cet ordinateur" -ForegroundColor Cyan
Write-Host ""
"  {0,-22} {1,-42} {2,10}" -f "APPLICATION", "CE QUI EST SUR LE DISQUE", "TAILLE"
"  {0,-22} {1,-42} {2,10}" -f "----------------------", "------------------------------------------", "----------"
"  {0,-22} {1,-42} {2,10}   [video-poids]" -f "Video a la maison", "les 34 Go du modele video", (Lisible $oPoids)
"  {0,-22} {1,-42} {2,10}   [video-image]" -f "Video a la maison", "le bac a sable qui sait parler a la carte", (Lisible $oImgGpu)
"  {0,-22} {1,-42} {2,10}   [chat]" -f "Chat (Open WebUI)", "l'application de conversation", (Lisible $oImgChat)
"  {0,-22} {1,-42} {2,10}   [whisper]" -f "Ecoute des voix", "les modeles qui transcrivent", (Lisible $oWhisper)
"  {0,-22} {1,-42} {2,10}   [studio]" -f "Le Studio lui-meme", "ses trois services", (Lisible $oImgStudio)
Write-Host ""
"  {0,-22} {1,-42}" -f "VOTRE TRAVAIL", "jamais propose a la suppression ici"
"  {0,-22} {1,-42} {2,10}" -f "Vos fichiers", "l'espace de travail du bac a sable", (Lisible $oTravail)
"  {0,-22} {1,-42} {2,10}" -f "Vos conversations", "l'historique du chat", (Lisible $oConvers)
Write-Host ""
Write-Host ("  Telecharge : {0}     Votre travail : {1}" -f (Lisible $totalTelecharge), (Lisible $totalTravail))
Write-Host "  (les images Docker partagent des morceaux : le total telecharge est une borne haute)"
$d = Get-PSDrive -Name ($env:SystemDrive.TrimEnd(":"))
Write-Host ("  Disque : {0:N1} Go libres sur {1:N0} Go" -f ($d.Free/1GB), (($d.Free + $d.Used)/1GB))
Write-Host ""

if (-not $Vider) {
    Write-Host "  Pour en rendre une ligne :  ... -Vider <cle entre crochets>"
    Write-Host "  Pour tout le telecharge  :  ... -Vider tout"
    Write-Host ""
    exit 0
}

# --- vidage -----------------------------------------------------------------
# Ce qu'on perd, et ce qu'il en coute de revenir : dit AVANT la question, pour
# chaque ligne. Un vidage qui ne dit pas son prix n'est pas un choix.
switch ($Vider) {
    "video-poids" { $quoi = "les 34 Go du modele video"; $perte = "les clips partiront sur une machine louee tant qu'ils ne sont pas revenus"; $retour = "tout seul : au prochain clip demande a la maison, le Studio les retelecharge (~22 minutes) et vous propose d'attendre ou de louer" }
    "video-image" { $quoi = "le bac a sable qui parle a la carte"; $perte = "plus de video a la maison tant qu'il n'est pas refait"; $retour = "quelques minutes au prochain demarrage du Studio" }
    "chat"        { $quoi = "l'application de conversation"; $perte = "le chat ne demarre plus tant qu'il n'est pas retelecharge"; $retour = "quelques minutes au prochain demarrage du Studio" }
    "whisper"     { $quoi = "les modeles qui transcrivent"; $perte = "la premiere transcription sera plus lente"; $retour = "automatique, au premier besoin" }
    "studio"      { $quoi = "les trois services du Studio"; $perte = "le Studio est arrete le temps de se refaire"; $retour = "quelques minutes au prochain demarrage du Studio" }
    "tout"        { $quoi = "TOUT ce qui a ete telecharge ci-dessus"; $perte = "le Studio repart de zero, et les clips sont loues en attendant"; $retour = "22 minutes pour la video, quelques minutes pour le reste" }
    { $_ -in @("sandbox-data", "open-webui-data", "travail", "conversations") } {
        Write-Host "  Ce n'est pas une ressource telechargee : c'est VOTRE travail." -ForegroundColor Yellow
        Write-Host "  Ce script ne le supprime pas. Si c'est vraiment ce que vous voulez :"
        Write-Host "    docker volume rm ${projet}_sandbox-data      (vos fichiers)"
        Write-Host "    docker volume rm ${projet}_open-webui-data   (vos conversations)"
        exit 1
    }
    default {
        Write-Host "  Cle inconnue : $Vider"
        Write-Host "  Les cles sont entre crochets dans le tableau ci-dessus."
        exit 2
    }
}

Write-Host "  A vider : $quoi"
Write-Host "  Ce que vous perdez : $perte" -ForegroundColor Yellow
Write-Host "  Pour revenir : $retour" -ForegroundColor Yellow
Write-Host ""
if (-not $Oui) {
    $reponse = Read-Host "  Tapez oui pour vider, n'importe quoi d'autre pour annuler"
    if ($reponse.Trim().ToLower() -notin @("oui", "o", "yes", "y")) {
        Write-Host "  Annule. Rien n'a ete touche." -ForegroundColor Green
        exit 0
    }
}

# Une image ou un volume encore utilise fait refuser docker. On ne force pas et
# on n'arrete pas le Studio a la place de la personne : on dit quoi faire.
$script:code = 0
function Refus([string]$sortie) {
    Write-Host "  Docker a refuse : $sortie" -ForegroundColor Red
    Write-Host "  C'est qu'il est encore en service. Arretez le Studio puis relancez :"
    Write-Host "    docker compose down"
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\ressources.ps1 -Vider $Vider"
    $script:code = 1
}
function ViderPoids {
    # Une seule route pour effacer les 34 Go : le script dedie, avec ses gardes.
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "supprimer-modele-video.ps1") -Oui
    if ($LASTEXITCODE -ne 0) { $script:code = 1 }
}
function ViderImage([string]$nom) {
    $sortie = & docker image rm $nom 2>&1
    if ($LASTEXITCODE -ne 0) { Refus ($sortie -join " ") } else { Write-Host "  Rendu : $nom" -ForegroundColor Green }
}
function ViderVolume([string]$nom) {
    $sortie = & docker volume rm $nom 2>&1
    if ($LASTEXITCODE -ne 0) { Refus ($sortie -join " ") } else { Write-Host "  Rendu : $nom" -ForegroundColor Green }
}
function ImagesChat {
    & docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | Where-Object { $_ -match 'open-webui' } | ForEach-Object { ($_ -split ' ')[1] } | Sort-Object -Unique
}

switch ($Vider) {
    "video-poids" { ViderPoids }
    "video-image" { ViderImage "free-ai-studio-sandbox-worker-gpu" }
    "chat"        { foreach ($id in (ImagesChat)) { ViderImage $id } }
    "whisper"     { ViderVolume "${projet}_whisper-modeles" }
    "studio"      { foreach ($i in @("free-ai-studio-free-tier-manager", "free-ai-studio-sandbox-manager", "free-ai-studio-sandbox-worker")) { ViderImage $i } }
    "tout" {
        ViderPoids
        ViderImage "free-ai-studio-sandbox-worker-gpu"
        foreach ($id in (ImagesChat)) { ViderImage $id }
        ViderVolume "${projet}_whisper-modeles"
        foreach ($i in @("free-ai-studio-free-tier-manager", "free-ai-studio-sandbox-manager", "free-ai-studio-sandbox-worker")) { ViderImage $i }
    }
}

Write-Host ""
if ($script:code -eq 0) {
    Write-Host "  Fait. Relancez ce script pour voir la place rendue." -ForegroundColor Green
} else {
    Write-Host "  Une partie n'a pas pu etre rendue (voir au-dessus). Votre travail n'a pas ete touche." -ForegroundColor Yellow
}
exit $script:code
