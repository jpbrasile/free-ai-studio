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
| 23/09/2026 | `/video` | « phare lancé » sur Kaggle, parti sur la carte de cet ordinateur : le réglage par défaut « À la maison si la carte est libre » passe avant « Si on loue : Kaggle », et rien ne le rappelle au moment de choisir Kaggle | non | le propriétaire |
| 23/09/2026 | `/video` | « vraiment très lent pour une vidéo d'une seconde » : clip Kaggle ebffade9, 29 min 22 s au total, dont 23 min 48 s de calcul (47 s par étape) pour 1 s de vidéo. Le journal dit « Precision : bfloat16 » sur un T4, qui ne le fait qu'en émulation : corrigé (float16 selon la génération de la carte, comme chanson et dialogue). Reste à mesurer le gain par un vrai clip, et à vérifier que l'image n'est pas abîmée en float16 | oui | le propriétaire |

## Levées

| Date | Page | Ce qui gênait | Bloquait ? | Levée par | Vue par |
|---|---|---|---|---|---|
| 23/09/2026 | `/composite` | La voix anglaise a lu tout un exposé en Markdown (« ### », « ** », numéros, le titre « English Text to Read Aloud »), et elle ne passait pas par le filtre de cohérence avec la transcription qui protège le dialogue. Le chat sait maintenant qu'il écrit pour une voix, titres et symboles sont retirés avant Piper, et le son est réécouté (même filtre que le dialogue : mots retrouvés, parole ajoutée retirée, écart signalé) | non | ce commit (tests seulement) | le propriétaire |
| 23/09/2026 | `/composite` | « la sortie markdown n'est pas restituée en pretty printing » : les textes s'affichent maintenant mis en forme (titres, gras, listes), toujours échappés | non | ce commit (tests seulement) | le propriétaire |
| 23/09/2026 | `/composite` | Le document joint ne se voyait pas : vignette d'une image, lecteur d'un son ou d'une vidéo, nom et taille d'un document, sans rien envoyer avant « Lancer » | non | ce commit (tests seulement) | le propriétaire |
| 23/09/2026 | `/composite` | « on a la voix mais pas le texte » : la chaîne image → chat → voix anglaise a marché (vérifié en vrai, la photo n'est plus envoyée comme du texte), mais seul le son revenait ; une chaîne finissant par du texte ne montrait qu'un lien « Télécharger ». La réponse porte maintenant les textes de chaque étape : le texte lu s'affiche sous la voix, les autres repliés | non | ce commit (tests seulement) | le propriétaire |
| 23/09/2026 | `/composite` | « résume et dis-moi en anglais à voix haute » avec une photo jointe : « C'est possible » (chat puis voix), puis « Aucun service gratuit branché n'a pu répondre ». Le verdict ignorait le fichier ; l'image est partie comme du texte (540 498 jetons, HTTP 400 chez les trois). Le verdict reçoit maintenant le type du fichier (jamais son contenu), le compositeur sait par quoi commencer, et le lancement refuse sur le vrai fichier avant toute étape ; « l'étape ? » dit son numéro | oui | ce commit (tests seulement) | le propriétaire |
| 23/09/2026 | le chat | on ne pouvait pas demander une chaîne depuis le chat : il renvoyait à Open WebUI, qui ne connaît pas `/composite`. Le chat reçoit maintenant les pages du Studio et donne un lien `/composite?phrase=…` qui pose la demande dans la case, sans rien lancer ; les appels internes de la chaîne en sont exclus | non | ce commit (tests seulement, à essayer dans le chat) | le propriétaire |
| 23/09/2026 | `/video` | la vidéo sur Kaggle échouait (`CUBLAS_STATUS_ALLOC_FAILED`, travail `ef554b3c…`) : la table des mots du lecteur de texte était recréée au hasard, environ 2 Go de trop sur un T4 de 14,6 Go. Rattachée à la main : le clip ebffade9 a réussi, le journal dit « Table des mots … rattachée » et 14,5 Go libres avant le calcul | oui | 5c05a3c, vérifié en vrai | le propriétaire |
| 23/09/2026 | `/video` | « en appuyant sur suivre elle ne s'affiche pas » : le suivi ne disait que « En cours depuis 1072 s », sous un formulaire resté sur 5 secondes et Modal ; le clip suivi faisait 1 s chez Kaggle, sa fiche disait « carte L4 », et « le modèle se télécharge une seule fois » est faux chez Kaggle. Le suivi dit maintenant titre, durée, fournisseur et carte, avec l'attente propre à Kaggle | non | ce commit (tests seulement) | le propriétaire |
| 23/09/2026 | `/chanson` | « elle coupe avant la fin (vue sur la partition) » : chanson Kaggle e1b68125, 60 s chantées pour une partition écrite de 72,3 s. Rien ne disait quelle durée choisir. Une chanson coupée dit maintenant la durée à choisir la prochaine fois, en précisant qu'une relance écrit une autre partition | non | ce commit (tests seulement) | le propriétaire |
| 23/09/2026 | `/chanson` | « la synchro de la partition n'est pas toujours synchrone » : quand la chanson atteint la durée choisie, le son n'est que le début de la partition écrite, et le surlignage étirait toute la partition dessus. Mesuré sur les 20 chansons réussies : partition / son de 1,01 à 1,07 sur les 9 entières, de 1,19 à 18,3 sur les 11 coupées. Une chanson coupée suit maintenant le tempo écrit, sans recalage | non | ce commit (tests seulement, à écouter après reconstruction) | le propriétaire |
| 23/09/2026 | `/chanson` | « Kaggle apparaît mais n'est pas sélectionnable » : voulu pour la version LoRA (vérifiée sur Modal seulement), mais la raison n'était écrite qu'à la fin d'un long paragraphe. L'option grisée dit maintenant « pas pour cette version (vérifiée sur Modal seulement) » | non | ce commit (tests seulement, à essayer après reconstruction) | le propriétaire |
| 23/09/2026 | `/chanson` (et `/video`, `/dialogue`) | « on a bien l'historique des chansons mais on ne peut pas les jouer » : le clic sur l'heure affichait le lecteur en haut de page, cinq secondes plus tard, loin de la liste. Chaque ligne a maintenant un bouton « ▶ Écouter » (« ▶ Voir » pour la vidéo), l'affichage est immédiat et la page remonte jusqu'au lecteur | oui | ce commit (tests seulement, à essayer après reconstruction) | le propriétaire |
| 23/09/2026 | `/video`, `/chanson`, `/dialogue` | toutes les chansons s'appelaient « chanson de 60 s au plus ». Un champ « Titre » à la création ; vide, le début de la description, des paroles ou du dialogue. Il nomme aussi le fichier téléchargé. Les travaux d'avant n'ont pas de titre : leur fiche ne gardait pas le texte | non | ce commit (tests seulement, à essayer après reconstruction) | le propriétaire, et une vérification |
| 23/09/2026 | `/video`, `/chanson`, `/dialogue` | « ma demande a disparu » : un rechargement pendant un clip loué chez Modal le faisait disparaître de la page, alors qu'il tournait encore, facturé. Chaque page liste maintenant « Vos travaux » : elle reprend seule le suivi d'un travail en cours ; on peut revoir, télécharger, supprimer (un travail en cours est arrêté puis effacé) | oui | ce commit (tests seulement, à essayer après reconstruction) | le propriétaire |
| 23/09/2026 | accueil | l'endroit où demander une chaîne n'était pas clair : aucune carte de l'accueil ne menait à `/composite` ni à `/dialogue` | non | ce commit (tests seulement, à essayer après reconstruction) | le propriétaire |
| 23/09/2026 | `/chanson`, `/dialogue` | le bouton « Arrêt d'urgence » s'affichait pour Kaggle, qui n'a pas d'annulation : il devient « Ne plus attendre », et la page dit que le calcul et le quota continuent | non | ce commit (tests seulement, à essayer après reconstruction) | le propriétaire |
| 23/09/2026 | `/composite`, `/video` | « vidéo sur votre carte » (`video_maison`) pouvait partir chez Modal sans demander : carte injoignable, image jointe, durée hors table. Avec « toujours à la maison » (le réglage des chaînes), le Studio demande maintenant « louer ou annuler ? » et rien ne part ; le réglage par défaut loue encore, pour le client sans carte | oui | `8323b00` (essayé en vrai par le propriétaire le 23/09 : question posée, clip loué chez Modal) | une lecture du code |
| 23/09/2026 | `/sandbox` | « local first before modal if ressources available, local options not always proposed » : Modal passait avant l'ordinateur et la carte d'ici | oui | `c951868`, `49af741` | le propriétaire |
| 23/09/2026 | `/composite` | le dialogue affichait « maximum inconnu » au lieu de son coût au pire | non | `c392f6b` | le propriétaire |
| 23/09/2026 | `/dialogue` | un dialogue de 63 répliques était accepté puis s'arrêtait à la 36e, carte déjà louée sur Modal | oui | `37059af` | une mesure sur la 4090 |
| 23/09/2026 | `/composite` | un document piégé (« ignore la demande… ») détournait le résumé, 10 fois sur 10 | non | `f3b5451` | une mesure sur le vrai routeur |
