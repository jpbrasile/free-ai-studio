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

Le coût, sans l'arrondir :

- **torch + CUDA dans une image** : environ 3 Go, en plus des ~6 Go que le débutant
  télécharge déjà. Donc **une image séparée**, construite seulement quand une carte est
  vue : celui qui n'en a pas ne télécharge rien de plus.
- **Les poids de Wan 2.1 VACE 1.3B** : 19 Go (mesuré le 09/09), le gros morceau étant le
  lecteur de texte umT5 qui l'accompagne, pas le fabricant d'images.
- **Trois réglages déjà payés le 09/09**, à reprendre tels quels : `enable_model_cpu_offload()`
  sous 60 Go — pas 20 —, `vae.enable_tiling()`, et `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
  posé **avant** le premier `import torch`, sinon ignoré en silence.
- **Le premier chiffre à obtenir** : le clip de 3 s qui a coûté **422 s de calcul et
  0,096 $** sur une L4 chez Modal, refait sur la 4090. De combien la 4090 bat la L4 est
  **non mesuré** ici, et ne sera pas annoncé avant de l'être.

## Phase 3 — router

- `run_auto` et la vidéo demandent à `gpu_local.utilisable(besoin)` avant de louer.
- **Occupée ⇒ on va chez Modal.** On n'attend pas la carte, on n'arrête jamais le travail
  qui la tient : elle est partagée avec le jumeau plasma et, certains jours, un serveur
  LLM qui y tenait 15,5 Go le 04/09.
- Un manque de mémoire en cours de route est un **repli**, pas une panne du Studio.
- Sur la page, deux mots suffisent : « fait à la maison » ou « loué chez Modal », et ce
  que le travail aurait coûté.

## Ce qui est refusé d'avance

- **Réserver la carte au Studio.** Elle ne lui appartient pas.
- **Décider sur « une carte existe ».** La décision se prend sur la mémoire libre à
  l'instant du lancement, et se refait au lancement suivant.
- **Alourdir l'installation de celui qui n'a pas de carte.** C'est la promesse du produit.

## Non vérifié à ce jour

- De combien la 4090 bat la L4 louée.
- Le temps de premier chargement des 19 Go de poids depuis un disque local.
- La place disque totale que la phase 2 demande, et ce qu'elle fait grossir sous WSL2.
