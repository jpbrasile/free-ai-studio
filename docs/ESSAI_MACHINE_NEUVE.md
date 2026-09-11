# Essai sur un Windows neuf — protocole

But : mesurer l'indicateur de l'étape 5 du `PLAN.md`, le nombre de tâches menées à terme
sans aide, sur un vrai Windows neuf, sans toucher au Studio qui tourne sur ce PC.

Écrit le 11/09/2026, **avant** la séance. Rien ici n'a encore été joué : les commandes
viennent de la documentation de Microsoft, pas d'un essai.

## Ce qu'il faut

- Windows 11 Pro sur l'hôte, avec Hyper-V activé.
- Une session PowerShell **administrateur** : les commandes Hyper-V l'exigent (ou le groupe
  « Administrateurs Hyper-V »). L'assistant de code n'a pas ce droit sur ce PC : c'est vous
  qui les lancez.
- Une ISO officielle de Windows 11, d'environ 6 Go. Deux sources :
  - l'outil de Microsoft, sur <https://www.microsoft.com/software-download/windows11> : sans
    activation, elle suffit pour l'essai ;
  - Windows 11 Entreprise, version d'évaluation de 90 jours, sur le Microsoft Evaluation Center.
- De la place sur le disque. Le disque virtuel est dynamique : il n'occupe que ce qu'il
  contient, 40 à 60 Go à la fin de l'essai, pour un plafond de 80 Go.
  - Relevé du 11/09 sur l'hôte : 161 Go libres sur C:.
  - `docker system df` y compte 202 Go d'images, dont 99 Go récupérables.
  - Faire de la place, et laquelle, reste votre décision. Le disque virtuel peut aussi aller
    sur un autre lecteur.
- Une vraie clé Gemini pour les tâches 2 à 5 : quelques demandes, gratuites.
- Idéalement, une personne qui n'a jamais ouvert un terminal. À défaut, vous, en vous
  interdisant tout ce qui n'est pas écrit dans le README.

## 1. Créer la machine (PowerShell administrateur, sur l'hôte)

```powershell
$vm  = "fas-neuf"
$vhd = "C:\VM\fas-neuf.vhdx"        # ou sur un autre lecteur
$iso = "C:\ISO\Win11.iso"           # le chemin de votre ISO
New-Item -ItemType Directory -Force (Split-Path $vhd) | Out-Null
New-VM -Name $vm -Generation 2 -MemoryStartupBytes 8GB -NewVHDPath $vhd -NewVHDSizeBytes 80GB -SwitchName "Default Switch"
# Memoire FIXE : quand un hyperviseur tourne dans la VM (Docker Desktop, WSL 2),
# la memoire dynamique ne varie plus.
Set-VMMemory -VMName $vm -DynamicMemoryEnabled $false
# Virtualisation imbriquee, VM eteinte : sans elle, Docker Desktop ne demarre pas.
Set-VMProcessor -VMName $vm -Count 4 -ExposeVirtualizationExtensions $true
# Windows 11 exige un TPM.
Set-VMKeyProtector -VMName $vm -NewLocalKeyProtector
Enable-VMTPM -VMName $vm
Add-VMDvdDrive -VMName $vm -Path $iso
Set-VMFirmware -VMName $vm -FirstBootDevice (Get-VMDvdDrive -VMName $vm)
Start-VM -Name $vm
vmconnect.exe localhost $vm
```

Installer Windows. Prendre un compte local si l'installation le propose ; sinon, un compte
Microsoft de test, jamais le vôtre. N'installer rien d'autre. Puis, sur l'hôte :

```powershell
Stop-VM -Name $vm
Checkpoint-VM -Name $vm -SnapshotName "Windows neuf"
```

## 2. Poser Docker Desktop, comme un débutant

Dans la VM, suivre le geste 1 du README à la lettre. Noter ce qui apparaît :

- une demande de redémarrage ;
- une mise à jour de WSL ;
- les conditions de Docker à accepter ;
- le temps jusqu'à la baleine verte.

Si Docker affiche « Virtualization support not detected », la virtualisation imbriquée n'est
pas passée. Le vérifier sur l'hôte :

```powershell
Get-VMProcessor -VMName fas-neuf | Select-Object ExposeVirtualizationExtensions
```

Puis, sur l'hôte : `Stop-VM -Name $vm` et `Checkpoint-VM -Name $vm -SnapshotName "Docker installe"`.
Chaque nouvel essai repart de ce point :

```powershell
Restore-VMSnapshot -VMName fas-neuf -Name "Docker installe" -Confirm:$false
```

## 3. La séance : la grille

Chronométrer chaque tâche. « Sans aide » veut dire que personne n'a dit ni montré quoi faire.
Toute aide donnée se note, avec les mots employés.

| # | Tâche | Menée à terme sans aide (oui/non) | Durée | Où ça a bloqué, mot pour mot |
|---|---|---|---|---|
| 1 | Installer : gestes 2 à 5 du README (Git, VS Code, récupérer le dossier, `demarrer.cmd`), jusqu'à la page du Studio ouverte | | | |
| 2 | Coller la clé Gemini sur la page Clés | | | |
| 3 | Poser une question dans le chat et lire la réponse | | | |
| 4 | Poser une question avec Recherche Web, et obtenir une réponse qui cite ses sources | | | |
| 5 | Fabriquer une image | | | |
| 6 | Ouvrir le diagnostic et dire ce qu'il affiche | | | |

Indicateur : le nombre de « oui » sur 6. Le reporter, daté, dans `PLAN.md` (étape 5).

## 4. À observer en plus, propre à Windows

Chacun de ces points a été lu dans les scripts, jamais joué.

- **Avertissement au double-clic.** Un `demarrer.cmd` venu d'un ZIP fait-il paraître
  « Fichier ouvert — Avertissement de sécurité » ou SmartScreen ? La personne sait-elle quoi
  cliquer ?
- **Politique d'exécution.** `demarrer.cmd` lance PowerShell avec `-ExecutionPolicy Bypass`.
  Vérifier qu'aucun refus n'apparaît.
- **Python absent.** La page `/diagnostic` suffit-elle à la place de `self-test.ps1` ?
- **Premier démarrage du chat.** Une fois la page du Studio ouverte par `demarrer.cmd`, combien
  de temps le lien « Chat » reste-t-il sans réponse pendant le premier démarrage d'Open WebUI ?
- **Menu du chat.** Il doit proposer Free AI Auto et Free AI Max, sans « Arena Model ».

## 5. Après

Sur l'hôte, deux possibilités :

- `Stop-VM`, en gardant les points de contrôle pour le prochain essai ;
- `Remove-VM -Name fas-neuf`, puis la suppression du fichier `.vhdx` pour rendre la place.

Ces deux gestes vous appartiennent.

Ce que l'essai ne mesure pas : un autre matériel (la VM n'a pas de carte graphique),
Windows 10, macOS.
