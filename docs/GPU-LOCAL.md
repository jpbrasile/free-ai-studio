# Le GPU local d'abord — chantier ouvert le 19/09/2026

Ouvert sur demande de l'utilisateur, après la mesure qui suit : « le gpu local ne devrait
pas être utilisé de façon automatique (s'il existe et est assez large en plus !) ».

## Pourquoi, en une image

La carte graphique de la maison tourne à vide pendant qu'on loue une machine à l'heure
chez quelqu'un d'autre. Mesuré le 19/09/2026 : **la RTX 4090 est libre, 24 138 Mo sur
24 564, aucun processus dessus**, et le mois de septembre a coûté **1,2781 $** chez Modal
pour 28 travaux — 2 clips, 20 chansons, 6 dialogues.

**Et le plus gênant n'est pas la dépense, c'est que trois fichiers du dépôt annonçaient
déjà « GPU local d'abord ».** Aucun code ne l'implémentait :

- `docker-compose.yml` ne nommait la carte **nulle part** — aucun `gpus`, aucun `devices` ;
- ce que le code appelle `local` est le bac à sable **sur processeur** ;
- la vidéo ne consulte même pas cette branche : `preparer()` part sur Modal par défaut.

Les trois descriptions ont été remises à l'endroit le 19/09 (`d63d87d`) : elles disent
maintenant ce que le code fait. **Ce chantier fait l'inverse — il fait faire au code ce
que les descriptions promettaient.**

## Phase 1 — savoir. FAITE le 19/09/2026

| Pièce | Ce qu'elle fait | Preuve |
|---|---|---|
| Le passage de la carte | Docker la donne déjà au conteneur, **sans image CUDA** | `docker run --rm --gpus all python:3.12-slim nvidia-smi` → `RTX 4090, 24138 MiB` |
| `docker-compose.gpu.yml` | surcouche qui donne la carte au bac à sable | `compose run --rm sandbox-manager nvidia-smi` → `NVIDIA GeForce RTX 4090, 24564, 24138` |
| `scripts/demarrer.ps1` | n'ajoute la surcouche **que si** une carte répond | une réservation `driver: nvidia` sans carte fait échouer `compose up` |
| `sandbox-manager/gpu_local.py` | la sonde : mesure **au lancement**, marge, motif lisible | `tests/test_gpu_local.py`, 13 tests |

**Le morceau réputé pénible était déjà en place** : le passage de la carte par WSL2
fonctionne sur cette machine sans que rien ait été installé. C'est la bonne nouvelle du
jour, et elle change le coût du reste.

**Ce que la phase 1 ne fait pas, et il faut le lire** : *rien ne tourne encore sur la
carte*. Aucun routage n'a changé, aucun clip n'est fabriqué à la maison. La phase 1
répond seulement à « peut-on, là, tout de suite ». Sans elle, la phase 2 déciderait sur
« une carte existe », ce qui est faux dès qu'un autre travail la tient.

## Phase 2 — faire tourner un modèle dessus

> **Arrêt posé par l'utilisateur le 19/09/2026 au soir : « 2.1 deprecated »**, avec
> <https://blog.fal.ai/wan-2-2-vs-wan-2-1-whats-new-and-how-to-upgrade-your-video-pipeline/>.
> **La phase 2 ne se construit donc pas sur Wan 2.1.** Ce que le Studio fait tourner
> aujourd'hui, chez Modal : `Wan-AI/Wan2.1-VACE-1.3B-diffusers` (rapide) et
> `Wan-AI/Wan2.1-VACE-14B-diffusers` (soigné, 75 Go, A100) — `sandbox-manager/video.py:62`.
> Et `notebooks/SOTA_LINKS.md` recommandait **déjà** la 2.2 pendant que le code tournait en
> 2.1, sans qu'aucun fichier ne porte la décision : c'est la contradiction relevée au §9.
>
> **À vérifier avant d'écrire une ligne, et non supposé** : (1) quelle variante de la 2.2
> tient sur une carte de 24 Go ; (2) si elle garde les commandes que la page `/video`
> utilise réellement — image de **fin** (`mask` + `video=`, `video.py:308`) et
> `reference_images` pour la cohérence d'un personnage (`:322`) —, car les perdre serait
> une régression du produit, pas une mise à jour ; (3) sa licence et sa restriction de
> territoire. ~~Tant que ces trois réponses ne sont pas écrites ici, la phase 2 n'a pas de
> modèle.~~ *Les trois réponses sont mesurées ci-dessous, le 19/09/2026 au soir.*

### Les trois réponses, mesurées

**Question 3 d'abord, parce qu'elle ne bloque rien : Apache 2.0, aucune restriction de
pays**, pour la TI2V-5B comme pour la seule VACE 2.2 qui existe. Rien à surveiller de ce
côté.

**Question 1 — une seule variante de la 2.2 tient sur 24 Go.** Tailles relevées par
l'API de Hugging Face le 19/09, pas recopiées d'une page :

| Modèle | Sur disque | Tient sur la 4090 ? | Garde les 3 commandes ? |
|---|---|---|---|
| `Wan-AI/Wan2.2-TI2V-5B-Diffusers` | **34,20 Go** | **oui** — la fiche dit « at least 24GB VRAM (e.g, RTX 4090 GPU) » | **non** |
| `Wan-AI/Wan2.2-T2V-A14B` et `I2V-A14B` | — | non, deux experts de 14 milliards | non |
| `alibaba-pai/Wan2.2-VACE-Fun-A14B` | **81,24 Go** | **non** | oui |
| `Wan-AI/Wan2.1-VACE-1.3B-diffusers` *(ce qui tourne aujourd'hui)* | 19 Go | oui | oui |

**Question 2 — et c'est elle qui décide : la Wan 2.2 n'a pas de VACE.**

- La liste officielle de l'organisation Wan-AI ne contient **aucun** `Wan2.2-VACE` : il y a
  T2V-A14B, I2V-A14B, TI2V-5B, S2V-14B, Animate-14B, rien d'autre.
- La documentation de `diffusers` dit la même chose de son côté : les seuls points de
  contrôle que `WanVACEPipeline` annonce sont `Wan-AI/Wan2.1-VACE-1.3B-diffusers` et
  `Wan-AI/Wan2.1-VACE-14B-diffusers`.
- Le seul VACE 2.2 qui existe vient d'une **autre équipe** (PAI-Fun, pas l'équipe Wan) :
  81,24 Go, faits de **deux experts de 34,68 Go chacun**. Avec le déchargement vers la
  mémoire centrale, un seul expert est sur la carte à la fois — **34,68 Go dans 24 Go, ça
  ne rentre pas.** Il faudrait le comprimer en float8 (≈ 17 Go) ou le charger couche par
  couche, beaucoup plus lent. Sa propre fiche ne donne d'ailleurs aucun exemple `diffusers`,
  seulement ComfyUI et ses scripts maison.

**Le piège, écrit noir sur blanc parce qu'il ne fait aucun bruit.** La TI2V-5B **accepte**
l'argument `last_image` et **ne s'en sert pas**. Sa configuration porte
`"expand_timesteps": true`, et dans `pipeline_wan_i2v.py` cette branche-là ne garde que la
première image :

```python
if self.config.expand_timesteps:
    video_condition = image          # last_image n'entre nulle part
elif last_image is None:
    ...
```

Commentaire des auteurs deux cents lignes plus bas : `# wan 2.2 5b i2v use firt_frame_mask
to mask timesteps`. Aucune erreur levée, aucun message : **l'image de fin serait ignorée en
silence.** C'est exactement le faux vert qu'on refuse — un bouton qui a l'air de marcher.

### Ce que ces mesures décident

« La 2.2 remplace la 2.1 » est vrai pour un clip ordinaire, et **faux pour la page `/video`
telle qu'elle est** : ses trois commandes sont des fonctions de VACE, et la 2.2 n'a pas de
VACE qui tienne sur la carte. On ne choisit donc pas un modèle, **on route selon ce que le
client demande** :

| Ce que le client demande | Où ça tourne | Modèle |
|---|---|---|
| un clip : texte seul, ou texte + image de **départ** | **à la maison, gratuit** | Wan 2.2 TI2V-5B, 720p à 24 im/s |
| une image de **fin** | loué chez Modal | Wan 2.1 VACE, faute de 2.2 qui rentre |
| une image de **référence** (garder un personnage) | loué chez Modal | idem |

La page le dit en une ligne quand ça part chez Modal, et la 2.1 reste **avec son motif
écrit** au lieu d'être défendue. À rouvrir le jour où l'équipe Wan publie un VACE 2.2.

**Deux conséquences chiffrées, à ne pas recopier de la 2.1 :**

- **Le clip ne se compte plus pareil.** La 2.1 tourne à 16 images par seconde (49 images
  = 3 s, table `DUREES` de `video.py`). L'exemple officiel de la 5B est **121 images,
  704 × 1280, 24 images par seconde**. La table est à refaire, pas à traduire.
- **Le téléchargement passe de 19 Go à 34,20 Go** : transformeur 20,0 Go (en fp32 dans le
  dépôt, chargé en bf16 ⇒ ≈ 10 Go sur la carte), lecteur de texte umT5 11,4 Go, VAE 2,8 Go.
  Place libre sur `C:` mesurée à l'instant : **405 Go**, dont 84 Go récupérables dans Docker.
  **Téléchargement lancé le 19/09 au soir** dans le cache du profil ; effaçable si le choix
  change.

Le coût ci-dessous est celui **mesuré pour la 2.1** ; il donne l'ordre de grandeur, et il
sera refait pour le modèle retenu :

- **torch + CUDA dans une image** : environ 3 Go, en plus des ~6 Go que le débutant
  télécharge déjà. Donc **une image séparée**, construite seulement quand une carte est
  vue : celui qui n'en a pas ne télécharge rien de plus.
- **Les poids de Wan 2.1 VACE 1.3B** : 19 Go (mesuré le 09/09), le gros morceau étant le
  lecteur de texte umT5 qui l'accompagne, pas le fabricant d'images.
- **Trois réglages déjà payés le 09/09**, à reprendre tels quels : `enable_model_cpu_offload()`
  sous 60 Go — pas 20 —, `vae.enable_tiling()`, et `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
  posé **avant** le premier `import torch`, sinon ignoré en silence.
- ~~**Le premier chiffre à obtenir** : le clip de 3 s qui a coûté **422 s de calcul et
  0,096 $** sur une L4 chez Modal, refait sur la 4090.~~ **FAIT le 19/09/2026 à 18:43.**

### Le premier clip fabriqué à la maison — 19/09/2026

`C:\Users\test\Documents\clips-4090\clip_4090.mp4`, relu par ffmpeg : **3,04 s, 1280 × 704,
24 im/s, h264, 636 218 octets.**

| | À la maison, 19/09 | Loué chez Modal, 09/09 |
|---|---|---|
| carte | RTX 4090 (partagée) | L4 |
| modèle | Wan 2.2 TI2V-5B | Wan 2.1 VACE 1.3B |
| définition | **1280 × 704** | 832 × 480 |
| images / cadence | 73 à 24 im/s | 49 à 16 im/s |
| longueur du clip | **3,04 s** | 3,06 s |
| passes de débruitage | **50** | 30 |
| chargement du modèle | 23,7 s | — |
| **calcul** | **411,8 s** | **422 s** |
| pic mémoire carte | **12 841 Mo** | — |
| **coût** | **0 $** | 0,117 $ |

**Ce que ces nombres disent, et rien de plus.** Le même clip de 3 secondes sort en
**pratiquement le même temps** — 412 s contre 422 s — mais à la maison il est en **720p au
lieu de 480p**, avec **50 passes au lieu de 30**, et il **ne coûte rien**. À temps égal, la
carte de la maison a produit **3,4 fois plus de pixels**. **Ce n'est pas une mesure propre du
matériel** : les deux modèles sont différents, le 5B est presque quatre fois le 1,3B. Le
chiffre honnête est celui du produit, pas celui d'un banc d'essai.

**Et le nombre le plus utile pour la suite est le pic mémoire : 12 841 Mo.** C'est ce que la
phase 3 passera à `gpu_local.utilisable(besoin)` — mesuré, pas estimé. Il tient largement
dans les 24 564 Mo de la carte, et il tiendrait encore si un tiers en occupait 10 Go.

**Deux défauts trouvés en route, tous deux écrits parce qu'ils se répéteront :**

- **Le téléchargement des poids se bloque en silence.** À 14 067 Mo sur 34 200, plus un
  octet pendant **treize minutes** (dates des fichiers partiels : 18:03:05 contre 18:16:36).
  Cause : la couche de transfert « Xet » de `huggingface_hub` 1.9.2. Avec
  `HF_HUB_DISABLE_XET=1` : **14 067 → 24 620 Mo en quatre-vingts secondes**, puis terminé.
  **Sur cette machine, les poids se téléchargent Xet coupé.**
- **Le Python de la machine ne peut pas servir** : son `numpy` et son `tokenizers` (0.15.2,
  il en faut ≥ 0.22) sont en conflit avec `transformers`. On ne répare pas l'installation
  d'un tiers pour une mesure — on isole. L'image de mesure est
  `pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` plus `diffusers`, `transformers`,
  `accelerate`, `ftfy`, `imageio` : **6,35 Go**, et elle voit la carte.
- **Correction d'une ligne de la phase 2 ci-dessus** : `WanPipeline.__call__` **n'accepte
  pas** d'argument `image` (vérifié dans `diffusers` 0.40.0). La phrase de la fiche du
  modèle — « si le paramètre `image` est configuré, c'est de l'image-vers-vidéo » — parle de
  leur outil à eux. L'image de **départ** passe par `WanImageToVideoPipeline`, l'autre
  classe, qui traite `expand_timesteps` explicitement. La décision de routage ne change pas ;
  le nom de la pièce, si.

## Phase 3 — router

- ~~`run_auto` et la vidéo~~ **la vidéo seule** demande à `gpu_local.utilisable(besoin)` avant
  de louer. **`run_auto` est laissé dehors, et c'est mesuré, pas oublié** : il exécute du
  code quelconque, dont personne ne connaît le besoin mémoire. La sonde exige un nombre
  (`utilisable(besoin_mo)`) ; lui en donner un inventé serait exactement le chiffre supposé
  que ce chantier refuse. La vidéo, elle, a deux besoins relevés sur cette carte.
- **La mémoire libre n'est pas le seul critère.** La vidéo regarde d'abord *ce qui est
  demandé* : une image de fin ou une image de référence part chez Modal même si la carte
  est libre, parce que le modèle de la maison ne sait pas les faire (voir le tableau de la
  phase 2). Le refuser à la mémoire libre seule produirait un clip qui ignore la consigne.
- ~~**Occupée ⇒ on va chez Modal.** On n'attend pas la carte~~ — **corrigé par l'utilisateur
  le 19/09 au soir : « il faut que le client ait le choix du gpu local et du bypass si
  occupée ».** Ce n'est pas à nous de décider pour lui ; voir la section suivante. Ce qui
  ne change pas : **on n'arrête jamais le travail qui tient la carte**, elle est partagée
  avec le jumeau plasma et, certains jours, un serveur LLM qui y tenait 15,5 Go le 04/09.
- Un manque de mémoire en cours de route est un **repli**, pas une panne du Studio.
- Sur la page, deux mots suffisent : « fait à la maison » ou « loué chez Modal », et ce
  que le travail aurait coûté.

### Le choix appartient au client — décidé le 19/09/2026

**Ce qui a provoqué la décision, et ce n'est pas une préférence.** Le soir du 19/09, le
premier clip local était prêt à partir et **n'a pas pu** : un calcul du jumeau plasma tenait
la carte. Il a fallu attendre **de 18:20:54 à 18:35:52, quinze minutes**, pour une fabrication
qui a ensuite duré quelques minutes. **L'attente était plus longue que le travail.** Et la
règle que j'avais écrite — « occupée ⇒ on va chez Modal » — aurait dépensé de l'argent sans
demander, là où quinze minutes de patience ne coûtaient rien.

**Aucune règle écrite d'avance ne sait si le client est pressé.** Donc trois réglages, et
il en choisit un :

| Réglage | Ce qui se passe |
|---|---|
| **À la maison si la carte est libre** *(par défaut quand une carte existe)* | occupée ⇒ on **demande**, on ne décide pas |
| **Toujours chez Modal** | le contournement permanent : la carte partagée n'entre jamais en jeu |
| **Toujours à la maison** | jamais un centime, on attend le temps qu'il faut |

**Et quand la carte est occupée, la page montre trois choses et attend :**

- **ce qui bloque, en clair et avec le nombre** : « un autre calcul tient la carte, il reste
  8,9 Go libres sur 24,5 » — jamais « indisponible » tout seul ;
- **« J'attends »** : la demande se met en file, le client voit où il en est et **peut
  changer d'avis à tout moment** ;
- **« Louer chez Modal »** : avec **le prix avant**, pas après — « environ 0,12 $, il vous
  reste 28,72 $ ce mois-ci ».

**Le coût honnête de ce choix** : « j'attends » demande au Studio de garder une demande en
attente entre deux rechargements de page, ce qui n'existe pas aujourd'hui. **Ce que ça
représente en travail n'est pas mesuré** et sera chiffré avant d'être promis. Le réglage
« toujours chez Modal », lui, ne demande rien de neuf : c'est le comportement actuel.

### Ce qui a été écrit le 19/09 au soir

Le routage existe en code, **et il n'a encore jamais tourné dans la pile complète** — voir
la dernière ligne de « Non vérifié » plus bas. Les pièces :

| Pièce | Ce qu'elle fait |
|---|---|
| `sandbox-manager/ou_calculer.py` | tranche le factuel, **rend la question** dès qu'il reste un goût à arbitrer |
| `sandbox-worker-gpu/Dockerfile` | le même worker, sur l'image `pytorch:2.6.0-cuda12.4` mesurée le 19/09 |
| `docker-compose.gpu.yml` | le deuxième bac à sable, la carte, le cache des 34 Go |
| `POST /video/creer` | **409 + la décision** quand la carte est prise : ni dépense ni attente décidée à la place du client |
| `GET`/`POST /video/ou-calculer` | les trois réglages, gardés dans `/config/ou-calculer.json` |
| la page `/video` | le réglage, la boîte « la carte est prise » avec ses nombres, et « fait à la maison, 0 $ » à l'arrivée |

**L'attente vit dans la page, pas dans le service**, et c'est une décision, pas un oubli :
une file côté serveur n'a pas été chiffrée (voir le paragraphe ci-dessus), alors que
« la page redemande toutes les 30 secondes et le client peut arrêter d'un clic » ne coûte
rien et se voit. Ce qui est perdu : fermer l'onglet arrête l'attente. C'est écrit sur la page.

**La durée de 5 secondes est entrée dans la table le 19/09 à 19:23** : 121 images,
**14 902 Mo de pic, 598 s de calcul**, `clip_4090_5s.mp4`. Elle apprend quelque chose qui
interdit d'extrapoler la troisième : **66 % d'images en plus coûtent 45 % de temps en plus
mais seulement 16 % de mémoire en plus**. Ni l'un ni l'autre n'est proportionnel, et pas
dans le même sens. Une durée absente de la table est donc vraiment inconnue.

**Un défaut trouvé en écrivant la phase 3, réparé dans le même tour.** Le script de la
maison recevait l'**image de départ** et ne la posait nulle part : `WanPipeline` n'a pas
d'argument `image` (c'est `WanImageToVideoPipeline` qui l'a). Le clip serait sorti **sans
l'image demandée, sans un mot** — exactement la panne silencieuse que la phase 2 avait
documentée pour l'image de fin. Les trois images jointes partent donc chez le loueur, et
trois gardes le disent : le routage, `preparer(maison=True)`, et le script lui-même.

### Ce que seule la pile complète a montré — 19/09/2026, 20:0x

Les 32 tests remplacent la sonde et le lancement : ils jugent la décision, pas la fabrication.
**Un clip est donc parti par la vraie pile** — page → gestionnaire → décision → bac à sable de
la carte → fichier. Il est sorti : `succeeded`, **73 images, 1280 × 704, 24 im/s, 1 901 468
octets**, et la décision écrite dans la fiche du travail dit « Fabriqué ici, gratuitement.
NVIDIA GeForce RTX 4090 : 24 138 Mo libres pour 12 841 demandés (marge 1 024) ».

**Trois inconnues tombent d'un coup** : le bac à sable GPU **se construit** ; il **voit la
carte** depuis `docker compose` (24 138 MiB) ; et le compte non privilégié (uid 10001) **lit
les 34 Go** montés depuis `C:\Users\…\.cache\huggingface`.

**Et deux défauts que rien d'autre ne pouvait montrer :**

- **40 secondes perdues par clip, et vingt lignes rouges.** Le journal ouvre sur cinq
  `Temporary failure in name resolution` avant un `Will try to load from local cache`.
  Le bac à sable est sur un réseau clos ; `diffusers` demande quand même à Hugging Face si
  les poids ont changé, échoue, et **recommence cinq fois**. Réparé par `HF_HUB_OFFLINE=1`,
  **et le deuxième clip le mesure : 416,5 s → 390,0 s**, soit **26,5 s rendues**, pour un
  calcul rigoureusement identique (4:07 à 4,95 s/it les deux fois). Les vingt lignes rouges
  sont remplacées par une seule, claire : `offline mode is enabled`. Pour un débutant,
  c'était un mur de rouge devant un clip qui allait réussir.
- **Sans les poids, « à la maison » ne peut pas marcher — et le disait dix minutes trop
  tard.** Le bac à sable n'a pas internet : si les 34 Go manquent, il ne les trouvera
  jamais. Trois pièces maintenant : le worker **déclare** ses poids sur `/health`, le
  gestionnaire **regarde avant de router** (une demi-seconde contre dix minutes perdues), et
  `scripts/telecharger-modele-video.ps1` les descend **une fois** depuis un conteneur qui,
  lui, a le droit d'aller sur le réseau.

**Correction de ma propre phrase, faite par l'utilisateur le 19/09 au soir** : j'avais écrit
« le worker GPU est sur un réseau sans internet » comme si c'était une contrainte. **C'est
ma ligne**, posée le jour même dans `docker-compose.gpu.yml` par recopie du bac à sable
processeur ; `- default` suffirait à l'ouvrir. Ce que la mesure dit, elle : depuis ce
conteneur, `gethostbyname('huggingface.co')` rend `[Errno -3] Temporary failure in name
resolution`, parce que `sandbox-internal` porte `internal: true`. **Ce que l'ouvrir ne
réglerait pas** : les 34 Go ont demandé environ une heure le 19/09, et un travail est coupé
à 2 400 s — le premier clip expirerait avant la fin. Le préchargement reste nécessaire dans
les deux cas ; le réseau clos reste le défaut tant que rien ne paie son ouverture.

## Ce qui est refusé d'avance

- **Réserver la carte au Studio.** Elle ne lui appartient pas.
- **Décider sur « une carte existe ».** La décision se prend sur la mémoire libre à
  l'instant du lancement, et se refait au lancement suivant.
- **Alourdir l'installation de celui qui n'a pas de carte.** C'est la promesse du produit.

## Non vérifié à ce jour

> **Les trois manques qui sont des chantiers sont ouverts dans le plan**, pas seulement
> listés ici : `PLAN.md`, étape 9 — **GPU-1** (la surcouche ne marche que sous Windows),
> **GPU-2** (la comparaison de qualité, dont la moitié louée coûte ≈ 0,114 $ et appartient
> au propriétaire), **GPU-3** (les deux trajets vus par bouts). Chacun y porte son rayon
> mesuré, qui décide, et la preuve qui le ferme. Une ligne « non vérifié » qui reste ici
> sans entrée là-bas est un manque nommé mais jamais ouvert : c'est exactement le défaut
> relevé par le propriétaire le 19/09 au soir.
>
> **Les trois sont fermés le 20/09/2026** — et un quatrième, GPU-4, ouvert et fermé le même jour : rendre les 34 Go se demande, section « Rendre les 34 Go » en bas. J'avais écrit ici, le même jour, que « rien
> n'a jamais tourné sous Linux » ; le propriétaire a relevé que **le moteur Docker de
> cette machine EST un Linux**. Les deux scripts y ont donc été exécutés depuis —
> section « GPU-1 (suite) » en bas. Ce qui reste non mesuré se dit maintenant plus
> étroitement : **le `compose up` réel et le clip à la maison depuis un hôte Linux** dont
> le shell et le moteur partagent le disque ; et la boîte « carte prise » n'a **pas de
> capture d'écran** — la fenêtre Chrome qui porte l'onglet rend un viewport de 0 × 0. Le
> reste des lignes ci-dessous tient toujours.

- ~~De combien la 4090 bat la L4 louée.~~ **Mesuré le 19/09** : 412 s contre 422 s pour un
  clip de 3 s, mais en 720p au lieu de 480p et 50 passes au lieu de 30 — voir le tableau.
  Reste non mesuré : la **même** tâche des deux côtés, qui seule comparerait les cartes.
- ~~Le temps de premier chargement des 19 Go de poids depuis un disque local.~~ **Mesuré :
  23,7 s** pour charger la TI2V-5B depuis le disque local (poids déjà téléchargés).
- ~~La place disque totale que la phase 2 demande~~ — 34,20 Go de poids, mesurés ; reste
  non mesuré ce que l'image torch + CUDA fait grossir sous WSL2.
- **Si la TI2V-5B tient vraiment dans 24 Go sur CETTE carte**, qui est partagée. La fiche
  annonce 24 Go pour une carte entière ; la sonde de la phase 1 décidera sur la mémoire
  libre à l'instant, et un manque en cours de route est un repli chez Modal, pas une panne.
- La qualité comparée : personne n'a encore vu côte à côte un clip de la 1.3B 480p et un
  de la 5B 720p sur le même texte.
- ~~**Le routage de la phase 3 n'a jamais tourné dans la pile Docker complète.**~~
  **Vérifié le 19/09 au soir, deux clips de bout en bout** (`succeeded`, 73 images,
  1280 × 704, fichier récupéré par l'adresse à jeton de la page). Construction du worker
  GPU, carte vue depuis `docker compose`, lecture des 34 Go par le compte non privilégié,
  page → fichier : les quatre sont mesurés. **Ce qui reste non vérifié**, et qui n'est pas
  la même chose : le chemin **« les poids manquent »** sur une machine qui ne les a pas
  (tenu par un test, jamais vu en vrai), le script de téléchargement `telecharger-modele-
  video.ps1` ~~**jamais exécuté**~~ (exécuté le 19/09 à 21:5x, voir plus bas), et ~~la boîte
  « la carte est prise » **vue dans un navigateur**~~ (ligne suivante).
- ~~**Le chantier ne marche que sous Windows aujourd'hui, et ce n'est écrit nulle part
  ailleurs.**~~ **Les trois pièces sont écrites le 20/09** (`start.sh`,
  `scripts/telecharger-modele-video.sh`, le message qui nomme le bon script) — section
  « GPU-1 » en bas de ce document. *Énoncé d'origine, gardé :* seul `scripts/demarrer.ps1`
  ajoutait `-f docker-compose.gpu.yml` ; `start.sh` ne le faisait pas, et il n'existait pas
  de jumeau `.sh` du script de téléchargement. Un débutant sous Linux avec une carte
  obtenait donc le comportement d'avant le chantier — tout est loué — **sans un mot**.
  Mesuré par `grep -rn docker-compose.gpu.yml` : sept fichiers le nommaient, aucun n'était
  un `.sh`. ~~**Ce qui reste non vérifié** : rien de tout cela n'a jamais tourné SOUS
  Linux — cette machine est sous Windows.~~ **Exécuté sous Linux le 20/09** dans un
  conteneur de cette machine, carte comprise (section « GPU-1 (suite) »). Reste : un hôte
  Linux dont le shell et le moteur Docker partagent le disque.
- ~~La boîte « la carte est prise » vue à l'écran.~~ **Vue le 19/09 vers 21:10.** Elle
  affiche « NVIDIA GeForce RTX 4090 : 3.2 Go libres sur 24.0, il en faut 12.5 », puis les
  trois sorties « J'attends », « Louer chez Modal — environ 0,114 $ » et « Annuler ».
  **Comment elle a été obtenue, mot pour mot** : les 3 275 Mo libres sont un relevé RÉEL,
  mesuré à 20:29 pendant qu'un conteneur à moi tenait 20 Go de la carte ; ce relevé a été
  **rejoué** dans `ou_calculer.decider()` — code non modifié — qui a rendu le `on-demande`
  et sa phrase ; la page a dessiné cette réponse par sa propre fonction. **Ce qui n'a donc
  pas été refait au moment du rendu** : l'occupation de la carte, car trois `julia.exe`
  étaient présents et la règle du dépôt interdit alors de lancer quoi que ce soit dessus.
  ~~Le trajet « carte vraiment prise → 409 → boîte » reste mesuré par bouts, pas d'un
  tenant.~~ **Parcouru d'un seul tenant le 20/09 vers 08:25** — section « GPU-3 (a) » en
  bas de ce document : occupation réelle par un clip de la maison, 409 réel à 9 351 Mo
  libres, boîte affichée par la page. Reste non obtenu : **la capture d'écran**, la
  fenêtre Chrome de cet onglet rendant un viewport de 0 × 0.

## Le modèle de la maison ne se voyait nulle part sur la page (19/09, 21:0x)

Relevé du propriétaire : **« pas de Wan 2.2 sur le lien /video »**. Exact, et ce n'était pas
un oubli d'affichage : le menu « Qualité » ne propose que la Wan 2.1 (1,3 B et 14 B), parce
que le modèle de la maison **ne se choisit pas** — il se déduit du réglage « Carte de cet
ordinateur ». Mais sur le réglage PAR DÉFAUT, carte libre, c'est la Wan 2.2 qui fabrique le
clip. La page annonçait donc, sur son chemin le plus fréquent, le nom d'un modèle qui ne
tournait pas, et le pied de page écrivait « Modèle : Wan2.1 » au singulier.

Réparé le soir même, sans rien inventer : la ligne de licence et le pied lisent le
dictionnaire déjà servi par `/video/budget`, qui contient l'entrée `maison`.

| | avant | après |
|---|---|---|
| menu | « Qualité » | « Qualité si on loue » |
| licence | une ligne, Wan 2.1 | deux : « Si on loue : Wan 2.1… » et « À la maison : Wan-AI/Wan2.2-TI2V-5B-Diffusers — Apache 2.0, 1280 × 704 à 24 images/s, gratuit » |
| pied | « Modèle : Wan2.1-VACE-1.3B (19 Go) » | « Modèles : …1.3B (19 Go) quand on loue, …TI2V-5B (34 Go) sur la carte de cet ordinateur » |

La seconde ligne disparaît sous « toujours sur une machine louée » : elle ne décrit alors
plus rien. Tenu par `test_la_page_nomme_le_modele_de_la_maison` (317 tests verts), relu
dans Chrome le 19/09 à 21:1x.

## Le chemin « les 34 Go ne sont pas là », vu en vrai (19/09, 21:4x → 22:0x)

Il n'était tenu que par un test. Trois mesures l'ont pris en charge pour de bon, et l'une
d'elles a trouvé un défaut que personne ne cherchait.

**1. Le bac à sable déclare des poids absents, le gestionnaire le voit en une demi-seconde.**
On n'a rien supprimé : une surcouche d'essai, hors dépôt, a fait pointer
`SANDBOX_POIDS_REQUIS` sur un dossier qui n'existe pas — exactement le fait que le contrôle
regarde. Le worker réel a répondu `poids_presents: false`, et `maison_prete()` a rendu
« Les 34 Go du modèle vidéo ne sont pas encore téléchargés sur cet ordinateur. Une seule
fois, dans le dossier du Studio : `scripts\telecharger-modele-video.ps1` ». Aucun travail
n'a été créé : un travail routé chez le loueur est une dépense, et la dépense se demande.

**2. Le défaut trouvé en remettant la vraie configuration : le montage des 34 Go tenait à
une variable de shell.** `docker-compose.gpu.yml` montait
`${GPU_MODELES_DIR:-modeles-gpu}`, et **seul** `scripts/demarrer.ps1` posait cette variable
sur le cache du profil. Un `docker compose up -d sandbox-worker-gpu` tapé à la main — ce que
fait n'importe qui après une mise à jour — remontait donc le **volume Docker vide, en
silence** : mesuré ici, `poids_presents` est passé à `false` alors que les 34 Go étaient sur
le disque, à un dossier près. Le Studio aurait alors dit « téléchargez-les », et un débutant
aurait repris une heure de ligne pour rien.

Réparé dans le même tour : le défaut est désormais le cache du profil lui-même,
`${GPU_MODELES_DIR:-${USERPROFILE:-${HOME:-.}}/.cache/huggingface}`. Vérifié par
`docker compose config` — sans variable, la source rendue est `C:\Users\test/.cache/hugging
face` ; avec `GPU_MODELES_DIR=D:\poids-ailleurs`, c'est ce dossier-là — puis en recréant le
conteneur **dans un shell où la variable est vide** : montage
`/run/desktop/mnt/host/c/Users/test/.cache/huggingface`, `poids_presents: true`.

**3. Le script de téléchargement a été exécuté pour la première fois.** Deux essais :

| | destination | résultat |
|---|---|---|
| poids déjà là | `C:\Users\test\.cache\huggingface` | **2 s**, « Fait en 0 s », 29 fichiers reconnus, sortie 0 |
| dossier vide | un dossier temporaire à moi | **1 901,5 Mo descendus en 75 s**, soit ≈ 25 Mo/s |

Le second essai a été **arrêté volontairement** après 75 s et son dossier supprimé : il
prouve que le téléchargement part, écrit dans le dossier monté et sort du réseau ; il ne
prouve **pas** que les 34 Go arrivent au bout. À 25 Mo/s ce serait ~23 min, mais le débit
d'une ligne ne se tient pas une demi-heure — le 19/09, le téléchargement complet avait
demandé environ une heure **avec une reprise après blocage**. Une seule ligne d'avertissement
au passage, notée telle quelle : `You are sending unauthenticated requests to the HF Hub`.

## La fiche du travail ne gardait pas le texte du clip (19/09, 22:2x)

Trouvé en préparant la comparaison de qualité que ce document réclame depuis la phase 2 :
« un clip de la 1.3B 480p et un de la 5B 720p **sur le même texte** ». Les fiches des trois
clips déjà fabriqués ont été relues une par une — elles gardent le modèle, la carte, la
définition, la précision, le temps de calcul, le prix et **le motif du routage**, et pas la
phrase tapée. Les deux clips du 19/09 pèsent **1 901 468 et 390 313 octets** : plus personne
ne peut dire sur quel texte, ni refaire le même clip, ni donc comparer deux modèles sur le
même. Le clip loué du 09/09 (`b16ee2c1`, Wan 2.1 VACE 1.3B, 832 × 480, 49 images, 422,4 s)
est dans le même cas — sa moitié de comparaison est inutilisable.

Réparé : `resume_public` porte la description, la fiche la rend, et la page l'écrit sous le
clip (échappée — du texte libre qui revient dans du HTML redevient du code si on le laisse
faire). Tenu par `test_la_fiche_du_travail_garde_le_texte_du_clip`. **Ce que ça ne répare
pas** : les trois clips déjà fabriqués restent sans texte, et aucune invention ne le leur
rendra.

**Reste donc à faire pour clore la comparaison** : un clip loué et un clip local sur le
texte que la page propose elle-même. Le local est gratuit ; le loué coûte **environ
0,114 $** et attend l'accord du propriétaire — une dépense ne se décide pas toute seule,
c'est la règle du chantier.

## GPU-2 — la comparaison de qualité, faite le 20/09/2026 vers 06:15

Autorisée par le propriétaire (« oui pour les 0,114 $ »). **Même texte des deux côtés**, celui
que la page propose elle-même : *« Un phare breton sous la pluie, la mer se soulève, la lumière
tourne. »* — vérifié **octet par octet** dans les deux fiches (`c3a8` = è ; l'affichage de
PowerShell 5.1 le montre en mojibake, c'est son décodage latin-1, pas la donnée).

| | loué (`52a7cf3e`) | à la maison (`27e68191`) |
|---|---|---|
| modèle | Wan 2.1 VACE 1.3B | Wan 2.2 TI2V-5B |
| carte | NVIDIA L4 (louée) | RTX 4090 (ici) |
| définition | 832 × 480 | **1280 × 704** |
| images | 49 à 16 im/s = 3,1 s | **73 à 24 im/s** = 3,0 s |
| passes | 30 | 50 |
| temps de calcul | 393,9 s | **391,0 s** |
| fichier | 131 468 octets | 367 447 octets |
| coût | **0,1097 $** (budget Modal 1,2781 → 1,3878) | **0 $** |

**Le chiffre qui compte n'est pas le temps, c'est ce qu'il achète.** Les deux calculs durent la
même chose à trois secondes près, mais la maison fabrique **5,6 fois plus** de
pixel × image × passe (3 289 088 000 contre 587 059 200). C'est une mesure grossière — elle
suppose que toutes les passes se valent, ce qui est faux entre deux architectures — et elle ne
remplace pas un banc. Elle dit seulement l'ordre de grandeur.

**Et à l'œil, une surprise qui va dans l'autre sens.** Une image prise au milieu de chaque clip
(`clips-4090/image_LOUE.png`, `image_MAISON.png`) :

- **le loué 480p obéit mieux au texte** : il fait la pluie, le crépuscule bas, **et la lanterne
  est allumée**. L'image est molle, la mer peu détaillée, la plage dynamique étroite.
- **la maison 720p est nettement plus belle** — herbe, rochers, écume, nuages, un horizon avec
  une île — **et elle ignore deux mots sur trois** : pas de pluie, coucher de soleil dégagé,
  lanterne éteinte.

**n = 1, un seul texte, une seule graine.** Cela ne dit pas qu'un modèle suit mieux les consignes
que l'autre ; cela dit que sur ce clip-là, le gain de définition n'est pas gratuit et qu'il faut
regarder, pas seulement compter les octets. Ce qui est établi, en revanche : **le même clip coûte
0,11 $ dehors et 0 $ ici, pour le même temps d'attente**, et c'est la raison d'être de ce
chantier.

Les deux fichiers et les deux images sont dans `C:\Users\test\Documents\clips-4090\`.

## GPU-1 — les deux lanceurs font enfin la même chose (20/09/2026)

Jusqu'ici, la carte de la maison ne servait qu'aux gens sous Windows. Sous Linux, le
Studio démarrait sans regarder s'il y avait une carte : tous les clips partaient chez le
loueur, **sans un mot**, exactement comme avant le chantier. Le plus désagréable n'est pas
la dépense, c'est le silence — rien à l'écran ne disait qu'une carte était là et ignorée.

### Les trois pièces écrites

| | avant | maintenant |
|---|---|---|
| `start.sh` | `docker compose up -d`, jamais la surcouche | regarde `nvidia-smi`, ajoute `-f docker-compose.gpu.yml` **si une carte répond**, réutilise le cache Hugging Face déjà rempli, et dit quoi faire si les 34 Go manquent |
| téléchargement des 34 Go | `telecharger-modele-video.ps1` seulement | + `scripts/telecharger-modele-video.sh`, même dossier de destination, même image |
| le message « il manque les 34 Go » | nommait toujours le script PowerShell | nomme celui de **cette** machine (`STUDIO_LANCEUR`), et les deux si le lanceur est inconnu |

Deux différences assumées entre les jumeaux, toutes deux écrites dans les fichiers :

- le `.ps1` lance le conteneur **en root** (le cache appartient à l'utilisateur Windows) ;
  le `.sh` le lance **sous le compte de la personne** (`--user "$(id -u):$(id -g)"`), sinon
  root déposerait des fichiers root dans son dossier personnel, qu'elle ne pourrait plus
  effacer sans `sudo` ;
- `start.sh` gagne `--build`, que `demarrer.ps1` avait déjà : le code des services est
  **copié** dans les images, il n'est pas monté. Sans cette option, un dépôt mis à jour
  continue de tourner sur l'image d'avant — y compris sur la détection de carte qu'on vient
  d'ajouter.

### Ce qui a vraiment été exécuté, et ce qui ne l'a pas été

~~**Jamais exécuté sous Linux. Cette machine est sous Windows.**~~ *Écrit le 20/09 au
matin, faux le 20/09 à midi : le moteur Docker de cette machine est lui-même un Linux, et
les deux scripts y ont été exécutés — section « GPU-1 (suite) », plus bas.* Ce qui a été
fait d'abord : `start.sh` et son jumeau ont tourné **pour de vrai** sous bash (Windows),
avec un faux `docker` qui écrit ses arguments au lieu d'agir — donc sans toucher aux
conteneurs. Les quatre chemins ont été parcourus :

| chemin | ce que le script a fait |
|---|---|
| carte présente, poids présents | `Carte graphique vue : NVIDIA GeForce RTX 4090`, puis `compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build` |
| `nvidia-smi` présent mais en échec | `compose -f docker-compose.yml up -d --build` — **pas de surcouche**, c'est le cas du débutant sans carte |
| carte présente, poids absents | les trois lignes « le modèle vidéo (34 Go) n'est pas téléchargé », avec `./scripts/telecharger-modele-video.sh` |
| téléchargement qui rate | « Le téléchargement a échoué (code 1). Relancez : il reprend où il s'est arrêté », et le script rend bien 1 |

Ce dernier chemin a servi à attraper un défaut du premier jet : avec `set -e`, un
téléchargement raté aurait arrêté le script **avant** son message, et la personne n'aurait
rien vu. Corrigé (`|| code=$?`), puis vérifié comme ci-dessus.

La troisième pièce a été vérifiée **dans la pile réelle**, elle : `sandbox-manager`
reconstruit avec `STUDIO_LANCEUR=windows`, `printenv` dans le conteneur rend `windows`, et
le service nomme `powershell -ExecutionPolicy Bypass -File scripts\telecharger-modele-video.ps1`.
Posée à `linux`, la même fonction rend `./scripts/telecharger-modele-video.sh` ; vide, elle
nomme les deux.

**Reste ouvert** : une machine Linux avec une carte, où `start.sh` applique la surcouche et
un clip sort à la maison. Tant que personne n'a fait tourner cela, GPU-1 est fermé sur son
critère de repli — les trois pièces écrites et tenues par des tests — pas sur le trajet
complet.

### Ce qui empêche les deux lanceurs de diverger à nouveau

`tests/test_gpu_local.py::test_le_lanceur_linux_applique_la_surcouche_comme_celui_de_windows`
lit les deux fichiers et exige les quatre mêmes gestes : la surcouche seulement sous
condition, le même dossier de poids, le même modèle sondé, et le nom du script de **son**
côté. Un lanceur réparé seul fait rougir ce test. C'est la même mécanique que le garde-fou
du 19/09 sur le dossier des poids : le défaut qui se répète est celui que rien ne mesure.

## GPU-3 (a) — « la carte est prise », vu d'un seul tenant le 20/09/2026 vers 08:25

Le 19/09, cette boîte avait été obtenue en deux morceaux : un relevé réel de la carte
occupée, **rejoué** ensuite dans le module de décision, et la page qui dessinait la
réponse. Entre les deux, le chemin n'avait jamais été parcouru d'une traite, parce que
trois `julia.exe` tenaient la carte et que la règle du dépôt interdit alors d'y toucher.

Cette fois, d'un bout à l'autre, et **sans rien prendre à personne** : l'occupation est un
clip de la maison, gratuit, lancé sur une carte que la sonde déclarait libre (aucun
`julia.exe`, 24 138 Mo).

| heure | ce qui est mesuré |
|---|---|
| 08:21:33 | clip `eb427639` envoyé à la maison — « 24138 Mo libres pour 12841 demandés (marge 1024) » |
| 08:22:14 → 08:23:14 | la mémoire libre tombe : 21 733 → 20 233 → 18 593 → 16 933 → 15 273 → **13 653 Mo**, sous les 13 865 qu'il faut |
| 08:24 | deuxième demande, **HTTP 409** : « La carte est prise par un autre calcul. NVIDIA GeForce RTX 4090 : **9351 Mo libres, il en faut 13865** (12841 demandés + 1024 de marge). La carte est partagée : on va chez Modal, on n'arrête personne. » — `prix_estime_usd` 0,1142, sorties `attente` / `modal` / `annuler` |
| 08:25 | **depuis la page, dans Chrome** : la boîte s'affiche, « NVIDIA GeForce RTX 4090 : **9.1 Go libres sur 24.0, il en faut 14.6.** Attendre ne coûte rien ; louer, si. », avec les trois boutons **J'attends**, **Louer chez Modal**, **Annuler** |
| 08:27:50 | le clip finit, la mémoire revient (21 457 Mo libres) ; `succeeded`, 430,2 s, 953 999 octets, **0 $** |

**Pourquoi 12,5 Go dans le 409 et 14,6 Go dans la boîte** — et ce n'est pas une
incohérence : la demande faite en ligne de commande portait 3 secondes (12 841 Mo
mesurés), celle de la page était sur 5 secondes (14 902 Mo). Deux durées, deux besoins,
les deux mesurés et écrits dans `BESOIN_MO_MESURE`.

**Rien n'a été cliqué dans la boîte** : ni « Louer » — qui aurait coûté 0,114 $ — ni
« J'attends ». Ce qui est vérifié, c'est que la question est posée avec ses chiffres,
pas ce que fait chaque bouton.

**Ce qui n'a PAS pu être fait : la capture d'écran.** La fenêtre Chrome qui porte cet
onglet rend un viewport de **0 × 0** — toute capture échoue sur « Cannot take screenshot
with 0 width », et restaurer les fenêtres réduites n'y change rien, l'onglet vivant dans
une fenêtre que Windows ne liste pas. Ce qui est consigné ci-dessus est donc le **texte
rendu de la boîte**, lu dans la page après coup, pas une image. Le contenu, lui, vient
bien du 409 réel : la page l'a fabriqué avec sa propre fonction, à partir de la réponse
du serveur, pendant que la carte était prise.

## GPU-3 (b) — les 34 Go descendus depuis un dossier vide, jusqu'au bout (20/09/2026)

Le 19/09, ce téléchargement avait été mesuré sur 75 secondes (1 901,5 Mo) et jamais
jusqu'à la fin ; la seule autre exécution, celle qui a rempli le cache du profil, avait
duré « presque une heure » avec une reprise après blocage. Un chiffre tiré d'une course
interrompue et d'un souvenir n'est pas une mesure.

Dossier **neuf et vide** (`C:\Users\test\gpu3-poids-depuis-zero`, 0 entrée au départ),
hors du cache du profil pour ne pas toucher aux 34 Go qui font tourner le Studio.

| | mesuré |
|---|---|
| début → fin | 08:20:14 → 08:42:04 |
| durée | **1 310,9 s**, soit 21 min 51 s |
| écrit | **34 203 034 754 octets** = 34,20 Go (31,85 Gio), 62 fichiers |
| débit moyen | **24,9 Mio/s** |
| code de sortie | 0 |
| place sur `C:` | 380,1 Go libres avant, 348 Go après |

**Vingt-deux minutes, pas une heure.** La différence avec le 19/09 tient à une seule
chose, déjà écrite dans `docker-compose.gpu.yml` et dans le script : la couche de
transfert « Xet » de `huggingface_hub`, coupée par `HF_HUB_DISABLE_XET=1`. Le 19/09 elle
s'était bloquée treize minutes sans écrire un octet, à 14 067 Mo sur 34 200. C'est la
mesure qui justifie ce réglage, et la voici de bout en bout.

**Et le dossier est utilisable, pas seulement rempli** : l'arbre obtenu est
`hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers/snapshots/b8fff731…/` avec `transformer/`,
`text_encoder/`, `vae/`, `scheduler/`, `tokenizer/` et `model_index.json` — exactement le
chemin que le bac à sable de la carte exige (`SANDBOX_POIDS_REQUIS`
= `/cache/huggingface/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers`). Un téléchargement
qui finit dans le mauvais dossier était le défaut réparé le 19/09 ; ici les deux chemins
coïncident.

**Ce qui reste hors mesure** : ces 24,9 Mio/s sont ceux de cette ligne, ce matin-là. Sur
une ligne trois fois plus lente, la même opération demande une heure et demie — le
message du Studio annonce toujours « une demi-heure à une heure », ce qui reste la bonne
fourchette à écrire pour quelqu'un dont on ne connaît pas la ligne.

Les 32 Gio de ce dossier d'essai sont **gardés tels quels** en attendant que le
propriétaire dise quoi en faire : ils ne servent à rien pour le Studio, qui lit le cache
du profil.

## GPU-1 (suite) — « tu n'as pas essayé sur le docker Linux du client ? » (20/09, ~09:00)

Relevé du propriétaire, et il a raison : j'avais écrit « jamais exécuté sous Linux » en
regardant le système de la machine, alors que **le moteur Docker de cette machine EST un
Linux** et qu'un conteneur en est un aussi. Il ne manquait pas une machine, il manquait
l'idée d'y entrer. Voici ce que donne l'essai, fait depuis.

### Ce qui tourne maintenant sous Linux, pour de vrai

`Linux 6.18.33.2-microsoft-standard-WSL2`, bash 5.2.37, le dépôt monté en lecture seule.

| essai | résultat |
|---|---|
| `start.sh`, carte qui répond, poids absents | « Carte graphique vue : NVIDIA GeForce RTX 4090 », les trois lignes « le modèle vidéo (34 Go) n'est pas téléchargé » nommant `./scripts/telecharger-modele-video.sh`, puis `compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build` |
| `start.sh`, carte qui répond, poids présents | « Modèles déjà téléchargés réutilisés : …/.cache/huggingface », même surcouche, pas d'avertissement |
| `start.sh`, carte qui ne répond pas | `compose -f docker-compose.yml up -d --build` — **pas de surcouche**, le débutant sans carte ne voit rien |
| `telecharger-modele-video.sh`, image absente | « L'image du bac à sable GPU n'existe pas encore. Lancez d'abord le Studio (`./start.sh`) », sortie 2, aucun téléchargement |
| `telecharger-modele-video.sh`, commande assemblée | `run --rm -v /root/.cache/huggingface:/cache/huggingface -v /studio/scripts:/scripts:ro -e HF_HOME=… -e HOME=… -e HF_HUB_DISABLE_XET=1 --user 0:0 …` — chemins Linux natifs, compte de la personne |
| le **vrai** moteur, depuis ce shell Linux | `docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --services` → `sandbox-worker`, **`sandbox-worker-gpu`**, `free-tier-manager`, `open-webui`, `sandbox-manager` |

`nvidia-smi` répond dans le conteneur : `NVIDIA GeForce RTX 4090, 24138 MiB`. La détection
de carte, la surcouche et le message ne sont donc plus des suppositions sous Linux.

### Ce que l'essai a trouvé, et qui n'était pas cherché

**Dans une image Alpine, `nvidia-smi` existe et ne s'exécute pas.** Le runtime NVIDIA
injecte le binaire, mais ses bibliothèques sont celles de la glibc et Alpine tourne sur
musl : `command -v nvidia-smi` répond oui, l'appel répond
`cannot execute: required file not found`. **Le script conclut « pas de carte » et part
chez le loueur** — c'est le bon repli, et il ne tient qu'à un détail : on juge le **code
de retour** de `nvidia-smi`, pas la présence du fichier. Tester la présence aurait donné
une machine qui croit avoir une carte et qui échoue plus tard, au moment du clip. Le même
cas se produit en vrai sur une machine Linux dont le pilote ne correspond pas à la
bibliothèque installée.

### Ce qui reste, et qui n'est pas la même chose

Ce conteneur parle au moteur Docker **de cette machine**, dont le système de fichiers
n'est pas le sien : un `docker run -v /studio/scripts:…` lancé depuis lui demanderait au
moteur un chemin qui n'existe pas chez lui. **Le téléchargement réel et le `compose up`
réel n'ont donc pas été lancés depuis Linux** — ce sont les deux seules lignes du trajet
qui attendent encore une machine dont le shell et le moteur partagent le disque. Tout ce
qui précède, lui, est mesuré.

## Rendre les 34 Go : demandé, jamais automatique (20/09/2026)

Question du propriétaire, après l'effacement de la copie d'essai : « *l'effacement sera
automatique ou demandé au client pour son pc* ». **Demandé.** Trois raisons, dans l'ordre
où elles pèsent :

1. **Le dossier n'appartient pas au Studio.** Les 34 Go vont dans
   `~/.cache/huggingface`, le cache Hugging Face **du compte** — celui que lisent aussi
   ComfyUI, un carnet Jupyter, n'importe quel autre outil d'IA de la personne. Un ménage
   automatique n'effacerait pas « nos » fichiers, il effacerait ceux de quelqu'un d'autre
   sur sa propre machine. C'est ce que l'essai vérifie : deux modèles voisins
   (`models--stabilityai--sdxl`, `models--openai--whisper-large`) sont posés à côté, et
   ils sont **intacts** après la suppression.
2. **Le retour coûte 22 minutes.** Mesuré le 20/09 sur cette ligne : 34,20 Go à
   24,9 Mio/s. Un geste de trois secondes qui en coûte vingt-deux se demande.
3. **Rien n'est en danger.** 34 Go sur un disque de 1 862 Go. Il n'y a aucune urgence qui
   justifierait de décider à la place du propriétaire de la machine.

Ce qui est écrit à la place, `scripts/supprimer-modele-video.{ps1,sh}` — jumeaux, comme
les deux autres paires :

- il **pose la question** et attend un mot tapé (`oui`), pas une touche ;
- sans terminal pour poser la question, **il refuse** au lieu de supposer (le `.sh` teste
  `[ -t 0 ]`) ; un script appelant doit dire `--oui` / `-Oui` explicitement ;
- il ne supprime **que** `hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers`, jamais la racine
  du cache ;
- il dit ce qui change après (« les clips repartiront sur une machine louée, payante »)
  et **comment revenir** (le script de téléchargement, 22 minutes).

Et le message de fin du téléchargement nomme maintenant le chemin du retour : celui qui
vient d'attendre 22 minutes est exactement celui à qui il faut dire comment rendre la
place — rien d'autre ne le lui dirait.

**Le garde-fou est dans les tests, pas dans l'intention.**
`test_la_suppression_des_34_go_se_demande_et_ne_vise_que_le_modele` vérifie qu'il n'y a
qu'**une** ligne qui efface dans chaque script, qu'elle porte le sous-dossier du modèle,
et qu'elle ne contient **aucune** des trois écritures de la racine du cache (`$cible`,
`$HOME/.cache/huggingface`, `GPU_MODELES_DIR`, `$cacheHF`). C'est l'erreur qu'une
simplification bien intentionnée écrirait un jour.

### Ce qui a vraiment été exécuté

Sous Windows (`.ps1`) et sous Linux dans un conteneur de cette machine (`.sh`, avec
`script` pour fabriquer un vrai terminal et jouer la question) :

| chemin | résultat |
|---|---|
| modèle absent | « Rien à supprimer : … n'existe pas », code 0 |
| question posée, réponse `non` | « Annulé. Rien n'a été touché », modèle **encore là** |
| question posée, réponse vide (juste Entrée) | idem — **annulé** |
| question posée, réponse `oui` | supprimé, **voisin intact** |
| pas de terminal, sans `--oui` (`.sh`) | refus, modèle encore là, code 1 |
| `--oui` / `-Oui` | supprimé sans question, voisin intact |

Défaut trouvé à l'essai et réparé dans le même tour : sur un petit dossier, le `.ps1`
annonçait « **0 Go rendus** » — un message de suppression qui a l'air de n'avoir rien
fait. Il affiche maintenant les Mo en dessous du Go (« 1,9 Mo rendus »).

La copie d'essai de GPU-3(b), elle, a été **effacée le 20/09 sur ordre du propriétaire** :
31,9 Go rendus, disque de 346,9 à **378,7 Go libres**, la copie lue par le Studio vérifiée
intacte avant et après (32 fichiers, 31,85 Go).

## GPU-5 — « nb Go par applis » : le client voit la place, et il la reprend

Demande du propriétaire, 20/09 : « *mettre chez le client une fonction de vidage des
ressources téléchargées via le studio, nb Go par applis* ».

Jusqu'ici le Studio se comportait comme un invité qui pose ses valises dans le couloir :
personne ne sait ce qu'elles pèsent, et personne ne sait lesquelles on peut sortir. Les
34 Go du modèle vidéo étaient la seule pièce nommée quelque part, et seulement dans ce
document-ci — que le client ne lit pas.

`scripts/ressources.{sh,ps1}` — jumeaux, comme les trois autres paires. **Sans argument,
ils ne suppriment rien : ils mesurent et ils affichent.** Mesure réelle sur cette
machine, 20/09 :

| application | ce qui est sur le disque | taille | clé |
|---|---|---|---|
| Vidéo à la maison | les 34 Go du modèle vidéo | 31,85 Go | `video-poids` |
| Vidéo à la maison | le bac à sable qui sait parler à la carte | 5,95 Go | `video-image` |
| Chat (Open WebUI) | l'application de conversation | 8,93 Go | `chat` |
| Écoute des voix | les modèles qui transcrivent | 2,00 Go | `whisper` |
| Le Studio lui-même | ses trois services | 1 002,0 Mo | `studio` |
| **VOTRE TRAVAIL** | vos fichiers · vos conversations | 781,2 Mo · 1,05 Go | *aucune* |

**Téléchargé : 49,70 Go. Votre travail : 1,81 Go.** Le total téléchargé est annoncé
comme une **borne haute**, et le script le dit sur la ligne d'après : les images Docker
partagent des morceaux, les additionner majore. Un total présenté comme exact serait
faux de quelques Go sans que personne puisse le voir.

**Ce qui ne s'efface pas d'ici.** Les deux volumes du travail — `sandbox-data`,
`open-webui-data` — sont affichés, parce que le client a le droit de savoir ce qu'ils
pèsent, et **refusés au vidage** : le script répond « c'est VOTRE travail » et imprime
la commande manuelle, pour que la personne puisse le faire elle-même en connaissance de
cause. Un `docker volume rm` de trop, et six mois de travail partent sans confirmation
possible.

**Pourquoi un script et pas un bouton dans la page.** Vider une image ou un volume Docker
demande la prise `/var/run/docker.sock`. La monter dans le service web reviendrait à
donner à n'importe quelle page — et au code quelconque qui tourne dans le bac à sable —
les pleins pouvoirs sur la machine hôte. Aucune prise de ce genre n'est montée nulle part
dans ce dépôt, et ce n'est pas pour une commodité de ménage qu'on ouvrirait la première.
La raison est écrite en tête des deux scripts, à l'endroit où quelqu'un aura un jour
l'idée de « simplifier ».

### Le test qui gardait cette page était creux, et c'est la mutation qui l'a dit

`test_le_travail_du_client_est_montre_mais_jamais_supprime` cherchait `docker volume rm`
et `rm -rf` sur les lignes qui nomment le travail du client. Or les deux scripts passent
par des fonctions — `vider_volume`, `ViderImage`. **Épreuve : j'ai ajouté à la main dans
`ressources.sh` la faute exacte que le test doit attraper** (`menage) vider_volume
"${PROJET}_sandbox-data"`), et le test **est passé** : « avec la faute -> code 0 :
1 passed ». Il ne gardait rien.

Corrigé — la garde regarde maintenant les appels **et** les commandes brutes, et saute
les définitions de fonctions. Rejoué des deux côtés :

| | avec la faute | fichier remis |
|---|---|---|
| `ressources.sh` | **code 1**, 1 failed | code 0, 6 passed |
| `ressources.ps1` | **code 1**, 1 failed | code 0, 6 passed |

Un test qui n'a jamais échoué n'est pas une garde, c'est une décoration. Celui-ci
protégeait la seule chose irremplaçable de la machine.

### Les dates : celle du dépôt, et celle du crédit

Demande du propriétaire, le même jour : « *note aussi la date de renouvellement des
ressources (modal en particulier)* », puis « *mais ok pour les dépôts aussi* ». Deux
choses différentes portent ce mot, et les deux sont affichées.

**Les dépôts : depuis quand ça dort là.** Une taille seule ne dit pas s'il faut s'en
occuper — 34 Go arrivés hier et 34 Go qui dorment depuis six mois ne mènent pas à la
même décision. Colonne « RENOUVELÉ LE », qui est la date d'arrivée **sur cette
machine** et non celle où l'auteur a publié :

| ligne | ce qui date la ligne |
|---|---|
| les 34 Go | le fichier le plus récemment écrit — un téléchargement repris ajoute des fichiers sans toucher au dossier du dessus |
| une image | `LastTagTime` (construite ou tirée ici) ; `.Created`, la date de l'auteur, n'est que le repli |
| un volume | sa date de création — et le tableau le dit : *ce qu'il contient a pu être ajouté plus tard* |

Vider puis réutiliser remet la date à aujourd'hui : c'est exactement ce que
« renouvelé » veut dire ici, et c'est le lien avec GPU-6.

**Deux fautes attrapées en regardant l'écran, pas le code.** La ligne du Studio affichait
d'abord un tiret : `LastTagTime` sort avec des espaces (« 2026-09-20 08:19:56.278 +0000
UTC ») et le mot `UTC` se comparait aux dates. Corrigé, elle affichait **19/09** — et
c'était encore faux : sans retour à la ligne, les trois dates des trois images se
collaient en un seul mot et la ligne montrait la date de la **première**, pas la plus
récente. Contrôle indépendant (`docker image inspect | cut | sort | tail -1`) :
**20/09/2026**, ce qu'elle affiche maintenant. Une date plausible et fausse ne se voit
pas ; c'est pour ça qu'on la recoupe.

**Les crédits : ce qui repart tout seul, et quand.** Les lignes du dessus ne bougent que
si on les vide. Celles-ci sont des droits d'usage, et elles reviennent à une date. Ne pas
la connaître, c'est soit attendre pour rien alors que le crédit est revenu, soit lancer
un calcul qui sera refusé.

```
  Modal (machines louées)   1.39 $ dépensés sur 30 $ ce mois-ci, reste 28.61 $
                            NOTRE compteur repart le 01/10/2026, et tous les 1ers.
                            Le crédit Modal aussi : « Billing Cycle: Sep 1 - Oct 1 »,
                            lu le 20/09/2026 sur VOTRE tableau de bord. Leur page
                            publique, elle, ne publie PAS le jour ; le tableau de
                            bord si, et c'est VOTRE cycle qui fait foi (modal.com).
                            ATTENTION, notre chiffre compte MOINS que la vraie
                            facture : mesuré le 20/09/2026 sur la même période,
                            1,39 $ ici contre 3,80 $ chez Modal. Le reste exact
                            est sur leur page « Usage & billing », pas ici.
  Gemini                    quota du JOUR, remis à zéro à minuit heure du
                            Pacifique, soit 9 h chez nous — écrit par Google
  OpenRouter                quota du JOUR ; l'heure n'est pas publiée
  Groq                      pas d'heure fixe : l'API rend un compte à rebours
  Le compte du jour est sur la page Clés du Studio.
  (vérifié le 20/09/2026 sur les pages officielles)
```

**Cette dernière forme est une correction, et elle vaut d'être racontée.** Le bloc
annonçait d'abord, à côté du nom de Modal : « *remis à zéro le 01/10/2026, et tous les
1ers du mois* ». Le propriétaire a relevé la phrase — « *web search pour retrouver les
jours exacts* ». Vérification faite, page par page :

| source | ce qu'elle dit vraiment |
|---|---|
| `modal.com/pricing` | « $30 / month free compute » — le montant, **pas** le jour |
| `modal.com/docs/guide/billing` | « All Workspaces are billed monthly » — **pas** le jour |
| `modal.com/docs/guide/budgets` | rien sur une remise à zéro |
| `ai.google.dev/.../rate-limits` | « Requests per day (RPD) quotas reset at **midnight Pacific time** » |
| `openrouter.ai/docs/api_reference/limits` | les comptes par jour (50, ou 1 000 au-delà de 10 $ de crédits) — **pas** l'heure |
| `console.groq.com/docs/rate-limits` | aucune heure : l'API rend un **compte à rebours**, `x-ratelimit-reset-requests` |

Le « 1er du mois » venait d'un **résumé de moteur de recherche**, pas de Modal. Il est
vrai de *notre* compteur, dont la clé est `%Y-%m` ; il ne l'est pas du crédit du client,
dont le cycle n'est écrit nulle part **dans la documentation publique**. Un client qui
compte sur une date inventée lance un calcul qui sera refusé. Le champ rendu par le
service s'appelle
maintenant `compteur_remis_a_zero_le` et non `renouvele_le` — il dit ce qu'il mesure — et
deux tests l'empêchent de reprendre du galon : l'un exige que toute ligne parlant du
« 1er » dise **de qui** il est, l'autre que les trois fournisseurs soient distingués au
lieu de recevoir le même « remis à zéro chaque jour », qui donnait le même niveau de
certitude à une mesure et à deux suppositions.

Le compteur se lit dans `config/modal-budget.json`, monté depuis le dépôt : **ni clé, ni
Docker, ni service à démarrer**. La mise en garde de `budget_modal.py` remonte jusqu'au
client — personne ici ne lit le compte Modal, c'est une estimation d'après les prix
publics, et la seule limite qui arrête vraiment la facture est celle réglée chez eux.

**La date est calculée à un seul endroit.** `budget_modal.premier_du_mois_suivant()` la
rend dans `lire()`, pour que la page et le script annoncent la **même** — deux dates
différentes sur le même compteur seraient pires que pas de date du tout. Un test garde
le passage de décembre à janvier, la faute que tout calcul de date oublie. Et un test
interdit d'écrire une **date de remise à zéro** en clair dans les scripts : juste une
fois, fausse pour toujours. Une date de **relevé**, elle, s'écrit en dur et doit
l'être — elle dit quand les pages des fournisseurs ont été lues.

**Ce qui a vraiment été exécuté.** Le fichier du compteur reculé d'un mois, puis remis :

| `config/modal-budget.json` | ligne affichée |
|---|---|
| `"mois": "2026-09"` (le mois en cours) | `1.39 $ dépensés sur 30 $, reste 28.61 $` |
| `"mois": "2026-08"` (un mois clos) | **`0.00 $ dépensés sur 30 $, reste 30.00 $`** |
| remis à l'identique | `1.39 $` |

Un total d'un mois clos affiché comme courant serait un chiffre faux présenté comme à
jour. Les deux jumeaux rendent les mêmes tailles, les mêmes dates et les mêmes montants.

## GPU-6 — vider ne doit pas fermer une porte

Ordre du propriétaire, dans le même tour : « *si on supprime, l'usage de la ressource
demandée démarre par son téléchargement* ».

Sans cette règle, la fonction de vidage ci-dessus était un piège. Le client rendait
32 Go, redemandait un clip « à la maison », et le Studio le faisait **payer chez le
loueur** en lui disant d'ouvrir un terminal et de lancer un script. Un débutant paie sans
comprendre pourquoi, alors que le produit lui promet l'inverse.

**Qui télécharge, et pourquoi ce n'est pas le bac à sable.** Le bac à sable qui fabrique
les clips est sur un réseau **sans internet** (`internal: true`) : c'est ce qui rend sûr
d'y exécuter du code quelconque, et on n'y touche pas. Le décideur, lui, est sur le
réseau normal **et** sur le réseau interne, et n'exécute jamais de code du client. C'est
donc lui qui va chercher les poids — dans le **même** dossier que le bac à sable lira
ensuite, monté des deux côtés par `docker-compose.gpu.yml`.

Ce que voit le client : la **même** boîte que pour une carte occupée, avec ses trois
sorties — j'attends (la page redemande toutes les 30 s), je loue tout de suite, j'annule
— et le compte qui avance : « *Le modèle vidéo (34 Go) se télécharge maintenant : 2 %
faits. Encore environ 22 minutes. Une seule fois — les clips suivants repartent du
disque.* »

### Deux défauts, trouvés en jouant le chemin et non en le relisant

**(a) « Le dossier existe » comptait pour « les poids sont là ».** Le bac à sable
répondait `poids_presents: true` dès que le dossier existait. Tant que personne ne
téléchargeait en arrière-plan, le cas ne se produisait guère ; à partir du moment où le
Studio télécharge lui-même, **le dossier existe pendant les vingt-deux minutes où il se
remplit**. Un clip routé « maison » à la troisième minute était perdu. Le défaut était
**déjà livré** avant ce chantier — un téléchargement interrompu à la main produisait le
même mensonge. Corrigé des deux côtés : aucun fichier `.incomplete`, **et** au moins 98 %
des 34 203 034 754 octets mesurés.

**(b) Le téléchargement écrivait à côté de l'endroit surveillé.** `snapshot_download`
sans `cache_dir` écrit dans le dossier par défaut de Hugging Face — dans le conteneur,
`/root/.cache/huggingface`, qui n'est pas monté et disparaît au redémarrage. **Mesuré, et
c'est ce qui l'a révélé** : sonde lancée sur un dossier vide, **0 octet après 30 s** là où
le Studio regarde, pendant que la page annonçait tranquillement « se télécharge : 0 %
faits ». Une phrase rassurante posée sur rien, et 34 Go perdus au premier
`docker compose up`. Aucun test ne pouvait le voir : les tests remplacent Hugging Face.

Corrigé par une fonction unique, `cache_hub()`, qui sert **aux deux** usages — dire où
écrire, et mesurer ce qui est arrivé — pour qu'ils ne *puissent* pas diverger ; plus
`HF_HOME` dans le compose pour tout autre appel de la bibliothèque.

### Ce qui a vraiment été exécuté

Sonde relancée sur l'image corrigée, dossier vide, réseau réel :

| | avant le correctif | après |
|---|---|---|
| t+6 s | 0 octet | 87 104 018 octets |
| t+30 s | **0 octet** | **758 192 658 octets — 2,2 %** |
| reste annoncé | *(aucun : 0 %, indéfiniment)* | **≈ 22 minutes** |
| `present` | False | False — *le partiel ne compte pas pour « prêt »* |

Le débit tombe sur la mesure de GPU-3(b) faite la veille (24,9 Mio/s, 21 min 51 s) : les
deux chiffres viennent de deux chemins indépendants et se rejoignent.

Et sur la pile qui tourne, poids présents, `GET /video/poids/etat` (qui **ne démarre
jamais** rien) : `34 203 028 556 / 34 203 034 754 octets`, **100,0 %**, « Le modèle vidéo
est sur cet ordinateur. » Appeler deux fois `demarrer()` ne lance qu'un téléchargement.

Suite complète **340 passés**, ruff propre, `bash -n` sur les deux `.sh`, analyse
syntaxique des deux `.ps1`, `verifier-imports` (3 services, 79 routes) et `verifier-js`
(14 scripts) verts.

### Non vérifié, dit tel quel

Le **bout en bout** n'a pas été joué : effacer pour de vrai les 34 Go de cette machine,
demander un clip depuis la page, et le voir sortir après le téléchargement. Il coûte
22 minutes de ligne et la suppression du cache réel, qui est une décision du propriétaire
de la machine — c'est précisément ce que GPU-4 a tranché. Ce qui est mesuré, c'est chaque
morceau du chemin, dont le seul qui n'était pas testable autrement : les octets qui
arrivent au bon endroit.

## GPU-7 — ce que Modal facture vraiment, à côté de ce que nous comptons

Demande du propriétaire, le 20/09/2026 : « *mesure modal pour moi, date du premier cas où
le budget de 30 € a commencé à être débité est probablement le t0* ». Puis, dans le même
tour : « *on avait 30 € de crédit modal juste avant le premier usage de modal par studio ;
c'est le t0 du compteur* ».

**Les deux phrases sont vérifiées — et la seconde est ce qui rend la mesure concluante.**

### Ce que Modal dit de lui-même

Le client `modal` est installé sur le poste et déjà authentifié (espace de travail
`jp-brasile`). `modal billing report` rend la facture jour par jour ; aucun chiffre
ci-dessous n'a été saisi à la main.

| question | réponse, relevée le 20/09/2026 |
|---|---|
| premier jour facturé, toutes applications confondues | **09/04/2026** — du fine-tuning (`gemma4-lora`, `qwen36-codegen-lora`), un autre chantier |
| ce qu'avril a coûté | **23,68 $** sur les 30 $ du mois |
| premier jour facturé au nom du Studio | **09/09/2026, 11 h** (Paris), 0,2382 $ |
| septembre, tel que Modal le facture | **3,7971 $**, six jours, tous `free-ai-studio-sandbox` |
| cycle de facturation | **« Billing Cycle: Sep 1 - Oct 1, 2026 »** |
| plan | Starter, « $30.00 included compute credits per month » |
| crédit restant annoncé | **26,20 $** |

Mai, juin, juillet, août : **zéro ligne**. De septembre 2025 à mars 2026 : **zéro ligne**.
Modal refuse de remonter au-delà d'un an — c'est la limite de la mesure, pas une absence
prouvée, et c'est dit ici plutôt que tu.

### La réponse à la question posée

Le t0 du **cycle** n'est pas le premier débit. Le cycle est le **mois civil**, et il est
écrit — non pas dans la documentation publique, mais sur le tableau de bord de l'espace
de travail, page « Usage & billing ». Le « 1er du mois » retiré la veille faute de source
**était juste** ; ce qui lui manquait, c'était sa source, qui existait ailleurs que là où
je l'avais cherchée. Une leçon de méthode plutôt qu'un chiffre : *pas publié dans la doc*
ne veut pas dire *pas publié*.

Le t0 du **compteur**, lui, est bien celui que le propriétaire nomme : **le 09/09/2026 à
11 h**, les 30 $ intacts.

### Et c'est cette remarque-là qui fait tomber le vrai défaut

Si les 30 $ étaient intacts juste avant, alors les deux compteurs couvrent exactement la
même fenêtre et exactement le même travail — rien d'autre n'a tourné en septembre, les
six jours facturés portent tous le nom du Studio. La comparaison est donc légitime :

| | montant sur la même période |
|---|---|
| `config/modal-budget.json` (nous) | **1,3878 $** |
| `modal billing report` (eux) | **3,7971 $** |
| tableau de bord (eux) | **3,80 $** |
| crédit restant réel | **26,20 $** — et non 28,61 $ |

**Notre compteur voit 37 % de la facture.** Ce n'est pas un défaut d'affichage : ce
compteur sert à *refuser* avant de lancer. Au rythme mesuré, le plafond de 30 $ ne se
déclenche qu'aux alentours de **82 $ réellement facturés** — c'est-à-dire bien après la
fin du crédit, donc sur un moyen de paiement. `budget_modal.py` écrivait déjà, à propos
des prix des cartes : « *se tromper vers le bas est exactement ce qu'un compteur de refus
ne doit jamais faire* ». Il le faisait sur lui-même.

La cause n'est pas entièrement attribuée, et je ne la devine pas. Une part au moins est
du **stockage** : le relevé du 16/09/2026 conservé dans `depenses.py` porte une ligne
`volumes 0.383` que ce compteur, qui n'additionne que des secondes de calcul, ne voit
pas. Le temps de conteneur d'une application déployée et les constructions d'image sont
les autres candidats — **non mesurés**.

### Ce qui est fait, et ce qui ne l'est pas

**Fait dans le même tour, parce que ça ne déplace aucun nombre :** l'écart est écrit là
où le client le lit — la ligne du script (les deux jumeaux), la note déposée dans
`config/modal-budget.json`, et le module — avec ses deux chiffres et l'adresse du vrai.
Deux tests le gardent ; ils ont été **cassés exprès** pour vérifier qu'ils tombent (sans
la faute : 2 passés ; avec la faute : 2 échoués ; fichiers remis : 2 passés).

**Pas fait, et pas à moitié :** multiplier l'estimation par 2,74 remplacerait un nombre
faux par un nombre inventé — ce rapport est *une* mesure, sur *un* mois, sur *un* mélange
de travaux, pas un coefficient. La réparation est de lire le vrai chiffre et de le donner
au garde ; `depenses.py` sait déjà appeler `modal billing summary`. Rayon **mesuré** : le
garde est appelé dans **5 fichiers et 67 endroits**. C'est un chantier, donc un
sous-plan — **GPU-7 dans `PLAN.md`**, avec ses cinq champs.
