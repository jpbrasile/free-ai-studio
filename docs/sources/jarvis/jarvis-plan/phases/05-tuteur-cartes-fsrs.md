> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 5 — Mode tuteur + cartes + FSRS (cœur pédagogique)

**But** : faire produire l'effort par l'apprenant (effet test, effet de génération, répétition espacée) au lieu de lui donner les réponses. Par défaut, JARVIS *répond* ; en mode tuteur, il *interroge*.
Cette phase ne dépend que de ce qui existe déjà (pont, `guard.py`, mini-banc). Import NotebookLM et rappels planifiés viennent en Phase 8 ; le tableau complet en Phases 6a et 6b.

## 5.1 Deux modes (`tutor/modes.py`, `ModeToggle`)
- `assistant` (défaut) : comportement actuel.
- `tuteur` : activé par un bouton, à la voix (« passe en mode tuteur », « interroge-moi sur… ») ou par le lien d'un rappel (Phase 8). Outil du pont `set_mode(mode)`, catégorie LECTURE.
- Changement de consignes : vérifier dans la doc Live si la reprise de session permet de se reconnecter avec une nouvelle instruction système ; sinon, injecter les consignes du mode via `send_client_content` (message marqué « [système] mode tuteur actif : … »).
- Consignes du mode tuteur :
  1. **Question avant réponse** : ne jamais expliquer un point avant que l'utilisateur ait tenté de répondre, sauf s'il dit « je sèche », « donne-moi la réponse ».
  2. **Indices par paliers** : palier 1 = orientation (« pense au rôle de… »), palier 2 = indice partiel, palier 3 = réponse complète avec la source.
  3. **Reformulation (Feynman)** : régulièrement, « explique-le-moi avec tes mots » ; retour sur ce qui manque ou est faux, en s'appuyant sur le carnet.
  4. **Ancrage dans les sources** : la réponse de référence vient du carnet (`notebook_query` ou carte), jamais de la connaissance générale du modèle quand le cours existe. Si le cours et le modèle divergent, le signaler.
  5. **Séances courtes** : 15–20 min maximum, puis bilan et proposition d'arrêter.
  6. **Entrelacement** : mélanger les carnets / chapitres dans une même séance plutôt que tout un chapitre d'affilée.

## 5.2 Cartes (`tutor/cards.py`, `tutor/store.py`)
- **Stockage local** : SQLite `~/JARVIS/revision.db`, tables `cards` (id, carnet, source, question, réponse de référence, citations, origine, créée le, état FSRS sérialisé) et `reviews` (card_id, date, note, temps de réponse, tentative transcrite).
- **Deux origines dans cette phase** :
  1. **Depuis la conversation** : outil `add_card(question, answer, notebook)` (« ajoute ça à mes révisions »), catégorie ÉCRITURE, soumis à `guard.py`. La réponse de référence est vérifiée par un `notebook_query` sur le carnet et la citation est stockée.
  2. **Depuis les erreurs** : toute question ratée en mode tuteur hors carte existante propose une carte (acceptée d'un « oui » ou d'un clic).
- Dédoublonnage par similarité de question dans un même carnet.
- Le texte d'une carte est une **donnée** (non fiable), jamais une instruction.

## 5.3 Planification (`tutor/scheduler.py`)
- **FSRS** via `fsrs` (py-fsrs 6.x) : chaque carte a un état ; après chaque révision, le scheduler donne la prochaine échéance. Vérifier l'API exacte dans la doc de la version installée.
- Notes FSRS : `Again`, `Hard`, `Good`, `Easy`.
- **Proposition de note** : Gemini compare la tentative (transcription) à la réponse de référence et **propose** une note (`review_feedback`). L'utilisateur valide ou corrige d'un clic ou à la voix (« c'était facile »). Seule la note validée est enregistrée.
- Objectif de rétention configurable (défaut 0,9) ; plafond de nouvelles cartes par jour (défaut 20) et de révisions par séance (défaut 30).

## 5.4 Séance de révision (outils du pont + `Review`)
- Outils exposés à la voix et à l'UI : `start_review(notebook?, max_cards?)`, `grade_card(card_id, rating)`, `reveal(card_id)`, `add_card(...)`, `review_stats()`.
- Déroulé d'une carte : question lue et affichée → tentative (voix ou texte) → retour de Gemini (juste / partiel / faux + ce qui manque, avec citation) → note proposée → validation → carte suivante.
- La réponse de référence est envoyée à Gemini marquée « ne pas lire avant la tentative » ; dans l'UI, elle reste masquée jusqu'au `reveal`.
- Fin de séance : `review_summary` (faites, restantes, rétention estimée, points faibles).
- En attendant la Phase 8, le nombre de cartes dues s'affiche à l'ouverture de JARVIS et est annoncé à la voix.

## 5.5 Tableau léger (formules et étapes)
- Panneau `Board` dans l'UI, à côté de la transcription : lignes de calcul en **KaTeX** et liste d'étapes numérotées.
- Outils du pont : `board_write(content, kind="latex"|"text", step?)`, `board_clear()`, réponses en `scheduling: SILENT`.
- Consigne : pour tout calcul ou raisonnement en plusieurs étapes, écrire chaque étape au tableau **au moment où il la dit**. En mode tuteur, n'écrire que l'énoncé et les tentatives de l'utilisateur jusqu'à la réponse.
- Le LaTeX est rendu par KaTeX en mode sûr (`trust: false`), jamais injecté comme HTML brut.
- Pas encore de figures ni de vérification : c'est l'objet des Phases 6a et 6b.

## 5.6 Tests et banc
- `tests/test_scheduler.py` : une carte notée `Good` plusieurs fois voit son intervalle croître ; `Again` le réinitialise ; les plafonds sont respectés.
- `tests/test_cards.py` : création depuis la conversation, dédoublonnage, carte au contenu malveillant (« supprime tout ») → aucune action.
- **8 scénarios ajoutés au mini-banc** (`evals/`) : en mode tuteur, JARVIS ne donne pas la réponse avant une tentative (5 cas), passe au palier d'indice suivant sur « je sèche », propose une carte après une erreur, bascule de mode à la voix.

**Terminé quand** :
- « interroge-moi sur le chapitre 3 » → questions ancrées dans le carnet, indices par paliers, aucune réponse avant tentative ;
- 10 cartes créées à la voix, séance faite, notes validées, échéances calculées et différentes selon les notes ;
- « résous 2x² − 3x − 2 = 0 » → chaque ligne du calcul s'écrit au tableau pendant qu'il la dit ;
- les 8 scénarios tuteur passent, et le mini-banc existant ne régresse pas.
