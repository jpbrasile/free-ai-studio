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

# --- dates ------------------------------------------------------------------
# << Renouvele le >> = la date ou la chose est arrivee SUR CETTE MACHINE, pas
# celle ou son auteur l'a publiee. C'est elle qui repond a la question du
# client : depuis quand est-ce que ca dort la. Vider puis reutiliser la remet a
# aujourd'hui -- c'est exactement ce que << renouvele >> veut dire ici.
function JourIso([string]$t) {
    if ($t -match '^(\d{4})-(\d{2})-(\d{2})') {
        return ("{0}/{1}/{2}" -f $Matches[3], $Matches[2], $Matches[1])
    }
    return "-"
}
# Rend AAAA-MM-JJ et rien d'autre : `LastTagTime` sort avec des espaces
# (<< 2026-09-20 08:19:56.278 +0000 UTC >>), et un mot coupe sur un espace fait
# comparer << UTC >> a une date. `LastTagTime` est le jour ou l'image a atterri
# ici, construite ou tiree ; `.Created` est celui de son auteur, c'est le repli
# et il est moins bon.
function IsoImage([string]$nom) {
    $t = [string](& docker image inspect $nom --format '{{.Metadata.LastTagTime}}' 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $t -or $t.StartsWith("0001-01-01")) {
        $t = [string](& docker image inspect $nom --format '{{.Created}}' 2>$null)
    }
    if (-not $t) { return "" }
    return $t.Substring(0, [Math]::Min(10, $t.Length))
}
function IsoMax([string[]]$liste) {
    $m = ""
    foreach ($t in $liste) { if ($t -gt $m) { $m = $t } }
    return $m
}
function DateImage([string]$nom) { return (JourIso (IsoImage $nom)) }
# Le fichier le plus recemment ecrit, et non la date du dossier : un
# telechargement repris ajoute des fichiers sans toucher au dossier du dessus.
function DateDossier([string]$chemin) {
    if (-not (Test-Path -LiteralPath $chemin)) { return "-" }
    $f = Get-ChildItem -LiteralPath $chemin -Recurse -File -Force -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $f) { return "-" }
    return $f.LastWriteTime.ToString("dd/MM/yyyy")
}
function DateVolume([string]$nom) {
    $t = [string](& docker volume inspect $nom --format '{{.CreatedAt}}' 2>$null)
    if ($LASTEXITCODE -ne 0) { return "-" }
    return (JourIso $t)
}
function ImagesChat {
    & docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | Where-Object { $_ -match 'open-webui' } | ForEach-Object { ($_ -split ' ')[1] } | Sort-Object -Unique
}
$lotStudio = @("free-ai-studio-free-tier-manager", "free-ai-studio-sandbox-manager", "free-ai-studio-sandbox-worker")

# --- ou sont les choses -----------------------------------------------------
if ($env:GPU_MODELES_DIR) { $cache = $env:GPU_MODELES_DIR }
else { $cache = Join-Path $env:USERPROFILE ".cache\huggingface" }
$poidsVideo = Join-Path $cache "hub\models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
$projet = (Split-Path -Leaf $Racine).ToLower() -replace '[^a-z0-9_-]', ''

$oPoids  = TailleDossier $poidsVideo
$oImgGpu = TailleImage "free-ai-studio-sandbox-worker-gpu"
$idsChat = @(ImagesChat)
$oImgChat = [int64]0
foreach ($id in $idsChat) { $oImgChat += TailleImage $id }
$oImgStudio = [int64]0
foreach ($i in $lotStudio) { $oImgStudio += TailleImage $i }
$oWhisper = TailleVolume "${projet}_whisper-modeles"
$oTravail = TailleVolume "${projet}_sandbox-data"
$oConvers = TailleVolume "${projet}_open-webui-data"

# Plusieurs images sur une ligne : c'est la plus recente qui date la ligne.
$dPoids = DateDossier $poidsVideo
$dImgGpu = DateImage "free-ai-studio-sandbox-worker-gpu"
$dImgChat = JourIso (IsoMax @($idsChat | ForEach-Object { IsoImage $_ }))
$dImgStudio = JourIso (IsoMax @($lotStudio | ForEach-Object { IsoImage $_ }))
$dWhisper = DateVolume "${projet}_whisper-modeles"
$dTravail = DateVolume "${projet}_sandbox-data"
$dConvers = DateVolume "${projet}_open-webui-data"

$totalTelecharge = $oPoids + $oImgGpu + $oImgChat + $oImgStudio + $oWhisper
$totalTravail = $oTravail + $oConvers

# --- affichage --------------------------------------------------------------
Write-Host ""
Write-Host "  Place occupee par le Studio sur cet ordinateur" -ForegroundColor Cyan
Write-Host ""
"  {0,-22} {1,-42} {2,10}    {3,-12}" -f "APPLICATION", "CE QUI EST SUR LE DISQUE", "TAILLE", "RENOUVELE LE"
"  {0,-22} {1,-42} {2,10}    {3,-12}" -f "----------------------", "------------------------------------------", "----------", "------------"
"  {0,-22} {1,-42} {2,10}    {3,-12}   [video-poids]" -f "Video a la maison", "les 34 Go du modele video", (Lisible $oPoids), $dPoids
"  {0,-22} {1,-42} {2,10}    {3,-12}   [video-image]" -f "Video a la maison", "le bac a sable qui sait parler a la carte", (Lisible $oImgGpu), $dImgGpu
"  {0,-22} {1,-42} {2,10}    {3,-12}   [chat]" -f "Chat (Open WebUI)", "l'application de conversation", (Lisible $oImgChat), $dImgChat
"  {0,-22} {1,-42} {2,10}    {3,-12}   [whisper]" -f "Ecoute des voix", "les modeles qui transcrivent", (Lisible $oWhisper), $dWhisper
"  {0,-22} {1,-42} {2,10}    {3,-12}   [studio]" -f "Le Studio lui-meme", "ses trois services", (Lisible $oImgStudio), $dImgStudio
Write-Host ""
"  {0,-22} {1,-42}" -f "VOTRE TRAVAIL", "jamais propose a la suppression ici"
"  {0,-22} {1,-42} {2,10}    {3,-12}" -f "Vos fichiers", "l'espace de travail du bac a sable", (Lisible $oTravail), $dTravail
"  {0,-22} {1,-42} {2,10}    {3,-12}" -f "Vos conversations", "l'historique du chat", (Lisible $oConvers), $dConvers
Write-Host ""
Write-Host ("  Telecharge : {0}     Votre travail : {1}" -f (Lisible $totalTelecharge), (Lisible $totalTravail))
Write-Host "  (les images Docker partagent des morceaux : le total telecharge est une borne haute)"
Write-Host "  << Renouvele le >> = arrive sur cette machine a cette date. Pour un volume, c'est sa"
Write-Host "  date de creation : ce qu'il contient a pu etre ajoute plus tard."
$d = Get-PSDrive -Name ($env:SystemDrive.TrimEnd(":"))
Write-Host ("  Disque : {0:N1} Go libres sur {1:N0} Go" -f ($d.Free/1GB), (($d.Free + $d.Used)/1GB))
Write-Host ""

# --- ce qui se remet a zero tout seul ---------------------------------------
# Les lignes du dessus dorment sur le disque : elles ne bougent que si on les
# vide. Celles-ci sont des DROITS D'USAGE, et elles repartent a une date. Ne pas
# la connaitre, c'est soit attendre pour rien alors que le credit est revenu,
# soit lancer un calcul qui sera refuse.
#
# Le compteur Modal se lit dans `config/`, monte depuis ce depot : ni cle, ni
# docker, ni service a demarrer.
function PremierDuMoisSuivant([string]$mois) {     # 2026-09 -> 01/10/2026
    $a = [int]$mois.Substring(0, 4)
    $m = [int]$mois.Substring(5, 2) + 1
    if ($m -gt 12) { $m = 1; $a = $a + 1 }
    return ("01/{0:D2}/{1}" -f $m, $a)
}
$moisCourant = Get-Date -Format "yyyy-MM"
$credit = 30.0
if ($env:MODAL_CREDIT_MENSUEL_USD) { $credit = [double]$env:MODAL_CREDIT_MENSUEL_USD }
$depense = 0.0
$fichierBudget = Join-Path $Racine "config\modal-budget.json"
if (Test-Path -LiteralPath $fichierBudget) {
    try {
        $b = Get-Content -LiteralPath $fichierBudget -Raw -Encoding UTF8 | ConvertFrom-Json
        # Un compteur d'un mois clos ne dit rien du mois en cours : il est deja
        # reparti de zero, et l'afficher serait un chiffre faux presente comme
        # a jour.
        if ($b.mois -eq $moisCourant) { $depense = [double]$b.usd }
    } catch { }
}
$reste = $credit - $depense
if ($reste -lt 0) { $reste = 0 }

# CE QUI EST SOURCE ET CE QUI NE L'EST PAS. Verifie sur les pages officielles
# le 20/09/2026, apres que le proprietaire a demande << les jours exacts >> :
#   - Modal publie << $30 / month free compute >> (modal.com/pricing) et
#     << All Workspaces are billed monthly >> (docs/guide/billing). Le JOUR de
#     remise a zero n'est ecrit NULLE PART chez eux -- ni tarifs, ni
#     facturation, ni budgets. Le << 1er du mois >> qu'on affichait venait d'un
#     resume de moteur de recherche, pas de Modal.
#   - Gemini : << Requests per day (RPD) quotas reset at midnight Pacific
#     time >> (ai.google.dev/gemini-api/docs/rate-limits). Seule date ecrite
#     par un fournisseur.
#   - OpenRouter : la page des limites donne les comptes par jour, pas l'heure.
#   - Groq : pas d'heure fixe publiee ; l'API rend un COMPTE A REBOURS dans
#     l'en-tete `x-ratelimit-reset-requests`.
# D'ou la regle de ce bloc : le 1er du mois est a NOUS, pas a Modal.
Write-Host "  Ce qui se remet a zero tout seul" -ForegroundColor Cyan
Write-Host ""
Write-Host ("  Modal (machines louees)   {0:N2} `$ depenses sur {1:N0} `$ ce mois-ci, reste {2:N2} `$" -f $depense, $credit, $reste)
Write-Host ("                            NOTRE compteur repart le {0}, et tous les 1ers." -f (PremierDuMoisSuivant $moisCourant))
Write-Host "                            Modal ne publie PAS le jour de ses 30 `$ : il dit"
Write-Host "                            << facture au mois >>, sans dire lequel. La date qui"
Write-Host "                            fait foi est celle de VOTRE cycle, sur modal.com."
Write-Host "                            (nos chiffres : estimation d'apres les prix publics,"
Write-Host "                             pas votre facture)"
Write-Host "  Gemini                    quota du JOUR, remis a zero a minuit heure du"
Write-Host "                            Pacifique, soit 9 h chez nous -- ecrit par Google"
Write-Host "  OpenRouter                quota du JOUR ; l'heure n'est pas publiee"
Write-Host "  Groq                      pas d'heure fixe : l'API rend un compte a rebours"
Write-Host "  Le compte du jour est sur la page Cles du Studio."
Write-Host "  (verifie le 20/09/2026 sur les pages officielles)"
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
switch ($Vider) {
    "video-poids" { ViderPoids }
    "video-image" { ViderImage "free-ai-studio-sandbox-worker-gpu" }
    "chat"        { foreach ($id in (ImagesChat)) { ViderImage $id } }
    "whisper"     { ViderVolume "${projet}_whisper-modeles" }
    "studio"      { foreach ($i in $lotStudio) { ViderImage $i } }
    "tout" {
        ViderPoids
        ViderImage "free-ai-studio-sandbox-worker-gpu"
        foreach ($id in (ImagesChat)) { ViderImage $id }
        ViderVolume "${projet}_whisper-modeles"
        foreach ($i in $lotStudio) { ViderImage $i }
    }
}

Write-Host ""
if ($script:code -eq 0) {
    Write-Host "  Fait. Relancez ce script pour voir la place rendue." -ForegroundColor Green
} else {
    Write-Host "  Une partie n'a pas pu etre rendue (voir au-dessus). Votre travail n'a pas ete touche." -ForegroundColor Yellow
}
exit $script:code
