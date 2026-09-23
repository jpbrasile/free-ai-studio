> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 0 — Environnement
1. `uv init`, Python 3.12. Dépendances : `google-genai` (dernière), `mcp`, `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `python-dotenv`, `pyyaml` ; dev : `pytest`, `pytest-asyncio`, `httpx`.
2. `web/` : Vite (Preact + TS).
3. Côté utilisateur :
   ```bash
   uv tool install notebooklm-mcp-cli
   nlm login
   ```
   Noter la version installée dans `CLAUDE.md` (**version figée**).
4. `.env.example` :
   ```env
   GEMINI_API_KEY=
   JARVIS_LIVE_MODEL=gemini-3.8-live
   JARVIS_HOST=127.0.0.1
   JARVIS_PORT=8765
   NOTEBOOKLM_HL=fr
   NOTEBOOKLM_DOWNLOAD_DIR=~/JARVIS/notebooklm
   NOTEBOOKLM_ALLOWED_FILE_DIRS=~/Documents:~/Downloads:~/JARVIS/uploads
   NOTEBOOKLM_QUERY_TIMEOUT=180
   NOTEBOOKLM_DISABLED_GROUPS=auth,server
   ```
5. Skill de référence dans Claude Code : `google-gemini/gemini-skills` → `gemini-live-api-dev`.

**Terminé quand** : `nlm` fonctionne ; `uv run python -m jarvis.main` sert une page sur `http://127.0.0.1:8765`, protégée par un jeton affiché dans le terminal.
