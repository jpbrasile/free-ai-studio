# Brancher NotebookLM au Studio : une connexion Google, rien a copier ni a coller.
#
# 1. installe une fois l'outil de connexion (notebooklm-py, meme version que le
#    Studio) dans %LOCALAPPDATA%\FreeAIStudio\notebooklm ;
# 2. ouvre une fenetre Chrome (ou Edge) ou la personne se connecte a Google ;
# 3. envoie la session au Studio, qui la ferme dans son coffre ;
# 4. efface TOUT ce qui a servi : le fichier de session et le profil du
#    navigateur ouvert pour l'occasion (il restait connecte a Google, 25/09/2026).
#
# La session ouvre le compte Google entier : elle n'est jamais affichee. Un
# assistant de codage ne lance pas ce script a la place de la personne : c'est
# elle qui se connecte.
#
#   double-clic sur brancher-notebooklm.cmd
#   powershell -ExecutionPolicy Bypass -File scripts\brancher-notebooklm.ps1
#   ... -Verifier : tout prepare (Studio, version, outil, navigateur), s'arrete
#                   avant la fenetre Google. Rien n'est ouvert ni envoye.

param([string]$Navigateur = "", [switch]$Verifier)

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
$Studio = "http://127.0.0.1:8020"
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Arret($texte) {
    Write-Host ""
    Write-Host "ARRET : $texte"
    exit 1
}

# --- La cle du Sandbox, lue dans .env, jamais affichee -----------------------
$cheminEnv = Join-Path $Racine ".env"
if (-not (Test-Path $cheminEnv)) { Arret "pas de .env dans $Racine. Lancez d'abord demarrer.cmd." }
$cle = ""
foreach ($l in [System.IO.File]::ReadAllLines($cheminEnv, $utf8)) {
    if ($l -match "^SANDBOX_MANAGER_KEY=(.+)$") { $cle = $Matches[1].Trim() }
}
if (-not $cle) { Arret "SANDBOX_MANAGER_KEY est vide dans .env. Lancez d'abord demarrer.cmd." }
$entetes = @{ Authorization = "Bearer $cle" }

try {
    Invoke-RestMethod -Uri "$Studio/notebooklm/etat" -Headers $entetes -TimeoutSec 20 | Out-Null
} catch {
    Arret "le Studio ne repond pas sur $Studio. Lancez demarrer.cmd, attendez la fin, puis relancez ce fichier."
}

# --- La version exacte, lue la ou le Studio l'epingle (une seule verite) -----
$exigences = Join-Path $Racine "sandbox-manager\requirements.txt"
$version = ""
foreach ($l in [System.IO.File]::ReadAllLines($exigences, $utf8)) {
    if ($l -match "^notebooklm-py==(\S+)") { $version = $Matches[1] }
}
if (-not $version) { Arret "notebooklm-py n'est pas epingle dans sandbox-manager\requirements.txt." }

# --- Python, puis l'outil dans son propre dossier ----------------------------
$outil = Join-Path $env:LOCALAPPDATA "FreeAIStudio\notebooklm"
$py = Join-Path $outil "Scripts\python.exe"
$nlm = Join-Path $outil "Scripts\notebooklm.exe"
$aJour = $false
if (Test-Path $py) {
    $ligne = & $py -m pip show notebooklm-py 2>$null | Select-String "^Version:"
    $aJour = ($ligne -and ($ligne.ToString() -replace "Version:\s*", "") -eq $version)
}
if (-not $aJour) {
    Write-Host "Installation de l'outil de connexion (une seule fois, 1 a 3 minutes)..."
    if (-not (Test-Path $py)) {
        $base = $null
        foreach ($essai in @(@("py", "-3"), @("python"))) {
            try {
                $sortie = & $essai[0] $essai[1..9] -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
                if ($sortie -eq "True") { $base = $essai; break }
            } catch { }
        }
        if (-not $base) {
            Arret ("Python 3.10 ou plus est introuvable. Installez-le depuis https://www.python.org/downloads/ " +
                   "(cochez << Add python.exe to PATH >>), ou suivez l'autre chemin de la page NotebookLM du Studio.")
        }
        & $base[0] $base[1..9] -m venv $outil
        if ($LASTEXITCODE) { Arret "creation de $outil impossible." }
    }
    & $py -m pip install --quiet --disable-pip-version-check "notebooklm-py[browser]==$version"
    if ($LASTEXITCODE) { Arret "l'installation de notebooklm-py $version a echoue (sortie ci-dessus)." }
}

# --- Le navigateur : Chrome s'il est la, sinon Edge (present sur tout Windows) -
if (-not $Navigateur) {
    $chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
                "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
                "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ }
    $Navigateur = if ($chrome) { "chrome" } else { "msedge" }
}
if ($Verifier) {
    $v = & $nlm --version 2>$null
    Write-Host "PRET : Studio joignable, outil $v dans $outil, navigateur $Navigateur."
    Write-Host "(-Verifier : aucune fenetre ouverte, rien envoye.)"
    exit 0
}

# --- Connexion, envoi, effacement ---------------------------------------------
$travail = Join-Path $env:TEMP ("fas-nlm-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $travail | Out-Null
$session = Join-Path $travail "session.json"
$code = 1
try {
    Write-Host ""
    Write-Host "Une fenetre $Navigateur va s'ouvrir. Connectez-vous a Google et attendez"
    Write-Host "que NotebookLM s'affiche : la fenetre se ferme seule. Vous avez 10 minutes."
    Write-Host ""
    & $nlm login --browser $Navigateur --storage $session --browser-timeout 600 | Out-Null
    if (-not (Test-Path $session)) { Arret "la connexion n'a pas abouti (fenetre fermee trop tot ?). Relancez ce fichier." }

    $corps = @{ export = [System.IO.File]::ReadAllText($session, $utf8) } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$Studio/notebooklm/session" -Method Post -Headers $entetes `
            -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($corps)) -TimeoutSec 180
    } catch {
        $detail = ""
        try { $detail = (ConvertFrom-Json $_.ErrorDetails.Message).detail } catch { }
        Arret "le Studio a refuse la session. $detail"
    }
    if ($r.ok) {
        Write-Host "OK : NotebookLM est branche ($($r.carnets) carnet(s) dans ce compte)."
        Write-Host "Rechargez la page NotebookLM du Studio."
        $code = 0
    } else {
        Write-Host "Session enregistree, mais NotebookLM ne repond pas : $($r.message)"
    }
} finally {
    # Le fichier de session ET le profil du navigateur (session.json.browser_profile).
    Remove-Item -Recurse -Force -LiteralPath $travail -ErrorAction SilentlyContinue
    if (Test-Path $travail) {
        Write-Host "ATTENTION : $travail n'a pas pu etre efface. Supprimez ce dossier : il ouvre votre compte Google."
    } else {
        Write-Host "Le fichier de session et le profil du navigateur ont ete effaces."
    }
}
exit $code
