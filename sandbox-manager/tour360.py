"""Le tour 360° d'un décor, fait seul (propriétaire, 06/10 : « adapt studio to automate that »).

La recette d'atelier de docs/DECOR_360.md (étape 7), sans main, depuis une fiche « décor » :
  consigne   le chat regarde la photo du décor et écrit la consigne du panorama (ce que la photo ne montre pas) ;
  panorama   une carte louée (tour360_pano.py) : MoGe-3 mesure la pièce, la boîte guide Qwen-Image 2.1 + Union,
             SeedVR2, la photo recollée ; les images clés du tour découpées dans ce SEUL panorama, tous les PAS degrés ;
  cartes     les cartes d'identité des éléments : le chat voit les images clés et nomme chaque élément (meuble,
             ouverture, mur nu) avec sa place dans chaque vue ; l'azimut en est tiré ;
  troncons   un clip H3 « première et dernière image » par pas, sa consigne tirée des cartes : ce qu'il voit au
             départ, à l'arrivée, ce qu'il croise, et rien d'autre (sans elle, H3 invente une autre pièce sur un mur nu) ;
  montage    les tronçons bout à bout, un même fond sonore (`lieux`).
Chaque étape écrit l'état ; une reprise saute les étapes faites (comme film_auto).
"""
import base64
import json
import math
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

import agrandir
import retouche_qwen as rq
import video_h3

GPU = "A100-80GB"         # celle de l'atelier (maquette4_modal) : Qwen 2.1 + Union à 2048×1024, puis SeedVR2
MEMOIRE_MB = 65536
COEURS = 8.0
DUREE_MAX_S = 2400
PAQUETS = video_h3.PAQUETS_POIDS
PAS_PERMIS = (30, 45)     # 45 : 8 tronçons ; 30 : 12, plus sûr sur un mur nu (06/10, tronçon 6 : une pièce inventée)
PAS = 45
LONGUEUR = 124            # 5,2 s par tronçon
DEFINITION = "768p"
GRAINE = 11
RESOLUTION = 1440         # -> latent 2048×1024 pour l'image 2:1
MOGE_DEPOT = "git+https://github.com/microsoft/MoGe.git@74fbce054ebed49800de42d0ad0e83495065719a"
MOGE_MODELE = "Ruicheng/moge-3-vitl"
T8 = ("https://github.com/T8mars/Comfyui-Qwen-Image-2.1-Fun-Controlnet-Union-T8",
      "01f084ccde2f2a262529b6e7b5504df9ea36a0b7")
UNION = ("Qwen-Image-2.1-Fun-Controlnet-Union-ComfyUI.safetensors", "t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy",
         "199bd863c41b5401e3c9bbc2b1bd4b62f468229c")
ATTENTE_PAS_S = 15
ATTENTE_MAX_S = 3 * 3600
CARTES_MAX = 24
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


def demande(photo: bytes, consigne: str, graine: int = GRAINE, pas: int = PAS) -> dict:
    graphes = {"graphe_dessin": graphe_union("maquette.png", "masque.png", "aretes.png", consigne, graine),
               "graphe_couture": graphe_union("tourne.png", "bande.png", "aretes_tourne.png", consigne, graine),
               "graphe_agrandi": graphe_agrandi()}
    classes = sorted({n["class_type"] for g in graphes.values() for n in g.values()})
    return dict(graphes, poids=[
        {"depot": rq.HF, "revision": rq.HF_REVISION, "fichiers": list(rq.FICHIERS), "base": rq.DOSSIER_POIDS},
        {"depot": UNION[1], "revision": UNION[2], "fichiers": [UNION[0]], "base": rq.DOSSIER_POIDS + "/controlnet"},
        {"depot": agrandir.HF, "revision": agrandir.HF_REVISION, "fichiers": list(agrandir.FICHIERS),
         "base": agrandir.DOSSIER_POIDS}],
        photo=base64.b64encode(photo).decode(), moge=MOGE_MODELE, pas=int(pas), comfy=video_h3.DOSSIER_COMFY,
        base_qwen=rq.DOSSIER_POIDS, base_seedvr=agrandir.DOSSIER_POIDS, classes=classes,
        delai_s=DUREE_MAX_S - 60)


def construire_script(photo: bytes, consigne: str, graine: int = GRAINE, pas: int = PAS) -> str:
    source = Path(__file__).with_name("tour360_pano.py").read_text(encoding="utf-8")
    return video_h3._emballer(source + "\n\nprincipal()\n", demande(photo, consigne, graine, pas))


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("POIDS_ABSENTS", "Les poids (Qwen-Image 2.1, Union, SeedVR2) n'ont pas pu être posés sur le disque Modal."),
            ("NOEUD_ABSENT", "Ce ComfyUI n'a pas les nœuds Qwen-Image 2.1 Union."),
            ("GRAPHE_REFUSE", "ComfyUI a refusé un graphe du panorama."),
            ("COMFY_ARRETE", "ComfyUI s'est arrêté pendant le panorama (mémoire ?)."),
            ("CALCUL_ECHOUE", "Le panorama n'a pas pu être dessiné."),
            ("DELAI", "Le panorama n'était pas fini avant le délai."),
            ("PIECE_ILLISIBLE", "La photo du décor ne montre pas assez de sol pour mesurer la pièce.")):
        if mot in s:
            return phrase
    return ""


# --- Ce que le chat écrit, et comment on le lit -------------------------------------------------------------------

CONSIGNE_DESSIN = (
    "The attached photo shows a place (a film set), described by its owner as: « %s ». A 360° panorama of this place, "
    "seen from the same spot, will be painted around the photo. Answer with JSON only, in English: "
    '{"piece": "<the place in 2 to 4 words, with its article, e.g. the living room>", '
    '"panorama": "<3 to 5 sentences: what surrounds the camera on the left, on the right and BEHIND it, which the '
    'photo does not show; keep to what the description and the photo imply; the room is closed, no other room>", '
    '"ambiance": "<one sentence: the quiet sound of this place, no music, no voice>"}')

CONSIGNE_CARTES = (
    "These %d images are the views of a slow 360° turn on the spot, %d degrees apart, in order, turning right; the "
    "last one is followed by the first. List the KEY ELEMENTS of the place: each piece of furniture, each opening "
    "(window, glass wall, door, doorway) and each long bare wall. Give the SAME element once, even when several "
    "views show it. Answer with JSON only: a list of at most %d objects "
    '{"nom": "<short id, lowercase>", "description": "<one English sentence describing it so that a video model '
    'redraws it exactly: material, colour, shape, where it stands>", "vues": [{"vue": <view number from 1>, '
    '"x0": <left edge, 0-1000>, "x1": <right edge, 0-1000>}]}. x is measured across the width of each view.')

MOUVEMENT = ("A slow, steady pan to the right: the camera stays in place at eye level and turns smoothly about %s "
             "degrees on its axis, revealing the rest of %s. Nothing in the place moves.")
RIEN_D_AUTRE = ("There is nothing else in this part of %s: no other furniture, no pictures on the walls, no rug, no "
                "other room.")
NOMBRES = {30: "thirty", 45: "forty-five"}


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
            "ambiance": _phrase(d.get("ambiance"), 200) or "Quiet room tone"}


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


def liste(cartes: list) -> str:
    return "; ".join(c["description"] for c in cartes) if cartes else "plain walls"


def consignes_troncons(cartes: list, consigne: dict, fx: float, pas: int) -> list:
    """Une consigne par tronçon : la caméra va du cap k·pas au cap (k+1)·pas."""
    demi = math.degrees(math.atan(VUE_L / 2 / fx))
    piece = consigne["piece"]
    sortie = []
    for k in range(360 // pas):
        a, b = k * pas, (k + 1) * pas
        sortie.append({
            "image_paroles": (MOUVEMENT % (NOMBRES.get(pas, str(pas)), piece) + " The camera only passes: "
                              + liste(visibles(cartes, (a + b) / 2, demi + pas / 2)) + ". " + RIEN_D_AUTRE % piece),
            "description_premiere": "%s, showing %s." % (piece, liste(visibles(cartes, a, demi))),
            "description_derniere": "the same place, the camera turned further right, showing %s."
                                    % liste(visibles(cartes, b, demi)),
            "ambiance": consigne["ambiance"]})
    return sortie


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


class Tour:
    """`appel(methode, chemin, corps)` -> (code, json) : les routes du Studio ; `chat(consigne, images)` -> texte ;
    `panorama(photo, texte, graine, pas)` -> {nom: octets} (geometrie.json, pano.png, cle_NNN.png…), Arret sinon ;
    `decouper(png, x0, x1)` -> png."""

    ETAPES = ("consigne", "panorama", "cartes", "troncons", "montage")

    def __init__(self, etat: dict, dossier: Path, appel: Callable, chat: Callable, panorama: Callable,
                 decouper: Callable = decouper_ffmpeg, dormir: Callable = time.sleep):
        self.etat, self.dossier, self.appel, self.chat = etat, Path(dossier), appel, chat
        self.panorama, self.decouper, self.dormir = panorama, decouper, dormir

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
            c = lire_consigne(self.chat(CONSIGNE_DESSIN % _phrase(self.etat["description"], 1400),
                                        [_data_url(self._photo())]))
        except ValueError as exc:
            raise Arret(str(exc)) from exc
        self.etat["consigne"] = c
        self.noter("consigne", piece=c["piece"])

    def panorama_(self):
        fichiers = self.panorama(self._photo(), texte_dessin(self.etat["consigne"]), self.etat["graine"],
                                 self.etat["pas"])
        manque = [n for n in ["geometrie.json"] + ["cle_%03d.png" % c for c in self._caps()] if n not in fichiers]
        if manque:
            raise Arret("Le panorama n'a pas rendu : %s." % ", ".join(manque))
        (self.dossier / "cles").mkdir(parents=True, exist_ok=True)
        for nom, octets in fichiers.items():
            if re.fullmatch(r"cle_\d{3}\.png", nom):
                (self.dossier / "cles" / nom).write_bytes(octets)
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
        self.etat["consignes"] = consignes_troncons(cartes, self.etat["consigne"], fx, self.etat["pas"])
        self.noter("cartes", nombre=len(cartes))

    def troncons(self):
        faits = self.etat.setdefault("troncons", [])
        caps = self._caps()
        for k in range(len(faits), len(caps)):
            c = self.etat["consignes"][k]
            corps = dict(c, mode="premiere_derniere", camera={"mouvement": "pano_droite", "vitesse": "lente"},
                         images=[base64.b64encode(self._cle(caps[k])).decode(),
                                 base64.b64encode(self._cle(caps[k] + self.etat["pas"])).decode()],
                         definition=DEFINITION, longueur=LONGUEUR, graine=self.etat["graine"], ou=self.etat["ou"])
            job = self.route("POST", "/video-h3/creer", corps)
            self.noter("troncon_lance", troncon=k + 1, job=job["id"])
            self.reussi(job["id"], "Le tronçon %d" % (k + 1))
            faits.append(job["id"])
            self.noter("troncon", troncon=k + 1, job=job["id"])

    def montage(self):
        n = len(self.etat["troncons"])
        film = self.route("POST", "/video-h3/montage", {"clips": self.etat["troncons"],
                                                        "scenario": "Tour 360° : " + self.etat["nom"],
                                                        "lieux": ["tour"] * n})
        self.reussi(film["id"], "Le montage")
        self.etat["film"] = film["id"]
        self.noter("montage", job=film["id"])

    def derouler(self):
        try:
            for etape in self.ETAPES:
                if etape in self.etat["faites"]:
                    continue
                getattr(self, etape + "_" if etape == "panorama" else etape)()
                self.etat["faites"].append(etape)
                self.ecrire()
            self.etat["statut"] = "fini"
        except Arret as exc:
            self.etat.update(statut="arrete", erreur=str(exc))
        except Exception as exc:  # noqa: BLE001 -- l'état dit la panne, le fil ne meurt pas muet
            self.etat.update(statut="arrete", erreur="%s : %s" % (type(exc).__name__, str(exc)[:600]))
        self.noter(self.etat["statut"])


def nouvel_etat(fiche: dict, ou: str = "modal", graine=None, pas=None) -> dict:
    if fiche.get("genre") != "decor":
        raise ValueError("Le tour 360° se fait sur une fiche « décor ».")
    pas = PAS if pas in (None, "") else pas
    if pas not in PAS_PERMIS:
        raise ValueError("Pas du tour : %s degrés." % " ou ".join(map(str, PAS_PERMIS)))
    try:
        graine = GRAINE if graine in (None, "") else int(graine)
    except (TypeError, ValueError):
        raise ValueError("Graine illisible.") from None
    return {"id": uuid.uuid4().hex, "fiche": fiche["id"], "nom": fiche["nom"],
            "description": fiche.get("description") or "", "cree_le": round(time.time()), "ou": ou, "graine": graine,
            "pas": pas, "statut": "en cours", "etape": "", "faites": [], "journal": [], "erreur": ""}
