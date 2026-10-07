"""Le chemin de la caméra d'un tour 360° et ses tronçons H3 épinglés, enchaînés par le latent (PLAN 21.6, étape 4
et « Tronçons »). C'est la recette de l'atelier du 06/10 (`scripts/decor360/latent_chaine.py`, tour v3 de 30 s,
« plus de saccades, tout est ok » et « le saut à 17/18 s a disparu », propriétaire) :

- des clips de 5 s ; dans un groupe (4 clips au plus), le 1er part de sa clé épinglée, les suivants du latent du
  précédent (MiniMaxH3MotionContext, 22 images de contexte) ; chaque clip finit sur sa clé épinglée (-1) ;
- une vue EXACTE du panorama épinglée tous les 7,5° (sans elles, H3 invente le chemin, dépasse et revient) ;
- chaque groupe repart d'une clé : la dérive ne s'accumule pas.

Les vues (clés et épingles) sont découpées dans le panorama SUR LA MACHINE de calcul, qui a numpy et Pillow (le
Studio n'en a pas) ; les clips d'un groupe y sont recollés en un seul `video.mp4`.

Caméra (propriétaire, 06/10 : « pour la caméra une liste défilante pour les options ; la durée de 30 s est un
paramètre réglable ») : tour complet à droite ou à gauche, demi-tour, quart de tour, aller-retour sur un angle
choisi. La durée fixe le nombre de clips (5 s chacun), donc la vitesse.
"""
import base64
import json
import math

import video_h3

DUREE_CLIP_S = 5
DUREE_DEFAUT_S = 30
DUREE_MIN_S, DUREE_MAX_S = 10, 120
ECART_PIN = 7.5                    # une vue exacte épinglée tous les 7,5°
PAS_MIN, PAS_MAX = 5.0, 90.0       # degrés par clip de 5 s ; 60 mesuré (tour v3), au-delà de 90 rien de mesuré
PAR_GROUPE_MAX = 4                 # au-delà de ~4 raccords la texture se dégrade (video_h3.PLANS_MAX)
LONGUEUR_1, LONGUEUR_SUITE, CONTEXTE = 124, 141, 22
DEFINITION = "768p"
GROUPE_MAISON_S = 1800             # mesuré : groupe de 3 clips en 803,7 s sur la 4090 (tour v3, 06/10)
GROUPE_MODAL_S = 2400

CAMERAS = {
    "tour_droite": {"titre": "Tour complet vers la droite", "angle": 360.0},
    "tour_gauche": {"titre": "Tour complet vers la gauche", "angle": -360.0},
    "demi_tour": {"titre": "Demi-tour vers la droite", "angle": 180.0},
    "quart_de_tour": {"titre": "Quart de tour vers la droite", "angle": 90.0},
    "aller_retour": {"titre": "Aller-retour lent (angle choisi)", "angle": None},
}
CAMERA_DEFAUT = {"camera": "tour_droite", "duree_s": DUREE_DEFAUT_S, "cap_depart": 0.0, "angle": 90.0}


def lire_camera(reglages) -> dict:
    """{camera, duree_s, cap_depart, angle (aller-retour : signé, négatif = vers la gauche)} ; ValueError sinon."""
    if reglages in (None, ""):
        reglages = {}
    if not isinstance(reglages, dict) or set(reglages) - set(CAMERA_DEFAUT):
        raise ValueError("Caméra : camera, duree_s, cap_depart, angle.")
    r = dict(CAMERA_DEFAUT, **reglages)
    if r["camera"] not in CAMERAS:
        raise ValueError("Caméra inconnue : %s." % " ; ".join(c["titre"] for c in CAMERAS.values()))
    try:
        r["duree_s"], r["cap_depart"], r["angle"] = int(r["duree_s"]), float(r["cap_depart"]), float(r["angle"])
    except (TypeError, ValueError):
        raise ValueError("Durée, cap ou angle illisible.") from None
    if not DUREE_MIN_S <= r["duree_s"] <= DUREE_MAX_S:
        raise ValueError("Durée du tour : de %d à %d s." % (DUREE_MIN_S, DUREE_MAX_S))
    if r["camera"] == "aller_retour" and not 15 <= abs(r["angle"]) <= 180:
        raise ValueError("Angle de l'aller-retour : de 15 à 180 degrés (négatif : vers la gauche).")
    r["cap_depart"] = (r["cap_depart"] + 180.0) % 360.0 - 180.0
    chemin(r)                                   # trop vite ou trop lent : refusé ici, avant tout calcul
    return r


def _repartir(n: int) -> list:
    """n clips en groupes de 4 au plus, de tailles égales à un près (6 -> 3 + 3, 5 -> 3 + 2)."""
    g = math.ceil(n / PAR_GROUPE_MAX)
    return [n // g + (1 if i < n % g else 0) for i in range(g)]


def chemin(reglages: dict) -> list:
    """Les groupes de clips : [[{a, b, arret}, ...], ...] ; a, b = caps (degrés) de départ et d'arrivée du clip.
    `arret` : le clip finit une branche (fin du tour, ou demi-tour d'un aller-retour) et ralentit sur sa clé."""
    r = reglages
    n = max(2, round(r["duree_s"] / DUREE_CLIP_S))
    angle = CAMERAS[r["camera"]]["angle"]
    if angle is None:                           # aller-retour : deux branches, demi-tour à une jointure de groupe
        n += n % 2
        branches = [(r["cap_depart"], r["angle"], n // 2), (r["cap_depart"] + r["angle"], -r["angle"], n // 2)]
    else:
        branches = [(r["cap_depart"], angle, n)]
    groupes = []
    for depart, total, clips in branches:
        pas = total / clips
        if abs(pas) > PAS_MAX:
            raise ValueError("Trop rapide : %.0f degrés par clip de 5 s (%d au plus) ; allongez la durée."
                             % (abs(pas), PAS_MAX))
        if abs(pas) < PAS_MIN:
            raise ValueError("Trop lent : %.1f degrés par clip de 5 s (%d au moins) ; raccourcissez la durée."
                             % (abs(pas), PAS_MIN))
        k = 0
        for taille in _repartir(clips):
            groupes.append([{"a": round(depart + pas * (k + j), 3), "b": round(depart + pas * (k + j + 1), 3),
                             "arret": k + j == clips - 1} for j in range(taille)])
            k += taille
    return groupes


def dans(cap: float, a0: float, a1: float) -> bool:
    """Le cap tombe-t-il dans le secteur [a0, a1] (degrés, a1 >= a0, à 360 près) ?"""
    return (cap - a0) % 360.0 <= a1 - a0


def epingles(clip: dict, suite: bool, zones=()) -> dict:
    """{image du clip: cap} des vues exactes entre ses deux clés. Clip de tête : 124 images, image f = f / 123 du
    chemin ; clip enchaîné : 141 images dont 22 de contexte, rendue r = f - 22 -> (r + 1) / 119 du chemin.
    `zones` : [(a0, a1, ecart)] secteurs (caps dont le champ voit quelque chose qui bouge) où une vue exacte
    figerait ce qui bouge : ecart None ou 0 = aucune épingle (un personnage absent du panorama : épinglée, la pièce
    vide l'efface ; peint, ou un feu : épinglés, ils restent figés comme une photo — château, 07/10, même à une
    épingle tous les 22,5°) ; sinon une épingle tous les `ecart` degrés au lieu de ECART_PIN."""
    a, b = clip["a"], clip["b"]
    m = max(1, round(abs(b - a) / ECART_PIN))
    if not suite:
        tout = {round(123 * j / m): (j, a + (b - a) * round(123 * j / m) / 123) for j in range(1, m)}
    else:
        tout = {CONTEXTE + round(119 * j / m) - 1: (j, a + (b - a) * round(119 * j / m) / 119) for j in range(1, m)}
    garde = {}
    for f, (j, cap) in tout.items():
        ecarts = [e for a0, a1, e in zones if dans(cap, a0, a1)]
        if any(not e for e in ecarts):
            continue
        if ecarts:
            pas = max(1, round(max(ecarts) / ECART_PIN))
            # le compte part du départ absolu du tour : les épingles restantes tombent aux mêmes caps d'un clip à
            # l'autre
            if round(cap / ECART_PIN) % pas:
                continue
        garde[f] = cap
    return garde


_PROPRES = {"10", "12", "13", "14", "15", "16", "17", "18"}


def demande_groupe(clips: list, invites: list, sujets: list, cartes_png: dict, pano_png: bytes, fx: float,
                   graine: int, delai_s: int, zones=(), ref_image_size: str = "match") -> dict:
    """La demande d'un groupe pour le script H3 du Studio : un seul graphe, ses images (cartes), et les vues à
    découper du panorama sur la machine ({nom: cap}). `sujets[i]` : noms des images du clip i (cartes, photos d'un
    personnage), dans l'ordre de ses <Picture N> après les clés. `zones` : voir `epingles`. Un clip dont la clé
    d'arrivée tombe dans une zone sans épingle (`fin` faux) n'a ni clé d'arrivée en référence ni épingle de fin.
    `ref_image_size` : « match » (références réduites à la surface de la vidéo) ou « max » (2048 px de petit côté :
    l'identité la plus fidèle, plusieurs fois plus lent ; nœud MiniMaxH3ReferenceToVideo)."""
    if not 1 <= len(clips) <= PAR_GROUPE_MAX or not len(clips) == len(invites) == len(sujets):
        raise ValueError("Groupe de clips illisible.")
    g, images, vues = {}, {}, {}
    classes = {"MiniMaxH3ReferenceToVideo", "MiniMaxH3AddGuide"}
    precedent = None
    for i, clip in enumerate(clips):
        p, suite = ("", False) if i == 0 else ("bcd"[i - 1], True)
        fin = clip.get("fin", True)
        if not suite and not clip.get("debut", True):
            raise ValueError("Le premier clip d'un groupe part de sa clé épinglée.")
        cles = ([] if suite else [clip["a"]]) + ([clip["b"]] if fin else [])
        if len(cles) + len(sujets[i]) > 9:
            raise ValueError("Plus de 9 images pour un clip.")
        g2 = video_h3.graphe("references", invites[i], LONGUEUR_SUITE if suite else LONGUEUR_1, graine,
                             len(cles) + len(sujets[i]), DEFINITION)
        g2["10"]["inputs"]["ref_image_size"] = ref_image_size
        propres = {k for k in g2 if k in _PROPRES or k.startswith("6")}

        def renomme(v, p=p, propres=propres):
            return [p + v[0], v[1]] if isinstance(v, list) and len(v) == 2 and v[0] in propres else v
        for k, nd in g2.items():
            if k in propres:
                nd = json.loads(json.dumps(nd))
                nd["inputs"] = {a: renomme(v) for a, v in nd["inputs"].items()}
                if nd["class_type"] == "LoadImage":
                    nd["inputs"]["image"] = p + "_" + nd["inputs"]["image"]
                g[p + k] = nd
            elif i == 0:
                g[k] = nd
        noms = [p + "_ref_%d.png" % j for j in range(len(cles) + len(sujets[i]))]
        for nom, cap in zip(noms, cles):
            vues[nom] = cap
        for nom, carte in zip(noms[len(cles):], sujets[i]):
            images[nom] = base64.b64encode(cartes_png[carte]).decode()

        def guide(nom, depart, image, frame, p=p):
            g[nom] = video_h3._n("MiniMaxH3AddGuide", {"positive": [depart, 0], "vae": ["4", 0],
                                                      "latent": [p + "10", 1], "image": image, "frame_idx": frame})
            return nom
        tete = p + "10"
        if not suite:
            tete = guide("11", tete, ["60", 0], 0)
        for j, (f, cap) in enumerate(sorted(epingles(clip, suite, zones).items()), 1):
            vues[p + "_pin_%d.png" % j] = cap
            g[p + "v%d" % j] = video_h3._n("LoadImage", {"image": p + "_pin_%d.png" % j})
            tete = guide(p + "e%d" % j, tete, [p + "v%d" % j, 0], f)
        if fin:
            tete = guide(p + "19", tete, [p + ("60" if suite else "61"), 0], -1)
        if suite:
            g[p + "31"] = video_h3._n("MiniMaxH3MotionContext", {
                "conditioning": [tete, 0], "vae": ["4", 0], "latent": [p + "10", 1],
                "context_length": video_h3.CONTEXTE_IMAGES, "audio_context_length": video_h3.CONTEXTE_SON,
                "context_latent": [precedent, 0]})
            tete = p + "31"
            g[p + "32"] = video_h3._n("MiniMaxH3MotionContextTrim", {
                "images": [p + "15", 0], "audio": [p + "16", 0], "trim_frames": [p + "31", 1],
                "fps": float(video_h3.IMAGES_PAR_SECONDE)})
            g[p + "17"]["inputs"].update({"images": [p + "32", 0], "audio": [p + "32", 1]})
            classes |= {"MiniMaxH3MotionContext", "MiniMaxH3MotionContextTrim"}
        g[p + "13"]["inputs"]["conditioning"] = [tete, 0]
        g[p + "18"]["inputs"]["filename_prefix"] = "h3/clip_%d" % (i + 1)
        precedent = p + "14"
    classes |= {nd["class_type"] for nd in g.values()}
    return {"mode": "references", "graphe": g, "classes": sorted(classes), "images": images, "sons": {},
            "fichiers": list(video_h3.fichiers_du_mode("references")), "base_poids": video_h3.POINT_DE_MONTAGE,
            "comfy": video_h3.DOSSIER_COMFY, "comfy_version": video_h3.COMFY_VERSION, "coupe_s": 0.0,
            "delai_s": delai_s, "longueur": LONGUEUR_1 + (len(clips) - 1) * (LONGUEUR_SUITE - CONTEXTE),
            "graine": graine,
            "vues": {"pano": base64.b64encode(pano_png).decode(), "fx": fx, "l": 1344, "h": 768, "caps": vues},
            "assembler": True}


# Avant l'écriture des images dans ComfyUI : les vues exactes du panorama (même échantillonnage que
# tour360_pano.vue, qui a fait les clés du tour).
_VUES = r'''
if D.get("vues"):
    import io
    import math as _m
    import numpy as np
    from PIL import Image
    _p = np.asarray(Image.open(io.BytesIO(base64.b64decode(D["vues"]["pano"]))).convert("RGB")).astype(np.float32)

    def _vue(cap, fx=D["vues"]["fx"], l=D["vues"]["l"], h=D["vues"]["h"]):
        hp, lp = _p.shape[:2]
        x, y = np.meshgrid((np.arange(l) - l / 2 + 0.5) / fx, (np.arange(h) - h / 2 + 0.5) / fx)
        c, s = _m.cos(_m.radians(cap)), _m.sin(_m.radians(cap))
        X, Z = x * c + s, -x * s + c
        u = (np.arctan2(X, Z) / (2 * np.pi) + 0.5) * lp - 0.5
        v = np.clip((0.5 - np.arctan2(-y, np.hypot(X, Z)) / np.pi) * hp - 0.5, 0, hp - 1.001)
        u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
        du, dv = (u - u0)[..., None], (v - v0)[..., None]
        u1, u0, v1 = (u0 + 1) % lp, u0 % lp, np.clip(v0 + 1, 0, hp - 1)
        r = (_p[v0, u0] * (1 - du) + _p[v0, u1] * du) * (1 - dv) + (_p[v1, u0] * (1 - du) + _p[v1, u1] * du) * dv
        return r.clip(0, 255).astype(np.uint8)

    for _nom, _cap in D["vues"]["caps"].items():
        _t = io.BytesIO()
        Image.fromarray(_vue(_cap)).save(_t, format="PNG")
        D["images"][_nom] = base64.b64encode(_t.getvalue()).decode()
    del _p
'''

# Les clips du groupe, recollés tels quels (même graphe, même codec) en un seul film.
_ASSEMBLER = r'''if D.get("assembler"):
    Path("/tmp/clips.txt").write_text("".join("file '%s'\n" % c for c in clips))
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "/tmp/clips.txt",
                        "-c", "copy", str(OUT / "video.mp4")], capture_output=True, text=True)
    if r.returncode:
        echouer(9, "COUPE_ECHOUEE", r.stderr)
else:
    shutil.copyfile(clips[-1], OUT / "video.mp4")'''

_ANCRE_VUES = '(COMFY / "input").mkdir(exist_ok=True)\n'
_ANCRE_FIN = 'else:\n    shutil.copyfile(clips[-1], OUT / "video.mp4")'


def construire_script(demande: dict) -> str:
    script = video_h3.construire_script(demande)
    if script.count(_ANCRE_VUES) != 1 or script.count(_ANCRE_FIN) != 1:
        raise RuntimeError("Le script H3 du Studio a changé : tour360_chaine.construire_script à revoir.")
    script = script.replace(_ANCRE_VUES, _VUES + _ANCRE_VUES)
    # « if D["coupe_s"] > 0: … else: copie du dernier clip » -> « … elif assembler … »
    return script.replace(_ANCRE_FIN, "el" + _ASSEMBLER)
