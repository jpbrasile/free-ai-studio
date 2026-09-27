# Free AI Studio : remettre la cle du routeur dans le chat restaure.
#
# sauvegarder.ps1 retire de la copie du chat la cle interne du routeur, qu'Open
# WebUI garde en clair dans sa base (27/09/2026, docs/SAUVEGARDES.md). Une
# restauration doit donc la remettre, avec la cle du .env de la CIBLE : c'est
# elle que le routeur restaure attendra. restaurer.ps1 appelle ce script tout
# seul quand ce .env existe deja ; sinon, copiez .env dans la cible (depuis le
# gestionnaire de mots de passe), puis lancez :
#
#   powershell -ExecutionPolicy Bypass -File scripts\remettre-cle-routeur.ps1 [-Cible <dossier>] [-Reel]
#
# Memes cibles que restaurer.ps1 : par defaut le dossier d'essai <depot>-essai,
# -Reel le vrai Studio. Il ne remplace QUE la marque posee par la sauvegarde :
# une base qui a deja sa cle n'est pas changee, et relancer ne fait rien de plus.
# La cle n'est jamais affichee ; elle passe au conteneur par le NOM de la
# variable. Le chat doit etre arrete : il garde ses reglages en memoire.

param(
    [string]$Cible = "",
    [switch]$Reel,
    [string]$Projet = "",
    [string]$ImageChat = ""
)

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot

$Journal = Join-Path $env:TEMP "free-ai-studio-restauration"
if (-not (Test-Path $Journal)) { New-Item -ItemType Directory -Path $Journal | Out-Null }

function Bon($texte)   { Write-Host ("   OK   " + $texte) -ForegroundColor Green }
function Note($texte)  { Write-Host ("   ..   " + $texte) -ForegroundColor Gray }
function Arreter($titre, $quoiFaire) {
    Write-Host ""
    Write-Host ("ARRET : " + $titre) -ForegroundColor Red
    foreach ($ligne in @($quoiFaire)) { if ($ligne) { Write-Host ("  " + $ligne) } }
    exit 1
}
function Guillemets($a) {
    $s = [string]$a
    if ($s -match '[\s"]') {
        $s = $s -replace '"', '\"'
        $s = $s -replace '(\\+)$', '$1$1'
        return '"' + $s + '"'
    }
    return $s
}
function Executer($programme, $arguments, $etiquette) {
    $sortie = Join-Path $Journal ($etiquette + ".out.txt")
    $erreur = Join-Path $Journal ($etiquette + ".err.txt")
    $liste = @($arguments | ForEach-Object { Guillemets $_ })
    $p = Start-Process -FilePath $programme -ArgumentList $liste -WorkingDirectory $Racine `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $sortie -RedirectStandardError $erreur
    $out = ""
    $err = ""
    if (Test-Path $sortie) { $out = [System.IO.File]::ReadAllText($sortie) }
    if (Test-Path $erreur) { $err = [System.IO.File]::ReadAllText($erreur) }
    return [pscustomobject]@{ Code = $p.ExitCode; Sortie = $out; Erreur = $err }
}
function Lignes($texte) { return @(([string]$texte) -split "\r?\n" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }) }
function Plein($chemin) { return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($chemin).TrimEnd('\') }

# La cible, calculee comme dans restaurer.ps1.
if (-not $Projet) {
    if ($env:COMPOSE_PROJECT_NAME) { $Projet = $env:COMPOSE_PROJECT_NAME }
    else { $Projet = ((Split-Path -Leaf $Racine).ToLower() -replace '[^a-z0-9_-]', '') }
}
if ($Reel) {
    $Dossier = [System.IO.Path]::GetFullPath($Racine).TrimEnd('\')
    $ProjetCible = $Projet
} else {
    if (-not $Cible) { $Cible = Join-Path (Split-Path -Parent $Racine) ((Split-Path -Leaf $Racine) + "-essai") }
    $Dossier = Plein $Cible
    $ProjetCible = ((Split-Path -Leaf $Dossier).ToLower() -replace '[^a-z0-9_-]', '')
}
Note ("Cible : " + $Dossier + " (projet " + $ProjetCible + ")")

# La cle : seulement la ligne FREE_TIER_MANAGER_KEY du .env de la cible.
$cheminEnv = Join-Path $Dossier ".env"
$Cle = ""
if (Test-Path -LiteralPath $cheminEnv) {
    foreach ($l in [System.IO.File]::ReadAllLines($cheminEnv)) {
        if ($l -match '^FREE_TIER_MANAGER_KEY=(.*)$') { $Cle = $Matches[1].Trim().Trim('"').Trim("'") }
    }
}
if (-not $Cle) {
    Arreter "Pas de FREE_TIER_MANAGER_KEY dans le .env de la cible." @(
        $cheminEnv, "Copiez-y .env depuis le gestionnaire de mots de passe, puis relancez.")
}

if (-not $ImageChat) {
    $compose = [System.IO.File]::ReadAllText((Join-Path $Racine "docker-compose.yml"))
    $m = [regex]::Match($compose, '(?m)^\s*image:\s*(ghcr\.io/open-webui/open-webui:\S+)\s*$')
    if (-not $m.Success) { Arreter "Image d'Open WebUI introuvable dans docker-compose.yml." @("Donnez -ImageChat.") }
    $ImageChat = $m.Groups[1].Value
}

$r = Executer "docker" @("volume", "ls", "-q",
    "--filter", ("label=com.docker.compose.project=" + $ProjetCible),
    "--filter", "label=com.docker.compose.volume=open-webui-data") "cle-routeur-volume"
$noms = @(Lignes $r.Sortie)
if ($r.Code -ne 0 -or $noms.Count -ne 1) {
    Arreter ("Volume du chat introuvable pour le projet " + $ProjetCible + ".") @("Restaurez d'abord : scripts\restaurer.ps1.")
}
$marche = Executer "docker" @("ps", "-q", "--filter", ("label=com.docker.compose.project=" + $ProjetCible)) "cle-routeur-marche"
if ((Lignes $marche.Sortie).Count -gt 0) {
    Arreter ("Le projet " + $ProjetCible + " tourne.") @(
        ("Arretez-le d'abord : docker compose -p " + $ProjetCible + " stop"), "Rien n'a ete ecrit.")
}

$env:FAS_CLE_ROUTEUR = $Cle
try {
    $r = Executer "docker" @("run", "--rm", "--entrypoint", "python",
        "-e", "FAS_CLE_ROUTEUR",
        "-v", ($noms[0] + ":/donnees"),
        "-v", ((Join-Path $Racine "scripts") + ":/scripts:ro"),
        $ImageChat, "/scripts/cle_routeur_chat.py", "remettre", "/donnees") "cle-routeur-remettre"
} finally { Remove-Item Env:FAS_CLE_ROUTEUR -ErrorAction SilentlyContinue }
$Cle = $null
$resultat = [regex]::Match($r.Sortie, 'RESULTAT lignes=(\d+)')
if ($r.Code -ne 0 -or -not $resultat.Success) {
    Arreter "La cle du routeur n'a pas pu etre remise." @($r.Sortie, $r.Erreur)
}
$n = [int]$resultat.Groups[1].Value
if ($n -gt 0) { Bon ("cle du routeur remise dans le chat : " + $n + " ligne(s) (volume " + $noms[0] + ")") }
else { Note "Aucune marque a remplacer : le chat avait deja sa cle, ou la sauvegarde ne l'avait pas retiree." }
exit 0
