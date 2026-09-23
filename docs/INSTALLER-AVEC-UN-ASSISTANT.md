# Installer Free AI Studio avec un assistant de codage

Ce guide s'adresse à **l'assistant de codage** (Claude Code, opencode, ou un autre) qu'une
personne a ouvert sur **son propre ordinateur** pour y installer le Studio. Il remplace, pour
cette tâche, le reste d'`AGENTS.md`, qui décrit le développement du Studio.

Ton rôle ici : installer, vérifier, et rendre la main. Tu n'es pas là pour améliorer le code.

## Ce que tu fais, dans l'ordre

1. **Le système.** Windows, macOS ou Linux. Sous Windows, les commandes ci-dessous passent par
   PowerShell. Si ton outil te donne Git Bash, il réécrit les chemins qui commencent par `/`
   avant de les passer à `docker` : lance `docker` par PowerShell, ou préfixe la commande de
   `MSYS_NO_PATHCONV=1`.
2. **Docker.** `docker info --format "{{.ServerVersion}}"` doit rendre un numéro de version.
   Un code de sortie 0 avec une sortie vide veut dire que le moteur ne tourne pas. Docker
   absent ou arrêté : dis à la personne d'installer ou d'ouvrir Docker Desktop
   (<https://www.docker.com/products/docker-desktop/>) et d'attendre la baleine verte. Ne
   l'installe pas toi-même : il demande les droits d'administrateur et souvent un
   redémarrage. « Virtualization support not detected » : suis `docs/DEPANNAGE.md`, section
   du même nom, et dis à la personne ce qu'elle doit cliquer.
3. **Le dossier.** Si tu n'es pas déjà dans le dépôt, clone-le dans `Documents` :
   `git clone https://github.com/jpbrasile/free-ai-studio.git`. Git crée lui-même le
   sous-dossier `free-ai-studio`.
4. **Le démarrage.** Le lanceur fait tout : vérifications, `.env`, mots de passe internes,
   construction, attente des services.
   - Windows : `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\demarrer.ps1`,
     c'est-à-dire ce que fait un double-clic sur `demarrer.cmd`.
   - Linux ou macOS : `./install.sh`, puis `./start.sh`.

   Le premier démarrage prend plusieurs minutes, surtout pour télécharger l'image du chat
   (5 Go). Ne l'interromps pas. Si le lanceur écrit **`ARRET :`**, arrête-toi aussi, rends
   son message mot pour mot à la personne, et ne fais que ce qu'il demande quand c'est sans
   risque. S'il dit que le Studio tourne déjà depuis un autre dossier, **ne supprime rien** :
   laisse la personne choisir.
5. **La vérification.**
   - Linux ou macOS : `./scripts/self-test.sh`.
   - Windows : `powershell -ExecutionPolicy Bypass -File .\scripts\self-test.ps1`. Il demande
     Python. Sans Python, ouvre <http://127.0.0.1:8010/diagnostic> et lis ce qu'il affiche.

   Rends le résultat tel quel, lignes `[ECHEC]` comprises. Sans clé, le test dit
   « Aucun service de chat branché » : c'est attendu, pas une panne. Le chat met parfois une
   ou deux minutes de plus que le reste à répondre la première fois ; un échec sur le chat
   juste après le démarrage se revérifie une fois, deux minutes plus tard.
6. **Rendre la main.** Dis à la personne :
   - d'ouvrir <http://127.0.0.1:8010/studio> ;
   - de cliquer **Clés** et d'y coller une clé Google Gemini gratuite, obtenue sur
     <https://aistudio.google.com/apikey>. Elle suffit pour écrire, lire une image et
     fabriquer une image.

   **La clé se colle sur la page, jamais dans ta conversation.**

## Ce que tu ne fais jamais

- **Modifier le code du dépôt.** Aucun fichier suivi par git. Le bouton « Mettre à jour » du
  Studio remplace le dossier par la version publiée : une modification locale le bloque ou
  se perd. Si quelque chose casse, tu le décris ; la correction se fait dans le dépôt
  d'origine.
- **Lire, afficher ou recopier un secret** : les valeurs de `.env`, `config/keys.json`,
  `config/sandbox-keys.json`. Pour savoir si une clé est en place, la page Clés et
  l'auto-test le disent sans la montrer.
- **Payer ou engager une dépense** : saisir une carte, acheter des crédits, activer un
  modèle payant ou le Boost, relever un plafond (`FREE_ONLY`, `ALLOW_PAID_MODELS`,
  `ALLOW_PAID_GPU`, `MAX_DAILY_COST`, `MODAL_BUDGET_USD_PAR_MOIS`).
- **Supprimer** des conteneurs, volumes ou dossiers que tu n'as pas créés, ou arrêter un
  Studio qui tourne déjà.
- **Ouvrir le Studio au réseau.** Il n'écoute que `127.0.0.1`, et c'est voulu : les clés
  sont gardées en clair sur cet ordinateur.

## Les options payantes : tu les expliques, la personne décide

Le Studio marche sans rien payer. Deux dépenses peuvent pourtant valoir la peine. Tu peux
les présenter, avec le gain et le prix. C'est la personne qui les fait, sur le site du
fournisseur, puis colle la clé sur la page Clés.

- **OpenRouter : 10 $ de crédits achetés une fois.** Les modèles gratuits d'OpenRouter
  passent alors de 50 à 1 000 demandes par jour. Le Studio ne dépense pas ce crédit : il
  force `openrouter/free` et bloque les modèles payants. Le seuil et les quotas changent :
  vérifie-les sur <https://openrouter.ai/docs/api-reference/limits> le jour où tu en parles,
  et cite la page.
- **Modal : une carte graphique louée**, pour la vidéo et la musique quand l'ordinateur n'a
  pas de carte assez forte. Modal demande une carte bancaire. Le Studio refuse avant de
  dépenser au-delà d'un plafond mensuel (`MODAL_BUDGET_USD_PAR_MOIS`, 30 $ par défaut, dont
  la moitié réservée aux tâches automatiques), et chaque page annonce le prix avant de
  lancer.

Le Boost payant est décrit dans `docs/BOOST.md`. Il reste éteint tant que la personne ne
l'allume pas elle-même.

## Si ça coince

Arrête-toi et donne à la personne trois choses :

- la commande lancée ;
- sa sortie exacte, sans aucun secret ;
- le texte du bouton **Copier ce diagnostic** de <http://127.0.0.1:8010/diagnostic>, si la
  page répond.

Les pannes déjà rencontrées et leur remède sont dans `docs/DEPANNAGE.md`. N'essaie pas trois
contournements de suite : une panne expliquée vaut mieux qu'une installation bricolée.

## Ton compte rendu final

Quatre lignes, en français simple :

1. installé ou non, et la version (la page du Studio affiche « version installée … ») ;
2. le résultat de l'auto-test, recopié ;
3. ce qu'il reste à faire à la personne (la clé Gemini, en général) ;
4. ce qui a échoué, s'il y a lieu, avec la sortie.
