# Saisir une cle dans .env sans qu'elle s'affiche.
#
# Pour les cles que les pages Cles du Studio ne prennent pas (OPENROUTER_MANAGEMENT_KEY,
# HF_TOKEN, Cloudflare...) ou pour qui prefere le .env. La cle tapee ou collee ne
# s'affiche pas, n'est jamais ecrite a l'ecran ni dans un journal : seulement dans
# .env. Un assistant de codage qui aide a l'installation dit a la personne de lancer
# ce script elle-meme ; il ne voit donc jamais la cle.
#
#   double-clic sur saisir-une-cle.cmd
#   powershell -ExecutionPolicy Bypass -File scripts\saisir-cle.ps1 [-Nom HF_TOKEN]

param([string]$Nom = "")

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
$cheminEnv = Join-Path $Racine ".env"
$cheminModele = Join-Path $Racine ".env.example"
# UTF-8 sans BOM, comme install.ps1 : garde les accents des commentaires du .env.
$utf8 = New-Object System.Text.UTF8Encoding($false)

$Connues = @(
    @("GEMINI_API_KEY",            "Gemini (Google AI Studio), la cle gratuite principale"),
    @("GROQ_API_KEY",              "Groq"),
    @("OPENROUTER_API_KEY",        "OpenRouter, cle d'inference"),
    @("OPENROUTER_MANAGEMENT_KEY", "OpenRouter, Management Key (Boost protege, docs/BOOST.md)"),
    @("HF_TOKEN",                  "Hugging Face"),
    @("CLOUDFLARE_ACCOUNT_ID",     "Cloudflare Workers AI, identifiant de compte"),
    @("CLOUDFLARE_API_TOKEN",      "Cloudflare Workers AI, jeton"),
    @("MODAL_TOKEN_ID",            "Modal, identifiant du jeton"),
    @("MODAL_TOKEN_SECRET",        "Modal, secret du jeton"),
    @("KAGGLE_USERNAME",           "Kaggle, nom d'utilisateur"),
    @("KAGGLE_API_TOKEN",          "Kaggle, jeton")
)

if (-not (Test-Path $cheminEnv)) {
    if (-not (Test-Path $cheminModele)) {
        Write-Host "ARRET : ni .env ni .env.example dans $Racine."
        exit 1
    }
    Copy-Item $cheminModele $cheminEnv
    Write-Host ".env cree a partir de .env.example"
}
$modele = [System.IO.File]::ReadAllText($cheminModele, $utf8)

function Deja-Renseignee($contenu, $nom) {
    return $contenu -match "(?m)^$nom=\S"
}

function Choisir-Nom {
    $contenu = [System.IO.File]::ReadAllText($cheminEnv, $utf8)
    Write-Host ""
    Write-Host "Quelle cle ?"
    for ($i = 0; $i -lt $Connues.Count; $i++) {
        $etat = if (Deja-Renseignee $contenu $Connues[$i][0]) { "  [deja renseignee]" } else { "" }
        Write-Host ("  {0,2}. {1} -- {2}{3}" -f ($i + 1), $Connues[$i][0], $Connues[$i][1], $etat)
    }
    Write-Host "  ou tapez le nom exact d'une autre variable de .env.example"
    $reponse = (Read-Host "Numero ou nom (Entree seule : quitter)").Trim()
    if ($reponse -eq "") { return "" }
    $n = 0
    if ([int]::TryParse($reponse, [ref]$n)) {
        if ($n -ge 1 -and $n -le $Connues.Count) { return $Connues[$n - 1][0] }
        Write-Host "Pas de numero $n."
        return $null
    }
    return $reponse.ToUpper()
}

function Enregistrer($nom, $valeur) {
    # Guillemets simples : docker compose lit alors la valeur telle quelle, sans
    # interpreter un $ ou un # qu'elle contiendrait.
    if ($valeur -match "[\s#`$`"\\]") { $valeur = "'" + $valeur + "'" }
    $contenu = [System.IO.File]::ReadAllText($cheminEnv, $utf8)
    $motif = "(?m)^" + [regex]::Escape($nom) + "=.*$"
    if ($contenu -match $motif) {
        # MatchEvaluator : un $ dans la cle ne doit pas etre lu comme $1 par Replace.
        $contenu = [regex]::Replace($contenu, $motif, { param($m) "$nom=$valeur" })
    } else {
        if (-not $contenu.EndsWith("`n")) { $contenu += "`n" }
        $contenu += "$nom=$valeur`n"
    }
    [System.IO.File]::WriteAllText($cheminEnv, $contenu, $utf8)
}

$enregistrees = 0
while ($true) {
    $nom = if ($Nom -ne "") { $Nom.ToUpper() } else { Choisir-Nom }
    if ($nom -eq "") { break }
    if ($null -eq $nom) { continue }
    if ($nom -notmatch "^[A-Z][A-Z0-9_]*$" -or $modele -notmatch "(?m)^$nom=") {
        # Sans repeter ce qui a ete tape : une cle collee ici par erreur s'afficherait.
        Write-Host "Ce n'est ni un numero de la liste ni une variable de .env.example : rien n'est ecrit."
        if ($Nom -ne "") { exit 1 }
        continue
    }

    Write-Host ""
    Write-Host "Collez la valeur de $nom (clic droit colle dans cette fenetre), puis Entree."
    Write-Host "Rien ne s'affiche pendant la saisie, c'est normal."
    $secret = Read-Host "$nom" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { $valeur = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

    if ($valeur -eq "") {
        Write-Host "Rien de saisi : $nom n'est pas modifiee."
    } elseif ($valeur.Contains("'")) {
        Write-Host "Cette valeur contient une apostrophe, aucune cle n'en a : $nom n'est pas modifiee."
    } else {
        Enregistrer $nom $valeur
        $enregistrees++
        Write-Host ("OK : $nom enregistree dans .env ({0} caracteres)." -f $valeur.Length)
    }
    $valeur = $null

    if ($Nom -ne "") { break }
    if ((Read-Host "Une autre cle ? (o/N)").Trim().ToLower() -ne "o") { break }
}

if ($enregistrees -eq 0) { exit 0 }

Write-Host ""
Write-Host "Les services lisent .env a leur demarrage."
if ((Read-Host "Les relancer maintenant pour prendre la ou les cles ? (O/n)").Trim().ToLower() -eq "n") {
    Write-Host "Plus tard : double-clic sur demarrer.cmd."
    exit 0
}
Push-Location $Racine
try {
    # up -d ne recree que les conteneurs dont la configuration a change.
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { Write-Host "ARRET : docker compose up -d a echoue (code $LASTEXITCODE). Docker Desktop est-il ouvert ?"; exit 1 }
    Write-Host "Services relances."
} finally { Pop-Location }
