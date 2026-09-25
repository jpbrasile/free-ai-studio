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
5. Le résumé s’écoute dans la page et s’enregistre (`.m4a`). Un navigateur qui ne lirait pas l’AAC
   reçoit la même chose en Opus, fabriquée à la première écoute. « 🗑️ Supprimer du Studio »
   (deux clics) efface le son, sa copie, vos documents et la fiche gardés par le Studio ; le
   carnet chez Google reste, et se supprime par « Faire de la place ». Un résumé encore en
   fabrication ne se supprime pas : rien ne l’arrête chez Google. Dans VS Code, ouvrez la page
   après avoir cliqué « Go Live ». Le carnet reste dans votre
   NotebookLM : « Ouvrir le carnet » ou « Poser une question à vos documents ».
   Quand la réponse n’est pas dans vos documents, cochez **« Chercher aussi sur le web »** : la
   recherche web rapide de NotebookLM ajoute au carnet les pages qu’elle trouve (10 au plus ;
   elles y restent, comme dans NotebookLM), puis répond. Compter 1 à 3 minutes. La page liste les
   pages ajoutées ; si rien n’est trouvé, elle le dit et répond avec vos seuls documents.
   **L’historique reste dans le Studio** : sous chaque résumé, « 📜 Questions posées » montre les
   questions posées depuis le Studio (avec citations et pages du web, lisibles même session
   refusée), puis celles posées directement dans NotebookLM. Vidéo, diapositives et infographie
   se font dans NotebookLM (« Ouvrir le carnet ») : le Studio ne les refait pas.
   Chaque question écrit aussi une ligne dans la base de mesures du poste — date, durée,
   succès ou motif du refus, recherche web ou non — **sans le texte de la question** ; rien ne
   part vers l’éditeur (PLAN-PLATEFORME, décision du 25/09/2026).

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

**Le chemin conseillé : un double-clic.** Le Studio doit tourner (`demarrer.cmd`).

1. Dans le dossier du Studio, double-cliquez sur **`brancher-notebooklm.cmd`**. La première fois,
   il installe son outil (notebooklm-py, **la version épinglée par le Studio**) dans
   `%LOCALAPPDATA%\FreeAIStudio\notebooklm` : 1 à 3 minutes.
2. Une fenêtre Chrome (Edge si Chrome manque) s’ouvre : connectez-vous à Google et attendez que
   NotebookLM s’affiche. Elle se ferme seule.
3. Le script envoie la session au Studio, puis **efface ce qui a servi** : le fichier de session et
   le profil de navigateur ouvert pour l’occasion (il restait connecté à Google). Il écrit
   « OK : NotebookLM est branché », et la page le montre avec « J’ai fini, vérifier ».

Rien à copier ni à coller, et la session ne s’affiche jamais. Il faut Python 3.10 ou plus ; le
script le dit s’il manque. `scripts\brancher-notebooklm.ps1 -Verifier` fait toute la préparation
sans ouvrir de fenêtre ni rien envoyer.

**Sans Python**, la page propose, replié, un autre chemin :

1. une extension qui exporte les cookies en JSON (par exemple « Cookie-Editor »), autorisée en
   navigation privée ;
2. une **fenêtre de navigation privée** : connexion à Google, puis `https://notebook.google.com/` ;
3. « Exporter » › « JSON » dans l’extension ;
4. fermer la fenêtre privée **sans se déconnecter** (se déconnecter tuerait la session) ;
5. coller l’export dans la page, puis « Brancher ».

Seuls les cookies de Google sont gardés : c’est la commande publique de la bibliothèque,
`notebooklm auth import-cookies`, qui fait le tri et vérifie que les cookies requis sont là.

**Une fois branchée, la session s’entretient seule.** Google périme un cookie de session
(`__Secure-1PSIDTS`) s’il ne tourne pas ; la bibliothèque conseille de le faire tourner toutes les
15 à 20 minutes. Le Studio le fait toutes les 15 minutes (`NOTEBOOKLM_ENTRETIEN_SECONDES`, 900
par défaut), au démarrage compris, et pendant un résumé long le client le fait lui-même toutes les
10 minutes. La session tournée revient dans le coffre ; le journal du Studio dit quels cookies ont
tourné (des noms, jamais une valeur) et si Google a accepté (`NotebookLM entretien : ok` ou
`ECHEC`). Studio arrêté longtemps (PC éteint, en veille) : la session peut être refusée au
redémarrage. La page montre alors **« Réparer la session »** : le même entretien, à la demande,
depuis le coffre, sans se reconnecter. Si Google refuse encore, il faut se rebrancher :
**« 🔑 Me reconnecter à Google »** sur la page ouvre `brancher-notebooklm.cmd` à votre place, et
la page se met à jour seule quand la nouvelle session arrive. Ce bouton passe par le veilleur de
mise à jour (lancé par `demarrer.cmd`, il tourne sous votre compte) : sans lui, la page ne montre
pas le bouton et le double-clic reste le chemin. Combien de temps une session tient Studio
arrêté : pas encore mesuré.

### Les carnets du Studio, et quand NotebookLM est plein

Chaque résumé crée un carnet au nom clair : **« Studio · <titre> · <date et heure> »**, par exemple
`Studio · Phares · 25/09/2026 08:40`.

Le Studio ne supprime **jamais rien tout seul**. Quand Google refuse un nouveau carnet parce que le
compte est plein, la page ouvre « Faire de la place dans NotebookLM » :

- la liste de **vos** carnets, du plus ancien au plus récent (les carnets partagés par d’autres
  n’y figurent pas) ;
- « Cocher les N plus anciens » ; un carnet sans date connue n’est jamais coché d’office ;
- une case « Je comprends que c’est définitif », sans laquelle le bouton reste grisé.

Le même bouton est disponible à tout moment, sous le formulaire.

### Quand ça casse

| La page dit | Ce qui se passe | Quoi faire |
|---|---|---|
| « La session NotebookLM a expiré… » | Google refuse la session | « Réparer la session » ; sinon « Me reconnecter à Google » (ou `brancher-notebooklm.cmd`, ou un nouvel export) |
| « …le quota de NotebookLM est atteint… » | 3 résumés du jour faits | réessayer demain |
| « Votre NotebookLM est plein… » | nombre maximal de carnets atteint | choisir les anciens carnets à supprimer dans la page |
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
