> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 13 — Mode confidentiel (100 % local) et sélection du mode

**But** : pouvoir choisir, à tout moment, où partent les données. En **mode confidentiel**, aucune donnée (voix, documents, questions, tableau) ne quitte la machine. Le reste de JARVIS (pont, politique, `guard.py`, confirmations, tuteur, tableau, FSRS, UI) est **réutilisé tel quel** grâce aux interfaces posées dès les Phases 1 et 2.

Prérequis : Phase R3 terminée ; modèles locaux, remplaçant de NotebookLM et périmètre décidés dans `RISKS.md`.

## 13.1 Les trois modes

| | ☁️ Standard | 🔒 Confidentiel | 🔀 Hybride |
|---|---|---|---|
| Voix (écoute, dialogue, parole) | Gemini 3.8 Live | Chaîne locale : Kyutai STT → LLM local → Qwen3-TTS | Chaîne locale |
| Documents et carnets | NotebookLM (MCP) | Remplaçant local choisi en R3 (Open Notebook ou SurfSense) | Remplaçant local |
| Recherche web | Google Search (natif) | Désactivée par défaut | SearXNG, confirmation à chaque requête |
| Solveur du tableau | Modèle haut de gamme cloud | LLM local (périmètre fixé en R3) | Local par défaut ; cloud **sur accord explicite**, avec l'énoncé seul (aucun document, aucun historique) |
| Vision du tableau | Image + état textuel | État textuel (+ image si R3/S18 passe) | idem confidentiel |
| Révisions, cartes, FSRS | Local | Local | Local |
| Rappel planifié | Local | Local | Local |

## 13.2 Choisir le mode
- **Au démarrage** : écran de choix (le dernier mode utilisé est présélectionné) ; possibilité de fixer un mode par défaut dans `.env` (`JARVIS_PRIVACY_MODE=standard|confidential|hybrid`).
- **En cours d'usage** : sélecteur dans l'en-tête, ou à la voix (« passe en mode confidentiel »). Outil du pont `set_privacy_mode(mode)`.
- **Par carnet** : un carnet marqué `confidentiel` n'existe que dans le stockage local et **force** le mode confidentiel dès qu'il est ouvert, sélectionné ou interrogé. Un carnet NotebookLM ne peut pas être marqué confidentiel (il est déjà dans le cloud) : proposer de l'exporter vers le stockage local.
- **Indicateur permanent** : bandeau de couleur + icône (☁️ / 🔒 / 🔀) toujours visibles ; annoncé à la voix à chaque changement.
- **Règles de bascule** :
  - Standard → Confidentiel : immédiat ; la session Gemini est fermée.
  - Confidentiel → Standard ou Hybride : **nouvelle conversation, sans historique** ; rien de ce qui a été dit ou affiché en mode confidentiel n'est transmis. Si l'utilisateur veut reprendre un sujet, il le redit.
  - Une bascule demandée à la voix est une action SENSIBLE dans le sens « vers le cloud » (confirmation), directe dans le sens « vers le local ».

## 13.3 Voix locale (`backends/voice/local_cascade.py`)
- Implémente l'interface `VoiceBackend` (la même que `backends/voice/gemini_live.py`) : audio entrant, transcriptions, audio sortant, appels d'outils, interruption, injection de contexte.
- **Écoute** : serveur Kyutai STT (`stt-1b-en_fr`) en flux ; fin de parole par VAD sémantique si disponible, sinon seuil d'énergie + silence.
- **Dialogue** : LLM local via un serveur compatible OpenAI (llama.cpp, Ollama ou vLLM, choisi en R3), appels d'outils au format OpenAI ; sortie contrainte par grammaire JSON si R3/S14 l'a exigé. Les déclarations d'outils sont générées par `schema.py` au format OpenAI (même source que pour Gemini).
- **Parole** : Qwen3-TTS en flux, **dès la première phrase** générée.
- **Interruption** : quand l'utilisateur parle, arrêter la lecture (`flush()`), annuler la génération LLM et la synthèse en cours, garder la partie déjà dite dans l'historique.
- **Appels d'outils asynchrones** : l'application exécute l'outil en tâche de fond et injecte le résultat quand il arrive (même contrat que `NON_BLOCKING` côté Gemini) ; le LLM enchaîne une phrase d'attente naturelle.
- Mêmes métriques de latence (`metrics.py`, `LatencyBadge`), avec le budget fixé en R3.

## 13.4 Documents locaux (`backends/knowledge/`)
- Interface `KnowledgeBackend` : lister carnets et sources, interroger (avec citations), ajouter une source, notes, générer (podcast, résumé), supprimer.
- `notebooklm_mcp.py` (existant, via le pont MCP) et `local_notebook.py` (Open Notebook ou SurfSense via son API REST, choix R3).
- **Même politique, même garde** : chaque opération locale est classée dans les catégories existantes (LECTURE, QUESTION, ÉCRITURE, TÂCHE LONGUE, SENSIBLE) ; `guard.py` et `confirm.py` s'appliquent à l'identique.
- **Équivalents du Studio** : podcasts via le remplaçant (voix Qwen3-TTS) ou `podcastfy` ; **quiz et fiches générés par le LLM local directement en cartes** FSRS (pas de fichier intermédiaire) ; les fonctions sans équivalent (vidéo, infographie…) sont masquées en mode confidentiel, avec une mention dans la palette.
- **Import depuis NotebookLM** (optionnel) : exporter les sources d'un carnet (texte + fichiers) vers le stockage local, en mode Standard, sur demande explicite.

## 13.5 Étanchéité (`privacy.py`)
- **Construction impossible plutôt qu'interdiction** : en mode confidentiel, les clients cloud (Gemini, solveur cloud, MCP NotebookLM, Google Search) ne sont **pas instanciés** ; les outils correspondants sont retirés des déclarations et de la palette.
- **Garde réseau applicative** : toute connexion sortante du processus passe par une fonction qui refuse, en mode confidentiel, toute destination hors de `127.0.0.1` / `::1` et journalise la tentative (alerte visible dans l'UI).
- **Hybride** : seules deux sorties sont possibles, chacune confirmée à chaque fois et journalisée : requête SearXNG (texte de la requête affiché avant envoi) et solveur cloud (énoncé seul affiché avant envoi).
- **Rapport d'étanchéité** dans l'UI : connexions sortantes de la session (normalement aucune), mode actif, modèles utilisés.
- Option avancée (documentée, non obligatoire) : lancer JARVIS dans un espace réseau isolé au niveau du système pour une garantie supplémentaire.

## 13.6 Tuteur et tableau en mode confidentiel
- Mode tuteur, cartes, FSRS, rappels : inchangés (déjà locaux).
- Tableau : solveur local ; `validate.py` et le moteur géométrique inchangés ; le périmètre (types de problèmes) est celui validé en R3/S16 et affiché (« en mode confidentiel, le tableau couvre : … »).

## 13.7 Tests et banc
- `tests/test_privacy.py` : en mode confidentiel, aucun client cloud n'est construit ; toute connexion non locale est refusée (sockets interceptés) ; bascule vers le cloud = nouvelle conversation sans historique ; carnet confidentiel → force le mode.
- `tests/test_backends_contract.py` : les deux `VoiceBackend` et les deux `KnowledgeBackend` passent la même suite de tests de contrat (mêmes messages, mêmes erreurs).
- **Banc dans les deux modes** : `run_evals.py --mode confidential` rejoue les scénarios compatibles ; seuils propres au mode confidentiel fixés en R3 (par exemple ≥ 80 % de bon choix d'outil, 100 % des injections sans effet, 100 % « pas de réponse avant tentative »).
- **Test d'étanchéité de bout en bout** (S17) rejoué à chaque fin de phase ultérieure.

**Terminé quand** :
- une séance complète en mode confidentiel (question sur un carnet local, ajout d'une source, séance de révision, un problème au tableau) se déroule à la voix, dans le budget de latence de R3, avec **zéro connexion sortante** constatée ;
- la bascule Confidentiel → Standard ouvre une conversation vierge, et un carnet confidentiel force le mode ;
- le banc passe dans les deux modes avec leurs seuils respectifs.
