# Essai sur un autre ordinateur — protocole

But : mesurer l'indicateur de l'étape 5 du `PLAN.md`, soit le nombre de tâches menées à terme
sans aide, sur un autre ordinateur que celui où le Studio est développé.

Écrit le 11/09/2026 pour une machine virtuelle Hyper-V. Adapté le 12/09/2026 à un ordinateur
physique, décision de l'utilisateur. **Pas encore joué.** Les points de la section 4 ont été
lus dans les scripts, jamais observés.

Le Studio de ce PC ne sert pas à l'essai. Il n'écoute que `127.0.0.1`, et l'essai porte
d'abord sur l'installation. Que l'autre ordinateur soit sur le même Wi-Fi n'y change rien :
il lui faut seulement Internet.

## Ce qu'il faut

- Windows 10 ou 11, 64 bits.
- 8 Go de mémoire au moins.
- De la place sur le disque. Compter 25 Go, une estimation : Docker Desktop, WSL, l'image
  d'Open WebUI (5,1 Go) et les trois services construits sur place.
- La virtualisation activée : Gestionnaire des tâches, Performance, Processeur, ligne
  « Virtualisation ». Si elle est désactivée, c'est un obstacle réel pour un débutant : le
  noter, ne pas le corriger en silence.
- Les droits d'administrateur sur cet ordinateur, pour installer Docker Desktop.
- Une connexion Internet : environ 6 Go à télécharger.
- Une vraie clé Gemini pour les tâches 2 à 5 : quelques demandes, gratuites.
- Idéalement, une personne qui n'a jamais ouvert un terminal. À défaut, vous, en vous
  interdisant tout ce qui n'est pas écrit dans le README.

## 1. Avant la séance : noter l'état de départ

L'ordinateur n'est pas neuf : ce qui y est déjà installé fausse la mesure, surtout la
tâche 1. Ne rien installer ni désinstaller : noter seulement.

| Relevé | Où le lire | Valeur |
|---|---|---|
| Version de Windows | touche Windows, taper `winver` | |
| Mémoire, place libre sur C: | Paramètres, Système, Stockage | |
| Virtualisation | Gestionnaire des tâches, Performance, Processeur | |
| Déjà installés : Docker Desktop, Git, Visual Studio Code, Python | Paramètres, Applications, Applications installées | |

Si Docker Desktop est déjà installé, la tâche 1 ne mesure pas son installation : l'écrire à
côté du résultat.

Il n'y a pas de retour arrière : un seul essai « neuf » par ordinateur. Un second essai sur la
même machine mesure une réinstallation, et doit être noté comme tel.

## 2. La séance : la grille

Chronométrer chaque tâche. « Sans aide » veut dire que personne n'a dit ni montré quoi faire.
Toute aide donnée se note, avec les mots employés.

| # | Tâche | Menée à terme sans aide (oui/non) | Durée | Où ça a bloqué, mot pour mot |
|---|---|---|---|---|
| 1 | Installer : gestes 1 à 5 du README (Docker Desktop, Git, VS Code, récupérer le dossier, `demarrer.cmd`), jusqu'à la page du Studio ouverte | | | |
| 2 | Coller la clé Gemini sur la page Clés | | | |
| 3 | Poser une question dans le chat et lire la réponse | | | |
| 4 | Poser une question avec Recherche Web, et obtenir une réponse qui cite ses sources | | | |
| 5 | Fabriquer une image | | | |
| 6 | Ouvrir le diagnostic et dire ce qu'il affiche | | | |

Indicateur : le nombre de « oui » sur 6. Le reporter, daté, dans `PLAN.md` (étape 5), avec
l'état de départ de la section 1.

## 3. Pendant la tâche 1 : Docker Desktop

Noter ce qui apparaît :

- une demande de redémarrage ;
- une mise à jour de WSL ;
- les conditions de Docker à accepter ;
- le temps jusqu'à la baleine verte.

Si Docker affiche « Virtualization support not detected », la virtualisation est désactivée
dans le BIOS ou l'UEFI. C'est un blocage : il se note comme tel.

## 4. À observer en plus, propre à Windows

- **Avertissement au double-clic.** Un `demarrer.cmd` venu d'un ZIP fait-il paraître
  « Fichier ouvert — Avertissement de sécurité » ou SmartScreen ? La personne sait-elle quoi
  cliquer ? Un antivirus le bloque-t-il ?
- **Politique d'exécution.** `demarrer.cmd` lance PowerShell avec `-ExecutionPolicy Bypass`.
  Vérifier qu'aucun refus n'apparaît.
- **Python absent.** La page `/diagnostic` suffit-elle à la place de `self-test.ps1` ?
- **Premier démarrage du chat.** Une fois la page du Studio ouverte par `demarrer.cmd`, combien
  de temps le lien « Chat » reste-t-il sans réponse pendant le premier démarrage d'Open WebUI ?
- **Menu du chat.** Il doit proposer Free AI Auto et, avec la clé Gemini, Free AI Max, sans
  « Arena Model ».

## 5. Après

Garder le Studio ou le retirer appartient au propriétaire de l'ordinateur. Pour le retirer :
désinstaller Docker Desktop (Paramètres, Applications), puis supprimer le dossier du Studio.

Ce que l'essai ne mesure pas : macOS, Linux, les autres versions de Windows ; une seule
personne sur un seul ordinateur ne fait pas une statistique.
