> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 12 — PC, vérificateur, emballage
1. `pc_control(action, args)` : liste blanche (état CPU/RAM/batterie, volume, luminosité, ouvrir une appli autorisée) ; aucun shell arbitraire ; soumis à `guard.py`.
2. **Vérificateur Jev (ou Laya)**, seulement si le banc ou `frictions.md` montre des erreurs de choix d'outil sur les actions à risque : `Noul` « cet appel correspond-il à la demande de l'utilisateur ? » sur les appels vocaux SENSIBLE / TÂCHE LONGUE ; sous le seuil, on redemande. Mode dégradé si indisponible : confirmation explicite.
3. Emballage desktop (Tauri ou pywebview) si l'onglet navigateur gêne : raccourci global pour le micro, icône de barre système.

**Terminé quand** : banc complet sans régression, et une semaine d'usage sans nouvelle friction bloquante.
