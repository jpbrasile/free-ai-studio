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

- `run_auto` et la vidéo demandent à `gpu_local.utilisable(besoin)` avant de louer.
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

## Ce qui est refusé d'avance

- **Réserver la carte au Studio.** Elle ne lui appartient pas.
- **Décider sur « une carte existe ».** La décision se prend sur la mémoire libre à
  l'instant du lancement, et se refait au lancement suivant.
- **Alourdir l'installation de celui qui n'a pas de carte.** C'est la promesse du produit.

## Non vérifié à ce jour

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
