# Frictions de la validation locale

Pendant qu'on valide le Studio sur ce PC (PLAN.md, point 15.2), **chaque gêne se note ici,
sur le moment, en une ligne** : la date, la page, ce qui gêne, et si ça bloque. Pas besoin
de l'expliquer ni de la corriger d'abord ; une phrase suffit (« la page chanson est lente »).

Deux règles :

- **Le portage sur un poste client attend qu'aucune ligne « bloquante » ne reste ouverte.**
- **C'est cette liste qui choisit la suite**, avant les idées du plan : une gêne vécue passe
  devant une amélioration imaginée.

Idée reprise du plan JARVIS (PLAN.md, point 16.4), qui met une semaine d'usage réel et un
fichier de frictions entre ses deux étapes.

## Comment remplir

| Colonne | Ce qu'on y met |
|---|---|
| Date | le jour où la gêne a été vécue |
| Page | `/sandbox`, `/dialogue`, le chat… ou « installation » |
| Ce qui gêne | ce qu'on a vu, avec les mots de la personne qui l'a vu |
| Bloque ? | **oui** si on ne peut pas s'en servir chez un client tel quel, sinon **non** |
| État | **ouverte**, ou **levée** avec le commit qui l'a levée |
| Vue par | le propriétaire, ou une mesure (quand c'est un essai qui l'a trouvée) |

## Ouvertes

| Date | Page | Ce qui gêne | Bloque ? | Vue par |
|---|---|---|---|---|
| — | — | aucune pour l'instant | — | — |

## Levées

| Date | Page | Ce qui gênait | Bloquait ? | Levée par | Vue par |
|---|---|---|---|---|---|
| 23/09/2026 | `/composite`, `/video` | « vidéo sur votre carte » (`video_maison`) pouvait partir chez Modal sans demander : carte injoignable, image jointe, durée hors table. Avec « toujours à la maison » (le réglage des chaînes), le Studio demande maintenant « louer ou annuler ? » et rien ne part ; le réglage par défaut loue encore, pour le client sans carte | oui | `8323b00` (essayé en vrai par le propriétaire le 23/09 : question posée, clip loué chez Modal) | une lecture du code |
| 23/09/2026 | `/sandbox` | « local first before modal if ressources available, local options not always proposed » : Modal passait avant l'ordinateur et la carte d'ici | oui | `c951868`, `49af741` | le propriétaire |
| 23/09/2026 | `/composite` | le dialogue affichait « maximum inconnu » au lieu de son coût au pire | non | `c392f6b` | le propriétaire |
| 23/09/2026 | `/dialogue` | un dialogue de 63 répliques était accepté puis s'arrêtait à la 36e, carte déjà louée sur Modal | oui | `37059af` | une mesure sur la 4090 |
| 23/09/2026 | `/composite` | un document piégé (« ignore la demande… ») détournait le résumé, 10 fois sur 10 | non | `f3b5451` | une mesure sur le vrai routeur |
