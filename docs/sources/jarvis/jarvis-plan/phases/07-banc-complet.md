> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 7 — Banc d'évaluation complet
1. Étendre à **50 scénarios** (en plus des 8 scénarios tuteur et des 15 problèmes du tableau), couvrant chaque outil voix, les formulations ambiguës, les multi-carnets, les confirmations, les refus, **10 cas d'injection** et des scénarios issus de `frictions.md`.
2. **Audio réel** : enregistrer ~20 scénarios avec votre voix (micro habituel, bruit ambiant normal) dans `evals/audio/` ; `run_evals.py --audio` les injecte comme micro. Inclure 5 réponses orales en séance de révision (justes, partielles, fausses) pour mesurer la qualité des notes proposées.
3. Métriques par scénario : outil correct, arguments corrects, confirmation respectée, latence ; pour les injections, aucune action exécutée ; pour le tuteur, aucune réponse avant tentative et accord entre note proposée et note attendue.
4. Rapport HTML comparatif (avant/après) ; **règle** : tout changement de prompt, de modèle, de `voice_tools.py`, des consignes tuteur ou de version MCP doit passer le banc sans régression.
5. Ajuster `voice_tools.py`, l'instruction système et les consignes tuteur avec les résultats.

**Terminé quand** : ≥ 90 % de bon choix d'outil, 100 % des injections sans effet, 100 % des scénarios « pas de réponse avant tentative », p95 de latence dans le budget.
