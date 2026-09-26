# Veilleur de mise a jour.
#
# Le probleme, en une image : le bouton << Mettre a jour >> est dans une page web
# servie par un conteneur, et un conteneur ne peut pas se reconstruire lui-meme
# -- il se couperait la branche sous les pieds. Lui donner la main sur Docker
# reviendrait a confier a une page web les pleins pouvoirs sur la machine.
#
# Ce veilleur est la reponse simple : il tourne sous VOTRE compte, il regarde une
# fois par seconde si la page a depose une demande, et c'est lui qui fait le
# travail. La page ne commande rien ; elle laisse un mot sur la table.
#
# Lance sans fenetre par demarrer.cmd (et start.ps1), puis a chaque ouverture de
# session Windows, par un raccourci qu'il pose lui-meme dans le dossier Demarrage.
# Le bouton doit agir sans que le debutant pense a rien : decision de
# l'utilisateur du 14/09/2026. La veille, sur l'autre ordinateur, Docker avait
# relance le Studio tout seul apres un redemarrage, sans veilleur, et le bouton
# ne faisait que renvoyer vers un double-clic.
#
# Un seul veilleur par dossier du Studio : un second lancement s'arrete aussitot.
#
# Pour qu'il ne reparte plus avec Windows : supprimer le raccourci
# << Free AI Studio - mises a jour >> du dossier Demarrage (touches Windows+R,
# taper shell:startup).

param(
    # Dossier Demarrage de Windows. Ne se change que pour les essais.
    [string]$DossierDemarrage = [Environment]::GetFolderPath('Startup')
)

$ErrorActionPreference = 'Stop'
$Racine  = Split-Path -Parent $PSScriptRoot
$Config  = Join-Path $Racine 'config'
$Demande = Join-Path $Config 'maj-demandee.json'
$Script  = Join-Path $PSScriptRoot 'mettre-a-jour.ps1'
$Vivant  = Join-Path $Config 'maj-veilleuse.json'
# Deuxieme service, demande de l'utilisateur du 25/09/2026 : le bouton
# << Me reconnecter a Google >> de la page NotebookLM laisse ce mot, et le
# veilleur ouvre brancher-notebooklm.cmd dans une fenetre visible. Rien d'autre :
# le mot ne porte aucune commande, seulement l'envie d'ouvrir ce fichier-la.
$DemandeBrancher = Join-Path $Config 'brancher-demandee.json'
$Brancher        = Join-Path $Racine 'brancher-notebooklm.cmd'
# Journal du veilleur. Il tourne sans fenetre : sans ce fichier, un Write-Host
# ou un Write-Warning ne se lit nulle part. Vu en reel le 26/09/2026 : une
# demande consommee sans fenetre ouverte, et rien pour dire pourquoi.
$Journal = Join-Path $Config 'maj-veilleuse.log'

if (-not (Test-Path $Config)) { New-Item -ItemType Directory -Path $Config | Out-Null }

# Une ligne horodatee par evenement, pas une par tour de boucle. Borne : au-dela
# de 200 Ko, le journal devient maj-veilleuse.log.1 (l'ancien .1 est ecrase).
# Une erreur ici (disque plein, fichier tenu) ne doit jamais arreter le
# veilleur : try/catch vide, comme le signe de vie.
function Ecrire-Journal([string]$texte) {
    try {
        if ((Test-Path -LiteralPath $Journal) -and (Get-Item -LiteralPath $Journal).Length -gt 200KB) {
            Move-Item -LiteralPath $Journal -Destination ($Journal + '.1') -Force
        }
        $ligne = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $texte + [Environment]::NewLine
        [System.IO.File]::AppendAllText($Journal, $ligne, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

# --- Un seul veilleur par dossier ----------------------------------------------
# Ouverture de session, demarrer.cmd, start.ps1 : trois portes peuvent le lancer,
# et deux veilleurs reconstruiraient deux fois pour une seule demande. Le nom du
# verrou vient du chemin du dossier ; une barre oblique inverse y est interdite,
# d'ou l'empreinte.
$sha = [System.Security.Cryptography.SHA1]::Create()
try {
    $octets = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Racine.ToLowerInvariant()))
} finally { $sha.Dispose() }
$cle = -join ($octets[0..7] | ForEach-Object { $_.ToString('x2') })
$Verrou = New-Object System.Threading.Mutex($false, ('Local\FreeAIStudio-veilleur-' + $cle))
$aLaMain = $false
try { $aLaMain = $Verrou.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $aLaMain = $true }
# Un veilleur d'avant le 25/09/2026 ne sait pas ouvrir brancher-notebooklm.cmd
# et ne se relance pas quand son fichier change : il resterait en place jusqu'au
# prochain redemarrage de Windows. Le neuf le remplace -- seulement si son signe
# de vie ne dit pas "brancher", et seulement le processus qui y est nomme, s'il
# execute bien ce fichier-ci.
if (-not $aLaMain) {
    try {
        $etat = Get-Content -LiteralPath $Vivant -Raw | ConvertFrom-Json
        if ($etat.brancher -ne $true -and $etat.pid) {
            $ancien = Get-CimInstance Win32_Process -Filter ("ProcessId = " + [int]$etat.pid)
            # IndexOf plutot que -like : un [ dans le chemin serait un joker.
            if ($ancien -and $ancien.CommandLine -and
                $ancien.CommandLine.ToLowerInvariant().IndexOf($PSCommandPath.ToLowerInvariant()) -ge 0) {
                Write-Host "Un veilleur plus ancien tourne : il est remplace."
                Ecrire-Journal ("Veilleur plus ancien (PID " + [int]$etat.pid + ") remplace par PID " + $PID)
                Stop-Process -Id ([int]$etat.pid) -Force
                try { $aLaMain = $Verrou.WaitOne(10000) } catch [System.Threading.AbandonedMutexException] { $aLaMain = $true }
            }
        }
    } catch { }
}
if (-not $aLaMain) {
    Write-Host "Un veilleur tourne deja pour ce dossier : rien a faire."
    Ecrire-Journal ("Second lancement (PID " + $PID + ") : un veilleur tourne deja, arret.")
    exit 0
}

# --- Repartir avec Windows -----------------------------------------------------
# Un raccourci dans le dossier Demarrage de l'utilisateur : ni droits
# d'administrateur, ni registre, et il se retire comme un fichier. Le chemin du
# script est entre guillemets : sans eux, un chemin avec une espace
# (C:\Users\Jean Dupont\...) se coupe en deux et le veilleur ne demarre pas.
function Poser-Raccourci {
    if (-not $DossierDemarrage) { return }
    $lien  = Join-Path $DossierDemarrage 'Free AI Studio - mises a jour.lnk'
    $cible = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '"'
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $lien) {
        $deja = $shell.CreateShortcut($lien)
        if ($deja.TargetPath -eq $cible -and $deja.Arguments -eq $arguments) { return }
    }
    $r = $shell.CreateShortcut($lien)
    $r.TargetPath = $cible
    $r.Arguments = $arguments
    $r.WorkingDirectory = $Racine
    $r.WindowStyle = 7
    $r.Description = 'Free AI Studio : rend le bouton Mettre a jour de la page Studio capable d agir.'
    $r.Save()
}
try { Poser-Raccourci } catch { Write-Warning "Raccourci de demarrage non pose : $($_.Exception.Message)" }

# Empreinte du veilleur lui-meme : si une mise a jour le change, il se relance
# avec la nouvelle version au lieu de garder l'ancienne en memoire.
$Empreinte = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
$Tours = 0
$DernierBrancher = [datetime]::MinValue

function Se-Relancer {
    Write-Host "Le veilleur lui-meme a change : il se relance avec la nouvelle version."
    Ecrire-Journal ("Empreinte du veilleur changee : relance (PID " + $PID + " s'arrete).")
    $Verrou.ReleaseMutex()
    $Verrou.Dispose()
    Start-Process -FilePath 'powershell' -WindowStyle Hidden -WorkingDirectory $Racine `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                        '-File', ('"' + $PSCommandPath + '"'),
                        '-DossierDemarrage', ('"' + $DossierDemarrage + '"')) | Out-Null
    exit 0
}

Write-Host "Veilleur de mise a jour actif. Le bouton << Mettre a jour >> de la page Studio fonctionne."
Ecrire-Journal ("Veilleur demarre (PID " + $PID + ", " + $PSCommandPath + ")")

while ($true) {
    # Signe de vie : la page s'en sert pour savoir si le bouton peut agir ou
    # s'il doit renvoyer vers le double-clic. Une erreur passagere (fichier tenu
    # un instant par un autre programme) ne doit pas arreter le veilleur : hors
    # de ce try, elle le tuait sans un mot.
    try {
        [ordered]@{ vivant = $true; horodate = (Get-Date).ToString('s'); pid = $PID; brancher = $true } |
            ConvertTo-Json | Out-File -FilePath $Vivant -Encoding utf8
    } catch { }

    if (Test-Path $DemandeBrancher) {
        Remove-Item $DemandeBrancher -Force -ErrorAction SilentlyContinue
        Ecrire-Journal "Demande de branchement recue (brancher-demandee.json)"
        $ecart = ((Get-Date) - $DernierBrancher).TotalSeconds
        # Deux clics rapides ne font qu'une fenetre : la derniere a 60 s pres.
        if ((Test-Path $Brancher) -and ($ecart -gt 60)) {
            $DernierBrancher = Get-Date
            Write-Host "Demande recue : ouverture de brancher-notebooklm.cmd"
            try {
                $fenetre = Start-Process -FilePath $Brancher -WorkingDirectory $Racine -PassThru
                if ($fenetre) {
                    Ecrire-Journal ("Fenetre brancher-notebooklm.cmd ouverte (PID " + $fenetre.Id + ")")
                } else {
                    Ecrire-Journal "Start-Process n'a rendu aucun processus pour brancher-notebooklm.cmd"
                }
            } catch {
                Write-Warning "brancher-notebooklm.cmd n'a pas pu s'ouvrir : $($_.Exception.Message)"
                Ecrire-Journal ("ECHEC Start-Process brancher-notebooklm.cmd : " + $_.Exception.Message)
            }
        } elseif (-not (Test-Path $Brancher)) {
            Ecrire-Journal ("Demande ignoree : fichier absent " + $Brancher)
        } else {
            Ecrire-Journal ("Demande ignoree : garde des 60 s (derniere ouverture il y a " + [int]$ecart + " s)")
        }
    }

    # Le veilleur lui-meme a change (git pull, copie d'une version neuve) : il se
    # relance, sinon le nouveau service n'existerait qu'au prochain redemarrage
    # de Windows. Regarde toutes les 30 s environ, pas a chaque tour.
    $Tours++
    if ($Tours % 15 -eq 0) {
        $nouvelle = $null
        try { $nouvelle = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash } catch { }
        if ($nouvelle -and $nouvelle -ne $Empreinte) { Se-Relancer }
    }

    if (Test-Path $Demande) {
        Remove-Item $Demande -Force -ErrorAction SilentlyContinue
        Write-Host "`nDemande recue : mise a jour en cours..."
        Ecrire-Journal "Demande de mise a jour recue (maj-demandee.json) : mettre-a-jour.ps1 lance"
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $Script
            Ecrire-Journal ("Mise a jour terminee (code de sortie " + $LASTEXITCODE + ")")
        } catch {
            Write-Warning "Mise a jour interrompue : $($_.Exception.Message)"
            Ecrire-Journal ("Mise a jour interrompue : " + $_.Exception.Message)
        }
        $nouvelle = $null
        try { $nouvelle = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash } catch { }
        if ($nouvelle -and $nouvelle -ne $Empreinte) { Se-Relancer }
        Write-Host "Retour en veille.`n"
    }

    Start-Sleep -Seconds 2
}
