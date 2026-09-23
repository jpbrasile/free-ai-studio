# Référence technique — JARVIS

> Consulté par les phases selon les besoins ; pas besoin de le relire en entier à chaque session.

## Structure cible

```text
jarvis/
├── pyproject.toml
├── .env.example
├── CLAUDE.md
├── RISKS.md                 # résultats R1/R2, décisions, historique des réajustements
├── spikes/                  # scripts jetables de R1 et R2 (jamais importés par jarvis/)
├── jarvis/
│   ├── main.py · config.py · server.py · protocol.py
│   ├── live_session.py      # Gemini Live : connexion, receive, reprise, GoAway
│   ├── transcript.py        # historique horodaté
│   ├── metrics.py           # latences, compteurs, journal JSON
│   ├── privacy.py           # mode actif, garde réseau, journal des sorties (étape C)
│   ├── backends/
│   │   ├── voice/
│   │   │   ├── base.py          # interface VoiceBackend (Phase 1)
│   │   │   ├── gemini_live.py   # Gemini 3.8 Live (Phase 1)
│   │   │   └── local_cascade.py # Kyutai STT → LLM local → Qwen3-TTS (Phase 13)
│   │   └── knowledge/
│   │       ├── base.py          # interface KnowledgeBackend (Phase 2)
│   │       ├── notebooklm_mcp.py# via le pont MCP (Phase 2)
│   │       └── local_notebook.py# Open Notebook ou SurfSense, API REST (Phase 13)
│   ├── bridge/
│   │   ├── __init__.py      # Bridge.call(tool, args, origin)
│   │   ├── mcp_client.py    # session stdio persistante + redémarrage
│   │   ├── schema.py        # JSON Schema → FunctionDeclaration + schéma UI
│   │   ├── voice_tools.py   # liste curée des outils exposés à la voix
│   │   ├── policy.py        # (outil, args) → catégorie
│   │   ├── guard.py         # anti-injection : provenance, marquage, blocage
│   │   ├── confirm.py       # confirmation vocale vérifiée / clic UI
│   │   ├── jobs.py          # tâches longues
│   │   ├── context.py       # carnets, sélection UI
│   │   └── formatting.py    # résumés voix, fichiers complets sur disque
│   ├── tutor/               # (étape B, Phases 5 et 8)
│   │   ├── modes.py         # assistant / tuteur : consignes et bascule
│   │   ├── cards.py         # cartes créées à la voix (Ph. 5), import quiz/fiches NotebookLM (Ph. 8)
│   │   ├── store.py         # SQLite local : cartes + historique de révision
│   │   ├── scheduler.py     # FSRS : prochaine date de révision
│   │   └── reminder.py      # CLI `jarvis revise --notify` lancée par l'OS (Ph. 8)
│   └── board/               # (étape B, Phases 6a et 6b)
│       ├── dsl.py           # format « leçon » : objets, étapes, propriétés
│       ├── solver.py        # appel au modèle haut de gamme, diffusion en flux
│       ├── validate.py      # vérification : 20 tirages + calculs sympy isolés
│       ├── pacer.py         # rythmeur : l'application choisit l'étape affichée
│       └── engine.py | engine/  # moteur géométrique unique (Python, ou JSXGraph sous Node) — choisi en R2
├── web/src/
│   ├── main.tsx · ws.ts
│   ├── audio/capture-worklet.ts · audio/player-worklet.ts
│   └── components/ Transcript · StatusBar · LatencyBadge · Notebooks ·
│       ToolPalette · ConfirmCard · Jobs · ArtifactViewer · FrictionButton ·
│       (étape B) ModeToggle · Review · Board · StepTimeline · PenLayer ·
│       ScreenShare · DropZone
├── evals/                   # étape A : mini-banc ; étape B : banc complet
│   ├── scenarios.yaml
│   ├── audio/               # (étape B) enregistrements
│   └── run_evals.py
└── tests/
    ├── fixtures/            # list_tools.json, réponses MCP enregistrées
    ├── test_schema.py · test_policy.py · test_guard.py · test_confirm.py
    ├── test_jobs.py · test_bridge_origins.py · test_live_dispatch.py
    └── contract/            # (étape B) tests contre le vrai MCP
```

## Protocole WebSocket

- **Audio binaire** : préfixe `0x01` micro (client → serveur, PCM16 16 kHz), `0x02` voix (serveur → client, PCM16 24 kHz).
- **Client → serveur** : `auth {token}` · `mic {on|off}` · `tool_call {tool, args}` · `confirm {confirmation_id, accepted}` · `select {notebook_id, source_ids[]}` · `text {content}` · `friction {note}` · (B) `mode {assistant|tutor}` · `grade {card_id, rating, attempt_text?}` · `reveal {card_id}` · `board_event {kind: moved|stroke|step_click, data}` · `lesson_control {action, step?}` · `board_snapshot {jpeg_b64, state}` · `frame {mime, data_b64}` · (C) `privacy_mode {standard|confidential|hybrid}` · `egress_confirm {request_id, accepted}`
- **Serveur → client** : `state {listening|speaking|thinking|tool}` · `transcript {role, text, final}` · `interrupted` · `latency {turn_ms}` · `tool_started {id, tool, args, origin}` · `tool_result {id, summary, citations[], file?}` · `confirm_request {confirmation_id, summary, category}` · `job_update {job_id, kind, status, progress?, file?}` · `notebooks {items[]}` · `tools {items[{name, category, voice, description, ui_schema}]}` · (B) `mode {current}` · `review_card {card_id, question, hint_level, notebook}` · `review_feedback {card_id, correct, missing[], proposed_rating}` · `review_summary {done, due_left, retention}` · `board_lesson {lesson_id, figure, steps_meta}` · `board_op {step, ops[], latex[]}` · `board_highlight {object_ids}` · `lesson_state {step, total, status}` · (C) `privacy_state {mode, cloud_clients: [], egress_log[]}` · `egress_request {request_id, destination, payload_preview}` · `error {message}`
