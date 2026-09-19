# PLAN-PLATEFORME.md — où va Free AI Studio

> **Ce que ce document est.** Le plan de plateforme, adapté à l'état réel du dépôt. Il ne
> remplace pas `PLAN.md` : le journal dit *ce qui s'est passé*, celui-ci dit *où va le
> projet*. Il confronte un plan stratégique écrit hors du dépôt (« Free SOTA Capability
> Platform (MVP) », en anglais, cité en annexe) à ce que le dépôt contient vraiment.
>
> **Branche `audit-20260911`, relevé sur `edb2b56` (18/09/2026), mesures du 19/09/2026.**
>
> **Sur `main`.** `git rev-list --left-right --count main...HEAD` donne **0 / 41**, et
> `git merge-base --is-ancestor main HEAD` réussit : **`main` est un ancêtre de cette
> branche.** Une fusion serait donc une avance directe, sans conflit possible. Cela veut
> dire que **`main` est en retard de 41 commits, pas qu'il ignore tout** : la licence MIT,
> `AGENTS.md`, `modal/profiles.json`, `notebooks/SOTA_LINKS.md`, le durcissement du bac à
> sable et le stockage des clés en clair y sont **déjà**. Ce qui manque à `main`, ce sont
> les 41 commits du 11 au 18/09 — la chanson, le dialogue, les dépenses, et huit des
> treize fichiers de test. La colonne « sur `main` » du §1 dit, ligne par ligne, laquelle
> des deux situations s'applique.
>
> **Un compte qui bouge, dit comme tel.** Les deux nombres ci-dessus sont relevés sur
> `edb2b56`. **L'avance sur `main` croît à chaque commit de cette branche** — elle était
> de 41 le 18/09 et de 45 le 19/09 au soir. **Ce qui ne bouge pas, et qui est le fait
> utile, c'est le 0 de gauche** : `main` reste un ancêtre, la fusion reste une avance
> directe. Un lecteur qui rejoue la commande aujourd'hui obtiendra un autre nombre à
> droite : ce n'est pas une contradiction, c'est la raison d'être du contrôle de fraîcheur
> retenu au §8, point 13.
>
> **Convention, reprise de `PLAN.md:35`** : « Un “fait” cite sa preuve ; sans preuve, c'est
> “non vérifié”. » Chaque nombre entre avec son instrument, jamais nu. Chaque section finit
> par une décision à prendre.
>
> **Où s'écrivent les réponses.** Les décisions demandées ici se consignent dans `PLAN.md`,
> datées, selon la convention du journal (rien ne s'efface ; une position dépassée se
> barre). Ce document est ensuite mis à jour et la date de son relevé change.

---

## Le cap, avant tout le reste

**briques → composites → flux payants → flux d'apprentissage.**

Un *composite* est une chaîne de briques désignées par leur **fonction** et non par un nom
de modèle : « la voix », pas « Piper 1.8.0 ». C'est pourquoi le registre (§5, étape 1)
n'éloigne pas de l'apprentissage — il en est la première brique. Sans un endroit qui dise
« la fonction *voix* est tenue aujourd'hui par tel candidat », aucune chaîne ne peut se
décrire autrement qu'en recopiant des noms de modèles qui changeront.

Ces étapes portent **un ordre et des conditions d'entrée, jamais un mois inventé**. Écrire
« flux payants en janvier » serait un nombre fabriqué de la même famille que ceux que le
dépôt refuse partout ailleurs.

**Une correction à écrire noir sur blanc** : le dépôt n'a pas écarté le flux
d'apprentissage. Il a décidé de **ne pas reconstruire NotebookLM** et de renvoyer vers
celui de Google (`docs/NOTEBOOKLM.md` ; route `/notebooklm`,
`free-tier-manager/app.py:2824` ; le bouton envoie sur `https://notebooklm.google.com/`,
`:2846`). Ne pas refaire un produit existant est une décision de moyens ; abandonner
l'apprentissage serait une décision de cap. Seule la première a été prise.

---

## §1 — L'état, avec preuves

Une seule grille pour le socle, les phases P0→P9 du plan d'origine et ses règles dures.
Elle ne recopie que ce qui n'est écrit nulle part ailleurs ; pour le reste elle pointe la
preuve. Sans cette règle, ce tableau deviendrait lui-même une copie de plus de la vérité —
la maladie diagnostiquée au §5.

Verdicts : **fait** · **partiel** · **contredit** (le réel dit l'inverse) · **écarté par
décision** · **à faire**.

### Le socle qui existe

| Affirmation | État réel | Preuve (relevé le 19/09/2026) | Verdict | Sur `main` |
|---|---|---|---|---|
| Une application utilisable existe | 4 services Docker Compose et **onze pages** — 5 servies par le routeur, 6 par le bac à sable (`grep -c "response_class=HTMLResponse"` sur les deux `app.py`) | `docker-compose.yml` | fait | les services oui ; deux pages sur onze (chanson, dialogue) non |
| Elle couvre neuf fonctions | chat, image, recherche web, dictée, voix, dessins SVG, vidéo, chanson, dialogue. **Aucun fichier du dépôt ne porte cette liste** : elle est reconstituée à la main, page par page | `free-tier-manager/app.py`, `sandbox-manager/app.py` | fait, **mais non dénombré par le dépôt** — c'est déjà un symptôme du §5 | sept sur neuf |
| Elle est testée | **209** fonctions `def test_` dans **12** fichiers portant des tests (`tests/*.py` en compte 13, `conftest.py` n'en porte aucune) — `grep -rh "def test_" tests/*.py \| wc -l`, 19/09. Le journal écrit « **214 tests passent** » au 18/09 (`PLAN.md:315`) : c'est le compte **collecté** par pytest, reproduit le 19/09 par `pytest --collect-only -q`. Deux instruments, deux nombres justes | `tests/` | fait | **non** : `main` ne porte que 5 fichiers de test sur 13 |
| Une CI la vérifie | **9 étapes nommées** (`grep -c "^      - name:" .github/workflows/validate.yml`), plus **trois** actions sans nom (`checkout`, `setup-python`, `setup-node`, l. 11, 14, 49). Déclencheurs : `push` et `pull_request`, sans filtre de chemin | `.github/workflows/validate.yml` | fait | oui |
| Un bac à sable isole le code étranger | `read_only`, `cap_drop: ALL`, `no-new-privileges`, `pids_limit: 128`, `mem_limit: 1g`, réseau `sandbox-internal` déclaré `internal: true` (`docker-compose.yml:211-213`) : **aucune sortie réseau** | `docker-compose.yml` | fait | **oui, déjà sur `main`** |

### Les phases du plan d'origine

| Phase | État réel | Preuve | Verdict | Sur `main` |
|---|---|---|---|---|
| **P0** Setup (VPS EU, Postgres, Forgejo+CI, sauvegardes, arrêt d'urgence) | **Rien dans ce dépôt** — et c'était la seule lecture d'une version antérieure de ce document. **Mais l'utilisateur possède déjà un VPS qui tourne**, avec Docker, Coolify, un **PostgreSQL** (Supabase auto-hébergé) et nginx, relevé le 19/09 dans les procédures d'un autre projet. **Il n'est simplement relié à rien ici.** L'arrêt d'urgence, lui, existe mais **par travail**, pas global : `POST /jobs/{jid}/arreter` | `sandbox-manager/app.py:1598` ; pour le VPS : `agentic-flow-fresh/.claude/skills/vps-claude/SKILL.md`, `pv-supabase/SKILL.md` | **partiel, et bien plus avancé qu'il n'y paraît** : le matériel de P0 existe, l'arrêt d'urgence ne répond pas à « Kill switch must stop **all** pipelines », et **la localisation européenne du VPS reste non vérifiée** alors que le plan l'exige | non |
| **P1** Registry + Scan | `registry/` et `scan/` n'existent pas. Aucun schéma, aucune graine, aucune source de balayage | relevé de racine, 19/09 | à faire | — |
| **P2** Gateway | La passerelle existe : chaîne `gemini → openrouter → groq`, bascule annoncée et non silencieuse, pause jusqu'à minuit Pacifique. Ce qui manque : elle **ne lit aucun registre**, et elle **ne compte rien d'avance** | `free-tier-manager/app.py:52` (`PROVIDERS`), `:141` (`LIMITES_PUBLIEES`), `:618` (`apply_rate_limit_cooldown`) | partiel — **et sur un point le réel réfute le plan** (ci-dessous) | en partie |
| **P3** Runners | Quatre endroits d'exécution réels, dans cet ordre : `modal → local → kaggle → colab` (`sandbox-manager/app.py:879`, `:1451`). Pas de `llama.cpp`, **pas un seul LLM auto-hébergé** | `sandbox-manager/` | partiel | en partie |
| **P4** Integrate + Evals + Gates | `integrate/`, `evals/`, `gates/` absents. Mais des barrières existent déjà comme code, sous d'autres noms : `budget_verifier` refuse **avant** de lancer, sur le pire cas, hors ligne (`video.py:187`, `chanson.py:203`, `dialogue.py:380`) ; `contexte_partage()` coupe Kaggle dès que le contexte devient partagé (`sandbox-manager/app.py:73`) ; `exiger_page_du_studio` ferme les routes sensibles côté serveur (`free-tier-manager/app.py:1820`, `sandbox-manager/app.py:159`) ; le chat refuse tout nom de modèle par un 403 **en configuration par défaut** (`:3521-3526`, sous `if FREE_ONLY or not ALLOW_PAID` — `FREE_ONLY` vaut `true` et `ALLOW_PAID_MODELS` `false` par défaut, `:29-30`) | voir colonne | **partiel sur les barrières, absent sur les évaluations** | en partie |
| **P5** Expérience (20–30 candidats, zéro geste humain) | Jamais lancée. Aucun taux d'autonomie n'a jamais été mesuré | — | à faire | — |
| **P6** Studio (« after P5 success ») | **Existe et tourne. C'est le seul livrable du plan qui existe** | tout le dépôt | **fait, hors séquence** | en partie |
| **P7** Contributions | Rien. `CONTRIBUTING.md` existe mais ne décrit aucune soumission d'évaluation | `CONTRIBUTING.md` | à faire | — |
| **P8** Flux payants | `flows/`, `queue/`, `billing/`, `compliance/` absents. Mais des fonctions payantes existent déjà (§2.6) | relevé de racine | à faire, et déjà contredit sur son préalable | — |
| **P9** Flux d'apprentissage | Le dépôt a décidé de ne pas reconstruire NotebookLM et de renvoyer vers Google. **Il n'a pas écarté l'apprentissage** | `docs/NOTEBOOKLM.md` ; `free-tier-manager/app.py:2824` | partiellement écarté par décision (la reconstruction, pas le cap) | oui |

**Le plan d'origine nomme dix-sept répertoires** (`Downloads\PLAN.md:47-59`, `:127`,
`:131-136`). **Seize sont absents.** Le seul qui existe est `sandbox/` — et `studio/`, que
le plan prévoit en phase 4, n'existe pas comme répertoire parce que le Studio *est* le
dépôt entier. Le journal l'écrivait déjà le 11/09 : « zéro ligne d'implémentation »
(`PLAN.md:45`).

**L'ordre est donc inversé dans les faits : le livrable que le plan conditionne à la
réussite de P5 est le seul qui existe.** C'est le point de départ de tout ce document.

### Deux constats qui méritent plus qu'une case

**P2 — le réel réfute le plan, et le remplacement a un prix.** Le plan veut un compteur
RPM/RPD/TPM/TPD nourri par le registre. Le dépôt ne compte rien d'avance : il lit la limite
dans le refus 429 du fournisseur. Ce n'est pas de la paresse — la page des limites de
Google **ne publie aucun chiffre** (`PLAN.md:41`), et un compteur codé en dur y serait un
nombre inventé. **Mais le prix est réel** : lire la limite *dans* le refus, c'est la
connaître **après** avoir été refusé. Le plan voulait éviter le refus ; le dépôt le subit
puis l'annonce proprement. Les deux approches ont un coût, et le choix du dépôt est le bon
seulement là où le fournisseur ne publie rien.

**P9 — l'ironie à noter.** La brique « audio overview » de P9 a bel et bien été
construite : c'est le dialogue à plusieurs voix (FireRedTTS-2), entré par la douzième
exception au gel (`PLAN.md:184`), sans passer par P9 ni par aucun registre. Le plan
prévoyait cette brique à la fin d'une chaîne de neuf phases ; elle est arrivée par une
demande d'utilisateur, un jeudi.

> **Décision demandée.** Ce tableau devient-il la référence d'état du projet — donc relu à
> chaque étape franchie — ou reste-t-il une photographie datée du 19/09/2026 ? Sans
> réponse, il vieillira en silence et deviendra une septième copie de la vérité (§5).
> *Recommandation : référence, avec obligation de citer la date du relevé à chaque ligne
> modifiée.*

---

## §2 — Les contradictions vivantes

Sept. Toutes rouvertes une à une le 19/09/2026 avant d'être écrites : accuser le plan
d'origine à tort serait le même défaut que de le recopier sans le lire.

### 1. Les clés — le dépôt viole sa propre règle, et un autre fichier lui ordonne de la violer

Le plan (règle dure, l. 24) : « Never store, proxy or share user API keys. Keys live
client-side only, **encrypted**. »

Le dépôt les écrit **en clair**. `KEYS_FILE = CONFIG_DIR / "keys.json"`
(`free-tier-manager/app.py:91-92`), écriture atomique par fichier temporaire puis
`tmp.replace(KEYS_FILE)` (`:356-359`), monté par le volume `./config:/config`.

**Aucun chiffrement au repos nulle part.** La recherche de `Fernet`, `cryptography` et
`encrypt` dans tout le dépôt renvoie **trois** occurrences, toutes en PowerShell et aucune
sur les clés : deux tirages d'aléa (`install.ps1:27`, `scripts/demarrer.ps1:331`) et un
calcul d'empreinte SHA-1 (`scripts/maj-veilleuse.ps1:44`).

Et `AGENTS.md:77` **ordonne l'inverse de la règle** : « stocker les secrets uniquement côté
serveur ».

**La nuance honnête**, et elle compte : ici « serveur » est le PC de l'utilisateur, lié à
`127.0.0.1`. Tant que c'est vrai, l'écart est théorique. Mais `STUDIO_HEBERGE` existe déjà
(`docker-compose.yml:73`, `.env.example:333`) : le jour où cette variable passe à `true`,
la règle est violée au sens plein **sans qu'une seule ligne de code ne change**.

*Rectification d'une version antérieure de ce document : j'avais écrit que cette règle
était « tenue par construction ». C'est faux.*

**Deux mesures du 19/09 rendent le remède plus nécessaire, et moins simple qu'il n'y
paraît.**

**Un : `free-tier-manager` ne lit jamais `STUDIO_HEBERGE`.** La recherche de `HEBERGE` dans
tout `free-tier-manager/` ne renvoie **aucune ligne**. La variable parvient pourtant au
service — il la reçoit par `env_file: .env` (`docker-compose.yml:131-132`, et
`.env.example:333` la pose à `false`) — mais **aucune ligne ne la consulte**. Le seul
service qui la lit est `sandbox-manager` (`app.py:67`), pour couper Kaggle automatique.
**Le drapeau qui déclare « cette instance est hébergée » est donc invisible au service qui
écrit les clés en clair** : le jour où il passe à `true`, le bac à sable réagit et le
stockage des clés ne bronche pas.

**Deux : le drapeau est une déclaration, pas une détection** — et c'est le code lui-même
qui l'écrit (`sandbox-manager/app.py:65-66`) : « *Ces signes sont des indices, pas une
preuve : une instance exposee par un moyen qui n'en laisse aucun doit etre declaree avec
STUDIO_HEBERGE=true.* » Une instance exposée **sans** avoir été déclarée n'est donc
protégée par rien.

> **Décision.** Trois options — et elles ne sont pas de même rang. C'est le classement qui
> est la décision, pas le choix entre elles.
>
> **(c) Le refus au démarrage — d'abord.** Faire de `STUDIO_HEBERGE=true` un mode qui
> **refuse de démarrer** tant que les clés ne sont pas protégées. C'est le patron que le
> dépôt applique déjà partout : `budget_verifier` refuse avant de dépenser, `preparer()`
> refuse LoRA+T4 « au lieu de parier », `exiger_page_du_studio` refuse côté serveur.
> **Coût réel : deux changements, pas un** — faire lire le drapeau par
> `free-tier-manager`, puis refuser. Et une troisième ligne utile, puisque le drapeau est
> déclaratif : refuser aussi lorsque le service n'est **pas** lié à `127.0.0.1`, car cette
> condition-là, elle, **se constate** au lieu de se déclarer.
>
> **(a) Chiffrer `keys.json` au repos — utile, pas urgent, et à son vrai rang.** Sur une
> machine mono-utilisateur, la clé de déchiffrement vit sur la même machine, lisible par le
> même processus : le chiffrement ne défend qu'un seul cas, **le fichier qui s'échappe sans
> sa machine** — sauvegarde égarée, dossier de support, disque revendu. Ce cas est réel et
> mérite d'être traité ; il n'est simplement pas celui qui justifierait de retenir le
> reste. **Il ne conditionne pas (c)** : mieux vaut un refus qui marche sans chiffrement
> qu'un chiffrement sans refus.
>
> **(b) Écrire la raison dans `AGENTS.md` — dans tous les cas.** Quelle que soit l'issue
> des deux autres, `AGENTS.md:77` ne peut pas continuer d'**ordonner le contraire** de la
> règle du plan. Ce point ne dépend d'aucune décision technique.
>
> **Ce qui borne le risque d'aujourd'hui, mesuré le 19/09** : `config/` est dans
> `.gitignore` et **non suivi** — `git ls-files config/` ne rend aucune ligne, donc
> **aucune clé n'a jamais été commitée** — et les trois ports sont liés à `127.0.0.1`
> (`docker-compose.yml:110`, `:134`, `:162`). Les seules clés en jeu sont celles de
> l'utilisateur, sur sa machine. **Cela borne l'urgence ; cela ne referme pas le chemin.**

### 2. Windows — ici, c'est le dépôt qui a raison contre le plan

Le plan (l. 146, hors périmètre) : « Windows (Colab CLI unsupported) ».

Le dépôt vise Windows en premier et porte **906 lignes** de PowerShell et CMD sur 9
fichiers suivis (`git ls-files '*.ps1' '*.cmd' | xargs wc -l`, 19/09) — dont
`scripts/demarrer.ps1` à lui seul, 533 lignes.

Et le motif du plan est une erreur de raisonnement : il exclut une *plateforme* à cause
d'une limite d'*outil*. Le dépôt a résolu le problème sans jamais toucher au CLI Colab, par
un carnet cliquable et un passage de main.

> **Décision.** Cette ligne du plan d'origine est morte. Elle se raye, elle ne se discute
> pas.

### 3. Licences — trois écarts, et le plus grave n'est pas celui qu'on croit

Le plan (l. 28) : « Only ungated, permissively licensed resources in MVP
(Apache-2.0/MIT/BSD). »

| Ressource | Licence | Preuve | Gravité |
|---|---|---|---|
| YuE2-3B (chanson) | **CC BY-NC 4.0** (poids) ; code Apache 2.0 | `sandbox-manager/chanson.py:96`, `:99` | tourne à distance, sur commande |
| LoRA instrumentale | **CC BY-NC 4.0**, et **`"revision": None`** | `chanson.py:126-133` | non épinglée : le dépôt source peut changer sous les pieds |
| **Piper** | **GPL-3.0-or-later** — *selon `PLAN.md:147` ; non vérifié contre les métadonnées du paquet* | importé **dans le processus** : `from piper import PiperVoice, …` (`free-tier-manager/app.py:1470`) ; version `piper-tts==1.8.0` (`requirements.txt:13`) | **la plus grave** |

**Piper passe devant YuE.** YuE tourne à distance, sur demande explicite, dans un travail
séparé. Piper est embarqué comme bibliothèque **dans le processus du routeur**, d'un dépôt
publié sous **MIT** (`LICENSE`, 21 lignes). C'est le seul des trois qui pose une question
sur l'artefact distribué lui-même.

*Au crédit du dépôt* : la révision du **modèle de base** de la chanson **est** épinglée
(`chanson.py:89`, `29b3558d…`, et `vae_revision` aussi). L'écart porte sur la LoRA seule, et
le code le dit lui-même à l'utilisateur (`chanson.py:507` : « Sa revision n'est PAS
epinglee, contrairement au modele de base »).

> **Décision.** Sur Piper : (a) l'isoler dans un service séparé appelé par HTTP, ce qui
> rétablit la frontière ; (b) changer la licence du dépôt ; (c) l'assumer par écrit, avec
> l'analyse. **Ne rien faire, c'est choisir (c) sans l'écrire.** Préalable à toutes :
> vérifier la licence réelle du paquet, que le dépôt n'a jamais relevée.

### 4. Le cas que le schéma du plan laisserait passer

FireRedTTS-2 est **Apache 2.0** : conforme à la lettre de la règle. Et ses auteurs écrivent
que cette capacité est « intended solely for academic research purposes ».

Le dépôt affiche **les deux**, par un champ `reserve_auteurs`
(`sandbox-manager/dialogue.py:130-141`), et il les affiche **à l'endroit du choix**, pas en
note de bas de page (`:732-735`, `:883-896`).

Un champ `license: Apache-2.0` seul — c'est exactement ce que prévoit le schéma du plan
d'origine (l. 65) — aurait laissé passer ce modèle sans un mot.

> **Décision.** `reserve_auteurs` entre dans le schéma du registre **dès sa première
> version** (§5, étape 1). Un schéma se décide une fois ; ajouter un champ après coup
> oblige à repasser toutes les entrées.

### 5. Licence du dépôt — contredit sur les trois termes

Le plan (l. 31) : « Registry results DB is private (VPS). Public repo = method only
(AGPL-3.0). »

Le dépôt est **MIT** (`LICENSE`, 21 lignes, « Copyright (c) 2026 Free AI Studio
contributors »), il publie **l'application entière** et non la méthode seule, et il n'a
aucune base privée. Trois termes sur trois.

**Et le changement coûte aujourd'hui zéro.** `git shortlog -sn --all` donne **73 commits,
un seul auteur**. Il n'y a aucune contribution extérieure à engager. C'est la fenêtre la
plus large qu'aura jamais ce projet pour choisir sa licence — elle se refermera au premier
contributeur.

> **Décision demandée, et elle a une échéance réelle** : ce point bloque le §5, étape 4
> (« la base de mesures est-elle la douve, et peut-elle l'être dans un dépôt MIT ? »).
> Reporté en §7.

### 6. Fonctions payantes — le plan les exclut, le dépôt en a déjà

Le plan (l. 146) : « Out of scope (MVP) : paid features ».

Le dépôt a le **Boost** : route `/boost`, budget global 5 $
(`OPENROUTER_BOOST_TOTAL_BUDGET_USD`, `free-tier-manager/app.py:39`), plafond par session
0,50 $ (`:40`), réserve protégée 10 $ (`:38`). Et trois budgets Modal actifs par défaut dès
que Modal est configuré.

Ce n'est pas un défaut : c'est le plan qui a vieilli. Mais il faut le dire, parce que le
plan en tire une conséquence — « first revenue after P5 » (l. 20) — qui est déjà fausse.

> **Décision.** Rayer « paid features » du hors-périmètre, et **rayer avec elle la phrase
> « first revenue after P5 »**, qui n'a plus de support. La séquence de valorisation du
> plan doit être réécrite, ou abandonnée : elle repose sur un préalable déjà franchi.

### 7. Épinglage — et un constat de méthode plus intéressant que la règle

Le plan (l. 29) : « Install nothing unpinned. Pin versions + hashes. »

- Versions `==` partout dans les `requirements.txt` : **fait** ;
- **`--hash=` : zéro occurrence dans tout le dépôt** ;
- Les trois Dockerfile sont en `FROM python:3.12-slim`, **sans empreinte** ;
- Et surtout : **`video.py` ne contient aucun champ `revision`** (`grep -n "revision"
  sandbox-manager/video.py` → aucune ligne). **Wan 2.1 VACE tourne sur ce que Hugging Face
  sert ce jour-là.**

**Le constat de méthode, qui vaut mieux que la règle du plan** : le dépôt épingle **là où
il a peur**, pas là où la règle l'exige. La chanson est épinglée à la révision près parce
que ses fichiers `.pt` exécutent du code au chargement. La vidéo ne l'est pas. C'est un
meilleur critère que « tout épingler » — mais il n'est appliqué nulle part de façon
systématique, et il n'est écrit nulle part.

> **Décision.** Écrire le critère — « on épingle ce qui s'exécute ou se désérialise » — et
> **l'appliquer à `video.py`**, seul endroit où il est violé alors qu'il s'applique.

---

## §3 — La thèse

Le plan d'origine promet (l. 4-5) : « Free LLMs integrate new SOTA resources (models/tools)
end-to-end with no human in the loop […] ≥70% autonomous integrations, 0 bad merges ». Et
(l. 6) : « Also prove it works with self-hosted Qwen3.8-27B only. »

Cette seconde jambe n'a aucun support : **il n'y a pas un seul modèle de langage
auto-hébergé dans le dépôt.** Pas de `llama.cpp`, pas de vLLM, pas d'Ollama. Elle n'est pas
réfutée : elle n'a jamais commencé.

La première mérite mieux qu'un verdict.

### La thèse n'a pas été réfutée : elle a été ignorée, puis remplacée en fait

C'est la formulation juste, et il faut la tenir avec précision. Le journal ne *refuse* pas
l'autonomie — il se donne explicitement un autre objet (P0-P2, le débutant). Un journal qui
ne parle pas d'une chose ne la combat pas. Mais les arbitrages, eux, comptent :

- **Treize exceptions au gel sur treize** arbitrent en faveur d'une fonction visible,
  jamais en faveur d'une preuve d'autonomie (`PLAN.md:31` pour les huit premières, puis
  `:158`, `:166`, `:173`, `:184`, `:226`). Treize sur treize : ce n'est plus une série
  d'accidents.
- **`grep -in autonom PLAN.md` ne renvoie rien.** Aucune ligne du journal ne poursuit une
  intégration sans humain.
- L'unique expérience prévue (étape 5 du journal) mesure l'usage **par un débutant**, pas
  l'autonomie. Ce sont deux thèses différentes.
- **Au moins deux des treize exceptions dépendaient entièrement d'un jugement à l'oreille** :
  la cinquième, levée par « *le tts en français est effectivement avec l'accent anglais,
  faire mieux !!* », et la huitième, motivée par le constat que la LoRA « supprime le
  chant » (`PLAN.md:31`). **Le plan d'origine n'a aucun rôle pour l'oreille humaine** : son
  schéma (l. 68) ne connaît que `scores: {quality, speed, tool_calling}`.

### Ce qui, dans le travail fait, constitue déjà un début de preuve

La première douve du plan (l. 10) est la capture de tout, y compris les échecs : « never
discard failed runs ». **Cette capture existe déjà, et elle est solide** — le témoin du
matin mort-né (`PLAN.md:310`) ; la CI rouge pendant des jours, masquée en local par un vrai
`.env` (`PLAN.md:19`) ; l'essai LoRA dont le code dit lui-même ce qu'il n'établit pas ; la
prédiction démentie le soir même et laissée en place, barrée.

Sauf qu'elle est en prose, dans un fichier de **152 191 octets**, et qu'elle n'est pas
dénombrable. C'est pourquoi le projet ne peut produire **aucun** des indicateurs que le plan
réclame (l. 139-140) : `autonomy_rate`, `bad_merges`, `rejections_by_reason`.

### La proposition concrète : relire les treize exceptions

Plutôt que de lancer l'expérience à 20–30 candidats que rien ne permet de lancer :
**reprendre les treize exceptions déjà vécues et mesurer, cas par cas, ce qu'un agent
aurait pu mener seul et où l'humain fut indispensable.**

Rétrospectif, sans GPU, sans dollar. Coût : une demi-journée de lecture, aucune
infrastructure. **Et c'est le premier chiffre d'autonomie de l'histoire du projet.** Il sera
petit et il sera mesuré.

> **Décision demandée, et c'est la plus structurante du document.**
> (a) La thèse d'origine est **reprise** — et les treize exceptions deviennent des dettes
> datées ; (b) elle est **enterrée**, avec sa date et son motif, et le projet assume d'être
> un studio pour débutants plutôt qu'une plateforme d'intégration autonome ; (c) elle est
> **suspendue** jusqu'au résultat de la relecture des treize exceptions.
> Sans cette décision, l'étape « autonomie » du §5 est orpheline : elle sert une thèse que
> personne n'a confirmée depuis treize arbitrages contraires.

---

## §4 — Les règles debout

### Le gel, et l'amendement qu'il réclame

> **État du matin du 19/09. Tranché le soir même, et plus largement que ce qui suit : le
> gel est **levé**, les fonctions nouvelles sont permises à nouveau (§8, décision 1 de
> l'utilisateur). Cette section reste écrite telle quelle — on n'efface rien — parce que
> son analyse tient : c'est elle qui explique **pourquoi** un gel binaire n'a pas survécu,
> et ce que sa levée coûte.**


La règle (`PLAN.md:31`) : « Gel des fonctions. Aucune nouvelle fonction tant que P0-1 et
P0-2 ne sont pas vérifiés **en réel**. »

**Elle a été contournée treize fois en sept jours** (première exception le 11/09,
treizième le 17/09). Ce n'est pas un procès : chacune était légitime, levée par
l'utilisateur, motivée, et plusieurs ont produit du réel mesuré. C'est le **format** de la
règle qui ne tient pas.

**Amendement proposé, avec son motif : un gel binaire ne survit pas à un utilisateur qui se
sert de son outil tous les jours.** Un gel qui dit « aucune nouvelle *fonction visible* ;
les corrections de ce que l'essai révèle sont *attendues* » tiendra, parce qu'il décrit ce
qui se passe vraiment.

### Le bon format d'exception, que le journal a trouvé tout seul

Les douzième (`PLAN.md:184`) et treizième (`:226`) exceptions sont écrites **avant** le
travail. Ce sont les deux mieux cadrées des treize, et la treizième porte même une section
« ce que cette exception ne couvre pas, et qui reste interdit » (`:234`). C'est le format ;
il ne reste qu'à le rendre obligatoire.

### Le statut de ce chantier lui-même

**Ce document n'est pas du code et ne tombe pas sous le gel.** Le registre (§5, étape 1),
lui, en est.

Il doit donc passer par la porte prévue : **une quatorzième exception, datée, écrite avant
le travail, citant l'autorisation de l'utilisateur verbatim** — et non par une
requalification commode en « ce n'est pas une fonction nouvelle ». Si le registre entre par
la petite porte, le gel ne veut plus rien dire, et les treize précédentes deviennent
rétroactivement de la paperasse.

**Qui peut amender le gel ?** Le gel est une règle de `PLAN.md`, et les treize exceptions
ont toutes été **levées par l'utilisateur**, jamais par un agent. L'amendement proposé
ci-dessus suit la même règle : **il ne vaut que levé par l'utilisateur, et daté.** Sans
cette précision, « amender le gel » serait une porte aussi petite que celle qu'il dénonce.

> ~~**Décision demandée.** (a) Lever la quatorzième exception pour le registre, avec sa
> section « ce qu'elle ne couvre pas » ; (b) attendre l'essai machine neuve (§6) avant
> toute ligne de code ; (c) amender le gel comme proposé, **puis** lever l'exception.~~
>
> **Tranché le 19/09 : aucune des trois. L'utilisateur a levé le gel** — « fonction
> nouvelle permise dorénavant ». Ni exception à lever, ni règle à amender : il n'y a plus
> de porte. **Ce que cela coûte est écrit au §8** : la pression qui rappelait la dette de
> l'essai machine neuve disparaît avec la règle, et il ne reste que la date butoir.

---

## §5 — Les étapes

Pour chacune : ce qu'elle produit, son livrable vérifiable, ce qu'elle prouve, **et ce
qu'elle ne prouve pas**.

### Étape 1 — le registre

C'est l'**étape 6 du journal** (`PLAN.md:319-323`) reprise telle quelle en quatre temps —
`registry/apps.yaml`, `registry/apps.schema.json` validé en CI, lecture du registre par les
services, puis seulement un job qui propose des candidats. Avec deux ajouts que le journal
n'a pas.

*Coût estimé : quelques jours de travail, aucune infrastructure, aucun dollar.*

#### Ajout 1 — il y a plus de copies de la vérité que le journal ne le croit

Le journal en compte trois (`PLAN.md:319-323`, point 3 : « le tableau du README en est une
troisième copie »). Relevé le 19/09, **il y en a six, et quatre divergent** :

| # | Copie | Preuve | État |
|---|---|---|---|
| 1 | Tableau « Fonction / Ce qui la fait tourner / Coût » | `README.md:316-324` | **périmé** |
| 2 | Tableau « Fonction / Fournisseur, modèle / Nature / Licence » | `README.md:394-…` | **périmé** |
| 3 | `PROVIDERS` et `LIMITES_PUBLIEES` | `free-tier-manager/app.py:52`, `:141` | source réelle du routeur |
| 4 | `MODELES` / `MODELE` / `LORA` | `video.py:84`, `chanson.py:85` et `:126`, `dialogue.py:115` | source réelle des trois pages |
| 5 | `modal/profiles.json` | 2 521 octets, 13 profils, `"verified": "2026-09-09"` | **lu par aucun code, et faux sur un point vérifiable** |
| 6 | `notebooks/SOTA_LINKS.md` | 3 297 octets | **divergent, et personne ne porte l'arbitrage** |

**Les deux tableaux du README sont périmés, et la preuve est courte** : `grep -c -i
"dialogue\|firered" README.md` renvoie **0**. Le dialogue à plusieurs voix, entré le 17/09
par la douzième exception, n'existe dans aucun des deux. Le README décrit un produit à sept
fonctions ; le Studio en a neuf.

**Sur `modal/profiles.json`** — relu intégralement le 19/09 avant d'être accusé. Il faut lui
accorder la même nuance qu'au fichier suivant : il décrit des **profils Modal** (« exemples
officiels déployables »), pas ce que le Studio fait tourner. L'écart Chatterbox-contre-Piper
n'est donc pas, en soi, une faute.

**Mais sa section `policy`, elle, décrit bien le Studio, et elle est fausse** : elle annonce
`"fallback_manual": ["colab", "kaggle"]` alors que l'ordre réel du Studio est
`["modal", "local", "kaggle", "colab"]`, **automatique** (`sandbox-manager/app.py:879`,
`:1451`). Kaggle y est donné pour manuel quand il est automatique, et `local` n'y figure
pas du tout. À cela s'ajoute que **aucun code ne lit ce fichier** — la recherche de son nom
dans `*.py`, `*.sh`, `*.ps1`, `*.yml`, `*.cmd` ne renvoie **aucune ligne** — alors
qu'`AGENTS.md:111` y envoie les agents comme vers « la version lisible par machine » du
catalogue. **C'est un document que les agents sont activement envoyés lire et dont la seule
partie qui décrit le Studio est fausse.**

**Sur `notebooks/SOTA_LINKS.md`** — relu intégralement, et l'accusation doit être plus
étroite que ce que j'avais d'abord écrit. Ce fichier ne prétend **pas** décrire les endroits
d'exécution du Studio : il s'annonce comme une liste de carnets communautaires pour GPU
gratuit, « solutions ponctuelles, jamais [...] backends garantis 24/7 ». C'est honnête. Mais
sa « Règle de sélection » écrit « VIDEO → **Wan 2.2** 5B si ressources limitées » et
« TTS → **Qwen3-TTS** », pendant que `video.py:87` fait tourner **Wan 2.1 VACE** et que le
routeur embarque **Piper**. **Aucun fichier du dépôt ne porte la décision « pourquoi 2.1 et
pas 2.2 ».** L'écart n'est pas un mensonge : c'est une décision qui n'a pas été écrite.

**Le pire état n'est donc pas « pas de registre ». C'est six vérités, aucune autorité, et
aucune trace des arbitrages.**

> **Premier arbitrage du chantier, et il est petit :** `modal/profiles.json` devient une
> source réellement lue, ou il se supprime et `AGENTS.md:111` avec lui. Le laisser tel quel
> est pire que les deux options, parce qu'il envoie activement les agents vers une
> description fausse.

#### Ajout 2 — une règle d'arbitrage écrite

Qui gagne quand deux copies se contredisent ? Et `verifie_le` (la date de vérification)
**par entrée**, pas pour tout le fichier — c'est déjà le défaut de `profiles.json`, dont
l'unique `"verified": "2026-09-09"` couvre treize profils, y compris une `policy` que le
Studio a démentie depuis.

Sans cette règle, la fusion produira une septième copie divergente et le remède reconduira
la maladie.

#### Ajout 3 — le remède existe, il est écrit et il a déjà servi

**Position de l'utilisateur, 19/09/2026 : « une partie du dépôt décrit le Studio de façon
périmée ou fausse, c'est un risque inacceptable pour un fonctionnement automatique, sinon
on ne sait pas l'utiliser. »** C'est la bonne lecture, et elle change le rang de cette
étape : un agent qui lit `modal/profiles.json` croit que Kaggle est manuel et que `local`
n'existe pas. Il ne se trompe pas par hasard — **il se trompe parce que le dépôt le lui a
dit**, par la voix d'`AGENTS.md:111`. Ce n'est pas un défaut de propreté, c'est une source
d'erreur dirigée.

**Un autre projet de l'utilisateur a déjà rencontré cette panne exacte et l'a réparée** :
`plasma-digital-twin` (`C:\Users\test\Documents\agentic-flow-fresh\plasma-digital-twin`).
Son générateur en écrit l'histoire dans son propre en-tête
(`scripts/living_docs/generate_status_block.py:5-27`) : son `CLAUDE.md` portait à la main
« 124/135 PASS, 0 FAIL », recopié d'un instantané JSON. **Les deux étaient faux** —
l'instantané avait gelé, la CI était rouge depuis des semaines. « *Nothing failed loudly ;
the numbers simply aged.* » C'est mot pour mot ce qui est arrivé à `profiles.json`, gelé
sur `"verified": "2026-09-09"`.

**Et la leçon qu'il en tire n'est pas celle qu'on attend** (`:11`) :

> « The lesson from that is NOT “generate it instead of writing it by hand”. »

Parce qu'un document engendré par une machine porte le même mensonge **avec l'autorité
d'une machine** : dans ce dépôt, une fiche auto-engendrée annonçait « 11 processus », tirés
d'un test rouge depuis des semaines. **Ce n'est pas l'écriture à la main qui périme, c'est
l'absence de contrôle de fraîcheur.** Fabriquer `registry/apps.yaml` sans ce contrôle
produirait une septième copie, simplement mieux habillée.

**Les cinq pièces à reprendre, et elles sont petites :**

1. **Zone engendrée, délimitée et interdite à la main.** `<!-- AUTO:STATUS:BEGIN -->` …
   `<!-- AUTO:STATUS:END -->` (`CLAUDE.md:280`, `:404`), avec en première ligne du bloc
   « generated, do not hand-edit » (`:282`). Le reste du fichier reste humain. **La
   frontière est visible dans le texte**, pas dans une convention qu'il faut connaître.
2. **Le bloc dit d'où il vient.** « Generated 2026-09-18 02:00 at `a9028b2ef` on
   `chantier/…` by `scripts/living_docs/generate_status_block.py` » (`:284`). Date,
   commit, branche, et **le programme qui l'a écrit** — de quoi refaire la mesure.
3. **La règle d'or, et c'est celle qui manque au Studio** (`generate_status_block.py:17`
   et `:20`) :
   - « Status comes from a **RUN**, never from a file that quotes a run. »
   - « Every figure is printed with the **evidence** it rests on, and a figure whose
     evidence no longer describes the current code is printed as **STALE** rather than as
     a number. **A stale number is worse than no number, because it reads as a
     measurement.** »

   Appliqué là-bas jusqu'au refus explicite : « `validation/validation_status.json` is
   **not** consulted : it is a snapshot with no freshness check, and quoting it is what put
   a false corpus-wide claim in this file » (`CLAUDE.md:324`). **C'est exactement le statut
   que `modal/profiles.json` devrait avoir**, ou alors il doit gagner un contrôle de
   fraîcheur.
4. **Le contrôle de fraîcheur est un rehachage, pas une date déclarée.** Chaque module est
   rehaché (source + tests) et comparé à l'empreinte enregistrée quand il est passé au
   vert ; empreinte différente, le vert décrit du code qui n'existe plus. **Et le détail
   qui fait tout** (`:26`) : la fonction de hachage est **importée du lanceur, jamais
   réécrite** — « *imported, not reimplemented, so the two can never drift apart* ». Le
   commentaire de l'import le dit sans détour (`:50`) : « UNE regle de scellement dans ce
   depot, et elle n'est pas definie ici. […] une seconde transcription derive, et celle-ci
   avait derive. » **C'est littéralement le mal des six copies, traité à la racine :
   une seule définition, importée partout.**
   Corollaire écrit là-bas et à reprendre tel quel (`CLAUDE.md:330`) : quand un sceau ne
   correspond plus, « **re-run and re-sign ; never re-hash the seal to match** ».
5. **Un drapeau `--check` qui sort en code 1 quand c'est périmé** (`:34`) — c'est
   l'accroche pour la CI.

**Deux pièges que ce dépôt a payés et qu'il ne faut pas repayer**, tous deux écrits dans
son propre code (`generate_status_block.py:671-683`) :

- **Un contrôle qui répare ce qu'il inspecte ne contrôle rien.** Jusqu'au 08/09, `--check`
  réécrivait le bloc *avant* de le juger : il ne pouvait donc jamais le trouver périmé, et
  il sortait en code 0 en annonçant une réussite. « *A check that repairs what it inspects
  answers a question nobody asked, and answers the asked one wrong.* »
- **Un contrôle que personne n'appelle ne protège personne.** Le commentaire le constate
  lui-même : « *No caller in the tree passes `--check`* », et `.github/workflows/` de ce
  dépôt ne contient qu'un `README.md` — **il n'y a pas de CI pour l'appeler.** La fraîcheur
  y repose sur une tâche nocturne, pas sur une barrière.

> **Et c'est précisément là que Free AI Studio peut faire mieux que le dépôt dont il
> s'inspire.** Le Studio a **une vraie CI, déclenchée sur chaque `push` et chaque
> `pull_request`, sans filtre de chemin** (`.github/workflows/validate.yml`). Le drapeau
> `--check` y devient une **dixième étape nommée** — ce que `plasma-digital-twin` n'a
> jamais pu faire. La pièce manquante là-bas est la seule que le Studio possède déjà.

#### Trois idées du plan d'origine à porter dans le schéma, maintenant

Parce qu'un schéma se décide **une fois** :

1. **Le rôle** (plan, l. 43 : « Agents request ROLES, never model names »). Le registre
   *expose un contrat* fonction → candidats ; il n'inventorie pas seulement. Le dépôt
   applique déjà l'idée (le 403 du §1, P4), **mais sous condition** : si `FREE_ONLY=false`
   et `ALLOW_PAID_MODELS=true`, le nom demandé n'est pas refusé — il est remplacé **en
   silence** par `free-ai-auto`. La règle des rôles est donc défendue par du code
   *en configuration par défaut seulement*, et cet état admis n'est documenté nulle part.
2. **Une colonne `statut`** (`candidate|challenger|champion|fallback|deprecated|archived`,
   plan l. 69 — le cycle de vie d'un candidat, du premier essai à la mise au rebut). La
   *mécanique* peut attendre ; **la colonne, non** : l'ajouter après coup oblige à repasser
   toutes les entrées.
3. **`commercial_ok`** (plan, l. 65), avec trois précisions que le plan n'a pas : il ne se
   déduit **pas** de la licence seule (§2.4 le prouve) ; il se pose **par sortie** autant
   que par modèle ; et **le territoire est une seconde dimension indépendante** — que le
   schéma du plan ignore et que le journal, lui, a déjà (le champ `territoire` de
   `PLAN.md:319-323`).

#### Livrable vérifiable

**Supprimer la ligne `chanson` du registre doit faire échouer la CI**, pas dégrader la page
en silence. C'est le test qui distingue un registre d'un fichier de documentation.

**Et un second livrable, qui est le vrai remède au risque nommé par l'utilisateur le
19/09 : une dixième étape de CI qui échoue quand une description a vieilli.** Concrètement,
dans l'ordre de difficulté croissante :

1. **Les deux tableaux du `README.md` et `modal/profiles.json` passent en zone engendrée**,
   entre marqueurs, avec la ligne « engendré, ne pas modifier à la main », la date, le
   commit et le nom du programme qui les écrit.
2. **La source unique est le code qui tourne** — `PROVIDERS`, `LIMITES_PUBLIEES`, les
   `MODELE`/`MODELES`/`LORA`, l'ordre `fallback_order` — **importée, jamais recopiée.**
   Le registre les lit ; il ne les redit pas.
3. **La CI échoue si le bloc engendré diffère de ce que le programme produirait
   aujourd'hui.** Un seul contrôle, une seule ligne de sortie, code 1.
4. **Ce qui ne peut pas être dérivé du code porte sa preuve et sa date** — une licence, une
   révision de modèle, un chiffre relevé chez un fournisseur — **et s'affiche `PÉRIMÉ` au
   lieu d'un nombre** dès que la preuve ne décrit plus le code courant.

**Le contrôle ne répare rien.** Il constate et il sort en erreur. La réparation est une
commande séparée, lancée par une personne. C'est l'exacte erreur que l'autre dépôt a payée
jusqu'au 08/09 et qu'il a écrite dans son code pour ne pas la refaire.

Plus une première barrière réellement utile, reprise du plan d'origine (l. 81 : « Never
retire a role's last working option ») : **« chaque fonction a au moins deux entrées
vivantes »**. Aujourd'hui, le routeur *refuse bien* quand plus rien n'est branché — un 503
avec le chemin vers la page Clés (`free-tier-manager/app.py:3544-3548`). **Mais il ne le
découvre qu'au moment de la question.** Rien, ni au démarrage ni en CI, ne dit « ce rôle
n'a plus qu'une seule option ». C'est cette alerte-là qui manque, pas le refus.

**Ce que l'étape 1 ne prouve pas** : rien sur la valeur pour un débutant, rien sur la
qualité d'un modèle, rien sur l'autonomie.

**Mais ce n'est pas de l'hygiène** — une version antérieure de ce document l'écrivait
ainsi, et la position de l'utilisateur du 19/09 corrige ce classement. Un dépôt qui décrit
son propre produit de travers n'est pas mal rangé : **il est inutilisable par une machine**,
parce que rien n'y distingue une description vivante d'une description morte. L'étape 3
(un agent qui valide les contributions) repose entièrement sur le contraire. **C'est donc
un préalable dur à l'automatisation, pas un travail de propreté.**

### Étape 2 — évaluations et barrières

Elle **commence à l'intérieur de l'étape 1** : un schéma validé en CI *est déjà* une
barrière.

**Premier rôle à évaluer : `stt` (la dictée).** La vérité terrain existe — un texte lu à
voix haute est sa propre référence. Trois moteurs sont comparables : Groq
`whisper-large-v3` et Whisper `small` local, tous deux en service pour la dictée, et
Whisper `medium`, en service pour le nettoyage du dialogue.

**Ce qui existe déjà, et ses limites.** Le 15/09, trois dictées ont été comparées au texte
attendu : mode Groq « 3 x 5, 15 », mode local « Trois fois cinq, quinze. »
(`PLAN.md:97-99`). C'est une comparaison, et elle est honnête. Mais c'est **une seule
dictée, jugée à l'œil** : il n'existe **aucun taux d'erreur de mots**, sur aucun corpus,
pour aucun moteur.

**Livrable : un taux d'erreur de mots par moteur, sur un corpus fixe, rejouable hors
réseau.**

**Deux pièges à nommer avant de commencer :**

1. **Une évaluation de la voix qui passe par Whisper juge partiellement Whisper.** Le dépôt
   utilise déjà la transcription pour vérifier la synthèse (le nettoyage du dialogue) ;
   c'est légitime comme outil, c'est circulaire comme juge.
2. **L'essai sur une fraction du trafic (10 % pendant 48 h, plan l. 80) n'a aucun sens dans
   un dépôt à un seul utilisateur.** 10 % du trafic d'une personne, c'est zéro ou un appel.
   **Et l'équivalent utile est déjà inventé dans le dépôt, sans être nommé : le rejeu à
   code changé sur des entrées réelles sauvegardées.** Ancien code contre nouveau, mêmes
   relevés, aucun GPU, aucun dollar — la méthode qui a donné « Modal : 1 coupe → 0 ;
   Kaggle : 2 coupes → 2, aux bornes identiques » (`PLAN.md:307`). Déterministe, gratuit,
   et plus fort qu'un essai sur fraction, parce qu'il compare deux versions sur les *mêmes*
   entrées au lieu de comparer deux populations.

**Les jauges chiffrées du plan d'origine sont reprises telles quelles** (l. 86, 94) : trois
candidats choisis à la main passent de bout en bout, trois candidats cassés sont correctement
rejetés ; budget maximal par candidat ; et **rejet journalisé pour empêcher la
reproposition**. Ce dernier point n'est pas théorique : le dépôt rejette déjà (LoRA+T4
refusée « au lieu de parier », fp8 écarté) — **mais dans la prose**, et rien n'empêche qu'un
agent repropose demain exactement la même chose.

> **Décision.** Le corpus de dictée est-il enregistré dans le dépôt (quelques fichiers
> audio courts, quelques kilo-octets) ou reconstruit à chaque fois ? **Dans le dépôt** :
> sinon le taux d'erreur n'est pas rejouable, et un taux non rejouable n'est pas une
> mesure.

### Étape 3 — l'intégration validée, puis ouverte aux clients

C'est le bout de la chaîne, et la demande explicite de l'utilisateur (19/09/2026) :

> un client propose un outil SOTA → un agent gratuit l'essaie dans le bac à sable → s'il
> passe la barre, la CI l'intègre → sinon, refus motivé et journalisé.

**Deux morceaux sur quatre existent déjà** : le bac à sable (§1) et la CI
(`.github/workflows/validate.yml`).

**Attention à ne pas surévaluer la CI.** Elle est solide, mais son bilan doit être écrit
exactement : le critère « ruff voit ce que `py_compile` laisse passer » a été prouvé par
une **faute introduite exprès** dans une copie de `video.py` (`PLAN.md:380-384`), pas par
une prise en conditions réelles ; et le `\n` mal échappé qui cassait tout le JavaScript de
`/studio` depuis `ed3e71d` a été **trouvé à la main** en vérifiant P0-1, après quoi
`node --check` a été ajouté pour qu'il ne repasse pas (`PLAN.md:27`). **La seule prise
réelle de la CI documentée dans le journal est l'échec de l'étape « Docker Compose
config » (`PLAN.md:19`).** Une CI qui n'a attrapé qu'une chose n'est pas une CI faible —
mais elle n'est pas non plus la preuve qu'un agent validateur peut s'y appuyer.

**Ce qui manque est la barre.** Sans les évaluations de l'étape 2, un agent validateur ne
valide pas : il tamponne. Et la règle dure du plan d'origine est gardée — les agents ne
peuvent modifier ni les barrières, ni les règles, ni l'authentification de la passerelle,
ni le fichier de plan (l. 30, traduction libre). **Un agent qui peut déplacer la barre
contre laquelle il valide ne valide rien.** C'est aussi le garde-fou personnel de
l'utilisateur : « pas de barre desserrée ».

#### Une contradiction à régler avant, et elle est dans le dépôt

**Le bac à sable n'a aucune sortie réseau** (`internal: true`,
`docker-compose.yml:211-213`). C'est excellent pour exécuter du code qu'on n'a pas écrit —
et **cela interdit exactement l'usage que cette étape lui assigne** : un agent qui essaie un
outil SOTA doit télécharger un modèle, un paquet, une fiche.

> **Décision demandée, et elle est préalable à toute l'étape 3.** (a) Une phase de
> préparation **hors** du bac à sable, qui télécharge et vérifie les empreintes, puis passe
> les fichiers par le volume — l'isolement reste total pendant l'exécution ; (b) une liste
> blanche de sorties, ce que le plan d'origine prévoyait (l. 51) et que le dépôt a choisi
> de ne pas faire ; (c) l'essai tourne sur Modal ou Kaggle, pas dans le bac à sable local.
> *(a) préserve la propriété la plus forte du dépôt, qui est de n'autoriser aucune sortie
> pendant que le code étranger tourne.*

#### Le modèle retenu : chaque client apporte ses propres clés

Précisé par l'utilisateur le 19/09/2026. Il n'y a donc **pas** de serveur multi-utilisateur
à construire, et j'avais tort d'y voir un obstacle :

- chacun installe le Studio chez lui, avec **ses** clés et **son** quota ;
- la contribution passe par **git** — pas par la machine de quelqu'un d'autre ;
- et `contexte_partage()` n'est pas une gêne : **c'est la garde qui fait tenir ce modèle**.
  Elle coupe Kaggle dès que le contexte devient partagé, ce qui est la traduction en code
  de la règle dure du plan (l. 25) : « Never resell/share quota. Each user runs on own
  accounts. » **Cette règle-là est déjà tenue, et par du code.**

Le stockage des clés en clair (§2.1) reste un défaut à corriger, mais il **cesse d'être un
blocage** pour les contributions.

> **Décision demandée : avec quelle clé l'agent validateur tourne-t-il ?**
> (a) Le contributeur valide chez lui, sur son propre quota, **avant** de proposer ;
> (b) le projet a un compte dédié, avec un budget de maintenance plafonné et séparé du
> travail de l'utilisateur — c'est ce que prévoit le plan d'origine (l. 40 : « Separate
> budgets: maintenance (low prio, capped) vs user work ») ;
> (c) les deux : local d'abord, reprise en CI ensuite.

### Étape 4 — ce qui rend l'étape 3 possible

Décidé avec l'utilisateur le 19/09/2026. **Ces décisions ne sont pas encore consignées dans
le dépôt** : elles viennent d'une conversation, et elles doivent entrer dans `PLAN.md` à la
même date pour exister au sens du journal.

#### Deux interfaces, pas une

L'administrateur et le client n'ont pas la même page : même code, un drapeau posé dans le
`.env` que le client ne pose jamais. Le client n'a ni la revue des contributions, ni
l'édition du registre, ni le budget de maintenance.

**Piège à écrire noir sur blanc : cacher un bouton n'est pas refuser une route.** Les routes
d'administration doivent renvoyer un refus **côté serveur**, pas disparaître de la page.
C'est la leçon que le dépôt a apprise le 16/09 en posant `exiger_page_du_studio` sur
`/maj/lancer`, `/diagnostic/reparer` et `/cles/oublier` (`free-tier-manager/app.py:1820`,
`sandbox-manager/app.py:159`). La forme existe ; il suffit de la réemployer.

#### Un budget de maintenance, plafonné et ajustable

Décision de l'utilisateur : **50 % du quota, ajustable**, réservé à la validation
automatique.

**La forme existe déjà et se reprend telle quelle : la réserve protégée du Boost.**
`can_activate_boost` (`free-tier-manager/app.py:286`) **refuse avant de dépenser**, pas
après : si le solde moins le plafond demandé passerait sous `BOOST_RESERVE_USD`,
l'activation est refusée avec son motif (`:300-303`).

**Mais « 50 % de quoi ? » n'a pas de réponse partout.** Groq publie 1 000 appels par jour,
OpenRouter 50 : le pourcentage s'y calcule. **Gemini ne publie aucun chiffre** — et le
Studio en a déjà tiré la bonne conclusion (`PLAN.md:41`) : il ne code aucune limite en dur,
il lit celle que Google écrit dans son refus.

> **Décision.** Pour Gemini : **un plafond en nombre d'appels par jour, fixé par
> l'utilisateur**, et non un pourcentage d'un dénominateur inconnu. Écrire « 50 % » là
> serait un nombre fabriqué.

#### Une base de mesures, anonyme, locale d'abord

Chaque Studio écrit **ses propres** mesures chez lui, sous une forme dénombrable — **une
ligne par essai**.

C'est le verrou du §3 : sans cette base, ni taux d'autonomie, ni comparaison entre deux
modèles, ni aucun des indicateurs du plan d'origine. La remontée vers l'administrateur vient
**ensuite**, et **seulement si le client dit oui** : interrupteur visible, éteint par
défaut. C'est la règle dure du plan d'origine (l. 33 : « explicit opt-in consent + visible
reward », « Never covert »), et elle est bonne.

- **Contenu : les mesures seules** — date, fonction, endroit d'exécution, durée, coût,
  refus, qui a décidé. **Aucune phrase écrite par une personne.** Un commentaire libre
  contient n'importe quoi, y compris un nom propre ou une clé collée par erreur ; et une
  base qu'on ne peut pas garantir anonyme n'est pas anonyme. *Si du commentaire libre est
  ajouté un jour, il lui faudra son propre écran d'accord et son propre effacement.*
- **Rotation : un fichier par mois, rien n'est jamais effacé**, les mois clos compressés.
  **Motif mesuré** : le dépôt s'est déjà fait mordre par une liste qui grossit sans
  limite. L'auto-test lisait la réponse de `GET /jobs` sous une borne trop basse et rendait
  un échec sur un système sain ; la borne a été relevée à 2 000 000 d'octets
  (`scripts/self-test.py:35`, `LIMITE_LECTURE`) et la troncature se déclare désormais au
  lieu de se déguiser en erreur de format. **Mais le journal laisse le point ouvert de sa
  propre main** : « la liste des travaux grossit sans limite, elle franchira la nouvelle
  borne à son tour » (`PLAN.md:278`). **Repousser une borne n'est pas une rotation.**
- **Les contributions, elles, ne sont pas anonymes et ne doivent pas l'être** : elles
  arrivent par git, avec auteur, date et signature. C'est ce qui permet le score de
  confiance du contributeur que le plan prévoit (l. 13, 97). Deux régimes distincts, et
  c'est délibéré : **contributions signées, mesures anonymes.**

#### Ce qui va dans git, ce qui reste ignoré

Règle à écrire, motivée par un défaut réel du dépôt (la CI rouge pendant des jours, masquée
en local par le vrai `.env`, `PLAN.md:19`) :

> **Ce que `.gitignore` cache, la CI ne peut pas le vérifier.**

- **Dans git** : le registre, son schéma, les définitions d'évaluations, les seuils, les
  résultats de référence, le corpus de dictée — tout ce qui doit être relu et vérifié
  automatiquement.
- **Ignoré** : les mesures qui s'accumulent, les clés, les compteurs — tout ce qui grossit
  seul. C'est déjà exactement le régime de `config/` et de `.env`.

#### Où vivent les trois choses — et pourquoi ce n'est pas « client contre administrateur »

Question posée par l'utilisateur le 19/09 : **faut-il deux dépôts, un pour le déploiement
client et un privé pour le socle d'administration ?**

**Oui, deux dépôts — mais la frontière « client / administrateur » ne tient pas.** La
décision du 19/09 fait du client l'administrateur de son propre Studio : il lui faut la
mise à jour, le diagnostic, la page Clés. **Ce que le client ne doit pas avoir, ce n'est pas
l'administration : c'est le jugement.**

La frontière juste est **ce qui tourne** contre **ce qui juge**. Et il y a **trois**
endroits, pas deux :

| | Quoi | Où | Pourquoi là |
|---|---|---|---|
| **Public** | le Studio, les pages, les services, le schéma du registre, le **lanceur** d'évals, un petit jeu d'évals de fumée | `github.com/jpbrasile/free-ai-studio`, public depuis le 09/09/2026, MIT | le produit doit s'installer en un geste ; le cacher tuerait la thèse débutant, qui **est** le produit |
| **Privé** | les **définitions d'évaluations**, les **seuils**, les résultats de référence | un dépôt privé | c'est du texte qui change par relecture, petit, dont l'historique sert : l'usage exact d'un dépôt git |
| **Sauvegardé** | la **base de mesures** | **pas dans git** — un fichier par mois, copié ailleurs | ça s'empile, ça ne se relit pas, et git n'oublie jamais |

**Ce n'est pas le code qui a de la valeur.** Le plan d'origine le dit lui-même (l. 35) :
« Public registry snapshot may be scraped by others ; **do not rely on hiding it. Protect
the flow**, not the snapshot. » Ce qui ne se copie pas, ce sont les mesures accumulées et
**le fait de savoir juger**.

**Et l'argument le plus fort pour la séparation n'est pas la propriété intellectuelle.**
C'est la règle dure que le plan porte déjà (l. 30) : l'agent qui valide ne doit jamais
pouvoir modifier la barre contre laquelle il valide. **Aujourd'hui c'est une promesse ; avec
deux dépôts, c'est structurel** — la barre vit là où l'agent lit sans pouvoir écrire. C'est
gratuit, et ça vaut plus que le secret.

**La forme : jeu public de fumée, jeu privé qui décide.** Le contributeur pré-valide chez
lui, sur **son** quota — la plupart des refus tombent là et ne coûtent rien. Le jeu privé
décide. Se régler sur le jeu public ne fait pas passer, **et l'écart entre les deux scores
est un signal que seul l'administrateur possède.**

**Traiter la fuite du jeu privé comme certaine, pas comme possible.** Il fuit par les
contributions acceptées et par déduction. Deux conséquences à écrire dans les règles :
- **le jeu se renouvelle** — c'est le « Value = FLOW, not snapshot » du plan d'origine ;
- **on ne publie jamais un score, seulement un verdict et un motif pris dans une liste
  fermée.** Un nombre livre le pouvoir discriminant de l'éval ; « refusé — licence non
  commerciale » n'en livre rien. Le plan a déjà l'idée sous le nom de « rejet journalisé » ;
  il suffit que le vocabulaire soit clos.

**Le couplage que personne n'avait vu, et il tranche une autre décision.** Le choix du
dépôt privé **force** la réponse à « avec quelle clé tourne l'agent validateur » (§5,
étape 3) :

- **barre privée** ⇒ la validation finale tourne chez l'administrateur, sur son budget. Le
  budget de maintenance devient **obligatoire**, plus optionnel ;
- **validation entièrement chez le client** ⇒ les évals sont sur sa machine, **donc elles ne
  sont pas privées**, et la douve se réduit à la base de mesures.

**On ne peut pas avoir « le client valide chez lui » et « la barre est secrète ».** L'option
(c) — pré-validation locale obligatoire, décision finale chez l'administrateur — est la
seule qui tienne les deux bouts, **et elle est aussi la protection du quota** : sans
pré-validation obligatoire, n'importe qui peut brûler le budget de maintenance en soumettant
des déchets, ce qui retourne la règle « never resell/share quota » contre le projet.

#### Les sauvegardes, et le matériel qui existe déjà

**L'utilisateur possède un VPS qui tourne** (Docker, Coolify, PostgreSQL via un Supabase
auto-hébergé, nginx), relevé le 19/09 dans les procédures d'un autre de ses projets.
**Son nom de domaine n'est pas écrit ici ; le paragraphe qui suit la répartition dit
pourquoi.** **Le plan d'origine réclamait exactement cela en P0** — « VPS
(private) : Postgres (registry + eval results + provenance), scheduler (cron), registry API
[…] **Off-site daily encrypted backups** ». Ce n'est donc pas à construire : c'est à relier.

**Décision de l'utilisateur, 19/09 : les sauvegardes se font en local et sur le VPS.**

- **Local + VPS, c'est deux copies dans deux lieux** — le « hors site » de la règle des
  trois copies est tenu. La troisième copie (disque externe ou espace en ligne) reste à
  décider, et pour quelques méga-octets par mois elle coûte presque rien.
- **Une question ouverte à ne pas sauter : le VPS est-il lui-même sauvegardé ?** S'il meurt
  et qu'il portait la seule copie hors site, il n'en reste qu'une. **Non vérifié.**
- **Et le critère qui fait la différence entre une sauvegarde et un espoir est déjà écrit
  dans le plan d'origine, pour P0** : « **DoD : restore-from-backup test passes.** » Une
  sauvegarde compte le jour où elle a été **remise en place**, pas le jour où elle a été
  configurée. Daté, comme tout le reste.

**Ce qui ne doit pas aller sur le VPS, et c'est important.** Le VPS héberge déjà un autre
produit en service, avec sa base. **Le code inconnu d'un contributeur ne doit pas s'exécuter
à côté.** Répartition :

- **VPS** : la base de mesures, les seuils, l'API de registre, l'ordonnanceur. **Aucun code
  étranger.**
- **Modal, Kaggle, ou le bac à sable local** : l'exécution des candidats.
- **Le PC de l'utilisateur** : le développement.

#### Les coordonnées du VPS ne vont dans aucun dépôt — même privé

Question de l'utilisateur, 19/09 : « les infos sur le VPS partent sur le dépôt privé ? »
**Non — et la bonne coupure n'est pas « public ou privé », c'est « trois natures
d'information qui n'ont pas le même domicile ».** Un dépôt privé n'est pas un coffre : il
se clone sur des portables, il s'ouvre au premier collaborateur, il est sauvegardé par
l'hébergeur, et **son historique est définitif** — un secret poussé une fois y reste après
la correction. C'est la règle que l'utilisateur s'est déjà donnée pour ce VPS précis, dans
ses propres procédures : « *Never read, print, or expose keys from `.env`, container env
vars, or Coolify configs.* »

| Nature | Exemples | Domicile | Pourquoi |
| --- | --- | --- | --- |
| **Les secrets** | clé SSH, mot de passe Postgres, jetons Coolify, clés Supabase | **l'environnement seul** : `.env` non suivi, gestionnaire de mots de passe | irréversible une fois poussé, dans le privé **comme** dans le public |
| **Les coordonnées** | nom de domaine, IP, noms de conteneurs, ports, chemins | **des variables**, dont les valeurs ne sont écrites nulle part dans git ; le dépôt privé au pire | ce n'est pas un secret au sens strict, c'est de la **surface d'attaque offerte** : un nom plus une pile connue font une cible |
| **La forme** | ce qui est sauvegardé, à quelle cadence, la procédure de restauration écrite **contre des variables** | **le dépôt privé** — et la partie sans coordonnées pourrait même être publique | c'est elle qu'il faut relire, versionner et rejouer |

**Le régime existe déjà dans ce dépôt ; il suffit de l'étendre.** `.env` est ignoré,
`.env.example` porte les noms des variables et **aucune valeur**. Une procédure de
sauvegarde s'écrit donc `ssh $VPS_UTILISATEUR@$VPS_HOTE` et jamais l'adresse en clair :
**le dépôt privé porte le script, la machine porte les valeurs.**

**Appliqué à ce document, le jour même.** Une première version de ce paragraphe portait le
nom de domaine du VPS en toutes lettres — **dans un dépôt public depuis le 09/09**. Il a
été retiré d'ici et de `PLAN.md` le 19/09. **Vérifié : `git grep` sur tous les objets
commités (`git rev-list --all`) ne rend aucune ligne — le nom n'a jamais été commité**,
donc la correction est complète et ne demande aucune réécriture d'historique. C'est la
démonstration du risque en une demi-journée : la fuite ne vient pas d'une attaque, elle
vient d'une phrase utile écrite au bon endroit du mauvais dépôt.

> **Conséquence pour l'étape 3.** Le jour où la validation tourne sur le VPS, son adresse
> devient une variable de la CI (un *secret* de dépôt), pas une ligne d'un fichier. Et le
> dépôt public ne doit contenir **aucun** indice du chemin réseau menant à la machine qui
> détient la barre — sinon la séparation du « produit » et du « jugement », décidée
> ci-dessus, se contourne par le réseau au lieu de se contourner par le code.

> **Décision.** La base de mesures est-elle **la douve du projet** (le plan d'origine le
> veut, l. 10 et 31) alors que le dépôt public est MIT ? La réponse proposée ici est
> **oui, et elle ne dépend pas de la licence** : ce qui protège n'est pas le secret du
> code, c'est que **la copie est sans valeur sans les mesures**. Un clone parti aujourd'hui
> a zéro ligne. La licence reste à trancher au §7 pour d'autres raisons — mais elle cesse
> d'être ce qui protège la douve.

---

## §6 — La mesure qui n'est pas une étape

**L'essai machine neuve** (`docs/ESSAI_MACHINE_NEUVE.md`) : une grille de **six tâches**, de
l'installation jusqu'au diagnostic, avec pour indicateur **le nombre de « oui » sur 6**
(l. 57-66). Elle a été jouée en partie le 13/09. **La grille n'est pas remplie. Il n'y a
aucun chiffre.**

Une version antérieure de ce document sortait cette mesure du chemin critique, au motif
qu'« aucun plan de code ne peut la programmer ». **L'argument ne tient pas** : l'absence de
programmabilité ne conclut rien sur la priorité. Elle déplace le travail vers
l'**organisation** — réserver la machine, trouver la personne, bloquer une soirée — et
*cela* se planifie et se date. « Obligation permanente » sans échéance est une épitaphe :
elle sera levée par l'inaction, comme les treize fois précédentes.

**C'est la seule étape qui puisse invalider tout le reste.** Si un débutant n'arrive pas au
bout de l'installation, le registre et les évaluations servent un produit que personne
n'atteint. Et on ne le saura pas autrement : les trois passages du 11/09 tournent dans un
`docker:dind` **sous Linux**, et le journal le dit lui-même — « ce passage ne dit rien de
Windows » (`PLAN.md:453`).

**La cible primaire du dépôt — Windows, débutant, 906 lignes de scripts écrites pour elle —
n'a jamais été mesurée une seule fois.**

Ce que le §6 porte, et qui se décide maintenant :

1. **Une date.** Pas « bientôt ».
2. **La contrainte matérielle, dite en toutes lettres** : un second ordinateur Windows
   physique, 8 Go, la virtualisation activée, les droits administrateur, environ 6 Go de
   téléchargement, et un vrai débutant. **Un seul essai « neuf » est possible par machine —
   une a déjà été brûlée.** Coût : une soirée, une machine, une personne.
3. **Sa jauge** : le compteur de fonctions nouvelles ajoutées depuis le 13/09, qui mesure
   exactement l'écart entre le produit essayé et le produit actuel.
4. **À partir de quand une mesure repoussée devient une mesure abandonnée** — écrit en
   toutes lettres, avec sa date. ~~Sans cette phrase, la quatorzième exception au gel
   arrivera avant l'essai, comme les treize précédentes.~~ **Répondu le 19/09 (§8,
   point 9) : butoir au 31/10/2026, après quoi le document écrit « mesure abandonnée ».
   Et le motif de la phrase a changé de nature : le gel étant levé, il n'y a plus
   d'exception à redouter — c'est l'absence totale de contrainte qui rend cette date
   nécessaire. Elle est désormais le seul levier.**

> **Décision demandée.** Une date, ou l'aveu écrit qu'il n'y en aura pas avant telle
> échéance. **Les deux sont acceptables ; le silence ne l'est pas.**

---

## §7 — Les décisions ouvertes

> **État du matin du 19/09. Les dix-sept points ont tous été tranchés le soir même : voir
> le §8.** Ce tableau reste écrit tel quel — on n'efface rien, et les options écartées
> expliquent les choix retenus.


| # | Décision | Section | Options |
|---|---|---|---|
| 1 | **La thèse d'autonomie** : reprise, enterrée ou suspendue ? | §3 | reprise (les 13 exceptions deviennent des dettes) · enterrée, datée · suspendue jusqu'à la relecture des 13 |
| 2 | **Le gel** : amendé ou non, et la 14ᵉ exception | §4 | lever l'exception · attendre le §6 · amender puis lever |
| 3 | **Piper (GPL) dans un dépôt MIT** | §2.3 | isoler en service HTTP · changer la licence · assumer par écrit — après avoir vérifié la licence réelle du paquet |
| 4 | **La licence du dépôt public.** Le dépôt est **public sur GitHub depuis le 09/09/2026**, MIT, **0 fork, 0 étoile** : rien n'est perdu à ce jour, et l'auteur unique (73 commits) peut encore relicencier les versions à venir. **Mais la fenêtre ne se ferme pas à une date : elle se ferme au premier contributeur extérieur** — donc avant l'ouverture des contributions (§5, étape 3). *La douve, elle, ne dépend plus de cette décision : voir §5, étape 4* | §2.5, §5 étape 4 | rester MIT (adoption maximale, forme « noyau ouvert ») · passer en AGPL · relicencier avant la première contribution |
| 5 | **Les modèles non conformes déjà en service** (YuE2-3B et sa LoRA, CC BY-NC 4.0) | §2.3 | les retirer · **amender la règle en distinguant « ce que le Studio fait tourner à la demande » de « ce que le Studio distribue »** — plus juste, et déjà ce que le dépôt pratique sans l'écrire |
| 6 | **La clé de l'agent validateur.** **Cette décision n'est plus libre** : elle est fixée par la n° 14. Barre privée ⇒ décision finale chez l'administrateur. Et la pré-validation obligatoire chez le contributeur n'est pas un confort, c'est **la protection du budget de maintenance** | §5 étapes 3 et 4 | **(c) les deux — pré-validation locale obligatoire, décision finale chez l'administrateur** · (a) · (b) |
| 14 | **Deux dépôts : public = le produit, privé = le jugement.** Pas « client / administrateur » — le client est l'administrateur de son Studio. La frontière est *ce qui tourne* contre *ce qui juge*. Bénéfice principal : la règle « l'agent ne modifie pas la barre » cesse d'être une promesse et devient structurelle | §5 étape 4 | **créer le dépôt privé (évals, seuils, références)** · tout garder public et n'avoir que la base pour douve · ne rien changer |
| 15 | **Les sauvegardes** — décision prise le 19/09 : **local + VPS**. Restent : la troisième copie, **le VPS est-il lui-même sauvegardé (non vérifié)**, et **la localisation européenne du VPS, exigée par le plan et non vérifiée** | §5 étape 4 | une date pour le **premier essai de restauration**, qui est le seul critère (« DoD : restore-from-backup test passes ») |
| 16 | **Où vivent les coordonnées du VPS.** Répondu au §5 étape 4 : ni public, ni privé — **en variables**, valeurs dans l'environnement. Ce qui reste à trancher est la **forme** : un `.env.example` de plus dans le dépôt privé, ou des *secrets* de dépôt côté CI ? | §5 étape 4 | **les deux : `.env.example` pour la lisibilité, secrets de CI pour l'exécution** · seulement l'un · rien tant que la validation ne tourne pas sur le VPS |
| 7 | **La sortie réseau du bac à sable**, préalable à l'étape 3 | §5 étape 3 | préparation hors bac à sable · liste blanche · essai sur Modal/Kaggle |
| 8 | **`modal/profiles.json`** | §5 étape 1 | source réellement lue · supprimé, avec `AGENTS.md:111` · **passé en zone engendrée sous contrôle de fraîcheur** (ajout 3) |
| 13 | **Le contrôle de fraîcheur des descriptions**, position de l'utilisateur du 19/09 : « risque inacceptable pour un fonctionnement automatique ». Le mécanisme existe et tourne dans `plasma-digital-twin` ; le Studio a en plus la CI qui manque là-bas | §5 étape 1, ajout 3 | **dixième étape de CI qui échoue si une description a vieilli** · zone engendrée seulement, sans barrière · ne rien faire et documenter le risque |
| 9 | **La date de l'essai machine neuve** | §6 | une date · l'impossibilité écrite, avec son échéance |
| 10 | **La branche `audit-20260911`** | en-tête | **`main` est ancêtre : la fusion est une avance directe, sans conflit possible.** fusionner · écrire pourquoi on ne fusionne pas |
| 11 | **Le trou des budgets Modal** | ci-dessous | corriger · documenter et assumer |
| 17 | **Les clés en clair**, décomposé le 19/09 en deux décisions de rangs différents. **Bon marché et d'abord** : le refus au démarrage — sachant que `free-tier-manager` **ne lit même pas `STUDIO_HEBERGE`** (recherche de `HEBERGE` vide dans tout le service) et que le drapeau est **déclaratif, pas détecté** (`sandbox-manager/app.py:65-66`). **Ouvert, à son vrai rang** : le chiffrement au repos, qui ne défend que le fichier échappé sans sa machine | §2.1 | **(1) faire lire le drapeau et refuser de démarrer, plus un refus sur liaison non locale ; (2) corriger `AGENTS.md:77` dans tous les cas ; (3) chiffrement au repos, tranché plus tard** · tout faire d'un coup · ne rien faire tant que `STUDIO_HEBERGE` reste `false` |
| 12 | **`FREE_ONLY=false` est-il un état admis ?** Si oui, la règle des rôles n'est pas défendue par du code | §5 étape 1 | interdit · admis et documenté |

**Sur le point 11, qui est le seul défaut connu pouvant coûter de l'argent réel.**
`docker-compose.yml:95-97` le dit lui-même : « 5 + 20 + 5 = EXACTEMENT le credit declare »
dans `MODAL_CREDIT_MENSUEL_USD` (30, `.env.example:245`), « et aucun des trois compteurs ne
voit les deux autres : ils peuvent donc atteindre leur plafond le meme mois ».
**Et la correction tient en une ligne** : un quatrième compteur, commun aux trois, plafonné
au crédit déclaré, refusant avant de lancer — exactement la forme de `budget_verifier`, qui
existe déjà en trois exemplaires. À défaut, la limite de dépense réglée **chez Modal** est
le seul arrêt réel, et `docker-compose.yml:98` le dit déjà.

**Les règles mortes du plan d'origine**, à ranger : le VPS européen, Postgres, Forgejo,
Temporal, Langfuse, LiteLLM, l'API de registre à paliers, et l'exclusion de Windows (§2.2).
Elles décrivent une architecture hébergée que le modèle « chaque client chez lui » rend sans
objet. *Ce rangement est proposé, pas acté : il attend une ligne de l'utilisateur.*

---

## §8 — Les décisions prises, 19/09/2026

**Le §7 ci-dessus reste écrit tel quel** — on n'efface rien. Ce §8 dit ce que chaque point
est devenu. **Quatre décisions sont de l'utilisateur ; les treize autres, il m'a demandé
de les trancher** (« tranche sur le reste »). Chaque ligne dit **qui** a décidé, pour
qu'on puisse revenir sur les miennes sans revenir sur les siennes.

**Aucune de ces décisions n'est un travail fait.** Ce sont des arbitrages ; le code qu'ils
appellent n'est pas écrit à ce jour.

### Les quatre décisions de l'utilisateur

#### 1. Le gel est levé : les fonctions nouvelles sont permises à nouveau *(point 2)*

Ce n'est pas l'amendement que je recommandais — je proposais « aucune fonction **visible**
nouvelle, les corrections restent attendues ». L'utilisateur a tranché plus large, et
c'est sa décision. Ce qu'elle entraîne, écrit d'avance :

- **La quatorzième exception n'a plus d'objet.** Le registre, le refus au démarrage et le
  budget commun s'écrivent directement, sans porte à franchir.
- **Le gel était la seule pression qui maintenait l'essai machine neuve en vie.** Il a été
  contourné treize fois — mais chaque contournement devait **s'écrire**, et cette écriture
  rappelait la dette. Sans lui, **la date butoir du §6 devient le seul levier restant**,
  d'où le caractère exécutoire donné au point 9 ci-dessous.
- **Le compteur de fonctions nouvelles depuis le 13/09 continue de tourner.** Il ne refuse
  plus rien ; il mesure l'écart entre le produit essayé un jour et le produit réel.

#### 2. Un seul budget Modal, partagé entre le mode autonome et les demandes humaines *(point 11)*

Aujourd'hui **trois** compteurs — 5 $, 20 $, 5 $ — dont la somme **égale exactement** le
crédit déclaré de 30 $ (`docker-compose.yml:95-97`, `.env.example:245`), et **aucun ne voit
les deux autres**. Un compteur unique **referme le défaut par construction** : on ne peut
plus dépasser en additionnant trois plafonds qui s'ignorent.

Dedans, **une part réservée à la validation automatique** — la décision du 19/09 : 50 %,
ajustable. La forme existe déjà et se reprend telle quelle : la réserve protégée du Boost
**refuse avant de dépenser**, pas après. Et le rappel qui vaut pour Gemini : là où le
fournisseur **ne publie aucune limite**, la part se dit en **appels par jour fixés par
l'utilisateur**, jamais en pourcentage d'un dénominateur inconnu — un pourcentage y serait
un nombre fabriqué.

#### 3. Refus au démarrage si les clés sont exposées *(point 17)*

Retenu tel que proposé au §2.1, avec son coût réel : **deux changements, pas un**, puisque
`free-tier-manager` **ne lit même pas** `STUDIO_HEBERGE` aujourd'hui. Plus la troisième
condition, celle qui **se constate** au lieu de se déclarer : refuser aussi lorsque le
service n'est pas lié à `127.0.0.1`. **Le chiffrement au repos n'est pas un préalable** et
reste au rang où le §2.1 le range.

#### 4. MIT pour le dépôt client ; la part critique sur le dépôt privé *(point 4)*

Confirmé et **déjà exécuté** : `jpbrasile/free-ai-studio-jugement` existe depuis le matin
du 19/09, **privé, sans licence** — tous droits réservés. Le dépôt public reste **MIT**.
La ligne de partage est celle du §5 étape 4 : **ce qui tourne** est public, **ce qui juge**
est privé, **ce qui mesure** est sauvegardé hors git.

Conséquence à ne pas perdre : **ce qui protège n'est ni le code ni les évaluations, c'est
que la copie est sans valeur sans les mesures.** Un clone parti aujourd'hui a zéro ligne.

### Les treize que j'ai tranchées

| # | Point | Ce que je tranche | Pourquoi |
|---|---|---|---|
| 1 | **La thèse d'autonomie** | **Suspendue** — et un chiffre d'ici là : reprendre les treize exceptions et compter, cas par cas, ce qu'un agent aurait pu mener seul | Ni la reprendre ni l'enterrer sans mesure. Le comptage est rétrospectif, gratuit, faisable en une séance — et ce serait **le premier chiffre d'autonomie du projet** |
| 3 | **Piper (GPL) dans un dépôt MIT** | **Vérifier d'abord la licence réelle du paquet installé** ; si GPL confirmé, **isoler Piper en processus séparé** | La contradiction repose sur **une seule source non vérifiée** (`PLAN.md:147`) : on ne réorganise pas un dépôt sur une croyance. Si elle tient, l'isolement est le remède standard et le moins cher. Piper est le cas grave parce qu'il est **importé dans le processus** (`app.py:1470`) d'un artefact distribué, là où YuE2 tourne à distance |
| 5 | **Les modèles CC BY-NC déjà en service** | **Les garder**, et porter la restriction **au point de choix**, pas en note de bas de page | C'est déjà ce que le dépôt pratique sans l'écrire (`dialogue.py:130-141`, montré en `:732-735`). La règle juste distingue **ce que le Studio fait tourner à la demande** de **ce qu'il distribue**. Deux obligations viennent avec : `commercial_ok: false` dans le registre, et **épingler la révision de la LoRA**, aujourd'hui `None` (`chanson.py:126-133`) |
| 6 | **La clé de l'agent validateur** | **Déjà fixée** par la décision 4 de l'utilisateur : **pré-validation locale obligatoire** chez le contributeur, **décision finale** chez l'administrateur | On ne peut pas avoir à la fois « le client valide chez lui » et « la barre est secrète ». Le contributeur sait s'il a une chance ; il ne sait pas où est la barre |
| 7 | **La sortie réseau du bac à sable** | **Jamais de sortie réseau.** La récupération se fait **avant**, par une étape séparée qui télécharge, empreinte et dépose l'artefact ; le bac à sable reste `internal: true` | C'est la propriété la plus dure du dépôt, et le plan d'origine en demandait **moins**. Ouvrir la sortie pour la commodité d'un agent échangerait la seule garantie réelle contre du confort |
| 8 | **`modal/profiles.json`** | **Supprimé**, et la ligne `AGENTS.md:111` retirée avec lui | Lu par **aucun** code, déjà faux sur trois fonctions, et `AGENTS.md` y envoie les agents comme « la version lisible par machine ». **Le laisser est pire que les deux autres options** : une vérité concurrente que personne ne maintient. Le registre prendra la place |
| 9 | **La date de l'essai machine neuve** | **Butoir au 31/10/2026.** Passé ce jour sans verdicts, le document écrit **« mesure abandonnée »**, pas « en attente » | L'utilisateur peut **déplacer** cette date ; il ne peut pas la laisser vide. **Le gel étant levé, c'est le seul levier qui reste.** Une échéance qu'on peut manquer et qui le dit vaut mieux qu'une « obligation permanente », qui est une épitaphe |
| 10 | **La branche `audit-20260911`** | **Fusionner dans `main`** | **0 de retard**, et `main` est un **ancêtre** : avance directe, aucun conflit possible. Et `main` est ce que le monde voit d'un dépôt public — il est aujourd'hui **trompeur** |
| 12 | **`FREE_ONLY=false` est-il un état admis ?** | **Oui — mais jamais par défaut, jamais silencieux** : choix explicite, plafonné, qui **expire**. La forme du Boost | Interdire un état que le code sait produire, c'est se mentir. L'encadrer le rend visible |
| 13 | **Le contrôle de fraîcheur des descriptions** | **Oui**, et il devient **une dixième étape nommée de la CI** | Position de l'utilisateur du 19/09 : une description périmée est un risque inacceptable pour un fonctionnement automatique. Les cinq pièces sont au §5 étape 1 — zone engendrée, provenance, **`PÉRIMÉ`** plutôt qu'un nombre vieilli, fonction d'empreinte **importée** et jamais réécrite, `--check` qui sort en 1 |
| 14 | **Deux dépôts** | **Fait** le matin du 19/09 | — |
| 15 | **Les sauvegardes** | **Même butoir : premier essai de restauration avant le 31/10/2026** | Une sauvegarde compte le jour où elle a été **remise en place**. Les trois questions non vérifiées — troisième copie, sauvegarde du VPS lui-même, localisation européenne — se répondent en la jouant |
| 16 | **Où vivent les coordonnées du VPS** | **Les deux** : `.env.example` dans le dépôt privé pour lire, **secrets de CI** pour exécuter | L'un documente, l'autre exécute ; **aucun des deux ne porte de valeur en clair** |

### Ce que le plan d'origine demande et que ce document avait omis

**Contrôle de couverture fait le 19/09 au soir**, en relisant le plan d'origine section par
section contre ce document. Les dix phases P0→P9 y sont, les sept contradictions aussi, le
schéma de registre est repris en partie. **Mais quatre éléments du plan d'origine n'étaient
traités nulle part — ni repris, ni contredits, ni écartés. Ils étaient simplement absents,
ce qui est le pire des trois états.** Ils sont tranchés ici.

| Élément du plan d'origine | État avant | Ce que j'en fais |
|---|---|---|
| **Les treize mesures du tableau de bord** (l. 138-140), dont les **cinq mesures de douve** : taille du jeu de mesures, délai sortie→validé, taux de contribution **et** d'acceptation, nombre de contributeurs, conversion apprenant→Studio | **trois seulement étaient citées** (`autonomy_rate`, `bad_merges`, `rejections_by_reason`), et en passant | **À porter dans le schéma de la base de mesures** (§5 étape 4). Ce n'est pas un détail de tableau de bord : **les cinq mesures de douve sont exactement ce que la base doit produire.** Sans elles, la phrase « la copie est sans valeur sans les mesures » n'est pas vérifiable — c'est une conviction, pas un fait |
| **Les quatre seuils chiffrés** (`thresholds.yaml`, l. 83-88) : tolérance de reproductibilité ±3 %, retour arrière si le taux d'erreur monte de 2 points ou la qualité baisse de 3 %, **300 appels et 2 GPU-h par candidat**, 5 h/semaine de GPU de maintenance | **aucun repris** | Les trois premiers **entrent dans `seuils/` du dépôt privé dès la première évaluation** — avec la règle du dépôt privé : un seuil porte la mesure qui l'a posé, sinon c'est un nombre inventé. **Ceux-là viennent du plan d'origine, pas d'une mesure : ils entrent donc comme « valeurs de départ à confirmer », marquées comme telles.** Le quatrième (5 h/semaine Kaggle) **est remplacé** par le budget Modal unique décidé le 19/09 |
| **La barrière de reproductibilité** : « *reproducible (2 runs within tolerance)* » (l. 87) | **absente**, et c'est une omission de ma part | **Reprise telle quelle.** C'est la seule barrière qui attrape **un candidat qui passe par chance**, et elle ne coûte qu'un second passage. Elle a de plus un jumeau déjà inventé dans ce document sans être relié à elle : le **rejeu à code changé sur entrées réelles** (§5 étape 2). Même mécanique, deux usages |
| **Deux décisions ouvertes de l'original** (l. 148-152) : la licence de **FreeLLMAPI** avant tout fork, et les **conditions d'utilisation de Kaggle** à vérifier avant P3 | **jamais reprises** | La seconde **est déjà tenue par le code** — `contexte_partage()` coupe Kaggle automatique hors Studio personnel, et `AGENTS.md:157` cite la politique d'usage. **Close.** La première **tombe** : aucun fork de FreeLLMAPI n'est au programme de ce dépôt |

**Et deux outils de la pile d'origine ne sont nommés nulle part** : `promptfoo` et
`Crawl4AI`. **Écartés sans cérémonie**, comme Temporal et Forgejo : le dépôt a déjà sa CI,
son bac à sable et ses carnets. Les nommer pour les écarter vaut mieux que de les taire.

> **Ce que ce contrôle enseigne, au-delà des quatre lignes.** Un document qui confronte un
> autre document **doit se relire section contre section**, pas thème par thème : les quatre
> omissions ci-dessus ne sont pas des désaccords, ce sont des **angles morts** — elles ont
> survécu à une relecture adverse hors modèle et à quatre passes de rédaction, parce que
> personne ne cherchait ce qui **manquait**. C'est exactement l'argument du contrôle de
> fraîcheur retenu au point 13, appliqué à la couverture plutôt qu'à l'âge.

### L'ordre dans lequel cela se fait

Le gel étant levé, rien ne bloque plus rien. L'ordre ci-dessous n'est donc plus une
procédure, c'est un classement par **coût du retard** :

1. **Le budget Modal unique** — seul défaut connu qui coûte de l'argent réel.
2. **Le refus au démarrage** — trois conditions, et il tient sans chiffrement.
3. **Les deux dates du 31/10** — elles ne coûtent rien à poser et tout à oublier.
4. **`modal/profiles.json` supprimé, `AGENTS.md:111` retirée** — une vérité fausse de
   moins, avant que le registre n'en hérite.
5. **La fusion dans `main`** — pour que le dépôt public cesse de mentir sur lui-même.
6. **Le registre, puis le contrôle de fraîcheur en CI**, puis les évaluations.
7. **La vérification de la licence de Piper**, avant toute réorganisation.

---

## Ordre de marche recommandé

**La mesure est première pour *décider*, le registre est premier pour *coder*.** Deux
chemins distincts qui avancent en parallèle, avec trois garde-fous :

1. **Le §6 se date cette semaine** — une date d'essai, ou l'aveu écrit de son impossibilité
   avec son échéance.
2. ~~**Le registre entre par une quatorzième exception datée**, levée par l'utilisateur,
   écrite **avant** le travail, avec sa section « ce qu'elle ne couvre pas ».~~
   **Caduc depuis le 19/09** : le gel est levé (§8, décision 1). Le registre s'écrit
   directement.
3. ~~**Le gel redevient absolu à sa sortie** : plus rien de code-neuf tant que la grille des
   six tâches n'a pas ses verdicts.~~ **Caduc, même motif.** Le seul levier restant sur le
   §6 est la date butoir du 31/10/2026 (§8, point 9).

**Ce qui ferait changer cet ordre, écrit d'avance pour que le changement soit visible :**

- si l'utilisateur ne peut fournir **ni machine ni personne** avant une date lointaine,
  cette date et cette impossibilité **s'écrivent — elles ne se taisent pas** ;
- si la fusion des six copies révèle une contradiction **matérielle** de licence, le
  registre devient urgent **pour le risque**, pas pour l'hygiène ;
- ~~si une quatorzième demande touche la vidéo, la chanson ou le dialogue, la priorité devient
  le trou des budgets Modal (§7, point 11) : c'est le seul défaut qui coûte de l'argent.~~
  **Tranché le 19/09** : un seul budget partagé (§8, décision 2). Le trou se referme par
  construction, et ce correctif passe en tête de l'ordre du §8.

---

## Annexe — le plan d'origine, cité verbatim

Le plan confronté par ce document ne vit pas dans le dépôt : il est dans un fichier séparé,
en anglais. Sans cette annexe, le §1 confronterait un texte que le lecteur n'aura jamais.
Les passages ci-dessous sont cités mot pour mot, avec leur numéro de ligne d'origine.

### La thèse (l. 3-6)

> Free LLMs integrate new SOTA resources (models/tools) end-to-end with no human in the
> loop, safely.
> Success: ≥70% autonomous integrations, 0 bad merges, cost within free quotas, on 20–30
> candidates across 6 domains.
> Also prove it works with self-hosted Qwen3.8-27B only (no external API).

*Confronté au §3.*

### Les règles dures confrontées (l. 24-36)

> - Never store, proxy or share user API keys. Keys live client-side only, encrypted. *(l. 24 — §2.1)*
> - Never resell/share quota. Each user runs on own accounts. *(l. 25 — §5, étape 3 : tenue par `contexte_partage()`)*
> - Only ungated, permissively licensed resources in MVP (Apache-2.0/MIT/BSD). Log license per entry. *(l. 28 — §2.3, §2.4)*
> - Install nothing unpinned. Pin versions + hashes. Sandbox all new code. No secrets in sandbox. *(l. 29 — §2.7)*
> - Agents cannot modify: gates, rules, gateway auth, this file. Kill switch must stop all pipelines. *(l. 30 — §1 P0, §5 étape 3)*
> - Registry results DB is private (VPS). Public repo = method only (AGPL-3.0). *(l. 31 — §2.5, §7.4)*
> - Never use users' accounts, keys, quota or content for platform benefit without explicit opt-in consent + visible reward. *(l. 33 — §5, étape 4)*

### L'architecture, passage sur la passerelle (l. 40)

> Gateway (local, per user): LiteLLM (pinned) or Bifrost. […] Per provider/model/key quota
> tracker (RPM/RPD/TPM/TPD). Reads free-API availability from registry. Separate budgets:
> maintenance (low prio, capped) vs user work.

*Confronté au §1 (P2) et repris au §5, étape 4.*

### La disposition du dépôt (l. 47-59, extrait)

> ```
> /registry        schema/, roles.yaml, seeds/ (6 domains)
> /scan            sources/{hf,modelscope,openrouter,mcp_registry,glama,ossinsight,hf_papers}.py, filter.py
> /integrate       agent/ (OpenHands config, prompts), templates/ (adapter, mcp_wrapper, worker, test)
> /sandbox         Dockerfile, policy (no secrets, egress allowlist)
> /runners         kaggle/, colab/, modal/, local/
> /evals           suites/<role>/ (Inspect AI tasks), quick/ (10 tasks), full/ (50 tasks)
> /gates           gates.py, thresholds.yaml, security_scan.py, license_check.py
> /gateway         config/, quota_tracker.py, registry_sync.py
> /api             registry API (VPS)
> /studio          (phase 4) local-first UI
> /ops             backups, killswitch, runbooks/
> /metrics         dashboard, experiment_report.py
> ```

*Avec `/flows`, `/queue`, `/billing`, `/compliance` (l. 131-136) et `/learn` (l. 127) :
dix-sept répertoires, dont seize sont absents. La ligne `/sandbox` est aussi la preuve du
§5, étape 3 : le plan prévoyait une* egress allowlist *là où le dépôt n'autorise aucune
sortie.*

### Le schéma du registre (l. 64-72)

> ```yaml
> id, role, name, kind: model|tool|api, source_url, publisher, official: bool
> version, license, commercial_ok: bool, license_verified_at, gated: bool
> size_params, vram_gb_q4, runs_on: [cpu,t4,2xt4,l4,modal,api]
> languages: [], modalities: []
> scores: {quality, speed, tool_calling}, eval_suite_version, hardware_tested
> status: candidate|challenger|champion|fallback|deprecated|archived
> retired_reason, provenance: {submitter, run_id, date, signed_hash}
> ```
> Roles MVP: llm_planner, llm_coder, stt, tts, image_gen, ocr, scraper.

*Confronté au §2.4 (le champ manquant) et repris au §5, étape 1.*

### Le pipeline et le cycle de vie (l. 79-81)

> 5. GATES (all must pass): tests green; score ≥ current fallback (and ≥ champion to
>    promote); vram/speed within role limits; license ok; security scan clean; reproducible
>    (2 runs within tolerance).
> 6. MERGE → canary (10% of role traffic, 48h) → promote or auto-rollback. Else REJECT with
>    logged reason (prevents re-proposal).
> Lifecycle: candidate→challenger→champion→fallback(2–4w)→deprecated→archived. Never retire
> a role's last working option. Security issue = immediate removal.

*L'essai sur une fraction du trafic est réfuté au §5, étape 2 ; la règle « never retire a
role's last working option » est reprise telle quelle au §5, étape 1.*

### Les phases (l. 90-99, extraits confrontés)

> - P0 Setup: VPS (EU), Postgres, Forgejo+CI, backups, killswitch.
> - P2 Gateway: LiteLLM/Bifrost + quota tracker + registry sync. DoD: 1000 calls routed with
>   zero cap violations.
> - P4 Integrate+Evals+Gates: […] DoD: 3 hand-picked candidates pass end-to-end; 3 broken
>   candidates correctly rejected.
> - P5 EXPERIMENT: 20–30 real candidates, zero human touches.
> - P6 Studio (after P5 success): local-first catalog, filter by user needs […]
> - P9 Learning flow: see section below (after P8). Can start after P6; paid tier after P8.

*« P6 (after P5 success) » est la phrase autour de laquelle tourne tout ce document.*

### Hors périmètre (l. 146)

> Gated models, paid features, user contributions, >6 domains, Windows (Colab CLI
> unsupported), always-on endpoints on Kaggle/Colab.

*Trois de ces six exclusions sont déjà contredites par le dépôt : Windows (§2.2), les
fonctions payantes (§2.6), et les contributions d'utilisateurs (§5, étape 3).*

---

*Document écrit le 19/09/2026 sur `audit-20260911`, à partir de `edb2b56`. Toutes les
mesures qu'il contient ont été refaites ce jour-là, avec leur commande. Une relecture
adverse en a corrigé quinze erreurs de fait avant cette version. Le plan d'origine n'a pas
été modifié.*
