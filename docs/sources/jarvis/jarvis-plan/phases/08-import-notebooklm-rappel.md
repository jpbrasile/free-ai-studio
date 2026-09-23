> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 8 — Import NotebookLM + rappel planifié (le « cron »)

## 7.1 Import des fiches et quiz NotebookLM (`tutor/cards.py`)
- `studio_create(artifact_type="flashcards" | "quiz")` (TÂCHE LONGUE, confirmation habituelle) → `download_artifact` → parser → une carte par question, avec carnet et source d'origine.
- **D'abord** : générer un quiz et des fiches sur le carnet de test, enregistrer les fichiers téléchargés dans `tests/fixtures/`, écrire le parser contre ces fixtures. Si le format change, échec propre : message + aucune carte importée à moitié.
- Outil `import_cards(notebook, kind)` exposé à la voix et à l'UI ; combiné avec le JobManager (« fais-moi des fiches du chapitre 3 et ajoute-les à mes révisions » → job → import automatique à la fin).
- Fin de séance : pour les points faibles, proposer un **podcast ciblé** ou de **nouvelles fiches** NotebookLM (TÂCHE LONGUE).

## 7.2 Rappel planifié (`tutor/reminder.py`)
- CLI `uv run jarvis revise --notify` : ouvre `revision.db`, compte les cartes dues, et si > 0 envoie une notification bureau (`desktop-notifier`) : « 14 cartes à revoir (~8 min) ». Un clic ouvre `http://127.0.0.1:8765/?mode=tutor&start=review` et démarre JARVIS si nécessaire.
- **Planification par l'OS** (fonctionne même si JARVIS est fermé), installée par `uv run jarvis revise --install-schedule --at 18:30` :
  - Linux : entrée crontab (`30 18 * * * …/jarvis revise --notify`) ;
  - macOS : `~/Library/LaunchAgents/com.jarvis.revise.plist` (launchd) ;
  - Windows : tâche `schtasks /Create /SC DAILY /ST 18:30 …`.
  `--uninstall-schedule` pour retirer ; `--status` pour vérifier.
- Options : deuxième créneau (matin), jours de repos, silence si 0 carte due, rattrapage si l'ordinateur était éteint à l'heure prévue (au démarrage suivant : une seule notification, pas de rafale).
- **Bilan hebdomadaire** (dimanche) : rétention de la semaine, régularité, carnets négligés ; affiché dans l'UI et résumé à la voix à la prochaine ouverture.
- Aucune donnée ne quitte la machine pour le rappel (tout est local).

## 7.3 Tests
- `tests/test_cards.py` : import des fixtures quiz et fiches ; fichier altéré → échec propre, aucune carte partielle.
- `tests/test_reminder.py` : 0 carte due → pas de notification ; installation/désinstallation génèrent la bonne entrée pour chaque OS (tests sur le texte généré, sans toucher le vrai planificateur) ; rattrapage → une seule notification.
- 3 scénarios ajoutés au banc (import à la voix, podcast ciblé proposé, lancement d'une séance depuis le lien du rappel).

**Terminé quand** :
- « fais-moi des fiches du chapitre 3 et ajoute-les à mes révisions » → cartes importées et visibles dans `Review` ;
- le rappel planifié à H+2 min déclenche une notification, et le clic ouvre JARVIS directement en séance ;
- le bilan hebdomadaire s'affiche avec des chiffres cohérents sur une semaine d'historique simulé.
