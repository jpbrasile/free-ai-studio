# Un autre dossier du Studio tourne-t-il deja sur cet ordinateur ?
#
# Ecrit sur sa sortie le chemin de cet autre dossier, ou rien. Ne change rien :
# il lit seulement les etiquettes des conteneurs.
#
# Pourquoi (essai a blanc du 23/09/2026) : quelqu'un installe depuis le ZIP
# (dossier free-ai-studio-main), puis reprend le dossier avec VS Code comme
# demarrer.ps1 le lui conseille (dossier free-ai-studio). Deux noms de dossier,
# donc deux projets Docker, mais les MEMES noms de conteneurs : le second
# demarrage echouait sur << Conflict. The container name ... is already in use >>,
# un message que demarrer.ps1 ne reconnaissait pas. Docker range dans chaque
# conteneur le dossier qui l'a lance (com.docker.compose.project.working_dir) :
# on peut donc nommer l'autre dossier AVANT de construire quoi que ce soit.
#
# Lance a part, et non dans demarrer.ps1, pour pouvoir le jouer seul contre un
# Studio en marche sans rien redemarrer.

param([Parameter(Mandatory = $true)][string]$Racine)

$ErrorActionPreference = "Stop"

# Meme precaution que Executer dans demarrer.ps1 : jamais de redirection de la
# sortie d'erreur d'une commande native sous PowerShell 5.1.
function Lire($arguments) {
    $sortie = [System.IO.Path]::GetTempFileName()
    $erreur = [System.IO.Path]::GetTempFileName()
    try {
        Start-Process -FilePath "docker" -ArgumentList $arguments -NoNewWindow -Wait `
            -RedirectStandardOutput $sortie -RedirectStandardError $erreur | Out-Null
        return @(Get-Content $sortie -Encoding UTF8 -ErrorAction SilentlyContinue)
    } finally {
        Remove-Item $sortie, $erreur -ErrorAction SilentlyContinue
    }
}

$noms = @(Lire @("ps", "-a", "--filter", "name=^free-ai-studio-", "--format", "{{.Names}}") |
    Where-Object { $_.Trim() })
if ($noms.Count -eq 0) { exit 0 }

# Guillemets obligatoires : Start-Process colle les arguments avec des espaces,
# et le gabarit en contient une.
$lignes = Lire (@("inspect", "--format", '"{{json .Config.Labels}}"') + $noms)

$ici = $Racine.TrimEnd('\', '/')
$autres = @()
foreach ($ligne in $lignes) {
    if (-not $ligne.Trim()) { continue }
    try { $etiquettes = $ligne | ConvertFrom-Json } catch { continue }
    $dossier = [string]$etiquettes.'com.docker.compose.project.working_dir'
    if (-not $dossier) { continue }
    $dossier = $dossier.TrimEnd('\', '/')
    if ($dossier -ine $ici -and $autres -notcontains $dossier) { $autres += $dossier }
}
if ($autres.Count -gt 0) { Write-Output $autres[0] }
