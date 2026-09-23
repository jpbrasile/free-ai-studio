> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase R1 — Levée de risques technique (avant la Phase 1)

**But** : vérifier, avec des scripts jetables, que les hypothèses dont dépend l'étape A tiennent, **avant** d'écrire le vrai code. Chaque test a un critère « passe » et un **plan B** décidé à l'avance.

- **Boîte de temps : 3 soirées maximum.** Code dans `spikes/r1/`, jamais réutilisé tel quel.
- Résultats consignés dans `RISKS.md` (mesures, captures, versions testées), puis **mise à jour du `PLAN.md`** avant la Phase 1.

| # | Hypothèse testée | Test | Passe si | Plan B si échec |
|---|---|---|---|---|
| S1 | Gemini 3.8 Live est assez rapide et bon en français | Script Python minimal (micro → Live → haut-parleur), 20 tours en français | p50 fin de parole → premier son < 800 ms (le budget final de 600 ms se gagne ensuite) ; compréhension et voix jugées bonnes | Tester `gemini-3.8-live-extended-thinking` et une autre API vocale temps réel ; en dernier recours, relâcher le budget à p50 < 1 s |
| S2 | L'annulation d'écho du navigateur suffit sans casque | Page HTML de 50 lignes : micro avec AEC + lecture d'un audio pendant qu'on parle, sur **votre** machine et vos haut-parleurs | JARVIS ne se coupe pas lui-même sur 10 réponses ; le barge-in fonctionne | Casque recommandé par défaut + mode « appuyer pour parler » ; seuil VAD relevé pendant que JARVIS parle |
| S3 | Appels de fonction asynchrones et injection de contexte en cours de session | Outil lent simulé (10 s) `NON_BLOCKING` ; réponse en `WHEN_IDLE` puis `SILENT` ; `send_client_content` sans `turn_complete` ; reconnexion avec reprise de session **et nouvelle instruction système** | La conversation continue pendant l'outil ; le résultat est annoncé au bon moment ; le contexte injecté est pris en compte ; savoir si l'instruction système peut changer à la reconnexion | Outils bloquants + phrase d'attente ; changement de mode par message « [système] » au lieu de l'instruction système |
| S4 | Gemini accepte les schémas des outils MCP et choisit bien parmi ~20 | Convertir le `list_tools()` réel ; déclarer les ~20 outils voix ; 10 phrases types | Toutes les déclarations acceptées ; ≥ 8/10 bons choix d'outil | Déclarations simplifiées écrites à la main pour les outils voix ; ou méta-outil `notebooklm(action, params)` avec moins d'outils exposés |
| S5 | Le MCP NotebookLM est utilisable au quotidien | `nlm login` puis 6 appels : liste, requête, source texte, note créer/supprimer, génération d'un quiz + téléchargement | Tous réussissent ; requête p50 < 20 s ; **format du quiz/des fiches récupéré** et enregistré en fixture | Requête lente → `notebook_query_start` par défaut ; auth instable → fork Enterprise si compte Workspace ; inutilisable → plan B « RAG local » (export des sources en fichiers + recherche locale) et NotebookLM limité au Studio |
| S6 | Le « oui » arrive à temps pour la confirmation vocale | Mesurer l'écart entre l'appel d'outil de Gemini et la transcription finale du « oui », sur 20 essais | p95 < 1,5 s | Actions SENSIBLE confirmées **au clic uniquement** ; la voix reste pour les TÂCHES LONGUES |

**Décision de fin de R1** (écrite dans `RISKS.md`) :
- **Tout passe** → Phase 1 telle quelle.
- **1 ou 2 échecs avec plan B** → appliquer les plans B dans `PLAN.md`, puis Phase 1.
- **S1 ou S5 en échec sans plan B satisfaisant** → le cœur du projet est touché : arrêter et revoir l'architecture (autre API vocale ou autre source de connaissances) avant d'écrire du code.

**Terminé quand** : `RISKS.md` rempli pour S1 à S6, décision prise, `PLAN.md` mis à jour.
