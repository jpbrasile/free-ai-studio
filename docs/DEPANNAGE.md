# Dépannage

Ce fichier n'est pas une liste de commandes. Il rassemble les pannes **réellement
rencontrées** sur un ordinateur neuf, avec ce qui les a causées et ce qui les a
réglées — chacune vérifiée par une mesure, pas par une supposition.

**Avant tout : le Studio sait se diagnostiquer lui-même.** Si les pages
répondent, ouvrez <http://127.0.0.1:8010/diagnostic>. Elle teste la chaîne
maillon par maillon, dit où ça casse, propose un bouton **Réparer la liaison**,
et un bouton **Copier ce diagnostic** pour montrer le résultat à quelqu'un. Aucune
clé n'y figure : d'une clé on ne montre que sa longueur et une empreinte.

---

## Docker : « Virtualization support not detected »

C'est la panne numéro un sur un PC neuf, et elle n'a rien à voir avec le Studio.
Docker Desktop a besoin d'une machine Linux ; Windows ne la lui donne que si
trois choses sont en place. Elles se vérifient dans cet ordre.

`demarrer.cmd` fait ce diagnostic tout seul et affiche la marche à suivre
correspondante. Ce qui suit est la version longue.

### Le piège, mesuré le 09/09/2026

La vérification « évidente » donne un **faux diagnostic**. Sur une machine qui
marche parfaitement :

```
HypervisorPresent             : True
VirtualizationFirmwareEnabled : False
VMMonitorModeExtensions       : False
```

Dès qu'un hyperviseur tourne, Windows s'exécute *au-dessus* de lui et ne voit
plus les drapeaux bruts du processeur. Ces deux dernières valeurs ne veulent donc
dire quelque chose **que si aucun hyperviseur ne tourne**. La valeur qui tranche
est **`HypervisorPresent`**.

Deuxième mesure, qui contraint l'installateur : `wsl --status` fonctionne sans
élévation (code 0), tandis que `Get-WindowsOptionalFeature -Online` **exige
l'élévation** — donc inutilisable dans un script lancé par double-clic.

### 1. L'interrupteur du processeur

`Ctrl + Maj + Échap` → **Performance** → **Processeur**. Ligne **Virtualisation**.

- **Activé** → passez au point 2.
- **Désactivé** → il faut le basculer dans le micrologiciel de la carte mère :
  Paramètres → **Système** → **Récupération** → **Démarrage avancé** →
  *Redémarrer maintenant*, puis **Dépannage** → **Options avancées** →
  **Changer les paramètres du microprogramme UEFI**.
  Dans `Advanced` ou `CPU Configuration` : **Intel Virtualization Technology
  (VT-x)** ou, sur AMD, **SVM Mode** → `Enabled`. Enregistrer et quitter (F10).

Ce chemin évite d'avoir à deviner la touche à marteler au démarrage.

### 2. Les composants Windows

C'est la cause la plus fréquente quand le point 1 dit « Activé ». Installer WSL2
ne coche pas toujours ce qu'il faut.

Touche Windows → `fonctionnalités windows` → **Activer ou désactiver des
fonctionnalités Windows**. Cocher exactement ces deux-là, et rien d'autre :

- **Plateforme de machine virtuelle**
- **Sous-système Windows pour Linux**

**Ni Hyper-V, ni « Plateforme d'hyperviseur Windows » ne sont nécessaires** —
mesuré le 09/09/2026 sur une machine qui marche : `HypervisorPlatform` y est à
l'état *non activée*. Docker passe par WSL2.

Puis **redémarrer l'ordinateur**. C'est le geste qu'on saute et qui coûte une
heure : tant que la machine n'a pas redémarré, la case est cochée et **rien n'a
changé**. Fermer et rouvrir Docker Desktop ne suffit pas.

Déjà redémarré, les deux cases cochées, et Docker ne démarre toujours pas ?
L'hyperviseur peut être coupé au démarrage de Windows : certains logiciels
changent le réglage `hypervisorlaunchtype`. Dans une invite de commandes
**ouverte en administrateur** : `bcdedit /set hypervisorlaunchtype auto`, puis
redémarrer. Ce cas n'a pas été rencontré ici : il se déduit de ce que lit
`demarrer.cmd`, qui ne peut pas lire ce réglage sans droits d'administrateur.

`demarrer.cmd` lit l'état réel de ces deux cases — `Win32_OptionalFeature` est
lisible **sans élévation**, contrairement à `Get-WindowsOptionalFeature` — et il
distingue les deux situations que l'on confond toujours : *une case manque* (il
dit laquelle) et *les cases sont mises mais l'ordinateur n'a pas redémarré*.

### 3. WSL lui-même

Test sans terminal : menu Démarrer → application **Ubuntu**. Si une fenêtre noire
s'ouvre sur une invite `vous@machine:~$`, WSL fonctionne. Sinon, Docker Desktop
propose souvent lui-même de le réparer au démarrage ; sinon, le noyau WSL :
<https://aka.ms/wsl2kernel>.

### 4. Docker regarde du mauvais côté

Docker Desktop → **Settings** → **General** → **Use the WSL 2 based engine** doit
être coché.

### 5. Un Docker Desktop ancien, déjà installé

Mesuré le 13/09/2026 sur un ordinateur d'essai, avec un Docker Desktop de 2023
(client 23.0.5) : moteur arrêté, `docker info` rendait **le code 0** et une
sortie vide. `demarrer.cmd` annonçait « Docker tourne », la construction
échouait plus loin (`error during connect … docker_engine`), et le diagnostic
de virtualisation ne s'affichait jamais. Corrigé : `demarrer.cmd` exige
maintenant un numéro de version du moteur. Mettre Docker Desktop à jour reste
une bonne idée : il le propose lui-même au démarrage.

---

## « Le démarrage a échoué » et les erreurs 500

**Une erreur 500 affichée par Docker Desktop n'est pas une panne distincte.**
Docker Desktop est une façade qui parle à un moteur Linux ; quand ce moteur ne
démarre pas, tout ce qui l'interroge reçoit *500 Internal Server Error*. Ne
cherchez rien du côté du 500 : réglez le démarrage du moteur (section
précédente), le 500 disparaît avec lui.

**Si le message vient de la fenêtre noire de `demarrer.cmd`**, il lit l'erreur
de Docker et nomme la cause : moteur arrêté, disque plein, porte prise, ou
magasin d'images de Docker qui répond mal (erreur 500, 502, « connection
reset » : relancer suffit le plus souvent). Jusqu'au 13/09/2026, il parlait
toujours du magasin d'images, y compris pour un moteur arrêté. Dans tous les
cas, le rapport complet s'ouvre dans le Bloc-notes
(`%TEMP%\free-ai-studio-demarrage\erreur-demarrage.txt`) : il est fait pour
être montré tel quel.

---

## Le chat ne propose aucun modèle

Symptôme : le menu déroulant des modèles est vide. On croit naturellement que la
clé du fournisseur est mauvaise. **Elle n'y est pour rien** — la liste des modèles
du routeur est rendue même sans aucune clé de fournisseur.

**Le geste à faire d'abord**, dix secondes : recharger l'onglet du chat avec
`Ctrl + Maj + R`. Le menu est rempli **une seule fois, au chargement de la page**.
Un onglet resté ouvert depuis avant une réparation affichera une liste vide
indéfiniment.

**La cause de fond, mesurée.** Open WebUI recopie le mot de passe interne du
Studio dans **sa propre base** au tout premier démarrage, puis n'écoute plus la
variable d'environnement. Le jour où ce mot de passe change, le chat présente
encore l'ancien, le routeur répond 401, et Open WebUI affiche une liste vide sans
un mot d'explication.

Reproduction du 09/09/2026 :

```
avant   clé gardée par le chat 246ac2a8f3a0, attendue par le routeur 3f6383c0d54c
        modèles proposés à l'utilisateur : []
après   clé gardée par le chat 3f6383c0d54c
        modèles proposés à l'utilisateur : free-ai-auto, arena-model
```

Détail qui explique pourquoi le défaut a survécu : interrogé depuis le conteneur
du chat *avec la variable d'environnement*, le routeur répondait **200 dans les
deux cas**. L'environnement disait une chose, la base une autre. Seule la liste
vue par l'utilisateur révélait la panne — d'où le contrôle ajouté à l'auto-test,
qui lit `/api/models`, c'est-à-dire exactement le menu déroulant.

**Correctif en place** : le routeur vérifie et répare cette liaison à chaque
démarrage. Il n'écrit que si la valeur gardée diffère, donc ce que vous réglez
vous-même reste.

**S'il faut réparer à la main**, deux chemins, du plus doux au plus radical :

1. <http://127.0.0.1:8010/diagnostic> → bouton **Réparer la liaison**, puis
   `Ctrl + Maj + R` sur l'onglet du chat.
2. Docker Desktop → **Volumes** → supprimer `free-ai-studio_open-webui-data` →
   relancer `demarrer.cmd`. Open WebUI repart d'une base neuve. Vous perdez
   l'historique de conversation, rien d'autre.

---

## Le chat ne s'ouvre pas : page vide sur le port 3000

Deux cas, tous deux vus le 13/09/2026.

**Premier démarrage.** Open WebUI met plusieurs minutes à s'ouvrir la première
fois, bien après la page du Studio. `demarrer.cmd` attend maintenant le chat
avant d'ouvrir la page, et la page du Studio dit « Le chat démarre encore »
tant qu'il ne répond pas ; elle se met à jour seule.

**Le relais de Docker coincé.** Le navigateur affiche `ERR_EMPTY_RESPONSE`.
Mesuré sur l'ordinateur de développement : Open WebUI répondait normalement
*dans* Docker, mais le relais de Docker Desktop vers le port 3000
(`com.docker.backend.exe`) acceptait la connexion et ne transmettait rien.
`docker compose restart open-webui` a suffi : la page a répondu en 0,27 s.
`demarrer.cmd` fait ce redémarrage lui-même dans ce cas précis. Sinon :
redémarrer Docker Desktop, puis relancer `demarrer.cmd`.

---

## « Image » rend une réponse en texte

Le réglage Images d'Open WebUI garde **sa propre copie** du mot de passe
interne du Studio, posée au premier démarrage. Si ce mot de passe change — un
`.env` refait, ou recopié d'un autre ordinateur —, le chat est réparé mais pas
les images : le routeur refuse la demande, et le modèle répond en texte.
Mesuré le 13/09/2026 sur l'ordinateur de développement : clé gardée par le
réglage Images différente du mot de passe interne, alors que le chat marchait.

**Correctif en place** : comme pour le chat, le routeur vérifie cette copie à
chaque démarrage, et le bouton **Réparer la liaison** du diagnostic aussi. Il
ne touche qu'à un réglage qui vise encore le Studio : un autre moteur choisi à
la main reste. Une clé Gemini collée dans ce champ par erreur est remplacée : le
routeur ne l'accepterait jamais.

Pour voir ce que le routeur a reçu, depuis le dossier du Studio :

```
docker logs free-ai-studio-manager 2>&1 | findstr images
```

`401` : mot de passe refusé. `503` : pas de clé Gemini. `502` : Google a
refusé. Aucune ligne : Open WebUI n'a jamais appelé le Studio. C'est ce qu'a
montré l'ordinateur d'essai du 13/09 : là-bas, la cause n'est pas établie.

---

## Une bulle vide, ou un dessin qui ne s'affiche pas

Le 14/09/2026, « fais moi un cube en svg » a rendu une bulle vide.
L'interrupteur « Interpréteur de code » d'Open WebUI était mis : le modèle a
écrit un programme Python au lieu du dessin, mal fermé, et son exécution a
échoué sans un mot.

**Correctif en place** : le Studio coupe cet interpréteur une fois, au
démarrage. Le fichier `config/open-webui-interpreteur.json` dit que c'est
fait. Si quelqu'un l'a remis depuis le panneau d'administration
(« Exécution de code »), le Studio le laisse : retirez l'interrupteur sous la
zone de saisie, puis reposez la question.

Un dessin SVG complet dans la réponse s'affiche ensuite sous celle-ci, avec un
lien « Télécharger ». L'image vient du Studio, à l'adresse
`http://localhost:8010/dessins/…` : si elle reste blanche, le routeur est
arrêté, ou le dessin fait partie des plus anciens, retirés au-delà de 200.

Quand un service refuse une demande, le journal du routeur dit maintenant
pourquoi, depuis le dossier du Studio :

```
docker logs free-ai-studio-manager 2>&1 | findstr failed
```

---

## La dictée écrit n'importe quoi, ou n'écrit rien

Jusqu'au 15/09/2026, la dictée tournait sur le plus petit Whisper utile, sans
savoir que vous parliez français : une dictée devenait « 3,4,5,5 ».

**Correctif en place** : la dictée passe par le Studio, qui choisit à chaque
fois. Sur la page d'accueil du Studio (<http://localhost:8010/studio>), carte
« Dictée » :

- **Groq si possible** (par défaut) : avec une clé Groq branchée, votre voix
  part chez Groq (`whisper-large-v3`, palier gratuit). Si Groq refuse (limite
  du jour, panne, clé retirée), la dictée se fait sur votre ordinateur, sans
  message d'erreur.
- **Sur cet ordinateur** : votre voix ne quitte jamais le PC. Whisper `small`,
  sur le processeur, sans carte graphique.

Le Whisper de l'ordinateur se télécharge une fois, d'avance, au démarrage du
Studio. Si la toute première dictée locale échoue, vérifiez la connexion, puis
réessayez. Pour voir qui a transcrit, et pourquoi Groq a été écarté (le
journal ne garde jamais ce qui a été dit) :

```
docker logs free-ai-studio-manager 2>&1 | findstr Dictee
```

Le fichier `config/open-webui-dictee.json` dit que la dictée d'Open WebUI a été
confiée au Studio. Si quelqu'un choisit un autre moteur dans Open WebUI
(Panneau d'administration, Audio), le Studio le laisse.

---

## Le piège du dossier imbriqué

Quand VS Code demande **où** cloner, il faut désigner le dossier **parent**
(`Documents`), pas un dossier `free-ai-studio` déjà créé : git crée lui-même le
sous-dossier à son nom. Sinon on obtient `Documents\free-ai-studio\free-ai-studio`.

Ce n'est pas qu'un désagrément de rangement. **Les deux dossiers portent le même
nom, donc Docker les traite comme un seul projet et leur donne le même volume de
données** — pendant que chacun a son propre `.env` avec ses propres mots de passe
internes. C'est exactement ce qui fabrique la panne « aucun modèle » ci-dessus.

Si vous avez les deux : gardez celui qui contient `demarrer.cmd` directement, et
supprimez l'autre.

---

## Mettre à jour quand le Studio ne démarre pas

Le bouton **Mettre à jour** vit dans la page du Studio : il ne sert à rien quand
rien ne tourne. Passez par VS Code :

**Affichage** → **Palette de commandes** → taper `extraire` → **Git : Extraire**.
(`Ctrl+Maj+P` ouvre bien la palette **dans VS Code**, mais l'impression système
dans un navigateur — d'où le passage par le menu.)

Puis double-cliquer `demarrer.cmd` : rien à reconstruire à la main.

Pour vérifier quelle version est réellement installée, ouvrir
<http://127.0.0.1:8010/maj/etat> et lire `version_locale_courte`.

---

## « Le veilleur n'est pas lancé » à côté du bouton Mettre à jour

Le bouton ne reconstruit rien lui-même : il laisse une demande à un petit veilleur qui
tourne sous votre compte, sans fenêtre. `demarrer.cmd` le lance ; le veilleur pose alors
un raccourci « Free AI Studio - mises a jour » dans le dossier Démarrage de Windows, et
repart seul à chaque ouverture de session.

Si la page dit qu'il n'est pas lancé :

1. Double-cliquer une fois `demarrer.cmd`. Il doit afficher « Veilleur de mise a jour
   lance ». S'il affiche « n'a pas demarre », passer au point 2.
2. Touches Windows+R, taper `shell:startup` : le raccourci doit s'y trouver. S'il manque,
   il a été supprimé, ou un antivirus l'a retiré.
3. En attendant, `mettre-a-jour.cmd` fait la même mise à jour à la main.

Un Studio installé avant le 14/09/2026 n'a pas encore ce veilleur-là : sa première mise à
jour passe par `mettre-a-jour.cmd`, puis un `demarrer.cmd` lance le nouveau veilleur, qui
pose le raccourci. Ensuite, le bouton suffit, même après un redémarrage.

---

## Le port 3000 est déjà utilisé

`demarrer.cmd` le détecte, nomme le programme qui occupe la porte, et s'arrête
avant de rien casser. Nos propres conteneurs sont reconnus et ne comptent pas :
un redémarrage n'est pas un conflit.

Pour changer de porte, dans `docker-compose.yml` :

```yaml
ports:
  - "127.0.0.1:3001:8080"
```

---

## Avec un terminal (pour un assistant de code)

```bash
docker --version && docker compose version
docker compose ps
docker compose logs --tail=200
docker compose up -d --build      # le code est cuit dans l'image : --build est nécessaire
python scripts/self-test.py       # n'appelle aucun service payant
```

Tout remettre à zéro, **y compris l'historique Open WebUI** :

```bash
docker compose down -v
```
