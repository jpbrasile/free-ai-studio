# Les sauvegardes — ce qui est décidé, ce qui ne l'est pas, et la date

Décision de l'utilisateur du 19/09/2026 : **les sauvegardes se font en local et sur le
VPS** (`docs/PLAN-PLATEFORME.md` §8, décision 15). Ce document porte cette décision, la
date qui la rend vérifiable, et l'endroit où la preuve s'écrira. **La procédure est écrite
depuis le 26/09/2026** (section « La procédure », en fin de document), contre des
variables, jamais contre des valeurs. **Elle n'a encore jamais été jouée** : ni
sauvegarde, ni restauration. Tant que l'essai n'a pas eu lieu, elle est une intention.

## La date : 31 octobre 2026

<!-- echeance: restauration-sauvegardes | butoir: 2026-10-31 | etat: en-attente -->

**Le critère n'est pas « la sauvegarde est configurée », c'est « elle a été remise en
place ».** Il vient du plan d'origine, pour P0 : *« DoD : restore-from-backup test
passes »*. Une sauvegarde jamais restaurée est un espoir : on n'apprend qu'elle était
illisible, incomplète ou chiffrée avec une clé perdue que le jour où on en a besoin, et ce
jour-là il n'y a pas de second essai.

**Premier essai de restauration avant le 31/10/2026.** La ligne de commentaire ci-dessus
est relue par `scripts/verifier-echeances.py`, étape « Échéances » de la CI. Trois
écritures possibles :

- l'essai est joué → `etat: tenue | preuve: <date, ce qui a été restauré, où>` ;
- on renonce → `etat: abandonnee | preuve: <date et qui décide>`, **et** le texte de ce
  document écrit les mots **essai abandonné** ;
- rien n'est fait et on est avant le butoir → `etat: en-attente`.

Passé le 31/10/2026, la dernière écriture fait **échouer la CI**.

## Les trois questions encore sans réponse

Elles sont ouvertes depuis le 19/09/2026 et **l'essai de restauration les referme presque
toutes en une fois** — c'est la raison de le dater plutôt que de les instruire une par une.

| Question | État | Ce que l'essai y répondra |
|---|---|---|
| La troisième copie (disque externe ou espace en ligne) | **à décider** — local + VPS font déjà deux lieux ; quelques Mo par mois coûtent presque rien | la **taille réelle** d'une archive (le résumé de `sauvegarder.ps1` l'affiche pièce par pièce) : c'est elle qui dit si « quelques Mo » est vrai, une fois les conversations comptées |
| Le VPS est-il lui-même sauvegardé ? | **non vérifié** | l'étape 6 de l'essai : lire dans le panneau de l'hébergeur si une sauvegarde ou des instantanés du VPS sont actifs, et l'écrire ici |
| Le VPS est-il en Europe, comme le plan l'exige ? | **non vérifié** | même étape : la région du centre de données, lue dans le panneau de l'hébergeur (pas par un service en ligne à qui l'on donnerait l'adresse) |

## Ce qu'il y a à sauvegarder aujourd'hui

Mesuré dans l'arbre le 19/09/2026. Rien de ceci n'est encore sauvegardé ailleurs que là où
il vit : c'est l'état de départ, pas un acquis.

| Ce que c'est | Où ça vit | Se perd si |
|---|---|---|
| Le code et son histoire | les deux dépôts git (ce dépôt, et le distant GitHub) | les deux disparaissent ensemble — peu probable, et c'est la seule pièce déjà en double |
| **Les clés saisies depuis les pages** `/cles` | le dossier de configuration du poste : `keys.json`, `sandbox-keys.json` | le dossier est effacé — et elles ne sont **dans aucun dépôt**, par construction |
| **La clé du coffre**, qui ouvre les deux magasins ci-dessus | `secrets/coffre.cle`, **hors** du dossier de configuration (c'est tout son objet), ou `STUDIO_COFFRE_CLE` dans `.env` | elle est perdue — et alors les clés sauvegardées à la ligne du dessus ne s'ouvrent plus. **Sauvegarder `config/` sans elle, c'est sauvegarder un fichier illisible** : les deux vont ensemble, ou ni l'une ni l'autre |
| Les compteurs de dépense | même dossier : `modal-budget.json`, `video-budget.json`, `chanson-budget.json`, `dialogue-budget.json` | idem — et on repart à zéro sans savoir ce qui a déjà été dépensé |
| Les témoins de réglage du chat | même dossier : `open-webui-regle.json` et ses voisins | idem — le Studio les repose au démarrage suivant |
| Les conversations et les comptes du chat | le volume Docker `open-webui-data` | le volume est supprimé — c'est le geste de dépannage documenté, il efface l'historique |
| Les travaux des bacs à sable | le volume Docker `sandbox-data` | idem |
| La base de mesures du registre | **n'existe pas encore** (registre non commencé) | — |
| La base de mesures des usages (depuis le 25/09/2026) | le dossier `config/mesures/` du Studio (hors des volumes Docker), un sous-dossier par service : `routeur/` (réponses du chat, images, dictée, voix lue) et `bac-a-sable/` (questions à NotebookLM) ; un fichier par mois (`AAAA-MM.jsonl`), jamais le texte de la personne (`mesures.py`, deux exemplaires identiques). Jusqu'au 25/09/2026 elle vivait dans le volume `sandbox-data`, dossier `mesures/` | le dossier `config/` est effacé — et elle ne se reconstruit pas : c'est l'historique des usages |
| L'historique des questions NotebookLM | même volume, `jobs/<résumé>/questions.jsonl` — le texte des questions et des réponses, qui **reste sur ce poste** (décision du 25/09, PLAN-PLATEFORME) | idem, ou quand on supprime le résumé : c'est voulu |

Deux remarques qui changent la procédure à écrire :

- **Les clés ne se sauvegardent pas comme le reste.** Une sauvegarde de `keys.json` est
  une sauvegarde de secrets : elle ne part ni sur le VPS en clair, ni dans un dépôt, même
  privé. Le gestionnaire de mots de passe est leur place.
- **Le registre n'existe pas encore**, donc la pièce que le plan voulait protéger en
  priorité n'est pas là. L'essai de restauration du 31/10 portera sur ce qui existe ce
  jour-là — et c'est déjà lui qui répond aux trois questions du tableau précédent.

## La règle d'écriture : des variables, jamais des valeurs

Établie le 19/09/2026, et appliquée le jour même après qu'une première rédaction eut mis
le nom de domaine du VPS en toutes lettres dans un dépôt **public depuis le 09/09**.

- **Les secrets** (clé SSH, mot de passe Postgres, jetons) : l'environnement seul, `.env`
  non suivi, gestionnaire de mots de passe. Jamais un dépôt, privé **comme** public.
- **Les coordonnées** (nom de domaine, IP, noms de conteneurs, ports, chemins) : des
  **variables**, dont les valeurs ne sont écrites nulle part dans git. Une commande de
  sauvegarde s'écrit `ssh $VPS_UTILISATEUR@$VPS_HOTE`, jamais l'adresse en clair.
- **La forme** (ce qui est sauvegardé, à quelle cadence, la procédure de restauration) :
  ici, versionnée, relisible — c'est elle qu'il faut pouvoir rejouer.

Le régime existe déjà dans ce dépôt : `.env` est ignoré, `.env.example` porte les noms des
variables et **aucune valeur**. La procédure ci-dessous s'y coule : `VPS_HOTE`,
`VPS_UTILISATEUR`, `VPS_DOSSIER` (et, facultatives, `VPS_PORT_SSH`, `VPS_CLE_SSH`) sont
nommées dans `.env.example`, vides.

## La procédure

Écrite le 26/09/2026. Vérifié à l'écriture : les deux scripts se lisent sans erreur de
syntaxe par l'analyseur de Windows PowerShell 5.1, et `tests/test_sauvegardes.py` relit
leurs garde-fous comme du texte.

**Premier passage réel, 26/09/2026 à 19:28, à chaud** (`-AChaud`, pour ne pas arrêter le
Studio pendant la mesure de la session NotebookLM ; le manifeste dit « a-chaud ») :
`sauvegarder.ps1` a produit 8 pièces sans erreur (chat 1 130 072 576 octets, bacs à sable
887 864 832, `config.tar` 44 032, magasins 29 696 ; 31 fichiers de `config/`) ; puis
`restaurer.ps1 -SansCle` dans la cible d'essai : 8 empreintes conformes, clone du dépôt à
la version de la sauvegarde, `config/` remis, les deux volumes d'essai
(`free-ai-studio-essai_*`) conformes à leur liste fichier par fichier, rien du Studio en
service touché. La base du chat copiée à chaud se rouvre : `PRAGMA integrity_check` = `ok`,
43 tables.

**Le Studio relancé sur l'essai, même nuit (vers 20:40)**, à côté du Studio en service :
- un fichier `docker-compose.essai.yml` propre au dossier d'essai (noms `essai-*`, ports
  18010, 18020 et 13000 par `!override`, les noms des conteneurs étant écrits en dur dans
  `docker-compose.yml`) ;
- un `.env` d'essai tiré de `.env.example` avec **quatre secrets internes neufs**, aucune clé
  de fournisseur, Modal, Kaggle et Colab coupés : le vrai `.env` n'est pas copié.

`up -d --build` a réussi. Les cinq services ont répondu 200 à `/health`, et le routeur à
`/diagnostic/etat`. L'essai relit ce qu'on lui a rendu :
- 126 dossiers de travaux, comme le Studio en service ; `/jobs` en sert 100, son plafond ;
- la base du chat donne les mêmes comptes des deux côtés : 1 compte, 24 conversations,
  5 fichiers, 352 réglages.

Le Studio en service a répondu 200 pendant tout l'essai. La pile d'essai a ensuite été
arrêtée, ses images supprimées. Ses volumes et son dossier sont **gardés**.

**Ce que l'essai apprend pour un vrai jour de restauration** : la base du chat garde la clé
du routeur (question B). Avec un `.env` neuf, le chat restauré présente donc l'**ancienne**
clé à un routeur qui en attend une nouvelle. Il faut reprendre `FREE_TIER_MANAGER_KEY` du
gestionnaire de mots de passe, avec la clé du coffre. **Non vérifié** : le chat de l'essai
refusé par son routeur (déduit, pas observé).

**Non vérifié encore** : ~~une copie à froid~~ (**faite le 27/09/2026**, voir « Copie à froid du 27/09 » plus bas), la restauration **avec** la clé du coffre (faite
sans elle, les magasins restent illisibles dans l'essai), `scp` et le VPS.

### Ce qui part où

| Pièce | Contenu | Archive locale | VPS |
|---|---|---|---|
| `config.tar` | `config/` **sans** les trois magasins de secrets : compteurs de dépense, témoins de réglage, base de mesures (`config/mesures/`, jamais le texte de la personne) | oui | oui |
| `config-magasins.tar` | `keys.json`, `sandbox-keys.json`, `notebooklm/` (la session NotebookLM) : valeurs **fermées par le coffre**, noms en clair | oui | **non** par défaut — question A |
| `open-webui-data.tar` | le volume du chat : conversations, comptes ; ~~**et la clé interne du routeur en clair** (vérifié le 26/09, question B)~~ **sans la clé du routeur depuis le 27/09** (retirée de la copie, remise à la restauration : section « La clé du routeur hors des sauvegardes », en fin de document) | oui | **non** par défaut — question B |
| `sandbox-data.tar` | le volume des bacs à sable : travaux, **texte des questions NotebookLM** | oui | **non** par défaut — question B |
| `<volume>.sha256.txt`, `<volume>.tailles.txt` | la liste des fichiers de chaque volume, empreinte et taille | oui | suit son volume |
| `manifeste.json` | date, version git, pièces, tailles, empreintes SHA-256, liste des fichiers de `config/`, empreinte **courte** de la clé du coffre | oui | oui |
| **`secrets/coffre.cle`** | la clé du coffre | **non** | **non, jamais** |
| **`.env`** | clés des fournisseurs, mots de passe internes, peut-être `STUDIO_COFFRE_CLE` | **non** | **non** |
| volume `whisper-modeles` | les modèles de la dictée et de la voix | non | non — ils se retéléchargent |

**La clé du coffre et `.env` vont dans le gestionnaire de mots de passe**, et nulle part
ailleurs : c'est ce qui rend vraie la phrase « config/ sans sa clé est illisible » — dans le
bon sens. Aucun interrupteur des scripts ne les met dans une archive. Le manifeste garde
seulement les 16 premiers caractères du SHA-256 de la clé : de quoi reconnaître la bonne
clé à la restauration, rien pour la retrouver. Si `STUDIO_COFFRE_CLE` est posée dans `.env`,
c'est elle qui ouvre le coffre (`coffre.py` la lit avant le fichier), et les scripts ne la
lisent pas : l'empreinte du manifeste est alors celle d'un fichier qui ne sert pas.

Par défaut, **seul ce qui ne contient ni secret ni texte de la personne part sur le VPS.**
Ce n'est pas un choix tranché : ce sont les deux premières questions ci-dessous.

### Questions pour le propriétaire, nées de la procédure

| | Question | Ce qui est fait en attendant |
|---|---|---|
| A | **Les magasins chiffrés partent-ils sur le VPS ?** Pour : si le PC meurt, les clés se rouvrent avec la clé du gestionnaire de mots de passe. Contre : « une sauvegarde de `keys.json` est une sauvegarde de secrets » (plus haut), les noms des services sont en clair, et une valeur d'avant le coffre (sans le préfixe `coffre-v1:`) serait en clair — ~~**non vérifié** qu'il n'en reste aucune~~ **vérifié le 26/09/2026** sur ce poste : `keys.json` a 2 valeurs, les deux commencent par `coffre-v1:` ; `sandbox-keys.json` est vide (aucune valeur affichée pendant la vérification). Les clés de fournisseurs se refont aussi chez chaque fournisseur. | ne partent pas ; l'interrupteur `-VpsAvecMagasinsChiffres` existe, éteint. **Répondu le 27/09/2026 par le propriétaire : non** — les clés se refont chez chaque fournisseur si le PC meurt. |
| B | **Les conversations et le texte des questions NotebookLM partent-ils sur le VPS ?** La décision du 19/09 dit « local et VPS » ; celle du 25/09 dit que le texte des questions NotebookLM « reste sur ce poste ». Les deux ne tiennent pas ensemble pour `sandbox-data`. Et la base du chat contient peut-être la clé interne du routeur (Open WebUI garde ses réglages de connexion dans sa base) — ~~**non vérifié**~~ **vérifié le 26/09/2026 : oui, en clair, quatre fois.** Dans la copie restaurée de la base (`webui.db`, table `config`), `openai.api_keys`, `image_generation.openai.api_key`, `audio.stt.openai.api_key` et `audio.tts.openai.api_key` portent chacune une valeur de 64 signes, **identique à `FREE_TIER_MANAGER_KEY`** de `.env` — comparaison par empreinte SHA-256 dans un conteneur jetable, aucune valeur affichée. La table `api_key` (clés des personnes) est vide. Donc `open-webui-data.tar` est **aussi une sauvegarde de secret** : l'envoyer sur le VPS, c'est y envoyer la clé du routeur ; l'archive locale la contient déjà. **Depuis le 27/09, la copie ne la porte plus** (section « La clé du routeur hors des sauvegardes », en fin de document) : la question B redevient une question de vie privée, les conversations. | ne partent pas ; l'interrupteur `-VpsAvecVolumes` existe, éteint. **Répondu le 27/09/2026 par le propriétaire : non** — conversations et questions NotebookLM restent sur ce poste ; perdues si son disque meurt, c'est accepté. |
| C | **La copie VPS doit-elle être chiffrée ?** Le plan d'origine dit « *encrypted backups* ». Aujourd'hui les archives partent telles quelles, par `scp` (chiffré en transit, pas au repos). Tant que A et B restent à « non », rien de secret ni de personnel n'y part ; si l'une passe à « oui », la question devient bloquante (avec quoi chiffrer, et où garder cette clé-là). | non chiffrée. **Répondu le 27/09/2026 par le propriétaire : pas de chiffrement tant que A et B restent à non** ; si l'une passe à oui, chiffrement obligatoire avant tout envoi. |
| D | **La clé du coffre dans l'archive *locale* ?** Écarté ici : la règle du document range les clés au gestionnaire de mots de passe, et une archive locale se copie sur un disque externe. Si le propriétaire préfère une archive locale autosuffisante, c'est à décider, pas à glisser dans un script. | jamais dans une archive. **Répondu le 27/09/2026 par le propriétaire : non** — la clé du coffre reste au gestionnaire de mots de passe. |

### `scripts/sauvegarder.ps1`

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sauvegarder.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sauvegarder.ps1 -VersVps
```

- **Où.** Un dossier daté `studio-AAAAMMJJ-HHMMSS` sous `-Destination`, par défaut
  `%USERPROFILE%\Sauvegardes\<projet>`. **Refuse un dossier situé dans le dépôt.**
- **Les volumes** sont retrouvés par leurs étiquettes Docker Compose (projet + nom court),
  pas par un nom deviné, puis lus par un conteneur jetable (`alpine:3.20`, `-Image` pour en
  changer ; téléchargé une fois s'il manque) qui les monte **en lecture seule** et écrit
  l'archive, les empreintes et les tailles.
- **À chaud ou à froid.** Si le Studio tourne, le script le dit et **demande** : arrêter le
  chat, les bacs à sable et le routeur le temps de la copie (recommandé : la base du chat
  est une base SQLite, qu'une copie au milieu d'une écriture peut rendre illisible), copier
  à chaud, ou quitter. `-Arret` et `-AChaud` répondent d'avance. S'il a arrêté, il
  redémarre à la fin, **même si la copie a échoué**. Le manifeste écrit `a-froid` ou
  `a-chaud`. Les deux veilleurs de l'hôte (mise à jour, sonde de la carte) continuent
  d'écrire leurs témoins dans `config/` ; ces fichiers se reposent d'eux-mêmes.
- **Contrôle après coup.** `config.tar` est relu : s'il contient un magasin de secrets, la
  pièce est retirée et le script s'arrête — on ne se fie pas au seul `--exclude`.
- **`-VersVps`** lit `VPS_HOTE`, `VPS_UTILISATEUR`, `VPS_DOSSIER` dans l'environnement de la
  session, sinon dans `.env`, refuse une valeur qui contiendrait un caractère inattendu, et
  n'en affiche aucune. Il crée `VPS_DOSSIER/studio-…` (droits `umask 077`), y copie par
  `scp` les pièces marquées VPS, le manifeste et un fichier `SHA256SUMS-vps`, puis **fait
  recalculer les empreintes par le VPS** (`sha256sum -c`). Une copie qui ne se vérifie pas
  là-bas est annoncée « NON vérifiée ». `ssh` tourne en `BatchMode` : la clé SSH doit être
  chargée dans `ssh-agent` (ou sans phrase), et l'hôte déjà connu — une première connexion à
  la main, une fois.
- **`-Garder N`** (ajouté le 26/09/2026) : rotation **locale** seulement. Sans lui, rien n'est
  supprimé ; le script dit combien d'anciennes sauvegardes du projet sont là et leur taille.
  Avec lui, il garde les N plus récentes, celle qu'il vient de faire comprise, et supprime
  les autres. N vaut au moins 2 : on ne supprime pas la précédente avant d'avoir restauré la
  nouvelle. Seuls comptent les dossiers `studio-AAAAMMJJ-HHMMSS` dont le manifeste porte le
  même projet. **Essayé le 26/09** sur des leurres : `-Garder 1` est refusé ; sans l'option,
  rien n'est supprimé ; `-Garder 2` a supprimé les trois anciennes du projet et laissé un
  autre projet, un dossier sans manifeste et un dossier au nom quelconque. Sur le VPS,
  aucune rotation.
- **À la fin**, il rappelle que la clé du coffre et `.env` ne sont pas dans la sauvegarde,
  et donne l'empreinte courte de la clé pour vérifier que celle du gestionnaire est la
  bonne.

### `scripts/restaurer.ps1`

```powershell
# essai, depuis une copie locale
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restaurer.ps1 -Archive <dossier studio-...>
# essai, depuis le VPS
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restaurer.ps1 -DepuisVps studio-AAAAMMJJ-HHMMSS
```

- **Par défaut, rien du Studio en service n'est touché.** La cible est un dossier d'essai
  à côté du dépôt (`<dépôt>-essai`, `-Cible` pour un autre), refusé s'il recouvre le dépôt,
  et deux volumes d'essai au nom de ce dossier (par défaut `<dépôt>-essai_open-webui-data`
  et `<dépôt>-essai_sandbox-data`) — exactement les noms que Docker Compose donnera quand on
  lancera `docker compose up` depuis ce dossier, ce qui permet d'y relancer le Studio. Deux
  essais dans deux dossiers ne partagent donc aucun volume. Si le dossier d'essai n'existe
  pas, il est créé par `git clone` du dépôt local (sans réseau) et remis à la version git
  de la sauvegarde.
- **Les empreintes d'abord.** Chaque pièce est comparée au manifeste (et le manifeste à
  `SHA256SUMS-vps` quand la copie vient du VPS). Une seule différence : **rien n'est écrit**.
  Une pièce absente (les magasins d'une copie VPS, par exemple) est dite, et le reste est
  restauré.
- **Rien n'est écrasé.** Un `config/` déjà présent dans le dossier d'essai, ou un volume
  cible qui existe et n'est pas vide, fait refuser la restauration ; supprimer reste un
  geste de la personne, et le script donne la commande. Le projet cible ne doit pas tourner.
- **La clé du coffre** est demandée en saisie masquée (ou `-FichierCle`, ou `-SansCle`),
  comparée à l'empreinte du manifeste — une clé différente fait tout refuser — puis posée
  dans `secrets/coffre.cle` du dossier d'essai. Elle n'est jamais affichée.
- **Chaque volume restauré est recomparé**, fichier par fichier, à la liste d'empreintes
  faite à la sauvegarde. Des écarts sont attendus pour une copie `a-chaud`, pas pour une
  copie `a-froid`.
- **À la fin**, il dit ce qui a été restauré, et ce qui manque : clé du coffre absente
  (« keys.json, sandbox-keys.json et la session NotebookLM sont restaurés mais
  illisibles »), pièces absentes, volumes qui n'existaient pas, et `.env`, qui n'est
  jamais dans une sauvegarde.
- **`-Reel`** vise le vrai `config/` et les vrais volumes, et fait taper `ECRASER`. Même
  alors : l'ancien `config/` est renommé `config.avant-restauration-…`, une clé déjà en place
  est renommée de même, et un vrai volume non vide fait refuser. C'est le geste du jour du
  sinistre, **pas celui de l'essai**.

### L'essai de restauration, pas à pas

À jouer par le propriétaire, avant le 31/10/2026. Compter une heure. Tout se lance depuis
le dossier du dépôt, dans Windows PowerShell.

1. **Avant.** Vérifier que la clé du coffre et le contenu de `.env` sont dans le
   gestionnaire de mots de passe. Noter trois témoins à retrouver après : le titre d'une
   conversation du chat, le nombre de travaux affichés par le bac à sable, et la dépense
   Modal du mois affichée par le Studio.
2. **Sauvegarder, à froid, avec la copie VPS.** Poser `VPS_HOTE`, `VPS_UTILISATEUR`,
   `VPS_DOSSIER` dans l'environnement de la session, puis
   `scripts\sauvegarder.ps1 -Arret -VersVps`. Noter le nom `studio-…`, la taille des
   pièces, et que la ligne VPS dit « copie et vérifiée ».
3. **Restaurer dans l'essai, deux fois.**
   - La copie locale complète, dans la cible par défaut :
     `scripts\restaurer.ps1 -Archive <dossier local studio-…>`. Coller la clé du coffre
     quand elle est demandée. Lire le compte rendu « Restauré / Manque ».
   - La copie hors site, rapatriée du VPS, dans une seconde cible :
     `scripts\restaurer.ps1 -DepuisVps studio-… -Cible ..\<dépôt>-essai-vps`. Tant que les
     questions A et B sont à « non », elle ne contient que `config.tar` et le manifeste :
     c'est **aussi** ce que l'essai doit montrer, noir sur blanc — ce qu'on retrouverait
     si le PC disparaissait.
4. **Relancer le Studio sur l'essai.** Les conteneurs portent des noms fixes : le vrai
   Studio doit d'abord céder la place. Dans le dossier du dépôt :
   `docker compose down` — **jamais avec `-v`**, qui effacerait les vrais volumes. Puis,
   dans le dossier d'essai `<dépôt>-essai` : y copier `.env` depuis le gestionnaire de mots
   de passe (le dossier d'essai n'en a pas), puis `scripts\remettre-cle-routeur.ps1` (la clé du routeur dans le chat, si la restauration l'a demandé), et `docker compose up -d --build` — sans `-p` :
   le nom du dossier donne le projet, donc les volumes d'essai. Ne **pas** lancer
   `demarrer.cmd` depuis l'essai : il relancerait les veilleurs de l'hôte sur ce dossier.
5. **Vérifier que le Studio relit tout.** Sur le chat (port 3000) : la conversation notée,
   et **une question envoyée qui reçoit une réponse** (c'est la clé interne du routeur qui se
   vérifie là, voir la question B). Sur la page du Studio : la page Clés montre les
   fournisseurs branchés — c'est la clé du coffre qui se vérifie. Sur le bac à sable : les
   travaux notés, et NotebookLM « branché ». La dépense Modal du mois : la même qu'avant.
   Ne lancer aucun calcul payant pendant l'essai.
6. **Le VPS lui-même.** Dans le panneau de l'hébergeur : la région du centre de données, et
   si une sauvegarde ou des instantanés du VPS sont actifs. Ce sont les réponses aux deux
   questions « non vérifié » du tableau du haut.
7. **Revenir.** Dans le dossier d'essai : `docker compose down`. Dans le
   dossier du dépôt : double-cliquer `demarrer.cmd`, et vérifier que la conversation notée
   est toujours là. Les volumes et dossiers d'essai restent ; les supprimer est un geste du
   propriétaire, une fois la preuve écrite.
8. **Écrire la preuve.** Modifier la ligne d'échéance en haut de ce document — la seule, ne
   pas en ajouter une seconde, la CI refuserait. Remplacer `etat: en-attente` par
   `etat: tenue | preuve: …`, par exemple :

   ```text
   etat: tenue | preuve: 2026-10-xx, sauvegarde studio-AAAAMMJJ-HHMMSS (a froid) rapatriee du VPS et restauree avec la copie locale dans le projet d'essai ; chat, cles, bac a sable et compteurs relus ; ecarts : ...
   ```

   Pas de `|` dans le texte de la preuve (c'est le séparateur des champs), pas de `-->`, et
   **aucune coordonnée du VPS** : ni nom, ni adresse, ni chemin. Écrire aussi, dans ce
   document, les réponses aux trois questions du tableau du haut et ce qui a raté. Un essai
   qui échoue s'écrit comme tel : il reste `en-attente`, avec ce qui a raté, et on le rejoue.
   Enfin, `python scripts/verifier-echeances.py` doit dire « tenue ».

## La clé du routeur hors des sauvegardes (proposée puis faite le 27/09/2026)

~~Rien n'est construit. Cette section attend l'accord du propriétaire.~~ **Voie (1) faite le
27/09/2026, à la demande du propriétaire** (« fais la correction (1) de la clé du routeur ») ;
ce qui a été fait, et en quoi il diffère de la proposition, est en fin de section.

### Ce qui est mesuré

- La base du chat (`webui.db`, table `config`) garde **quatre fois** la clé interne du routeur,
  en clair (question B, vérifié le 26/09). Open WebUI la recopie depuis `OPENAI_API_KEY` au
  premier démarrage, puis la relit dans sa base : c'est sa façon de garder un réglage.
- Cette clé ouvre, sur le routeur : le chat, les images, la transcription, la voix, `/status`,
  et `/boost/activate` (le mode payant plafonné d'OpenRouter).
- Ce qui borne le risque aujourd'hui, mesuré le 27/09 sur ce poste : le port 8010 n'écoute que
  sur `127.0.0.1` ; `OPENROUTER_MANAGEMENT_KEY` est vide, donc le Boost refuse de s'activer ;
  `ALLOW_PAID_MODELS=false`. Les clés des fournisseurs, elles, sont dans `keys.json`, fermées
  par le coffre : la clé du routeur ne les révèle pas.
- Sur ce poste, `.env` porte déjà la même clé en clair. La base n'ajoute donc **aucune**
  exposition **ici**. Elle en ajoute **dans chaque copie** : `open-webui-data.tar` est une
  sauvegarde de secret, et c'est ce qui bloque le VPS (question B).

### Ce que je propose : (1) la clé retirée de la copie, remise à la restauration

1. **`sauvegarder.ps1`** : après l'archive du volume du chat, un conteneur jetable ouvre la
   copie de `webui.db` **dans l'archive**, jamais la base vivante, et vide les quatre valeurs.
   Le manifeste le dit : `cle_du_routeur: retiree`. Le contrôle de la copie vérifie ensuite,
   par empreinte et sans rien afficher, qu'aucune valeur de 64 signes égale à
   `FREE_TIER_MANAGER_KEY` ne reste dans la copie.
2. **`restaurer.ps1`** : après la restauration du volume, il réécrit les quatre valeurs avec
   le `FREE_TIER_MANAGER_KEY` du `.env` de destination. Ce `.env` est déjà exigé :
   l'essai du 26/09 a montré qu'une restauration a besoin de cette clé, que la personne
   reprend dans son gestionnaire de mots de passe.
3. **Effet** : `open-webui-data.tar` ne porte plus de secret. Pour le VPS, la question B
   redevient une question de vie privée (les conversations), et non de clé.
4. **Preuve de clôture** : un test qui rougit sur l'état d'aujourd'hui (une archive dont la
   base porte la clé) ; puis l'essai réel sur une copie : sauvegarde, restauration dans le
   projet d'essai, une question posée au chat qui reçoit sa réponse.

### Les deux autres voies, et pourquoi je ne les propose pas en premier

- **(2) Changer la clé** (script de rotation : nouvelle valeur dans `.env`, puis les quatre
  valeurs de la base, puis la relance du routeur et du chat). C'est utile **si une copie a
  fui**, mais ne ferme rien : la copie suivante porterait la nouvelle clé. À écrire comme
  complément de (1), pas à la place.
- **(3) `ENABLE_PERSISTENT_CONFIG=false`** dans Open WebUI : les réglages ne viendraient
  plus de la base mais de l'environnement, à chaque démarrage. Rejeté : tout réglage changé
  depuis l'administration du chat serait perdu à chaque redémarrage. La table `config` compte
  352 lignes, et je n'ai pas mesuré combien ont été changées à la main.

### Ce que le propriétaire décide

~~Faire (1), avec ou sans (2). Ou garder l'état d'aujourd'hui, où la copie du chat reste une
sauvegarde de secret qui ne part pas sur le VPS.~~ Décidé le 27/09 : (1). La voie (2) reste
possible, elle n'est pas écrite.

### Ce qui a été fait (27/09/2026)

Deux écarts avec la proposition, trouvés en l'écrivant :
- **Nettoyer la copie AVANT l'archive, pas dans l'archive.** `<volume>.sha256.txt` est
  comparé à la restauration : modifier la base dans l'archive l'aurait rendue « non
  conforme ». Le volume du chat est donc copié dans un conteneur jetable (`/travail`), la clé
  y est retirée, puis l'archive **et** les deux listes sont faites sur cette copie.
- **Une marque, pas une valeur vide.** La clé est remplacée par
  `cle-du-routeur-retiree-par-la-sauvegarde`. Un chat restauré sans sa clé est alors refusé
  par son routeur, au lieu de parler à vide ; et la restauration sait exactement quoi
  remplacer.

Les pièces :
- `scripts/cle_routeur_chat.py`, deux verbes, `retirer` et `remettre`. La clé arrive par la
  variable `FAS_CLE_ROUTEUR`, passée au conteneur par son **nom** (`-e FAS_CLE_ROUTEUR`) et
  jamais par sa valeur. `retirer` travaille avec `secure_delete` et termine par un
  `wal_checkpoint(TRUNCATE)`. Il relit ensuite **chaque fichier** de la copie, octet par
  octet. S'il reste une trace dans la base, il la compacte (`VACUUM`) et relit ; s'il en reste
  une ailleurs, la sauvegarde s'arrête et l'archive commencée est retirée.
- `sauvegarder.ps1` : l'image est celle d'Open WebUI, lue dans `docker-compose.yml` (python et
  sqlite, déjà sur la machine). Le manifeste porte `cle_du_routeur` (`retiree`, `lignes`,
  `note`). Sans `FREE_TIER_MANAGER_KEY`, la copie se fait comme avant et le manifeste le dit.
- `restaurer.ps1` : la clé est remise depuis le `.env` **de la cible** quand il existe déjà.
  Sinon, le compte rendu donne la commande : `scripts\remettre-cle-routeur.ps1 -Cible <dossier>`
  (ou `-Reel`). Ce script ne remplace que la marque ; relancé, il ne change rien.
- `tests/test_cle_routeur_chat.py` : l'outil sur de vraies bases SQLite en WAL (rouge d'abord :
  une copie faite comme avant porte la clé et le contrôle la trouve ; une clé laissée hors de
  la base arrête la sauvegarde ; aucune trace dans une page libérée ; `remettre` pose la clé de
  la cible). S'y ajoutent les deux scripts relus comme du texte.

**Essai réel, 27/09 vers 04:25** : une sauvegarde à chaud dans un dossier à part, Studio en
service.
- « 4 ligne(s) » retirées. Relu sur l'hôte, octet par octet : la clé apparaît **0 fois** dans
  les 9 fichiers de la sauvegarde, la marque 4 fois dans `open-webui-data.tar`.
- La base vivante porte toujours ses 4 lignes : elle n'est pas touchée.
- Contre-épreuve : la sauvegarde du 26/09, faite par l'ancien script, porte la clé **4 fois**
  dans `open-webui-data.tar`.
- Restauration dans une cible neuve dont le `.env` ne contient qu'une clé de routeur **neuve**,
  tirée au hasard. Toutes les empreintes sont conformes, fichiers du volume compris. La clé a
  été remise automatiquement (« 4 ligne(s) »).
- La base restaurée : `integrity_check` = `ok`, 352 réglages, 24 conversations. Les quatre
  lignes portent la clé de la cible, aucune ne porte encore la marque.
- `remettre-cle-routeur.ps1` relancé : « aucune marque à remplacer », code 0.
- Dossier, sauvegarde et volumes de cet essai supprimés ensuite : ils contenaient une copie
  des conversations.

***Non vérifié*** :
- le chat restauré qui pose une question et reçoit sa réponse (Studio d'essai non relancé) ;
- le message « copiez .env, puis … » d'une restauration sans `.env` (texte relu, pas joué) ;
- ~~une copie à froid.~~ Faite le 27/09/2026 (section suivante).

## Copie à froid du 27/09/2026

Demandée par le propriétaire (« push puis copie à froid »). Avant de lancer : aucun travail
en cours dans le bac à sable (118 fiches `job.json` lues dans le conteneur : 95 réussies,
20 échouées, 3 annulées, aucune en cours).

Commande : `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sauvegarder.ps1 -Arret`,
sans `-VersVps`. Code de sortie 0. Relevé du résumé du script :

- archive `studio-20260927-101637`, manifeste **`a-froid`**, 8 pièces, 32 fichiers de `config/` ;
- `open-webui-data.tar` 1 130 035 200 octets, `sandbox-data.tar` 889 526 272 octets,
  `config.tar` 46 080, `config-magasins.tar` 29 696 ;
- clé du routeur retirée de la copie du chat : 4 lignes, comme mesuré le 26/09 ;
- Studio arrêté pendant la copie puis redémarré : sandbox-manager, manager, sandbox-worker et
  open-webui repassés **healthy** moins d'une minute après ; `voix` et `sandbox-worker-gpu`
  n'ont pas été arrêtés (leur durée de marche, 14 h et 9 h, n'a pas bougé).

***Non vérifié*** : la restauration de cette archive-ci (l'essai du 31/10 s'en chargera).
Constat : le script ne compte **aucune** sauvegarde plus ancienne dans
`%USERPROFILE%\Sauvegardes\free-ai-studio` ; celle du 26/09 n'y est plus (non recherché ailleurs).
