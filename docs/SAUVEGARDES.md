# Les sauvegardes — ce qui est décidé, ce qui ne l'est pas, et la date

Décision de l'utilisateur du 19/09/2026 : **les sauvegardes se font en local et sur le
VPS** (`docs/PLAN-PLATEFORME.md` §8, décision 15). Ce document porte cette décision, la
date qui la rend vérifiable, et l'endroit où la preuve s'écrira. **Il ne contient pas
encore de procédure** : elle s'écrit le jour où le premier essai se prépare, et elle
s'écrira contre des variables, jamais contre des valeurs (voir plus bas).

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

| Question | État |
|---|---|
| La troisième copie (disque externe ou espace en ligne) | **à décider** — local + VPS font déjà deux lieux ; quelques Mo par mois coûtent presque rien |
| Le VPS est-il lui-même sauvegardé ? | **non vérifié** — s'il meurt en portant la seule copie hors site, il n'en reste qu'une |
| Le VPS est-il en Europe, comme le plan l'exige ? | **non vérifié** |

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
variables et **aucune valeur**. La procédure à venir n'a qu'à s'y couler.
