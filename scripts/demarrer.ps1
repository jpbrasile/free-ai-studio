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
    return [pscustomobject]@{ Code = $p.ExitCode; Texte = ($texte -join "`n") }
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
if ($info.Code -ne 0) {

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
        Abandonner "Les composants Windows de virtualisation ne sont pas actives." `
            @("Le processeur est pret, mais Windows n'a pas allume les deux pieces qu'il faut.",
              "",
              "  1. Touche Windows, taper : fonctionnalites windows",
              "  2. Ouvrir << Activer ou desactiver des fonctionnalites Windows >>",
              "  3. Cocher : Plateforme de machine virtuelle",
              "  4. Cocher : Sous-systeme Windows pour Linux",
              "  5. OK, puis REDEMARRER l'ordinateur (indispensable).",
              "",
              "Au redemarrage, ouvrir Docker Desktop et attendre la baleine verte.") $null
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
Bon ("Docker tourne (moteur " + $info.Texte.Trim() + ")")

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
$up = Executer "docker" @("compose", "up", "-d", "--build") "compose-up"
if ($up.Code -ne 0) {
    Write-Host ""
    Write-Host "Le demarrage a echoue. Les dernieres lignes :" -ForegroundColor Red
    ($up.Texte -split "`n" | Select-Object -Last 25) | ForEach-Object { Write-Host ("   " + $_) }
    Abandonner "Docker n'a pas pu demarrer les services." `
        @("Verifiez que Docker Desktop est bien vert, puis relancez.",
          "Si cela recommence, le texte ci-dessus est ce qu'il faut montrer.") $null
}
Bon "Services demarres"

# --- 8. Le veilleur de mise a jour ---------------------------------------------
# Un conteneur ne peut pas se reconstruire lui-meme. Ce petit veilleur tourne
# sous votre compte : c'est lui qui donne au bouton de la page le pouvoir d'agir.
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
        Start-Process -FilePath "powershell" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script) `
            -WorkingDirectory $Racine -WindowStyle Minimized | Out-Null
        Bon "Veilleur de mise a jour lance (fenetre reduite, laissez-la)"
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
