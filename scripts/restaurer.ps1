# Free AI Studio : remettre en place une sauvegarde faite par sauvegarder.ps1.
#
# Une sauvegarde ne compte que le jour ou elle a ete remise en place
# (docs/SAUVEGARDES.md : << DoD : restore-from-backup test passes >>). Ce script
# est l'outil de ce jour-la, et de l'essai qui le precede.
#
# PAR DEFAUT IL NE TOUCHE PAS AU STUDIO EN SERVICE. Il restaure dans une cible
# d'essai au nom distinct :
#   - un dossier d'essai, a cote du depot : <depot>-essai (un clone du depot,
#     fait ici s'il n'existe pas, remis a la version git de la sauvegarde),
#     qui recoit config/ et, si on la donne, secrets/coffre.cle ;
#   - deux volumes d'essai, au nom du dossier d'essai : par defaut
#     <depot>-essai_open-webui-data et <depot>-essai_sandbox-data. Ce sont les
#     noms que Docker Compose donne aux volumes quand on lance
#     << docker compose up >> DEPUIS le dossier d'essai : on peut donc y relancer
#     le Studio et voir s'il relit tout.
#
# -Reel vise le vrai config/ et les vrais volumes. Il faut en plus taper ECRASER.
# Meme alors, rien n'est detruit : l'ancien config/ est renomme, l'ancienne cle
# aussi, et un volume qui existe et n'est pas vide fait REFUSER la restauration
# (le supprimer est un geste irreversible, qui reste a la personne).
#
# Avant d'ecrire quoi que ce soit, chaque piece est comparee a l'empreinte
# SHA-256 du manifeste ; une seule difference et rien n'est ecrit.
#
# -DepuisVps <studio-AAAAMMJJ-HHMMSS> rapatrie d'abord ce dossier depuis le VPS,
# avec les seules variables VPS_HOTE, VPS_UTILISATEUR, VPS_DOSSIER (VPS_PORT_SSH
# et VPS_CLE_SSH facultatives), comme sauvegarder.ps1.
#
# Memes precautions PowerShell 5.1 que demarrer.ps1 : jamais << 2>&1 >> sur une
# commande native, jamais Out-File -Encoding utf8, jamais && ni ternaire.

param(
    # Dossier studio-AAAAMMJJ-HHMMSS fait par sauvegarder.ps1.
    [string]$Archive = "",
    # Ou bien : le nom de ce dossier sur le VPS, a rapatrier d'abord.
    [string]$DepuisVps = "",
    # Dossier d'essai (par defaut : a cote du depot, <depot>-essai).
    [string]$Cible = "",
    # Fichier contenant la cle du coffre. Sans lui, elle est demandee (saisie
    # masquee) ; -SansCle saute la question.
    [string]$FichierCle = "",
    [switch]$SansCle,
    [string]$Projet = "",
    # Vise le VRAI config/ et les VRAIS volumes. Demande en plus ECRASER.
    [switch]$Reel,
    [string]$Image = "alpine:3.20"
)

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot

$Journal = Join-Path $env:TEMP "free-ai-studio-restauration"
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

function Sha256($chemin) { return (Get-FileHash -LiteralPath $chemin -Algorithm SHA256).Hash.ToLower() }

# L'empreinte de la cle du coffre : 16 caracteres du SHA-256 du texte de la
# cle, espaces de bord retires (coffre.py fait le meme strip). Assez pour
# reconnaitre la bonne cle, rien pour la retrouver. MEME FONCTION, au caractere
# pres, dans sauvegarder.ps1 : un test le verifie.
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

function Plein($chemin) { return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($chemin).TrimEnd('\') }

$Horodatage = Get-Date -Format "yyyyMMdd-HHmmss"
$Tar = Join-Path $env:SystemRoot "System32\tar.exe"

Titre "Restauration du Studio"

if (-not $Projet) {
    if ($env:COMPOSE_PROJECT_NAME) { $Projet = $env:COMPOSE_PROJECT_NAME }
    else { $Projet = ((Split-Path -Leaf $Racine).ToLower() -replace '[^a-z0-9_-]', '') }
}

# --- 1. L'archive ---------------------------------------------------------------
if ($DepuisVps) {
    if ($Archive) { Arreter "-Archive et -DepuisVps se contredisent." @("Donnez l'un ou l'autre.") }
    if ($DepuisVps -notmatch '^studio-[0-9]{8}-[0-9]{6}$') {
        Arreter "Nom de sauvegarde inattendu." @("Attendu : studio-AAAAMMJJ-HHMMSS, tel que sauvegarder.ps1 l'a annonce.")
    }
    $hote = Variable-Vps "VPS_HOTE"
    $utilisateur = Variable-Vps "VPS_UTILISATEUR"
    $dossierVps = Variable-Vps "VPS_DOSSIER"
    $portVps = Variable-Vps "VPS_PORT_SSH"
    $cleSsh = Variable-Vps "VPS_CLE_SSH"
    if (-not $hote -or -not $utilisateur -or -not $dossierVps) {
        Arreter "Rapatrier depuis le VPS demande VPS_HOTE, VPS_UTILISATEUR et VPS_DOSSIER." @(
            "Posez-les dans l'environnement de votre session ou dans .env (noms dans .env.example).")
    }
    if ($hote -notmatch '^[A-Za-z0-9.:-]+$' -or $utilisateur -notmatch '^[A-Za-z0-9._-]+$' -or
        $dossierVps -notmatch '^[A-Za-z0-9._/-]+$' -or ($portVps -and $portVps -notmatch '^[0-9]+$')) {
        Arreter "Une variable du VPS contient un caractere refuse." @("Memes regles que sauvegarder.ps1.")
    }
    $Scp = "scp"
    $scpWin = Join-Path $env:SystemRoot "System32\OpenSSH\scp.exe"
    if (Test-Path -LiteralPath $scpWin) { $Scp = $scpWin }
    $optsScp = @("-o", "BatchMode=yes", "-r")
    if ($portVps) { $optsScp += @("-P", $portVps) }
    if ($cleSsh) { $optsScp += @("-i", $cleSsh) }
    $local = Join-Path $env:USERPROFILE ("Sauvegardes\" + $Projet + "\depuis-vps")
    New-Item -ItemType Directory -Path $local -Force | Out-Null
    if (Test-Path -LiteralPath (Join-Path $local $DepuisVps)) {
        Arreter "Ce dossier a deja ete rapatrie." @((Join-Path $local $DepuisVps), "Donnez-le par -Archive, ou deplacez-le d'abord.")
    }
    $source = $utilisateur + "@" + $hote + ":" + $dossierVps.TrimEnd('/') + "/" + $DepuisVps
    $r = Executer $Scp ($optsScp + @($source, $local)) "vps-rapatriement"
    if ($r.Code -ne 0) { Arreter "Le rapatriement depuis le VPS a echoue." @($r.Erreur) }
    $Archive = Join-Path $local $DepuisVps
    Bon ("Rapatrie depuis le VPS : " + $Archive)
}
if (-not $Archive) { Arreter "Quelle sauvegarde ?" @("Donnez -Archive <dossier studio-...> ou -DepuisVps <studio-...>.") }
$Archive = Plein $Archive
$CheminManifeste = Join-Path $Archive "manifeste.json"
if (-not (Test-Path -LiteralPath $CheminManifeste)) {
    Arreter "Pas de manifeste.json dans ce dossier." @($Archive, "Ce n'est pas un dossier fait par sauvegarder.ps1.")
}
$Manifeste = [System.IO.File]::ReadAllText($CheminManifeste) | ConvertFrom-Json
Note ("Sauvegarde " + $Manifeste.nom + " du " + $Manifeste.date + ", copie " + $Manifeste.copie)

# --- 2. Les empreintes, AVANT d'ecrire quoi que ce soit ------------------------
Titre "Verification des empreintes"
# Le manifeste lui-meme se verifie quand la copie vient du VPS.
$sommes = Join-Path $Archive "SHA256SUMS-vps"
if (Test-Path -LiteralPath $sommes) {
    $attendu = ""
    foreach ($l in [System.IO.File]::ReadAllLines($sommes)) {
        if ($l -match '^([0-9a-f]{64})  manifeste\.json$') { $attendu = $Matches[1] }
    }
    if ($attendu -and $attendu -ne (Sha256 $CheminManifeste)) {
        Arreter "manifeste.json ne correspond pas a son empreinte." @("Rien n'a ete ecrit.")
    }
}
$Presentes = @{}
$Absentes = @()
$Fausses = @()
foreach ($p in @($Manifeste.pieces)) {
    $chemin = Join-Path $Archive $p.nom
    if (-not (Test-Path -LiteralPath $chemin)) { $Absentes += $p.nom; continue }
    if ((Sha256 $chemin) -ne $p.sha256) { $Fausses += $p.nom; continue }
    $Presentes[$p.nom] = $chemin
    Bon ($p.nom + " : empreinte conforme")
}
foreach ($n in $Absentes) { Souci ($n + " : absente de ce dossier") }
if ($Fausses.Count -gt 0) {
    Arreter "Des pieces ne correspondent pas a leur empreinte. Rien n'a ete ecrit." @($Fausses)
}
if ($Presentes.Count -eq 0) { Arreter "Aucune piece a restaurer." @() }

# --- 3. La cible, et tout ce qui pourrait l'empecher ----------------------------
Titre "Cible"
if ($Reel) {
    $Dossier = [System.IO.Path]::GetFullPath($Racine).TrimEnd('\')
    $ProjetCible = $Projet
    Souci "Mode REEL : le vrai config/ et les vrais volumes du Studio."
    $mot = [string](Read-Host "Tapez ECRASER pour continuer")
    if ($mot -cne "ECRASER") { Arreter "Rien n'a ete ecrit." @() }
} else {
    if (-not $Cible) { $Cible = Join-Path (Split-Path -Parent $Racine) ((Split-Path -Leaf $Racine) + "-essai") }
    $Dossier = Plein $Cible
    $racinePleine = [System.IO.Path]::GetFullPath($Racine).TrimEnd('\')
    if (($Dossier + '\').StartsWith($racinePleine + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
        ($racinePleine + '\').StartsWith($Dossier + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        Arreter "La cible d'essai touche le dossier du Studio en service." @(
            ("Cible : " + $Dossier),
            "Choisissez un dossier a part. Pour le vrai dossier, c'est -Reel.")
    }
    # Le projet d'essai porte le nom du dossier d'essai, comme Docker Compose le
    # nommera quand on y lancera << docker compose up >> : les volumes restaures
    # sont alors ceux qu'il trouve. Deux essais dans deux dossiers ne se
    # marchent pas dessus.
    $ProjetCible = ((Split-Path -Leaf $Dossier).ToLower() -replace '[^a-z0-9_-]', '')
    if (-not $ProjetCible -or $ProjetCible -eq $Projet) {
        Arreter "Le dossier d'essai donnerait le meme projet Docker que le Studio en service." @(
            ("Projet : " + $Projet), "Donnez a -Cible un nom de dossier different.")
    }
}
Note ("Projet Docker cible : " + $ProjetCible)
Note ("Dossier : " + $Dossier)
$ConfigCible = Join-Path $Dossier "config"
$CleCible = Join-Path $Dossier "secrets\coffre.cle"

$aConfig = $Presentes.ContainsKey("config.tar") -or $Presentes.ContainsKey("config-magasins.tar")
$configPlein = (Test-Path -LiteralPath $ConfigCible) -and (@(Get-ChildItem -LiteralPath $ConfigCible -Force).Count -gt 0)
if ($aConfig -and $configPlein -and -not $Reel) {
    Arreter "Le dossier d'essai a deja un config/ (un essai precedent ?)." @(
        $ConfigCible, "Videz-le vous-meme, ou donnez une autre -Cible. Rien n'a ete ecrit.")
}

$Volumes = @("open-webui-data", "sandbox-data")
$aVolumes = @($Volumes | Where-Object { $Presentes.ContainsKey($_ + ".tar") })
$NomsCibles = @{}
$ACreer = @()
if ($aVolumes.Count -gt 0 -or $Reel) {
    $info = Executer "docker" @("info", "--format", "{{.ServerVersion}}") "docker-info"
    if ($info.Code -ne 0 -or -not $info.Sortie.Trim()) {
        Arreter "Docker ne tourne pas." @("Ouvrez Docker Desktop, attendez la baleine verte, puis relancez.")
    }
    # Rien ne doit tourner sur ce qu'on va remplir : ni les volumes, ni config/.
    $marche = Executer "docker" @("ps", "-q", "--filter", ("label=com.docker.compose.project=" + $ProjetCible)) "en-marche"
    if ((Lignes $marche.Sortie).Count -gt 0) {
        Arreter ("Le projet " + $ProjetCible + " tourne.") @(
            ("Arretez-le d'abord : docker compose -p " + $ProjetCible + " stop"), "Rien n'a ete ecrit.")
    }
}
if ($aVolumes.Count -gt 0) {
    foreach ($court in $aVolumes) {
        # Le nom : celui que Compose a deja donne s'il existe, sinon le sien.
        $nom = $ProjetCible + "_" + $court
        $r = Executer "docker" @("volume", "ls", "-q",
            "--filter", ("label=com.docker.compose.project=" + $ProjetCible),
            "--filter", ("label=com.docker.compose.volume=" + $court)) ("volume-" + $court)
        $trouves = @(Lignes $r.Sortie)
        if ($trouves.Count -eq 1) { $nom = $trouves[0] }
        $NomsCibles[$court] = $nom
        $existe = Executer "docker" @("volume", "inspect", $nom) ("inspect-" + $court)
        if ($existe.Code -ne 0) { $ACreer += $court; Note ("volume " + $nom + " : sera cree"); continue }
        $vide = Executer "docker" @("run", "--rm", "-v", ($nom + ":/donnees:ro"), $Image, "sh", "-c", "ls -A /donnees | head -n 1") ("vide-" + $court)
        if ($vide.Code -ne 0) { Arreter ("Le volume " + $nom + " n'a pas pu etre lu.") @($vide.Erreur) }
        if ($vide.Sortie.Trim()) {
            Arreter ("Le volume " + $nom + " existe et n'est pas vide. Rien n'a ete ecrit.") @(
                "Ce script n'ecrase pas un volume : le supprimer est irreversible, c'est a vous.",
                ("Si vous etes sur : docker volume rm " + $nom + "   puis relancez."))
        }
        Note ("volume " + $nom + " : existe, vide")
    }
}

# --- 4. La cle du coffre --------------------------------------------------------
# Elle n'est dans aucune archive. On la demande ; on ne l'affiche jamais.
$CleTexte = ""
$CleEtat = ""
if ($FichierCle) {
    $CleTexte = [System.IO.File]::ReadAllText((Plein $FichierCle)).Trim()
} elseif (-not $SansCle -and $Presentes.ContainsKey("config-magasins.tar")) {
    Note "La cle du coffre ouvre les cles restaurees. Ou la trouver :"
    Note "  1. votre gestionnaire de mots de passe, fiche 'Studio - cle du coffre' (dans Chrome : chrome://password-manager) ;"
    Note "  2. sinon, sur le PC d'origine : le fichier secrets\coffre.cle du dossier du Studio, une seule ligne (notepad secrets\coffre.cle)."
    $saisie = Read-Host "Collez-la ici (rien ne s'affiche ; Entree seule pour passer)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($saisie)
    try { $CleTexte = ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
$attendue = [string]$Manifeste.cle_du_coffre.empreinte
if ($CleTexte) {
    $donnee = Empreinte-Cle $CleTexte
    if ($attendue -and $donnee -ne $attendue) {
        Arreter "Cette cle n'est pas celle de la sauvegarde (empreintes differentes). Rien n'a ete ecrit." @(
            ("Attendue : " + $attendue + "   donnee : " + $donnee),
            "Si la cle en service etait STUDIO_COFFRE_CLE dans .env, c'est elle qu'il faut donner.")
    }
    if (-not $attendue) { $CleEtat = "posee, NON comparee (la sauvegarde n'en avait pas l'empreinte)" }
    else { $CleEtat = "posee, empreinte conforme (" + $donnee + ")" }
}

# --- 5. L'ecriture --------------------------------------------------------------
Titre "Restauration"
$Restaure = @()
$Manque = @()

if (-not (Test-Path -LiteralPath $Dossier)) {
    # Un clone du depot, pour pouvoir relancer le Studio sur l'essai. Local,
    # sans reseau, remis a la version de la sauvegarde.
    $r = Executer "git" @("clone", "--quiet", $Racine, $Dossier) "clone"
    if ($r.Code -ne 0) { Arreter "Le dossier d'essai n'a pas pu etre cree par git clone." @($r.Erreur) }
    $commit = [string]$Manifeste.version_git.commit
    if ($commit) {
        $r = Executer "git" @("-C", $Dossier, "checkout", "--quiet", $commit) "checkout"
        if ($r.Code -eq 0) { Bon ("Dossier d'essai : clone du depot, version " + $commit.Substring(0, [Math]::Min(12, $commit.Length))) }
        else { Souci "Clone fait, mais la version de la sauvegarde est introuvable : il reste sur la version courante." }
    } else {
        Bon "Dossier d'essai : clone du depot"
    }
}

if ($aConfig) {
    if ($Reel -and $configPlein) {
        $garde = $ConfigCible + ".avant-restauration-" + $Horodatage
        Rename-Item -LiteralPath $ConfigCible -NewName (Split-Path -Leaf $garde)
        Note ("Ancien config/ garde sous : " + $garde)
    }
    foreach ($piece in @("config.tar", "config-magasins.tar")) {
        if (-not $Presentes.ContainsKey($piece)) { continue }
        $r = Executer $Tar @("-xf", $Presentes[$piece], "-C", $Dossier) ("extraction-" + $piece)
        if ($r.Code -ne 0) { Arreter ($piece + " n'a pas pu etre extrait.") @($r.Erreur) }
        $Restaure += ($piece + " -> " + $ConfigCible)
        Bon ($piece + " -> config/")
    }
}

if ($CleTexte) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $CleCible) -Force | Out-Null
    if (Test-Path -LiteralPath $CleCible) {
        # Une cle deja en place n'est jamais ecrasee : elle ouvre peut-etre
        # autre chose que ce qu'on restaure.
        $ancienne = $CleCible + ".avant-restauration-" + $Horodatage
        Rename-Item -LiteralPath $CleCible -NewName (Split-Path -Leaf $ancienne)
        Note ("Ancienne cle gardee sous : " + $ancienne)
    }
    [System.IO.File]::WriteAllText($CleCible, $CleTexte, (New-Object System.Text.ASCIIEncoding))
    $CleTexte = $null
    $Restaure += ("cle du coffre -> " + $CleCible + " : " + $CleEtat)
    Bon ("cle du coffre : " + $CleEtat)
} elseif ((Test-Path -LiteralPath $CleCible) -and $attendue) {
    $enPlace = Empreinte-Cle ([System.IO.File]::ReadAllText($CleCible))
    if ($enPlace -eq $attendue) { Bon "cle du coffre deja en place, empreinte conforme" }
    else { $Manque += "la cle du coffre en place n'est PAS celle de la sauvegarde : les cles restaurees seront illisibles" }
} elseif ($Presentes.ContainsKey("config-magasins.tar")) {
    $Manque += "la cle du coffre : keys.json, sandbox-keys.json et la session NotebookLM sont restaures mais ILLISIBLES sans elle"
}

foreach ($court in $aVolumes) {
    $nom = $NomsCibles[$court]
    if ($ACreer -contains $court) {
        $r = Executer "docker" @("volume", "create",
            "--label", ("com.docker.compose.project=" + $ProjetCible),
            "--label", ("com.docker.compose.volume=" + $court), $nom) ("creation-" + $court)
        if ($r.Code -ne 0) { Arreter ("Le volume " + $nom + " n'a pas pu etre cree.") @($r.Erreur) }
    }
    $r = Executer "docker" @("run", "--rm", "-v", ($nom + ":/donnees"), "-v", ($Archive + ":/archive:ro"),
        $Image, "tar", "-xf", ("/archive/" + $court + ".tar"), "-C", "/donnees") ("extraction-" + $court)
    if ($r.Code -ne 0) { Arreter ("Le volume " + $nom + " n'a pas pu etre rempli.") @($r.Erreur) }
    # Chaque fichier revenu est recompare a la liste faite a la sauvegarde.
    $liste = $court + ".sha256.txt"
    if ($Presentes.ContainsKey($liste)) {
        $v = Executer "docker" @("run", "--rm", "-v", ($nom + ":/donnees:ro"), "-v", ($Archive + ":/archive:ro"),
            $Image, "sh", "-c", ("cd /donnees && sha256sum -c -s /archive/" + $liste)) ("controle-" + $court)
        if ($v.Code -eq 0) { $Restaure += ("volume " + $court + " -> " + $nom + " : fichiers conformes a la liste") ; Bon ("volume " + $nom + ", fichiers conformes") }
        else { $Restaure += ("volume " + $court + " -> " + $nom + " : ECARTS avec la liste des fichiers"); Souci ("volume " + $nom + " : des fichiers different de la liste (copie " + $Manifeste.copie + ")") }
    } else {
        $Restaure += ("volume " + $court + " -> " + $nom + " : fichiers non compares (liste absente)")
        Bon ("volume " + $nom)
    }
}

# La cle du routeur, retiree de la copie du chat par sauvegarder.ps1 (27/09/2026).
# Elle revient du .env de la CIBLE, s'il existe deja ; sinon, a remettre apres.
$remettre = Join-Path $PSScriptRoot "remettre-cle-routeur.ps1"
$commandeRemettre = "powershell -ExecutionPolicy Bypass -File scripts\remettre-cle-routeur.ps1 -Cible " + $Dossier
if ($Reel) { $commandeRemettre = "powershell -ExecutionPolicy Bypass -File scripts\remettre-cle-routeur.ps1 -Reel" }
if (($aVolumes -contains "open-webui-data") -and $Manifeste.cle_du_routeur -and $Manifeste.cle_du_routeur.retiree) {
    $envCible = Join-Path $Dossier ".env"
    $aCle = (Test-Path -LiteralPath $envCible) -and
        (@([System.IO.File]::ReadAllLines($envCible) | Where-Object { $_ -match '^FREE_TIER_MANAGER_KEY=.+' }).Count -gt 0)
    if ($aCle) {
        if ($Reel) { & $remettre -Reel -Projet $Projet } else { & $remettre -Cible $Dossier -Projet $Projet }
        if ($LASTEXITCODE -eq 0) { $Restaure += "cle du routeur -> chat, depuis le .env de la cible" }
        else { $Manque += ("la cle du routeur dans le chat : la remettre a echoue ; relancez " + $commandeRemettre) }
    } else {
        $Manque += ("la cle du routeur dans le chat (retiree de la sauvegarde) : copiez .env dans " + $Dossier +
            ", puis " + $commandeRemettre + " ; sans elle, le chat restaure est refuse par son routeur")
    }
}

foreach ($n in $Absentes) { $Manque += ($n + " : absente de cette copie") }
foreach ($court in @($Manifeste.volumes_absents)) { if ($court) { $Manque += ("volume " + $court + " : n'existait pas a la sauvegarde") } }
$Manque += ".env : jamais dans une sauvegarde (gestionnaire de mots de passe)"

# --- 6. Le compte rendu ---------------------------------------------------------
Write-Host ""
Write-Host "  --------------------------------------------------------------" -ForegroundColor White
Write-Host ("  Sauvegarde " + $Manifeste.nom + " restauree dans " + $Dossier) -ForegroundColor Green
Write-Host "  Restaure :"
foreach ($l in $Restaure) { Write-Host ("    " + $l) }
Write-Host "  Manque :" -ForegroundColor Yellow
foreach ($l in $Manque) { Write-Host ("    " + $l) -ForegroundColor Yellow }
Write-Host ""
if (-not $Reel) {
    Write-Host "  Rien du Studio en service n'a ete touche."
    Write-Host ("  Pour voir si le Studio relit tout : docs\SAUVEGARDES.md, essai pas a pas (projet " + $ProjetCible + ").")
} else {
    Write-Host "  Relancez le Studio : double-cliquez demarrer.cmd."
}
Write-Host "  --------------------------------------------------------------" -ForegroundColor White
