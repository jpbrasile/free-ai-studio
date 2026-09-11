# Plan — Free AI Studio

Le seul fil de ce qui reste à faire, dans quel ordre, et de ce qui est gelé.
`AGENTS.md` dit **comment** travailler ; ce fichier dit **où on en est**.

Source : l'audit externe du 11/09/2026, copié tel quel dans
[`docs/audits/AUDIT-2026-09-11.md`](docs/audits/AUDIT-2026-09-11.md). Ce plan ne le
recopie pas : il dit ce qui en est fait, avec quelle preuve, ce que les sources
officielles ont contredit, et ce qui reste. Travail mené sur la branche
`audit-20260911`.

## Où en est le plan — 11/09/2026

| Tâche | État | Preuve | Ce qui manque |
|---|---|---|---|
| **P0-1** Quota Gemini, bascule annoncée | **fait ; critère vérifié en réel** | essai du 11/09 : 65 messages à `gemini-3.5-flash-lite`, aucun refus de Google, aucun recours à OpenRouter (§ P0-1) ; bascule vérifiée par `tests/test_quotas.py`, 8 tests | une **bascule réelle** (aucun refus en 65 messages) ; le rendu de l'avis dans Open WebUI ; les installations existantes gardent `gemini-3.8-flash` si leur `.env` le fixe |
| **P0-2** Modal : carte, crédit, plafond | **fait** | README, `.env.example`, page `/video`, `docs/MODAL_CATALOG.md`, `docs/SERVICES_DEBUTANT.md` ; nombre de clips recalculé avec la règle du code | le palier Modal ne peut pas être **détecté** (aucune API de crédit lue) : il est affiché comme une déclaration |
| **P0-3** « open source » / « gratuit » | **fait dans le dépôt** | README, section « Ce qui est ouvert, ce qui ne l'est pas » ; licence et territoire affichés à côté du choix sur `/video` ; règle de vocabulaire dans `AGENTS.md` | documents de présentation hors dépôt : non touchés |
| **P1-1** CI | **fait, critère vérifié en local** | une faute dans une copie de `video.py` fait échouer la CI (§ P1-1) | un premier passage réel sur GitHub Actions : rien n'est poussé |
| **P1-2** Kaggle | **fait** | `tests/test_kaggle.py`, 5 tests ; conditions de Kaggle lues | la politique d'usage soulève une question nouvelle (étape 4) |
| **P2** Périmètre | **commencé** | pastilles « expérimental » sur `/studio` (Voix, Vidéo, Étudier, Code, Sandbox) | parcours complet sur une machine vierge avec une vraie personne ; l'indicateur |
| **P2** Registre | **non commencé** | — | tout (étape 6) |
| Hors audit : **Free AI Max**, deuxième choix du chat | **fait dans le dépôt** | décision de l'utilisateur le 11/09 ; `gemini-3.8-flash` en tête, puis la chaîne d'Auto ; quota et pause à part ; `tests/test_quotas.py` (4 tests de plus, 17 au total) ; essai réel hors conteneur le 11/09 : `/v1/models` propose les deux choix, une demande Max servie par `gemini-3.8-flash`, une demande Auto par `gemini-3.5-flash-lite` | pas encore reconstruit ni vu dans Open WebUI ; bascule de Max vers Flash-Lite vérifiée seulement par les tests |
| Hors audit : `/studio` sans JavaScript | **corrigé** | `scripts/verifier-js.py`, ajouté à la CI | vue dans Chrome (service d'essai, 0 erreur console) ; conteneurs reconstruits depuis `dcc742d` |

Le dernier point a été trouvé en vérifiant P0-1. Depuis le commit `ed3e71d`, un `\n` mal échappé dans la chaîne Python de la page `/studio` cassait **tout** son script dans le navigateur. Les effets : état des clés absent, bouton « Mettre à jour » inerte, et le bandeau des quotas n'aurait jamais paru. Ni `py_compile`, ni ruff, ni le test d'import ne pouvaient le voir ; `node --check` le voit.

## Règles qui tiennent pendant tout le plan

- **Gel des fonctions.** Aucune nouvelle fonction tant que P0-1 et P0-2 ne sont pas vérifiés **en réel**. Aujourd'hui, ils ne sont vérifiés que hors réseau. Seule exception, levée par l'utilisateur le 11/09/2026 : Free AI Max. Sur les fiches de Google, Flash-Lite est nettement en dessous de 3.8 Flash (Terminal-bench 2.1 : 54,0 % contre 89,4 %), et les deux quotas sont distincts.
- P0 avant P1, P1 avant P2.
- Source officielle d'abord. Si elle contredit l'audit, elle gagne, et l'écart s'écrit ci-dessous.
- Rien de payant en secours, jamais. `ALLOW_PAID_MODELS=false` ne s'assouplit pas.
- Un « fait » cite sa preuve ; sans preuve, c'est « non vérifié ».

## Écarts entre l'audit et les sources officielles (relevé du 11/09/2026)

| L'audit dit | La source dit | Conséquence |
|---|---|---|
| Gemini Flash : 20 demandes par jour ; Flash-Lite : 500 | La [page des limites](https://ai.google.dev/gemini-api/docs/rate-limits) ne publie **aucun chiffre**. Elle renvoie à AI Studio et précise que les limites valent par projet et par modèle, avec une remise à zéro à minuit, heure du Pacifique. Le « 500 par jour » est la ligne « ancrage Google Search » de la [page des prix](https://ai.google.dev/gemini-api/docs/pricing). | Le défaut passe quand même à `gemini-3.5-flash-lite` : c'est la variante d'usage courant, gratuite et stable ([modèles](https://ai.google.dev/gemini-api/docs/models)). Aucun chiffre n'est codé en dur : le Studio lit la limite que Google écrit dans son refus. |
| Modal : 5 $ par mois sans carte, 30 $ avec | 30 $ par mois de crédit sur l'offre Starter ([pricing](https://modal.com/pricing)). Un moyen de paiement est **exigé** ([billing](https://modal.com/docs/guide/billing)). Aucun palier sans carte n'apparaît. Au-delà du crédit, Modal facture jusqu'à la limite de dépense, qui vaut par défaut la limite d'usage moins le crédit ([budgets](https://modal.com/docs/guide/budgets)). | La « cinquantaine de clips sans carte » est sans objet. Le plafond vidéo reste à 20 $. Le vrai risque est la facture au-delà du crédit : partout où « 30 $ » apparaît, la carte et la limite de dépense sont dites. |
| Critère P0-2 : le budget vidéo ne dépasse pas le crédit d'un compte sans carte | Un compte sans carte ne peut pas utiliser Modal | Critère appliqué sous cette forme : aucune page n'annonce 30 $ sans la carte, et le plafond (20 $) reste sous le crédit (30 $). |
| Kaggle : conditions à vérifier | [Conditions](https://www.kaggle.com/terms) du 22/06/2025 : usage personnel, jamais pour des tiers, compte non partageable. [Politique d'usage](https://www.kaggle.com/aup) : pas d'activité étrangère à la science des données. [CLI](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md) : `kernels push` est documenté. | La garde est confirmée par les conditions. La politique d'usage ouvre une question (étape 4). |
| Mode Découverte, Registry et scan Hugging Face ne se trouvent que dans `AGENTS.md` | Une recherche dans le dépôt, le 11/09, ne les trouve nulle part, pas même dans `AGENTS.md` | « Zéro ligne d'implémentation » tient. La mention dans `AGENTS.md` n'existe pas, ou plus. |

## Prochaines étapes, dans l'ordre

1. ~~**Vérifier P0-1 en réel.**~~ Fait le 11/09 : 65 messages sur 65 servis par Gemini (§ P0-1). Il reste à observer une **bascule réelle**. Elle viendra d'elle-même le jour où Google refusera ; ne pas brûler le quota d'OpenRouter pour la provoquer, cela n'apprend rien que les tests ne montrent déjà. Ce jour-là, relever la limite écrite par Google dans son refus et la reporter, datée, dans `docs/FREE_TIER_MANAGER.md`.
2. ~~**Reconstruire les conteneurs et regarder les pages**~~ **Fait le 11/09/2026.** Commit `dcc742d` sur `audit-20260911`, puis `docker compose up -d --build` : les 4 conteneurs sont en bonne santé. Contrôles sur les conteneurs reconstruits :
   - le routeur annonce la version `dcc742d` ;
   - le bloc `quotas` est présent dans `/diagnostic/etat` ;
   - Gemini (`gemini-3.5-flash-lite`), OpenRouter et Groq sont éligibles ;
   - la garde Kaggle dit permis depuis localhost et coupé par 192.168.1.20 ;
   - une demande de chat : HTTP 200, servie par Gemini, `x-free-ai-secours: non`.

   Les pages ont été vues dans Chrome sur le service d'essai hors conteneur, avec le même code. **Reste non vérifié** : une vraie bascule, et son avis tel qu'Open WebUI l'affiche.
3. **Pousser la branche** et lire le premier passage de GitHub Actions.
4. **Kaggle et la politique d'usage : décision humaine.** Même sur la machine de la personne, le mode `auto` peut envoyer sur Kaggle un code quelconque. Trois choix :
   - (a) laisser tel quel, avec l'avertissement de `docs/GPU_CLOUD.md` ;
   - (b) ne proposer Kaggle en `auto` qu'aux jobs `gpu=true` ;
   - (c) retirer Kaggle du mode `auto` et ne garder que le lien manuel.

   Recommandation : (b). Le coût est faible, et un job GPU relève presque toujours du calcul d'apprentissage.
5. **P2 : verrouiller Chat, Recherche et Image** sur une machine vierge, avec une personne qui n'a jamais ouvert un terminal.
   - Écrire le protocole avant la séance : une liste fixe de tâches (installer, coller la clé, poser une question, chercher sur le Web, fabriquer une image, ouvrir le diagnostic), et pour chacune une case « menée à terme sans aide ».
   - Indicateur : le pourcentage de tâches menées à terme, à la place de la taille du catalogue.
   - Aucune nouvelle fonction avant un premier chiffre.
6. **P2 : le registre**, après l'étape 5.
   1. `registry/apps.yaml`, une entrée par application : `id`, `fonction`, `modele`, `licence`, `territoire`, `vram_min_go`, `modes` (`api`, `local`, `modal`, `kaggle`, `colab`), `cout_estime`, `source`, `verifie_le`.
   2. `registry/apps.schema.json` (JSON Schema), validé en CI. Outil candidat : [`check-jsonschema`](https://pypi.org/project/check-jsonschema/) 0.38.0 (09/08/2026), qui existe en ligne de commande et en hook pre-commit. Sa page ne dit pas s'il lit le YAML : à vérifier avant de l'adopter. À défaut, vingt lignes de Python avec `jsonschema` et `pyyaml`.
   3. Faire lire le registre par `free-tier-manager` (`PROVIDERS`, `LIMITES_PUBLIEES`) et par `sandbox-manager` (`video.MODELES`). Aujourd'hui ces données sont en dur, et le tableau du README en est une troisième copie.
   4. Seulement ensuite, un job qui propose des candidats par PR, avec validation humaine.
7. **Dette relevée en passant, hors audit.** `@app.on_event("startup")` est déprécié par FastAPI (avertissements des tests). Passer à `lifespan` au prochain changement du démarrage.

## Détail par tâche

### P0-1 — Le chat ne se dégrade plus en silence

- **Code** (`free-tier-manager/app.py`) :
  - défaut `gemini-3.5-flash-lite` ; le modèle haut de gamme `gemini-3.8-flash` reste accessible par `GEMINI_FREE_MODEL` ;
  - `lire_quota()` lit un refus 429 de l'une ou l'autre forme (documentée ou réelle) ;
  - un quota du jour met Gemini en pause jusqu'à minuit, heure du Pacifique ; une limite par minute, de 5 s à 5 min ;
  - la première réponse du secours commence par une ligne d'avis ;
  - `GET /quotas/etat` ; bloc « quotas » dans `/diagnostic/etat` ; bandeau et liste sur `/studio` ;
  - un `429` explicite quand **tous** les services sont en pause.
- **Docs** : `docs/FREE_TIER_MANAGER.md` (tableau des limites, avec date et sources), `README.md`, `.env.example`.
- **Vérifié hors réseau** : `tests/test_quotas.py`. Les fournisseurs y sont simulés, avec un refus au format réel et un au format documenté.
- **Vérifié en réel le 11/09/2026.** Le nouveau routeur a été lancé hors conteneur, sur un port d'essai. Conditions : la clé Gemini gratuite du `.env`, un dossier de configuration neuf, et `GEMINI_FREE_MODEL` retiré pour simuler une installation neuve. Déroulé :
  - 25 messages espacés de 4,5 s, puis 40 en rafale, à environ 0,8 s par message ;
  - **65 réponses sur 65 servies par `gemini-3.5-flash-lite`** : aucun refus, aucun recours à OpenRouter ;
  - `/quotas/etat` compte 65 réponses servies et aucune pause.

  Le critère d'acceptation (« plus de 20 échanges sans dégradation silencieuse ») est donc tenu sans bascule. Faute de refus, la bascule elle-même n'a pas pu être observée en réel.
- **Installations existantes.** Un `.env` créé avant le 11/09 peut contenir `GEMINI_FREE_MODEL=gemini-3.8-flash`, qui prime sur le défaut du code. C'est le cas sur la machine de l'essai. Pour passer à Flash-Lite, supprimer la ligne ou la remplacer par `gemini-3.5-flash-lite`. Le Studio ne réécrit jamais `.env`.
- **Pages rendues dans Chrome** (même service d'essai, après les 65 demandes). Sur `/studio`, le bloc « Services gratuits » affiche Gemini (`gemini-3.5-flash-lite`) « disponible, 65 réponse(s) servie(s) aujourd'hui » et OpenRouter à 0. Chaque ligne porte sa limite publiée, et les pastilles « expérimental » sont présentes. Sur `/diagnostic`, une ligne par service. Aucune erreur dans la console sur les deux pages. Groq n'apparaissait pas : `ENABLE_GROQ=false` dans le `.env`, donc le service n'était pas éligible. À la demande de l'utilisateur, `.env` a ensuite été remis sur le plan de `.env.example` et Groq activé, le 11/09. La clé Groq est acceptée (GET `/openai/v1/models`, HTTP 200), et `openai/gpt-oss-20b` figure dans la liste. Ce changement ne prend effet qu'à la recréation des conteneurs. Or `/diagnostic` le liste quand même parmi les services « branchés » ; ce décalage existait avant.
- **Non vérifié** : la vraie limite du jour de Google, et le rendu de l'avis dans Open WebUI.

### P0-2 — Modal : la carte bancaire est dite partout

- **Fichiers** : `README.md`, `.env.example`, `sandbox-manager/video.py`, `docs/MODAL_CATALOG.md`, `docs/SERVICES_DEBUTANT.md`, et les cartes Vidéo et d'accueil de `/studio`.
- **Page `/video`** :
  - crédit « déclaré (`MODAL_CREDIT_MENSUEL_USD`), non vérifié chez Modal » ;
  - lien vers le réglage de la limite de dépense ;
  - option « Modal — machine louée (carte bancaire exigée) ».
- **Clips** : au coût mesuré le 09/09 (0,096 $), 30 $ paieraient 312 clips. Le plafond de 20 $ en laisse passer **203**, parce que chaque clip doit encore tenir son pire cas (0,53 $). Ces nombres sont calculés en appliquant la règle de `budget_verifier`, pas estimés.

### P0-3 — Ce qui est ouvert, ce qui ne l'est pas

- Tableau du README : fonction, fournisseur, nature, licence. Licences relevées sur les fiches officielles : gpt-oss-20b et Wan 2.1 VACE sous Apache 2.0, Whisper sous MIT.
- `/video` affiche la licence et le territoire du modèle **à côté du choix de qualité**.
- « open source » est remplacé là où il voulait dire « gratuit » : `scripts/configure-beginner.*`, `docs/API_KEYS.md`, `AGENTS.md`. Il reste là où il est juste : Hugging Face dans `docs/SERVICES_DEBUTANT.md`, et une URL.

### P1-1 — La CI voit tout le Python, et le JavaScript des pages

La CI (`.github/workflows/validate.yml`) enchaîne :
1. la compilation de tous les `.py` suivis ;
2. `ruff check` (`ruff.toml` : règles E9 et F) ;
3. `scripts/verifier-imports.py` ;
4. `scripts/verifier-js.py` ;
5. `pytest tests` ;
6. puis, comme avant, Bash, les interdits du mode gratuit et Compose.

Preuve du critère : les fichiers du dépôt sont copiés (jamais `.env`), une faute est introduite dans la **copie** de `sandbox-manager/video.py`, puis les étapes Python sont rejouées.

| Cas | compilation | ruff | imports | tests | CI |
|---|---|---|---|---|---|
| nom mal écrit dans une fonction (`prix_secnde`) | passe | **échoue** (F821) | passe | passe | **échoue** |
| deux-points oublié | **échoue** | **échoue** | **échoue** | **échoue** | **échoue** |
| sans faute (témoin) | passe | passe | passe | passe | passe |

Le premier cas montre pourquoi la compilation ne suffisait pas : sans ruff, cette faute serait passée.

### P1-2 — Kaggle automatique : vos identifiants, votre machine

`contexte_partage()` dans `sandbox-manager/app.py` coupe Kaggle automatique dans quatre cas :
- `STUDIO_HEBERGE=true` ;
- `WEBUI_AUTH=true` ;
- la page est ouverte par une autre adresse que localhost ;
- la requête passe par un proxy.

Effets de la coupure :
- `POST /jobs` avec Kaggle, `/video/creer` vers Kaggle et `/cles/tester` pour Kaggle répondent 403, avec le lien manuel ;
- le mode `auto` saute Kaggle ;
- `/etat` et `/providers` donnent la raison.

Documenté dans `docs/GPU_CLOUD.md`, `docs/SANDBOX.md` et `AGENTS.md`. Vérifié par `tests/test_kaggle.py`.

**Vérifié en réel le 11/09/2026** : service lancé hors conteneur sur 127.0.0.1:8120, interrogé avec curl.
- `/etat` depuis localhost : `automatique_permis` vaut true, sans raison.
- Même requête avec l'en-tête `Host: 192.168.1.20:8120` : false, raison « page ouverte par l'adresse 192.168.1.20, pas par localhost ».
- Avec `X-Forwarded-For` : false, raison « requete relayee par un proxy ».
- Par 192.168.1.20 :
  - `POST /jobs` (kaggle), `POST /video/creer` (kaggle) et `POST /cles/tester` (kaggle) donnent tous **403**, avec le lien `https://www.kaggle.com/code` ;
  - `/cles/etat` porte `coupe` avec la même raison.

`/cles/tester` refuse avant tout appel réseau : aucune requête n'est partie vers Kaggle.

## Vérifications locales du 11/09/2026

Machine : ce PC sous Windows 11 Pro (10.0.26200), avec un venv Python **3.11.5** (la CI utilise 3.12), ruff 0.16.7, pytest 9.1.1 et Node 24.14.1.

```text
ruff check .                       All checks passed!
compilation de tous les .py        exit 0
python scripts/verifier-imports.py 3 services chargés
python scripts/verifier-js.py      9 scripts, 0 en échec (avant correction : /studio en échec)
python -m pytest -q tests          13 passed
docker compose --env-file .env.example config   exit 0 (sortie jetée : elle résout les variables)
```

**Essais réels, hors conteneur.** Les deux services ont été lancés depuis le dépôt sur 127.0.0.1:8110 et :8120. Les clés venaient de l'environnement ; aucun `keys.json` n'a été copié. Chaque service avait un dossier de configuration neuf, Open WebUI n'était pas joignable, et Modal comme Kaggle étaient coupés.
- **Fournisseurs** : 65 appels à Gemini, aucun à OpenRouter ni à Groq.
- **Pages rendues dans Chrome** : `/studio`, `/diagnostic`, `/video`, `/cles` et `/` du Sandbox. Aucune erreur dans la console, chaque page ayant été rechargée une fois le suivi de la console actif.
  - `/video` : option « Modal — machine louée (carte bancaire exigée) » ; ligne « licence Apache 2.0, aucune restriction de pays » ; crédit « déclaré (`MODAL_CREDIT_MENSUEL_USD`), non vérifié chez Modal ».
  - `/cles` : la carte Kaggle dit « Pilotage automatique réservé à votre machine ».
- **Non vérifié à l'écran** : la carte Kaggle grisée, et l'option Kaggle désactivée, quand le contexte est partagé. Le navigateur ne peut pas se présenter sous une autre adresse que localhost. Ce cas n'a été vérifié qu'au niveau de l'API (voir P1-2).

Les deux services d'essai ont été arrêtés après les mesures. Les conteneurs ont ensuite été reconstruits depuis `dcc742d`, à la demande de l'utilisateur (voir « Prochaines étapes », point 2). **Pas lancé** : aucun push.
