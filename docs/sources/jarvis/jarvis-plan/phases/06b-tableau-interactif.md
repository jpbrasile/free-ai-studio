> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase 6b — Tableau interactif : manipulation, stylet, vision, flux

**But** : passer d'une démonstration qu'on regarde à un tableau sur lequel on agit, et que JARVIS voit.

1. **Manipulation** : points libres déplaçables ; recalcul par le moteur unique (option A : dans le navigateur avec la même version de JSXGraph ; option B : Python, limité à 10 recalculs par seconde) ; l'événement et les nouvelles mesures sont signalés à Gemini (« AM = 3,2 ; BM = 3,2 »).
2. **Stylet / souris** : calque d'écriture libre ; « regarde » (voix) ou un bouton envoie l'image à Gemini, qui commente le raisonnement écrit.
3. **Vision par l'image** : après une manipulation ou un trait de stylet terminé, l'UI envoie une **image** du tableau (JPEG ~768 px) via `send_realtime_input`, **en plus** de l'état textuel qui reste la source fiable. Au plus 1 image/s, seulement quand le tableau change.
4. **Diffusion en flux** : le solveur envoie la leçon étape par étape (JSON Lines), en commençant par l'énoncé ; chaque étape est vérifiée dès son arrivée et le rythmeur peut démarrer avant la fin de la solution. Objectif : énoncé affiché en < 5 s.
5. **Indices visuels en mode tuteur** : chaque indice est un surlignage (`board_highlight`, « regarde ce triangle ») ; la leçon peut devenir une carte de révision (figure de l'énoncé + réponse).
6. Frise cliquable : cliquer une étape demande à Gemini de la réexpliquer.
7. Tests : événements de manipulation, débit d'images plafonné, flux interrompu (leçon partielle affichée proprement), 5 scénarios ajoutés au banc (« tu vois, quand je bouge C… », commentaire d'un tracé au stylet).

**Terminé quand** : on déplace le sommet de l'angle droit et JARVIS commente correctement ce qui change ; un raisonnement écrit au stylet est commenté ; l'énoncé s'affiche en moins de 5 s grâce au flux.
