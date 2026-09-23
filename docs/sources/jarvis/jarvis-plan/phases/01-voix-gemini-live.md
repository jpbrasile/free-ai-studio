> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 1 — Voix dans le navigateur + Gemini Live + latence
1. **Frontend** : bouton micro, `capture-worklet` (16 kHz, blocs 20–40 ms), `player-worklet` avec `flush()`, `StatusBar`, `Transcript` (partiel gris, final noir), champ texte de secours.
2. **Interface `VoiceBackend`** (`backends/voice/base.py`), posée dès maintenant pour permettre le mode confidentiel (Phase 13) : méthodes `connect(config)`, `send_audio(pcm)`, `send_text(text)`, `inject_context(text)`, `send_tool_result(call_id, result, scheduling)`, `interrupt()`, `close()` ; événements `transcript`, `audio`, `tool_call`, `interrupted`, `turn_complete`. `live_session.py` ne parle qu'à cette interface. **Une seule implémentation dans cette phase** : `gemini_live.py`. Ne pas sur-concevoir : l'interface suit ce dont Gemini a besoin, la Phase 13 l'ajustera.
3. **Backend** `gemini_live.py` (appelé par `live_session.py`) :
   - `client.aio.live.connect(...)` : `response_modalities=["AUDIO"]`, transcription entrée + sortie, `tools=[{"google_search": {}}, {"function_declarations": [ping]}]`.
   - Compression de fenêtre de contexte + reprise de session ; sur `GoAway`, reconnexion transparente.
   - Relais micro → `send_realtime_input` ; audio → trames `0x02` ; `interrupted` → `flush()` côté navigateur.
   - Citations de grounding Google affichées sous la réponse.
   - Un seul onglet actif ; les autres sont spectateurs.
4. **Latence** (`metrics.py` + `LatencyBadge`) : mesurer **fin de parole utilisateur → premier octet audio de JARVIS** à chaque tour. La fin de parole est le dernier bloc micro au-dessus du seuil d'énergie avant la réponse. Afficher la dernière valeur et la p50/p95 de la session ; journaliser.
   **Budget : p50 < 600 ms, p95 < 1 200 ms.**

**Terminé quand** : conversation fluide sans casque (JARVIS ne s'interrompt pas lui-même), barge-in effectif, actualité répondue avec sources, `ping` visible, budget de latence respecté sur 20 tours.
