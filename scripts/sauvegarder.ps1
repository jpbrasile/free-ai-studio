# Free AI Studio : une sauvegarde datee, en local, puis sur le VPS si on le demande.
#
# Decision du proprietaire du 19/09/2026 : les sauvegardes se font en local ET
# sur le VPS (docs/PLAN-PLATEFORME.md, decision 15). docs/SAUVEGARDES.md,
# section << La procedure >>, dit pourquoi chaque piece va ou elle va, et comment
# jouer l'essai de restauration qui seul fait compter une sauvegarde.
#
# Ce que fabrique ce script, dans un dossier HORS du depot (par defaut
# %USERPROFILE%\Sauvegardes\<projet>\studio-AAAAMMJJ-HHMMSS) :
#
#   config.tar            config/ SANS les magasins de secrets
#   config-magasins.tar   keys.json, sandbox-keys.json, notebooklm/ : les valeurs
#                         y sont fermees par le coffre, les NOMS sont en clair
#   open-webui-data.tar   le volume du chat (conversations, comptes), SANS la cle
#                         interne du routeur (voir plus bas)
#   sandbox-data.tar      le volume des bacs a sable (travaux, questions NotebookLM)
#   <volume>.sha256.txt   chaque fichier du volume et son empreinte
#   <volume>.tailles.txt  chaque fichier du volume et sa taille
#   manifeste.json        date, version git, pieces, tailles, empreintes SHA-256
#
# LA CLE DU COFFRE (secrets/coffre.cle) N'EST DANS AUCUNE ARCHIVE, ni locale ni
# VPS, et aucun interrupteur ne l'y met. Sa place est le gestionnaire de mots de
# passe. Le manifeste n'en garde qu'une empreinte courte (16 caracteres d'un
# SHA-256), pour que restaurer.ps1 puisse dire si la cle qu'on lui donne est la
# bonne. Ce script ne l'affiche jamais.
#
# LA CLE INTERNE DU ROUTEUR non plus (27/09/2026). Open WebUI la garde en clair
# dans sa base, quatre fois. Le volume du chat est donc copie dans un conteneur
# jetable, la cle y est remplacee par une marque (scripts/cle_routeur_chat.py),
# chaque fichier de la copie est relu pour s'assurer qu'elle n'y est plus, et
# c'est CETTE copie qui est archivee. La base vivante n'est pas touchee.
# restaurer.ps1 la remet depuis le .env de la cible. Si elle reste quelque part,
# la sauvegarde s'arrete.
#
# -VersVps copie ensuite par scp, avec les SEULES variables VPS_HOTE,
# VPS_UTILISATEUR, VPS_DOSSIER (VPS_PORT_SSH et VPS_CLE_SSH facultatives), lues
# dans l'environnement, sinon dans .env. Aucune valeur n'est ecrite ici, ni
# affichee. Par defaut ne partent que config.tar et le manifeste : ni les
# magasins de secrets, ni les volumes (le texte des conversations et des
# questions NotebookLM, qui << reste sur ce poste >>, decision du 25/09). Les
# deux interrupteurs -VpsAvecMagasinsChiffres et -VpsAvecVolumes attendent une
# decision du proprietaire : voir les questions ouvertes du document.
#
# Memes precautions PowerShell 5.1 que demarrer.ps1 : jamais << 2>&1 >> sur une
# commande native (on passe par Start-Process et deux fichiers), jamais
# Out-File -Encoding utf8 (marque d'octets), jamais && ni ternaire.
#
# Ce script ne supprime rien du Studio : ni volume, ni conteneur, ni fichier.
# S'il arrete le Studio le temps de la copie, c'est apres l'avoir demande, et il
# le redemarre meme si la copie echoue. La seule suppression possible est celle
# des anciennes sauvegardes, et seulement avec -Garder N (au moins 2).

param(
    # Dossier ou poser l'archive. Refuse s'il est dans le depot.
    [string]$Destination = "",
    # Nom du projet Docker Compose (par defaut : COMPOSE_PROJECT_NAME, sinon le
    # nom du dossier du depot, comme le fait Docker Compose).
    [string]$Projet = "",
    # Arreter le Studio le temps de la copie, sans poser la question.
    [switch]$Arret,
    # Copier a chaud, sans poser la question (NON sur : voir plus bas).
    [switch]$AChaud,
    # Copier ensuite l'archive vers le VPS.
    [switch]$VersVps,
    # En attente d'une decision du proprietaire (docs/SAUVEGARDES.md).
    [switch]$VpsAvecMagasinsChiffres,
    [switch]$VpsAvecVolumes,
    # Image du conteneur jetable qui lit les volumes. Etiquette fixe : la meme
    # image a la sauvegarde et a la restauration.
    [string]$Image = "alpine:3.20",
    # Image qui retire la cle du routeur de la copie du chat : celle d'Open
    # WebUI (python et sqlite, deja sur la machine). Vide : lue dans
    # docker-compose.yml.
    [string]$ImageChat = "",
    # Rotation locale : garder les N sauvegardes les plus recentes (celle-ci
    # comprise) et supprimer les autres. 0 (par defaut) : rien n'est supprime,
    # le script dit seulement combien il y en a et leur taille. Au moins 2.
    [int]$Garder = 0
)

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot

$Journal = Join-Path $env:TEMP "free-ai-studio-sauvegarde"
if (-not (Test-Path $Journal)) { New-Item -ItemType Directory -Path $Journal | Out-Null }

function Titre($texte) {
    Write-Host ""
    Write-Host ("== " + $texte) -ForegroundColor Cyan
}
function Bon($texte)   { Write-Host ("   OK   " + $texte) -ForegroundColor Green }
function Note($texte)  { Write-Host ("   ..   " + $texte) -ForegroundColor Gray }
function Souci($texte) { Write-Host ("   !    " + $texte) -ForegroundColor Yellow }
function Arreter($titre, $quoiFaire) {
    Write-Host ""
    Write-Host ("ARRET : " + $titre) -ForegroundColor Red
    foreach ($ligne in @($quoiFaire)) { if ($ligne) { Write-Host ("  " + $ligne) } }
    exit 1
}

# Start-Process colle les arguments avec des espaces, sans guillemets : un
# chemin avec une espace serait coupe en deux. On les pose ici.
function Guillemets($a) {
    $s = [string]$a
    if ($s -match '[\s"]') {
        $s = $s -replace '"', '\"'
        $s = $s -replace '(\\+)$', '$1$1'
        return '"' + $s + '"'
    }
    return $s
}

# Lance un programme et rend son code, sa sortie et ses plaintes, sans que la
# moindre ligne ecrite sur la sortie d'erreur soit prise pour une erreur.
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

function Sha256($chemin) { return (Get-FileHash -LiteralPath $chemin -Algorithm SHA256).Hash.ToLower() }

# L'empreinte de la cle du coffre : 16 caracteres du SHA-256 du texte de la
# cle, espaces de bord retires (coffre.py fait le meme strip). Assez pour
# reconnaitre la bonne cle, rien pour la retrouver. MEME FONCTION, au caractere
# pres, dans restaurer.ps1 : un test le verifie.
function Empreinte-Cle($texte) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $octets = $sha.ComputeHash([System.Text.Encoding]::ASCII.GetBytes(([string]$texte).Trim()))
    } finally { $sha.Dispose() }
    return (-join ($octets | ForEach-Object { $_.ToString("x2") })).Substring(0, 16)
}

# Une variable du VPS : l'environnement d'abord, la ligne de .env ensuite. Seule
# la ligne qui porte CE nom est lue ; aucune autre valeur de .env n'est touchee.
function Variable-Vps($nom) {
    $v = [Environment]::GetEnvironmentVariable($nom)
    if (-not $v) {
        $cheminEnv = Join-Path $Racine ".env"
        if (Test-Path -LiteralPath $cheminEnv) {
            foreach ($l in [System.IO.File]::ReadAllLines($cheminEnv)) {
                if ($l -match ('^' + $nom + '=(.*)$')) { $v = $Matches[1] }
            }
        }
    }
    if (-not $v) { return "" }
    return $v.Trim().Trim('"').Trim("'")
}

$utf8SansMarque = New-Object System.Text.UTF8Encoding($false)

# --- 1. Ou, et quoi -------------------------------------------------------------
Titre "Sauvegarde du Studio"

if ($Arret -and $AChaud) {
    Arreter "-Arret et -AChaud se contredisent." @("Choisissez l'un des deux, ou aucun pour que la question soit posee.")
}
if (($VpsAvecMagasinsChiffres -or $VpsAvecVolumes) -and -not $VersVps) {
    Arreter "-VpsAvecMagasinsChiffres et -VpsAvecVolumes ne valent qu'avec -VersVps." @()
}
# Garder 1, c'est effacer la copie precedente avant d'avoir restaure celle-ci.
if ($Garder -ne 0 -and $Garder -lt 2) {
    Arreter "-Garder vaut au moins 2." @("0 (par defaut) ne supprime rien ; 2 garde celle-ci et la precedente.")
}

if (-not $Projet) {
    if ($env:COMPOSE_PROJECT_NAME) { $Projet = $env:COMPOSE_PROJECT_NAME }
    else { $Projet = ((Split-Path -Leaf $Racine).ToLower() -replace '[^a-z0-9_-]', '') }
}
Note ("Projet Docker : " + $Projet)

if (-not $Destination) { $Destination = Join-Path $env:USERPROFILE ("Sauvegardes\" + $Projet) }
$Destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination).TrimEnd('\')
$racinePleine = [System.IO.Path]::GetFullPath($Racine).TrimEnd('\')
# Dans le depot, l'archive serait a une commande << git add . >> d'un commit,
# et une copie du depot l'emporterait avec lui.
if (($Destination + '\').StartsWith($racinePleine + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Arreter "Le dossier de sauvegarde est dans le depot." @(
        ("Dossier demande : " + $Destination),
        "Choisissez un dossier hors du depot, par exemple sous Documents ou sur un disque externe.")
}

$Nom = "studio-" + (Get-Date -Format "yyyyMMdd-HHmmss")
$Dossier = Join-Path $Destination $Nom
New-Item -ItemType Directory -Path $Dossier -Force | Out-Null
Bon ("Archive : " + $Dossier)

$Tar = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path -LiteralPath $Tar)) {
    Arreter "tar.exe de Windows est introuvable." @("Il est livre avec Windows 10 1803 et plus recent.")
}

$info = Executer "docker" @("info", "--format", "{{.ServerVersion}}") "docker-info"
if ($info.Code -ne 0 -or -not $info.Sortie.Trim()) {
    Arreter "Docker ne tourne pas." @("Ouvrez Docker Desktop, attendez la baleine verte, puis relancez.")
}

# Les deux volumes, retrouves par leurs etiquettes Compose et non par un nom
# devine : Docker les prefixe du nom du projet.
$Volumes = @("open-webui-data", "sandbox-data")
$NomsVolumes = @{}
$VolumesAbsents = @()
foreach ($court in $Volumes) {
    $r = Executer "docker" @("volume", "ls", "-q",
        "--filter", ("label=com.docker.compose.project=" + $Projet),
        "--filter", ("label=com.docker.compose.volume=" + $court)) ("volume-" + $court)
    $noms = @(Lignes $r.Sortie)
    if ($r.Code -ne 0 -or $noms.Count -ne 1) {
        $VolumesAbsents += $court
        Souci ("Volume " + $court + " introuvable pour le projet " + $Projet + " : il ne sera pas sauvegarde.")
    } else {
        $NomsVolumes[$court] = $noms[0]
    }
}

# La cle du routeur a retirer de la copie du chat : celle que le Studio utilise
# (l'environnement, sinon .env, comme Docker Compose). Jamais affichee ; elle
# passe au conteneur par le NOM de la variable, pas par sa valeur.
$CleRouteur = Variable-Vps "FREE_TIER_MANAGER_KEY"
$CleRouteurEtat = [ordered]@{ retiree = $false; lignes = 0; note = "" }
if (-not $ImageChat) {
    $compose = [System.IO.File]::ReadAllText((Join-Path $Racine "docker-compose.yml"))
    $m = [regex]::Match($compose, '(?m)^\s*image:\s*(ghcr\.io/open-webui/open-webui:\S+)\s*$')
    if ($m.Success) { $ImageChat = $m.Groups[1].Value }
}
if ($NomsVolumes.ContainsKey("open-webui-data")) {
    if (-not $CleRouteur) {
        $CleRouteurEtat.note = "NON retiree : FREE_TIER_MANAGER_KEY introuvable (ni environnement ni .env) ; open-webui-data.tar peut la porter"
        Souci "Cle du routeur introuvable : la copie du chat la portera peut-etre (voir le manifeste)."
    } elseif (-not $ImageChat) {
        $CleRouteurEtat.note = "NON retiree : image d'Open WebUI introuvable dans docker-compose.yml ; open-webui-data.tar la porte"
        Souci "Image d'Open WebUI introuvable : la copie du chat portera la cle du routeur."
    }
}

# --- 2. A chaud ou a froid ------------------------------------------------------
# Une copie a chaud n'est PAS sure : le chat ecrit dans une base SQLite, et une
# base copiee au milieu d'une ecriture peut ne pas se rouvrir. Un travail du bac
# a sable en cours laisse un dossier a moitie ecrit. D'ou la question, et la
# reponse recommandee : arreter les quatre services le temps de la copie.
$Services = @("open-webui", "sandbox-manager", "sandbox-worker", "free-tier-manager")
$enMarche = Executer "docker" @("ps", "-q", "--filter", ("label=com.docker.compose.project=" + $Projet)) "en-marche"
$tourne = ((Lignes $enMarche.Sortie).Count -gt 0)
$Copie = "a-froid"
$arretes = $false
if ($tourne) {
    $choix = ""
    if ($Arret) { $choix = "A" }
    elseif ($AChaud) { $choix = "C" }
    else {
        Souci "Le Studio tourne."
        Note  "Copier a chaud n'est pas sur : la base du chat peut etre copiee au milieu d'une ecriture."
        Note  "Arreter le chat et les bacs a sable prend quelques secondes ; ils repartent a la fin."
        $choix = ([string](Read-Host "A = arreter le temps de la copie (recommande), C = copier a chaud, Q = quitter")).Trim().ToUpper()
    }
    if ($choix -eq "A") {
        $r = Executer "docker" (@("compose", "-p", $Projet, "stop") + $Services) "arret"
        if ($r.Code -ne 0) {
            Arreter "Le Studio n'a pas pu etre arrete ; rien n'a ete copie." @($r.Erreur)
        }
        $arretes = $true
        Bon "Studio arrete le temps de la copie"
    } elseif ($choix -eq "C") {
        $Copie = "a-chaud"
        Souci "Copie A CHAUD : le manifeste le dira, et l'essai de restauration aussi."
    } else {
        Arreter "Rien n'a ete copie." @()
    }
}

# --- 3. La copie ----------------------------------------------------------------
$Magasins = @("config/keys.json", "config/sandbox-keys.json", "config/notebooklm")
$ConfigPresent = Test-Path -LiteralPath (Join-Path $Racine "config")
try {
    Titre "Copie"
    if ($ConfigPresent) {
        # config/ sans les magasins de secrets.
        $argsTar = @("-cf", (Join-Path $Dossier "config.tar"), "-C", $Racine, "--exclude", "*.tmp")
        foreach ($m in $Magasins) { $argsTar += @("--exclude", $m) }
        $argsTar += "config"
        $r = Executer $Tar $argsTar "tar-config"
        if ($r.Code -ne 0) { Arreter "config/ n'a pas pu etre archive." @($r.Erreur) }

        # Controle APRES coup, et non confiance dans --exclude : si un magasin
        # est entre dans config.tar, cette piece partirait sur le VPS.
        $liste = Executer $Tar @("-tf", (Join-Path $Dossier "config.tar")) "tar-config-liste"
        $fuite = @(Lignes $liste.Sortie | Where-Object { $_ -match '^(\./)?config/(keys\.json|sandbox-keys\.json|notebooklm(/|$))' })
        if ($liste.Code -ne 0 -or $fuite.Count -gt 0) {
            Remove-Item -LiteralPath (Join-Path $Dossier "config.tar") -Force
            Arreter "config.tar contenait un magasin de secrets ; la piece est retiree." @($fuite)
        }
        Bon "config/ (sans les magasins de secrets)"

        $presents = @($Magasins | Where-Object { Test-Path -LiteralPath (Join-Path $Racine $_) })
        if ($presents.Count -gt 0) {
            $r = Executer $Tar (@("-cf", (Join-Path $Dossier "config-magasins.tar"), "-C", $Racine, "--exclude", "*.tmp") + $presents) "tar-magasins"
            if ($r.Code -ne 0) { Arreter "Les magasins de secrets n'ont pas pu etre archives." @($r.Erreur) }
            Bon ("magasins de secrets, valeurs chiffrees : " + ($presents -join ", "))
        } else {
            Note "Aucun magasin de secrets dans config/ (aucune cle saisie depuis les pages)."
        }
    } else {
        Souci "Pas de dossier config/ : rien a sauvegarder de ce cote."
    }

    # Chaque volume par un conteneur jetable qui le lit en LECTURE SEULE et
    # ecrit l'archive, la liste des empreintes et celle des tailles.
    foreach ($court in $Volumes) {
        if (-not $NomsVolumes.ContainsKey($court)) { continue }
        $archiver = "tar -cf /sortie/" + $court + ".tar . && " +
            "find . -type f -exec sha256sum {} + > /sortie/" + $court + ".sha256.txt && " +
            "find . -type f -exec stat -c '%s %n' {} + > /sortie/" + $court + ".tailles.txt"
        if ($court -eq "open-webui-data" -and $CleRouteur -and $ImageChat) {
            # La copie d'abord, la cle retiree de la copie, puis l'archive ET les
            # listes d'empreintes faites sur elle : restaurer.ps1 compare ce qu'il
            # remet a ces listes, elles doivent decrire ce qui est archive.
            $commande = "mkdir /travail && cp -a /donnees/. /travail/ && " +
                "python /scripts/cle_routeur_chat.py retirer /travail && cd /travail && " + $archiver
            $env:FAS_CLE_ROUTEUR = $CleRouteur
            try {
                $r = Executer "docker" @("run", "--rm", "--entrypoint", "sh",
                    "-e", "FAS_CLE_ROUTEUR",
                    "-v", ($NomsVolumes[$court] + ":/donnees:ro"),
                    "-v", ((Join-Path $Racine "scripts") + ":/scripts:ro"),
                    "-v", ($Dossier + ":/sortie"),
                    $ImageChat, "-c", $commande) ("copie-" + $court)
            } finally { Remove-Item Env:FAS_CLE_ROUTEUR -ErrorAction SilentlyContinue }
            $resultat = [regex]::Match($r.Sortie, 'RESULTAT lignes=(\d+) restes=(\S*)')
            if ($r.Code -ne 0) {
                # Une archive commencee ne doit pas rester : elle porterait la cle.
                Remove-Item -LiteralPath (Join-Path $Dossier ($court + ".tar")) -Force -ErrorAction SilentlyContinue
                $restes = ""
                if ($resultat.Success) { $restes = $resultat.Groups[2].Value }
                Arreter ("Le volume " + $court + " n'a pas pu etre copie sans la cle du routeur.") @(
                    ("Fichiers qui la portent encore : " + $restes), $r.Erreur)
            }
            $CleRouteurEtat.retiree = $true
            if ($resultat.Success) { $CleRouteurEtat.lignes = [int]$resultat.Groups[1].Value }
            $CleRouteurEtat.note = "remplacee par une marque dans " + $CleRouteurEtat.lignes + " ligne(s) de la base ; aucun fichier de la copie ne la porte ; restaurer.ps1 la remet depuis le .env de la cible"
            Bon ("volume " + $court + " (cle du routeur retiree de la copie : " + $CleRouteurEtat.lignes + " ligne(s))")
            continue
        }
        $commande = "cd /donnees && " + $archiver
        $r = Executer "docker" @("run", "--rm",
            "-v", ($NomsVolumes[$court] + ":/donnees:ro"),
            "-v", ($Dossier + ":/sortie"),
            $Image, "sh", "-c", $commande) ("copie-" + $court)
        if ($r.Code -ne 0) { Arreter ("Le volume " + $court + " n'a pas pu etre copie.") @($r.Erreur) }
        Bon ("volume " + $court)
    }
} finally {
    # Redemarre meme si la copie a echoue : une sauvegarde ratee ne doit pas
    # laisser le Studio arrete.
    if ($arretes) {
        $r = Executer "docker" (@("compose", "-p", $Projet, "start") + $Services) "redemarrage"
        if ($r.Code -eq 0) { Bon "Studio redemarre" }
        else { Souci "Le Studio n'a pas redemarre : double-cliquez demarrer.cmd." }
    }
}

# --- 4. Le manifeste -----------------------------------------------------------
Titre "Manifeste"
$Pieces = @()
function Ajouter-Piece($nom, $quoi, $vps) {
    $chemin = Join-Path $Dossier $nom
    if (-not (Test-Path -LiteralPath $chemin)) { return }
    $script:Pieces += [pscustomobject]@{
        nom    = $nom
        quoi   = $quoi
        octets = (Get-Item -LiteralPath $chemin).Length
        sha256 = (Sha256 $chemin)
        vps    = [bool]$vps
    }
}
Ajouter-Piece "config.tar" "config/ sans les magasins de secrets" $true
Ajouter-Piece "config-magasins.tar" "keys.json, sandbox-keys.json, notebooklm/ (valeurs chiffrees par le coffre)" $VpsAvecMagasinsChiffres.IsPresent
foreach ($court in $Volumes) {
    Ajouter-Piece ($court + ".tar") ("volume Docker " + $court) $VpsAvecVolumes.IsPresent
    Ajouter-Piece ($court + ".sha256.txt") ("empreintes des fichiers du volume " + $court) $VpsAvecVolumes.IsPresent
    Ajouter-Piece ($court + ".tailles.txt") ("tailles des fichiers du volume " + $court) $VpsAvecVolumes.IsPresent
}

# La liste des fichiers de config/, lue sur le disque : chemin, taille, empreinte.
$FichiersConfig = @()
if ($ConfigPresent) {
    $base = Join-Path $Racine "config"
    Get-ChildItem -LiteralPath $base -Recurse -File -Force | Where-Object { $_.Name -notlike "*.tmp" } | ForEach-Object {
        $rel = "config/" + $_.FullName.Substring($base.Length + 1).Replace('\', '/')
        $empreinte = "illisible"
        try { $empreinte = Sha256 $_.FullName } catch { }
        $piece = "config.tar"
        if ($rel -match '^config/(keys\.json|sandbox-keys\.json|notebooklm/)') { $piece = "config-magasins.tar" }
        $FichiersConfig += [pscustomobject]@{ chemin = $rel; octets = $_.Length; sha256 = $empreinte; piece = $piece }
    }
}

# La cle du coffre : jamais copiee, seulement reconnue.
$CleFichier = Join-Path $Racine "secrets\coffre.cle"
$Cle = [ordered]@{
    dans_l_archive = $false
    fichier_present = (Test-Path -LiteralPath $CleFichier)
    empreinte = ""
    note = "La cle n'est dans aucune piece. Sa place : le gestionnaire de mots de passe. Si STUDIO_COFFRE_CLE est posee dans .env, c'est elle qui ouvre le coffre, et ce script ne la lit pas."
}
if ($Cle.fichier_present) {
    $texteCle = [System.IO.File]::ReadAllText($CleFichier)
    $Cle.empreinte = Empreinte-Cle $texteCle
    $texteCle = $null
}

$commit = Executer "git" @("rev-parse", "HEAD") "git-commit"
$etat = Executer "git" @("status", "--porcelain", "--untracked-files=no") "git-etat"
$Manifeste = [ordered]@{
    format = 1
    nom = $Nom
    date = (Get-Date -Format "yyyy-MM-dd'T'HH:mm:sszzz")
    projet = $Projet
    version_git = [ordered]@{
        commit = $commit.Sortie.Trim()
        modifications_non_commitees = ((Lignes $etat.Sortie).Count -gt 0)
    }
    copie = $Copie
    image_des_volumes = $Image
    pieces = $Pieces
    volumes_absents = $VolumesAbsents
    fichiers_config = $FichiersConfig
    cle_du_coffre = $Cle
    cle_du_routeur = $CleRouteurEtat
    hors_archive = @(
        "secrets/coffre.cle : gestionnaire de mots de passe",
        ".env : gestionnaire de mots de passe (cles des fournisseurs, mots de passe internes)",
        "volume whisper-modeles : se retelecharge tout seul"
    )
}
$CheminManifeste = Join-Path $Dossier "manifeste.json"
[System.IO.File]::WriteAllText($CheminManifeste, ($Manifeste | ConvertTo-Json -Depth 6), $utf8SansMarque)
Bon ("manifeste.json : " + $Pieces.Count + " piece(s), " + $FichiersConfig.Count + " fichier(s) de config/")

# --- 5. Le VPS, si on le demande -----------------------------------------------
$VpsEtat = "non demande"
if ($VersVps) {
    Titre "Copie vers le VPS"
    $hote = Variable-Vps "VPS_HOTE"
    $utilisateur = Variable-Vps "VPS_UTILISATEUR"
    $dossierVps = Variable-Vps "VPS_DOSSIER"
    $portVps = Variable-Vps "VPS_PORT_SSH"
    $cleSsh = Variable-Vps "VPS_CLE_SSH"
    $manque = @()
    if (-not $hote) { $manque += "VPS_HOTE" }
    if (-not $utilisateur) { $manque += "VPS_UTILISATEUR" }
    if (-not $dossierVps) { $manque += "VPS_DOSSIER" }
    if ($manque.Count -gt 0) {
        Arreter "La copie vers le VPS demande des variables absentes." @(
            ("Manquent : " + ($manque -join ", ")),
            "Posez-les dans l'environnement de votre session ou dans .env (noms dans .env.example).",
            ("L'archive locale est faite : " + $Dossier))
    }
    # Les valeurs passent dans une ligne de commande distante : on refuse ce
    # qui pourrait y etre interprete, plutot que de l'echapper.
    if ($hote -notmatch '^[A-Za-z0-9.:-]+$' -or $utilisateur -notmatch '^[A-Za-z0-9._-]+$' -or
        $dossierVps -notmatch '^[A-Za-z0-9._/-]+$' -or ($portVps -and $portVps -notmatch '^[0-9]+$')) {
        Arreter "Une variable du VPS contient un caractere refuse." @(
            "VPS_HOTE, VPS_UTILISATEUR, VPS_DOSSIER : lettres, chiffres, point, tiret (et / pour le dossier).",
            "VPS_DOSSIER : chemin absolu, ou relatif au dossier personnel ; pas de ~ ni d'espace.")
    }
    $Ssh = "ssh"
    $Scp = "scp"
    $sshWin = Join-Path $env:SystemRoot "System32\OpenSSH\ssh.exe"
    if (Test-Path -LiteralPath $sshWin) { $Ssh = $sshWin; $Scp = Join-Path $env:SystemRoot "System32\OpenSSH\scp.exe" }

    # BatchMode : jamais de question pendant la copie. La cle SSH doit etre
    # chargee (ssh-agent) ou sans phrase, et l'hote deja connu : une premiere
    # connexion a la main, une fois (docs/SAUVEGARDES.md).
    $optsSsh = @("-o", "BatchMode=yes")
    $optsScp = @("-o", "BatchMode=yes")
    if ($portVps) { $optsSsh += @("-p", $portVps); $optsScp += @("-P", $portVps) }
    if ($cleSsh) { $optsSsh += @("-i", $cleSsh); $optsScp += @("-i", $cleSsh) }
    $compte = $utilisateur + "@" + $hote
    $distant = $dossierVps.TrimEnd('/') + "/" + $Nom

    # Ce qui part : les pieces marquees vps, la liste de leurs empreintes, le
    # manifeste. Jamais secrets/ : aucune piece ne le contient.
    $PiecesVps = @($Pieces | Where-Object { $_.vps })
    $sommes = @($PiecesVps | ForEach-Object { $_.sha256 + "  " + $_.nom })
    $sommes += ((Sha256 $CheminManifeste) + "  manifeste.json")
    $CheminSommes = Join-Path $Dossier "SHA256SUMS-vps"
    [System.IO.File]::WriteAllText($CheminSommes, (($sommes -join "`n") + "`n"), $utf8SansMarque)
    $envoi = @($PiecesVps | ForEach-Object { Join-Path $Dossier $_.nom }) + @($CheminManifeste, $CheminSommes)

    $r = Executer $Ssh ($optsSsh + @($compte, ("umask 077 && mkdir -p -- '" + $distant + "'"))) "vps-dossier"
    if ($r.Code -ne 0) {
        Arreter "Le VPS n'a pas repondu, ou a refuse la connexion." @(
            $r.Erreur,
            "Essayez d'abord a la main : ssh `$env:VPS_UTILISATEUR@`$env:VPS_HOTE",
            ("L'archive locale est faite : " + $Dossier))
    }
    $r = Executer $Scp ($optsScp + $envoi + @($compte + ":" + $distant + "/")) "vps-copie"
    if ($r.Code -ne 0) { Arreter "La copie vers le VPS a echoue." @($r.Erreur, ("L'archive locale est faite : " + $Dossier)) }

    # Verification LA-BAS : le VPS recalcule les empreintes de ce qu'il a recu.
    $r = Executer $Ssh ($optsSsh + @($compte, ("cd -- '" + $distant + "' && sha256sum -c SHA256SUMS-vps"))) "vps-verification"
    if ($r.Code -eq 0) {
        $VpsEtat = "copie et verifiee (sha256sum -c sur le VPS) : " + $PiecesVps.Count + " piece(s) + manifeste"
        Bon ("VPS : " + $VpsEtat)
        Note ("Sur le VPS : VPS_DOSSIER/" + $Nom)
    } else {
        $VpsEtat = "copiee mais NON verifiee"
        Souci "VPS : les empreintes ne se verifient pas la-bas. La copie ne compte pas."
        foreach ($l in (Lignes ($r.Sortie + "`n" + $r.Erreur))) { Note $l }
    }
    $restes = @($Pieces | Where-Object { -not $_.vps } | ForEach-Object { $_.nom })
    if ($restes.Count -gt 0) { Note ("Restees sur ce poste seulement : " + ($restes -join ", ")) }
}

# --- 5b. Rotation locale, si on la demande --------------------------------------
# Ne sont candidats que les dossiers studio-AAAAMMJJ-HHMMSS de la destination
# qui portent un manifeste du MEME projet ; le nom porte la date, le tri se fait
# sur lui. Celle qui vient d'etre faite n'est jamais candidate. Rien sur le VPS.
Titre "Rotation locale"
$Anciennes = @(Get-ChildItem -LiteralPath $Destination -Directory |
    Where-Object { $_.Name -match '^studio-[0-9]{8}-[0-9]{6}$' -and $_.Name -ne $Nom } |
    Where-Object {
        $m = Join-Path $_.FullName "manifeste.json"
        $ok = $false
        if (Test-Path -LiteralPath $m) {
            try { $ok = ((Get-Content -LiteralPath $m -Raw | ConvertFrom-Json).projet -eq $Projet) } catch { $ok = $false }
        }
        $ok
    } | Sort-Object Name -Descending)
function Taille-Dossier($d) {
    $s = (Get-ChildItem -LiteralPath $d -Recurse -File | Measure-Object -Property Length -Sum).Sum
    if (-not $s) { return 0 }
    return [int64]$s
}
$RotationEtat = "non demandee"
if ($Garder -eq 0) {
    $total = [int64]0
    foreach ($a in $Anciennes) { $total += Taille-Dossier $a.FullName }
    Note ("Sauvegardes plus anciennes du projet ici : " + $Anciennes.Count + ", " + [Math]::Round($total / 1GB, 1) + " Go.")
    Note "Rien n'est supprime. -Garder N garde les N plus recentes (celle-ci comprise)."
} else {
    $aSupprimer = @($Anciennes | Select-Object -Skip ($Garder - 1))
    $supprimees = @()
    foreach ($a in $aSupprimer) {
        try {
            Remove-Item -LiteralPath $a.FullName -Recurse -Force
            $supprimees += $a.Name
        } catch {
            Souci ("Non supprimee : " + $a.Name + " (" + $_.Exception.Message + ")")
        }
    }
    $RotationEtat = ("gardees " + [Math]::Min($Garder, $Anciennes.Count + 1) + ", supprimees " + $supprimees.Count)
    if ($supprimees.Count -gt 0) { Bon ("Supprimees : " + ($supprimees -join ", ")) }
    else { Bon ("Rien a supprimer : " + ($Anciennes.Count + 1) + " sauvegarde(s), " + $Garder + " gardee(s) au plus.") }
}

# --- 6. Ce qui a ete fait, et ce qui reste a faire a la main -------------------
Write-Host ""
Write-Host "  --------------------------------------------------------------" -ForegroundColor White
Write-Host ("  Sauvegarde " + $Nom + " (" + $Copie + ")") -ForegroundColor Green
Write-Host ("  Local : " + $Dossier)
foreach ($p in $Pieces) { Write-Host ("    " + $p.nom + "  " + $p.octets + " octets") }
if ($VolumesAbsents.Count -gt 0) { Write-Host ("  Volumes absents, NON sauvegardes : " + ($VolumesAbsents -join ", ")) -ForegroundColor Yellow }
Write-Host ("  VPS : " + $VpsEtat)
Write-Host ("  Rotation locale : " + $RotationEtat)
if ($CleRouteurEtat.retiree) {
    Write-Host ("  Cle du routeur : retiree de la copie du chat (" + $CleRouteurEtat.lignes + " ligne(s))")
} elseif ($CleRouteurEtat.note) {
    Write-Host ("  Cle du routeur : " + $CleRouteurEtat.note) -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  LA CLE DU COFFRE N'EST PAS DANS CETTE SAUVEGARDE." -ForegroundColor White
Write-Host "  Sans elle, les cles saisies sur les pages /cles ne se rouvrent pas."
if ($Cle.fichier_present) {
    Write-Host ("  Verifiez qu'elle est dans votre gestionnaire de mots de passe (empreinte " + $Cle.empreinte + ").")
    Write-Host "  Elle est ici : secrets\coffre.cle du dossier du Studio, une seule ligne (notepad secrets\coffre.cle)."
    Write-Host "  Rangez-la dans Chrome : chrome://password-manager/passwords > Ajouter ;"
    Write-Host "  site studio.local, utilisateur cle-du-coffre, mot de passe = la ligne."
    Write-Host "  Pas a pas : docs\SAUVEGARDES.md, 'Ou les trouver, precisement'."
} else {
    Write-Host "  secrets\coffre.cle est absent : la cle est peut-etre dans STUDIO_COFFRE_CLE (.env)."
}
Write-Host "  .env non plus n'est pas dans la sauvegarde : meme endroit."
Write-Host "  Une sauvegarde ne compte qu'une fois restauree : scripts\restaurer.ps1."
Write-Host "  --------------------------------------------------------------" -ForegroundColor White
