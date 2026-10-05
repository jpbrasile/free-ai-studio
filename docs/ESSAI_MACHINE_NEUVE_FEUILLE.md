# Essai sur un autre ordinateur — feuille du jour

À imprimer et à remplir au stylo. La règle reste `docs/ESSAI_MACHINE_NEUVE.md` : cette
feuille la met en cases, elle n'ajoute aucune règle. Écrite le 26/09/2026, avant la séance.
Chaque renvoi `fichier:ligne` ci-dessous porte entre parenthèses le texte qu'on doit y lire.

Date butoir : **31/10/2026** (`docs/ESSAI_MACHINE_NEUVE.md:20` (`butoir: 2026-10-31`),
`docs/PLAN-PLATEFORME.md:1534` (`La date de l'essai machine neuve`)).

---

## A. Avant la séance

### Ce qu'il faut sur l'ordinateur

Repris de `docs/ESSAI_MACHINE_NEUVE.md:40-56` (`Ce qu'il faut`). Cocher ce qui est vrai ;
ce qui manque se **note**, ne se corrige pas en silence (`docs/ESSAI_MACHINE_NEUVE.md:49-51` (`ne pas le corriger en silence`)).

- ☐ Windows 10 22H2 ou Windows 11 23H2 au moins, 64 bits. `demarrer.cmd` le vérifie
  (`scripts/demarrer.ps1:94` (`$build -lt 19045`)).
- ☐ 8 Go de mémoire au moins.
- ☐ 25 Go libres sur le disque — une estimation (`docs/ESSAI_MACHINE_NEUVE.md:45` (`Compter 25 Go`)).
- ☐ Virtualisation activée (Gestionnaire des tâches, Performance, Processeur).
- ☐ Un compte administrateur sur cet ordinateur, pour installer Docker Desktop.
- ☐ Internet : environ 6 Go à télécharger.
- ☐ Une vraie clé Gemini, prête pour la tâche 2 (`docs/ESSAI_MACHINE_NEUVE.md:54` (`vraie clé Gemini`)).
  **Ne pas l'écrire sur cette feuille.**
- ☐ Idéalement, une personne qui n'a jamais ouvert un terminal
  (`docs/ESSAI_MACHINE_NEUVE.md:55` (`jamais ouvert un terminal`)).

Seule la clé Gemini sert à l'essai. `docs/SERVICES_DEBUTANT.md:100` (`Commencez uniquement avec`)
conseille aussi Groq et OpenRouter ; les ajouter changerait ce qu'on mesure. Le README dit
qu'une clé Gemini suffit (`README.md:84-85` (`une seule chose`)).

### Ce qu'il ne faut PAS faire

- ☐ **Pas de `.env` recopié** d'un autre ordinateur, ni de dossier `config\` recopié.
  L'essai du 13/09 a été faussé ainsi, tâches 2 et 5 (`PLAN.md:74` (`recopié d'un autre ordinateur`)).
  `demarrer.cmd` fabrique lui-même un `.env` neuf quand il n'y en a pas
  (`scripts/demarrer.ps1:353` (`.env cree a partir de .env.example`)) ; s'il écrit
  « .env deja present » au premier lancement, quelque chose a été recopié : le noter.
- ☐ **Pas d'aide non notée.** Toute aide se note avec les mots employés
  (`docs/ESSAI_MACHINE_NEUVE.md:80-81` (`Toute aide donnée se note`)). Une tâche aidée compte « non ».
- ☐ **Ne rien installer ni désinstaller avant** : seulement noter l'état de départ
  (`docs/ESSAI_MACHINE_NEUVE.md:63` (`Ne rien installer ni désinstaller`)).
- ☐ Ne pas rallumer la virtualisation à la place de la personne. Si elle est éteinte, c'est
  un blocage de la tâche 1, à noter.
- ☐ Un seul essai « neuf » par ordinateur. Un second essai sur la même machine se note
  « réinstallation » (`docs/ESSAI_MACHINE_NEUVE.md:75-76` (`un seul essai`)).

### Comment récupérer le Studio : ce que dit le dépôt

Le README recommande le **clone par VS Code** : menu Affichage → Palette de commandes,
`Git: Clone`, coller `https://github.com/jpbrasile/free-ai-studio.git`, désigner
**Documents** comme dossier parent (`README.md:55-59` (`Récupérer le dossier`)). Le ZIP
n'est qu'un repli : tout marche sauf le bouton de mise à jour (`README.md:60-61` (`Download ZIP`)),
et `demarrer.cmd` le dit (`scripts/demarrer.ps1:311` (`Dossier obtenu par telechargement ZIP`)).

Pendant l'essai, c'est la personne qui récupère le dossier : cela fait partie de la tâche 1
(geste 4 du README). Si elle prend le ZIP d'elle-même, ce n'est pas une faute : le noter.

### La version testée

- **Veille de l'essai** : relever le commit de `main` sur GitHub (page du dépôt, identifiant
  court du dernier commit) : `____________`
- **Après la tâche 1** : la page du Studio affiche « version installée » suivie de 7 caractères
  (`free-tier-manager/app.py:3029` (`version installée`)). Elle les lit dans le dossier `.git`
  (`free-tier-manager/app.py:2507` (`lu directement dans .git`)). Relevé : `____________`
- Dossier pris en ZIP : pas de `.git`, la page affiche « version inconnue »
  (`free-tier-manager/app.py:3029` (`version inconnue`)). Garder alors le commit relevé la veille,
  et écrire « ZIP » à côté.

---

## B. État de départ (avant de toucher à quoi que ce soit)

Repris de `docs/ESSAI_MACHINE_NEUVE.md:65-70` (`Version de Windows`).

| Relevé | Où le lire | Valeur |
|---|---|---|
| Date et heure | | |
| Modèle de l'ordinateur | | |
| Version de Windows (et numéro de build) | touche Windows, taper `winver` | |
| Mémoire | Paramètres, Système, Informations | |
| Place libre sur C: | Paramètres, Système, Stockage | |
| Virtualisation | Gestionnaire des tâches, Performance, Processeur, ligne « Virtualisation » | ☐ activée ☐ désactivée |
| Docker Desktop déjà installé ? | Paramètres, Applications, Applications installées | ☐ non ☐ oui, version : |
| Git déjà installé ? | idem | ☐ non ☐ oui |
| Visual Studio Code déjà installé ? | idem | ☐ non ☐ oui |
| Python déjà installé ? | idem | ☐ non ☐ oui |
| Antivirus autre que celui de Windows ? | idem | ☐ non ☐ oui, lequel : |
| Un dossier `free-ai-studio` déjà présent dans Documents ? | Explorateur | ☐ non ☐ oui |
| Qui joue l'essai | | ☐ une personne qui n'a jamais ouvert un terminal ☐ le propriétaire lui-même |

Si Docker Desktop est déjà installé, la tâche 1 ne mesure pas son installation : l'écrire à
côté du résultat (`docs/ESSAI_MACHINE_NEUVE.md:72` (`Si Docker Desktop est déjà installé`)).

---

## C. Les six tâches

**La règle, écrite le 23/09/2026 avant la séance** (`docs/ESSAI_MACHINE_NEUVE.md:92-97` (`Quand une tâche compte`)) :
une tâche compte **« non »** dès que quelqu'un a dit ou montré quoi faire, dès que la personne
abandonne, ou si le Studio tombe en panne. Elle **ne compte pas « non » parce qu'elle a été
longue** : pas de durée plafond.

Lire la consigne **telle quelle**, sans rien ajouter. Ne pas montrer l'écran du doigt.

### Tâche 1 — Installer

> **Consigne à lire :** « Voici la page d'accueil du Studio sur GitHub
> (https://github.com/jpbrasile/free-ai-studio). Installez-le en suivant ce qui est écrit
> dans la partie *Installation*, jusqu'à ce que la page du Studio s'ouvre. »

Ouvrir la page GitHub dans le navigateur avant de lire la consigne. Les gestes : Docker Desktop,
Git, VS Code, récupérer le dossier, double-clic sur `demarrer.cmd` (`README.md:36-68` (`Cinq gestes`)).

**Compte « oui »** : la page `http://127.0.0.1:8010/studio` s'ouvre dans le navigateur
(`demarrer.cmd` l'ouvre seul à la fin : `scripts/demarrer.ps1:665` (`Votre page`)), sans aide.

| Début | Fin | Menée sans aide | Aide donnée |
|---|---|---|---|
| __ h __ | __ h __ | ☐ oui ☐ non ☐ abandon | ☐ non ☐ oui, mot pour mot : |

Où ça a bloqué, mot pour mot : ______________________________________________

Pendant la tâche 1, noter aussi (`docs/ESSAI_MACHINE_NEUVE.md:107-117` (`Pendant la tâche 1`)) :

- ☐ demande de redémarrage — ☐ mise à jour de WSL — ☐ conditions de Docker à accepter
- Temps jusqu'à la baleine verte de Docker Desktop : ______
- ☐ « Virtualization support not detected » affiché : c'est un blocage, il se note comme tel.
- ☐ `demarrer.cmd` s'est arrêté sur **ARRET** : recopier le titre : __________________
- Dossier récupéré par : ☐ clone VS Code ☐ ZIP ☐ autre : ______
- La fenêtre de `demarrer.cmd` a-t-elle écrit « .env deja present » ? ☐ non ☐ oui (alors l'essai n'est pas neuf)

### Tâche 2 — Coller la clé Gemini

Donner la clé à la personne comme convenu (voir section G, point 2). Puis :

> **Consigne à lire :** « Le Studio a besoin d'une clé. La voici. Branchez-la. »

**Compte « oui »** : la page Clés affiche « Le chat fonctionne. »
(`free-tier-manager/app.py:2148` (`Le chat fonctionne.`)), sans aide.

| Début | Fin | Menée sans aide | Aide donnée |
|---|---|---|---|
| __ h __ | __ h __ | ☐ oui ☐ non ☐ abandon | ☐ non ☐ oui, mot pour mot : |

Où ça a bloqué, mot pour mot : ______________________________________________

### Tâche 3 — Poser une question dans le chat

> **Consigne à lire :** « Posez une question au Studio, par écrit, et lisez-moi la réponse. »

**Compte « oui »** : une réponse s'affiche dans le chat et la personne la lit à voix haute, sans aide.

| Début | Fin | Menée sans aide | Aide donnée |
|---|---|---|---|
| __ h __ | __ h __ | ☐ oui ☐ non ☐ abandon | ☐ non ☐ oui, mot pour mot : |

Question posée : ______________________________ Choix du menu (Auto / Max) : ______

### Tâche 4 — Chercher sur le Web

> **Consigne à lire :** « Demandez au Studio de chercher sur Internet le prix du gaz naturel
> en France cette semaine, et montrez-moi d'où vient sa réponse. »

La carte « Recherche Web » de la page du Studio dit comment faire
(`free-tier-manager/app.py:2839` (`Recherche Web`)).

**Compte « oui »** : la réponse affiche au moins une source (lien ou nom de site) et la personne
la montre, sans aide.

| Début | Fin | Menée sans aide | Aide donnée |
|---|---|---|---|
| __ h __ | __ h __ | ☐ oui ☐ non ☐ abandon | ☐ non ☐ oui, mot pour mot : |

Où ça a bloqué, mot pour mot : ______________________________________________

### Tâche 5 — Fabriquer une image

> **Consigne à lire :** « Demandez au Studio de dessiner un chat roux sur un toit. »

La carte « Image » de la page du Studio dit comment faire
(`free-tier-manager/app.py:2838` (`Image`)).

**Compte « oui »** : une image s'affiche, sans aide. Du texte à la place d'une image compte
« non ». Si cela arrive (c'est arrivé le 13/09, cause non établie :
`PLAN.md:77` (`rend du texte`)) : **avant de toucher à quoi que ce soit**, recopier la
réponse exacte et cliquer **Copier ce diagnostic** sur la page Diagnostic, puis coller dans un
fichier texte (`docs/ESSAI_MACHINE_NEUVE.md:99-101` (`Copier ce diagnostic`)).

| Début | Fin | Menée sans aide | Aide donnée |
|---|---|---|---|
| __ h __ | __ h __ | ☐ oui ☐ non ☐ abandon | ☐ non ☐ oui, mot pour mot : |

Ce qui s'est affiché : ☐ une image ☐ du texte ☐ rien ☐ un message d'erreur : ______________

### Tâche 6 — Ouvrir le diagnostic

> **Consigne à lire :** « Le Studio sait vérifier s'il va bien. Trouvez où, et dites-moi ce
> qu'il affiche. »

Le lien « Diagnostic » est sur la page du Studio (`free-tier-manager/app.py:2914` (`Diagnostic`)) ;
la page est `http://127.0.0.1:8010/diagnostic`.

**Compte « oui »** : la personne ouvre la page Diagnostic et dit avec ses mots ce qu'elle
affiche (tout va bien, ou quel maillon casse), sans aide.

| Début | Fin | Menée sans aide | Aide donnée |
|---|---|---|---|
| __ h __ | __ h __ | ☐ oui ☐ non ☐ abandon | ☐ non ☐ oui, mot pour mot : |

Ce qu'elle a dit : ______________________________________________

### Résultat

| Tâche | 1 | 2 | 3 | 4 | 5 | 6 | **Total** |
|---|---|---|---|---|---|---|---|
| oui / non | | | | | | | **___ / 6** |

---

## D. À observer, propre à Windows

Repris de `docs/ESSAI_MACHINE_NEUVE.md:119-144` (`propre à Windows`).

| Observation | Ce qu'on a vu |
|---|---|
| **Avertissement au double-clic** de `demarrer.cmd` : « Fichier ouvert — Avertissement de sécurité », SmartScreen, antivirus ? La personne a-t-elle su quoi cliquer ? | ☐ rien ☐ avertissement ☐ SmartScreen ☐ antivirus — ce qu'elle a cliqué : |
| **Politique d'exécution** : un refus de PowerShell ? (`demarrer.cmd:6` (`-ExecutionPolicy Bypass`)) | ☐ aucun refus ☐ refus, texte : |
| **ZIP puis clone** : `demarrer.cmd` s'est-il arrêté sur « deja installe depuis un autre dossier » (`scripts/demarrer.ps1:331` (`deja installe depuis un autre dossier`)) ? La personne a-t-elle compris, et qu'a-t-elle fait ? | ☐ sans objet ☐ oui : |
| **Python absent** : la page Diagnostic a-t-elle suffi ? | ☐ oui ☐ non : |
| **Premier démarrage du chat** : combien de temps le lien « Chat » est-il resté sans réponse ? (`scripts/demarrer.ps1:637` (`Ouverture du chat`)) | ______ min |
| **Menu du chat** : Free AI Auto, et Free AI Max une fois la clé posée, sans « Arena Model » ? | ☐ Auto ☐ Max ☐ Arena Model présent |
| **Après un redémarrage de Windows** : la page du Studio dit-elle « le veilleur n'est pas lancé » ? Un antivirus signale-t-il le veilleur ? Non vérifié à ce jour (`PLAN.md:82` (`un vrai redémarrage de Windows`)). | ☐ mention absente ☐ mention présente ☐ alerte antivirus : |

---

## E. À la fin : reporter le résultat

Deux écritures, dans cet ordre. **Un échec se reporte comme un échec** : 0/6 est un chiffre.

### 1. Dans `PLAN.md`, étape 5

L'étape 5 commence à `PLAN.md:70` (`verrouiller Chat, Recherche et Image`) ; l'essai partiel du
13/09 y est noté à `PLAN.md:74` (`Essai du 13/09/2026`). Ajouter une ligne de la même forme,
avec l'état de départ de la section B et la version testée
(`docs/ESSAI_MACHINE_NEUVE.md:103-105` (`Indicateur : le nombre`)) :

```text
   - **Essai du JJ/MM/2026 : n/6.** <modèle>, Windows <version> (build <n>), <mémoire>,
     virtualisation <activée/désactivée>, déjà installés : <liste ou « rien »>.
     Joué par <une personne débutante / le propriétaire>. Version testée : <commit à 7 caractères>
     (<clone / ZIP>). Tâches : 1 <oui/non>, 2 …, 6 …. Aides données : <mot pour mot, ou « aucune »>.
     Blocages : <mot pour mot>. Feuille remplie : <où elle est rangée>.
```

`PLAN.md:72` (`le pourcentage de tâches`) parle d'un pourcentage, le protocole de n/6 : écrire
les deux (par exemple « 4/6, soit 67 % »).

### 2. Dans `docs/ESSAI_MACHINE_NEUVE.md`, la ligne d'échéance

**Remplacer** la ligne `docs/ESSAI_MACHINE_NEUVE.md:20` (`etat: en-attente`) — ne pas en ajouter
une seconde : deux lignes d'échéance font échouer la CI
(`scripts/verifier-echeances.py:144` (`len(trouves) > 1`)). La ligne devient :

```text
<!-- echeance: essai-machine-neuve | butoir: 2026-10-31 | etat: tenue | preuve: 2026-10-18, 4/6, version a1b2c3d (clone), PLAN.md étape 5 -->
```

(date, chiffre et version ci-dessus à remplacer par les vrais.)

Ce que le script exige, lu dans `scripts/verifier-echeances.py` :

- la forme `<!-- echeance: <id> | butoir: AAAA-MM-JJ | etat: <etat> | preuve: <texte> -->`
  (`scripts/verifier-echeances.py:8` (`echeance: <id> | butoir`)) ;
- le butoir reste **2026-10-31** : le changer sans changer le script fait échouer la CI
  (`scripts/verifier-echeances.py:163` (`butoir != echeance.butoir`)) ;
- `etat: tenue` exige une preuve non vide (`scripts/verifier-echeances.py:180` (`etat in ("tenue", "abandonnee") and not preuve`)) ;
- **dans la preuve, pas de barre verticale `|`** : le script coupe la ligne à chaque `|`
  (`scripts/verifier-echeances.py:102` (`corps.split("|")`)), et un morceau sans deux-points
  fait échouer la CI (`scripts/verifier-echeances.py:106` (`champ sans deux-points`)). Utiliser
  des virgules. Pas de `-->` non plus : il fermerait le commentaire trop tôt ;
- le contenu de la preuve est libre : le script ne vérifie ni la date, ni le n/6, ni la version.
  Le protocole demande « date, n/6, version testée » (`docs/ESSAI_MACHINE_NEUVE.md:30` (`etat: tenue`)).

Pour vérifier avant de committer : `python scripts/verifier-echeances.py` doit écrire
`ok   essai-machine-neuve : tenue -- …`.

Si l'essai n'est pas joué au 31/10/2026, l'autre issue est écrite à
`docs/ESSAI_MACHINE_NEUVE.md:31-32` (`etat: abandonnee`).

---

## F. Après la séance

Garder ou retirer le Studio appartient au propriétaire de l'ordinateur. Pour le retirer :
`docs/ESSAI_MACHINE_NEUVE.md:148-152` (`Pour le retirer`) — Docker Desktop, **les deux**
raccourcis du dossier Démarrage, puis le dossier du Studio.

---

## G. Ce qui reste à décider avant la séance

Points que ni le protocole ni le README ne tranchent. À décider par le propriétaire, **avant**
la séance, et à écrire ici pour ne pas les décider en voyant le résultat.

1. **Mot de passe administrateur.** Docker Desktop le demande. Si la personne ne l'a pas et que
   le propriétaire le tape, est-ce une aide ? Décision : ______________________
2. **La clé Gemini.** La tâche 2 dit « coller » : la clé est donc fournie. Par quel moyen
   arrive-t-elle sur l'ordinateur (fichier sur clé USB, message) ? Et la créer soi-même
   (la page Clés renvoie vers `https://aistudio.google.com/apikey` :
   `free-tier-manager/app.py:210` (`aistudio.google.com/apikey`)) fait-il partie de l'essai ?
   Décision : ______________________
3. **Les interrupteurs Image et Recherche Web.** Les cartes de la page du Studio disent d'ouvrir
   le rouage et de mettre l'interrupteur (`free-tier-manager/app.py:2838` (`mettez <b>Image</b>`)).
   Le 13/09, le retour était qu'un débutant ne doit pas avoir à y penser
   (`PLAN.md:78` (`ni penser à`)). La consigne des tâches 4 et 5 ne nomme pas l'interrupteur :
   lire la carte est permis, rien d'autre. D'accord ? ______________________
4. **La porte du portage.** `PLAN.md:811` (`Porte du portage`) pose : aucune friction bloquante
   ouverte avant le portage sur un poste client. Au 26/09, une reste ouverte
   (`docs/FRICTIONS.md:139` (`24 h sans intervention`), session NotebookLM ; le critère des 24 h
   a échoué le 26/09, session morte après environ 2 h). NotebookLM n'est dans aucune des six tâches. L'essai attend-il sa levée ?
   ______________________
