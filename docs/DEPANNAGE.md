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
fonctionnalités Windows**. Cocher :

- **Plateforme de machine virtuelle**
- **Sous-système Windows pour Linux**
- **Plateforme d'hyperviseur Windows**, si elle est présente

*Hyper-V n'est pas nécessaire : Docker passe par WSL2.*

Puis **redémarrer l'ordinateur**. C'est le geste qu'on saute et qui coûte une
heure : tant que la machine n'a pas redémarré, la case est cochée et **rien n'a
changé**. Fermer et rouvrir Docker Desktop ne suffit pas.

### 3. WSL lui-même

Test sans terminal : menu Démarrer → application **Ubuntu**. Si une fenêtre noire
s'ouvre sur une invite `vous@machine:~$`, WSL fonctionne. Sinon, Docker Desktop
propose souvent lui-même de le réparer au démarrage ; sinon, le noyau WSL :
<https://aka.ms/wsl2kernel>.

### 4. Docker regarde du mauvais côté

Docker Desktop → **Settings** → **General** → **Use the WSL 2 based engine** doit
être coché.

---

## « Le démarrage a échoué » et les erreurs 500

**Une erreur 500 affichée par Docker Desktop n'est pas une panne distincte.**
Docker Desktop est une façade qui parle à un moteur Linux ; quand ce moteur ne
démarre pas, tout ce qui l'interroge reçoit *500 Internal Server Error*. Ne
cherchez rien du côté du 500 : réglez le démarrage du moteur (section
précédente), le 500 disparaît avec lui.

**Si le message vient de la fenêtre noire de `demarrer.cmd`**, c'est autre chose,
et le plus souvent ce n'est pas votre ordinateur : le magasin d'images de Docker
répond mal pendant une minute. Relancez `demarrer.cmd`. À partir de la troisième
fois de suite, ce n'est plus un hasard : le rapport complet s'ouvre tout seul
dans le Bloc-notes (`%TEMP%\free-ai-studio-demarrage\erreur-demarrage.txt`), il
est fait pour être montré tel quel.

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
