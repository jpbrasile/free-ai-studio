# Rend les 34 Go du modele video, quand on ne veut plus fabriquer de clips ici.
#
# POURQUOI CE N'EST PAS AUTOMATIQUE, et ne le sera pas :
#   1. le dossier vise n'appartient pas au Studio. C'est le cache Hugging Face
#      du PROFIL -- celui que lisent aussi ComfyUI, un carnet Jupyter, ou tout
#      autre outil d'IA de la personne. Y passer un balai tout seul, c'est
#      effacer le travail de quelqu'un d'autre sur sa propre machine ;
#   2. revenir en arriere coute 22 minutes de ligne, mesurees le 20/09 sur une
#      fibre (34,20 Go, 24,9 Mio/s). Un geste de trois secondes qui en coute
#      vingt-deux se DEMANDE ;
#   3. aucun disque n'est en danger : 34 Go sur un disque de 1 862 Go. Rien ne
#      justifie de decider a la place du proprietaire de la machine.
#
# Ce script ne supprime donc QUE sur un << oui >> tape a la main, et il ne
# supprime QUE le dossier du modele video -- jamais le cache entier, qui
# contient les modeles des autres outils.
#
#   powershell -ExecutionPolicy Bypass -File scripts\supprimer-modele-video.ps1
#   ... -Oui     pour un script qui appelle celui-ci (sans question posee)
param([switch]$Oui)
$ErrorActionPreference = "Stop"

# EXACTEMENT le dossier que monte docker-compose.gpu.yml, et la meme regle que
# scripts\telecharger-modele-video.ps1 : GPU_MODELES_DIR s'il est pose, sinon le
# cache du profil. Si les deux divergent un jour, ce script effacerait un
# dossier que personne ne lit pendant que le Studio garde les 34 Go ailleurs.
$cacheHF = Join-Path $env:USERPROFILE ".cache\huggingface"
if ($env:GPU_MODELES_DIR) { $cible = $env:GPU_MODELES_DIR } else { $cible = $cacheHF }
$modele = Join-Path $cible "hub\models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"

Write-Host ""
Write-Host "  Modele video de la maison -- suppression" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $modele)) {
    Write-Host "  Rien a supprimer : $modele n'existe pas." -ForegroundColor Yellow
    Write-Host "  Les clips partent deja sur une machine louee."
    exit 0
}

$mesure = Get-ChildItem -LiteralPath $modele -Recurse -File -Force | Measure-Object -Property Length -Sum
# En Go pour les 34 Go du vrai modele, en Mo en dessous : un essai sur un faux
# cache affichait << 0 Go rendus >>, ce qui donne a un message de suppression
# l'air de n'avoir rien fait.
if ($mesure.Sum -ge 1GB) { $taille = "{0} Go" -f [math]::Round($mesure.Sum / 1GB, 2) }
else { $taille = "{0} Mo" -f [math]::Round($mesure.Sum / 1MB, 1) }
Write-Host ""
Write-Host "  A supprimer : $modele"
Write-Host "  $($mesure.Count) fichiers, $taille"
Write-Host ""
Write-Host "  Ce qui change apres : les clips repartiront sur une machine louee," -ForegroundColor Yellow
Write-Host "  payante, au lieu de la carte de cet ordinateur." -ForegroundColor Yellow
Write-Host "  Pour revenir en arriere : scripts\telecharger-modele-video.ps1," -ForegroundColor Yellow
Write-Host "  environ 22 minutes de ligne (mesure du 20/09)." -ForegroundColor Yellow
Write-Host ""

if (-not $Oui) {
    # Read-Host et non une touche : on veut le mot ecrit, pas un clic reflexe.
    $reponse = Read-Host "  Tapez oui pour supprimer, n'importe quoi d'autre pour annuler"
    if ($reponse.Trim().ToLower() -notin @("oui", "o", "yes", "y")) {
        Write-Host "  Annule. Rien n'a ete touche." -ForegroundColor Green
        exit 0
    }
}

Remove-Item -LiteralPath $modele -Recurse -Force -Confirm:$false
$libre = [math]::Round((Get-PSDrive -Name ($env:SystemDrive.TrimEnd(":"))).Free / 1GB, 1)
Write-Host ""
Write-Host "  Supprime. $taille rendus, $libre Go libres sur le disque." -ForegroundColor Green
Write-Host "  Le reste de votre cache Hugging Face n'a pas ete touche."
