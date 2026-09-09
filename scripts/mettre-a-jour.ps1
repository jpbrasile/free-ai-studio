# Met Free AI Studio a jour : recupere la derniere version du depot, puis
# reconstruit les conteneurs.
#
# Pourquoi reconstruire et pas seulement redemarrer : le code est CUIT dans
# l'image Docker. Un « restart » relance l'ancien code, sans rien dire. C'est le
# piege qui a coute deux heures le 09/09.
#
# Ce script est appele de trois facons, et fait la meme chose dans les trois :
#   - double-clic sur mettre-a-jour.cmd, a la racine du dossier ;
#   - bouton « Mettre a jour » de la page Studio, via le veilleur ;
#   - a la main, pour ceux que le terminal ne gene pas.
#
# ATTENTION, piege mesure le 09/09 : ne JAMAIS ecrire « docker compose ... 2>&1 »
# ici. PowerShell 5.1 transforme chaque ligne que Docker ecrit sur sa sortie
# d'erreur -- y compris « Image ... Building », qui n'est pas une erreur -- en
# erreur bloquante, et la mise a jour s'arrete au bout de dix secondes en
# annoncant un echec alors que tout allait bien. D'ou Start-Process, qui rend un
# vrai code de sortie et met les sorties dans des fichiers.

param(
    [switch]$Silencieux
)

$ErrorActionPreference = 'Stop'
$Racine = Split-Path -Parent $PSScriptRoot
$Config = Join-Path $Racine 'config'
$Etat   = Join-Path $Config 'maj-etat.json'

if (-not (Test-Path $Config)) { New-Item -ItemType Directory -Path $Config | Out-Null }

function Ecrire-Etat {
    param([string]$Phase, [string]$Message, [string]$Detail = '', [bool]$Fini = $false, [bool]$Ok = $false)
    $donnees = [ordered]@{
        phase    = $Phase
        message  = $Message
        detail   = $Detail
        fini     = $Fini
        ok       = $Ok
        horodate = (Get-Date).ToString('s')
    }
    $donnees | ConvertTo-Json -Depth 4 | Out-File -FilePath $Etat -Encoding utf8
    if (-not $Silencieux) { Write-Host "[$Phase] $Message" }
}

function Lancer {
    <#
      Lance un programme et rend son code de sortie ET ce qu'il a ecrit, sans
      passer par la redirection qui fait trebucher PowerShell 5.1.
    #>
    param([string]$Programme, [string[]]$Arguments)

    $sortieFichier = [System.IO.Path]::GetTempFileName()
    $erreurFichier = [System.IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath $Programme -ArgumentList $Arguments `
            -WorkingDirectory $Racine -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $sortieFichier -RedirectStandardError $erreurFichier
        $texte = @()
        foreach ($f in @($sortieFichier, $erreurFichier)) {
            if (Test-Path $f) {
                $contenu = Get-Content $f -ErrorAction SilentlyContinue
                if ($contenu) { $texte += $contenu }
            }
        }
        return [pscustomobject]@{ Code = $p.ExitCode; Texte = ($texte -join "`n") }
    } finally {
        Remove-Item $sortieFichier, $erreurFichier -Force -ErrorAction SilentlyContinue
    }
}

try {
    Ecrire-Etat -Phase 'demarrage' -Message 'Mise a jour demandee.'

    # --- 1. Recuperer la derniere version -------------------------------------
    Ecrire-Etat -Phase 'depot' -Message 'Recuperation de la derniere version...'
    $avant = (Lancer 'git' @('rev-parse', 'HEAD')).Texte.Trim()
    $pull  = Lancer 'git' @('pull', '--ff-only')
    $apres = (Lancer 'git' @('rev-parse', 'HEAD')).Texte.Trim()

    if ($pull.Code -ne 0) {
        Ecrire-Etat -Phase 'depot' -Message 'Le depot n a pas pu etre mis a jour.' `
            -Detail $pull.Texte -Fini $true -Ok $false
        exit 1
    }

    if ($avant -eq $apres) {
        $motCode = 'Aucun changement de code : vous aviez deja la derniere version.'
    } else {
        $motCode = "Code mis a jour : $($avant.Substring(0,7)) -> $($apres.Substring(0,7))."
    }
    Ecrire-Etat -Phase 'depot' -Message $motCode -Detail $pull.Texte

    # --- 2. Reconstruire ------------------------------------------------------
    Ecrire-Etat -Phase 'construction' -Message 'Reconstruction des services (quelques minutes)...'
    $build = Lancer 'docker' @('compose', 'up', '-d', '--build')

    if ($build.Code -ne 0) {
        Ecrire-Etat -Phase 'construction' -Message 'La reconstruction a echoue.' `
            -Detail $build.Texte -Fini $true -Ok $false
        exit 1
    }

    Ecrire-Etat -Phase 'fini' -Message "$motCode Les services sont repartis." `
        -Detail $build.Texte -Fini $true -Ok $true
    exit 0
}
catch {
    Ecrire-Etat -Phase 'erreur' -Message 'Interrompu par une erreur.' `
        -Detail $_.Exception.Message -Fini $true -Ok $false
    exit 1
}
