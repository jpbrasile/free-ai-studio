> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 10 — Multimodal : voir et déposer
1. **Partage d'écran / webcam** : `getDisplayMedia` / `getUserMedia({video})` → 1 image/s, JPEG ~768 px → `frame` → `send_realtime_input` (vidéo). Indicateur rouge permanent ; arrêt en un clic ou à la voix ; jamais activé automatiquement.
2. **Glisser-déposer** : fichier → `POST /api/upload` vers `~/JARVIS/uploads/` → « ajouter au carnet … » → `source_add(file)` ; URL déposée → `source_add(url)`.
3. **Capture ciblée** : une frame haute définition sur demande, pour les schémas détaillés.
4. **Exercice photographié** : webcam ou photo d'une copie / d'un manuel → `solve_visual` avec l'image → la figure est reconstruite sur le tableau vivant (Phases 6a/6b) et commentée.
5. En mode tuteur : « interroge-moi sur ce que je montre » → questions et cartes créées à partir de l'image.
6. Ajouter 5 scénarios multimodaux au banc.

**Terminé quand** : « explique-moi ce graphique » (écran partagé) et « ajoute ce PDF à mon carnet Veille » (déposé) fonctionnent ; le partage s'arrête sur demande.
