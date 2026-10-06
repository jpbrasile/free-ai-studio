"""Le tour 360° d'un décor (06/10/2026) : mesure de la pièce, cartes des éléments, tronçons, par les routes du Studio."""
import importlib
import importlib.util
import json
import math
from pathlib import Path

import pytest


@pytest.fixture
def t3(sandbox):
    return importlib.import_module("tour360")


@pytest.fixture
def tp(t3):
    """Le script de la carte louée : un fichier à côté de tour360, chargé par son chemin."""
    spec = importlib.util.spec_from_file_location("tour360_pano", Path(t3.__file__).with_name("tour360_pano.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- La géométrie (tour360_pano, envoyé tel quel sur la carte louée) ----------------------------------------------

def _piece_synthetique(np, tp, lacet=10.0, tangage=-5.0):
    """Une pièce connue vue par une caméra inclinée : x [-2, 3], z [-2, 5], sol 1,5 m sous la caméra, plafond à
    2,5 m ; les points et normales de MoGe, en repère caméra."""
    w, h, fx = 320, 240, 200.0
    c, s = math.cos(math.radians(tangage)), math.sin(math.radians(tangage))
    incline = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])          # vers le bas pour un tangage négatif
    r_vrai = tp.lacet_y(lacet) @ incline                             # caméra -> pièce
    x, y = np.meshgrid(np.arange(w) - w / 2 + 0.5, np.arange(h) - h / 2 + 0.5)
    d_cam = np.stack([x / fx, y / fx, np.ones_like(x)], -1)
    d = d_cam @ r_vrai.T
    geo = {"piece": [-2.0, 3.0, -2.0, 5.0], "hauteur": 1.5, "plafond": 2.5}
    t, face = tp.boite(d, geo)
    p_piece = d * t[..., None]
    n_piece = np.zeros_like(d)
    axe, signe = face // 2, face % 2
    np.put_along_axis(n_piece, axe[..., None], np.where(signe, -1.0, 1.0)[..., None], -1)
    return p_piece @ r_vrai, n_piece @ r_vrai, np.ones((h, w), bool), fx, w, h


def test_la_piece_mesuree_est_la_boite_vue(tp):
    np = pytest.importorskip("numpy")
    geo = tp.repere(*_piece_synthetique(np, tp))
    assert geo["hauteur"] == pytest.approx(1.5, abs=0.01)
    assert geo["plafond"] == pytest.approx(2.5, abs=0.05)
    assert geo["lacet"] == pytest.approx(10.0, abs=0.5)
    assert geo["tangage"] == pytest.approx(-5.0, abs=0.5)
    x0, x1, _z0, z1 = geo["piece"]
    assert (x0, x1, z1) == (pytest.approx(-2.0, abs=0.05), pytest.approx(3.0, abs=0.05), pytest.approx(5.0, abs=0.05))


def test_sans_sol_la_piece_est_illisible(tp):
    np = pytest.importorskip("numpy")
    p, n, v, fx, w, h = _piece_synthetique(np, tp)
    n[..., 1] = 0.0                       # aucune normale vers le haut : pas de sol
    with pytest.raises(ValueError, match="sol"):
        tp.repere(p, n, v, fx, w, h)


# --- Le module du Studio -------------------------------------------------------------------------------------------

def test_le_script_porte_la_demande_et_les_noeuds_union(t3):
    d = t3.demande(b"\x89PNG photo", "An equirectangular 360 panorama.", 7, 30)
    assert {"QwenImage21UnionLoader", "QwenImage21UnionApply", "QwenImage21UnionLatentFromImage", "SeedVR2Preprocess",
            "RepeatImageBatch", "SaveImage"} <= set(d["classes"])
    assert d["pas"] == 30 and d["graphe_dessin"]["41"]["inputs"]["seed"] == 7
    assert d["graphe_dessin"]["70"]["inputs"]["control_mode"] == "Lineart"
    assert d["graphe_couture"]["20"]["inputs"]["image"] == "tourne.png"
    assert d["poids"][1]["base"].endswith("/controlnet")
    script = t3.construire_script(b"\x89PNG photo", "x", 7, 30)
    assert "__DEMANDE_B64__" not in script and script.rstrip().endswith("principal()")
    compile(script, "tour360_pano", "exec")
    assert any("MoGe.git@" in c for c in t3.commandes()) and any("union_t8" in c for c in t3.commandes())


def test_consigne_du_chat_lue_meme_entouree_de_texte(t3):
    c = t3.lire_consigne('Voici :\n```json\n{"piece": "the living room", "panorama": "Behind the camera, a bookshelf.",'
                         ' "ambiance": "Quiet room tone."}\n```')
    assert c == {"piece": "the living room", "panorama": "Behind the camera, a bookshelf",
                 "ambiance": "Quiet room tone"}
    assert t3.texte_dessin(c).startswith("An equirectangular 360 panorama of the living room of <image1>")
    with pytest.raises(ValueError):
        t3.lire_consigne("je ne sais pas")


def test_cartes_azimut_et_visibles(t3):
    fx = 904.0
    caps = [0, 45, 90, 135, 180, 225, 270, 315]
    rep = json.dumps([
        {"nom": "Sofa", "description": "a cream sofa.", "vues": [{"vue": 1, "x0": 400, "x1": 600}]},
        {"nom": "Glass wall", "description": "a glass wall", "vues": [{"vue": 8, "x0": 0, "x1": 1000},
                                                                     {"vue": 1, "x0": 0, "x1": 100}]},
        {"nom": "ghost", "description": "", "vues": [{"vue": 2, "x0": 0, "x1": 500}]},       # sans description
        {"nom": "nowhere", "description": "x", "vues": [{"vue": 12, "x0": 0, "x1": 500}]}])  # vue hors du tour
    cartes = t3.lire_cartes(rep, caps, fx)
    assert [c["nom"] for c in cartes] == ["sofa", "glass_wall"]
    sofa, vitre = cartes
    assert sofa["a0"] == pytest.approx(-math.degrees(math.atan(0.1 * 1344 / fx)), abs=0.1)
    assert sofa["a1"] == pytest.approx(-sofa["a0"], abs=0.1)
    assert vitre["a0"] < 315 - 30 and vitre["a1"] > 315 + 30            # vue 8, la plus centrée
    demi = math.degrees(math.atan(1344 / 2 / fx))
    assert [c["nom"] for c in t3.visibles(cartes, 0, demi)] == ["glass_wall", "sofa"]   # de gauche à droite
    assert t3.visibles(cartes, 180, demi) == []
    consignes = t3.consignes_troncons(cartes, {"piece": "the living room", "ambiance": "Quiet"}, fx, 45)
    assert len(consignes) == 8
    assert "a cream sofa" in consignes[0]["description_premiere"]
    assert "plain walls" in consignes[4]["description_premiere"]
    assert consignes[0]["image_paroles"].count("nothing else") == 1


class FauxStudio:
    def __init__(self):
        self.appels, self.jobs, self.n = [], {}, 0

    def job(self):
        self.n += 1
        jid = "%032x" % self.n
        self.jobs[jid] = {"id": jid, "status": "succeeded"}
        return dict(self.jobs[jid])

    def __call__(self, methode, chemin, corps=None):
        self.appels.append((methode, chemin, corps))
        if methode == "GET" and chemin.startswith("/jobs/"):
            return 200, self.jobs[chemin.split("/")[-1]]
        return 200, self.job()


def _chat(consigne, images):
    if consigne.startswith("The attached photo"):
        assert len(images) == 1 and images[0].startswith("data:image/png;base64,")
        return '{"piece": "the living room", "panorama": "A bookshelf behind.", "ambiance": "Quiet"}'
    assert len(images) == 8
    return json.dumps([{"nom": "sofa", "description": "a cream sofa", "vues": [{"vue": 1, "x0": 400, "x1": 600}]}])


def _panorama(photo, texte, graine, pas):
    assert texte.startswith("An equirectangular 360 panorama of the living room")
    sortie = {"cle_%03d.png" % c: b"\x89PNG cle %d" % c for c in range(0, 360, pas)}
    sortie["geometrie.json"] = json.dumps({"hauteur": 1.2, "plafond": 2.5, "piece": [-1, 3, -3, 5], "lacet": 13,
                                           "tangage": -2, "fx": 756, "fx_vue": 904}).encode()
    return sortie


def _tour(t3, tmp_path, studio, **quoi):
    etat = t3.nouvel_etat({"id": "a" * 12, "nom": "Salon", "genre": "decor", "description": "un salon"}, "modal")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG photo")
    return etat, t3.Tour(etat, tmp_path, studio, quoi.get("chat", _chat), quoi.get("panorama", _panorama),
                         decouper=lambda png, x0, x1: png, dormir=lambda s: None)


def test_le_tour_va_de_la_photo_au_film_par_les_routes_du_studio(t3, tmp_path):
    studio = FauxStudio()
    etat, tour = _tour(t3, tmp_path, studio)
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert etat["faites"] == list(t3.Tour.ETAPES)
    creer = [x for m, c, x in studio.appels if c == "/video-h3/creer"]
    assert len(creer) == 8
    assert creer[0]["mode"] == "premiere_derniere" and creer[0]["camera"]["mouvement"] == "pano_droite"
    assert creer[0]["definition"] == "768p" and creer[0]["longueur"] == 124 and creer[0]["ou"] == "modal"
    # le dernier tronçon revient à la première clé : le tour boucle
    assert creer[7]["images"][1] == creer[0]["images"][0]
    montage = next(x for m, c, x in studio.appels if c == "/video-h3/montage")
    assert montage["clips"] == etat["troncons"] and montage["lieux"] == ["tour"] * 8
    assert etat["film"] and (tmp_path / "cartes" / "sofa.png").is_file()
    assert json.loads((tmp_path / "tour.json").read_text(encoding="utf-8"))["statut"] == "fini"


def test_la_reprise_garde_les_troncons_tournes(t3, tmp_path):
    studio = FauxStudio()
    etat, tour = _tour(t3, tmp_path, studio)
    reel = studio.__call__

    def troisieme_refuse(methode, chemin, corps=None):
        if chemin == "/video-h3/creer" and sum(c == "/video-h3/creer" for _m, c, _x in studio.appels) == 2:
            studio.appels.append((methode, chemin, corps))
            return 429, {"detail": "Budget Modal atteint."}
        return reel(methode, chemin, corps)

    tour.appel = troisieme_refuse
    tour.derouler()
    assert etat["statut"] == "arrete" and "429" in etat["erreur"] and len(etat["troncons"]) == 2
    etat.update(statut="en cours", erreur="")
    tour.appel = reel
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert len(etat["troncons"]) == 8
    assert sum(c == "/video-h3/creer" for _m, c, _x in studio.appels) == 9      # 2 + 1 refusé + 6


def test_un_panorama_en_echec_arrete_le_tour_avec_sa_phrase(t3, tmp_path):
    def en_panne(*a):
        raise t3.Arret(t3.phrase_d_echec("... PIECE_ILLISIBLE pas de sol"))
    etat, tour = _tour(t3, tmp_path, FauxStudio(), panorama=en_panne)
    tour.derouler()
    assert etat["statut"] == "arrete" and "sol" in etat["erreur"] and etat["faites"] == ["consigne"]


def test_le_tour_refuse_ce_qui_n_est_pas_un_decor_et_un_pas_inconnu(t3):
    with pytest.raises(ValueError, match="décor"):
        t3.nouvel_etat({"id": "a" * 12, "nom": "Leila", "genre": "personne"})
    with pytest.raises(ValueError, match="30 ou 45"):
        t3.nouvel_etat({"id": "a" * 12, "nom": "Salon", "genre": "decor"}, pas=60)
