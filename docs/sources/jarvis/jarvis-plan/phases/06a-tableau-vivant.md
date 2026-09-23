> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 6a — Tableau vivant : leçon vérifiée + déroulé piloté par l'application

**But** : pour les maths et la géométrie, la voix seule ne suffit pas. Un modèle haut de gamme **produit la solution complète**, le code **la vérifie**, l'application **affiche les étapes une à une**, et Gemini Live **commente chaque étape** au moment où elle apparaît.

## 6a.1 Quatre rôles, séparés
```
Question (voix) ─▶ Gemini Live ─solve_visual()─▶ Solveur haut de gamme (texte, async)
                       ▲                                │ « leçon » JSON
                       │ « [système] étape n affichée : │
                       │    points clés… commente-la »  ▼
                  Rythmeur (code) ◀────────────── Validateur (moteur géométrique unique + sympy)
                       │ étape n                        │ leçon vérifiée
                       ▼                                │
                  Tableau (navigateur) : JSXGraph · KaTeX · frise des étapes · sous-titres
```
1. **Solveur** (`board/solver.py`) : modèle de raisonnement non-Live, `JARVIS_SOLVER_MODEL`, choisi en R2 (S7). Il ne parle pas : il écrit une **leçon** en JSON strict, avec les exemples validés en R2 dans son prompt.
2. **Validateur** (`board/validate.py`) : vérifie la leçon avant tout affichage (6a.3).
3. **Rythmeur** (`board/pacer.py`) : **c'est l'application, pas Gemini, qui décide quelle étape est affichée.**
4. **Narrateur** : Gemini Live. Il ne calcule pas et ne choisit pas l'étape ; il commente celle qu'on lui montre et répond aux questions.

## 6a.2 La leçon : un format déclaratif (`board/dsl.py`)
- `problem` : énoncé reformulé.
- `figure` : **construction**, pas des coordonnées. Types de cette phase : `point` (libre, position initiale), `point_on`, `midpoint`, `segment`, `line`, `ray`, `circle`, `circle_diameter`, `intersection`, `perpendicular`, `parallel`, `foot`, `bisector`, `polygon`, `angle` (marque), `length_mark`, `function_graph(expr, domaine)`, `tangent`, `label`, `text`. Le périmètre exact est celui validé en R2.
- `claims` : propriétés que la figure doit vérifier (`on(C, cercle)`, `perpendicular(d1, d2)`, `equal(AM, BM)`, `angle(A,C,B)=90`…).
- `steps[]` : pour chaque étape, `ops` (créer / montrer / surligner / masquer), `latex[]` (lignes de calcul), `key_points[]` (ce qu'il faut dire), `phase` (`énoncé` | `solution`).
- `answer` : résultat final.
- Aucun code exécutable : la leçon est une donnée.

## 6a.3 Vérification, avec une seule source de vérité géométrique
- **Un seul moteur** calcule la figure, pour la vérification **et** pour l'affichage, afin que la figure vérifiée soit exactement celle montrée. Choix fait en R2 (S8) :
  - **Option A** : JSXGraph exécuté côté serveur sous Node (`board/engine/`, petit service local appelé par Python) pour vérifier ; le navigateur utilise la même version de JSXGraph pour afficher.
  - **Option B** : moteur Python (`board/engine.py`) qui calcule les coordonnées ; le navigateur affiche ce qu'il reçoit, sans refaire de calcul géométrique.
- **Géométrie** : le moteur tire **20 positions aléatoires des points libres** et vérifie chaque `claim` à 1e-6 près.
- **Calculs** : chaque ligne `latex` est convertie en expression (liste blanche de fonctions, longueur limitée) et l'équivalence entre lignes successives est vérifiée par `sympy` **dans un sous-processus isolé avec timeout** (jamais de `sympify`/`eval` sur du texte du modèle dans le processus principal).
- **Échec** : leçon renvoyée au solveur avec l'erreur (2 tentatives max) ; sinon, étapes affichées avec un badge « non vérifié », et le narrateur le dit.

## 6a.4 Déroulé piloté par l'application (`board/pacer.py`)
- Machine à états : `attente leçon` → `étape n affichée` → `commentaire en cours` → `pause` → étape suivante.
- Pour chaque étape, le rythmeur (1) envoie `board_op` au navigateur, (2) envoie à Gemini, via `send_client_content` : « [système] Étape n/N affichée : <points clés>. Commente-la en 1 à 3 phrases, sans parler des étapes suivantes. »
- **Passage à l'étape suivante** : quand Gemini a fini de parler (fin de tour et audio lu jusqu'au bout), après une pause de 1,5 s en mode automatique, ou sur commande en mode manuel (réglable).
- **Commandes** : « suivant », « attends », « reviens », « recommence », « va à l'étape 4 », par un outil rapide `lesson_control(action, step?)` appelé par Gemini **et** par des boutons. Une question en cours de route met le déroulé en pause jusqu'à la réponse.
- Question hors leçon : `ask_solver(question)` complète la leçon ; les nouvelles étapes sont vérifiées puis ajoutées à la frise.
- **Frise des étapes** et **sous-titres** synchronisés sous le tableau.
- **Mode tuteur** : seules les étapes `énoncé` sont jouées ; la suite ne se débloque qu'après une tentative enregistrée (règle appliquée par le code si R2/S10 l'a exigé).
- **Attente du solveur** (5 à 45 s) : Gemini reformule le problème et, en mode tuteur, demande d'essayer d'abord ; une barre de progression s'affiche.
- **Vision (version texte)** : à chaque étape, Gemini reçoit l'**état textuel** du tableau (objets visibles, mesures). Les images arrivent en 6b.

## 6a.5 Tests et banc
- `tests/test_dsl.py` : chaque type se construit ; leçon avec type inconnu ou contenu exécutable → rejetée.
- `tests/test_validate.py` : propriétés vraies acceptées sur 20 tirages ; propriétés fausses (ou vraies pour une seule position) rejetées ; calcul faux détecté ; expression malveillante → rejet sans exécution, timeout respecté.
- `tests/test_pacer.py` : ordre des étapes, pause sur question, « reviens », mode tuteur bloqué avant tentative.
- **15 problèmes de référence** (Thalès, Pythagore, cercle circonscrit, hauteurs, milieu de l'hypoténuse, tangente à une courbe, second degré…) avec réponse attendue. Métriques : leçon validée, réponse juste, commentaire conforme à l'étape affichée, aucune annonce d'étape future, aucune solution avant tentative en tuteur.

**Terminé quand** :
- « démontre que dans un triangle rectangle le milieu de l'hypoténuse est à égale distance des trois sommets » → la figure se construit étape par étape, chaque étape commentée au moment où elle apparaît, « attends » et « reviens » fonctionnent ;
- même problème en mode tuteur : énoncé seul, suite débloquée après tentative ;
- ≥ 13/15 problèmes de référence validés avec réponse juste.
