# Sonde de la carte, cote hote. SP-CARTE-LIBRE-SONDE-AVEUGLE, 23/09/2026.
#
# Le probleme, mesure le 22/09 : le Studio disait la carte « libre » d'apres
# `nvidia-smi --query-gpu=memory.free`, qui ne voit pas un processus ayant pris
# la carte sans encore y ecrire -- un `julia` qui compile, ou sur un cas
# processeur seul. `--query-compute-apps` rend une liste vide dans ce cas-la
# aussi. Le conteneur, lui, ne voit pas les processus de Windows.
#
# Cette sonde tourne sous VOTRE compte et ecrit toutes les ~10 s, dans
# config\etat-carte-hote.json, les processus qui tiennent la carte. Le Studio
# le lit avant chaque lancement sur la carte. Fichier absent, illisible ou vieux
# de plus de 30 s : la carte est comptee PRISE et le travail part ailleurs.
# Arreter cette sonde ne peut donc jamais faire prendre la carte de quelqu'un ;
# cela fait seulement louer une machine a la place.
#
# Elle ne lit rien d'autre que le nom et le numero des processus surveilles, et
# n'en arrete aucun.
#
# Lancee sans fenetre par start.ps1, puis a chaque ouverture de session par un
# raccourci qu'elle pose elle-meme dans le dossier Demarrage (meme mecanisme que
# maj-veilleuse.ps1 : ni droits d'administrateur, ni registre). Pour qu'elle ne
# reparte plus avec Windows : supprimer le raccourci
# « Free AI Studio - sonde de la carte » du dossier Demarrage (Windows+R,
# shell:startup).
#
#   powershell -ExecutionPolicy Bypass -File scripts\sonde-carte.ps1
#   ... -UneFois       un seul releve, puis s'arrete (essais)

param(
    [int]$Intervalle = 10,
    [switch]$UneFois,
    # Les processus qui tiennent la carte meme a 0 Mo. `julia.exe` est celui
    # de la regle de cette machine : present => on attend, jamais on n'arrete.
    [string[]]$Noms = @('julia.exe'),
    # Dossier Demarrage de Windows. Ne se change que pour les essais.
    [string]$DossierDemarrage = [Environment]::GetFolderPath('Startup')
)

$ErrorActionPreference = 'Stop'
$Racine = Split-Path -Parent $PSScriptRoot
$Config = Join-Path $Racine 'config'
$Cible = Join-Path $Config 'etat-carte-hote.json'
$Provisoire = $Cible + '.tmp'
if (-not (Test-Path $Config)) { New-Item -ItemType Directory -Path $Config | Out-Null }

function Ecrire-Releve {
    $locataires = @()
    foreach ($n in $Noms) {
        foreach ($p in @(Get-CimInstance Win32_Process -Filter ("Name='" + $n + "'"))) {
            $locataires += [ordered]@{ nom = [string]$p.Name; pid = [int]$p.ProcessId }
        }
    }
    $etat = [ordered]@{
        ecrit_le_epoch = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
        surveilles = @($Noms)
        locataires = @($locataires)
    }
    $json = ConvertTo-Json -InputObject $etat -Depth 4 -Compress
    # Ecrit a cote puis deplace : le Studio ne lit jamais un fichier a moitie
    # ecrit. Dans l'instant ou il manque, le Studio le compte absent, donc la
    # carte prise -- le cote prudent.
    [System.IO.File]::WriteAllText($Provisoire, $json, (New-Object System.Text.UTF8Encoding $false))
    Move-Item -LiteralPath $Provisoire -Destination $Cible -Force
}

if ($UneFois) {
    Ecrire-Releve
    Get-Content -LiteralPath $Cible
    exit 0
}

# --- Une seule sonde par dossier ---------------------------------------------
$sha = [System.Security.Cryptography.SHA1]::Create()
try {
    $octets = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Racine.ToLowerInvariant()))
} finally { $sha.Dispose() }
$cle = -join ($octets[0..7] | ForEach-Object { $_.ToString('x2') })
$Verrou = New-Object System.Threading.Mutex($false, ('Local\FreeAIStudio-sonde-carte-' + $cle))
$aLaMain = $false
try { $aLaMain = $Verrou.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $aLaMain = $true }
if (-not $aLaMain) {
    Write-Host "Une sonde de la carte tourne deja pour ce dossier : rien a faire."
    exit 0
}

# --- Repartir avec Windows ---------------------------------------------------
function Poser-Raccourci {
    if (-not $DossierDemarrage) { return }
    $lien  = Join-Path $DossierDemarrage 'Free AI Studio - sonde de la carte.lnk'
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
    $r.Description = 'Free AI Studio : dit au Studio qui d autre se sert de la carte graphique.'
    $r.Save()
}
try { Poser-Raccourci } catch { Write-Warning "Raccourci de demarrage non pose : $($_.Exception.Message)" }

# --- La boucle ---------------------------------------------------------------
# Une erreur passagere ne l'arrete pas ; si elle s'arretait quand meme, le
# releve vieillirait et le Studio compterait la carte prise.
while ($true) {
    try { Ecrire-Releve } catch { Write-Warning "Releve non ecrit : $($_.Exception.Message)" }
    Start-Sleep -Seconds $Intervalle
}
