# Décor 360° et autres angles d'un lieu — recette

Essais du 05/10/2026 (salon de Leila, clip 11), avant branchement dans le Studio. Scripts : `scripts/decor360/`.
Rien ici ne tourne depuis la page : ce sont des scripts d'atelier, lancés à la main.

**Licence.** Qwen-Image 2.1 et l'Union ControlNet de Qwen 2.1 sont sous licence de recherche Qwen, **non commerciale**.
Le LoRA AnyAngle est Apache-2.0, mais il tourne sur Qwen 2.1. Blender est GPL : il reste un programme à part, appelé
en ligne de commande, jamais importé. L'usage commercial reste à trancher par le propriétaire.

## Quand

- Un lieu a **une** photo (la « plaque », 16:9) et il faut le reste de la pièce : contrechamp, côtés, autre position
  de caméra. L'image du Studio (Gemini) ne sait pas tourner autour d'un lieu (FRICTIONS, 03/10).
- La règle des 180° tient tant qu'on n'a pas fait ce qui suit.

## Faire

1. **Maquette en boîtes** (`maquette.py`, NumPy + PIL, ~10 s) : pièce, ouvertures, baie, meubles, calés sur la plaque
   (fx de la plaque, hauteur de caméra déduite d'un meuble connu). Contrôle : `maquette_vue_000_calage.png` (maquette
   en fondu sur la plaque) ; les arêtes doivent tomber sur celles de la photo. L'arrière, que la photo ne montre
   pas, se décide ici, à la main.
   `python maquette.py <plaque.png> <dossier>`
2. **Panorama 360°** (`maquette4_modal.py`, Modal A100, ~2 min 30 par essai) : Qwen 2.1 + Union, contrôle **Lineart
   sur les arêtes** de la maquette, à 2048×1024, repeint hors de la plaque ; couture (demi-tour, bande de ±25°) ;
   SeedVR2 ×2 ; plaque d'origine recollée à pleine résolution ; six vues à plat.
   `python maquette4_modal.py <dossier maquette> <sortie> L11 L7` (dans le conteneur du routeur, client Modal ; le
   dossier contient les `maquette_*.png` de l'étape 1 et la plaque sous le nom `plaque.png`).
   La consigne **décrit ce que l'on veut voir là où la photo ne voit pas** et ne cite pas ce qui ne doit pas y être
   (le jardin cité revenait derrière la caméra).
3. **Autres angles par la 3D** (`preparer_scene.py`, `scene_blender.py`, `anyangle_local.py`) : la même maquette
   devient une scène Blender ; la plaque et le contrechamp (vue 180 de l'étape 2) y sont projetés depuis leur caméra ;
   rendu grossier de chaque caméra voulue (Cycles, processeur, ~10 s par vue) ; puis Qwen 2.1 + LoRA AnyAngle
   reporte la photo sur ce rendu (« Change the camera angle from <image2> to <image1>. », force 1, CFG 3, 25 pas).
   ```
   python preparer_scene.py <plaque.png> <contrechamp.png> <essai>/scene.json <pano.png de l'étape 2>
   blender -b --factory-startup -noaudio -P scene_blender.py -- <essai>/scene.json <essai>/rendus
   python file_attente.py deposer --nom anyangle --ressources gpu -- python anyangle_local.py <essai> 11
   ```
   **Toujours donner le panorama** : AnyAngle ne suit l'angle que là où le rendu porte de la matière (voir Résultats).
   Contrôle avant la 4090 : `rendus/rendu_verif_plaque.png` doit redonner la plaque.
4. **Vue qui ne montre qu'un mur nu** : AnyAngle n'y trouve aucun repère et refait la vue de face. Retouche Qwen 2.1
   **sans** LoRA, le rendu en `<image1>` (base), la plaque en `<image2>` (matière) : « Turn <image1> into a realistic
   photograph of the same living room as <image2> … Keep the camera, the walls and the doorway of <image1> exactly
   where they are. » La géométrie du rendu est gardée.
   `python file_attente.py deposer --nom polir --ressources gpu -- python anyangle_local.py --polir <essai> v060 11`

## Caméra H3 dans un décor 3D : plan d'abord

Pour un mouvement de caméra H3 (travelling, tour sur place) où le décor doit **rester fixe**. Une maquette calée à
l'œil (étape 1) ne suffit pas : la baie glissait dans le clip, parce que la caméra supposée (fx 904, 0,9 m, horizontale,
baie à x = -1) n'était pas la vraie. On mesure d'abord, puis on pose les emprises au sol, puis la hauteur.

1. **Géométrie de la plaque** : MoGe-3 (`Ruicheng/moge-3-vitl`, MIT) dans un conteneur jetable de l'image ComfyUI du
   Studio. Sortie : nuage de points métrique, intrinsèques, normales, masque. ~2,5 Go de VRAM.
   `file_attente.py deposer --nom moge --ressources gpu -- python moge_plaque.py <plaque.png> <dossier plaque>/moge.npz`
2. **Repère et vue de dessus** : sol par RANSAC (hauteur et tangage réels), murs alignés sur les axes (lacet de la
   plaque par rapport aux murs), vue de dessus à 1 cm/px (couleur | hauteur).
   `python plan_moge.py moge.npz plaque.png <dossier>` → `plan_moge.png`, `repere_moge.json`
3. **Le plan, à la main, sur `plan_moge.png`** (JSON, repère de la pièce : x à droite, z devant, caméra de la plaque à
   l'origine) : caméra `{hauteur, lacet, tangage, f}` tirée de `repere_moge.json` ; pièce ; baie ; éléments
   `{emprise [x0,x1,z0,z1], hauteur [bas,haut]}` ; ouvertures ; **cibles relatives** `{devant, droite, tourne}`.
   Exemple : `Desktop\leila_sf\interieur\blender3\plan_salon.json`.
4. **Scène puis rendus** : `python scene_plan.py plan.json plaque.png contre.png pano.png <essai>/scene.json`, puis
   `scene_blender.py` comme à l'étape 3. Il fait maintenant l'**occultation** (carte de profondeur équirectangulaire
   depuis l'origine, vitre exclue, `profondeur.exr`) et vérifie des profondeurs connues (`controles` du scene.json) :
   écart > 0,05 m ⇒ arrêt avant tout rendu.
5. **Dernière image** : `anyangle_local.py <essai> 11 <caméra>` (seulement cette caméra, sans témoin).
6. **Clip H3** (première = plaque, dernière = vue AnyAngle), par la file, ressource gpu, ~170 s sur la 4090 :
   `python travelling_h3.py plaque.png anyangle/<cam>_aa_g11.png travelling/<nom>.mp4 11 [124] [--consigne c.json]`
   **Tour 360°** : rotation sur place, donc exacte (aucune parallaxe). Cibles `tourne` 45, 90 … 315 à `devant = droite
   = 0` ; les rendus servent directement d'images clés (pas d'AnyAngle) ; 8 clips H3 « pano_droite » de 45° mis bout
   à bout : `python tour360_h3.py <essai> 11` → `<essai>/tour360/tour360_g11.mp4`.

## Résultats (05/10, salon de Leila, 4090, graine 11)

Planche : `Desktop\leila_sf\interieur\PLANCHE_DECOR_360.jpg`. AnyAngle 46-89 s par image ; Blender ~65 s les 6 rendus.

| Caméra | Essai 1 (plaque + contrechamp) | Essai 2 (+ panorama) |
|---|---|---|
| avance (travelling 1,5 m) | angle suivi ; table devenue 2e assise | angle suivi ; table en double plateau (vient du rendu) |
| recul (vers la bibliothèque) | propre | propre |
| v300 (baie, jardin) | photo de face collée dans la vitre — échec | baie et jardin, angle suivi — réussi |
| v060 (mur droit) | vue de face refaite — échec | vue de face refaite — échec ; étape 4 : mur nu propre |

Témoin sans LoRA (v060) : la plaque revient presque inchangée, le LoRA agit bien. Jugé à l'œil, une graine.

## Voies bouchées (05/10)

- Latent gris de la maquette, débruitage 0,75 : reste un dessin gris.
- Couleurs de la maquette données à l'Union : **l'Union efface `inpaint_image` sous le masque**, sortie identique.
- Panorama à 1024 puis SeedVR2 ×4 : détail inventé (jardin peint, moquette ondulée). Naître à 2048, ×2 une fois.
- Profondeur seule : l'Union ne connaît pas l'équirectangulaire, droites courbes. Profondeur + arêtes enchaînées
  (DL11) : les meubles se perdent. Les arêtes seules gagnent.
- Bords de la plaque : des arêtes et une consigne ne disent pas « vitre » ni « couloir ». À 300°, la baie n'est
  venue qu'avec la graine 7 (montants ajoutés à la maquette + consigne) ; à 60°, mur nu sur toutes les graines.
  D'où l'étape 3 : la 3D montre la matière, pas seulement le trait. Avec l'étape 3, la baie à 300° vient à la
  graine 11 ; à 60° le mur reste nu, parce que la maquette n'y met rien : c'est à décider dans la maquette.
- AnyAngle sur un rendu non texturé à 80 % (essai 1, sans panorama) : il recolle la photo source au lieu de tourner.

## Pièges

- `cv2` de l'hôte cassé par NumPy 2 : scripts locaux en NumPy + PIL.
- Le conteneur du routeur n'a pas NumPy : la scène (`scene.json`) se prépare sur l'hôte.
- La projection de `scene_blender.py` ne connaît pas l'occultation : exacte depuis le point des photos (rotation
  seule), traînées derrière les meubles dès que la caméra se déplace.
- Une boîte de meuble porte sur sa face avant les pixels de ce qui est derrière elle dans la photo : table en
  double plateau au travelling. Limite des boîtes ; un vrai maillage (MoGe-2, Trellis2) est la suite.
- Arête brillante au chambranle de la porte à 60°, dans le rendu et donc dans la retouche ; cause non trouvée.
- MoGe-3 sous Windows/Anaconda : `libtriton` ne charge pas (le runtime VC 14.27 de `Anaconda\Library\bin` passe avant
  celui de System32 ; triton-windows en veut ≥ 14.42). Ne pas bricoler : **MoGe tourne dans Docker** (`moge_plaque.py`).
- `np.linalg.svd` sur le nuage entier sans `full_matrices=False` demande 215 Gio : NumPy refuse, mais c'est le piège.
- Mesures du salon (05/10) : caméra à 1,23 m, inclinée de 2,38° vers le bas, tournée de 13,1° par rapport aux murs,
  fx 756 ; baie à x = -0,16. Rien de cela ne se devine à l'œil.
- Le contrechamp et le panorama ont été faits sur l'ancienne maquette : ce que la plaque ne voit pas en hérite
  (mur proche droit devenu porte vitrée au travelling). À refaire depuis le plan.
- Les vues de `scene_blender.py` en « Standard » (pas AgX/Filmic) : sinon la photo projetée change de couleurs.
