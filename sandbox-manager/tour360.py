"""Le tour 360° d'un décor, fait seul (propriétaire, 06/10 : « adapt studio to automate that »).

La recette d'atelier de docs/DECOR_360.md (étape 7), sans main, depuis une fiche « décor » :
  consigne   le chat regarde la photo du décor et écrit la consigne du panorama (ce que la photo ne montre pas) ;
  panorama   une carte louée (tour360_pano.py) : MoGe-3 mesure la pièce, la boîte guide Qwen-Image 2.1 + Union,
             SeedVR2, la photo recollée ; les images clés du tour découpées dans ce SEUL panorama, tous les PAS degrés ;
  cartes     les cartes d'identité des éléments : le chat voit les images clés et nomme chaque élément (meuble,
             ouverture, mur nu) avec sa place dans chaque vue ; l'azimut en est tiré ;
  troncons   (PLAN 21.6 étape 4, recette du tour v3 de l'atelier, tour360_chaine) le chemin de la caméra choisi
             (tour, demi-tour, quart de tour, aller-retour ; durée réglable) en clips de 5 s, Ref2VA : chaque élément
             croisé est un <Subject N> défini par sa carte ; une vue exacte du panorama épinglée tous les 7,5° ; les
             clips d'un groupe (4 au plus) enchaînés par le latent, un travail H3 par groupe ;
  montage    les groupes bout à bout, un même fond sonore (`lieux`) ;
  finition   (PLAN 21.6 étape 5, atelier du 06/10 : « plus de saccades, tout est ok ») la 4K d'abord
             (/video-h3/finaliser), la musique (/chanson/creer puis /video-h3/musique), puis 60 images/s à pas
             réguliers (/video-h3/fluidifier, mouvement mesuré sur le montage d'avant la 4K : une 4K efface la
             texture d'un mur nu), puis l'AV1 (/video-h3/compresser). Chaque morceau est optionnel ; la musique
             qui échoue n'arrête pas le tour (le film reste sans musique, l'état le dit).
Chaque étape écrit l'état ; une reprise saute les étapes faites (comme film_auto).

PLAN 21.6 étapes 1 à 3 (06/10) : entre la consigne et le panorama,
  mesure     MoGe-3 seul (tour360_pano, mode « mesure ») : la pièce, la caméra, les points ; ici si le tour est
             « ici », chez Modal sinon ;
  plan       le chat propose le plan au sol (plan_piece : ce que la photo montre, par cadres mesurés ; le reste,
             imaginé) ; le tour ATTEND (statut « plan_a_valider ») : le client le retouche en écrivant
             (retoucher_plan), puis le valide (valider_plan) ; le panorama ne part qu'après (seule la mesure,
             gratuite ici, coûte une L4 de quelques minutes chez Modal quand le tour n'est pas « ici ») ;
puis le panorama dessine la maquette PAR PARTIES du plan, et les cartes en sont calculées (le chat n'a écrit que
les descriptions).
"""
import base64
import hashlib
import json
import math
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

import agrandir
import plan_piece
import retouche_qwen as rq
import tour360_chaine as chaine
import video_h3

GPU = "A100-80GB"         # celle de l'atelier (maquette4_modal) : Qwen 2.1 + Union à 2048×1024, puis SeedVR2
MEMOIRE_MB = 65536
COEURS = 8.0
DUREE_MAX_S = 2400
PAQUETS = video_h3.PAQUETS_POIDS
PAS_PERMIS = (30, 45)     # 45 : 8 tronçons ; 30 : 12, plus sûr sur un mur nu (06/10, tronçon 6 : une pièce inventée)
PAS = 45                  # écart des images clés que le chat regarde pour les cartes (pas celui des clips)
GRAINE = 11
RESOLUTION = 1440         # -> latent 2048×1024 pour l'image 2:1
MOGE_DEPOT = "git+https://github.com/microsoft/MoGe.git@74fbce054ebed49800de42d0ad0e83495065719a"
MOGE_MODELE = "Ruicheng/moge-3-vitl"
# La mesure seule (PLAN 21.6 étape 1, MoGe-3 : ~20 s et 2,5 Go de carte, 05/10) : ici, la carte de cet ordinateur
# lit les poids sur /poids (le bac à sable n'a pas Internet) ; chez Modal, une L4 suffit.
MOGE_MAISON = "/poids/moge-3-vitl/model.pt"
GPU_MESURE = "L4"
MEMOIRE_MESURE_MB = 16384
COEURS_MESURE = 4.0
DUREE_MESURE_S = 900
T8 = ("https://github.com/T8mars/Comfyui-Qwen-Image-2.1-Fun-Controlnet-Union-T8",
      "01f084ccde2f2a262529b6e7b5504df9ea36a0b7")
UNION = ("Qwen-Image-2.1-Fun-Controlnet-Union-ComfyUI.safetensors", "t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy",
         "199bd863c41b5401e3c9bbc2b1bd4b62f468229c")
ATTENTE_PAS_S = 15
ATTENTE_MAX_S = 3 * 3600
CARTES_MAX = 24
# La finition (PLAN 21.6 étape 5). La musique : YuE2 + LoRA instrumentale chez Modal (~0,04 $ mesuré le 06/10).
FINITION_DEFAUT = {"4k": True, "musique": "instrumental ambient, soft piano and warm strings, slow tempo",
                   "fluide": True, "compresser": True}
MUSIQUE_VOLUME = 0.6
MUSIQUE_FONDU_S = 1.5
DESCRIPTION_MAX = 220

# Une image clé : 1344 × 768 (tour360_pano.VUE_L/VUE_H) ; sa focale est dans geometrie.json (fx_vue).
VUE_L, VUE_H = 1344, 768


def commandes() -> tuple:
    """ComfyUI (celui de H3), le nœud Union de T8 à son commit, MoGe à son commit."""
    dossier = video_h3.DOSSIER_COMFY + "/custom_nodes/union_t8"
    return video_h3.COMMANDES + (f"git clone {T8[0]} {dossier}", f"cd {dossier} && git checkout {T8[1]}",
                                 f"pip install {MOGE_DEPOT}")


# --- Les graphes ComfyUI ------------------------------------------------------------------------------------------

def graphe_union(entree: str, masque: str, aretes: str, consigne: str, graine: int) -> dict:
    """Qwen-Image 2.1 + Union, contrôle Lineart sur les arêtes de la boîte, repeint sous le masque."""
    g = rq.graphe("plaque.png", [], consigne, graine)
    g["4"] = {"class_type": "QwenImage21UnionLoader", "inputs": {"union_model": UNION[0]}}
    g["20"] = {"class_type": "LoadImage", "inputs": {"image": entree}}
    g["21"] = {"class_type": "LoadImageMask", "inputs": {"image": masque, "channel": "red"}}
    g["60"] = {"class_type": "LoadImage", "inputs": {"image": aretes}}
    g["70"] = {"class_type": "QwenImage21UnionApply",
               "inputs": {"control_mode": "Lineart", "strength": 1.0, "start_percent": 0.0, "end_percent": 1.0,
                          "model": ["1", 0], "union_patch": ["4", 0], "vae": ["3", 0], "control_image": ["60", 0],
                          "inpaint_image": ["20", 0], "mask": ["21", 0]}}
    g["13"] = {"class_type": "QwenImage21UnionLatentFromImage", "inputs": {"resolution": RESOLUTION,
                                                                           "image": ["20", 0]}}
    g["41"]["inputs"].update({"model": ["70", 0], "latent_image": ["13", 0]})
    return g


def graphe_agrandi() -> dict:
    """SeedVR2 ×2 sur une image (le graphe vidéo d'agrandir.py, une image répétée en lot)."""
    s = agrandir.graphe("x.mp4", "x2", "agrandi")
    s["1"] = {"class_type": "LoadImage", "inputs": {"image": "a_agrandir.png"}}
    s["2"] = {"class_type": "RepeatImageBatch", "inputs": {"image": ["1", 0], "amount": agrandir.MULTIPLE}}
    s["3"]["inputs"]["input"] = ["2", 0]
    del s["14"], s["15"]
    s["16"] = {"class_type": "ImageFromBatch", "inputs": {"image": ["13", 0], "batch_index": 0, "length": 1}}
    s["43"] = {"class_type": "SaveImage", "inputs": {"images": ["16", 0], "filename_prefix": "agrandi"}}
    return s


def demande_mesure(photo: bytes, maison: bool = False) -> dict:
    """La mesure seule : MoGe -> geometrie.json (avec les retraits des bords) et grille.json."""
    return {"mode": "mesure", "poids": [], "photo": base64.b64encode(photo).decode(),
            "moge": MOGE_MAISON if maison else MOGE_MODELE, "pas": PAS, "delai_s": DUREE_MESURE_S - 60}


def construire_mesure(photo: bytes, maison: bool = False) -> str:
    source = Path(__file__).with_name("tour360_pano.py").read_text(encoding="utf-8")
    return video_h3._emballer(source + "\n\nprincipal()\n", demande_mesure(photo, maison))


def construire_incrustation(mode: str, pano: bytes, cap: float, fx: float, image: bytes = None) -> str:
    """Le personnage peint dans le panorama (07/10) : « vue » découpe la vue au cap du personnage ; « coller »
    recolle dans le panorama ce que l'image du Studio y a ajouté (tour360_pano.coller). NumPy seul, sans poids."""
    source = Path(__file__).with_name("tour360_pano.py").read_text(encoding="utf-8")
    d = {"mode": mode, "poids": [], "pano": base64.b64encode(pano).decode(), "cap": float(cap), "fx": float(fx),
         "delai_s": DUREE_MESURE_S - 60}
    if image is not None:
        d["image"] = base64.b64encode(image).decode()
    return video_h3._emballer(source + "\n\nprincipal()\n", d)


def demande(photo: bytes, consigne: str, graine: int = GRAINE, pas: int = PAS, geo=None, scene=None,
            cartes=None) -> dict:
    graphes = {"graphe_dessin": graphe_union("maquette.png", "masque.png", "aretes.png", consigne, graine),
               "graphe_couture": graphe_union("tourne.png", "bande.png", "aretes_tourne.png", consigne, graine),
               "graphe_agrandi": graphe_agrandi()}
    classes = sorted({n["class_type"] for g in graphes.values() for n in g.values()})
    return dict(graphes, poids=[
        {"depot": rq.HF, "revision": rq.HF_REVISION, "fichiers": list(rq.FICHIERS), "base": rq.DOSSIER_POIDS},
        {"depot": UNION[1], "revision": UNION[2], "fichiers": [UNION[0]], "base": rq.DOSSIER_POIDS + "/controlnet"},
        {"depot": agrandir.HF, "revision": agrandir.HF_REVISION, "fichiers": list(agrandir.FICHIERS),
         "base": agrandir.DOSSIER_POIDS}],
        **({"photo": base64.b64encode(photo).decode()} if photo else {}), moge=MOGE_MODELE, pas=int(pas), comfy=video_h3.DOSSIER_COMFY,
        base_qwen=rq.DOSSIER_POIDS, base_seedvr=agrandir.DOSSIER_POIDS, classes=classes,
        delai_s=DUREE_MAX_S - 60, **({"geo": geo} if geo else {}), **({"scene": scene} if scene else {}),
        **({"cartes": cartes} if cartes else {}))


def construire_script(photo: bytes, consigne: str, graine: int = GRAINE, pas: int = PAS, geo=None, scene=None,
                      cartes=None) -> str:
    source = Path(__file__).with_name("tour360_pano.py").read_text(encoding="utf-8")
    return video_h3._emballer(source + "\n\nprincipal()\n",
                              demande(photo, consigne, graine, pas, geo, scene, cartes))


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("POIDS_ABSENTS", "Les poids (Qwen-Image 2.1, Union, SeedVR2) n'ont pas pu être posés sur le disque Modal."),
            ("NOEUD_ABSENT", "Ce ComfyUI n'a pas les nœuds Qwen-Image 2.1 Union."),
            ("GRAPHE_REFUSE", "ComfyUI a refusé un graphe du panorama."),
            ("COMFY_ARRETE", "ComfyUI s'est arrêté pendant le panorama (mémoire ?)."),
            ("CALCUL_ECHOUE", "Le panorama n'a pas pu être dessiné."),
            ("DELAI", "Le panorama n'était pas fini avant le délai."),
            ("PIECE_ILLISIBLE", "La photo du décor ne montre pas assez de sol pour mesurer la pièce."),
            ("RIEN_AJOUTE", "L'image du Studio n'a rien ajouté à la vue : le personnage n'est pas dans le panorama.")):
        if mot in s:
            return phrase
    return ""


# --- Ce que le chat écrit, et comment on le lit -------------------------------------------------------------------

# Le son d'ambiance (07/10, château) : H3 rend « room tone », « quiet sound », un silence demandé, en un ton continu
# (saillance 52 dB, un ton pur > 30 dB) ; une ou deux sources douces et concrètes (« Log fires crackle softly in the
# hearths ») donnent un son propre (27-32 dB). Ce qui demande un fond continu est retiré de la phrase du chat.
AMBIANCE_DEMANDE = ("<one sentence: one or two soft, concrete sounds heard in this place, e.g. a fire crackling "
                    "softly, a faint breeze, distant birds; never a hum, a drone or a room tone; no music, no voice>")
AMBIANCE_DEFAUT = "A faint breeze stirs softly in the distance."
FOND_CONTINU = re.compile(r"room tone|\bhum|\bdrone|\bbuzz|\bwhine|\bring(s|ing)?\b|\bsilen(ce|t)|quiet sound|"
                          r"\btone\b|\bno (sound|music)", re.I)


def ambiance_propre(texte: str) -> str:
    """La phrase d'ambiance sans ses morceaux qui demandent un fond continu (coupée aux « ; », « , » et « . »)."""
    morceaux = [m.strip() for m in re.split(r"[;,.]", texte or "") if m.strip()]
    gardes = [m for m in morceaux if not FOND_CONTINU.search(m)]
    if not gardes:
        return AMBIANCE_DEFAUT
    t = "; ".join(gardes)
    return t[0].upper() + t[1:] + "."

CONSIGNE_DESSIN = (
    "The attached photo shows a place (a film set), described by its owner as: « %s ». A 360° panorama of this place, "
    "seen from the same spot, will be painted around the photo. Answer with JSON only, in English: "
    '{"piece": "<the place in 2 to 4 words, with its article, e.g. the living room>", '
    '"panorama": "<3 to 5 sentences: what surrounds the camera on the left, on the right and BEHIND it, which the '
    'photo does not show; keep to what the description and the photo imply; the room is closed, no other room>", '
    '"ambiance": "' + AMBIANCE_DEMANDE + '"}')

CONSIGNE_CARTES = (
    "These %d images are the views of a slow 360° turn on the spot, %d degrees apart, in order, turning right; the "
    "last one is followed by the first. List the KEY ELEMENTS of the place: each piece of furniture, each opening "
    "(window, glass wall, door, doorway) and each long bare wall. Give the SAME element once, even when several "
    "views show it. Answer with JSON only: a list of at most %d objects "
    '{"nom": "<short id, lowercase>", "description": "<one English sentence describing it so that a video model '
    'redraws it exactly: material, colour, shape, where it stands>", "vues": [{"vue": <view number from 1>, '
    '"x0": <left edge, 0-1000>, "x1": <right edge, 0-1000>}]}. x is measured across the width of each view.')
# un lieu sans photo (PLAN 21.6 étape 6) : la même consigne, d'après le texte seul
CONSIGNE_DESSIN_TEXTE = (
    "A place is described by its owner as: « %s » (it will be built as a film set; name the place itself, not the "
    "set). A 360° panorama of this place will be painted, seen "
    "from one spot inside it. Answer with JSON only, in English: "
    '{"piece": "<the place in 2 to 4 words, with its article, e.g. the great hall>", '
    '"panorama": "<3 to 5 sentences: what surrounds the camera in front, on the left, on the right and behind; keep '
    'to what the description implies>", '
    '"ambiance": "' + AMBIANCE_DEMANDE + '"}')



def _json_de(reponse: str):
    texte = str(reponse or "")
    m = re.search(r"```(?:json)?\s*(.*?)```", texte, re.S)
    if m:
        texte = m.group(1)
    debut = min([i for i in (texte.find("{"), texte.find("[")) if i >= 0], default=-1)
    if debut < 0:
        raise ValueError("Le chat n'a pas rendu de JSON.")
    fin = max(texte.rfind("}"), texte.rfind("]"))
    return json.loads(texte[debut:fin + 1])


def _phrase(x, n=DESCRIPTION_MAX) -> str:
    return " ".join(str(x or "").split())[:n].rstrip(" .")


def lire_consigne(reponse: str) -> dict:
    try:
        d = _json_de(reponse)
    except ValueError as exc:
        raise ValueError("Consigne du panorama illisible : %s" % exc) from exc
    if not isinstance(d, dict) or not _phrase(d.get("panorama")):
        raise ValueError("Consigne du panorama illisible : pas de « panorama ».")
    return {"piece": _phrase(d.get("piece"), 60) or "the room", "panorama": _phrase(d.get("panorama"), 1200),
            "ambiance": ambiance_propre(_phrase(d.get("ambiance"), 200))}


def texte_dessin(consigne: dict) -> str:
    return ("An equirectangular 360 panorama of %s of <image1>, seen from the same spot, following the box layout "
            "exactly. %s." % (consigne["piece"], consigne["panorama"]))


def azimut(cap: float, x: float, fx: float) -> float:
    """L'azimut (degrés, 0 = la photo, positif à droite) d'une colonne x (0-1000) de la vue prise au cap `cap`."""
    return cap + math.degrees(math.atan((x / 1000.0 - 0.5) * VUE_L / fx))


def _ecart(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def lire_cartes(reponse: str, caps: list, fx: float) -> list:
    """Les cartes : {nom, description, a0, a1 (azimuts, a1 >= a0), vue, x0, x1} ; la vue est celle où l'élément est
    le plus au centre (sa découpe)."""
    try:
        liste = _json_de(reponse)
    except ValueError as exc:
        raise ValueError("Cartes illisibles : %s" % exc) from exc
    if isinstance(liste, dict):
        liste = liste.get("elements") or liste.get("cartes") or []
    cartes, noms = [], set()
    for e in liste if isinstance(liste, list) else []:
        if not isinstance(e, dict):
            continue
        description = _phrase(e.get("description"))
        nom = re.sub(r"[^a-z0-9]+", "_", _phrase(e.get("nom"), 40).lower()).strip("_") or "element"
        vues = []
        for v in e.get("vues") or []:
            try:
                k, x0, x1 = int(v["vue"]) - 1, float(v["x0"]), float(v["x1"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= k < len(caps) and 0 <= min(x0, x1) and max(x0, x1) <= 1000 and abs(x1 - x0) >= 5:
                vues.append((k, min(x0, x1), max(x0, x1)))
        if not description or not vues:
            continue
        k, x0, x1 = min(vues, key=lambda v: abs((v[1] + v[2]) / 2 - 500))
        a0, a1 = azimut(caps[k], x0, fx), azimut(caps[k], x1, fx)
        # Les autres vues l'élargissent (un mur long n'est entier dans aucune).
        for j, y0, y1 in vues:
            b0 = a0 + _ecart(azimut(caps[j], y0, fx), a0)
            b1 = a0 + _ecart(azimut(caps[j], y1, fx), a0)
            a0, a1 = min(a0, b0), max(a1, b1)
        while nom in noms:
            nom += "_2"
        noms.add(nom)
        cartes.append({"nom": nom, "description": description, "a0": round(a0, 1), "a1": round(min(a1, a0 + 359), 1),
                       "vue": k, "x0": x0, "x1": x1})
        if len(cartes) >= CARTES_MAX:
            break
    if not cartes:
        raise ValueError("Cartes illisibles : aucun élément avec sa place.")
    return cartes


def visibles(cartes: list, cap: float, demi: float) -> list:
    """Les cartes dont l'étendue croise [cap - demi, cap + demi], dans l'ordre de la gauche vers la droite."""
    vues = []
    for c in cartes:
        a0 = cap + _ecart(c["a0"], cap)
        a1 = a0 + (c["a1"] - c["a0"])
        if a0 <= cap + demi and a1 >= cap - demi:
            vues.append((a0, c))
    return [c for _, c in sorted(vues, key=lambda v: v[0])]




def place(carte: dict, cap: float, demi: float) -> str:
    """Où l'élément tombe dans le cadre du cap `cap`."""
    milieu = max(-demi, min(demi, _ecart((carte["a0"] + carte["a1"]) / 2, cap)))
    return "at the left of the frame" if milieu < -demi / 3 else (
        "at the right of the frame" if milieu > demi / 3 else "in the centre of the frame")


# Les invites d'un tour s'écrivent une fois et se relisent (reprise, route du groupe) : un tour écrit avant un
# correctif gardait l'ancien texte (07/10, château : le geste muet n'arrivait pas, le groupe rejoué était l'octet
# près le clip v3). Écrites par un autre code que celui-ci, elles se réécrivent avant de partir.
SIGNATURE_INVITES = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]

IMAGES_MAX = 9                    # H3 Ref2VA : 9 images au plus par clip (clés comprises)

# Ce qui bouge de soi-même (07/10, propriétaire : « the fire in the castle is fixed ») : nommé tel quel, il reste
# figé (« furniture stay perfectly still », vue exacte épinglée tous les 7,5°). La phrase dit son mouvement ; les
# épingles s'espacent dans son secteur (Tour._zones).
VIVANTS = (
    (re.compile(r"\b(fire|flames?|blazing|burning|embers|candles?|torch(es)?|bonfire|campfire|hearth fire)\b", re.I),
     "its flames flicker and dance, throwing a moving warm glow"),
    (re.compile(r"\b(fountain|waterfall|running water|aquarium|waves|stream|river)\b", re.I),
     "its water ripples and flows"),
)


# Seul ce qui bouge en grand espace ses épingles : une torche ou une bougie dite « flicker » reste épinglée à 7,5°
# (château, 07/10 : les torches du mur espaçaient les épingles sur 150° du tour, et H3 y a inventé une seconde
# Leila assise devant un feu de sol).
GRANDS_VIVANTS = re.compile(r"\b(fireplace|hearth|bonfire|campfire|log fire|brazier|fountain|waterfall|"
                            r"running water|aquarium|waves|stream|river)\b", re.I)
# aucune épingle dans le secteur d'un personnage peint, d'un feu ou d'une eau (7,5° ailleurs) : à 22,5°, Leila et
# le feu du château restaient figés comme des photos (propriétaire, 07/10 : « leila and the fire are frozen as
# images ») ; sans épingle, le latent tient le chemin (Leila assise au fauteuil, 06/10, bougeait)
ECART_VIVANT = 0.0
MARGE_ZONE = 5.0                  # degrés ajoutés au demi-champ autour de ce qui bouge (skill h3-syntaxe)
LARGEUR_PERSONNE = 5.0            # demi-largeur (degrés) du corps d'une personne debout à 2-3 m (0,25 m / 2,5 m)
DEMI_AJOUT_MAX = 30.0             # garde-fou : au-delà, la peinture a changé la pièce (le chat juge en deçà)
ESSAIS_PEINTURE = 3

def sans_nom(texte: str, nom: str) -> str:
    """Le texte d'une fiche sans le prénom du personnage (07/10, propriétaire : « leila shall not be named in the
    prompt sent ») : un prénom n'est pas visible, H3 et l'image le prennent pour un sujet de plus."""
    if not nom:
        return texte
    t = re.sub(r"\b%s\b\s*,?\s*" % re.escape(nom), "", texte or "", flags=re.I).strip(" ,;")
    return t or texte


def _minuscule(texte: str) -> str:
    """« <Subject 3> is a large tapestry », pas « is A large » : l'article de tête d'une description en minuscule."""
    return re.sub(r"^(A|An|The)\b", lambda m: m.group(1).lower(), texte or "")


CONSIGNE_PERSONNAGE = (
    "A person will appear in a slow 360° camera turn filmed in %s. The elements of the place "
    "are listed below as name: description. Choose where the character stands (the name of ONE element, near which "
    "the character is clearly visible, not hidden behind it), what the character quietly does there for the whole "
    "turn: one short phrase, a small continuous gesture with an object held in the hands, done right where the "
    "character stands, without walking and without naming any other element of the place; the gesture makes NO "
    "sound: no liquid, no pouring, no glass, cup, metal, tool or tableware, nothing that clinks, taps or rings "
    "(e.g. \"slowly turning the pages of a book\" or \"winding a ribbon around her fingers\"; choose your own; never "
    "a still pose such as \"warming her hands\"), and the clothing the character wears that fits "
    "this place and its era (garments and colours, top to shoes, a few words in English). Answer with JSON only: "
    '{"pres_de": "<element name>", "action": "<what the character does>", "tenue": "<clothing>"}.\n%s')


# Un geste qui fait du bruit (07/10, château : « pouring wine from a jug into a goblet », exemple recopié par le
# chat) : H3 en fait un ton continu sur tout le clip (saillance 55 dB, −37 dBFS) ; « turning the pages of a book »,
# le reste de l'invite identique : 27 dB, −52 dBFS, le crépitement du feu seul.
GESTE_BRUYANT = re.compile(r"\b(pour\w*|wine|water|liquid|drink\w*|sip\w*|goblet|glass\w*|cups?|mugs?|jugs?|"
                           r"pitchers?|bottles?|kettles?|pots?|plates?|bowls?|cutlery|knife|knives|spoons?|forks?|"
                           r"tools?|hammer\w*|bells?|coins?|keys?|chains?|clink\w*|tap(s|ping)?|knock\w*|ring(s|ing)?)\b", re.I)
GESTE_DEFAUT = "slowly turning the pages of a book held in the hands"
# une pose, pas un geste (07/10 : « warming her hands by the fire », choisi avant la consigne du geste et gardé dans
# l'état du tour, a donné une figure figée)
GESTE_FIGE = re.compile(r"^\s*(warming|resting|sitting|standing|waiting|looking|watching|gazing|leaning|posing|"
                        r"staring|listening)\b", re.I)


def geste_silencieux(action: str) -> str:
    """Le geste du personnage, remplacé par un geste muet et continu s'il nomme un liquide, de la vaisselle ou du
    métal, ou s'il n'est qu'une pose."""
    return GESTE_DEFAUT if not action or GESTE_BRUYANT.search(action) or GESTE_FIGE.search(action) else action


def consigne_personnage(piece: str, cartes: list) -> str:
    """Ni nom ni description de la fiche : « adolescente de 15 ans » + « tenue » faisait refuser la question par le
    filtre du chat (château de Leila, 07/10) ; la tenue se choisit d'après le lieu."""
    elements = "\n".join("%s: %s" % (c["nom"], _phrase(c["description"], 160)) for c in cartes)
    return CONSIGNE_PERSONNAGE % (piece, elements)


def texte_personnage_pano(piece: str, action: str, tenue: str) -> str:
    """La demande à l'image du Studio : le personnage ajouté à la vue du panorama (images jointes après la vue :
    son portrait de face, sa photo en pied dans la tenue), rien d'autre ne change (tour360_pano.coller ne reprend
    que ce qui a changé). L'élément près duquel il se tient n'est PAS décrit : la vue le montre déjà, et décrit, il
    est peint une seconde fois (château, 07/10 : une cheminée ajoutée à côté de l'armoire)."""
    return ("Ajoute à cette photo de %s une seule personne : la personne des photos jointes (visage et coiffure "
            "du portrait, tenue de la photo en pied : %s), %s, devant ce qui est au milieu de l'image. En entier "
            "de la tête aux pieds, à la taille réelle d'une personne à cette distance, éclairée par la lumière de "
            "la pièce, avec son ombre. N'ajoute, n'enlève et ne déplace aucun objet ni meuble : même cadrage, "
            "mêmes murs, mêmes meubles, même lumière, aucun texte ; seule la personne est nouvelle."
            % (piece, tenue, action))


# Le personnage peint par Qwen-Image 2.1 sous un masque (07/10, château : l'image du Studio l'avait mis derrière le
# bout de la table, 2,4 m de haut, l'ourlet flottant devant ; Qwen sous le masque de son volume, à sa place du plan,
# l'a posé debout devant la table à sa taille, le reste de la vue gardé, 55 s sur la carte d'ici).
TAILLE_PERSONNE = 1.8             # m, du sol au haut de la tête (coiffe comprise)
LARGEUR_CORPS = 0.7               # m, carré au sol autour de sa place
MARGE_MASQUE = (25, 20, 30)       # px autour du volume : côtés, haut, bas (l'ombre au sol)


def boite_personne(point: dict, hauteur_camera: float, fx: float, l: int = VUE_L, h: int = VUE_H) -> tuple:
    """(x0, y0, x1, y1) : le rectangle de la vue (cap = celui du personnage, horizontale) qui contient son volume
    debout à sa place du plan (`point` {x, z}, caméra à l'origine, à `hauteur_camera` m du sol), marges comprises.
    Le personnage est au milieu de la vue : seule sa distance compte."""
    d = math.hypot(float(point["x"]), float(point["z"]))
    if d < 0.3:
        raise ValueError("Le personnage est sur la caméra.")
    xs, ys = [], []
    for sx in (-1, 1):
        for sz in (-1, 1):
            # le carré au sol vu de côté : sa profondeur rapproche son bord avant
            p = d + sz * LARGEUR_CORPS / 2
            for y in (hauteur_camera, hauteur_camera - TAILLE_PERSONNE):      # pieds, tête (y vers le bas)
                xs.append(l / 2 + fx * sx * LARGEUR_CORPS / 2 / p)
                ys.append(h / 2 + fx * y / p)
    mc, mh, mb = MARGE_MASQUE
    return (max(0, round(min(xs) - mc)), max(0, round(min(ys) - mh)), min(l, round(max(xs) + mc)),
            min(h, round(max(ys) + mb)))


def texte_personnage_qwen(action: str, tenue: str, n_photos: int) -> str:
    """La consigne de Qwen : <image1> = la vue exacte, <image2>… = les photos du personnage dans sa tenue ; sous le
    masque, le personnage entier à sa taille. Pas de nom, pas de meuble décrit (il serait peint une seconde fois)."""
    photos = ", ".join("<image%d>" % i for i in range(2, 2 + n_photos))
    return ("The person of %s (the same face, the same hair or headwear, the same clothing: %s). In <image1>, this "
            "person stands on the floor in the middle of the picture, in front of what is there, the whole body "
            "visible from the feet to the top of the head, at the real height of an adult at this distance, %s, "
            "lit by the light of the room, with a soft shadow on the floor. Everything else in <image1> stays exactly "
            "as it is: the same furniture, walls, light, camera and framing; only the person is new; a realistic "
            "photograph." % (photos, tenue, geste_silencieux(action)))


CONSIGNE_PEINTURE = (
    "Two photos of the same room from the same viewpoint: the first before, the second after a person was added. "
    "Compare them. Answer with JSON only: "
    '{"personnes": <number of people that appear in the second photo but not in the first>, '
    '"autre": "<any object or piece of furniture added, removed, moved or reshaped, other than the person and her '
    'shadow; empty string if none>"}')


def verdict_peinture(reponse: str):
    """None si la peinture est bonne (une personne ajoutée, rien d'autre), sinon la raison du refus. La largeur seule
    ne dit rien (château, 07/10) : une cheminée inventée faisait 30°, Leila juste avec son ombre sur le mur 38°."""
    try:
        d = _json_de(reponse)
        n, autre = int(d["personnes"]), str(d.get("autre") or "").strip()
    except (ValueError, KeyError, TypeError) as exc:
        return "verdict illisible (%s)" % exc
    if n != 1:
        return "%d personne(s) ajoutée(s) au lieu d'une" % n
    if autre and autre.lower() not in ("none", "nothing", "no", "aucun", "rien"):
        return "la pièce a changé : %s" % _phrase(autre, 200)
    return None


def lire_choix_personnage(reponse: str, cartes: list) -> dict:
    try:
        d = _json_de(reponse)
    except ValueError as exc:
        raise ValueError("Place du personnage illisible : %s" % exc) from exc
    noms = {c["nom"] for c in cartes}
    choix = {k: _phrase((d or {}).get(k), 200) for k in ("pres_de", "action", "tenue")} if isinstance(d, dict) else {}
    if not all(choix.values()) or choix["pres_de"] not in noms:
        raise ValueError("Place du personnage illisible : il faut un élément du lieu, une action et une tenue.")
    choix["action"] = geste_silencieux(choix["action"])
    return choix


def vivant(carte: dict):
    """La phrase du mouvement propre d'une carte (feu, eau) ; None si elle ne bouge pas d'elle-même."""
    if carte.get("personne"):
        return None
    return next((phrase for motif, phrase in VIVANTS if motif.search(carte.get("description") or "")), None)


MOTS_DESCRIPTION = 500           # detailed_description : 350-500 mots (guide ref-en, skill h3-syntaxe)
# fin du groupe nominal d'une description (« A tall narrow window | with small leaded panes ») : virgule,
# préposition, ou participe suivi d'une préposition (« standing torch » reste entier, « standing on » coupe)
_PREPOSITIONS = r"(?:in|into|with|on|of|at|by|from|for|under|above|behind|beside|against|along|across|between|alone)"
# « of » ne coupe pas : « a stretch of bare wall » réduit à « a stretch » ne nomme plus rien (07/10)
_COUPE = _PREPOSITIONS.replace("|of|", "|")
_FIN_NOYAU = re.compile(r"[,:]|\s(?:showing|[a-z]+(?:ing|ed)\s+%s|(?:set|hung|bound)\s+%s|%s)\s"
                        % (_PREPOSITIONS, _PREPOSITIONS, _COUPE))


def _abrege(texte: str, court: bool) -> str:
    """`court` : la description réduite à son groupe nominal (« a large faded medieval tapestry ») ; une carte de
    groupe (« side by side, left to right: A…; B… ») garde tous ses éléments, chacun réduit."""
    if not court:
        return texte

    def noyau(t):
        m = _FIN_NOYAU.search(t, len(" ".join(t.split()[:2])))
        return t[:m.start()].strip() if m else t
    tete, deux, corps = texte.partition("left to right: ")
    if not deux:
        return noyau(texte)
    return tete + deux + "; ".join(noyau(p) for p in corps.split("; "))


_ANGLES = (("trois_quarts", "in three-quarter view"), ("dos", "from the back"), ("", "from the front"))


def _angle(nom: str) -> str:
    return next(a for cle, a in _ANGLES if cle in nom)


def _et(mots: list) -> str:
    return mots[0] if len(mots) == 1 else ", ".join(mots[:-1]) + " and " + mots[-1]


def roles_personne(noms: list, refs: list) -> str:
    """Le rôle de chaque image d'un personnage, d'après son nom (video_h3.VUES_TENUE) : gros plans du visage
    (`…visage…`), photos en pied ; l'angle de chacune."""
    visages = [(n, r) for n, r in zip(noms, refs) if "visage" in n]
    pieds = [(n, r) for n, r in zip(noms, refs) if "visage" not in n]
    parts = []
    if len(visages) == 1 and visages[0][0] == "perso_visage":      # le portrait de la fiche, sans la tenue
        parts.append("the face and hair in %s" % visages[0][1])
    elif visages:
        parts.append("the face, framed by the headwear, in %s, close-ups of the same face %s"
                     % (_et([r for _, r in visages]), _et([_angle(n) for n, _ in visages])))
    if pieds:
        parts.append("the clothing and the whole figure in %s, full-length photos of the same single person %s"
                     % (_et([r for _, r in pieds]), _et([_angle(n) for n, _ in pieds])))
    return "; ".join(parts)


def _essentielles(noms: list) -> list:
    """Les deux images sans lesquelles un personnage n'est plus lui : le premier gros plan du visage et la première
    photo en pied (les vues de face viennent en premier, video_h3.VUES_TENUE)."""
    visages = [n for n in noms if "visage" in n]
    pieds = [n for n in noms if "visage" not in n]
    return visages[:1] + pieds[:1]


def _choisir_sujets(sujets: list, place: int) -> list:
    """Les cartes d'un clip dans ses `place` images (clés déduites), 7 sujets au plus. Le personnage d'abord, puis
    l'élément près duquel il agit (`pres_de`), puis les autres. Le personnage n'y prend que ses deux images
    essentielles tant qu'une carte du clip resterait dehors : nommé sans son image, un élément est inventé (château,
    07/10 : les quatre vues du personnage ont chassé la cheminée du clip, H3 en a fait une seconde et y a mis une
    seconde fois le personnage)."""
    personnes = [c for c in sujets if c.get("personne")]
    pres = {c.get("pres_de") for c in personnes}
    ordre = personnes + [c for c in sujets if not c.get("personne") and c["nom"] in pres] + [
        c for c in sujets if not c.get("personne") and c["nom"] not in pres]

    def remplir(cartes):
        libre, gardes = place, []
        for c in cartes:
            n = len(c.get("images") or [c["nom"]])
            if n <= libre and len(gardes) < 7:
                gardes.append(c)
                libre -= n
        return gardes
    gardes = remplir(ordre)
    if len(gardes) < min(len(ordre), 7):
        reduits = [dict(c, images=_essentielles(c["images"])) if c.get("personne") and len(c.get("images") or []) > 2
                   else c for c in ordre]
        gardes = remplir(reduits)
    return gardes


def _mots_description(texte: str) -> int:
    return len(texte.split("detailed_description:")[1].split("overall_soundscape:")[0].split())


def invite_clip(consigne: dict, cartes: list, a: float, b: float, demi: float, suite: bool = False,
                arret: bool = True, fin_cle: bool = True) -> tuple:
    """L'invite d'un clip (`_invite_clip`), les éléments du départ décrits plus court tant que `detailed_description`
    dépasse 500 mots (château, 07/10 : un clip devant trois groupes de meubles en faisait 658)."""
    texte, images = _invite_clip(consigne, cartes, a, b, demi, suite, arret, fin_cle, False)
    if _mots_description(texte) > MOTS_DESCRIPTION:
        texte, images = _invite_clip(consigne, cartes, a, b, demi, suite, arret, fin_cle, True)
    return texte, images


def _invite_clip(consigne: dict, cartes: list, a: float, b: float, demi: float, suite: bool = False,
                 arret: bool = True, fin_cle: bool = True, court: bool = False) -> tuple:
    """Les six sections Ref2VA (guide officiel h3-prompt-writing, ref-en ; skill h3-syntaxe) d'un clip du cap a au
    cap b ; rend (texte, noms des images dans l'ordre de leurs <Picture N> après les clés). Clip de tête :
    <Picture 1> clé de départ, <Picture 2> clé d'arrivée, puis les images des cartes ; `suite` (départ tenu par le
    latent du clip précédent) : la clé d'arrivée est <Picture 1>, les cartes suivent. Rien n'est nommé qui ne soit
    sur une image (un élément nommé sans sa carte, H3 l'invente : bibliothèque fantôme, 06/10). `arret=False` : la
    caméra passe la clé sans ralentir (sinon la chaîne s'arrête à chaque jointure). `fin_cle=False` : pas de clé
    d'arrivée (elle montrerait vide la place d'un personnage). Une carte peut porter plusieurs images (`images`,
    un personnage : photo de sa tenue et portrait) et `personne` (son action, dans `action`)."""
    piece, sens = consigne["piece"], "right" if b >= a else "left"
    gauche, droite = ("left", "right") if sens == "right" else ("right", "left")
    debut, fin = visibles(cartes, a, demi), visibles(cartes, b, demi)
    sujets = visibles(cartes, (a + b) / 2, demi + abs(b - a) / 2)
    if sens == "left":
        sujets = sujets[::-1]                       # dans l'ordre où la caméra les rencontre
    porte, vivants_portes = set(), []
    if suite:
        # tout ce qui est déjà dans le cadre au début d'un clip enchaîné : le latent du clip précédent le porte ; ni
        # nommé, ni étiqueté, ni en références. Redit avec sa carte, H3 en ajoute un second à côté de celui qu'il
        # voit : une seconde Leila (château, 07/10, clips 2 et 3), puis une seconde cheminée (même tour, clip 2).
        # Ce qui n'apparaît que dans ce clip garde ses images ; ce qui vit (feu) garde son mouvement, sans étiquette.
        porte = {c["nom"] for c in debut}
        vivants_portes = list(dict.fromkeys(vivant(c) for c in debut if vivant(c) and not c.get("personne")))
        sujets = [c for c in sujets if c["nom"] not in porte]
        debut = []
    p0, p1 = ("<Picture 1>", "<Picture 2>" if fin_cle else None) if not suite else (
        None, "<Picture 1>" if fin_cle else None)
    sujets = _choisir_sujets(sujets, IMAGES_MAX - (p0 is not None) - (p1 is not None))
    s = {c["nom"]: "<Subject %d>" % (i + 2) for i, c in enumerate(sujets)}
    noms = [c["nom"] for c in sujets]
    dans_debut, dans_fin = {c["nom"] for c in debut}, {c["nom"] for c in fin}
    part = abs(b - a) / (2 * demi)                  # amplitude = part du cadre qui change (base-en 4.3)
    mouvement = "pans %s" % sens + (" with small amplitude" if part < 0.25 else
                                    " with large amplitude" if part > 0.6 else "") + " at slow speed"
    image = 1 + (p0 is not None) + (p1 is not None)
    images = []                                     # noms des images après les clés, dans l'ordre des <Picture N>
    defs = ([] if suite else ["%s is the first frame of [Shot 1], the view of %s before the camera turns."
                              % (p0, piece)])
    if p1:
        defs.append("%s is the last frame of [Shot 1], the view of %s after the camera has turned about %d degrees "
                    "to the %s." % (p1, piece, round(abs(b - a)), sens))
    vu = " and ".join(p for p in (p0, p1) if p)
    defs.append("<Subject 1> is %s%s, with its walls, floor, ceiling and light."
                % (piece, " seen in %s" % vu if vu else " as the camera turns through it"))
    for c in sujets:
        noms_img = c.get("images") or [c["nom"]]
        refs = ["<Picture %d>" % (image + k) for k in range(len(noms_img))]
        image += len(noms_img)
        images += noms_img
        if c.get("personne") and len(refs) > 1:
            # ce que chaque image apporte (guide ref-en : sources mêlées, dire le rôle de chacune ; 07/10)
            defs.append("%s is %s: %s." % (s[c["nom"]], _minuscule(c["description"].rstrip(".")),
                                           roles_personne(noms_img, refs)))
        else:
            defs.append("%s is %s in %s." % (s[c["nom"]], _minuscule(c["description"].rstrip(".")),
                                              " and ".join(refs)))
    passe = ", ".join(s[n] for n in noms)
    vers = (" to %s" % p1) if p1 else ""
    depart = ("from %s%s" % (p0, vers)) if p0 else ("continuing the pan of the previous shot without a cut%s" % vers)
    taches = (["video continuation"] if suite else []) + (["keyframe completion"] if p0 or p1 else []) + [
        "reference generation"]
    resume = ("[%s] A single continuous shot in which the camera %s through <Subject 1>, %s"
              % (" + ".join(taches), mouvement, depart)
              + (", passing %s." % passe if passe else
                 ", past what is already in view." if porte else ", along its plain walls."))
    garde = ([] if suite else ["%s ([Shot 1] first frame): fully_preserved - the shot starts exactly on this frame."
                               % p0])
    if p1:
        garde.append("%s ([Shot 1] last frame): fully_preserved - the shot ends exactly on this frame." % p1)
    garde.append("<Subject 1> (appears in [Shot 1]): fully_preserved - the same walls, floor, ceiling and light "
                  "throughout.")

    def carte(n):
        return next(c for c in sujets if c["nom"] == n)
    garde += [("%s (appears in [Shot 1]): fully_preserved - the same face, hair and clothing throughout." if
               carte(n).get("personne") else
               "%s (appears in [Shot 1]): fully_preserved - the same shape, colour and material throughout.") % s[n]
              for n in noms]

    def qui(n):                     # la première mention : le personnage par ce qu'il fait, la carte par elle-même
        c = carte(n)
        d = _minuscule(c["description"].rstrip("."))
        return "%s, %s, %s" % (s[n], d, geste_silencieux(c["action"])) if c.get("personne") else \
            "%s, %s, stands" % (s[n], _abrege(d, court))
    au_depart = ["%s %s" % (qui(n), place(carte(n), a, demi)) for n in noms if n in dans_debut]
    ouverture = ("[Shot 1] The shot begins from %s: at eye level, the camera stands in <Subject 1>." % p0 if p0 else
                 "[Shot 1] The shot continues the previous shot without a cut, opening on the exact framing where "
                 "it ended: at eye level, the camera stands in <Subject 1>.")
    phrases = [ouverture + (" " + "; ".join(au_depart) + "." if au_depart else
                            "" if porte else " A stretch of plain wall fills the frame.")]
    # ce qui vit et que le latent porte : son mouvement, sans le renommer
    for phrase in vivants_portes:
        phrases.append("Wherever they are already in view, %s, all through the shot." % phrase.replace("its ", "the ", 1))
    # ce qui bouge se dit tout de suite après l'ouverture, avant les meubles qui « restent immobiles » (07/10 : dit
    # en dernier, après huit éléments immobiles, le personnage et le feu sont restés figés)
    bougent = [(n, vivant(carte(n))) for n in noms if vivant(carte(n))]
    gens = [n for n in noms if carte(n).get("personne")]
    # le geste dit en petits mouvements continus, jamais une pose (07/10 : « warming her hands » seul, dit deux
    # fois « staying in the same place », a donné une figure figée ; l'essai du fauteuil, qui bougeait, disait
    # « keeps reading calmly, … runs a finger along a line of text »)
    for n in gens:
        phrases.append("Throughout the shot %s keeps moving, %s: the hands, head and shoulders move gently and "
                       "continuously, the gaze shifts, the folds of the clothing stir, the lips stay closed; never a "
                       "frozen pose. The same face, hair and clothing; there is only one %s in the room."
                       % (s[n], geste_silencieux(carte(n)["action"]), s[n]))
    # une phrase par mouvement, pas par élément (sept torches faisaient sept fois la même phrase)
    for phrase in dict.fromkeys(p for _, p in bougent):
        qui_bouge = [s[n] for n, p in bougent if p == phrase]
        phrases.append("In %s, %s, all through the shot." % (
            ", ".join(qui_bouge[:-1]) + " and " + qui_bouge[-1] if len(qui_bouge) > 1 else qui_bouge[0],
            phrase.replace("its ", "the ", 1)))
    revele =[s[n] for n in noms if n not in dans_debut]
    phrases.append("The camera %s, revealing %s." % (mouvement, ", ".join(revele) if revele else
                                                     "more of the plain walls of <Subject 1>"))
    # Seule la caméra bouge : un élément « entre » parce que le cadre tourne vers lui. Dit d'une personne,
    # « enters … comes into full view » la faisait entrer en marchant, une seconde fois (château, 07/10).
    for n in noms:
        reste = ("staying in the same place, %s" % geste_silencieux(carte(n)["action"]) if carte(n).get("personne") else
                 "keeping its shape, colour and place in the room")
        if n in dans_debut and n not in dans_fin:
            phrases.append("As the camera turns, %s drifts toward the %s edge and slides out of the frame."
                           % (s[n], gauche))
        elif n in dans_debut:
            phrases.append("%s drifts from %s to %s across the frame, %s." % (s[n], droite, gauche, reste))
        elif n in dans_fin:
            phrases.append("As the camera turns, %s comes into view at the %s edge of the frame, already in place%s."
                           % (s[n], droite, ", " + geste_silencieux(carte(n)["action"]) if carte(n).get("personne") else ""))
        else:
            phrases.append("As the camera turns, %s comes into view at the %s edge, drifts across the frame and "
                           "slides out on the %s, %s." % (s[n], droite, gauche, reste))
    phrases.append("The floor and the base of the walls run as one continuous line across the frame while the view "
                   "turns, and the light stays soft and even.")
    # « is at », jamais « sits at » : dit d'une personne, H3 la faisait s'asseoir (château, 07/10)
    arrivee = ["%s is %s" % (s[n], place(carte(n), b, demi)) for n in noms if n in dans_fin]
    if p1:
        phrases.append(("The pan slows and settles, and the shot ends on %s" % p1 if arret else
                        "Keeping its steady speed, the pan reaches the end of the shot, and the shot ends on %s" % p1)
                       + " with its framing, spacing and composition"
                       + (", where " + ", ".join(arrivee) + "." if arrivee else ", a stretch of plain wall."))
    else:
        phrases.append("Keeping its steady speed, the pan reaches the end of the shot"
                       + (", where " + ", ".join(arrivee) + "." if arrivee else "."))
    quoi = sorted({"the flames" if "flames" in p else "the water" for p in [p for _, p in bougent] + vivants_portes}) + (
        ["the people"] if gens or any(c.get("personne") and c["nom"] in porte for c in cartes) else [])
    phrases.append("The whole shot is one continuous take; the walls, openings and furniture stay perfectly still"
                   + (", while %s keep moving." % " and ".join(quoi) if quoi else "."))
    style = ("The target video is a live-action, cinematic interior shot of %s, with a calm atmosphere. %s"
             % (piece, "Apart from the camera, only %s move." % " and ".join(quoi) if quoi else
                "Only the camera moves."))
    texte = "\n".join(["subject_definitions:", *defs, "", "summary:", resume, "", "retention_analysis:", *garde, "",
                       "detailed_description:", style, " ".join(phrases), "",
                       "overall_soundscape:", ambiance_propre(consigne.get("ambiance")), "",
                       "non_diegetic_music:", "N/A", ""])
    return texte, images


def decouper_ffmpeg(png: bytes, x0: int, x1: int) -> bytes:
    """La bande [x0, x1[ (pixels) d'une image clé, en PNG."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "png_pipe", "-i", "pipe:0", "-vf",
                        "crop=%d:ih:%d:0" % (max(2, x1 - x0), x0), "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                       input=png, capture_output=True, timeout=60)
    if r.returncode or not r.stdout:
        raise ValueError("Découpe impossible : %s" % r.stderr.decode(errors="replace")[-200:])
    return r.stdout


def _data_url(image: bytes) -> str:
    genre = "jpeg" if image[:3] == b"\xff\xd8\xff" else "webp" if image[:4] == b"RIFF" else "png"
    return "data:image/%s;base64,%s" % (genre, base64.b64encode(image).decode())


# --- Le tour, étape par étape -------------------------------------------------------------------------------------

class Arret(Exception):
    """Une étape impossible : le tour s'arrête là, et l'état dit pourquoi."""


class Attente(Exception):
    """Le plan attend le client (« rien ne part en calcul payant avant valider ») : le fil s'arrête, sans erreur."""


A_VALIDER = "plan_a_valider"


class Tour:
    """`appel(methode, chemin, corps)` -> (code, json) : les routes du Studio ; `chat(consigne, images)` -> texte ;
    `panorama(photo, texte, graine, pas, **plan)` -> {nom: octets} (geometrie.json, pano.png, cle_NNN.png,
    carte_<nom>.png…), Arret sinon ; `mesure(photo)` -> {geometrie.json, grille.json} (PLAN 21.6 étape 1 ; sans
    elle, le tour d'avant le plan : cartes nommées par le chat sur les images clés) ; `decouper(png, x0, x1)` -> png."""

    ETAPES = ("consigne", "mesure", "plan", "panorama", "cartes", "personnage", "troncons", "montage", "finition")

    def __init__(self, etat: dict, dossier: Path, appel: Callable, chat: Callable, panorama: Callable,
                 decouper: Callable = decouper_ffmpeg, dormir: Callable = time.sleep, mesure: Callable = None,
                 relecteur: Callable = None, personne: Callable = None, peindre: Callable = None):
        self.etat, self.dossier, self.appel, self.chat = etat, Path(dossier), appel, chat
        self.panorama, self.decouper, self.dormir, self.mesure_ = panorama, decouper, dormir, mesure
        # `personne(fiche, tenue)` -> {"nom", "description", "tenue": png, "visage": png} : la fiche du personnage
        # et la photo de sa tenue (faite par l'image du Studio si elle n'existe pas encore)
        self.personne_ = personne
        # `peindre(pano, cap, fx, texte, images)` -> (pano png, {cap, demi}) : le personnage ajouté par l'image du
        # Studio à la vue de ce cap, et seul ce qui a changé recollé dans le panorama (tour360_pano.coller)
        self.peindre = peindre
        # le relecteur du plan : un modèle plus fort que celui qui propose (propriétaire, 06/10), même forme que chat
        self.relecteur = relecteur or chat

    def ecrire(self):
        chemin = self.dossier / "tour.json"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        provisoire = chemin.with_suffix(".tmp")
        provisoire.write_text(json.dumps(self.etat, ensure_ascii=False, indent=1), encoding="utf-8")
        provisoire.replace(chemin)

    def noter(self, etape: str, **quoi):
        self.etat["etape"] = etape
        self.etat["journal"].append(dict({"le": round(time.time()), "etape": etape}, **quoi))
        self.ecrire()

    def route(self, methode: str, chemin: str, corps=None) -> dict:
        code, rendu = self.appel(methode, chemin, corps)
        if code != 200:
            detail = rendu.get("detail") if isinstance(rendu, dict) else rendu
            raise Arret("%s %s : %s %s" % (methode, chemin, code, str(detail)[:600]))
        return rendu

    def reussi(self, jid: str, quoi: str) -> dict:
        debut = time.time()
        while True:
            job = self.route("GET", "/jobs/" + jid)
            if job.get("status") not in ("queued", "running"):
                break
            if time.time() - debut > ATTENTE_MAX_S:
                raise Arret("%s : le travail %s n'a pas fini en %d s." % (quoi, jid, ATTENTE_MAX_S))
            self.dormir(ATTENTE_PAS_S)
        if job.get("status") != "succeeded":
            raise Arret("%s a échoué : %s" % (quoi, str(job.get("error") or job.get("status"))[:600]))
        return job

    def _photo(self) -> bytes:
        return (self.dossier / "photo.png").read_bytes()

    def _cle(self, cap: int) -> bytes:
        return (self.dossier / "cles" / ("cle_%03d.png" % (cap % 360))).read_bytes()

    def _caps(self) -> list:
        return list(range(0, 360, self.etat["pas"]))

    # --- les étapes ---
    def consigne(self):
        try:
            if self.etat.get("texte"):
                c = lire_consigne(self.chat(CONSIGNE_DESSIN_TEXTE % _phrase(
                    self.etat["description"] or self.etat["nom"], 1400), []))
            else:
                c = lire_consigne(self.chat(CONSIGNE_DESSIN % _phrase(self.etat["description"], 1400),
                                            [_data_url(self._photo())]))
        except ValueError as exc:
            raise Arret(str(exc)) from exc
        self.etat["consigne"] = c
        self.noter("consigne", piece=c["piece"])

    def mesure(self):
        """PLAN 21.6 étape 1 : MoGe mesure la pièce (ici ou chez Modal) avant que le chat n'en propose le plan."""
        if self.etat.get("texte"):        # sans photo, le repère vient du plan (étape « plan »)
            return
        fichiers = self.mesure_(self._photo())
        if "geometrie.json" not in fichiers or "grille.json" not in fichiers:
            raise Arret("La mesure de la pièce n'a pas rendu geometrie.json et grille.json.")
        (self.dossier / "grille.json").write_bytes(fichiers["grille.json"])
        self.etat["mesure"] = json.loads(fichiers["geometrie.json"])
        self.noter("mesure", piece=self.etat["mesure"]["piece"], retraits=self.etat["mesure"].get("retraits"))

    def plan(self):
        """Le chat propose le plan au sol ; le tour attend que le client le valide (route « plan/valider »)."""
        if not self.etat.get("plan") and self.etat.get("texte"):
            # sans photo (étape 6) : le chat imagine le plan en mètres, son repère vient avec
            try:
                plan, geo, remarques = plan_piece.lire_texte(self.chat(
                    plan_piece.consigne_plan_texte(self.etat["description"] or self.etat["nom"]), []))
            except ValueError as exc:
                raise Arret(str(exc)) from exc
            self.etat.update(plan=plan, mesure=geo, plan_remarques=remarques, plan_historique=[])
            self.noter("plan_propose", elements=len(plan["elements"]), dehors=bool(plan.get("dehors")))
            self.etat["plan_relecture"] = relire_plan(self.etat, self.relecteur, None)
            self.noter("plan_relu", corrige=self.etat["plan_relecture"]["corrige"],
                       problemes=len(self.etat["plan_relecture"]["problemes"]))
        if not self.etat.get("plan"):
            geo = self.etat["mesure"]
            grille = json.loads((self.dossier / "grille.json").read_text(encoding="utf-8"))
            try:
                plan, remarques = plan_piece.lire_proposition(self.chat(
                    plan_piece.consigne_plan(self.etat["description"] or self.etat["nom"], geo),
                    [_data_url(self._photo())]), geo, grille)
            except ValueError as exc:
                raise Arret(str(exc)) from exc
            self.etat.update(plan=plan, plan_remarques=remarques, plan_historique=[])
            self.noter("plan_propose", elements=len(plan["elements"]))
            self.etat["plan_relecture"] = relire_plan(self.etat, self.relecteur, self._photo())
            self.noter("plan_relu", corrige=self.etat["plan_relecture"]["corrige"],
                       problemes=len(self.etat["plan_relecture"]["problemes"]))
        self._personnage_au_plan()
        if not self.etat.get("plan_valide"):
            raise Attente()

    def panorama_(self):
        plan = self.etat.get("plan") if self.etat.get("plan_valide") else None
        extra = {}
        texte = texte_dessin(self.etat["consigne"])
        if plan:
            geo = self.etat["mesure"]
            extra = {"geo": geo, "scene": plan_piece.scene_du_plan(plan, geo),
                     "cartes": [{k: c[k] for k in ("nom", "a0", "a1", "haut", "bas")}
                                for c in plan_piece.cartes_du_plan(plan, geo)]}
            texte = plan_piece.texte_panorama(self.etat["consigne"]["piece"], plan, geo,
                                              photo=not self.etat.get("texte"))
        elif self.etat.get("texte"):
            raise Arret("Un lieu sans photo se peint d'après son plan validé.")
        photo = None if self.etat.get("texte") else self._photo()
        fichiers = self.panorama(photo, texte, self.etat["graine"], self.etat["pas"], **extra)
        manque = [n for n in ["geometrie.json", "pano.png"] + ["cle_%03d.png" % c for c in self._caps()]
                  + ["carte_%s.png" % c["nom"] for c in extra.get("cartes", [])] if n not in fichiers]
        if manque:
            raise Arret("Le panorama n'a pas rendu : %s." % ", ".join(manque))
        (self.dossier / "cles").mkdir(parents=True, exist_ok=True)
        for nom, octets in fichiers.items():
            if re.fullmatch(r"cle_\d{3}\.png", nom):
                (self.dossier / "cles" / nom).write_bytes(octets)
            elif re.fullmatch(r"carte_[a-z0-9_]+\.png", nom):
                (self.dossier / "cartes").mkdir(parents=True, exist_ok=True)
                (self.dossier / "cartes" / nom[len("carte_"):]).write_bytes(octets)
            elif nom in ("pano.png", "maquette.png", "geometrie.json", "temps.json"):
                (self.dossier / nom).write_bytes(octets)
        geo = json.loads(fichiers["geometrie.json"])
        self.etat["geometrie"] = {k: geo.get(k) for k in ("hauteur", "plafond", "piece", "lacet", "tangage", "fx",
                                                          "fx_vue")}
        try:
            self.etat["temps_panorama"] = json.loads(fichiers.get("temps.json") or "{}")
        except ValueError:
            pass
        self.noter("panorama", geometrie=self.etat["geometrie"])

    def cartes(self):
        if self.etat.get("plan") and self.etat.get("plan_valide"):
            # PLAN 21.6 étape 3 : azimuts et découpes calculés depuis la maquette ; le chat n'a écrit que les
            # descriptions, dans le plan
            cartes = [dict(c, vue=0, x0=0, x1=0) for c in plan_piece.cartes_du_plan(self.etat["plan"],
                                                                                     self.etat["mesure"])]
            self.etat["cartes"] = cartes
            self.noter("cartes", nombre=len(cartes), depuis="plan")
            return
        caps, fx = self._caps(), float(self.etat["geometrie"]["fx_vue"])
        try:
            cartes = lire_cartes(self.chat(CONSIGNE_CARTES % (len(caps), self.etat["pas"], CARTES_MAX),
                                           [_data_url(self._cle(c)) for c in caps]), caps, fx)
        except ValueError as exc:
            raise Arret(str(exc)) from exc
        dossier = self.dossier / "cartes"
        dossier.mkdir(parents=True, exist_ok=True)
        for c in cartes:
            x0, x1 = round(c["x0"] / 1000 * VUE_L), round(c["x1"] / 1000 * VUE_L)
            try:
                (dossier / (c["nom"] + ".png")).write_bytes(self.decouper(self._cle(caps[c["vue"]]), x0, x1))
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                self.noter("carte_sans_image", nom=c["nom"], erreur=str(exc)[:200])
        self.etat["cartes"] = cartes
        self.noter("cartes", nombre=len(cartes))

    def _choisir_personnage(self, elements: list):
        """Le chat choisit près de quel élément (`elements` : [{nom, description}]) le personnage se tient, ce qu'il
        y fait et la tenue du lieu, pour ce que le client n'a pas fixé."""
        p = self.etat["personnage"]
        if p.get("pres_de") and p.get("action") and p.get("tenue"):
            return
        try:
            choix = lire_choix_personnage(self.chat(consigne_personnage(
                self.etat["consigne"]["piece"], elements), []), elements)
        except ValueError as exc:
            raise Arret(str(exc)) from exc
        p.update({k: p.get(k) or choix[k] for k in ("pres_de", "action", "tenue")})

    def _personnage_au_plan(self):
        """Le personnage sur le plan au sol (07/10, propriétaire : « the 2d layout shall include Leila ») : sa place
        se voit et se valide avec le plan, devant l'élément choisi, du côté de la caméra."""
        plan = self.etat.get("plan")
        if not (self.etat.get("personnage") and plan) or plan.get("personnage") or self.personne_ is None:
            return
        self._choisir_personnage(plan["elements"])
        point = plan_piece.place_personnage(plan, self.etat["personnage"]["pres_de"])
        if point:
            plan["personnage"] = dict(point, nom=self.personne_(self.etat["personnage"]["fiche"], None)["nom"])
            self.noter("personnage_au_plan", **plan["personnage"])

    def personnage(self):
        """Un personnage dans le tour (07/10, propriétaire : « add Leila in all the scene with the appropriate
        dressing », puis « the 360° shall be done continuously as before ; the 2d layout shall include Leila ») : sa
        place vient du plan au sol (sinon de l'élément que le chat choisit) ; ses images viennent de sa fiche
        (portrait de face, photos en pied dans la tenue du lieu : face, trois-quarts, dos) ; il est PEINT dans le
        panorama (image du Studio), si bien que les épingles du tour le montrent et que le tour reste épinglé
        partout ; il devient une carte à plusieurs images, ses épingles espacées comme celles d'un feu."""
        p = self.etat.get("personnage")
        if not p:
            return
        if self.personne_ is None or self.peindre is None:
            raise Arret("Ce Studio ne sait pas encore placer un personnage dans un tour.")
        cartes = [c for c in self.etat["cartes"] if not c.get("personne")]
        self._choisir_personnage(cartes)
        fiche = self.personne_(p["fiche"], None)
        plan = self.etat.get("plan") if self.etat.get("plan_valide") else None
        point = (plan or {}).get("personnage")
        pres = next((e for e in (plan or {}).get("elements") or [] if e["nom"] == p["pres_de"]), None) or next(
            (c for c in cartes if c["nom"] == p["pres_de"]), None)
        if point:
            vise = math.degrees(math.atan2(point["x"], point["z"])) - float(self.etat["mesure"]["lacet"])
        elif pres is not None and "a0" in pres:
            vise = (pres["a0"] + pres["a1"]) / 2
        else:
            raise Arret("Le personnage se tient près de « %s », qui n'est pas un élément du lieu." % p["pres_de"])
        vise = round((vise + 180) % 360 - 180, 1)
        images = self.personne_(p["fiche"], p["tenue"])
        dossier = self.dossier / "cartes"
        dossier.mkdir(parents=True, exist_ok=True)
        # recette du 07/10 : des vues SÉPARÉES dans la tenue, chacune à pleine définition (pas de planche : réduite
        # d'un bloc, elle dédouble) — deux gros plans du visage coiffe comprise, deux photos en pied cadrées en
        # hauteur (video_h3.VUES_TENUE) ; sans elles, le portrait de la fiche et la photo de la tenue
        vues = images.get("vues") or {}
        refs = ({"perso_" + v: b for v, b in vues.items()} if vues else
                {"perso_visage": images["visage"], "perso_tenue": images["tenue"]})
        for nom, octets in refs.items():
            (dossier / (nom + ".png")).write_bytes(octets)
        vierge = self.dossier / "pano_sans_personnage.png"
        if not vierge.is_file():
            vierge.write_bytes((self.dossier / "pano.png").read_bytes())
        fx = float(self.etat["geometrie"]["fx_vue"])
        hc = (self.etat.get("geometrie") or {}).get("hauteur") or (self.etat.get("mesure") or {}).get("hauteur")
        if point and hc:
            # à sa place du plan : Qwen sous le masque de son volume, avec ses vues dans la tenue (visage de face et
            # de trois-quarts, en pied de trois-quarts)
            boite = boite_personne(point, float(hc), fx)
            photos = [b for b in (vues.get("visage_face") or images["visage"], vues.get("visage_trois_quarts"),
                                  vues.get("pied_trois_quarts") or vues.get("pied_face") or images["tenue"]) if b]
            texte = texte_personnage_qwen(p["action"], p["tenue"], len(photos))
        else:
            boite, photos = None, [vues.get("visage_face") or images["visage"], vues.get("pied_face") or images["tenue"]]
            texte = texte_personnage_pano(self.etat["consigne"]["piece"], p["action"], p["tenue"])
        # la vue avant / après jugée par le chat (château, 07/10 : une cheminée inventée) ; d'autres essais, puis
        # l'arrêt, jamais un panorama faux
        raison = ""
        for essai in range(ESSAIS_PEINTURE):
            try:
                pano, ajout = self.peindre(vierge.read_bytes(), vise, fx, texte, photos,
                                           **({"boite": boite, "graine": GRAINE + essai} if boite else {}))
            except ValueError as exc:
                raison = str(exc)
                continue
            if float(ajout["demi"]) > DEMI_AJOUT_MAX:
                raison = "l'image a changé %.0f° de la pièce" % (2 * float(ajout["demi"]))
            else:
                raison = verdict_peinture(self.chat(CONSIGNE_PEINTURE,
                                                    [_data_url(ajout["avant"]), _data_url(ajout["apres"])]))
                if raison is None:
                    break
            # gardé pour qu'on voie ce que l'image a changé
            (self.dossier / ("pano_refuse_%d.png" % (essai + 1))).write_bytes(pano)
            self.noter("peinture_refusee", demi=ajout["demi"], cap=ajout["cap"], raison=raison)
        else:
            raise Arret("%s n'a pas pu être peinte dans le panorama : %s" % (fiche["nom"], raison))
        (self.dossier / "pano.png").write_bytes(pano)
        # la carte = le corps, pas la bande changée : l'ombre portée l'élargissait jusqu'à 36°, et l'invite la disait
        # dans le cadre quand son corps n'y était pas (château, 07/10 : une seconde Leila est entrée). Le corps est
        # là où l'on a demandé de la peindre (milieu de la vue), ramené dans la bande changée.
        bande, demi_bande = float(ajout["cap"]), float(ajout["demi"])
        cap, demi = bande + max(-demi_bande, min(demi_bande, _ecart(vise, bande))), LARGEUR_PERSONNE
        self.etat["cartes"] = cartes + [{
            "nom": "perso", "personne": True, "dans_pano": True, "images": list(refs),
            "pres_de": pres["nom"] if pres is not None else None,
            "description": "%s, wearing %s" % (sans_nom(_phrase(fiche["description"], 160), fiche["nom"]),
                                               p["tenue"]),
            "action": p["action"], "a0": round(cap - demi, 1), "a1": round(cap + demi, 1)}]
        camera = self.etat.get("reglages_camera") or {}
        if camera.get("camera", "tour_droite") in ("tour_droite", "tour_gauche"):
            # un tour complet part où l'on veut : ses deux clés de groupe à 90° du personnage, hors de son secteur
            self.etat["reglages_camera"] = dict(lire_camera_etat(self.etat),
                                                cap_depart=round((cap - 90 + 180) % 360 - 180, 1))
        self.noter("personnage", pres_de=p["pres_de"], tenue=p["tenue"], action=p["action"], cap=round(cap, 1),
                   cap_vise=vise, demi=round(demi, 1), au_plan=bool(point))

    def _zones(self, demi: float) -> list:
        """Les secteurs (caps de la caméra) où une vue exacte épinglée figerait ce qui bouge : un personnage peint
        dans le panorama, un feu ou de l'eau (épingles espacées) ; un personnage absent du panorama (aucune épingle :
        la vue exacte montre sa place vide)."""
        zones = []
        ecart = float(self.etat.get("ecart_vivant") or ECART_VIVANT)    # None : la place vide, aucune clé
        for c in self.etat["cartes"]:
            if c.get("personne"):
                zones.append((c["a0"] - demi - MARGE_ZONE, c["a1"] + demi + MARGE_ZONE,
                              ecart if c.get("dans_pano") else None))
            elif vivant(c) and GRANDS_VIVANTS.search(c.get("description") or ""):
                zones.append((c["a0"] - demi - MARGE_ZONE, c["a1"] + demi + MARGE_ZONE, ecart))
        return zones

    def _groupes(self) -> list:
        """Les groupes du chemin de la caméra, avec l'invite et les cartes de chaque clip ; écrits une fois, la
        reprise et la route du groupe les relisent."""
        if not self.etat.get("groupes") or self.etat.get("invites_de") != SIGNATURE_INVITES:
            demi = math.degrees(math.atan(VUE_L / 2 / float(self.etat["geometrie"]["fx_vue"])))
            # un personnage peint avant le 07/10 n'a pas `pres_de` sur sa carte : le journal le garde
            pres_note = next((j.get("pres_de") for j in reversed(self.etat.get("journal") or [])
                         if j.get("etape") == "personnage"), None)
            for c in self.etat["cartes"]:
                if c.get("personne") and not c.get("pres_de") and pres_note:
                    c["pres_de"] = pres_note
            # une carte sans image ne se nomme pas : nommée sans image, H3 l'invente
            cartes = [c for c in self.etat["cartes"]
                      if all((self.dossier / "cartes" / (n + ".png")).is_file() for n in c.get("images") or [c["nom"]])]
            zones = self._zones(demi)
            # ni clé de groupe ni clé de fin de clip sur la place d'un personnage : vide, elle l'efface ; peinte,
            # elle le fige (le skill h3-syntaxe : « garder l'épingle finale hors de ce secteur »)
            vides = [(c["a0"] - demi - MARGE_ZONE, c["a1"] + demi + MARGE_ZONE, None)
                     for c in self.etat["cartes"] if c.get("personne")]
            groupes = []
            chemin = chaine.chemin(lire_camera_etat(self.etat))
            if any(chaine.dans(chemin[0][0]["a"], a0, a1) for a0, a1, _ in vides):
                raise Arret("Le tour part d'une vue où le personnage se tient : choisissez un autre départ.")
            if any(chaine.dans(chemin[-1][-1]["b"], a0, a1) for a0, a1, _ in vides):
                raise Arret("Le tour finit sur la place du personnage : choisissez un autre départ.")
            for clips in couper_sur_personnage(chemin, vides):
                for c in clips:
                    c["fin"] = not any(chaine.dans(c["b"], a0, a1) for a0, a1, _ in vides)
                faits = [invite_clip(self.etat["consigne"], cartes, c["a"], c["b"], demi, suite=i > 0,
                                     arret=c["arret"], fin_cle=c["fin"]) for i, c in enumerate(clips)]
                groupes.append({"clips": clips, "invites": [t for t, _ in faits], "sujets": [n for _, n in faits]})
            # un chemin découpé autrement : les rendus des anciens groupes ne correspondent plus
            if [g["clips"] for g in self.etat.get("groupes") or []] != [g["clips"] for g in groupes]:
                self.etat["troncons"] = []
            self.etat["groupes"] = groupes
            self.etat["zones"] = zones
            self.etat["invites_de"] = SIGNATURE_INVITES
            self.ecrire()
        return self.etat["groupes"]

    def troncons(self):
        # un groupe à refaire seul est vidé (None) : les autres gardent leur rendu (chaque groupe part de sa clé
        # exacte, rien ne passe d'un groupe à l'autre)
        groupes = self._groupes()      # d'abord : un chemin redécoupé remplace la liste des rendus
        faits = self.etat.setdefault("troncons", [])
        for k in range(len(groupes)):
            if k < len(faits) and faits[k]:
                continue
            lance = self.etat.get("groupe_lance") or {}
            if lance.get("groupe") != k:       # lancé une seule fois : une reprise attend le même travail
                job = self.route("POST", "/video-h3/fiches/%s/tour360/%s/groupe/%d"
                                 % (self.etat["fiche"], self.etat["id"], k), {})
                lance = self.etat["groupe_lance"] = {"groupe": k, "job": job["id"]}
                self.noter("troncon_lance", groupe=k + 1, job=job["id"], clips=len(groupes[k]["clips"]))
            try:
                self.reussi(lance["job"], "Le groupe %d" % (k + 1))
            except Arret:
                self.etat.pop("groupe_lance", None)    # échoué : la reprise le relance
                raise
            if k < len(faits):
                faits[k] = lance["job"]
            else:
                faits.append(lance["job"])
            self.etat.pop("groupe_lance", None)
            self.noter("troncon", groupe=k + 1, job=lance["job"])

    def montage(self):
        n = len(self.etat["troncons"])
        film = self.route("POST", "/video-h3/montage", {"clips": self.etat["troncons"],
                                                        "scenario": "Tour 360° : " + self.etat["nom"],
                                                        "lieux": ["tour"] * n})
        self.reussi(film["id"], "Le montage")
        self.etat["film"] = film["id"]
        self.noter("montage", job=film["id"])

    def _travail(self, cle: str, quoi: str, lancer: Callable) -> str:
        """Un morceau de la finition : lancé une seule fois (son numéro gardé dans l'état), attendu, rendu."""
        f = self.etat.setdefault("finition", {})
        if not f.get(cle):
            f[cle] = lancer()["id"]
            self.noter("finition_lancee", morceau=cle, job=f[cle])
        self.reussi(f[cle], quoi)
        return f[cle]

    def finition(self):
        reglages = dict(FINITION_DEFAUT, **(self.etat.get("reglages_finition") or {}))
        f = self.etat.setdefault("finition", {})
        base = film = self.etat["film"]
        if reglages["4k"]:
            fid = self._travail("finalisation", "La 4K", lambda: self.route(
                "POST", "/video-h3/finaliser", {"job": film, "echelle": "4k", "ou": self.etat["ou"]}))
            film = self.route("GET", "/jobs/" + fid).get("finalisation", {}).get("film") or ""
            if not film:
                raise Arret("La 4K n'a pas rendu de film.")
        if reglages["musique"] and not f.get("sans_musique"):
            try:
                chanson = self._travail("chanson", "La musique", lambda: self.route(
                    "POST", "/chanson/creer", {"style": reglages["musique"], "lora": True, "duree": "1",
                                               # un tour tourné ici a sa musique ici aussi (propriétaire, 06/10 :
                                               # « music local too ») ; sinon chez Modal, comme avant
                                               "ou": "ici" if self.etat["ou"] == "maison" else "modal",
                                               "titre": "Tour 360° : " + self.etat["nom"]}))
                film = self._travail("musique", "La pose de la musique", lambda: self.route(
                    "POST", "/video-h3/musique", {"film": film, "chanson": chanson, "debut_s": 0,
                                                  "volume": MUSIQUE_VOLUME, "fondu_s": MUSIQUE_FONDU_S}))
            except Arret as exc:      # sans musique, le tour reste un tour
                f["sans_musique"] = str(exc)[:300]
                self.noter("finition_sans_musique", erreur=f["sans_musique"])
        if reglages["fluide"] and not f.get("sans_fluide"):
            mesure = base if film != base else ""
            try:
                film = self._travail("fluide", "Les 60 images/s", lambda: self.route(
                    "POST", "/video-h3/fluidifier", dict({"job": film}, **({"chemin": mesure} if mesure else {}))))
            except Arret as exc:      # pas de carte ici, par exemple : le tour reste à 24 images/s, l'état le dit
                f["sans_fluide"] = str(exc)[:300]
                self.noter("finition_sans_fluide", erreur=f["sans_fluide"])
        if reglages["compresser"]:
            try:
                film = self._travail("compresse", "La compression", lambda: self.route(
                    "POST", "/video-h3/compresser", {"job": film}))
            except Arret as exc:      # rien de gagné : le film non compressé reste le bon
                self.noter("finition_sans_compression", erreur=str(exc)[:300])
        f["film"] = film
        self.etat["film_final"] = film
        self.noter("finition", job=film)

    def derouler(self):
        try:
            for etape in self.ETAPES:
                if etape in self.etat["faites"]:
                    continue
                # sans mesure (tour d'avant le plan, ou panorama déjà fait) : ni mesure ni plan
                if etape in ("mesure", "plan") and ((self.mesure_ is None and not self.etat.get("texte"))
                                                    or "panorama" in self.etat["faites"]):
                    continue
                getattr(self, etape + "_" if etape == "panorama" else etape)()
                self.etat["faites"].append(etape)
                self.ecrire()
            self.etat["statut"] = "fini"
        except Attente:
            self.etat["statut"] = A_VALIDER
        except Arret as exc:
            self.etat.update(statut="arrete", erreur=str(exc))
        except Exception as exc:  # noqa: BLE001 -- l'état dit la panne, le fil ne meurt pas muet
            self.etat.update(statut="arrete", erreur="%s : %s" % (type(exc).__name__, str(exc)[:600]))
        self.noter(self.etat["statut"])


PLAN_HISTORIQUE_MAX = 30


def relire_plan(etat: dict, chat: Callable, photo=None) -> dict:
    """Le relecteur : un second appel du chat reçoit le texte, la photo, le plan proposé et les constats calculés
    (recouvrements, passages bouchés, place sur la photo), et rend le plan amélioré s'il le faut. Une relecture
    en échec ne bloque pas le tour : le plan proposé reste, et l'état le dit."""
    plan, geo = etat["plan"], etat["mesure"]
    propose, problemes = plan, []
    for tour in range(plan_piece.RELECTURES_MAX):
        # un plan corrigé qui garde des défauts calculés repasse une fois (06/10, validation : relecteur indulgent)
        if tour and not plan_piece.defauts(plan, geo):
            break
        try:
            reponse = chat(plan_piece.consigne_relecture(etat.get("description") or etat.get("nom") or "", plan,
                                                         geo, photo is not None), [_data_url(photo)] if photo else [])
            vus, corrige, remarques = plan_piece.lire_relecture(reponse, geo)
        except (Arret, ValueError) as exc:
            if not tour:
                return {"problemes": ["Relecture impossible (%s) : plan proposé gardé." % _phrase(str(exc), 160)],
                        "corrige": False}
            break
        problemes += [p for p in vus if p not in problemes]
        if corrige is None:
            break
        plan = corrige
        etat.update(plan=corrige, plan_remarques=(etat.get("plan_remarques") or []) + remarques,
                    plan_propose=propose)
        plan_piece.recaler_geo(geo, plan)
    return {"problemes": problemes[:plan_piece.RELECTURE_MAX], "corrige": plan is not propose}


def retoucher_plan(etat: dict, message: str, chat: Callable, photo: bytes) -> dict:
    """Le client écrit (« déplace le canapé contre la fenêtre »), le chat rend le plan modifié ; l'ancien plan est
    gardé dans l'historique. ValueError si le tour n'attend pas son plan, ou si la réponse est illisible (le plan
    ne change pas)."""
    if etat.get("statut") != A_VALIDER or not etat.get("plan"):
        raise ValueError("Ce tour n'attend pas la validation de son plan.")
    message = _phrase(message, 600)
    if not message:
        raise ValueError("Écrivez ce qu'il faut changer au plan.")
    reponse = chat(plan_piece.consigne_retouche(etat["plan"], message), [_data_url(photo)] if photo else [])
    plan, remarques = plan_piece.lire_plan(plan_piece._json_de(reponse), etat["mesure"])
    historique = etat.setdefault("plan_historique", [])
    historique.append({"le": round(time.time()), "message": message, "avant": etat["plan"]})
    del historique[:-PLAN_HISTORIQUE_MAX]
    avant = historique[-1]["avant"].get("personnage")
    point = plan_piece.place_personnage(plan, (etat.get("personnage") or {}).get("pres_de")) if avant else None
    if point:                       # le personnage reste devant son élément, même déplacé
        plan["personnage"] = dict(point, nom=avant["nom"])
    etat.update(plan=plan, plan_remarques=remarques)
    plan_piece.recaler_geo(etat["mesure"], plan)
    etat["journal"].append({"le": round(time.time()), "etape": "plan_retouche", "message": message})
    return etat


def valider_plan(etat: dict) -> dict:
    if etat.get("statut") != A_VALIDER or not etat.get("plan"):
        raise ValueError("Ce tour n'attend pas la validation de son plan.")
    etat.update(plan_valide=True, statut="en cours", erreur="")
    if "plan" not in etat["faites"]:
        etat["faites"].append("plan")
    etat["journal"].append({"le": round(time.time()), "etape": "plan_valide"})
    return etat


def lire_finition(reglages) -> dict:
    """{4k, musique (style ou ""), fluide, compresser} ; ce qui manque prend FINITION_DEFAUT. ValueError sinon."""
    if reglages in (None, ""):
        return dict(FINITION_DEFAUT)
    if not isinstance(reglages, dict) or set(reglages) - set(FINITION_DEFAUT):
        raise ValueError("Finition : 4k, musique, fluide, compresser.")
    sortie = dict(FINITION_DEFAUT, **reglages)
    for k in ("4k", "fluide", "compresser"):
        sortie[k] = bool(sortie[k])
    sortie["musique"] = _phrase(sortie["musique"] or "", 300)
    return sortie


def couper_sur_personnage(groupes: list, vides: list) -> list:
    """Le chemin coupé là où la caméra quitte la place d'un personnage. Sans épingle dans sa zone (une vue exacte
    l'efface ou le fige), la caméra de H3 y prend du retard ; l'épingle suivante la rattrape d'un coup et le
    personnage s'efface dans le fondu (château, 07/10 : 25° de retard en fin de clip 2, effacé au début du clip 3).
    Le clip qui part de la zone et en sort (là où le rattrapage se ferait) ouvre un groupe depuis la clé exacte de la
    sortie de la zone, dans le sens du tour ; le clip d'avant ferme le sien (`coupe` : un plan serré du personnage se
    monte là)."""
    sortie = []
    for clips in groupes:
        courant = []
        for c in clips:
            c = dict(c, coupe=False)
            zone = next((z for z in vides if chaine.dans(c["a"], z[0], z[1])), None)
            if zone and (sortie or courant) and not chaine.dans(c["b"], zone[0], zone[1]):
                if courant:
                    sortie.append(courant)
                    courant = []
                sortie[-1][-1]["coupe"] = True
                sens = 1 if c["b"] >= c["a"] else -1
                bord = zone[1] if sens > 0 else zone[0]
                c["a"] = round(c["a"] + sens * ((bord - c["a"]) * sens % 360.0), 3)
            courant.append(c)
        sortie.append(courant)
    return sortie


def lire_camera_etat(etat: dict) -> dict:
    """Les réglages de caméra du tour ; un tour d'avant la liste (sans réglage) fait le tour par défaut."""
    return chaine.lire_camera(etat.get("reglages_camera"))


def demande_du_groupe(etat: dict, dossier: Path, k: int, delai_s: int) -> dict:
    """La demande H3 du groupe k, depuis l'état et les fichiers du tour (rien ne vient de la page)."""
    groupes = etat.get("groupes") or []
    if not 0 <= k < len(groupes):
        raise ValueError("Groupe inconnu.")
    g, dossier = groupes[k], Path(dossier)
    cartes = {n: (dossier / "cartes" / (n + ".png")).read_bytes() for s in g["sujets"] for n in s}
    return chaine.demande_groupe(g["clips"], g["invites"], g["sujets"], cartes, (dossier / "pano.png").read_bytes(),
                                 float(etat["geometrie"]["fx_vue"]), etat["graine"], delai_s,
                                 zones=[tuple(z) for z in etat.get("zones") or []],
                                 ref_image_size=etat.get("ref_image_size") or "match")


def lire_personnage(p):
    """{fiche, pres_de?, action?, tenue?} -> le personnage du tour (ce qui manque, le chat le choisit) ; None sans
    personnage. ValueError si illisible."""
    if p in (None, "", {}):
        return None
    if not isinstance(p, dict) or set(p) - {"fiche", "pres_de", "action", "tenue"} or not p.get("fiche"):
        raise ValueError("Personnage : fiche, et au choix pres_de, action, tenue.")
    return {"fiche": str(p["fiche"]), "pres_de": _phrase(p.get("pres_de"), 40), "action": _phrase(p.get("action"), 200),
            "tenue": _phrase(p.get("tenue"), 200)}


def poser_personnage(etat: dict, p) -> dict:
    """Un personnage ajouté à un tour qui n'a pas encore écrit ses groupes (ValueError sinon)."""
    if etat.get("groupes") or "personnage" in etat.get("faites", []):
        raise ValueError("Ce tour a déjà écrit ses clips : lancez un nouveau tour avec ce personnage.")
    etat["personnage"] = lire_personnage(p)
    etat["journal"].append({"le": round(time.time()), "etape": "personnage_demande"})
    return etat


def nouvel_etat(fiche: dict, ou: str = "modal", graine=None, pas=None, finition=None, camera=None,
                texte: bool = False, personnage=None, ref_image_size=None) -> dict:
    if fiche.get("genre") != "decor":
        raise ValueError("Le tour 360° se fait sur une fiche « décor ».")
    personnage = lire_personnage(personnage)
    if ref_image_size not in (None, "", "match", "max"):
        raise ValueError("Taille des références : « match » ou « max ».")
    camera = chaine.lire_camera(camera)
    pas = PAS if pas in (None, "") else pas
    if pas not in PAS_PERMIS:
        raise ValueError("Pas du tour : %s degrés." % " ou ".join(map(str, PAS_PERMIS)))
    try:
        graine = GRAINE if graine in (None, "") else int(graine)
    except (TypeError, ValueError):
        raise ValueError("Graine illisible.") from None
    return {"id": uuid.uuid4().hex, "fiche": fiche["id"], "nom": fiche["nom"],
            "description": fiche.get("description") or "", "cree_le": round(time.time()), "ou": ou, "graine": graine,
            "pas": pas, "reglages_camera": camera, "reglages_finition": lire_finition(finition), "plan_valide": False,
            "statut": "en cours", "etape": "", "texte": bool(texte), "personnage": personnage,
            "ref_image_size": ref_image_size or "match", "faites": [], "journal": [], "erreur": ""}
