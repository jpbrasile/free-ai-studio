# Free AI Studio : installation et demarrage, en un seul geste.
#
# Ce fichier est fait pour quelqu'un qui n'ouvrira jamais un terminal. Il est
# donc lance par demarrer.cmd, qui se double-clique, et il ne suppose rien :
# ni Docker installe, ni Docker demarre, ni les ports libres, ni le .env cree.
# Chaque verification qui echoue dit CE QU'IL FAUT FAIRE, pas ce qui a rate.
#
# Trois pieges de PowerShell 5.1 sont evites ici, tous rencontres pour de vrai :
#   - jamais << 2>&1 >> sur une commande native : chaque ligne que Docker ecrit
#     sur sa sortie d'erreur (<< Image ... Building >>, qui n'est pas une erreur)
#     deviendrait une erreur bloquante ;
#   - jamais Out-File -Encoding utf8 : il pose trois octets invisibles en tete
#     que json.loads refuse ;
#   - jamais && ni l'operateur ternaire : ils n'existent pas dans cette version.

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
Set-Location $Racine

$Journal = Join-Path $env:TEMP "free-ai-studio-demarrage"
if (-not (Test-Path $Journal)) { New-Item -ItemType Directory -Path $Journal | Out-Null }

function Titre($texte) {
    Write-Host ""
    Write-Host ("== " + $texte) -ForegroundColor Cyan
}
function Bon($texte)   { Write-Host ("   OK   " + $texte) -ForegroundColor Green }
function Note($texte)  { Write-Host ("   ..   " + $texte) -ForegroundColor Gray }
function Souci($texte) { Write-Host ("   !    " + $texte) -ForegroundColor Yellow }

function Abandonner($titre, $quoiFaire, $lien) {
    Write-Host ""
    Write-Host ("ARRET : " + $titre) -ForegroundColor Red
    Write-Host ""
    Write-Host "Ce qu'il faut faire :" -ForegroundColor White
    foreach ($ligne in $quoiFaire) { Write-Host ("  " + $ligne) }
    if ($lien) {
        Write-Host ""
        Write-Host ("J'ouvre la page : " + $lien)
        try { Start-Process $lien } catch { Write-Host "  (ouvrez-la a la main)" }
    }
    Write-Host ""
    Write-Host "Puis double-cliquez de nouveau sur demarrer.cmd."
    exit 1
}

# Lance un programme et rend son code de sortie ET son texte, sans que la
# moindre ligne d'avancement soit prise pour une erreur.
function Executer($programme, $arguments, $etiquette) {
    $sortie = Join-Path $Journal ($etiquette + ".out.txt")
    $erreur = Join-Path $Journal ($etiquette + ".err.txt")
    $p = Start-Process -FilePath $programme -ArgumentList $arguments `
        -WorkingDirectory $Racine -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $sortie -RedirectStandardError $erreur
    $texte = @()
    foreach ($f in @($sortie, $erreur)) {
        if (Test-Path $f) { $texte += (Get-Content $f -ErrorAction SilentlyContinue) }
    }
    # La sortie standard seule : c'est elle qui porte une reponse (une version,
    # un etat) ; la sortie d'erreur ne porte que des plaintes.
    $seule = @()
    if (Test-Path $sortie) { $seule = @(Get-Content $sortie -ErrorAction SilentlyContinue) }
    return [pscustomobject]@{ Code = $p.ExitCode; Texte = ($texte -join "`n"); Sortie = ($seule -join "`n") }
}

Write-Host ""
Write-Host "  Free AI Studio" -ForegroundColor White
Write-Host "  Installation et demarrage. Laissez cette fenetre ouverte."
Write-Host "  Le premier demarrage prend plusieurs minutes : les programmes se telechargent."

# --- 1. Windows PowerShell -----------------------------------------------------
Titre "Verification de l'ordinateur"
$v = $PSVersionTable.PSVersion
if ($v.Major -lt 5) {
    Abandonner "Cette version de Windows est trop ancienne (PowerShell $v)." `
        @("Il faut Windows 10 ou plus recent.") $null
}
Bon ("Windows PowerShell " + $v)

# Docker Desktop exige Windows 10 22H2 (build 19045) ou Windows 11 23H2 (build
# 22631), en 64 bits. En dessous, il s'installe mal ou ne demarre pas, avec des
# messages qui ne parlent jamais de la version de Windows.
if (-not [Environment]::Is64BitOperatingSystem) {
    Abandonner "Ce Windows est en 32 bits." `
        @("Docker Desktop, donc le Studio, demande un Windows 64 bits.") $null
}
$build = 0
try { $build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber } catch { }
if ($build -eq 0) {
    Note "Version de Windows non lue : on continue."
} elseif ($build -lt 19045 -or ($build -ge 22000 -and $build -lt 22631)) {
    Souci ("Windows trop ancien pour Docker Desktop (build " + $build + ").")
    Note  "Il faut Windows 10 22H2 ou Windows 11 23H2, ou plus recent :"
    Note  "Parametres > Windows Update, tout installer, redemarrer, puis relancer demarrer.cmd."
} elseif ($build -lt 22000) {
    Bon ("Windows 10 22H2 (build " + $build + ")")
    Note "Microsoft ne maintient plus Windows 10 depuis octobre 2025. Docker Desktop y"
    Note "marche encore (essai du 13/09/2026), sans garantie pour la suite."
} else {
    Bon ("Windows 11 (build " + $build + ")")
}

# --- 2. Docker installe --------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Abandonner "Docker Desktop n'est pas installe." `
        @("1. Telechargez Docker Desktop sur la page qui va s'ouvrir.",
          "2. Installez-le (suivant, suivant, terminer).",
          "3. Redemarrez l'ordinateur si on vous le demande.",
          "4. Ouvrez Docker Desktop et attendez que la baleine, en bas a gauche, soit verte.") `
        "https://www.docker.com/products/docker-desktop/"
}
Bon "Docker Desktop est installe"

# --- 3. Docker demarre ---------------------------------------------------------
# << installe >> et << en train de tourner >> sont deux choses differentes, et
# c'est la deuxieme qui manque neuf fois sur dix.
$info = Executer "docker" @("info", "--format", "{{.ServerVersion}}") "docker-info"
# Le code seul ne suffit pas. Essai du 13/09/2026, Docker Desktop de 2023
# (client 23.0.5) : moteur arrete, << docker info >> rend le code 0, une sortie
# vide et l'erreur sur l'autre canal. Le script annoncait << Docker tourne >>,
# la construction echouait plus loin avec un conseil hors sujet, et le
# diagnostic de virtualisation ci-dessous n'etait jamais montre. Sans numero
# de version, le moteur ne tourne pas.
$moteur = $info.Sortie.Trim()
if ($info.Code -ne 0 -or -not $moteur) {

    # Docker refuse de demarrer pour trois raisons tres differentes, qui
    # demandent trois gestes tres differents. Se tromper de raison, c'est
    # envoyer quelqu'un fouiller le BIOS alors qu'il suffisait de cocher une
    # case -- ou l'inverse. On regarde donc avant de parler.
    #
    # ATTENTION au piege, mesure le 09/09 sur une machine qui MARCHE :
    # VirtualizationFirmwareEnabled y vaut False, et VMMonitorModeExtensions
    # aussi. Ce n'est pas une panne : des qu'un hyperviseur tourne, Windows
    # s'execute au-dessus de lui et ne voit plus les drapeaux bruts du
    # processeur. Ces deux valeurs ne veulent donc dire quelque chose que
    # lorsque AUCUN hyperviseur ne tourne. La valeur qui tranche est
    # HypervisorPresent.
    $hyperviseur = $null
    $firmware = $null
    $marque = ""
    try {
        $hyperviseur = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
        $proc = Get-CimInstance Win32_Processor | Select-Object -First 1
        $firmware = $proc.VirtualizationFirmwareEnabled
        $marque = [string]$proc.Manufacturer
    } catch { }

    $reglageBios = "Intel Virtualization Technology (VT-x)"
    if ($marque -match "AMD") { $reglageBios = "SVM Mode (AMD-V)" }

    # Les deux cases a cocher dans << fonctionnalites Windows >>. Get-WindowsOptionalFeature
    # exige l'elevation et serait donc inutilisable ici, mais la meme information passe par
    # WMI SANS elevation (mesure le 09/09) : InstallState 1 = activee, 2 = non.
    # Mesure du meme jour sur une machine qui marche : HypervisorPlatform vaut 2. Cette
    # troisieme case n'est donc PAS necessaire -- l'exiger enverrait cocher pour rien.
    $vmp = $null
    $wslCase = $null
    try {
        Get-CimInstance -ClassName Win32_OptionalFeature `
            -Filter "Name='VirtualMachinePlatform' OR Name='Microsoft-Windows-Subsystem-Linux'" |
            ForEach-Object {
                if ($_.Name -eq "VirtualMachinePlatform") { $vmp = [int]$_.InstallState }
                else { $wslCase = [int]$_.InstallState }
            }
    } catch { }

    $wsl = Executer "wsl" @("--status") "wsl-status"

    if ($hyperviseur -eq $false -and $firmware -eq $false) {
        Abandonner "La virtualisation est eteinte dans le micrologiciel de la carte mere." `
            @("C'est exactement ce que dit Docker par << Virtualization support not detected >>.",
              "Le processeur en est capable, mais l'interrupteur est sur arret. Il faut le",
              "basculer dans le reglage de la carte mere -- une fois pour toutes.",
              "",
              "Verifier d'abord, sans rien risquer :",
              "  Ctrl+Maj+Echap (gestionnaire des taches) > Performance > Processeur.",
              "  La ligne << Virtualisation >> doit dire Active. Si elle dit Desactive, continuez.",
              "",
              "Y aller sans deviner la touche du demarrage :",
              "  Parametres > Systeme > Recuperation > Demarrage avance > Redemarrer maintenant",
              "  puis Depannage > Options avancees > Changer les parametres du microprogramme UEFI",
              "",
              "Une fois dedans, chercher dans Advanced ou CPU Configuration :",
              ("  " + $reglageBios + "  -> Enabled"),
              "Enregistrer et quitter (souvent F10). Windows redemarre.") $null
    }

    if ($hyperviseur -eq $false) {
        $aCocher = @()
        if ($vmp -ne 1) { $aCocher += "Plateforme de machine virtuelle" }
        if ($wslCase -ne 1) { $aCocher += "Sous-systeme Windows pour Linux" }

        # Les deux cases sont cochees et pourtant aucun hyperviseur ne tourne : il
        # manque le redemarrage. C'est le geste qu'on saute, et sans ce message la
        # personne recoche indefiniment des cases deja cochees.
        if ($aCocher.Count -eq 0) {
            Abandonner "Les composants Windows sont coches, mais l'ordinateur n'a pas redemarre." `
                @("Plateforme de machine virtuelle et Sous-systeme Windows pour Linux sont",
                  "bien actives. Ils ne se chargent qu'au demarrage de Windows : tant que",
                  "l'ordinateur n'a pas redemarre, la case est cochee et rien n'a change.",
                  "Fermer et rouvrir Docker Desktop ne suffit pas.",
                  "",
                  "  1. REDEMARRER l'ordinateur (un vrai redemarrage, pas une mise en veille).",
                  "  2. Ouvrir Docker Desktop, attendre la baleine verte.",
                  "  3. Double-cliquer de nouveau sur demarrer.cmd.",
                  "",
                  "Deja redemarre, et ce message revient ? L'hyperviseur est peut-etre coupe",
                  "au demarrage de Windows (certains logiciels le font). Touche Windows, taper",
                  "cmd, clic droit > Executer en tant qu'administrateur, puis taper :",
                  "  bcdedit /set hypervisorlaunchtype auto",
                  "et redemarrer. (Ce reglage ne se lit pas sans droits d'administrateur.)") $null
        }

        $lignes = @("Le processeur est pret, mais il manque une piece du cote de Windows.",
                    "",
                    "  1. Touche Windows, taper : fonctionnalites windows",
                    "  2. Ouvrir << Activer ou desactiver des fonctionnalites Windows >>")
        $numero2 = 3
        foreach ($case in $aCocher) {
            $lignes += ("  " + $numero2 + ". Cocher : " + $case)
            $numero2 = $numero2 + 1
        }
        $lignes += ("  " + $numero2 + ". OK, puis REDEMARRER l'ordinateur (indispensable).")
        $lignes += ""
        if ($vmp -eq $null -and $wslCase -eq $null) {
            $lignes += "(L'etat de ces cases n'a pas pu etre lu : verifiez les deux.)"
        } else {
            $lignes += "Les autres cases de cette liste n'ont pas a etre touchees."
        }
        $lignes += "Au redemarrage, ouvrir Docker Desktop et attendre la baleine verte."
        Abandonner "Il manque un composant Windows de virtualisation." $lignes $null
    }

    if ($wsl.Code -ne 0) {
        Abandonner "Docker ne demarre pas : sa machine Linux (WSL) repond mal." `
            @("La virtualisation est bonne, c'est WSL qui coince.",
              "",
              "  1. Ouvrir Docker Desktop : il propose souvent lui-meme de reparer WSL.",
              "     Accepter, puis redemarrer l'ordinateur.",
              "  2. Si rien n'est propose, installer la mise a jour du noyau WSL :",
              "     https://aka.ms/wsl2kernel",
              "",
              "Ensuite, rouvrir Docker Desktop et attendre la baleine verte.") $null
    }

    # Si la lecture du materiel a echoue plus haut, $hyperviseur vaut $null et on
    # arrive ici sans rien savoir. Ecrire quand meme << la virtualisation est en
    # ordre >> serait affirmer une mesure qu'on n'a pas faite, et envoyer quelqu'un
    # cliquer sur Docker en boucle alors que son micrologiciel est eteint. On dit
    # donc ce qu'on sait, et rien de plus.
    $premiereLigne = "La virtualisation est en ordre : il ne manque que le demarrage."
    if ($null -eq $hyperviseur) {
        $premiereLigne = "L'etat de la virtualisation n'a pas pu etre lu ; commencez par le plus simple."
    }
    Abandonner "Docker Desktop est installe, mais il ne tourne pas." `
        @($premiereLigne,
          "",
          "  1. Ouvrez Docker Desktop (menu Demarrer).",
          "  2. Attendez que la baleine, en bas a gauche, devienne verte.",
          "     Une a deux minutes au premier lancement.",
          "",
          "Pour ne plus y penser : dans Docker Desktop, Settings > General,",
          "cocher << Start Docker Desktop when you sign in >>.") $null
}
Bon ("Docker tourne (moteur " + $moteur + ")")

# --- 4. Les trois portes libres ------------------------------------------------
# Un autre programme deja assis sur le port 3000 ferait echouer le demarrage
# beaucoup plus loin, avec un message que personne ne peut relier a la cause.
$portsOccupes = @()
foreach ($port in @(3000, 8010, 8020)) {
    try {
        $prise = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if ($prise) {
            # Surtout pas $pid : c'est une variable reservee de PowerShell, en
            # lecture seule, et y ecrire arrete le script.
            $numero = ($prise | Select-Object -First 1).OwningProcess
            $nom = "programme inconnu"
            try { $nom = (Get-Process -Id $numero -ErrorAction Stop).ProcessName } catch { }
            # Nos propres conteneurs tiennent ces ports quand le Studio tourne
            # deja : ce n'est pas un conflit, c'est un redemarrage.
            if ($nom -notmatch "docker|com.docker|vpnkit|wslrelay") {
                $portsOccupes += ("port " + $port + " tenu par " + $nom)
            }
        }
    } catch {
        Note ("port " + $port + " non verifiable sur cette machine")
    }
}
if ($portsOccupes.Count -gt 0) {
    Abandonner "Une porte necessaire est deja prise." `
        (@("Fermez le programme concerne, puis relancez :") + $portsOccupes) $null
}
Bon "Les ports 3000, 8010 et 8020 sont libres"

# --- 5. Le code est-il complet ? -----------------------------------------------
if (-not (Test-Path (Join-Path $Racine "docker-compose.yml"))) {
    Abandonner "Le dossier ne contient pas Free AI Studio." `
        @("Vous avez lance ce fichier depuis le mauvais endroit,",
          "ou le telechargement est incomplet.",
          "Le dossier doit contenir docker-compose.yml, .env.example et le dossier scripts.") $null
}
$aGit = Test-Path (Join-Path $Racine ".git")
if ($aGit) {
    Bon "Dossier complet, avec son historique : le bouton de mise a jour marchera"
} else {
    Souci "Dossier obtenu par telechargement ZIP : pas d'historique."
    Note  "Tout fonctionnera, SAUF le bouton << Mettre a jour >>, qui ne saura pas"
    Note  "quelle version vous avez. Pour l'avoir, reprenez le dossier avec"
    Note  "VS Code : Ctrl+Shift+P, puis << Git: Clone >>."
}

# --- 6. Le fichier de reglages -------------------------------------------------
Titre "Reglages"
$cheminEnv = Join-Path $Racine ".env"
if (-not (Test-Path $cheminEnv)) {
    Copy-Item (Join-Path $Racine ".env.example") $cheminEnv
    Bon ".env cree a partir de .env.example"
} else {
    Bon ".env deja present : vos reglages sont conserves"
}

# UTF-8 SANS marque d'octets : avec la marque, les accents des commentaires sont
# abimes et certains lecteurs refusent le fichier.
$utf8SansMarque = New-Object System.Text.UTF8Encoding($false)

function Nouveau-Secret {
    $octets = New-Object byte[] 32
    # RandomNumberGenerator::Fill n'existe qu'a partir de PowerShell 7.
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($octets) } finally { $rng.Dispose() }
    return (-join ($octets | ForEach-Object { $_.ToString("x2") }))
}

$creees = 0
foreach ($nom in @("WEBUI_SECRET_KEY", "FREE_TIER_MANAGER_KEY", "SANDBOX_MANAGER_KEY", "SANDBOX_WORKER_KEY")) {
    $contenu = [System.IO.File]::ReadAllText($cheminEnv, $utf8SansMarque)
    if ($contenu -notmatch "(?m)^$nom=.+$") {
        $valeur = Nouveau-Secret
        $contenu = [regex]::Replace($contenu, "(?m)^$nom=.*$", "$nom=$valeur")
        if ($contenu -notmatch "(?m)^$nom=") { $contenu += "`n$nom=$valeur`n" }
        [System.IO.File]::WriteAllText($cheminEnv, $contenu, $utf8SansMarque)
        $creees = $creees + 1
    }
}
if ($creees -gt 0) {
    Bon ("$creees mot(s) de passe interne(s) fabrique(s) au hasard, dans .env")
    Note "Ils ne sortent jamais de cet ordinateur. Ne les partagez pas."
} else {
    Bon "Mots de passe internes deja en place"
}

# --- 7. Construction et demarrage ----------------------------------------------
Titre "Demarrage des services"
Note "Premiere fois : plusieurs minutes de telechargement. C'est normal."
# La carte de la maison, si elle existe. La surcouche docker-compose.gpu.yml
# n'est ajoutee QUE si une carte repond : une reservation `driver: nvidia` sur
# une machine sans carte fait ECHOUER `docker compose up`, et le debutant sans
# carte -- le cas le plus courant -- ne doit jamais rencontrer ce message.
# Mesure du 19/09/2026 sur cette machine : le passage de la carte par WSL2
# marche deja, sans image CUDA (`docker run --gpus all python:3.12-slim
# nvidia-smi` rend la 4090). Ce que la surcouche donne, c'est la MESURE de la
# memoire libre au lancement ; faire tourner un modele dessus est la phase 2,
# decrite dans docs/GPU-LOCAL.md.
$argsCompose = @("compose")
$carte = $null
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    try {
        $releve = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
        if ($LASTEXITCODE -eq 0 -and $releve) { $carte = ($releve | Select-Object -First 1).Trim() }
    } catch { $carte = $null }
}
if ($carte) {
    $argsCompose += @("-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml")
    Bon "Carte graphique vue : $carte"
}
$argsCompose += @("up", "-d", "--build")
$up = Executer "docker" $argsCompose "compose-up"
if ($up.Code -ne 0) {
    # Les 25 dernieres lignes defilent dans une fenetre noire qu'on ne sait pas
    # faire remonter et encore moins recopier. Le texte entier existe deja sur le
    # disque ; on l'ecrit dans UN fichier lisible et on l'ouvre dans le Bloc-notes,
    # pour que la personne n'ait qu'a le montrer.
    $rapport = Join-Path $Journal "erreur-demarrage.txt"
    try {
        [System.IO.File]::WriteAllText($rapport, $up.Texte, (New-Object System.Text.UTF8Encoding($false)))
    } catch { $rapport = "" }

    Write-Host ""
    Write-Host "Le demarrage a echoue. Les dernieres lignes :" -ForegroundColor Red
    ($up.Texte -split "`n" | Select-Object -Last 25) | ForEach-Object { Write-Host ("   " + $_) }

    # Le conseil depend de ce que Docker a ecrit. Essai du 13/09/2026 : moteur
    # arrete (<< error during connect ... docker_engine >>), et le script parlait
    # d'un magasin d'images en panne, faisant relancer pour rien.
    $t = $up.Texte
    if ($t -match "error during connect|docker_engine|daemon is not running|Cannot connect to the Docker daemon") {
        $quoiFaire = @("Docker Desktop s'est arrete, ou ne tourne pas vraiment.",
                       "",
                       "  1. Ouvrez Docker Desktop et attendez la baleine verte.",
                       "  2. S'il affiche << Virtualization support not detected >> :",
                       "     docs\DEPANNAGE.md, dans ce dossier, donne la marche a suivre.",
                       "  3. Double-cliquez de nouveau sur demarrer.cmd.")
    } elseif ($t -match "no space left on device") {
        $quoiFaire = @("Le disque est plein.",
                       "",
                       "  Liberez de la place (compter 25 Go pour le Studio), puis relancez demarrer.cmd.",
                       "  Docker range ses donnees sur C: ; pour les mettre ailleurs :",
                       "  Docker Desktop > Settings > Resources > Advanced > Disk image location.")
    } elseif ($t -match "port is already allocated|ports are not available|address already in use") {
        $quoiFaire = @("Une porte (3000, 8010 ou 8020) a ete prise par un autre programme",
                       "pendant le demarrage. Fermez-le, puis relancez demarrer.cmd.")
    } elseif ($t -match "500 Internal Server Error|502 Bad Gateway|503 Service Unavailable|connection reset|TLS handshake timeout|i/o timeout|unexpected EOF|toomanyrequests") {
        $quoiFaire = @("Le magasin d'images de Docker, sur Internet, repond mal : ce n'est pas",
                       "votre ordinateur. Cela passe le plus souvent en une minute.",
                       "",
                       "  1. Double-cliquez de nouveau sur demarrer.cmd.",
                       "  2. Si cela recommence trois fois de suite, ce n'est plus un hasard :",
                       "     montrez le rapport complet, ouvert dans le Bloc-notes.")
    } else {
        $quoiFaire = @("La cause n'est pas de celles que ce script reconnait.",
                       "",
                       "  1. Verifiez que la baleine de Docker Desktop est verte,",
                       "     puis double-cliquez de nouveau sur demarrer.cmd.",
                       "  2. Si cela recommence : montrez le rapport complet, ouvert dans",
                       "     le Bloc-notes, a quelqu'un qui peut aider.")
    }
    if ($rapport) {
        $quoiFaire += @("", ("Rapport complet : " + $rapport))
        try { Start-Process "notepad.exe" $rapport | Out-Null } catch { }
    }
    Abandonner "Docker n'a pas pu construire ou demarrer les services." $quoiFaire $null
}
Bon "Services demarres"

# --- 8. Le veilleur de mise a jour ---------------------------------------------
# Un conteneur ne peut pas se reconstruire lui-meme. Ce petit veilleur tourne
# sous votre compte : c'est lui qui donne au bouton de la page le pouvoir d'agir.
# Il tourne sans fenetre (une fenetre reduite se ferme par megarde) et pose
# lui-meme un raccourci dans le dossier Demarrage, pour repartir a chaque
# ouverture de session : apres un redemarrage, Docker relance le Studio tout
# seul, sans passer par ici (essai du 13/09/2026 : bouton inerte sur l'autre
# ordinateur). Il refuse de tourner en double.
$veilleuse = Join-Path $Racine "config\maj-veilleuse.json"
$vivante = $false
if (Test-Path $veilleuse) {
    $age = (Get-Date) - (Get-Item $veilleuse).LastWriteTime
    if ($age.TotalSeconds -lt 30) { $vivante = $true }
}
if ($vivante) {
    Bon "Veilleur de mise a jour deja en marche"
} else {
    $script = Join-Path $PSScriptRoot "maj-veilleuse.ps1"
    if (Test-Path $script) {
        # Guillemets obligatoires : Start-Process ne les met pas, et un chemin
        # avec une espace (C:\Users\Jean Dupont\...) coupait l'appel en deux --
        # le veilleur ne demarrait pas, et la ligne suivante disait le contraire.
        $depart = (Get-Date).AddSeconds(-1)
        Start-Process -FilePath "powershell" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", ('"' + $script + '"')) `
            -WorkingDirectory $Racine -WindowStyle Hidden | Out-Null
        # On ne l'annonce qu'une fois son premier signe de vie ecrit.
        $parti = $false
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Seconds 1
            if ((Test-Path $veilleuse) -and ((Get-Item $veilleuse).LastWriteTime -ge $depart)) { $parti = $true; break }
        }
        if ($parti) {
            Bon "Veilleur de mise a jour lance, sans fenetre ; il repartira seul avec Windows"
        } else {
            Souci "Le veilleur de mise a jour n'a pas demarre."
            Note  "Le Studio marche ; seul le bouton << Mettre a jour >> renverra vers ce fichier."
        }
    }
}

# --- 9. Attendre que la page reponde vraiment ----------------------------------
Titre "Verification"
$pret = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8010/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $pret = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $pret) {
    Souci "La page ne repond pas encore apres deux minutes."
    Note  "Les services viennent peut-etre de demarrer. Ouvrez quand meme :"
    Note  "http://127.0.0.1:8010/studio"
} else {
    Bon "Le Studio repond"
}

# Le Studio repond bien avant le chat : Open WebUI met plusieurs minutes a
# s'ouvrir la premiere fois. Ouvrir la page tout de suite, c'etait envoyer vers
# des liens << Chat >> muets (essai du 13/09/2026).
function Chat-Repond {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:3000/health" -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}
function Attendre-Chat($secondes) {
    $fin = (Get-Date).AddSeconds($secondes)
    while ((Get-Date) -lt $fin) {
        if (Chat-Repond) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}
if ($pret) {
    Note "Ouverture du chat (au premier demarrage : jusqu'a quelques minutes)"
    $chatPret = Attendre-Chat 300
    if (-not $chatPret) {
        # Mesure du 13/09/2026 : Open WebUI se dit en bonne sante DANS Docker, mais
        # le relais de Docker Desktop vers le port 3000 ne transmet plus rien
        # (page vide, ERR_EMPTY_RESPONSE). Redemarrer le seul conteneur du chat a
        # suffi ; ses conversations et reglages restent sur son volume.
        $sante = Executer "docker" @("inspect", "--format", "{{.State.Health.Status}}", "free-ai-studio-open-webui") "chat-sante"
        if ($sante.Sortie.Trim() -eq "healthy") {
            Note "Le chat tourne mais ne repond pas sur le port 3000 : je le redemarre."
            $relance = Executer "docker" @("compose", "restart", "open-webui") "chat-relance"
            if ($relance.Code -eq 0) { $chatPret = Attendre-Chat 120 }
        }
    }
    if ($chatPret) {
        Bon "Le chat repond"
    } else {
        Souci "Le chat ne repond pas encore sur http://localhost:3000"
        Note  "La page du Studio le dira des qu'il sera pret. S'il ne vient pas :"
        Note  "redemarrez Docker Desktop, puis relancez demarrer.cmd."
    }
}

# --- 10. Ce qu'il reste a faire ------------------------------------------------
Write-Host ""
Write-Host "  --------------------------------------------------------------" -ForegroundColor White
Write-Host "  Free AI Studio est installe." -ForegroundColor Green
Write-Host ""
Write-Host "  Votre page : http://127.0.0.1:8010/studio"
Write-Host ""
Write-Host "  IL RESTE UNE CHOSE : donner une cle gratuite pour le chat." -ForegroundColor White
Write-Host "  Sur la page, cliquez << Cles >>, puis suivez les instructions."
Write-Host "  Une cle Google Gemini gratuite suffit pour ecrire, lire une image"
Write-Host "  et fabriquer une image. Rien n'est payant."
Write-Host ""
Write-Host "  La prochaine fois, double-cliquez simplement demarrer.cmd."
Write-Host "  --------------------------------------------------------------" -ForegroundColor White
Write-Host ""

if ($pret) {
    try { Start-Process "http://127.0.0.1:8010/studio" } catch { }
}
