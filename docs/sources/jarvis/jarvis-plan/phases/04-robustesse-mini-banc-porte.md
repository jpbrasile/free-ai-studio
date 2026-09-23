> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 4 — Robustesse, mini-banc, porte de sortie
1. Tests unitaires :
   - `test_live_dispatch.py` : `receive()` jamais bloquée plus de 50 ms pendant qu'un appel MCP simulé dort 30 s ;
   - `test_policy.py` : tous les outils de la fixture sont classés ; un outil inconnu → SENSIBLE ;
   - `test_guard.py` : action après un résultat d'outil sans énoncé → bloquée ; e-mail absent de la transcription → bloqué ; cas légitimes → autorisés ;
   - `test_confirm.py` : oui/clic → exécuté ; non, silence, « oui mais pas celui-là », confirmation expirée, arguments modifiés → refusé ;
   - `test_bridge_origins.py` : UI → Gemini notifié ; voix → UI mise à jour.
2. Pannes simulées : MCP mort, auth expirée, timeout, `GoAway` pendant un job, onglet rechargé (l'état est récupéré).
3. **Mini-banc d'évaluation** (`evals/`) : **15 scénarios** en texte (`send_client_content`, rôle `user`) avec l'outil et les arguments clés attendus. `run_evals.py` rejoue sur un **carnet de test dédié** et affiche le taux de bon choix d'outil. Seuil : ≥ 13/15.
4. `FrictionButton` + journal JSON (outil, origine, catégorie, durée, statut, latence).
5. **Extension de la palette UI aux 43 outils** : élargir la liste affichée (hors MASQUÉ), avec un filtre « voix / tous ». Test : chaque formulaire s'affiche et envoie un appel valide sur le carnet de test (test automatisé à partir de la fixture `list_tools.json`). Corriger `schema.py`, et non les composants, si un schéma pose problème.
6. `test_confirm.py` couvre aussi le cas « oui transcrit 800 ms après le rappel » (accepté) et « oui transcrit après 2 s » (refusé).

**Terminé quand** : `uv run pytest` vert, mini-banc ≥ 13/15, les 43 formulaires utilisables, session réelle de 30 min sans plantage, budget de latence tenu.

## 🚪 Porte : une semaine d'usage réel
Utiliser JARVIS chaque jour. Chaque échec ou agacement va dans `frictions.md` (bouton UI). **Relire le fichier avant l'étape B** et réordonner les phases 10 à 12 si besoin.
La Phase R2 peut se faire **pendant** cette semaine : elle n'utilise que des scripts à part et ne touche pas au JARVIS en cours d'usage.
