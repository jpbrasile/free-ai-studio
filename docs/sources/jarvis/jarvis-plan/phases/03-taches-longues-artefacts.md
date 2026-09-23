> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 3 — Tâches longues + lecteur d'artefacts
1. `JobManager` : `id`, outil, carnet, artefact, état, progression, début, fichier.
2. Réponse immédiate (« lancé, compte 2 à 5 minutes »), puis polling (`studio_status` avec `artifact_id`, `research_status`) toutes les 20–30 s, avec un plafond de 10 min pour le studio et de 15 min pour la recherche. Chaque changement → `job_update`.
3. Fin : `download_artifact` automatique, notification à Gemini (annoncée au prochain moment calme), carte « prêt ».
4. `ArtifactViewer` : audio, vidéo, PDF/slides, image, markdown, tableau. Micro coupé automatiquement pendant la lecture audio/vidéo.
5. Outils du pont : `jobs_list()`, `open_artifact(job_id)`.
6. Fin de recherche → carte « Importer toutes / seulement citées ».
7. Artefacts en français (`NOTEBOOKLM_HL=fr`, `language="fr-FR"` si accepté).

**Terminé quand** : « fais-moi un podcast du carnet X », on parle d'autre chose, la carte progresse, JARVIS annonce qu'il est prêt, « lance-le » le joue, micro coupé pendant la lecture.
