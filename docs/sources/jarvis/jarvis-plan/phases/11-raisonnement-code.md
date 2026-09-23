> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 11 — Raisonnement et code
1. Tester `gemini-3.8-live-extended-thinking` sur le banc (gestion `interaction_status`) ; l'adopter s'il gagne sans casser la latence des tours simples. Sinon, l'utiliser en option (par exemple en mode tuteur pour les maths).
2. `deep_reasoning(problem)` pour les questions **sans visuel** (code, architecture, preuve textuelle) : réutiliser le client du solveur de la Phase 6a. Si DeepSeek : `AsyncOpenAI(base_url="https://api.deepseek.com")`, `deepseek-flash` par défaut, `deepseek-v4-pro` pour les cas durs ; lire `message.content` ; **jamais `deepseek-reasoner`** ; timeout 120 s ; réponse courte pour la voix, détail complet dans l'UI.
3. `run_code(code, language)` dans une sandbox isolée (Docker sans réseau ou E2B) ; sortie et graphiques affichés dans l'UI ; catégorie TÂCHE LONGUE.
4. Scénarios ajoutés au banc.

**Terminé quand** : une démonstration et un calcul sur données passent par le bon outil, avec le résultat vérifiable à l'écran.
