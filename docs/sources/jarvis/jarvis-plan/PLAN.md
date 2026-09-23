# PLAN.md — JARVIS (septembre 2026)

> Vue d'ensemble destinée à Claude Code. **Le détail de chaque phase est dans `phases/`** : ne lire que le fichier de la phase en cours. Structure du code et protocole : `docs/reference.md`. Règles permanentes : `CLAUDE.md`.
> Exécuter **phase par phase, dans l'ordre** ; ne pas passer à la suivante tant que le critère « Terminé quand » n'est pas rempli.
> Les API bougent vite : **en cas de doute sur une signature, vérifier la doc officielle / les skills installées plutôt que ce plan.**

## Feuille de route

| Étape | Phases | But | Note visée |
|---|---|---|---|
| *Levée de risques R1* | R1 | Tester les hypothèses techniques avant de coder, plans B prêts | — |
| **A — MVP 80/20** | 0, R1, 1 → 4 | Voix + écran + tout NotebookLM, utilisable au quotidien, sûr | 8,5 |
| *Porte* | — | Une semaine d'usage réel + `frictions.md` | — |
| *Levée de risques R2* | R2 | Tester solveur, moteur géométrique, narration, tuteur | — |
| **B — 100 %** | R2, 5 → 12 | Tuteur, tableau vivant, révision espacée, mesuré, surveillé, multimodal, extensions | 9,5 |
| **C — Confidentiel** | R3, 13 | Mode 100 % local sélectionnable (☁️ Standard / 🔒 Confidentiel / 🔀 Hybride) | 9,5 |

Les phases de l'étape B sont ordonnées par défaut, mais **`frictions.md` peut réordonner les phases 10 à 12**.
L'étape C peut être **avancée juste après la Phase 4** (par exemple pour un usage scolaire où les données ne doivent pas sortir) : les interfaces `VoiceBackend` et `KnowledgeBackend` sont posées dès les Phases 1 et 2 pour le permettre.

### Règles de réajustement (valables pour toutes les phases)
1. Chaque hypothèse risquée est testée **avant** d'être construite (R1, R2), avec un plan B écrit à l'avance.
2. Une phase qui échoue deux fois à son critère « Terminé quand », ou qui dépasse **deux fois** sa durée prévue, déclenche un arrêt : ajouter la cause dans `RISKS.md`, appliquer le plan B correspondant ou en écrire un, **mettre à jour `PLAN.md` et le fichier de phase concerné**, puis reprendre.
3. Chaque mise à jour du plan est datée en tête de `RISKS.md` (ce qui a changé et pourquoi).
4. On ne contourne jamais un échec en affaiblissant un critère de sécurité (confirmations, `guard.py`, vérification des leçons).

## Phases

| Étape | Phase | Contenu | Fichier | Durée indicative | État |
|---|---|---|---|---|---|
| A | 0 | Environnement | [`phases/00-environnement.md`](phases/00-environnement.md) | 1 soirée | à faire |
| A | R1 | Levée de risques technique | [`phases/R1-levee-risques-technique.md`](phases/R1-levee-risques-technique.md) | 3 soirées max | à faire |
| A | 1 | Voix dans le navigateur + Gemini Live + latence | [`phases/01-voix-gemini-live.md`](phases/01-voix-gemini-live.md) | 3–4 soirées | à faire |
| A | 2 | Pont MCP, sécurité, pilotage à la souris | [`phases/02-pont-mcp-securite-ui.md`](phases/02-pont-mcp-securite-ui.md) | 5–6 soirées | à faire |
| A | 3 | Tâches longues + lecteur d'artefacts | [`phases/03-taches-longues-artefacts.md`](phases/03-taches-longues-artefacts.md) | 2–3 soirées | à faire |
| A | 4 | Robustesse, mini-banc, porte | [`phases/04-robustesse-mini-banc-porte.md`](phases/04-robustesse-mini-banc-porte.md) | 3 soirées + 1 semaine d'usage | à faire |
| — | Porte | Une semaine d'usage réel + `frictions.md` (R2 possible en parallèle) | voir `phases/04-…` | 1 semaine | à faire |
| B | R2 | Levée de risques pédagogique | [`phases/R2-levee-risques-pedagogique.md`](phases/R2-levee-risques-pedagogique.md) | 4 soirées max | à faire |
| B | 5 | Mode tuteur + cartes + FSRS + tableau léger | [`phases/05-tuteur-cartes-fsrs.md`](phases/05-tuteur-cartes-fsrs.md) | 5–6 soirées | à faire |
| B | 6a | Tableau vivant : leçon vérifiée + déroulé piloté | [`phases/06a-tableau-vivant.md`](phases/06a-tableau-vivant.md) | 8–10 soirées | à faire |
| B | 6b | Tableau interactif : manipulation, stylet, vision, flux | [`phases/06b-tableau-interactif.md`](phases/06b-tableau-interactif.md) | 5–6 soirées | à faire |
| B | 7 | Banc d'évaluation complet | [`phases/07-banc-complet.md`](phases/07-banc-complet.md) | 3–4 soirées | à faire |
| B | 8 | Import NotebookLM + rappel planifié | [`phases/08-import-notebooklm-rappel.md`](phases/08-import-notebooklm-rappel.md) | 3–4 soirées | à faire |
| B | 9 | Contrats et surveillance du MCP | [`phases/09-contrats-mcp.md`](phases/09-contrats-mcp.md) | 2 soirées | à faire |
| B | 10 | Multimodal : voir et déposer | [`phases/10-multimodal.md`](phases/10-multimodal.md) | 3–4 soirées | à faire |
| B | 11 | Raisonnement et code | [`phases/11-raisonnement-code.md`](phases/11-raisonnement-code.md) | 3–4 soirées | à faire |
| B | 12 | PC, vérificateur, emballage | [`phases/12-pc-verificateur-emballage.md`](phases/12-pc-verificateur-emballage.md) | 3–4 soirées | à faire |
| C | R3 | Levée de risques du mode confidentiel (sur votre machine) | [`phases/R3-levee-risques-local.md`](phases/R3-levee-risques-local.md) | 4 soirées max | à faire |
| C | 13 | Mode confidentiel 100 % local + sélection du mode | [`phases/13-mode-confidentiel.md`](phases/13-mode-confidentiel.md) | 8–10 soirées | à faire |

Les durées sont des ordres de grandeur pour des soirées de 2 à 3 h ; un dépassement de ×2 déclenche les règles de réajustement.

## Objectif

**Étape A (MVP)** — un assistant desktop voix + écran qui :
1. converse en temps réel en français, avec barge-in, **sans casque** ;
2. cherche sur le web (Google Search natif) ;
3. pilote **tout NotebookLM** à la voix et à la souris, sur un même moteur ;
4. montre ce qu'il fait : transcription, tâches, confirmations, artefacts lisibles sur place ;
5. ne peut pas être détourné par le contenu de vos propres sources.

**Étape B (100 %)** — le rendre **pédagogue** (mode tuteur, tableau vivant où la solution d'une IA haut de gamme se construit et se commente en temps réel, révision espacée planifiée), mesurable (banc d'évaluation), surveillé (tests de contrat, fumée quotidienne), capable de voir (écran, webcam, glisser-déposer) et extensible (raisonnement, code, PC).

**Étape C (confidentiel)** — pouvoir choisir à tout moment un **mode 100 % local** où voix, documents, questions et tableau ne quittent jamais la machine, avec des modèles open source, et un mode hybride où chaque sortie vers le cloud est explicitement acceptée.

## Architecture

```
┌──────────── Navigateur (localhost) ─────────────┐
│ Micro getUserMedia (AEC + réduction de bruit)   │
│ AudioWorklet → PCM 16 kHz ─┐   ┌─ lecture 24 kHz│
│ Transcription · Carnets · Tâches · Confirmations│
│ Palette d'outils générée · Lecteur d'artefacts  │
│ Latence affichée · Bouton « friction »          │
│ (Étape B) Partage d'écran / webcam · Drag & drop│
└───────────────┬──────────────────▲──────────────┘
                │   WebSocket /ws (JSON + audio binaire, jeton)
┌───────────────▼──────────────────┴──────────────┐
│ Backend Python (FastAPI, 127.0.0.1)             │
│  live_session ──── Gemini 3.8 Live (WebSocket)  │
│       │               + google_search natif     │
│       │ tool_call                               │
│  ┌────▼──────────────────────────────────────┐  │
│  │ Bridge : schémas · politique · garde anti- │  │
│  │ injection · confirmation · jobs · contexte │◀─┼── actions UI
│  └────┬──────────────────────────────────────┘  │
└───────┼─────────────────────────────────────────┘
        │ stdio (session persistante, version figée)
   notebooklm-mcp (43 outils)
```

### Principes
1. **Gemini choisit l'outil pour la voix.** Pas de routeur séparé.
2. **Un seul moteur voix + souris** : tout passe par `Bridge.call(tool, args, origin)`.
3. **Pont générique** : outils découverts par `list_tools()`, convertis en déclarations Gemini et en formulaires UI.
4. **Deux périmètres d'outils** : environ 20 outils exposés à la voix (liste curée). L'UI démarre avec ces mêmes 20 (Phase 2), puis passe aux 43 une fois la génération de formulaires validée (Phase 4).
5. **Contexte partagé** : ce qui est fait à la souris est signalé à Gemini, et l'inverse.
6. **Seul l'utilisateur autorise une action sensible**, jamais le contenu d'un résultat d'outil.
7. **Politique en code**, fail-closed pour tout outil inconnu.
8. **La boucle de réception Gemini ne bloque jamais** (`asyncio.create_task`).
9. **Moteurs interchangeables** : la voix passe par une interface `VoiceBackend` (Gemini Live ou chaîne locale) et les documents par `KnowledgeBackend` (NotebookLM ou remplaçant local). Tout le reste (pont, politique, garde, tuteur, tableau) ignore quel moteur tourne.
10. **Confidentialité par construction** : en mode confidentiel, les clients cloud ne sont pas instanciés, et toute connexion hors de la machine est refusée.

## Stack

| Rôle | Choix | Notes |
|---|---|---|
| Voix | `gemini-3.8-live` | Appels de fonction async (`NON_BLOCKING`) par défaut. **Ne pas** envoyer `thinking_level` / `thinking_config`. Entrées texte, audio, images, vidéo. |
| Voix + raisonnement (étape B) | `gemini-3.8-live-extended-thinking` | Fonctions async uniquement ; suivre `interaction_status` (`IN_PROGRESS` / `IDLE`). |
| Second cerveau | `notebooklm-mcp-cli` → `notebooklm-mcp` (stdio) | Non officiel. Auth `nlm login`. 43 outils. **Version figée.** Compte Workspace : envisager le fork `notebooklm-enterprise-mcp` (API officielle Discovery Engine). |
| Backend | Python 3.12, `uv`, FastAPI + uvicorn, `google-genai`, `mcp` | Lié à `127.0.0.1`, jeton exigé. |
| Frontend | Vite + TypeScript + Preact | Build statique servi par FastAPI ; rendu JSON Schema maison et léger. |
| Audio | `getUserMedia` (echoCancellation, noiseSuppression, autoGainControl) + AudioWorklets | 48 → 16 kHz en capture ; lecture 24 kHz avec `flush()`. |
| Tableau (étape B) | JSXGraph (géométrie dynamique), KaTeX (formules), `sympy` (vérification des calculs) | **Un seul moteur géométrique** pour vérifier et afficher (JSXGraph sous Node ou moteur Python), choisi en R2. |
| Solveur (étape B) | modèle de raisonnement non-Live, `JARVIS_SOLVER_MODEL` | Choisi en R2 puis confirmé par le banc : `deepseek-v4-pro`, Gemini Pro texte ou Claude. Sortie JSON stricte. |
| Voix locale (étape C) | Kyutai STT `stt-1b-en_fr` → LLM local (Qwen3.6-27B, Gemma 4 31B/12B selon la carte) via serveur compatible OpenAI (llama.cpp, Ollama ou vLLM) → Qwen3-TTS (Apache 2.0) | Choix final et budget de latence fixés en R3 sur votre machine. Matériel visé : ~24 Go de mémoire vidéo ou Mac 32–64 Go. |
| Documents locaux (étape C) | Open Notebook (`lfnovo/open-notebook`, MIT) ou SurfSense, via API REST | Choisi en R3 ; recherche web optionnelle via SearXNG auto-hébergé (mode hybride). |
| Révision espacée (étape B) | `fsrs` (py-fsrs 6.x), SQLite local, `desktop-notifier` | Planification par le planificateur de l'OS (cron / launchd / Planificateur de tâches) pour que les rappels arrivent même si JARVIS est fermé. |

## Risques
- **MCP non officiel** : il peut casser à tout moment. En étape A, version figée ; en étape B, contrats et fumée quotidienne. C'est le risque résiduel qui empêche le 10/10.
- **Injection via les sources** : traitée dès l'étape A (`guard.py`) et mesurée en étape B.
- **Sécurité locale** : `127.0.0.1` + jeton sur `/ws` et `/api/*`.
- **Partage d'écran** : tout ce qui est visible part chez Google ; indicateur permanent.
- **Partage de carnets** : `notebook_share_public` → SENSIBLE.
- **Pédagogie** : un tuteur trop bavard recrée l'illusion de compétence. Le banc vérifie qu'aucune réponse n'est donnée avant une tentative, et c'est l'utilisateur qui valide chaque note.
- **Figures fausses** : un solveur peut se tromper. Aucune figure ni calcul n'est présenté comme vérifié sans passer `validate.py` ; sinon, badge « non vérifié » à l'écran et à la voix.
- **Désynchronisation voix / tableau** : évitée par construction, puisque l'application choisit l'étape affichée (`pacer.py`) ; la conformité des commentaires est mesurée en R2 puis au banc.
- **Hypothèses non vérifiées** (latence, AEC, schémas, format des quiz, solveurs, moteur) : testées en R1/R2 avant de construire, avec plans B.
- **Mode confidentiel** : qualité (voix française, raisonnement, solveur) et latence inférieures à la version cloud, et dépendantes du matériel ; mesurées en R3, périmètre réduit affiché clairement si besoin. Toute fuite réseau est un défaut bloquant (test d'étanchéité rejoué à chaque phase).
- **Format des quiz/fiches NotebookLM** non documenté officiellement : le parser s'appuie sur une fixture réelle et échoue proprement (message + carte non importée) si le format change.

## Commande de lancement

```bash
claude "Lis PLAN.md et CLAUDE.md, puis phases/00-environnement.md et phases/R1-levee-risques-technique.md. Exécute la Phase 0 puis la Phase R1 : écris les scripts jetables dans spikes/r1/, en vérifiant chaque appel google-genai avec la skill gemini-live-api-dev, et remplis RISKS.md. Pour les tests qui demandent ma voix ou mes haut-parleurs (S1, S2, S6), prépare le script et dis-moi exactement quoi faire. Arrête-toi à la fin de R1 : présente la décision (go / plans B / revoir l'architecture) et propose les modifications de PLAN.md et des fichiers de phase avant de toucher à la Phase 1."
```

Pour chaque phase suivante :

```bash
claude "Lis PLAN.md, CLAUDE.md et phases/<fichier de la phase>. Exécute cette phase jusqu'à son critère 'Terminé quand', mets à jour l'état dans PLAN.md et RISKS.md si besoin, puis arrête-toi et résume ce que je dois vérifier."
```
