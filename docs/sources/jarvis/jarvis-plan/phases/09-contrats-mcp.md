> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 9 — Contrats et surveillance du MCP
1. `tests/contract/` : contre le **vrai** MCP et un carnet de test, vérifier que `list_tools()` correspond à la fixture (outils ajoutés, retirés ou schémas changés) et que 8 appels types (liste, requête, ajout de source texte, note créer/supprimer, studio_status…) ont la forme attendue. **Inclure le format des quiz et fiches téléchargés** (Phase 8).
2. **Fumée quotidienne** : scénario automatique chaque matin (même mécanisme de planification OS que `jarvis revise`) → notification si échec, avec le diff du contrat.
3. Procédure de mise à jour : `uv tool upgrade` dans un environnement séparé → contrats + banc → bascule seulement si tout passe → nouvelle version figée dans `CLAUDE.md`.
4. Compte Workspace : évaluer le fork `notebooklm-enterprise-mcp` (API officielle) avec les mêmes contrats.

**Terminé quand** : une casse simulée (outil renommé ou format de quiz modifié dans une fixture) est détectée par la fumée avant usage.
