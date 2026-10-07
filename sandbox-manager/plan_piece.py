"""Le plan au sol d'un lieu, pour son tour 360° (PLAN 21.6 étapes 1 à 3, 06/10).

Propriétaire, 06/10 : « le llm imagine le plan au sol et les divers éléments (ici des meubles), le client peut
chatter pour modifier et valider, puis la suite ». L'atelier du 06/10 a montré pourquoi : les arêtes seules disent
ce qu'est chaque chose (une baie sans traverse ni seuil devient un mur, une bibliothèque en une boîte devient une
armoire) ; la maquette se construit donc PAR PARTIES, un gabarit par genre.

Repère (celui de tour360_pano.repere) : x à droite, z devant, caméra à l'origine ; ici les hauteurs se comptent
AU-DESSUS DU SOL (la maquette les retourne : y vers le bas, sol à y = hauteur de la caméra). La photo regarde au
cap `lacet` de la pièce ; le cap d'un panorama (0 = la photo) vaut donc l'azimut dans la pièce moins le lacet.

Un plan : {piece: [x0, x1, z0, z1], plafond, murs (phrase anglaise), elements: [{nom, genre, description,
emprise: [x0, x1, z0, z1], hauteur: [bas, haut]}]}.

Python seul (le Studio n'a ni NumPy ni PIL) : la maquette en rayons se fait sur la machine du panorama
(tour360_pano.scene), depuis `scene_du_plan`. Les vues pour le client sont des SVG.
"""
import json
import math
import re

GENRES = {
    "canape": "sofa", "fauteuil": "armchair", "chaise": "chair", "table": "table, coffee table or desk",
    "lit": "bed", "bibliotheque": "bookshelf or open shelving", "meuble": "cabinet, chest, wardrobe, sideboard, TV "
    "stand or any other closed piece of furniture", "lampe": "floor lamp", "plante": "plant in a pot", "tapis": "rug",
    "porte": "door", "ouverture": "doorway without a door", "fenetre": "window", "baie": "floor-to-ceiling glass wall "
    "or French window", "tableau": "painting, mirror, tapestry or screen hung on a wall",
    # au-delà d'un salon (propriétaire, 06/10 : « castle, forest… ») : chacun par parties, comme les meubles
    "arbre": "tree", "rocher": "rock, boulder or log", "colonne": "column, pillar or post",
    "escalier": "staircase or steps", "cheminee": "fireplace", "batiment": "building, house or facade (outdoors)",
    "objet": "any other free-standing thing (statue, well, fountain, barrel, cart, throne, stove...)",
    # 06/10, validation sur 8 lieux : mer, lac, chemin rendus en boîtes debout qui recouvraient les palmiers
    "surface": "flat area on the ground: water, sea, lake, pond, path, road, sand, lawn"}
MURAUX = ("porte", "ouverture", "fenetre", "baie", "tableau")
PLATS = ("tapis", "surface")              # à plat sur le sol : on passe dessus, rien ne s'y recouvre
TROUS = ("ouverture", "fenetre", "baie")
# largeur, profondeur, hauteur (m) quand le chat n'en dit rien ; la profondeur minimale d'un élément vu de face
DEFAUT = {"canape": (2.0, 0.9, 0.85), "fauteuil": (0.85, 0.85, 0.9), "chaise": (0.45, 0.5, 0.9),
          "table": (1.2, 0.6, 0.45), "lit": (1.6, 2.0, 1.0), "bibliotheque": (1.0, 0.35, 2.0),
          "meuble": (1.0, 0.5, 0.9), "lampe": (0.4, 0.4, 1.6), "plante": (0.5, 0.5, 1.2), "tapis": (2.0, 1.4, 0.02),
          "porte": (0.9, 0.04, 2.05), "ouverture": (0.9, 0.08, 2.05), "fenetre": (1.2, 0.08, 1.2),
          "baie": (2.4, 0.08, 2.3), "tableau": (0.8, 0.03, 0.6), "arbre": (3.0, 3.0, 8.0), "rocher": (1.5, 1.2, 1.0),
          "colonne": (0.6, 0.6, 4.0), "escalier": (1.2, 3.0, 2.0), "cheminee": (1.6, 0.5, 1.2),
          "batiment": (8.0, 6.0, 7.0), "objet": (0.8, 0.8, 1.0), "surface": (4.0, 4.0, 0.02)}
BAS_DEFAUT = {"fenetre": 0.9, "tableau": 1.3}
PLAFOND_MAX = 15.0        # m : une grande salle de château, une nef
CIEL = 40.0               # m : dehors, rien au-dessus ; la hauteur la plus grande d'un élément
ELEMENTS_MAX = 24
CADRE_MAX = 0.6           # part de la photo au-delà de laquelle un cadre du chat n'est pas une mesure
CAMERA_LIBRE = 0.45       # m : aucun meuble à moins de ça de la caméra (il boucherait la moitié du panorama)
COLLE_AU_MUR = 0.3        # m : un meuble plus près d'un mur y est adossé
SITE_MAX = 40.0           # degrés : la carte d'un élément s'arrête là en hauteur (cartes_plan.py de l'atelier)
MUR_NU_MIN = 35.0         # degrés sans élément : une carte « mur nu » (06/10, tronçon 6 : une pièce inventée)
DESCRIPTION_MAX = 220
SUJETS_MAX = 7            # cartes par clip : 2 clés + 7 cartes = 9 images, le maximum de H3 (tour360.invite_clip)
PAS_CLIP = 60.0           # degrés par clip du tour par défaut (360° en 30 s, clips de 5 s : tour360_chaine)
VUE_L = 1344              # largeur des images clés (tour360.VUE_L)
GROUPE_MAX = 50.0         # degrés : deux cartes voisines plus larges ensemble ne font plus une image lisible
PIECE_MAX = 40.0          # m : une clairière, une place, une plage vue de près


def _phrase(x, n=DESCRIPTION_MAX) -> str:
    return " ".join(str(x or "").split())[:n].rstrip(" .")


def _nom(x) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(x or "").lower()).strip("_")[:40] or "element"


def _nombre(x, defaut=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return defaut
    return v if math.isfinite(v) else defaut


def _borne(v, a, b):
    return max(a, min(b, v))


def _centile(valeurs, q):
    v = sorted(valeurs)
    if not v:
        return None
    i = (len(v) - 1) * q
    k = int(i)
    return v[k] if k + 1 >= len(v) else v[k] + (v[k + 1] - v[k]) * (i - k)


# --- Où est le dos d'un élément, et ses parties ----------------------------------------------------------------

def dos(emprise, piece) -> str:
    """Le mur le plus proche de l'emprise : « x- », « x+ », « z- » ou « z+ » (le dos de l'élément y est tourné)."""
    ex0, ex1, ez0, ez1 = emprise
    x0, x1, z0, z1 = piece
    ecarts = {"x-": ex0 - x0, "x+": x1 - ex1, "z-": ez0 - z0, "z+": z1 - ez1}
    return min(ecarts, key=ecarts.get)


def _cote(e, piece) -> str:
    """Le dos de l'élément : celui de sa façade quand il est posé sur un bâtiment (dehors), sinon son mur."""
    return e.get("dos") or dos(e["emprise"], piece)


def _local(e, cote):
    """(largeur, profondeur, boite(u0, u1, w0, w1, b, h)) : u le long du dos, w depuis le dos vers la pièce."""
    ex0, ex1, ez0, ez1 = e["emprise"]
    if cote in ("x-", "x+"):
        largeur, prof = ez1 - ez0, ex1 - ex0

        def boite(u0, u1, w0, w1, b, h):
            xa, xb = (ex0 + w0, ex0 + w1) if cote == "x-" else (ex1 - w1, ex1 - w0)
            return (xa, xb, ez0 + u0, ez0 + u1, b, h)
    else:
        largeur, prof = ex1 - ex0, ez1 - ez0

        def boite(u0, u1, w0, w1, b, h):
            za, zb = (ez0 + w0, ez0 + w1) if cote == "z-" else (ez1 - w1, ez1 - w0)
            return (ex0 + u0, ex0 + u1, za, zb, b, h)
    return largeur, prof, boite


def parties(e: dict, piece) -> list:
    """Les boîtes du gabarit de l'élément : [(partie, (x0, x1, z0, z1, bas, haut))], hauteurs au-dessus du sol."""
    cote = _cote(e, piece)
    L, P, f = _local(e, cote)
    b0, b1 = e["hauteur"]
    H = b1 - b0
    g = e["genre"]
    if g in ("canape", "fauteuil"):
        d = min(0.25, 0.3 * P)
        a = min(0.18, 0.2 * L)
        return [("dossier", f(0, L, 0, d, b0, b1)), ("assise", f(0, L, d, P, b0, b0 + 0.5 * H)),
                ("accoudoir_g", f(0, a, d, P, b0 + 0.5 * H, b0 + 0.7 * H)),
                ("accoudoir_d", f(L - a, L, d, P, b0 + 0.5 * H, b0 + 0.7 * H))]
    if g == "lit":
        return [("sommier", f(0, L, 0, P, b0, b0 + 0.5 * H)), ("tete", f(0, L, 0, 0.08, b0, b1))]
    if g in ("table", "chaise"):
        haut_assise = b1 - 0.04 if g == "table" else b0 + 0.5 * H
        p = min(0.06, 0.2 * L, 0.2 * P)
        pieds = [("pied_%d" % k, f(u, u + p, w, w + p, b0, haut_assise))
                 for k, (u, w) in enumerate([(0, 0), (L - p, 0), (0, P - p), (L - p, P - p)])]
        if g == "table":
            return [("plateau", f(0, L, 0, P, b1 - 0.04, b1))] + pieds
        return [("assise", f(0, L, 0, P, haut_assise - 0.04, haut_assise)),
                ("dossier", f(0, L, 0, 0.05, haut_assise, b1))] + pieds
    if g == "bibliotheque":
        n = max(2, round(H / 0.38))
        etageres = [("etagere_%d" % k, f(0, L, 0, P, b0 + k * H / n, b0 + k * H / n + 0.03)) for k in range(n)]
        return [("cote_g", f(0, 0.04, 0, P, b0, b1)), ("cote_d", f(L - 0.04, L, 0, P, b0, b1)),
                ("fond", f(0, L, 0, 0.03, b0, b1)), ("dessus", f(0, L, 0, P, b1 - 0.03, b1))] + etageres
    if g == "lampe":
        a = min(0.35, 0.25 * H)
        return [("pied", f(L / 2 - 0.02, L / 2 + 0.02, P / 2 - 0.02, P / 2 + 0.02, b0, b1 - a)),
                ("socle", f(L / 2 - 0.13, L / 2 + 0.13, P / 2 - 0.13, P / 2 + 0.13, b0, b0 + 0.03)),
                ("abat_jour", f(0, L, 0, P, b1 - a, b1))]
    if g == "plante":
        return [("pot", f(0.3 * L, 0.7 * L, 0.3 * P, 0.7 * P, b0, b0 + 0.35 * H)),
                ("feuillage", f(0, L, 0, P, b0 + 0.35 * H, b1))]
    if g in PLATS:
        return [(g, f(0, L, 0, P, b0, b0 + 0.02))]
    if g == "meuble":
        return [("socle", f(0.03, L - 0.03, 0, P - 0.03, b0, b0 + 0.08)), ("corps", f(0, L, 0, P, b0 + 0.08, b1)),
                ("joint", f(L / 2 - 0.01, L / 2 + 0.01, P, P + 0.01, b0 + 0.12, b1 - 0.04))]
    if g == "tableau":
        return [("tableau", f(0, L, 0, P, b0, b1))]
    if g == "arbre":
        t = min(0.5, 0.15 * L)
        return [("tronc", f(L / 2 - t / 2, L / 2 + t / 2, P / 2 - t / 2, P / 2 + t / 2, b0, b0 + 0.45 * H)),
                ("houppier", f(0, L, 0, P, b0 + 0.3 * H, b1))]
    if g == "colonne":
        s = min(0.15, 0.08 * H)
        return [("base", f(0, L, 0, P, b0, b0 + s)), ("fut", f(0.12 * L, 0.88 * L, 0.12 * P, 0.88 * P, b0 + s, b1 - s)),
                ("chapiteau", f(0, L, 0, P, b1 - s, b1))]
    if g == "escalier":                       # les marches montent vers le dos
        n = max(3, min(20, round(H / 0.18)))
        return [("marche_%d" % k, f(0, L, 0, P * (n - k) / n, b0 + k * H / n, b0 + (k + 1) * H / n))
                for k in range(n)]
    if g == "cheminee":
        j = min(0.25, 0.18 * L)
        if H > 1.8:                           # monumentale : foyer bas, hotte au-dessus (jambages pleine hauteur =
            o = b0 + min(1.6, 0.4 * H)        # un cadre de 4 m, peint en armoire : château, 07/10)
            return [("jambage_g", f(0, j, 0, P, b0, o)), ("jambage_d", f(L - j, L, 0, P, b0, o)),
                    ("linteau", f(0, L, 0, P, o, o + 0.15)),
                    ("hotte", f(0.08 * L, 0.92 * L, 0, 0.75 * P, o + 0.15, b1)),
                    ("foyer", f(j, L - j, 0, 0.6 * P, b0, b0 + 0.05))]
        return [("jambage_g", f(0, j, 0, P, b0, b1 - 0.1)), ("jambage_d", f(L - j, L, 0, P, b0, b1 - 0.1)),
                ("tablette", f(0, L, 0, P, b1 - 0.1, b1)), ("foyer", f(j, L - j, 0, 0.6 * P, b0, b0 + 0.05))]
    if g == "batiment":
        return [("murs", f(0, L, 0, P, b0, b0 + 0.75 * H)), ("toit", f(-0.3, L + 0.3, -0.3, P + 0.3, b0 + 0.75 * H, b1)),
                ("porte", f(L / 2 - 0.5, L / 2 + 0.5, P, P + 0.05, b0, b0 + 2.1))]
    c = 0.07                                  # chambranle d'une porte, d'une ouverture
    if g == "porte":
        return [("panneau", f(0, L, 0, 0.04, b0, b1)), ("chambranle_g", f(-c, 0, 0, 0.02, b0, b1 + c)),
                ("chambranle_d", f(L, L + c, 0, 0.02, b0, b1 + c)), ("linteau", f(-c, L + c, 0, 0.02, b1, b1 + c))]
    if g == "ouverture":
        return [("chambranle_g", f(-c, 0, 0, 0.02, b0, b1 + c)), ("chambranle_d", f(L, L + c, 0, 0.02, b0, b1 + c)),
                ("linteau", f(-c, L + c, 0, 0.02, b1, b1 + c))]
    if g == "fenetre":
        m = 0.05
        return [("cadre_bas", f(0, L, 0, 0.06, b0, b0 + m)), ("cadre_haut", f(0, L, 0, 0.06, b1 - m, b1)),
                ("cadre_g", f(0, m, 0, 0.06, b0, b1)), ("cadre_d", f(L - m, L, 0, 0.06, b0, b1)),
                ("meneau", f(L / 2 - 0.02, L / 2 + 0.02, 0, 0.06, b0, b1))]
    if g == "baie":                           # montants au plus tous les 1,2 m, traverse haute, seuil
        n = max(1, math.ceil(L / 1.2))
        montants = [("montant_%d" % k, f(_borne(k * L / n - 0.03, 0, L - 0.06), _borne(k * L / n + 0.03, 0.06, L),
                                         0, 0.08, b0, b1)) for k in range(n + 1)]
        return montants + [("traverse", f(0, L, 0, 0.08, b1 - 0.08, b1)), ("seuil", f(0, L, 0, 0.08, b0, b0 + 0.06))]
    return [("corps", f(0, L, 0, P, b0, b1))]


def trou(e: dict, piece):
    """Le jour d'une ouverture, d'une fenêtre, d'une baie dans son mur : {mur, a0, a1, bas, haut} (a le long du mur :
    z pour les murs x-/x+, x pour z-/z+) ; None pour le reste."""
    if e["genre"] not in TROUS or e.get("facade"):      # une fenêtre de façade ne perce pas les bords de la scène
        return None
    cote = _cote(e, piece)
    ex0, ex1, ez0, ez1 = e["emprise"]
    a0, a1 = (ez0, ez1) if cote in ("x-", "x+") else (ex0, ex1)
    return {"mur": cote, "a0": a0, "a1": a1, "bas": e["hauteur"][0], "haut": e["hauteur"][1]}


# --- Lire et corriger un plan -----------------------------------------------------------------------------------

def _au_mur(emprise, hauteur, genre, piece, plafond):
    """Un élément mural plaqué sur son mur, dans la largeur du mur."""
    x0, x1, z0, z1 = piece
    cote = dos(emprise, piece)
    ep = DEFAUT[genre][1]
    ex0, ex1, ez0, ez1 = emprise
    if cote in ("x-", "x+"):
        a0, a1 = _borne(ez0, z0, z1 - 0.2), _borne(ez1, z0 + 0.2, z1)
        x = (x0, x0 + ep) if cote == "x-" else (x1 - ep, x1)
        emprise = [x[0], x[1], a0, max(a1, a0 + 0.2)]
    else:
        a0, a1 = _borne(ex0, x0, x1 - 0.2), _borne(ex1, x0 + 0.2, x1)
        z = (z0, z0 + ep) if cote == "z-" else (z1 - ep, z1)
        emprise = [a0, max(a1, a0 + 0.2), z[0], z[1]]
    bas, haut = hauteur
    if genre in ("porte", "ouverture", "baie") and bas < 0.15:
        bas = 0.0
    if genre == "baie" and haut > plafond - 0.15:
        haut = plafond
    return emprise, [bas, _borne(haut, bas + 0.2, plafond)]


def _adosse(emprise, piece, genre):
    """Un meuble près d'un mur y est collé ; trop mince (vu de face), il s'épaissit vers son mur."""
    cote = dos(emprise, piece)
    x0, x1, z0, z1 = piece
    ex0, ex1, ez0, ez1 = emprise
    pmin = 0.7 * DEFAUT[genre][1]
    if cote == "x-":
        ex0 = x0 if ex0 - x0 < COLLE_AU_MUR else min(ex0, ex1 - pmin)
    elif cote == "x+":
        ex1 = x1 if x1 - ex1 < COLLE_AU_MUR else max(ex1, ex0 + pmin)
    elif cote == "z-":
        ez0 = z0 if ez0 - z0 < COLLE_AU_MUR else min(ez0, ez1 - pmin)
    else:
        ez1 = z1 if z1 - ez1 < COLLE_AU_MUR else max(ez1, ez0 + pmin)
    return [max(ex0, x0), min(ex1, x1), max(ez0, z0), min(ez1, z1)]


def _hors_rect(cx, cz, r) -> float:
    return math.hypot(max(r[0] - cx, 0.0, cx - r[1]), max(r[2] - cz, 0.0, cz - r[3]))


def _a_la_facade(emprise, hauteur, genre, batiments):
    """Dehors, une porte, une fenêtre, une enseigne vont sur la façade la plus proche du bâtiment le plus proche
    (06/10, validation : plaquées sur les bords de la scène, derrière les maisons) : (emprise, hauteur, dos, nom)."""
    ex0, ex1, ez0, ez1 = emprise
    cx, cz = (ex0 + ex1) / 2, (ez0 + ez1) / 2
    b = min(batiments, key=lambda b: _hors_rect(cx, cz, b["emprise"]))
    bx0, bx1, bz0, bz1 = b["emprise"]
    face = min({"x-": abs(cx - bx0), "x+": abs(cx - bx1), "z-": abs(cz - bz0), "z+": abs(cz - bz1)}.items(),
               key=lambda kv: kv[1])[0]
    ep = DEFAUT[genre][1]
    long_x = face in ("z-", "z+")
    a0, a1, c = (bx0, bx1, cx) if long_x else (bz0, bz1, cz)
    L = min(max(ex1 - ex0, ez1 - ez0, 0.2), a1 - a0)
    c = _borne(c, a0 + L / 2, a1 - L / 2)
    le_long = [c - L / 2, c + L / 2]
    if face == "x-":
        emprise, cote = [bx0 - ep, bx0] + le_long, "x+"
    elif face == "x+":
        emprise, cote = [bx1, bx1 + ep] + le_long, "x-"
    elif face == "z-":
        emprise, cote = le_long + [bz0 - ep, bz0], "z+"
    else:
        emprise, cote = le_long + [bz1, bz1 + ep], "z-"
    bb, bh = b["hauteur"]
    murs = bb + 0.75 * (bh - bb)              # sous le toit (gabarit du bâtiment)
    bas, haut = hauteur
    if genre in ("porte", "ouverture", "baie") and bas < 0.15:
        bas = 0.0
    bas = _borne(bas, bb, murs - 0.2)
    return emprise, [bas, _borne(haut, bas + 0.2, murs)], cote, b["nom"]


def lire_plan(d, geo: dict):
    """Un plan propre depuis ce que rend le chat (ou la page) : (plan, remarques). ValueError s'il n'en reste rien."""
    if not isinstance(d, dict):
        raise ValueError("Plan illisible : pas d'objet JSON.")
    remarques = []
    gx0, gx1, gz0, gz1 = geo["piece"]
    p = d.get("piece") if isinstance(d.get("piece"), list) and len(d.get("piece")) == 4 else [gx0, gx1, gz0, gz1]
    p = [_nombre(v, g) for v, g in zip(p, (gx0, gx1, gz0, gz1))]
    piece = [_borne(min(p[0], p[1]), -PIECE_MAX, -0.3), _borne(max(p[0], p[1]), 0.3, PIECE_MAX),
             _borne(min(p[2], p[3]), -PIECE_MAX, -0.5), _borne(max(p[2], p[3]), 0.5, PIECE_MAX)]
    dehors = bool(d.get("dehors", geo.get("dehors", False)))
    plafond = CIEL if dehors else _borne(_nombre(d.get("plafond"), geo["plafond"]),
                                         max(2.1, geo["hauteur"] + 0.3), PLAFOND_MAX)
    elements, noms = [], set()
    for e in d.get("elements") or []:
        if not isinstance(e, dict):
            continue
        nom = _nom(e.get("nom"))
        genre = e.get("genre") if e.get("genre") in GENRES else "objet"
        if e.get("genre") not in GENRES:
            remarques.append("%s : genre « %s » inconnu, pris pour un objet." % (nom, e.get("genre")))
        description = _phrase(e.get("description"))
        emp = e.get("emprise")
        hau = e.get("hauteur")
        if not description or not (isinstance(emp, list) and len(emp) == 4) or not (
                isinstance(hau, list) and len(hau) == 2):
            remarques.append("%s : sans description, emprise ou hauteur, écarté." % nom)
            continue
        emp = [_nombre(v) for v in emp]
        hau = [_nombre(v) for v in hau]
        if None in emp or None in hau:
            remarques.append("%s : nombres illisibles, écarté." % nom)
            continue
        emprise = [_borne(min(emp[0], emp[1]), piece[0], piece[1]), _borne(max(emp[0], emp[1]), piece[0], piece[1]),
                   _borne(min(emp[2], emp[3]), piece[2], piece[3]), _borne(max(emp[2], emp[3]), piece[2], piece[3])]
        hauteur = [_borne(min(hau), 0.0, plafond), _borne(max(hau), 0.0, plafond)]
        if genre in MURAUX and dehors:
            pass                              # sur une façade, quand tous les bâtiments sont lus (plus bas)
        elif genre in MURAUX:
            emprise, hauteur = _au_mur(emprise, hauteur, genre, piece, plafond)
        else:
            emprise = _adosse(emprise, piece, genre)
            if genre in PLATS:
                hauteur[1] = hauteur[0] + 0.02
            if hauteur[1] - hauteur[0] < 0.02:
                hauteur[1] = hauteur[0] + 0.02
            # la caméra : aucun meuble dessus (un tapis passe dessous)
            px, pz = _borne(0.0, emprise[0], emprise[1]), _borne(0.0, emprise[2], emprise[3])
            if genre not in PLATS and math.hypot(px, pz) < CAMERA_LIBRE:
                remarques.append("%s : à moins de %.2f m de la caméra, écarté." % (nom, CAMERA_LIBRE))
                continue
        if emprise[1] - emprise[0] < 0.02 or emprise[3] - emprise[2] < 0.02:
            remarques.append("%s : hors de la pièce, écarté." % nom)
            continue
        while nom in noms:
            nom += "_2"
        noms.add(nom)
        elements.append({"nom": nom, "genre": genre, "description": description,
                         "emprise": [round(v, 3) for v in emprise], "hauteur": [round(v, 3) for v in hauteur]})
        if len(elements) >= ELEMENTS_MAX:
            remarques.append("Plus de %d éléments : la suite est laissée de côté." % ELEMENTS_MAX)
            break
    batiments = [e for e in elements if e["genre"] == "batiment"]
    for e in (e for e in elements if dehors and e["genre"] in MURAUX):
        if batiments:
            emprise, hauteur, e["dos"], e["facade"] = _a_la_facade(e["emprise"], e["hauteur"], e["genre"], batiments)
        else:
            emprise, hauteur = _au_mur(e["emprise"], e["hauteur"], e["genre"], piece, plafond)
        e.update(emprise=[round(v, 3) for v in emprise], hauteur=[round(v, 3) for v in hauteur])
    # une pièce vide est un plan (photo d'agence, décor nu) : les murs nus ont leurs cartes
    plan = {"piece": [round(v, 3) for v in piece], "plafond": round(plafond, 3),
            "murs": _phrase(d.get("murs"), 300) or "plain painted walls", "elements": elements}
    if dehors:
        plan["dehors"] = True
    return plan, remarques


# --- La proposition du chat : ce que la photo montre (cadres) + ce qu'il imagine (mètres) -----------------------

def _rayon(geo, u, v):
    """Direction dans la pièce (y vers le bas) du pixel (u, v) de la photo."""
    w, h = geo["taille"]
    dc = ((u - w / 2) / geo["fx"], (v - h / 2) / geo["fx"], 1.0)
    R = geo["R"]
    return [sum(R[i][j] * dc[j] for j in range(3)) for i in range(3)]


def _vers_photo(geo, p):
    """Point de la pièce (y vers le bas) -> (u, v, profondeur) dans la photo."""
    R = geo["R"]
    dc = [sum(R[i][j] * p[i] for i in range(3)) for j in range(3)]
    w, h = geo["taille"]
    z = dc[2]
    return (geo["fx"] * dc[0] / z + w / 2 if z > 1e-6 else None,
            geo["fx"] * dc[1] / z + h / 2 if z > 1e-6 else None, z)


def _plan_du_mur(cote, piece):
    x0, x1, z0, z1 = piece
    return {"x-": (0, x0), "x+": (0, x1), "z-": (2, z0), "z+": (2, z1)}[cote]


def _touche_mur(d, piece):
    """Le mur que touche d'abord le rayon (horizontalement) : son côté."""
    meilleur, cote = None, "z+"
    for c in ("x-", "x+", "z-", "z+"):
        axe, val = _plan_du_mur(c, piece)
        if abs(d[axe]) > 1e-9 and val / d[axe] > 0:
            t = val / d[axe]
            if meilleur is None or t < meilleur:
                meilleur, cote = t, c
    return cote


def _cadre_px(cadre, geo):
    w, h = geo["taille"]
    vals = [_nombre(c, 0.0) for c in cadre]
    if all(0.0 <= v <= 1.0 for v in vals):        # rendu en fractions 0-1 au lieu de 0-1000
        vals = [v * 1000 for v in vals]
    u0, v0, u1, v1 = (_borne(v, 0, 1000) / 1000 for v in vals)
    return min(u0, u1) * w, max(u0, u1) * w, min(v0, v1) * h, max(v0, v1) * h


def _sous_cadre(cadre, geo, grille):
    """Les indices de la grille au cœur du cadre (5 % de marge par côté), avec leur distance à la caméra."""
    w, h = geo["taille"]
    u0, u1, v0, v1 = _cadre_px(cadre, geo)
    mu, mv = 0.05 * (u1 - u0), 0.05 * (v1 - v0)
    gl, gh = grille["l"], grille["h"]
    res = {}
    for k, p in enumerate(grille["points"]):
        if p is None:
            continue
        u, v = (k % gl + 0.5) * w / gl, (k // gl + 0.5) * h / gh
        if u0 + mu <= u <= u1 - mu and v0 + mv <= v <= v1 - mv:
            res[k] = math.hypot(p[0], p[2])
    return res


def partage_des_cadres(cadres: dict, geo: dict, grille: dict) -> dict:
    """{clé: cadre} des meubles -> {clé: indices exclus}. Les cadres du chat se chevauchent (la table devant le
    canapé, le canapé devant la bibliothèque) : un point de plusieurs cadres va à l'élément dont les points à lui
    seul sont à la distance la plus proche de la sienne (06/10, salon de Leila : sans ce partage, la bibliothèque
    prenait le dos du canapé et s'avançait d'1 m)."""
    sous = {n: _sous_cadre(c, geo, grille) for n, c in cadres.items()}
    compte = {}
    for s in sous.values():
        for k in s:
            compte[k] = compte.get(k, 0) + 1
    repere = {}
    for n, s in sous.items():
        propres = [d for k, d in s.items() if compte[k] == 1] or list(s.values())
        repere[n] = _centile(propres, 0.5) if propres else None
    exclus = {n: set() for n in cadres}
    for k, c in compte.items():
        if c < 2:
            continue
        dans = [n for n, s in sous.items() if k in s and repere[n] is not None]
        if not dans:
            continue
        d = sous[dans[0]][k]
        garde = min(dans, key=lambda n: abs(repere[n] - d))
        for n in dans:
            if n != garde:
                exclus[n].add(k)
    return exclus


def _plus_gros_amas(xs, zs, hs, pas=0.2):
    """Les points du plus gros amas d'un seul tenant vu de dessus (cases de `pas` m, voisines par les 8 côtés) :
    un cadre du chat déborde de l'objet (06/10, Leila : la table jusqu'au bord droit de la photo, la bibliothèque
    avec un bout du dossier du canapé à 2 m devant elle)."""
    cases = {}
    for i, (x, z) in enumerate(zip(xs, zs)):
        cases.setdefault((math.floor(x / pas), math.floor(z / pas)), []).append(i)
    vu, meilleur = set(), []
    for depart in cases:
        if depart in vu:
            continue
        pile, amas = [depart], []
        vu.add(depart)
        while pile:
            c = pile.pop()
            amas += cases[c]
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    v = (c[0] + dx, c[1] + dz)
                    if v in cases and v not in vu:
                        vu.add(v)
                        pile.append(v)
        if len(amas) > len(meilleur):
            meilleur = amas
    return [xs[i] for i in meilleur], [zs[i] for i in meilleur], [hs[i] for i in meilleur]


def depuis_cadre(cadre, genre: str, geo: dict, grille: dict, piece, exclus=()):
    """L'emprise et la hauteur d'un élément que la photo montre, depuis son cadre (0-1000 sur la largeur et la
    hauteur de la photo) : les points MoGe sous le cadre pour un meuble (sauf `exclus`, ceux d'un autre élément,
    partage_des_cadres) ; les rayons des bords coupés par le mur pour un élément mural (une baie laisse voir le
    jardin : ses points sont dehors)."""
    w, h = geo["taille"]
    u0, u1, v0, v1 = _cadre_px(cadre, geo)
    hc = geo["hauteur"]
    if genre in MURAUX:
        um, vm = (u0 + u1) / 2, (v0 + v1) / 2
        cote = _touche_mur(_rayon(geo, um, vm), piece)
        axe, val = _plan_du_mur(cote, piece)
        long = 2 if axe == 0 else 0
        pts = []
        for u, v in ((u0, vm), (u1, vm), (um, v0), (um, v1)):
            d = _rayon(geo, u, v)
            t = val / d[axe] if abs(d[axe]) > 1e-9 and val / d[axe] > 0 else None
            pts.append(None if t is None else [t * c for c in d])
        if None in pts:
            return None
        a0, a1 = sorted((pts[0][long], pts[1][long]))
        haut, bas = hc - pts[2][1], hc - pts[3][1]
        if genre in ("porte", "ouverture", "baie"):
            # elle part du sol ; coupée par le haut de la photo, elle a au moins sa hauteur ordinaire (06/10,
            # Leila : la baie à 3 dm du mur gauche, vue de 0,85 à 1,66 m seulement)
            bas = 0.0
            if v0 <= 0.02 * h:
                haut = max(haut, DEFAUT[genre][2])
        haut = min(haut, geo["plafond"])
        ep = DEFAUT[genre][1]
        if axe == 0:
            emprise = [val, val + ep] if cote == "x-" else [val - ep, val]
            emprise += [a0, a1]
        else:
            emprise = [a0, a1] + ([val, val + ep] if cote == "z-" else [val - ep, val])
        return emprise, [max(0.0, bas), haut]
    # un meuble : les points mesurés au cœur du cadre, hors des murs vus
    mu, mv = 0.05 * (u1 - u0), 0.05 * (v1 - v0)
    gl, gh = grille["l"], grille["h"]
    xs, zs, hs = [], [], []
    for k, p in enumerate(grille["points"]):
        if p is None or k in exclus:
            continue
        u, v = (k % gl + 0.5) * w / gl, (k // gl + 0.5) * h / gh
        if not (u0 + mu <= u <= u1 - mu and v0 + mv <= v <= v1 - mv):
            continue
        x, y, z = p
        haut = hc - y
        if (haut > 0.1) if genre in PLATS else (haut < 0.03):
            continue
        if min(abs(x - piece[0]), abs(x - piece[1]), abs(z - piece[3])) < 0.08:
            continue
        xs.append(x)
        zs.append(z)
        hs.append(haut)
    if len(xs) >= 4:
        xs, zs, hs = _plus_gros_amas(xs, zs, hs)
    if len(xs) >= 4:
        e = [_centile(xs, 0.03), _centile(xs, 0.97), _centile(zs, 0.03), _centile(zs, 0.97)]
        # MoGe ne voit que la face tournée vers la caméra : la profondeur manquante s'ajoute À L'OPPOSÉ de la
        # caméra, le long de l'axe où l'élément s'en éloigne le plus
        pmin = 0.7 * DEFAUT[genre][1]
        cx, cz = (e[0] + e[1]) / 2, (e[2] + e[3]) / 2
        if abs(cz) >= abs(cx):
            if e[3] - e[2] < pmin:
                e[2], e[3] = (e[2], e[2] + pmin) if cz > 0 else (e[3] - pmin, e[3])
        elif e[1] - e[0] < pmin:
            e[0], e[1] = (e[0], e[0] + pmin) if cx > 0 else (e[1] - pmin, e[1])
        # posé au sol : le bas vu n'est que ce qu'un meuble de devant laisse voir (06/10, Leila : canapé à 0,27 m)
        return e, [0.0, _centile(hs, 0.97)]
    # trop peu de points : le bas du cadre touche le sol
    d = _rayon(geo, (u0 + u1) / 2, v1)
    if d[1] <= 1e-6:
        return None
    t = hc / d[1]
    x, z = d[0] * t, d[2] * t
    L, P, H = DEFAUT[genre]
    return [x - L / 2, x + L / 2, z, z + P], [0.0, H]


def lire_proposition(reponse: str, geo: dict, grille: dict):
    """La proposition du chat (CONSIGNE_PLAN) -> (plan, remarques)."""
    d = _json_de(reponse)
    if not isinstance(d, dict):
        raise ValueError("Plan illisible : pas d'objet JSON.")
    x0, x1, _z0, z1 = geo["piece"]
    fond = _borne(_nombre(d.get("fond_z"), geo["piece"][2]), -8.0, -0.8)
    piece = [x0, x1, fond, z1]
    elements, remarques = [], []
    bruts = [e for e in d.get("elements") or [] if isinstance(e, dict)]
    a_cadre = [isinstance(e.get("cadre"), list) and len(e["cadre"]) == 4 for e in bruts]
    for i, e in enumerate(bruts):
        # 06/10, Leila : une baie rendue avec le cadre de toute la photo ne se mesure pas, elle se signale ;
        # un meuble peut, lui, remplir la photo (un lit vu de près)
        if a_cadre[i] and e.get("genre") in MURAUX:
            u0, u1, v0, v1 = _cadre_px(e["cadre"], geo)
            if (u1 - u0) * (v1 - v0) > CADRE_MAX * geo["taille"][0] * geo["taille"][1]:
                a_cadre[i] = False
                remarques.append("%s : cadre sur presque toute la photo, place à préciser." % _nom(e.get("nom")))
    exclus = partage_des_cadres({i: e["cadre"] for i, e in enumerate(bruts)
                                 if a_cadre[i] and e.get("genre") not in MURAUX}, geo, grille)
    for i, e in enumerate(bruts):
        genre = e.get("genre") if e.get("genre") in GENRES else "objet"
        cadre = e.get("cadre")
        place = None
        if a_cadre[i]:
            place = depuis_cadre(cadre, genre, geo, grille, piece, exclus.get(i, ()))
            if place is None:
                remarques.append("%s : cadre sans mesure possible." % _nom(e.get("nom")))
        if place is None:
            x, z = _nombre(e.get("x")), _nombre(e.get("z"))
            if x is None or z is None:
                remarques.append("%s : sans place (ni cadre mesurable ni x, z), écarté." % _nom(e.get("nom")))
                continue
            L, P, H = DEFAUT[genre]
            L, P = _nombre(e.get("largeur"), L), _nombre(e.get("profondeur"), P)
            H = _nombre(e.get("hauteur"), H)
            bas = _nombre(e.get("bas"), BAS_DEFAUT.get(genre, 0.0))
            place = [x - L / 2, x + L / 2, z - P / 2, z + P / 2], [bas, bas + H]
        elements.append({"nom": e.get("nom"), "genre": genre, "description": e.get("description"),
                         "emprise": place[0], "hauteur": place[1]})
    plan, r = lire_plan({"piece": piece, "plafond": geo["plafond"], "murs": d.get("murs"), "elements": elements}, geo)
    return plan, remarques + r


def _json_de(reponse: str):
    texte = str(reponse or "")
    m = re.search(r"```(?:json)?\s*(.*?)```", texte, re.S)
    if m:
        texte = m.group(1)
    debut = texte.find("{")
    if debut < 0:
        raise ValueError("Plan illisible : le chat n'a pas rendu de JSON.")
    try:
        return json.loads(texte[debut:texte.rfind("}") + 1])
    except ValueError as exc:
        raise ValueError("Plan illisible : %s" % exc) from exc


def _liste_genres() -> str:
    return "; ".join("%s = %s" % kv for kv in GENRES.items())


CONSIGNE_PLAN = (
    "The attached photo shows a place (a film set), described by its owner as: « %s ». It was measured: the camera "
    "stands at x = 0, z = 0, %.2f m above the floor; left wall at x = %.2f, right wall at x = %.2f, front wall at "
    "z = %.2f; ceiling %.2f m; the photo looks %s. The room continues BEHIND the camera (z < 0) up to a back wall "
    "you choose. Imagine the FLOOR PLAN of the whole room, behind the camera included, faithful to the photo and the "
    "description. Answer with JSON only: {\"murs\": \"<one English sentence: walls, floor and ceiling, materials "
    "and colours>\", \"fond_z\": <z of the back wall, between -6 and -1>, \"elements\": [...]}. Each element: "
    "{\"nom\": \"<short id, lowercase>\", \"genre\": \"<one of: %s>\", \"description\": \"<one English sentence so "
    "that a video model redraws it exactly: material, colour, shape>\"} plus, when the photo shows it, \"cadre\": "
    "[left, top, right, bottom] its box in the photo (0-1000 across the width and the height); otherwise \"x\", "
    "\"z\" (its centre, metres), \"largeur\" (size along x), \"profondeur\" (size along z), \"hauteur\" (metres), "
    "and \"bas\" for a window or a painting (height of its bottom edge). Doors, doorways, windows, glass walls and "
    "paintings touch a wall. Every piece of furniture, every opening, at most %d elements; nothing closer than "
    "0.6 m to the camera.")

CONSIGNE_RETOUCHE = (
    "Here is the floor plan of a room, as JSON. Metres; x to the right, z forward, the camera at x = 0, z = 0; "
    "\"piece\" = [left wall x, right wall x, back wall z, front wall z]; each element's \"emprise\" = [x0, x1, z0, "
    "z1] and \"hauteur\" = [bottom, top] above the floor; genres: %s.\n%s\nThe owner asks: « %s ». Apply exactly "
    "this change and nothing else; keep the names of the elements that stay. Answer with the whole plan as JSON "
    "only, in the same format.")


def consigne_plan(description: str, geo: dict) -> str:
    cap = geo["lacet"]
    sens = "straight ahead (towards +z)" if abs(cap) < 3 else "%.0f degrees to the %s of +z" % (
        abs(cap), "right" if cap > 0 else "left")
    x0, x1, _z0, z1 = geo["piece"]
    return CONSIGNE_PLAN % (_phrase(description, 1400), geo["hauteur"], x0, x1, z1, geo["plafond"], sens,
                            ", ".join(GENRES), ELEMENTS_MAX)


def consigne_retouche(plan: dict, message: str) -> str:
    return CONSIGNE_RETOUCHE % (_liste_genres(), json.dumps(plan, ensure_ascii=False), _phrase(message, 600))


# --- Relecture du plan avant le client (propriétaire, 06/10 : « an agent that check if the 2d floor ------------
# implementation from text is ok ») : des constats calculés, puis le chat relit plan, texte et photo ------------

CHEVAUCHEMENT_MIN = 0.04  # m² : deux meubles qui se recouvrent plus que ça au sol sont un défaut
PASSAGE = 0.6             # m : devant une porte, une ouverture ou une baie, la place pour passer
RELECTURE_MAX = 10        # problèmes gardés de la relecture
RELECTURES_MAX = 2        # passes du relecteur : la seconde seulement si le plan corrigé garde des défauts
CAMERA_AU_MUR = 1.0       # m : sans photo, la caméra à moins de ça d'un mur tourne le dos à un mur (06/10, revue)
MUR_GARNI = 0.25          # part d'un mur le long de laquelle quelque chose se tient, sous laquelle il est « nu »
COTES = {"x-": "left wall", "x+": "right wall", "z-": "back wall (behind the camera)", "z+": "front wall"}


def _recouvrement(a, b) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[2], b[2]))


def _passage(e, piece):
    """L'aire devant un élément mural qu'on traverse (porte, ouverture, baie), côté pièce."""
    x0, x1, z0, z1 = e["emprise"]
    cote = _cote(e, piece)
    return {"x-": [x1, x1 + PASSAGE, z0, z1], "x+": [x0 - PASSAGE, x0, z0, z1],
            "z-": [x0, x1, z1, z1 + PASSAGE], "z+": [x0, x1, z0 - PASSAGE, z0]}[cote]


def cadre_vu(e: dict, plan: dict, geo: dict):
    """Où l'élément du plan tombe sur la photo : [gauche, haut, droite, bas] en 0-1000, ou None s'il n'y est pas."""
    w, h = geo["taille"]
    us, vs = [], []
    for p in coins(e, plan, geo["hauteur"]):
        u, v, prof = _vers_photo(geo, list(p))
        if prof > 0.05:
            us.append(u)
            vs.append(v)
    if not us or max(us) < 0 or min(us) > w or max(vs) < 0 or min(vs) > h:
        return None
    return [round(_borne(min(us) / w, 0, 1) * 1000), round(_borne(min(vs) / h, 0, 1) * 1000),
            round(_borne(max(us) / w, 0, 1) * 1000), round(_borne(max(vs) / h, 0, 1) * 1000)]


def pose_sur(a: dict, b: dict) -> bool:
    """a est posé sur b (son bas au haut de b, à 5 cm près) : leur recouvrement au sol n'est pas un défaut."""
    return a["hauteur"][0] >= b["hauteur"][1] - 0.05


def _sous_table(chaise: dict, table: dict, s: float) -> bool:
    """Une chaise glissée sous une table (moins de la moitié de son assise dessous) : la place ordinaire d'une chaise
    (06/10, validation : cuisine, chaises de la table à manger comptées en recouvrement)."""
    x0, x1, z0, z1 = chaise["emprise"]
    return chaise["genre"] == "chaise" and table["genre"] == "table" and s < 0.5 * (x1 - x0) * (z1 - z0)


def defauts(plan: dict, geo: dict) -> list:
    """Les constats qui sont des défauts (la place dans la vue de face et ce qui est posé sur une surface se jugent,
    ce ne sont pas des défauts)."""
    return [c for c in constats(plan, geo) if "front view" not in c
            and "on the flat surface" not in c and "is bare" not in c]


def _garni(plan: dict, cote: str) -> float:
    """La part du mur (ou du bord de la scène) le long de laquelle un élément se tient à moins d'1 m."""
    x0, x1, z0, z1 = plan["piece"]
    le_long_x = cote in ("z-", "z+")
    a0, a1 = (x0, x1) if le_long_x else (z0, z1)
    morceaux = []
    for e in plan["elements"]:
        if e["genre"] in PLATS:
            continue
        ex0, ex1, ez0, ez1 = e["emprise"]
        ecart = {"x-": ex0 - x0, "x+": x1 - ex1, "z-": ez0 - z0, "z+": z1 - ez1}[cote]
        if ecart < 1.0:
            morceaux.append((ex0, ex1) if le_long_x else (ez0, ez1))
    couvert, fin = 0.0, a0
    for m0, m1 in sorted(morceaux):
        m0, m1 = max(m0, fin), min(m1, a1)
        if m1 > m0:
            couvert += m1 - m0
            fin = m1
    return couvert / max(a1 - a0, 1e-6)


def constats(plan: dict, geo: dict) -> list:
    """Ce qui se calcule sans regarder : recouvrements, passages bouchés, hauteurs, place sur la photo. En anglais
    pour la relecture ; chaque ligne commence par le nom de l'élément."""
    els, piece, res = plan["elements"], plan["piece"], []
    meubles = [e for e in els if e["genre"] not in MURAUX and e["genre"] not in PLATS]
    for i, a in enumerate(meubles):
        for b in meubles[i + 1:]:
            if pose_sur(a, b) or pose_sur(b, a):
                continue                      # un trône sur son estrade, un vase sur la table
            s = _recouvrement(a["emprise"], b["emprise"])
            if s > CHEVAUCHEMENT_MIN and not (_sous_table(a, b, s) or _sous_table(b, a, s)):
                res.append("%s and %s overlap on the floor by %.2f m2." % (a["nom"], b["nom"], s))
    # dehors, sur l'eau ou le sable : à juger, pas un défaut (06/10 : palmiers dans la mer, rochers dans le lac)
    for s in (e for e in els if e["genre"] == "surface"):
        for m in meubles:
            if _recouvrement(s["emprise"], m["emprise"]) > CHEVAUCHEMENT_MIN:
                res.append("%s stands on the flat surface %s (fine on sand, grass or a path; wrong in water)."
                           % (m["nom"], s["nom"]))
    for p in (e for e in els if e["genre"] in ("porte", "ouverture", "baie")):
        zone = _passage(p, piece)
        for m in meubles:
            if _recouvrement(zone, m["emprise"]) > CHEVAUCHEMENT_MIN:
                res.append("%s stands in front of %s and blocks the way through." % (m["nom"], p["nom"]))
    for e in els:
        if (not plan.get("dehors") and e["hauteur"][1] > plan["plafond"] - 0.02
                and e["genre"] not in ("porte", "ouverture", "baie", "colonne", "escalier")):
            res.append("%s reaches the ceiling (%.2f m)." % (e["nom"], e["hauteur"][1]))
        vu = cadre_vu(e, plan, geo)
        res.append("%s: %s." % (e["nom"], "in the front view at [%d, %d, %d, %d]" % tuple(vu) if vu
                                       else "outside the front view (fine: the camera turns 360 degrees)"))
    dehors = plan.get("dehors")
    if not dehors and not any(e["genre"] in ("porte", "ouverture", "baie") for e in els):
        res.append("room: no door, opening or glass door; the camera turns 360 degrees, add one where the place is "
                   "entered.")
    x0, x1, z0, z1 = piece
    if geo.get("texte"):                      # sans photo, la place de la caméra est un choix du plan
        loin = {"x-": -x0, "x+": x1, "z-": -z0, "z+": z1}
        besoin = dict.fromkeys(loin, CAMERA_AU_MUR)
        besoin["z-"] = max(CAMERA_AU_MUR, 0.25 * (z1 - z0))
        for c in loin:
            if loin[c] < besoin[c] - 0.01:
                res.append("camera: only %.1f m from the %s; it turns 360 degrees and must stand at least %.1f m "
                           "from it: move the %s (and what stands against it) away." % (
                               loin[c], COTES[c], besoin[c], COTES[c].split(" (")[0]))
    vus = set()
    for cap, dedans in trop_pleines(cartes_du_plan(plan, geo), fenetre_clip(geo)):
        noms = sorted(m["nom"] for c in dedans for m in (c.get("membres") or [c]) if not c.get("mur_nu"))
        if tuple(noms) in vus:
            continue
        vus.add(tuple(noms))
        res.append("clip around heading %d: %d cards in view even after grouping neighbours (the video model takes "
                   "%d): move apart, merge or remove some of %s." % (cap, len(dedans), SUJETS_MAX, ", ".join(noms)))
        if len(vus) >= 3:
            break
    for c, mur in COTES.items():
        if _garni(plan, c) < MUR_GARNI:
            res.append("%s is bare (nothing stands along it; fine only if intended)." % (
                mur.replace("wall", "edge of the scene") if dehors else mur))
    return res


CONSIGNE_RELECTURE = (
    "You check the floor plan of a room before its owner sees it. The owner described the place as: « %s ».%s "
    "Metres; x to the right, z forward, the camera at x = 0, z = 0 looking along +z (far in front = large z, behind "
    "the camera = negative z, left = negative x); \"piece\" = [left wall x, right wall x, back wall z, front wall z] "
    "(with \"dehors\": true, an outdoor place: no ceiling, \"piece\" bounds the scene and \"murs\" says what closes "
    "the view); \"emprise\" = [x0, x1, z0, z1] on the floor, \"hauteur\" = [bottom, top] above the floor; genres: "
    "%s.\nPlan: %s\nComputed facts (\"in the front view at [left, top, right, bottom]\" = where the element falls in "
    "the camera's first view, 0-1000):\n%s\nCheck: every object the description names%s is in the plan, at the "
    "right place and size, facing a sensible way; nothing contradicts the description%s; no overlap, no blocked "
    "door, real sizes; the place is filled all around (the camera turns 360 degrees). Every computed fact other "
    "than the place in the front view is a defect: fix each one in the plan (move or resize an element; water, a "
    "path or sand is a flat \"surface\"; a thing standing on another starts at that one's top); \"ok\": true only "
    "when no defect remains or a problem sentence says why it is intended. Then make the place believable: ADD what "
    "such a place plainly has even if the description does not name it (a harbour has bollards and moored boats, an "
    "office a waste bin and a coat stand), REMOVE what does not belong there; at most %d elements; one problem "
    "sentence per addition or removal; \"ok\": false whenever you add or remove.%s Answer with JSON only: {\"ok\": true or false, "
    "\"problemes\": [\"<one short sentence IN FRENCH per problem found>\"], \"plan\": <the whole corrected plan, "
    "same format, same names for what stays; or null when ok>}.")


def consigne_relecture(description: str, plan: dict, geo: dict, avec_photo: bool) -> str:
    photo = (" The attached photo is the camera's front view; what it shows is measured, keep it unless the facts "
             "show the element is not where the photo shows it.") if avec_photo else ""
    return CONSIGNE_RELECTURE % (_phrase(description, 1400), photo, _liste_genres(),
                                 json.dumps(plan, ensure_ascii=False), "\n".join(constats(plan, geo)),
                                 " or the photo shows" if avec_photo else "", " or the photo" if avec_photo else "",
                                 ELEMENTS_MAX, " Never add in the front view what the photo does not show."
                                 if avec_photo else "")


CAMERA_TEXTE = 1.6        # m : hauteur d'œil d'un plan sans photo
CONSIGNE_PLAN_TEXTE = (
    "A film set must be built from this description only (no photo): « %s ». Imagine its FLOOR PLAN as seen from "
    "where the camera stands, at x = 0, z = 0, eye height %.1f m, looking along +z (far in front = large z, behind "
    "the camera = negative z, left = negative x). Choose the size of the place: indoors, its walls and ceiling; "
    "outdoors (\"dehors\": true, only under the open sky; a cave, a hall, a tunnel are indoors), no ceiling, and "
    "\"piece\" bounds what the camera sees around it. The camera stands near the middle of the place, at least %.1f m "
    "from every wall and with a quarter of the depth behind it: it turns 360 degrees. Indoors, the place has a door "
    "or an opening where it is entered. Each tree, rock, house or column is its own element, never one "
    "element for a group; what is far away and closes the view goes in \"murs\". Doors and windows of a building "
    "outdoors touch its facade. A thing standing on another (a throne on a dais) has \"bas\" at that one's top. Add "
    "what such a place plainly has even if the description does not name it (a harbour has bollards and moored "
    "boats, an office a waste bin and a coat stand). Put the most "
    "important things in front of the camera, but fill all around: the camera turns 360 degrees. Answer with JSON "
    "only: {\"dehors\": true or false, \"piece\": [left wall x, right wall x, back wall z, front wall z], "
    "\"plafond\": <ceiling height in metres, or null outdoors>, \"murs\": \"<one English sentence: indoors the walls, "
    "floor and ceiling, materials and colours; outdoors the ground and what closes the view all around>\", "
    "\"elements\": [...]}. Each element: {\"nom\": \"<short id, lowercase>\", \"genre\": \"<one of: %s>\", "
    "\"description\": \"<one English sentence so that a video model redraws it exactly: material, colour, shape>\", "
    "\"x\", \"z\" (its centre), \"largeur\" (its width along the wall it stands against, or along x when it stands "
    "free), \"profondeur\" (its depth from that wall into the place, or along z), \"hauteur\" (metres), and "
    "\"bas\" for a window, a painting or a thing standing on another (height of its bottom edge)}. Doors, windows and paintings touch a wall. "
    "Real sizes; at most %d elements; nothing closer than 0.6 m to the camera.")


def consigne_plan_texte(description: str) -> str:
    return CONSIGNE_PLAN_TEXTE % (_phrase(description, 1400), CAMERA_TEXTE, CAMERA_AU_MUR, _liste_genres(),
                                  ELEMENTS_MAX)


def geo_du_texte(piece, plafond, dehors=False) -> dict:
    """Le repère d'un lieu sans photo (PLAN 21.6 étape 6) : caméra de niveau à CAMERA_TEXTE, regardant +z ; la
    taille et le champ sont ceux des clés de H3 (1344 × 768, fx 756)."""
    return {"R": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], "hauteur": CAMERA_TEXTE,
            "plafond": CIEL if dehors else plafond, "piece": piece, "lacet": 0.0, "tangage": 0.0, "fx": 756.0,
            "taille": [1344, 768], "retraits": [0.025] * 4, "dehors": bool(dehors), "texte": True}


def recaler_geo(geo: dict, plan: dict) -> dict:
    """Sans photo, le repère suit le plan : la relecture ou le client qui déplacent les murs les déplacent aussi
    pour le dessin (06/10, revue : plage relue à -8 m, repère resté à -2 m)."""
    if geo.get("texte"):
        geo.update(piece=list(plan["piece"]), plafond=CIEL if plan.get("dehors") else plan["plafond"],
                   dehors=bool(plan.get("dehors")))
    return geo


def lire_texte(reponse: str):
    """La proposition du chat sans photo (CONSIGNE_PLAN_TEXTE) -> (plan, geo, remarques)."""
    d = _json_de(reponse)
    if not isinstance(d, dict):
        raise ValueError("Plan illisible : pas d'objet JSON.")
    dehors = d.get("dehors") is True
    p = d.get("piece") if isinstance(d.get("piece"), list) and len(d["piece"]) == 4 else [-4, 4, -4, 6]
    p = [_nombre(v, g) for v, g in zip(p, (-4.0, 4.0, -4.0, 6.0))]
    piece = [_borne(min(p[0], p[1]), -PIECE_MAX, -0.3), _borne(max(p[0], p[1]), 0.3, PIECE_MAX),
             _borne(min(p[2], p[3]), -PIECE_MAX, -0.5), _borne(max(p[2], p[3]), 0.5, PIECE_MAX)]
    plafond = _borne(_nombre(d.get("plafond"), 2.7), CAMERA_TEXTE + 0.5, PLAFOND_MAX)
    geo = geo_du_texte(piece, plafond, dehors)
    elements, remarques = [], []
    for e in d.get("elements") or []:
        if not isinstance(e, dict):
            continue
        genre = e.get("genre") if e.get("genre") in GENRES else "objet"
        x, z = _nombre(e.get("x")), _nombre(e.get("z"))
        if x is None or z is None:
            remarques.append("%s : sans place (x, z), écarté." % _nom(e.get("nom")))
            continue
        L, P, H = DEFAUT[genre]
        L, P = _nombre(e.get("largeur"), L), _nombre(e.get("profondeur"), P)
        H = _nombre(e.get("hauteur"), H)
        bas = _nombre(e.get("bas"), BAS_DEFAUT.get(genre, 0.0))
        # la largeur court le long du mur contre lequel il se tient (06/10, revue : un lit contre le mur de gauche
        # pris en travers de la pièce, une porte de côté large de 10 cm)
        cote = dos([x, x, z, z], piece)
        ecart = {"x-": x - piece[0], "x+": piece[1] - x, "z-": z - piece[2], "z+": piece[3] - z}[cote]
        if cote in ("x-", "x+") and (genre in MURAUX or ecart < max(L, P) / 2 + COLLE_AU_MUR):
            L, P = P, L
        elements.append({"nom": e.get("nom"), "genre": e.get("genre"), "description": e.get("description"),
                         "emprise": [x - L / 2, x + L / 2, z - P / 2, z + P / 2], "hauteur": [bas, bas + H]})
    plan, r = lire_plan({"piece": piece, "plafond": plafond, "murs": d.get("murs"), "dehors": dehors,
                         "elements": elements}, geo)
    return plan, geo, remarques + r


def lire_relecture(reponse: str, geo: dict):
    """La réponse de la relecture -> (problèmes, plan corrigé ou None, remarques). ValueError si illisible."""
    d = _json_de(reponse)
    if not isinstance(d, dict):
        raise ValueError("Relecture illisible : pas d'objet JSON.")
    problemes = [_phrase(p, 200) for p in (d.get("problemes") or []) if _phrase(p, 200)][:RELECTURE_MAX]
    if d.get("ok") is True or not isinstance(d.get("plan"), dict):
        return problemes, None, []
    plan, remarques = lire_plan(d["plan"], geo)
    return problemes, plan, remarques


# --- Ce que voit la caméra : azimuts des éléments, cartes, texte du panorama ------------------------------------

def coins(e: dict, plan: dict, hauteur_cam: float) -> list:
    """Les coins (x, y vers le bas, z) des parties de l'élément."""
    pts = []
    for _, (x0, x1, z0, z1, b, h) in parties(e, plan["piece"]):
        pts += [(x, hauteur_cam - y, z) for x in (x0, x1) for y in (b, h) for z in (z0, z1)]
    return pts


def _ecart(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def etendue(e: dict, plan: dict, geo: dict) -> dict:
    """{a0, a1 (caps du panorama, a1 >= a0), haut, bas (site en degrés, borné à SITE_MAX)}."""
    pts = coins(e, plan, geo["hauteur"])
    az = [math.degrees(math.atan2(x, z)) - geo["lacet"] for x, _, z in pts]
    ref = az[0]
    az = [ref + _ecart(a, ref) for a in az]
    site = [_borne(math.degrees(math.atan2(-y, math.hypot(x, z))), -SITE_MAX, SITE_MAX) for x, y, z in pts]
    a0 = _ecart(min(az), 0.0)
    return {"a0": round(a0, 1), "a1": round(a0 + min(max(az) - min(az), 359.0), 1),
            "haut": round(max(site), 1), "bas": round(min(site), 1)}


def fenetre_clip(geo: dict) -> float:
    """Les degrés de panorama que voit un clip du tour : son pas plus un champ de clé."""
    fx = geo["fx"] * VUE_L / geo["taille"][0]
    return 2 * math.degrees(math.atan(VUE_L / 2 / fx)) + PAS_CLIP


def _croise(c, cap, demi) -> bool:
    a0 = cap + _ecart(c["a0"], cap)
    return a0 <= cap + demi and a0 + (c["a1"] - c["a0"]) >= cap - demi


def trop_pleines(cartes: list, fenetre: float) -> list:
    """[(cap, cartes vues)] des clips possibles (un cap tous les 7,5°) qui voient plus de SUJETS_MAX cartes."""
    res = []
    for k in range(48):
        dedans = [c for c in cartes if _croise(c, k * 7.5, fenetre / 2)]
        if len(dedans) > SUJETS_MAX:
            res.append((k * 7.5, dedans))
    return res


def _union(a, b):
    a0 = a["a0"]
    b0 = a0 + _ecart(b["a0"], a0)
    u0, u1 = min(a0, b0), max(a["a1"], b0 + b["a1"] - b["a0"])
    return u0, u1


def grouper(cartes: list, fenetre: float) -> list:
    """Tant qu'un clip verrait plus de SUJETS_MAX cartes, les deux cartes voisines les plus serrées d'un clip trop
    plein n'en font qu'une, découpée sur leurs deux étendues (guide Ref2VA : « one reference asset may provide
    multiple subjects » ; propriétaire, 06/10 : « group cards »). Jamais au-delà de GROUPE_MAX degrés ; les murs nus
    restent seuls."""
    cartes, k = list(cartes), 0
    while True:
        meilleur = None
        for cap, dedans in trop_pleines(cartes, fenetre):
            els = sorted((c for c in dedans if not c.get("mur_nu")), key=lambda c: _ecart(c["a0"], cap))
            for a, b in zip(els, els[1:]):
                u0, u1 = _union(a, b)
                if u1 - u0 <= GROUPE_MAX and (meilleur is None or u1 - u0 < meilleur[0]):
                    meilleur = (u1 - u0, a, b, u0, u1)
        if meilleur is None:
            return cartes
        _, a, b, u0, u1 = meilleur
        k += 1
        noms = {c["nom"] for c in cartes}
        while "groupe_%d" % k in noms:
            k += 1
        membres = a.get("membres") or [{"nom": a["nom"], "description": a["description"]}]
        membres = membres + (b.get("membres") or [{"nom": b["nom"], "description": b["description"]}])
        a0 = _ecart(u0, 0.0)
        cartes = [c for c in cartes if c is not a and c is not b] + [{
            "nom": "groupe_%d" % k, "membres": membres,
            "description": "side by side, left to right: " + "; ".join(m["description"].rstrip(". ")
                                                                         for m in membres) + ".",
            "a0": round(a0, 1), "a1": round(a0 + u1 - u0, 1), "haut": max(a["haut"], b["haut"]),
            "bas": min(a["bas"], b["bas"])}]


def cartes_du_plan(plan: dict, geo: dict) -> list:
    """Les cartes du tour : une par élément (nom, description, a0, a1, haut, bas), plus une par long mur nu ; des
    voisines groupées en une quand un clip en verrait plus que H3 n'en prend."""
    cartes = [dict({"nom": e["nom"], "description": e["description"]}, **etendue(e, plan, geo))
              for e in plan["elements"]]
    pris = sorted(((c["a0"] % 360, c["a0"] % 360 + c["a1"] - c["a0"]) for c in cartes
                   if next(e for e in plan["elements"] if e["nom"] == c["nom"])["genre"] not in PLATS))
    trous, fin = [], None
    for a, b in pris:
        if fin is not None and a - fin >= MUR_NU_MIN:
            trous.append((fin, a))
        fin = b if fin is None else max(fin, b)
    if pris and pris[0][0] + 360 - fin >= MUR_NU_MIN:
        trous.append((fin, pris[0][0] + 360))
    if not pris:
        trous = [(0.0, 360.0)]
    k = 0
    for a, b in trous:
        # un long mur nu en plusieurs cartes de 100° au plus : sans carte, H3 y invente une pièce
        n = max(1, math.ceil((b - a - 6) / 100.0))
        pas = (b - a) / n
        for i in range(n):
            k += 1
            a0 = _ecart(a + i * pas + 3, 0.0)
            cartes.append({"nom": "mur_nu_%d" % k, "description": ("the open view: " if plan.get("dehors") else
                                                                   "a stretch of bare wall: ") + plan["murs"],
                           "a0": round(a0, 1), "a1": round(a0 + pas - 6, 1), "haut": 25.0, "bas": -25.0,
                           "mur_nu": True})
    return grouper(cartes, fenetre_clip(geo))


def demi_champ_photo(geo: dict) -> float:
    return math.degrees(math.atan(geo["taille"][0] / 2 / geo["fx"]))


def texte_panorama(piece: str, plan: dict, geo: dict, photo: bool = True) -> str:
    """La consigne du dessin : ce que la photo ne montre pas, élément par élément, de la gauche vers la droite ;
    sans photo (étape 6), tout, en commençant par ce qui est devant."""
    demi = demi_champ_photo(geo)
    cotes = {"front": [], "left": [], "behind": [], "right": []}
    for e in plan["elements"]:
        x = etendue(e, plan, geo)
        milieu = _ecart((x["a0"] + x["a1"]) / 2, 0.0)
        if abs(milieu) <= demi * 0.8:
            if photo:
                continue
            cotes["front"].append(((milieu + 180) % 360, e["description"]))
            continue
        cotes["left" if -135 < milieu < 0 else "right" if 0 < milieu < 135 else "behind"].append(
            (milieu % 360, e["description"]))
    phrases = []
    for cote, debut in (("front", "In front"), ("left", "On the left"), ("behind", "Behind the camera"),
                        ("right", "On the right")):
        if cotes[cote]:
            phrases.append("%s: %s." % (debut, "; ".join(d for _, d in sorted(cotes[cote]))))
    if not photo:
        return ("An equirectangular 360 panorama of %s, following the box layout exactly. %s. %s"
                % (piece, plan["murs"], " ".join(phrases))).strip()
    return ("An equirectangular 360 panorama of %s of <image1>, seen from the same spot, following the box layout "
            "exactly. %s. %s" % (piece, plan["murs"], " ".join(phrases))).strip()


def scene_du_plan(plan: dict, geo: dict) -> dict:
    """Ce que la machine du panorama lance en rayons (repère de la pièce, y vers le BAS) :
    {boites: [[x0, x1, y0, y1, z0, z1]], element: [indice de l'élément de chaque boîte], trous: [[face, a0, a1, y0,
    y1]], piece, plafond} ; face = identifiant de tour360_pano.boite (0 x-, 1 x+, 4 z-, 5 z+)."""
    hc = geo["hauteur"]
    boites, element, trous = [], [], []
    for k, e in enumerate(plan["elements"]):
        for _, (x0, x1, z0, z1, b, h) in parties(e, plan["piece"]):
            boites.append([x0, x1, hc - h, hc - b, z0, z1])
            element.append(k)
        t = trou(e, plan["piece"])
        if t:
            trous.append([{"x-": 0, "x+": 1, "z-": 4, "z+": 5}[t["mur"]], t["a0"], t["a1"], hc - t["haut"],
                          hc - t["bas"]])
    return {"boites": boites, "element": element, "trous": trous, "piece": plan["piece"], "plafond": plan["plafond"]}


# --- Les vues du plan pour le client (SVG) ----------------------------------------------------------------------

COULEURS = {"canape": "#c98", "fauteuil": "#a87", "chaise": "#a87", "table": "#b84", "lit": "#99c",
            "bibliotheque": "#963", "meuble": "#875", "lampe": "#dc6", "plante": "#6a5", "tapis": "#cb9",
            "porte": "#a63", "ouverture": "#555", "fenetre": "#59c", "baie": "#4ad", "tableau": "#c6c",
            "surface": "#8bd"}


def _x(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def svg_dessus(plan: dict, geo: dict, px: float = 70.0) -> str:
    """La vue de dessus : la pièce, chaque élément à sa place (nommé), la caméra et le champ de la photo."""
    x0, x1, z0, z1 = plan["piece"]
    m = 0.6
    w, h = (x1 - x0 + 2 * m) * px, (z1 - z0 + 2 * m) * px
    X = lambda x: (x - x0 + m) * px                     # noqa: E731
    Z = lambda z: (z1 - z + m) * px                     # noqa: E731 -- devant en haut
    s = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.0f %.0f" font-family="sans-serif" font-size="13">'
         % (w, h), '<rect x="0" y="0" width="%.0f" height="%.0f" fill="#f4f1ea"/>' % (w, h),
         '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#fff" stroke="#333" stroke-width="4"/>'
         % (X(x0), Z(z1), (x1 - x0) * px, (z1 - z0) * px)]
    for e in sorted(plan["elements"], key=lambda e: e["genre"] not in PLATS):
        ex0, ex1, ez0, ez1 = e["emprise"]
        c = COULEURS.get(e["genre"], "#888")
        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" fill-opacity="%.2f" stroke="#222"/>'
                 % (X(ex0), Z(ez1), max(2, (ex1 - ex0) * px), max(2, (ez1 - ez0) * px), c,
                    0.35 if e["genre"] in PLATS else 0.85))
        s.append('<text x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                 % (X((ex0 + ex1) / 2), Z((ez0 + ez1) / 2) + 4, _x(e["nom"])))
    demi = math.radians(demi_champ_photo(geo))
    cap = math.radians(geo["lacet"])
    r = 1.2
    pts = [(0, 0), (r * math.sin(cap - demi), r * math.cos(cap - demi)), (r * math.sin(cap + demi),
                                                                          r * math.cos(cap + demi))]
    s.append('<polygon points="%s" fill="#e33" fill-opacity="0.18" stroke="#e33"/>'
             % " ".join("%.1f,%.1f" % (X(a), Z(b)) for a, b in pts))
    s.append('<circle cx="%.1f" cy="%.1f" r="6" fill="#e33"/>' % (X(0), Z(0)))
    s.append('<text x="%.1f" y="%.1f" fill="#e33">caméra</text>' % (X(0) + 9, Z(0) + 16))
    p = plan.get("personnage")
    if p:                                   # le personnage du tour (07/10), à valider avec le plan
        s.append('<circle cx="%.1f" cy="%.1f" r="9" fill="#2a7" stroke="#fff" stroke-width="2"/>' % (X(p["x"]), Z(p["z"])))
        s.append('<text x="%.1f" y="%.1f" fill="#2a7" font-weight="bold">%s</text>'
                 % (X(p["x"]) + 12, Z(p["z"]) + 5, _x(p.get("nom") or "personnage")))
    s.append("</svg>")
    return "\n".join(s)


PERSONNE_RECUL = 0.45      # m : le personnage se tient à ça du bord de son élément, côté caméra


def place_personnage(plan: dict, pres_de):
    """{x, z} : la place du personnage du tour, devant l'élément `pres_de`, au point de son emprise le plus proche
    de la caméra, reculé de PERSONNE_RECUL vers elle (jamais à moins de CAMERA_LIBRE) ; None sans cet élément."""
    e = next((e for e in plan.get("elements") or [] if e["nom"] == pres_de), None)
    if e is None:
        return None
    x0, x1, z0, z1 = e["emprise"]
    px, pz = _borne(0.0, x0, x1), _borne(0.0, z0, z1)
    d = math.hypot(px, pz)
    if d < 1e-6:
        return None
    k = max(CAMERA_LIBRE, d - PERSONNE_RECUL) / d
    return {"x": round(px * k, 3), "z": round(pz * k, 3)}


def _segment(geo, a, b):
    """Le segment a-b (points de la pièce) dans la photo, coupé devant la caméra ; None s'il est derrière."""
    pa, pb = _vers_photo(geo, a), _vers_photo(geo, b)
    près = 0.05
    if pa[2] < près and pb[2] < près:
        return None
    if pa[2] < près or pb[2] < près:
        t = (près - pa[2]) / (pb[2] - pa[2])
        c = [a[i] + (b[i] - a[i]) * t for i in range(3)]
        if pa[2] < près:
            a, pa = c, _vers_photo(geo, c)
        else:
            b, pb = c, _vers_photo(geo, c)
    return pa[0], pa[1], pb[0], pb[1]


def svg_camera(plan: dict, geo: dict) -> str:
    """Les arêtes de la maquette vues par la caméra de la photo, à poser sur la photo (même taille) : le client voit
    si chaque élément tombe sur ce que la photo montre."""
    w, h = geo["taille"]
    hc = geo["hauteur"]
    s = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" font-family="sans-serif" font-size="%d">'
         % (w, h, max(12, w // 60))]
    x0, x1, z0, z1 = plan["piece"]
    sol, haut = hc, hc - plan["plafond"]
    lignes = []
    for y in (sol, haut):
        cs = [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)]
        lignes += [("#fff", cs[i], cs[(i + 1) % 4]) for i in range(4)]
    lignes += [("#fff", (x, sol, z), (x, haut, z)) for x in (x0, x1) for z in (z0, z1)]
    etiquettes = []
    for e in plan["elements"]:
        c = COULEURS.get(e["genre"], "#888")
        for _, (bx0, bx1, bz0, bz1, b, t) in parties(e, plan["piece"]):
            ya, yb = hc - b, hc - t
            for (p, q) in (((0, 0), (1, 0)), ((1, 0), (1, 1)), ((1, 1), (0, 1)), ((0, 1), (0, 0))):
                xa, za = (bx0, bx1)[p[0]], (bz0, bz1)[p[1]]
                xb, zb = (bx0, bx1)[q[0]], (bz0, bz1)[q[1]]
                lignes += [(c, (xa, ya, za), (xb, ya, zb)), (c, (xa, yb, za), (xb, yb, zb))]
            lignes += [(c, (x, ya, z), (x, yb, z)) for x in (bx0, bx1) for z in (bz0, bz1)]
        ex0, ex1, ez0, ez1 = e["emprise"]
        u, v, prof = _vers_photo(geo, ((ex0 + ex1) / 2, hc - e["hauteur"][1], (ez0 + ez1) / 2))
        if prof > 0.05 and -w < u < 2 * w and -h < v < 2 * h:
            etiquettes.append('<text x="%.0f" y="%.0f" fill="%s" stroke="#000" stroke-width="0.6" '
                              'text-anchor="middle">%s</text>' % (u, v - 6, c, _x(e["nom"])))
    for c, a, b in lignes:
        seg = _segment(geo, a, b)
        if seg:
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>' % (*seg, c))
    s += etiquettes + ["</svg>"]
    return "\n".join(s)
