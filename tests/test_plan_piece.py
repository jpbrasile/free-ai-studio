"""Le plan au sol d'un tour 360° (PLAN 21.6 étapes 1 à 3, 06/10) : gabarits par parties, plan proposé par le chat
et retouché en chattant, mesure sous les cadres, cartes calculées, maquette en rayons, et le tour qui attend
« valider »."""
import importlib
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


@pytest.fixture
def pp(sandbox):
    return importlib.import_module("plan_piece")


@pytest.fixture
def t3(sandbox):
    return importlib.import_module("tour360")


@pytest.fixture
def tp(t3):
    spec = importlib.util.spec_from_file_location("tour360_pano", Path(t3.__file__).with_name("tour360_pano.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _geo(lacet=0.0):
    """Caméra de niveau à 1,5 m, regardant au cap `lacet` ; pièce x [-2, 3], z [-3, 5], plafond 2,5 m."""
    c, s = math.cos(math.radians(lacet)), math.sin(math.radians(lacet))
    return {"R": [[c, 0, s], [0, 1, 0], [-s, 0, c]], "hauteur": 1.5, "plafond": 2.5, "piece": [-2.0, 3.0, -3.0, 5.0],
            "lacet": lacet, "tangage": 0.0, "fx": 500.0, "taille": [1000, 600], "retraits": [0.025] * 4}


def _el(nom, genre, emprise, hauteur, description="a thing"):
    return {"nom": nom, "genre": genre, "description": description, "emprise": emprise, "hauteur": hauteur}


def _plan(pp, geo, *elements):
    return pp.lire_plan({"piece": geo["piece"], "plafond": 2.5, "murs": "cream plaster walls, oak floor",
                         "elements": list(elements)}, geo)[0]


# --- Les gabarits ------------------------------------------------------------------------------------------------

def test_les_aretes_disent_ce_qu_est_chaque_chose(pp):
    piece = [-2.0, 3.0, -3.0, 5.0]
    canape = dict(_el("canape", "canape", [-1.0, 1.0, 4.1, 5.0], [0.0, 0.85]))
    p = dict(pp.parties(canape, piece))
    assert pp.dos(canape["emprise"], piece) == "z+"
    assert p["dossier"][3] == 5.0 and p["dossier"][2] == pytest.approx(5.0 - 0.25)    # contre le mur du fond
    assert p["assise"][5] == pytest.approx(0.425) and p["dossier"][5] == 0.85
    assert {"accoudoir_g", "accoudoir_d"} <= set(p)
    baie = _el("baie", "baie", [-2.0, -1.92, 0.0, 3.0], [0.0, 2.5])
    noms = [n for n, _ in pp.parties(baie, piece)]
    assert "traverse" in noms and "seuil" in noms and sum(n.startswith("montant_") for n in noms) == 4
    assert pp.trou(baie, piece) == {"mur": "x-", "a0": 0.0, "a1": 3.0, "bas": 0.0, "haut": 2.5}
    biblio = _el("biblio", "bibliotheque", [0.0, 1.0, -3.0, -2.65], [0.0, 2.0])
    assert sum(n.startswith("etagere_") for n, _ in pp.parties(biblio, piece)) == 5
    assert pp.trou(biblio, piece) is None
    # une cheminée monumentale : foyer bas sous une hotte, jamais un cadre de 4 m (peint en armoire, château 07/10)
    grande = dict(pp.parties(_el("ch", "cheminee", [2.0, 3.0, 0.0, 3.0], [0.0, 4.5]), piece))
    assert grande["jambage_g"][5] == pytest.approx(1.6) and grande["hotte"][5] == 4.5
    assert "tablette" in dict(pp.parties(_el("ch", "cheminee", [2.0, 3.0, 0.0, 1.6], [0.0, 1.2]), piece))


def test_le_plan_lu_est_corrige_plutot_que_refuse(pp):
    geo = _geo()
    plan, remarques = pp.lire_plan({"murs": "white walls", "elements": [
        _el("Porte bois", "porte", [2.7, 2.9, 1.0, 1.9], [0.1, 2.05]),          # près du mur droit : plaquée
        _el("canape", "canape", [-0.3, 0.4, -0.2, 0.5], [0, 0.8]),               # sur la caméra : écarté
        _el("coffre", "malle", [1.0, 1.8, 3.0, 3.5], [0, 0.5]),                  # genre inconnu : un meuble
        _el("fauteuil", "fauteuil", [1.6, 2.5, -2.9, -2.4], [0, 0.9]),            # mince et près du mur : adossé
        {"nom": "x", "genre": "lampe"}]}, geo)
    noms = [e["nom"] for e in plan["elements"]]
    assert noms == ["porte_bois", "coffre", "fauteuil"]
    porte = plan["elements"][0]
    assert porte["emprise"][:2] == [pytest.approx(2.96), 3.0] and porte["hauteur"][0] == 0.0
    assert plan["elements"][1]["genre"] == "objet"
    assert plan["elements"][2]["emprise"][2] == -3.0
    assert any("caméra" in r for r in remarques) and any("malle" in r for r in remarques)
    assert pp.lire_plan({"elements": []}, geo)[0]["elements"] == []          # une pièce vide est un plan


# --- La mesure sous les cadres de la photo ---------------------------------------------------------------------

def _rayon_boite(o, d, b0, b1):
    tmin, tmax = -1e9, 1e9
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if not b0[i] <= o[i] <= b1[i]:
                return None
            continue
        ta, tb = (b0[i] - o[i]) / d[i], (b1[i] - o[i]) / d[i]
        tmin, tmax = max(tmin, min(ta, tb)), min(tmax, max(ta, tb))
    return tmin if tmax >= tmin > 0 else None


def _grille(pp, geo, boites, l=96):
    """Les points MoGe d'une pièce connue (y vers le bas), sans NumPy : le rayon de chaque case, la boîte touchée
    d'abord, sinon la pièce."""
    w, h = geo["taille"]
    lignes = round(l * h / w)
    x0, x1, z0, z1 = geo["piece"]
    hc = geo["hauteur"]
    pts = []
    for i in range(lignes):
        for j in range(l):
            d = pp._rayon(geo, (j + 0.5) * w / l, (i + 0.5) * h / lignes)
            t = _rayon_boite((0, 0, 0), d, (x0, hc - 2.5, z0), (x1, hc, z1))
            # depuis l'intérieur : la sortie de la pièce
            ts = []
            for k, (a, b) in enumerate(((x0, x1), (hc - 2.5, hc), (z0, z1))):
                if abs(d[k]) > 1e-12:
                    ts.append(max(a / d[k], b / d[k]))
            t = min(ts)
            for b0, b1 in boites:
                tb = _rayon_boite((0, 0, 0), d, b0, b1)
                if tb is not None and tb < t:
                    t = tb
            pts.append([c * t for c in d])
    return {"l": l, "h": lignes, "points": pts}


def _cadre(pp, geo, b0, b1):
    us, vs = [], []
    for x in (b0[0], b1[0]):
        for y in (b0[1], b1[1]):
            for z in (b0[2], b1[2]):
                u, v, _ = pp._vers_photo(geo, (x, y, z))
                us.append(u)
                vs.append(v)
    w, h = geo["taille"]
    return [min(us) / w * 1000, min(vs) / h * 1000, max(us) / w * 1000, max(vs) / h * 1000]


def test_un_meuble_vu_prend_l_emprise_de_ses_points(pp):
    geo = _geo(lacet=8.0)
    canape = ((-0.5, 1.5 - 0.85, 3.0), (0.5, 1.5, 3.9))           # y vers le bas : 0,85 m de haut
    grille = _grille(pp, geo, [canape])
    emprise, hauteur = pp.depuis_cadre(_cadre(pp, geo, *canape), "canape", geo, grille, geo["piece"])
    assert emprise[0] == pytest.approx(-0.5, abs=0.15) and emprise[1] == pytest.approx(0.5, abs=0.15)
    assert emprise[2] == pytest.approx(3.0, abs=0.15)
    assert hauteur == [0.0, pytest.approx(0.85, abs=0.08)]


def test_une_fenetre_vue_se_pose_sur_son_mur_par_les_rayons(pp):
    geo = _geo()
    fenetre = ((0.0, 1.5 - 2.0, 4.99), (1.0, 1.5 - 1.0, 5.0))
    emprise, hauteur = pp.depuis_cadre(_cadre(pp, geo, *fenetre), "fenetre", geo, {"l": 1, "h": 1, "points": [None]},
                                       geo["piece"])
    assert emprise[0] == pytest.approx(0.0, abs=0.02) and emprise[1] == pytest.approx(1.0, abs=0.02)
    assert emprise[3] == pytest.approx(5.0) and hauteur == [pytest.approx(1.0, abs=0.02), pytest.approx(2.0, abs=0.02)]


def test_la_proposition_du_chat_mele_cadres_et_metres(pp):
    geo = _geo()
    canape = ((-0.5, 1.5 - 0.85, 3.0), (0.5, 1.5, 3.9))
    grille = _grille(pp, geo, [canape])
    reponse = "Voici le plan :\n```json\n" + json.dumps({
        "murs": "cream plaster walls, oak floor, white ceiling", "fond_z": -2.5, "elements": [
            {"nom": "canape", "genre": "canape", "description": "a cream sofa", "cadre": _cadre(pp, geo, *canape)},
            {"nom": "bibliotheque", "genre": "bibliotheque", "description": "a tall oak bookshelf full of books",
             "x": 0.5, "z": -2.3, "largeur": 1.6, "profondeur": 0.35, "hauteur": 2.0},
            {"nom": "tableau", "genre": "tableau", "description": "a framed print", "x": -1.9, "z": 1.0,
             "largeur": 0.04, "profondeur": 0.8}]}) + "\n```"
    plan, remarques = pp.lire_proposition(reponse, geo, grille)
    assert plan["piece"] == [-2.0, 3.0, -2.5, 5.0]
    e = {x["nom"]: x for x in plan["elements"]}
    assert e["bibliotheque"]["emprise"][2] == -2.5                          # adossée au mur du fond choisi
    assert e["tableau"]["hauteur"][0] == pytest.approx(1.3) and e["tableau"]["emprise"][0] == -2.0
    assert e["canape"]["emprise"][3] >= 3.6           # vu de face : épaissi à l'opposé de la caméra
    assert "cream sofa" in pp.consigne_retouche(plan, "move the sofa")
    assert "x = -2.00" in pp.consigne_plan("un salon", geo) and "straight ahead" in pp.consigne_plan("x", geo)


# --- Ce que voit la caméra ---------------------------------------------------------------------------------------

def test_les_cartes_viennent_de_la_maquette_et_les_murs_nus_aussi(pp):
    geo = _geo(lacet=10.0)
    plan = _plan(pp, geo, _el("canape", "canape", [-1.0, 1.0, 4.1, 5.0], [0.0, 0.85], "a cream sofa"),
                 _el("biblio", "bibliotheque", [-0.5, 0.5, -3.0, -2.65], [0.0, 2.0], "an oak bookshelf"))
    cartes = {c["nom"]: c for c in pp.cartes_du_plan(plan, geo)}
    # le canapé est devant la pièce : au cap -10° de la photo (lacet 10°)
    assert (cartes["canape"]["a0"] + cartes["canape"]["a1"]) / 2 == pytest.approx(-10.0, abs=1.0)
    assert cartes["canape"]["bas"] < 0 < cartes["biblio"]["haut"]
    assert abs(pp._ecart((cartes["biblio"]["a0"] + cartes["biblio"]["a1"]) / 2, 170.0)) < 2
    murs = [c for n, c in cartes.items() if n.startswith("mur_nu_")]
    assert len(murs) == 4 and all(c["a1"] - c["a0"] <= 100 for c in murs)       # deux murs nus de ~150°, coupés
    assert all("bare wall" in c["description"] and "oak floor" in c["description"] for c in murs)
    texte = pp.texte_panorama("the living room", plan, geo)
    assert "Behind the camera: an oak bookshelf." in texte and "cream sofa" not in texte    # le canapé est sur la photo


def test_les_vues_du_client_sont_du_svg_lisible(pp):
    geo = _geo()
    plan = _plan(pp, geo, _el("canape", "canape", [-1.0, 1.0, 4.1, 5.0], [0.0, 0.85]),
                 _el("baie <x>", "baie", [-2.0, -1.9, 0.0, 3.0], [0.0, 2.5]))
    dessus = ET.fromstring(pp.svg_dessus(plan, geo))
    assert "baie_x" in pp.svg_dessus(plan, geo) and dessus.tag.endswith("svg")
    cam = pp.svg_camera(plan, geo)
    racine = ET.fromstring(cam)
    assert racine.get("viewBox") == "0 0 1000 600"
    lignes = [x for x in racine.iter() if x.tag.endswith("line")]
    # le canapé est devant la caméra : ses arêtes tombent dans la photo
    assert any(0 <= float(x.get("x1")) <= 1000 and 300 <= float(x.get("y1")) <= 600 for x in lignes
               if x.get("stroke") == pp.COULEURS["canape"])


def test_la_maquette_en_rayons_voit_les_parties_et_le_jour_des_trous(pp, tp):
    np = pytest.importorskip("numpy")
    geo = _geo()
    plan = _plan(pp, geo, _el("canape", "canape", [-1.0, 1.0, 4.1, 5.0], [0.0, 0.85]),
                 _el("fenetre", "fenetre", [2.9, 3.0, 1.0, 2.0], [1.0, 2.0]))
    sc = pp.scene_du_plan(plan, geo)
    assert len(sc["trous"]) == 1 and sc["trous"][0][0] == 1
    # trois rayons : sur l'assise du canapé, dans le jour de la fenêtre, sur le mur du fond
    vers = lambda x, h, z: np.array([[x, geo["hauteur"] - h, z]]) / np.linalg.norm([x, geo["hauteur"] - h, z])  # noqa
    d = np.concatenate([vers(0.0, 0.3, 4.5), vers(3.0, 1.5, 1.25), vers(-1.5, 2.0, 5.0)])
    t, ident = tp.scene(d, dict(geo, piece=sc["piece"], plafond=sc["plafond"]), sc)
    assert ident[0] >= 100 and sc["element"][(ident[0] - 100) // 8] == 0
    assert ident[1] == 10 and ident[2] == 5
    mq = tp.maquette(np.zeros((600, 1000, 3), np.uint8), geo, 256, 128, sc=sc)
    assert mq["aretes"].any() and mq["maquette"].shape == (128, 256, 3)


def test_la_carte_est_une_vue_en_perspective_et_le_retrait_s_elargit_au_bord_proche(tp):
    np = pytest.importorskip("numpy")
    pano = np.random.default_rng(1).integers(0, 255, (256, 512, 3), dtype=np.uint8)
    assert np.array_equal(tp.vue_cadree(pano, 30, 400.0, 336, 192, -96), tp.vue(pano, 30, 400.0, 336, 192))
    carte = tp.decoupe_carte(pano, {"a0": -10.0, "a1": 10.0, "haut": 10.0, "bas": -20.0}, 400.0)
    assert carte.shape[1] == round(2 * 400 * math.tan(math.radians(14))) and carte.shape[0] > 96
    # une photo 200 × 100 : à gauche un panneau à 0,8 m sur 8 % de la largeur, le reste à 4 m
    dist = np.full((100, 200), 4.0)
    dist[:, :16] = 0.8
    points = np.stack([np.zeros_like(dist), np.zeros_like(dist), dist], -1)
    r = tp.retraits_bords(points, np.ones((100, 200), bool), {})
    assert r[0] >= 0.075 and r[1] == tp.RETRAIT and r[2:] == [tp.RETRAIT, tp.RETRAIT]
    g = tp.grille_points(points, np.ones((100, 200), bool), {"R": np.eye(3).tolist()}, colonnes=20)
    assert g["l"] == 20 and g["h"] == 10 and g["points"][0] == [0.0, 0.0, 0.8]


# --- Le tour attend « valider » ---------------------------------------------------------------------------------

class FauxStudio:
    def __init__(self):
        self.appels, self.jobs, self.n = [], {}, 0

    def __call__(self, methode, chemin, corps=None):
        self.appels.append((methode, chemin, corps))
        if methode == "GET" and chemin.startswith("/jobs/"):
            return 200, self.jobs[chemin.split("/")[-1]]
        self.n += 1
        jid = "%032x" % self.n
        self.jobs[jid] = {"id": jid, "status": "succeeded"}
        if chemin == "/video-h3/finaliser":
            self.jobs[jid]["finalisation"] = {"film": jid}
        return 200, dict(self.jobs[jid])


def test_le_tour_propose_le_plan_attend_valider_puis_le_suit(t3, pp, tmp_path):
    geo = _geo()
    canape = ((-0.5, 1.5 - 0.85, 3.0), (0.5, 1.5, 3.9))
    grille = _grille(pp, geo, [canape], l=48)
    vus = {"panorama": [], "chat": []}

    def chat(consigne, images):
        vus["chat"].append(consigne)
        if consigne.startswith("The attached photo shows a place (a film set), described by its owner as: « "
                               "un salon ». A 360"):
            return '{"piece": "the living room", "panorama": "x", "ambiance": "Quiet"}'
        if "FLOOR PLAN" in consigne:
            return json.dumps({"murs": "cream walls", "fond_z": -2.0, "elements": [
                {"nom": "canape", "genre": "canape", "description": "a cream sofa", "cadre": _cadre(pp, geo, *canape)},
                {"nom": "biblio", "genre": "bibliotheque", "description": "an oak bookshelf", "x": 0, "z": -1.8,
                 "largeur": 1.2, "profondeur": 0.35, "hauteur": 2.0}]})
        if consigne.startswith("You check the floor plan"):
            return '{"ok": true, "problemes": [], "plan": null}'
        assert "The owner asks: « ajoute une lampe »" in consigne
        plan = json.loads(consigne.split("\n")[1])
        plan["elements"].append(_el("lampe", "lampe", [2.4, 2.9, 4.4, 4.9], [0, 1.6], "a brass floor lamp"))
        return json.dumps(plan)

    def mesure(photo):
        return {"geometrie.json": json.dumps(geo).encode(), "grille.json": json.dumps(grille).encode()}

    def panorama(photo, texte, graine, pas, **plan):
        vus["panorama"].append(dict(plan, texte=texte))
        sortie = {"cle_%03d.png" % c: b"\x89PNG" for c in range(0, 360, pas)}
        sortie.update({"pano.png": b"\x89PNG pano", "geometrie.json": json.dumps(dict(geo, fx_vue=904)).encode()})
        sortie.update({"carte_%s.png" % c["nom"]: b"\x89PNG carte" for c in plan.get("cartes", [])})
        return sortie

    etat = t3.nouvel_etat({"id": "a" * 12, "nom": "Salon", "genre": "decor", "description": "un salon"}, "maison")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG photo")
    studio = FauxStudio()
    tour = t3.Tour(etat, tmp_path, studio, chat, panorama, dormir=lambda s: None, mesure=mesure)
    tour.derouler()
    assert etat["statut"] == t3.A_VALIDER and etat["faites"] == ["consigne", "mesure"]
    assert [e["nom"] for e in etat["plan"]["elements"]] == ["canape", "biblio"] and not vus["panorama"]
    assert not studio.appels                                     # rien de lancé avant « valider »
    with pytest.raises(ValueError, match="Écrivez"):
        t3.retoucher_plan(etat, "  ", chat, b"")
    t3.retoucher_plan(etat, "ajoute une lampe", chat, b"\x89PNG photo")
    assert [e["nom"] for e in etat["plan"]["elements"]][-1] == "lampe" and len(etat["plan_historique"]) == 1
    t3.valider_plan(etat)
    with pytest.raises(ValueError, match="attend"):
        t3.valider_plan(etat)
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    p = vus["panorama"][0]
    assert p["geo"] == geo and len(p["scene"]["boites"]) > 10
    assert {c["nom"] for c in p["cartes"]} >= {"canape", "biblio", "lampe"}
    assert "Behind the camera: an oak bookshelf." in p["texte"]
    assert (tmp_path / "cartes" / "lampe.png").read_bytes() == b"\x89PNG carte"
    assert any("lampe" in n for g in etat["groupes"] for n in g["sujets"])
    # le plan proposé n'a pas été redemandé à la reprise, ni relu deux fois
    assert sum("FLOOR PLAN" in c for c in vus["chat"]) == 1
    assert sum(c.startswith("You check the floor plan") for c in vus["chat"]) == 1
    assert etat["plan_relecture"] == {"problemes": [], "corrige": False}


def test_un_lieu_sans_photo_suit_le_meme_tour_et_se_peint_en_entier(t3, pp, tmp_path):
    """PLAN 21.6 étape 6 (propriétaire, 06/10 : « do it step by step as in studio with these 8 examples »)."""
    vus = {"panorama": [], "chat": []}

    def chat(consigne, images):
        vus["chat"].append((consigne, images))
        if consigne.startswith("A place is described by its owner"):
            return '{"piece": "the village street", "panorama": "houses all around", "ambiance": "Quiet"}'
        if consigne.startswith("A film set must be built from this description only"):
            return json.dumps({"dehors": True, "piece": [-8, 8, -6, 16], "plafond": None, "murs": "far hills",
                               "elements": [
                                   {"nom": "puits", "genre": "objet", "description": "a stone well", "x": 0, "z": 6,
                                    "largeur": 1.4, "profondeur": 1.4, "hauteur": 1.2},
                                   {"nom": "charrette", "genre": "objet", "description": "a wooden cart", "x": 0,
                                    "z": -4, "largeur": 1.2, "profondeur": 2.2, "hauteur": 1.3}]})
        assert consigne.startswith("You check the floor plan")
        return '{"ok": true, "problemes": [], "plan": null}'

    def panorama(photo, texte, graine, pas, **plan):
        vus["panorama"].append(dict(plan, texte=texte, photo=photo))
        sortie = {"cle_%03d.png" % c: b"\x89PNG" for c in range(0, 360, pas)}
        sortie.update({"pano.png": b"\x89PNG", "geometrie.json": json.dumps(dict(plan["geo"], fx_vue=756)).encode()})
        sortie.update({"carte_%s.png" % c["nom"]: b"\x89PNG" for c in plan["cartes"]})
        return sortie

    etat = t3.nouvel_etat({"id": "b" * 12, "nom": "Rue", "genre": "decor", "description": "a village street"},
                          "maison", texte=True)
    tour = t3.Tour(etat, tmp_path, FauxStudio(), chat, panorama, dormir=lambda s: None)    # ni photo ni mesure
    tour.derouler()
    assert etat["statut"] == t3.A_VALIDER and etat["faites"] == ["consigne", "mesure"]
    assert etat["mesure"]["hauteur"] == pp.CAMERA_TEXTE and etat["plan"]["dehors"] is True
    assert all(images == [] for _, images in vus["chat"])                       # aucune image envoyée
    t3.valider_plan(etat)
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    p = vus["panorama"][0]
    assert p["photo"] is None and "<image1>" not in p["texte"]
    assert "In front: a stone well." in p["texte"] and "Behind the camera: a wooden cart." in p["texte"]
    assert sum(c.startswith("A film set must be built") for c, _ in vus["chat"]) == 1


def test_la_maquette_sans_photo_se_peint_partout_et_la_demande_n_a_pas_de_photo(sandbox, t3, pp):
    pytest.importorskip("numpy")
    spec = importlib.util.spec_from_file_location("tour360_pano", Path(t3.__file__).with_name("tour360_pano.py"))
    tp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tp)
    plan, geo, _ = _texte(pp, False, [-4, 4, -3, 6], {"nom": "table", "genre": "table", "description": "a table",
                                                      "x": 0, "z": 3, "largeur": 1.2, "profondeur": 0.8})
    mq = tp.maquette(None, geo, 256, 128, sc=pp.scene_du_plan(plan, geo))
    assert mq["masque"].min() == 255 and mq["aretes"].max() == 255
    d = t3.demande(None, "x", geo=geo, scene=pp.scene_du_plan(plan, geo))
    assert "photo" not in d and d["geo"] == geo


# --- Le relecteur du plan ----------------------------------------------------------------------------------------

def test_les_constats_voient_recouvrement_passage_bouche_et_place_sur_la_photo(pp):
    geo = _geo()
    plan = _plan(pp, geo,
                 _el("canape", "canape", [-1.0, 1.0, 3.5, 4.4], [0.0, 0.85]),
                 _el("table", "table", [-0.5, 0.5, 3.2, 3.8], [0.0, 0.45]),
                 _el("porte", "porte", [2.96, 3.0, 1.0, 1.9], [0.0, 2.05]),
                 _el("fauteuil", "fauteuil", [2.0, 2.8, 1.1, 1.8], [0.0, 0.9]),
                 _el("biblio", "bibliotheque", [-0.5, 0.5, -2.95, -2.6], [0.0, 2.0]))
    c = pp.constats(plan, geo)
    assert any(s.startswith("canape and table overlap") for s in c)
    assert "fauteuil stands in front of porte and blocks the way through." in c
    assert "biblio: outside the front view (fine: the camera turns 360 degrees)." in c
    assert not any("biblio" in s for s in pp.defauts(plan, geo))                  # hors de la vue : pas un défaut
    vu = pp.cadre_vu(next(e for e in plan["elements"] if e["nom"] == "canape"), plan, geo)
    assert vu[0] < 500 < vu[2] and 500 < vu[1] < vu[3]          # droit devant, sous l'horizon (caméra à 1,5 m)


def test_le_relecteur_ameliore_le_plan_ou_le_laisse_et_n_arrete_jamais_le_tour(t3, pp):
    geo = _geo()
    plan = _plan(pp, geo, _el("canape", "canape", [-1.0, 1.0, 3.5, 4.4], [0.0, 0.85]),
                 _el("table", "table", [-0.5, 0.5, 3.2, 3.8], [0.0, 0.45]),
                 _el("porte", "porte", [-2.0, -1.9, -2.5, -1.6], [0.0, 2.0]))
    etat = {"plan": plan, "mesure": geo, "description": "un salon, table basse devant le canapé",
            "plan_remarques": []}
    vu = {}

    def corrige(consigne, images):
        vu.update(consigne=consigne, images=images)
        p = json.loads(json.dumps(plan))
        p["elements"][1]["emprise"] = [-0.5, 0.5, 2.4, 3.0]
        return json.dumps({"ok": False, "problemes": ["La table recouvre le canapé."], "plan": p})

    r = t3.relire_plan(etat, corrige, b"\x89PNG photo")
    assert r == {"problemes": ["La table recouvre le canapé"], "corrige": True}
    assert etat["plan"]["elements"][1]["emprise"][3] == 3.0 and etat["plan_propose"] == plan
    assert "canape and table overlap" in vu["consigne"] and "table basse devant" in vu["consigne"]
    assert len(vu["images"]) == 1 and "The attached photo" in vu["consigne"]
    sans_photo = {"plan": plan, "mesure": geo, "description": "a bare room"}
    t3.relire_plan(sans_photo, corrige, None)
    assert vu["images"] == [] and "The attached photo" not in vu["consigne"]
    garde = dict(etat, plan=plan)
    r = t3.relire_plan(garde, lambda c, i: "pas de json", b"x")
    assert r["corrige"] is False and r["problemes"][0].startswith("Relecture impossible")
    assert garde["plan"] == plan


# --- Ce que la revue du 06/10 a fait généraliser ------------------------------------------------------------------

def test_piece_vide_long_mur_nu_cadres_en_fractions_et_elements_sans_place(pp):
    geo = _geo()
    vide, remarques = pp.lire_plan({"piece": geo["piece"], "plafond": 2.5, "murs": "white walls", "elements": []},
                                   geo)
    assert vide["elements"] == [] and remarques == []
    cartes = pp.cartes_du_plan(vide, geo)
    assert len(cartes) == 4 and all(c["a1"] - c["a0"] <= 100 for c in cartes)      # 360° en cartes de 100° au plus
    assert pp._cadre_px([0.1, 0.2, 0.5, 0.6], geo) == pp._cadre_px([100, 200, 500, 600], geo)
    plan, rem = pp.lire_proposition(json.dumps({"murs": "white", "elements": [
        {"nom": "lit", "genre": "lit", "description": "a bed", "cadre": [0, 0, 1000, 1000]},
        {"nom": "flou", "genre": "chaise", "description": "a chair"}]}), geo, {"l": 1, "h": 1, "points": [None]})
    assert not any("presque toute la photo" in r for r in rem)                   # un meuble peut remplir la photo
    assert any(r.startswith("flou : sans place") for r in rem)


# --- Ce que la validation sur 8 lieux (06/10 : château, forêt, plage, rue…) a fait généraliser --------------------

def _texte(pp, dehors, piece, *elements):
    return pp.lire_texte(json.dumps({"dehors": dehors, "piece": piece, "plafond": None if dehors else 6.0,
                                     "murs": "far hills" if dehors else "stone walls", "elements": list(elements)}))


def test_eau_et_chemin_a_plat_un_trone_sur_son_estrade_n_est_pas_un_recouvrement(pp):
    plan, geo, _ = _texte(
        pp, True, [-15, 15, -10, 25],
        {"nom": "mer", "genre": "surface", "description": "turquoise sea", "x": 0, "z": 18, "largeur": 30,
         "profondeur": 14, "hauteur": 1.0},
        {"nom": "palmier", "genre": "arbre", "description": "a palm", "x": 4, "z": 12, "largeur": 3,
         "profondeur": 3, "hauteur": 9})
    mer = plan["elements"][0]
    assert mer["hauteur"][1] - mer["hauteur"][0] <= 0.021                        # à plat, quoi qu'en dise le chat
    assert pp.defauts(plan, geo) == []                                            # pas un recouvrement…
    assert "palmier stands on the flat surface mer (fine on sand, grass or a path; wrong in water)." in \
        pp.constats(plan, geo)                                                    # …mais le relecteur juge
    assert [p for p, _ in pp.parties(mer, plan["piece"])] == ["surface"]
    salle, geo, _ = _texte(
        pp, False, [-6, 6, -4, 12],
        {"nom": "estrade", "genre": "objet", "description": "a dais", "x": 0, "z": 10, "largeur": 4,
         "profondeur": 3, "hauteur": 0.5},
        {"nom": "trone", "genre": "objet", "description": "a throne", "x": 0, "z": 10.5, "largeur": 1,
         "profondeur": 1, "hauteur": 1.6, "bas": 0.5},
        {"nom": "coffre", "genre": "objet", "description": "a chest", "x": 1, "z": 9.5, "largeur": 1,
         "profondeur": 1, "hauteur": 0.6})
    d = pp.defauts(salle, geo)
    assert not any("trone" in c for c in d) and any("estrade and coffre overlap" in c for c in d)
    geo = _geo()
    repas = _plan(pp, geo, _el("table", "table", [-0.8, 0.8, 3.0, 4.0], [0.0, 0.75]),
                  _el("glissee", "chaise", [-0.25, 0.25, 3.8, 4.4], [0.0, 0.9]),          # 0,1 m² sur 0,3 m²
                  _el("dedans", "chaise", [0.3, 0.7, 3.2, 3.7], [0.0, 0.9]))              # toute dessous
    d = pp.defauts(repas, geo)
    assert not any("glissee" in c for c in d) and any("dedans" in c for c in d)


def test_dehors_portes_et_fenetres_vont_sur_la_facade_la_plus_proche(pp):
    plan, geo, _ = _texte(
        pp, True, [-12, 12, -10, 20],
        {"nom": "maison", "genre": "batiment", "description": "a half-timbered house", "x": -7, "z": 8,
         "largeur": 6, "profondeur": 8, "hauteur": 9},
        {"nom": "porte", "genre": "porte", "description": "an oak door", "x": -11.5, "z": 8},   # au bord de la scène
        {"nom": "fenetre", "genre": "fenetre", "description": "a window", "x": -3.5, "z": 6, "bas": 3})
    els = {e["nom"]: e for e in plan["elements"]}
    m = els["maison"]["emprise"]
    porte, fenetre = els["porte"], els["fenetre"]
    assert porte["facade"] == "maison" and porte["emprise"][1] == pytest.approx(m[0])      # façade x- de la maison
    assert porte["dos"] == "x+" and porte["hauteur"][0] == 0.0
    assert fenetre["emprise"][0] == pytest.approx(m[1]) and fenetre["dos"] == "x-"         # façade côté rue
    assert fenetre["hauteur"][1] <= 0.75 * 9 + 1e-6                                        # sous le toit
    assert pp.trou(fenetre, plan["piece"]) is None                                         # ne perce pas le bord
    (_, (x0, x1, z0, z1, _, _)), *_ = pp.parties(porte, plan["piece"])
    assert x1 - x0 < 0.1 and z1 - z0 > 0.5                                                 # le panneau suit la façade
    relu, _ = pp.lire_plan(json.loads(json.dumps(plan)), geo)                              # relu : même place
    assert {e["nom"]: e["emprise"] for e in relu["elements"]} == {e["nom"]: e["emprise"] for e in plan["elements"]}
    rue, geo, _ = _texte(pp, True, [-12, 12, -10, 20],
                         {"nom": "porte", "genre": "porte", "description": "a gate", "x": 0, "z": 19.9})
    assert "facade" not in rue["elements"][0] and pp.cartes_du_plan(rue, geo)[-1]["description"].startswith(
        "the open view")


def test_le_relecteur_repasse_une_fois_si_le_plan_corrige_garde_des_defauts(t3, pp):
    geo = _geo()
    plan = _plan(pp, geo, _el("canape", "canape", [-1.0, 1.0, 3.5, 4.4], [0.0, 0.85]),
                 _el("table", "table", [-0.5, 0.5, 3.2, 3.8], [0.0, 0.45]),
                 _el("porte", "porte", [-2.0, -1.9, -2.5, -1.6], [0.0, 2.0]))
    etat = {"plan": plan, "mesure": geo, "description": "un salon", "plan_remarques": []}
    consignes = []

    def relecteur(consigne, images):
        consignes.append(consigne)
        p = json.loads(json.dumps(plan))
        # 1re passe : la table bouge à peine (recouvre encore) ; 2e : elle sort
        p["elements"][1]["emprise"] = [-0.5, 0.5, 3.0, 3.6] if len(consignes) == 1 else [-0.5, 0.5, 2.4, 3.0]
        return json.dumps({"ok": False, "problemes": ["La table recouvre le canapé."], "plan": p})

    r = t3.relire_plan(etat, relecteur)
    assert len(consignes) == 2 and r == {"problemes": ["La table recouvre le canapé"], "corrige": True}
    assert pp.defauts(etat["plan"], geo) == [] and etat["plan_propose"] == plan
    assert "Every computed fact other than the place in the front view is a defect" in consignes[0]
    assert "ADD what such a place plainly has" in consignes[0] and "REMOVE what does not belong" in consignes[0]
    assert "Never add in the front view" not in consignes[0]                      # sans photo
    assert "Never add in the front view" in pp.consigne_relecture("x", plan, geo, True)
    assert "Add what such a place plainly has" in pp.consigne_plan_texte("a street")
    consignes.clear()
    t3.relire_plan(dict(etat, plan=plan), lambda c, i: consignes.append(c) or '{"ok": true, "problemes": []}')
    assert len(consignes) == 1                                                    # « ok » : une seule passe


def test_le_relecteur_du_studio_est_le_modele_fort_du_routeur(sandbox, t3, monkeypatch):
    app = sandbox
    vus = []

    async def faux(consigne, quoi="", images=None, modele="free-ai-auto"):
        vus.append(modele)
        return "{}"

    monkeypatch.setattr(app, "_chat_du_studio", faux)
    app._tour360_chat("propose", [])
    app._tour360_relecteur("relis", [])
    assert vus == ["free-ai-auto", "free-ai-max"]                                 # propose léger, relit fort
    seul = t3.Tour({}, Path("."), None, "chat", None)
    assert seul.relecteur == "chat" and t3.Tour({}, Path("."), None, "chat", None, relecteur="max").relecteur == "max"


def test_la_mesure_se_fait_sur_la_carte_d_ici_et_rend_ses_fichiers(sandbox, t3, monkeypatch):
    app = sandbox
    vu = {}

    def faux_maison(jid, code, secondes=None, url=None):
        vu.update(code=code, secondes=secondes)
        sortie = app.JOBS / jid / "output"
        sortie.mkdir(parents=True, exist_ok=True)
        (sortie / "geometrie.json").write_text("{}")
        (sortie / "grille.json").write_text("{}")
        return {"exit_code": 0, "stdout": "MESURE", "stderr": "", "artifacts": []}

    monkeypatch.setattr(app, "attendre_la_carte", lambda jid: True)
    monkeypatch.setattr(app, "maison_execute", faux_maison)
    fichiers = app._tour360_mesure(b"\x89PNG photo", "maison")
    assert set(fichiers) == {"geometrie.json", "grille.json"} and vu["secondes"] == t3.DUREE_MESURE_S
    assert "__DEMANDE_B64__" not in vu["code"]
    d = t3.demande_mesure(b"x", maison=True)
    assert d["mode"] == "mesure" and d["moge"] == t3.MOGE_MAISON and d["poids"] == []
    compile(t3.construire_mesure(b"x"), "mesure", "exec")
    assert t3.demande(b"x", "y", geo={"a": 1}, scene={"b": 2}, cartes=[{"nom": "c"}])["scene"] == {"b": 2}


def test_sans_photo_la_largeur_court_le_long_du_mur_la_camera_au_milieu_une_porte_et_le_repere_suit(t3, pp):
    # 06/10, revue des 8 lieux : lit de côté pris en travers, caméra contre le fond, pas de porte, repère figé
    plan, geo, _ = _texte(
        pp, False, [-3, 3, -0.5, 5],
        {"nom": "lit", "genre": "lit", "description": "a bed", "x": -2.2, "z": 3, "largeur": 2.0,
         "profondeur": 1.6, "hauteur": 0.6},
        {"nom": "table", "genre": "table", "description": "a table", "x": 0.5, "z": 3, "largeur": 1.2,
         "profondeur": 0.8, "hauteur": 0.75})
    lit, table = plan["elements"]
    assert lit["emprise"][1] - lit["emprise"][0] == pytest.approx(1.6) and lit["emprise"][3] - lit["emprise"][2] == 2.0
    assert table["emprise"][1] - table["emprise"][0] == pytest.approx(1.2)         # au milieu : largeur le long de x
    d = pp.defauts(plan, geo)
    assert any(c.startswith("room: no door") for c in d)
    assert any(c.startswith("camera: only 0.5 m from the back wall") for c in d)
    assert not any("is bare" in c for c in d) and any("is bare" in c for c in pp.constats(plan, geo))
    assert "a quarter of the depth behind it" in pp.consigne_plan_texte("a bedroom")
    etat = {"plan": plan, "mesure": geo, "description": "a bedroom", "plan_remarques": []}
    p = json.loads(json.dumps(plan))
    p["piece"] = [-3, 3, -2.5, 5]
    t3.relire_plan(etat, lambda c, i: json.dumps({"ok": False, "problemes": ["recule"], "plan": p}))
    assert etat["mesure"]["piece"] == [-3, 3, -2.5, 5] and not any(
        c.startswith("camera:") for c in pp.defauts(etat["plan"], etat["mesure"]))


def test_les_cartes_voisines_se_groupent_et_un_clip_trop_plein_est_un_defaut(pp):
    # propriétaire, 06/10 : « group cards and cap per arc » ; H3 prend 9 images, 2 clés + 7 cartes
    def objet(k, x):
        return {"nom": "vase%d" % k, "genre": "objet", "description": "vase %d." % k, "x": x, "z": 4.5,
                "largeur": 0.3, "profondeur": 0.3, "hauteur": 0.5, "bas": 0.0}
    plan, geo, _ = _texte(pp, False, [-4, 4, -2.5, 5], *[objet(k, -3.5 + 0.7 * k) for k in range(11)],
                          {"nom": "porte", "genre": "porte", "description": "a door", "x": 0, "z": -2.5,
                           "largeur": 0.9, "profondeur": 0.1, "hauteur": 2.0})
    fen = pp.fenetre_clip(geo)
    cartes = pp.cartes_du_plan(plan, geo)
    assert all(len([c for c in cartes if pp._croise(c, k * 7.5, fen / 2)]) <= pp.SUJETS_MAX for k in range(48))
    groupes = [c for c in cartes if c.get("membres")]
    assert groupes and all(c["a1"] - c["a0"] <= pp.GROUPE_MAX for c in groupes)
    assert sum(len(c["membres"]) for c in groupes) + len(cartes) - len(groupes) - sum(
        1 for c in cartes if c.get("mur_nu")) == 12
    assert groupes[0]["description"].startswith("side by side, left to right: vase")
    assert not any(c.startswith("clip around") for c in pp.constats(plan, geo))
    # trop serré pour grouper (au-delà de GROUPE_MAX) : la relecture le reçoit comme un défaut
    garde = pp.GROUPE_MAX
    pp.GROUPE_MAX = 0.0
    try:
        assert any(c.startswith("clip around heading") and "vase0" in c for c in pp.defauts(plan, geo))
    finally:
        pp.GROUPE_MAX = garde


def test_le_personnage_se_tient_devant_son_element_cote_camera_et_se_voit_au_plan(pp):
    # 07/10, propriétaire : « the 2d layout shall include Leila »
    geo = _geo()
    plan = _plan(pp, geo, _el("canape", "meuble", [-0.5, 0.5, 3.0, 3.8], [0.0, 0.8]))
    p = pp.place_personnage(plan, "canape")
    assert p["x"] == pytest.approx(0.0, abs=0.01) and p["z"] == pytest.approx(3.0 - pp.PERSONNE_RECUL, abs=0.01)
    assert pp.place_personnage(plan, "piano") is None
    plan["personnage"] = dict(p, nom="Leila")
    assert ">Leila</text>" in pp.svg_dessus(plan, geo)
