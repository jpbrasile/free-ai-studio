# NotebookLM — résumés audio et questions sur vos documents

NotebookLM (renommé « Gemini Notebook » par Google en juillet 2026) étudie vos sources : PDF,
documents, pages Web, vidéos YouTube, audio. Il répond avec des citations et fabrique des résumés
audio, des quiz, des cartes mentales et des rapports.

Free AI Studio le propose de **deux façons** :

| | Ouvrir NotebookLM vous-même | Résumé audio automatique (expérimental) |
|---|---|---|
| Adresse | `http://127.0.0.1:8010/notebooklm` › « Ouvrir NotebookLM vous-même » | `http://localhost:8020/notebooklm` |
| Ce que fait le Studio | rien : un lien vers Google | crée un carnet dans votre compte, y verse vos documents, demande un résumé audio **en français**, le rapporte ; questions avec citations |
| Branchement | aucun | une fois : votre session Google (voir plus bas) |
| Vos documents | vous les déposez vous-même chez Google | **partent chez Google (NotebookLM)**, dans votre compte |
| Solidité | celle de Google | dépend d’accès **non documentés** de Google, qui peuvent changer sans prévenir |

## Le résumé audio automatique

1. Ouvrez `http://localhost:8020/notebooklm`.
2. Au premier passage, suivez « Brancher NotebookLM » (ci-dessous).
3. Donnez des fichiers (PDF, `.txt`, `.md`, `.docx`) et/ou collez un texte, une consigne
   facultative, la forme (discussion approfondie, bref, critique, débat) et la durée.
4. « Fabriquer le résumé audio ». Comptez souvent 5 à 10 minutes.
5. Le résumé s’écoute dans la page et s’enregistre (`.m4a`). Le carnet reste dans votre
   NotebookLM : « Ouvrir le carnet » ou « Poser une question à vos documents ».

L’offre gratuite de Google annonce **3 résumés audio par jour**. Au-delà, la page le dit et il faut
attendre le lendemain. Google peut changer ce quota : le Studio ne promet jamais d’illimité.

### Brancher NotebookLM : ce que vous donnez

NotebookLM n’a **pas d’accès officiel pour les programmes**. Le Studio passe par la bibliothèque
libre [notebooklm-py](https://github.com/teng-lin/notebooklm-py) (licence MIT, version 0.8.2
épinglée), qui se sert de la connexion de votre compte Google.

**Ce que vous collez ouvre votre compte Google entier**, pas seulement NotebookLM. En conséquence :

- le Studio le garde **chiffré** par son coffre (`config/notebooklm/session.coffre`), jamais dans
  `.env`, ne l’affiche jamais et ne l’envoie qu’à Google ;
- il n’est ouvert, dans un dossier temporaire, que le temps d’un appel ;
- « Oublier la session NotebookLM » l’efface ;
- si vous le pouvez, utilisez un **compte Google réservé à cet usage** ;
- dans un Studio partagé (plusieurs personnes, ou ouvert depuis une autre machine), le branchement
  est **coupé** : la session serait celle d’une seule personne.

La méthode proposée dans la page :

1. une extension qui exporte les cookies en JSON (par exemple « Cookie-Editor »), autorisée en
   navigation privée ;
2. une **fenêtre de navigation privée** : connexion à Google, puis `https://notebook.google.com/` ;
3. « Exporter » › « JSON » dans l’extension ;
4. fermer la fenêtre privée **sans se déconnecter** (se déconnecter tuerait la session) ;
5. coller l’export dans la page, puis « Brancher ».

Autre chemin, si vous avez Python : `pip install "notebooklm-py[browser]"`, `notebooklm login`, puis
coller le contenu du `storage_state.json` qu’il indique.

Seuls les cookies de Google sont gardés : c’est la commande publique de la bibliothèque,
`notebooklm auth import-cookies`, qui fait le tri et vérifie que les cookies requis sont là.

### Quand ça casse

| La page dit | Ce qui se passe | Quoi faire |
|---|---|---|
| « La session NotebookLM a expiré… » | Google refuse la session | refaire « Brancher » avec un nouvel export |
| « …le quota de NotebookLM est atteint… » | 3 résumés du jour faits | réessayer demain |
| « Google a changé NotebookLM… » | l’accès non documenté a changé | mettre le Studio à jour |
| « La bibliothèque notebooklm-py manque… » | image pas reconstruite | relancer `demarrer.cmd` |

La page vérifie la session **à chaque ouverture** (`/notebooklm/etat?verifier=1` : la liste des
carnets, rien n’est fabriqué). C’est la vérification au jour le jour tant que la fumée
quotidienne automatique (PLAN.md 16.5) n’existe pas.

## Ce qui n’est pas fait

- **Pas encore d’étape NotebookLM dans « Enchaîner »** : une chaîne ne peut pas finir par
  « fais-en un résumé audio NotebookLM ». Voir PLAN.md 17.6.
- Seul le résumé audio est piloté. Quiz, cartes mentales, rapports : dans NotebookLM lui-même,
  depuis le carnet créé.
