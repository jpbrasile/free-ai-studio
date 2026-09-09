# Veilleur de mise a jour.
#
# Le probleme, en une image : le bouton « Mettre a jour » est dans une page web
# servie par un conteneur, et un conteneur ne peut pas se reconstruire lui-meme
# — il se couperait la branche sous les pieds. Lui donner la main sur Docker
# reviendrait a confier a une page web les pleins pouvoirs sur la machine.
#
# Ce veilleur est la reponse simple : il tourne sous VOTRE compte, il regarde une
# fois par seconde si la page a depose une demande, et c'est lui qui fait le
# travail. La page ne commande rien ; elle laisse un mot sur la table.
#
# Lance automatiquement par start.ps1. Se ferme avec sa fenetre, sans rien casser.

$ErrorActionPreference = 'Stop'
$Racine  = Split-Path -Parent $PSScriptRoot
$Config  = Join-Path $Racine 'config'
$Demande = Join-Path $Config 'maj-demandee.json'
$Script  = Join-Path $PSScriptRoot 'mettre-a-jour.ps1'
$Vivant  = Join-Path $Config 'maj-veilleuse.json'

if (-not (Test-Path $Config)) { New-Item -ItemType Directory -Path $Config | Out-Null }

Write-Host "Veilleur de mise a jour actif. Le bouton « Mettre a jour » de la page Studio fonctionne."
Write-Host "Fermez cette fenetre pour l'arreter (rien d'autre ne s'arrete)."

while ($true) {
    # Signe de vie : la page s'en sert pour savoir si le bouton peut agir ou
    # s'il doit renvoyer vers le double-clic.
    [ordered]@{ vivant = $true; horodate = (Get-Date).ToString('s'); pid = $PID } |
        ConvertTo-Json | Out-File -FilePath $Vivant -Encoding utf8

    if (Test-Path $Demande) {
        Remove-Item $Demande -Force -ErrorAction SilentlyContinue
        Write-Host "`nDemande recue : mise a jour en cours..."
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $Script
        } catch {
            Write-Warning "Mise a jour interrompue : $($_.Exception.Message)"
        }
        Write-Host "Retour en veille.`n"
    }

    Start-Sleep -Seconds 2
}
