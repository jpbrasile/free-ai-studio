> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase R2 — Levée de risques pédagogique (avant la Phase 5)

**But** : avant d'investir dans le tuteur et le tableau vivant, vérifier les hypothèses qui les rendent possibles. Même règles que R1 : **boîte de temps de 4 soirées**, scripts jetables dans `spikes/r2/`, résultats dans `RISKS.md`, `PLAN.md` mis à jour avant la Phase 5.

| # | Hypothèse testée | Test | Passe si | Plan B si échec |
|---|---|---|---|---|
| S7 | Un solveur haut de gamme écrit des leçons valides dans notre format | Format de leçon minimal + 3 exemples dans le prompt ; 10 problèmes (5 géométrie, 3 fonctions, 2 algèbre) × 3 solveurs candidats ; validation automatique | ≥ 8/10 leçons validées (après au plus 2 corrections) pour au moins un solveur ; temps total < 45 s | Réduire le format (moins de types d'objets) ; commencer par fonctions + algèbre seulement ; pour la géométrie, une bibliothèque de leçons écrites et vérifiées à la main pour les exercices types |
| S8 | Une seule source de vérité géométrique est possible | Construire 10 figures avec JSXGraph **exécuté côté serveur sous Node** et vérifier les propriétés ; comparer avec un mini-moteur Python | JSXGraph tourne sous Node et donne les mêmes résultats que dans le navigateur (option A) | Option B : Python calcule tout, le navigateur n'affiche que les coordonnées reçues ; un point déplacé redemande le calcul à Python (limité à 10 fois par seconde) |
| S9 | Gemini commente fidèlement une étape imposée par l'application | Leçon factice de 6 étapes ; l'application envoie « [système] étape n affichée : … » ; 5 déroulés complets, avec « attends », « reviens », « suivant » dits en cours de route | ≥ 90 % des commentaires conformes aux points clés, sans annoncer les étapes suivantes ; les commandes vocales respectées | Narration écrite à l'avance par le solveur pour chaque étape, que Gemini lit en l'adaptant ; commandes par boutons seulement |
| S10 | Le mode tuteur tient la règle « pas de réponse avant tentative » | 10 conversations avec relances insistantes (« allez, dis-moi », « c'est quoi déjà ? ») | Aucune réponse donnée avant tentative ou avant la demande explicite « donne-moi la réponse » | **Règle appliquée par le code** : la réponse de référence n'est envoyée à Gemini qu'après qu'une tentative a été enregistrée |
| S11 | La notation proposée par Gemini est fiable | 20 tentatives enregistrées (justes, partielles, fausses) comparées à vos propres notes | ≥ 80 % d'accord sur juste / partiel / faux | Notation par l'utilisateur seul (4 boutons), Gemini se limitant au commentaire |

**Décision de fin de R2** :
- **Tout passe** → Phases 5 et 6 telles quelles.
- **Plans B appliqués** → mettre à jour les Phases 5 et 6 (périmètre, moteur choisi, mode de narration).
- **S7 en échec pour tous les solveurs** → le tableau vivant devient un **tableau de leçons préparées** (bibliothèque vérifiée à la main + calculs vérifiés par sympy) ; la Phase 6 est revue dans ce sens.

**Terminé quand** : `RISKS.md` rempli pour S7 à S11, solveur et moteur choisis, décision prise, `PLAN.md` mis à jour.
