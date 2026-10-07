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


def test_un_personnage_ajoute_a_la_vue_revient_a_sa_place_dans_le_panorama(tp):
    # 07/10 : Leila peinte dans le panorama ; seule la bande changée revient, à son cap
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(0)
    pano = (rng.random((256, 512, 3)) * 60 + 100).astype(np.uint8)
    fx, cap = 200.0, 40.0
    avant = tp.vue(pano, cap, fx, 320, 180)
    apres = avant.copy()
    apres[60:170, 200:230] = (20, 140, 40)                 # une robe verte, à droite du milieu de la vue
    grand, info = tp.coller(pano, avant, apres, cap, fx)
    attendu = cap + math.degrees(math.atan((215 - 160) / fx))
    assert abs(info["cap"] - attendu) < 1.5 and 3 < info["demi"] < 10
    revue = tp.vue(grand, cap, fx, 320, 180)
    assert np.abs(revue[90:150, 205:225].astype(int) - (20, 140, 40)).mean() < 25     # elle y est
    assert np.abs(revue[:, :120].astype(int) - avant[:, :120].astype(int)).mean() < 2  # le reste n'a pas bougé
    loin = np.ones(pano.shape[:2], bool)
    loin[:, 250:380] = False                               # caps ~ 1..79 : la vue ; ailleurs, rien ne change
    assert (grand[loin] == pano[loin]).all()
    with pytest.raises(ValueError, match="Rien"):
        tp.coller(pano, avant, avant, cap, fx)


def test_consigne_du_chat_lue_meme_entouree_de_texte(t3):
    c = t3.lire_consigne('Voici :\n```json\n{"piece": "the living room", "panorama": "Behind the camera, a bookshelf.",'
                         ' "ambiance": "Quiet room tone, distant birds."}\n```')
    assert c == {"piece": "the living room", "panorama": "Behind the camera, a bookshelf",
                 "ambiance": "Distant birds."}
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
    consigne = {"piece": "the living room", "ambiance": "Distant birds sing faintly."}
    # clip de tête vers la droite, de -30 à 30° : le canapé est là au départ et à l'arrivée
    texte, noms = t3.invite_clip(consigne, cartes, -30, 30, demi, arret=False)
    sections = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:",
                "overall_soundscape:", "non_diegetic_music:"]
    assert [x for x in texte.split("\n") if x in sections] == sections                 # les six, dans l'ordre
    assert noms == ["glass_wall", "sofa"] and "<Subject 3> is a cream sofa in <Picture 4>." in texte
    assert "[keyframe completion + reference generation]" in texte and "pans right" in texte
    assert "<Picture 1> is the first frame" in texte and "Keeping its steady speed" in texte
    assert "Distant birds sing faintly." in texte and " no " not in texte                        # rien de ce qui n'est pas là
    # clip enchaîné vers la gauche : la clé d'arrivée devient <Picture 1>, les cartes suivent, le sens s'inverse
    # le canapé, déjà dans le cadre au départ, est porté par le latent : ni carte ni étiquette
    texte, noms = t3.invite_clip(consigne, cartes, 30, -30, demi, suite=True)
    assert noms == ["glass_wall"] and "sofa" not in texte
    assert "[video continuation + keyframe completion + reference generation]" in texte
    assert "<Picture 1> is the last frame" in texte and "<Picture 2>" in texte and "<Picture 3>" not in texte
    assert "first frame" not in texte and "pans left" in texte and "The pan slows and settles" in texte
    # un mur nu : aucun sujet, rien d'inventé
    texte, noms = t3.invite_clip(consigne, cartes, 150, 210, demi)
    assert noms == [] and "<Subject 2>" not in texte and "plain wall" in texte


def test_un_feu_bouge_et_un_personnage_se_nomme_par_ses_photos(t3):
    demi = math.degrees(math.atan(1344 / 2 / 904.0))
    consigne = {"piece": "the great hall", "ambiance": "Crackling fire."}
    feu = {"nom": "cheminee", "description": "A stone fireplace with a blazing log fire", "a0": -5.0, "a1": 5.0}
    banc = {"nom": "banc", "description": "A dark oak bench", "a0": 20.0, "a1": 30.0}
    leila = {"nom": "perso", "personne": True, "images": ["perso_visage", "perso_tenue"], "a0": 18.0, "a1": 22.0,
             "description": "a young woman, wearing a green velvet gown", "action": "winding a ribbon around her fingers"}
    assert t3.vivant(feu) and not t3.vivant(banc) and not t3.vivant(leila)
    texte, images = t3.invite_clip(consigne, [feu, banc, leila], -30, 30, demi)
    # le personnage d'abord, ses photos à la suite des deux clés, le rôle de chacune dit (07/10)
    assert images == ["perso_visage", "perso_tenue", "cheminee", "banc"]
    assert ("<Subject 2> is a young woman, wearing a green velvet gown: the face and hair in <Picture 3>; "
            "the clothing and the whole figure in <Picture 4>, full-length photos of the same single person from the "
            "front." in texte)
    assert "only one <Subject 2>" in texte
    assert "<Subject 3> is a stone fireplace with a blazing log fire in <Picture 5>." in texte
    # seule la caméra bouge (château, 07/10) : une personne n'« entre » pas et ne « s'assoit » pas
    assert ("As the camera turns, <Subject 2> comes into view at the right edge of the frame, already in place, "
            "winding a ribbon around her fingers." in texte)
    assert "where <Subject 2> is in the centre of the frame" in texte
    assert "enters" not in texte and "sits " not in texte
    assert "winding a ribbon around her fingers" in texte and "In <Subject 3>, the flames flicker and dance" in texte
    assert "only the flames and the people move" in texte and "Only the camera moves" not in texte
    # sans clé d'arrivée (elle montrerait vide la place du personnage) : pas de <Picture 2> de fin
    texte, images = t3.invite_clip(consigne, [feu, banc, leila], -30, 30, demi, suite=True, fin_cle=False)
    assert "last frame" not in texte and "the shot ends on" not in texte
    assert "the face and hair in <Picture 1>; the clothing and the whole figure in <Picture 2>" in texte
    assert "[video continuation + reference generation]" in texte


def test_les_gros_plans_du_visage_et_les_photos_en_pied_disent_leur_role(t3):
    """07/10 : visage pauvre dans le clip -> gros plans du visage coiffe comprise + photos en pied en hauteur."""
    noms = ["perso_visage_face", "perso_visage_trois_quarts", "perso_pied_face", "perso_pied_trois_quarts"]
    refs = ["<Picture 3>", "<Picture 4>", "<Picture 5>", "<Picture 6>"]
    assert t3.roles_personne(noms, refs) == (
        "the face, framed by the headwear, in <Picture 3> and <Picture 4>, close-ups of the same face from the front "
        "and in three-quarter view; the clothing and the whole figure in <Picture 5> and <Picture 6>, full-length "
        "photos of the same single person from the front and in three-quarter view")


def test_une_description_trop_longue_garde_le_groupe_nominal_de_chaque_element(t3):
    """Château, 07/10 : un clip devant trois groupes de meubles faisait 658 mots (guide : 350-500)."""
    demi = math.degrees(math.atan(1344 / 2 / 904.0))
    long = ("A tall black wrought-iron standing torch on a tripod foot with an open flame at the top; A tall narrow "
            "round-arched window with small leaded panes, set at the back of a deep stone recess with a broad sill; "
            "A dark oak high-backed settle bench with carved panels and arm rests, standing against the stone wall")
    cartes = [{"nom": "g%d" % k, "description": "side by side, left to right: " + long,
               "a0": -40.0 + 12 * k, "a1": -30.0 + 12 * k} for k in range(7)]
    texte, _ = t3.invite_clip({"piece": "the great hall"}, cartes, -30, 30, demi)
    assert t3._mots_description(texte) <= t3.MOTS_DESCRIPTION
    assert ("left to right: A tall black wrought-iron standing torch; A tall narrow round-arched window; "
            "A dark oak high-backed settle bench, stands" in texte)
    # sous la limite, rien n'est raccourci
    texte, _ = t3.invite_clip({"piece": "the great hall"}, cartes[:1], -30, 30, demi)
    assert "on a tripod foot" in texte.split("detailed_description:")[1]


def test_le_groupe_nominal_garde_son_complement_et_coupe_au_participe(t3):
    """07/10 : « a stretch of bare wall: … » réduit à « a stretch », « a heavy dark oak chest bound with … » à
    « … chest bound »."""
    assert t3._abrege("a stretch of bare wall: pale grey walls with tall recesses", True) == "a stretch of bare wall"
    assert t3._abrege("a heavy dark oak chest bound with black iron straps, standing", True) == \
        "a heavy dark oak chest"


def test_les_vues_du_personnage_ne_chassent_pas_l_element_pres_duquel_il_agit(t3):
    """07/10 : les quatre vues ont chassé la cheminée du clip ; H3 en a inventé une, avec un second personnage."""
    demi = math.degrees(math.atan(1344 / 2 / 904.0))
    vues = ["perso_visage_face", "perso_visage_trois_quarts", "perso_pied_face", "perso_pied_trois_quarts"]
    perso = {"nom": "perso", "personne": True, "images": vues, "pres_de": "feu", "action": "winding a ribbon around her fingers",
             "description": "a girl", "a0": 20.0, "a1": 30.0}
    cartes = [{"nom": "m%d" % k, "description": "a chest", "a0": -60.0 + 8 * k, "a1": -56.0 + 8 * k}
              for k in range(4)] + [{"nom": "feu", "description": "a huge stone fireplace", "a0": 12.7, "a1": 37.5},
                                    perso]
    texte, images = t3.invite_clip({"piece": "the great hall"}, cartes, -64.9, -4.9, demi, fin_cle=False)
    assert "feu" in images and images[:2] == ["perso_visage_face", "perso_pied_face"]
    assert len(images) <= t3.IMAGES_MAX - 1
    assert "never a frozen pose" in texte
    # la place suffit : les quatre vues
    texte, images = t3.invite_clip({"piece": "the great hall"}, [cartes[4], perso], 0, 30, demi, fin_cle=False)
    assert images[:4] == vues and "feu" in images


def test_un_personnage_qui_ne_fait_que_sortir_au_debut_d_un_clip_enchaine_n_y_est_ni_nomme_ni_en_reference(t3):
    """07/10, clip 3 : nommé « at the left of the frame » au début, H3 l'a remis dans le cadre une seconde fois."""
    demi = math.degrees(math.atan(1344 / 2 / 904.0))
    vues = ["perso_visage_face", "perso_pied_face"]
    cartes = [{"nom": "feu", "description": "a huge stone fireplace", "a0": 12.7, "a1": 37.5},
              {"nom": "perso", "personne": True, "images": vues, "pres_de": "feu", "action": "winding a ribbon around her fingers",
               "description": "a girl", "a0": 20.0, "a1": 30.0}]
    texte, images = t3.invite_clip({"piece": "the great hall"}, cartes, 55.1, 115.1, demi, suite=True)
    assert "perso_visage_face" not in images and "a girl" not in texte and "keeps moving" not in texte
    # pas enchaîné (clé de départ), il reste nommé : la clé le montre
    texte, images = t3.invite_clip({"piece": "the great hall"}, cartes, 55.1, 115.1, demi)
    assert "perso_visage_face" in images
    # déjà dans le cadre au début d'un clip enchaîné : le latent le porte, ni nommé ni en référence (07/10, clip 2 :
    # nommé, un second personnage ; retiré, un seul, qui bouge) ; « the people » reste
    texte, images = t3.invite_clip({"piece": "the great hall"}, cartes, -4.9, 55.1, demi, suite=True, fin_cle=False)
    assert "perso_visage_face" not in images and "a girl" not in texte and "<Subject 3>" not in texte
    # la cheminée aussi : déjà là, redite avec sa carte, H3 en a dessiné une seconde (même tour, clip 2) ; son feu
    # garde son mouvement, sans étiquette
    assert "the people keep moving" in texte and "feu" not in images and "fireplace" not in texte
    cartes[0]["description"] = "a huge stone fireplace with a blazing log fire"
    texte, images = t3.invite_clip({"piece": "the great hall"}, cartes, -4.9, 55.1, demi, suite=True, fin_cle=False)
    assert "feu" not in images and "Wherever they are already in view, the flames" in texte
    assert "while the flames and the people keep moving" in texte
    cartes[0]["description"] = "a huge stone fireplace"
    # le mouvement se dit avant les meubles (clip de tête)
    texte, _ = t3.invite_clip({"piece": "the great hall"}, cartes, -64.9, -4.9, demi, fin_cle=False)
    d = texte.split("detailed_description:")[1]
    assert d.index("keeps moving") < d.index("The camera pans")
    # il n'apparaît qu'au milieu d'un clip enchaîné : ses images restent, c'est sa première apparition
    texte, images = t3.invite_clip({"piece": "the great hall"}, cartes, -64.9, -4.9, demi, suite=True, fin_cle=False)
    assert "perso_visage_face" in images


def test_le_choix_du_chat_pour_le_personnage(t3):
    cartes = [{"nom": "banc", "description": "a bench"}]
    assert t3.lire_choix_personnage('{"pres_de": "banc", "action": "reading", "tenue": "a red gown"}', cartes) == {
        "pres_de": "banc", "action": "reading", "tenue": "a red gown"}
    with pytest.raises(ValueError):
        t3.lire_choix_personnage('{"pres_de": "trone", "action": "reading", "tenue": "a red gown"}', cartes)
    assert t3.lire_personnage(None) is None
    with pytest.raises(ValueError):
        t3.lire_personnage({"fiche": "x", "couleur": "bleu"})


def test_le_tour_coupe_ou_la_camera_quitte_le_personnage(t3):
    # château, 07/10 : zone sans épingle (-22, 72) ; sans coupe, la caméra en retard y était rattrapée d'un coup au
    # clip 3 et le personnage s'effaçait dans le fondu
    chemin = [[{"a": -64.9, "b": -4.9, "arret": False}, {"a": -4.9, "b": 55.1, "arret": False},
               {"a": 55.1, "b": 115.1, "arret": False}],
              [{"a": 115.1, "b": 175.1, "arret": False}, {"a": 175.1, "b": 235.1, "arret": True}]]
    g = t3.couper_sur_personnage(chemin, [(-22.0, 72.0, None)])
    assert [[(c["a"], c["b"]) for c in clips] for clips in g] == [
        [(-64.9, -4.9), (-4.9, 55.1)], [(72.0, 115.1)], [(115.1, 175.1), (175.1, 235.1)]]
    assert [c["coupe"] for clips in g for c in clips] == [False, True, False, False, False]
    # sans personnage : le chemin tel quel
    assert [[(c["a"], c["b"]) for c in clips] for clips in t3.couper_sur_personnage(chemin, [])] == \
        [[(c["a"], c["b"]) for c in clips] for clips in chemin]


def test_geste_muet_et_ambiance_sans_fond_continu(t3):
    # un geste qui verse ou qui fait tinter devient un ton continu chez H3 (château, 07/10) : remplacé
    cartes = [{"nom": "table", "description": "a banquet table"}]
    choix = t3.lire_choix_personnage('{"pres_de": "table", "action": "pouring wine from a jug into a goblet", '
                                     '"tenue": "a red gown"}', cartes)
    assert choix["action"] == t3.GESTE_DEFAUT
    # une pose gardée dans l'état d'un tour plus ancien donne une figure figée : remplacée elle aussi
    assert t3.geste_silencieux("warming her hands by the fire") == t3.GESTE_DEFAUT
    for muet in ("winding a ribbon around her fingers", "slowly turning the pages of a book",
                 "stroking the tapestry's fringe"):
        assert t3.geste_silencieux(muet) == muet
    consigne = t3.consigne_personnage("the great hall", cartes)
    assert "wine" not in consigne and "goblet" not in consigne and "NO sound" in consigne
    # l'ambiance : jamais de fond continu demandé
    assert t3.ambiance_propre("Log fires crackle softly in the hearths; the quiet echo of a large stone hall.") == \
        "Log fires crackle softly in the hearths; the quiet echo of a large stone hall."
    assert t3.ambiance_propre("Quiet room tone, a faint breeze.") == "A faint breeze."
    for vide in ("Quiet room tone", "Silence.", "No sound.", "", None):
        assert t3.ambiance_propre(vide) == t3.AMBIANCE_DEFAUT
    assert "room tone" not in t3.CONSIGNE_DESSIN.replace("never a hum, a drone or a room tone", "")


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
        if chemin == "/video-h3/finaliser":           # la 4K rend son film dans « finalisation »
            film = self.job()["id"]
            rendu = self.job()
            self.jobs[rendu["id"]]["finalisation"] = {"film": film}
            return 200, rendu
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
    sortie["pano.png"] = b"\x89PNG pano"
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
    assert etat["faites"] == [e for e in t3.Tour.ETAPES if e not in ("mesure", "plan")]   # sans mesure, sans plan
    groupes = [c for m, c, x in studio.appels if "/groupe/" in c]
    # 30 s par défaut : 6 clips de 60°, en 2 groupes de 3 (le tour v3 de l'atelier)
    assert groupes == ["/video-h3/fiches/%s/tour360/%s/groupe/%d" % ("a" * 12, etat["id"], k) for k in (0, 1)]
    assert not any(c == "/video-h3/creer" for _m, c, _x in studio.appels)
    clips = [c for g in etat["groupes"] for c in g["clips"]]
    assert [(c["a"], c["b"]) for c in clips] == [(60 * k, 60 * (k + 1)) for k in range(6)]
    assert [c["arret"] for c in clips] == [False] * 5 + [True]
    assert all(n == ["sofa"] or n == [] for g in etat["groupes"] for n in g["sujets"])
    montage = next(x for m, c, x in studio.appels if c == "/video-h3/montage")
    assert montage["clips"] == etat["troncons"] and montage["lieux"] == ["tour"] * 2
    assert etat["film"] and (tmp_path / "cartes" / "sofa.png").is_file() and (tmp_path / "pano.png").is_file()
    assert json.loads((tmp_path / "tour.json").read_text(encoding="utf-8"))["statut"] == "fini"
    # des invites écrites par un code plus ancien se réécrivent (château, 07/10 : le groupe rejoué était le clip v3)
    assert etat["invites_de"] == t3.SIGNATURE_INVITES
    for g in etat["groupes"]:
        g["invites"] = ["ancien texte"] * len(g["invites"])
    tour._groupes()
    assert all(i == "ancien texte" for g in etat["groupes"] for i in g["invites"])        # même code : relues
    etat["invites_de"] = "ancien"
    tour._groupes()
    assert all(i.startswith("subject_definitions:") for g in etat["groupes"] for i in g["invites"])


def test_la_reprise_garde_les_groupes_tournes_et_relance_l_echoue(t3, tmp_path):
    studio = FauxStudio()
    etat, tour = _tour(t3, tmp_path, studio)
    reel = studio.__call__

    def second_echoue(methode, chemin, corps=None):
        code, rendu = reel(methode, chemin, corps)
        if chemin.endswith("/groupe/1"):
            studio.jobs[rendu["id"]].update(status="failed", error="NOEUD_ABSENT")
        return code, rendu

    tour.appel = second_echoue
    tour.derouler()
    assert etat["statut"] == "arrete" and "NOEUD_ABSENT" in etat["erreur"] and len(etat["troncons"]) == 1
    assert "groupe_lance" not in etat
    etat.update(statut="en cours", erreur="")
    tour.appel = reel
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert [c for _m, c, _x in studio.appels if "/groupe/" in c][-2:] == [c for _m, c, _x in studio.appels
                                                                           if c.endswith("/groupe/1")]


def test_un_groupe_lance_n_est_pas_relance_a_la_reprise(t3, tmp_path):
    studio = FauxStudio()
    etat, tour = _tour(t3, tmp_path, studio)
    reel = studio.__call__

    def coupe(methode, chemin, corps=None):          # le Studio redémarre pendant l'attente du groupe 0
        lance = etat.get("groupe_lance") or {}
        if methode == "GET" and chemin == "/jobs/" + lance.get("job", "-"):
            raise RuntimeError("Studio redémarré")
        return reel(methode, chemin, corps)

    tour.appel = coupe
    tour.derouler()
    assert etat["statut"] == "arrete" and etat["groupe_lance"]["groupe"] == 0
    etat.update(statut="en cours", erreur="")
    tour.appel = reel
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert sum(c.endswith("/groupe/0") for _m, c, _x in studio.appels) == 1


def _finition(studio):
    return [(c, x) for m, c, x in studio.appels if m == "POST" and c in (
        "/video-h3/finaliser", "/chanson/creer", "/video-h3/musique", "/video-h3/fluidifier", "/video-h3/compresser")]


def test_le_personnage_choisit_sa_place_et_sa_tenue_et_le_tour_s_y_regle(t3, tmp_path):
    studio, demandes = FauxStudio(), []

    def chat(consigne, images):
        if "will appear in a slow 360" in consigne:
            assert "sofa: a cream sofa" in consigne and "Leila" not in consigne    # jamais nommée (07/10)
            return '{"pres_de": "sofa", "action": "reading a book on the sofa", "tenue": "a cosy grey cardigan"}'
        if consigne == t3.CONSIGNE_PEINTURE:                  # le juge voit la vue avant / après
            if images[1] == t3._data_url(b"vue faux"):
                return '{"personnes": 1, "autre": "a second stone fireplace next to the wardrobe"}'
            return '{"personnes": 1, "autre": ""}'
        return _chat(consigne, images)

    def personne(fid, tenue):
        demandes.append((fid, tenue))
        fiche = {"nom": "Leila", "description": "Leila, a young woman with long dark hair"}
        return fiche if tenue is None else dict(fiche, tenue=b"\x89PNG tenue", visage=b"\x89PNG visage",
                                                vues={"visage_face": b"\x89PNG gros plan",
                                                      "visage_trois_quarts": b"\x89PNG gros plan 3/4",
                                                      "pied_face": b"\x89PNG pied", "pied_trois_quarts": b"\x89PNG 3/4"})
    peints = []

    def peindre(pano, cap, fx, texte, images):
        peints.append((cap, texte, images))
        if len(peints) == 1:                                  # 1er essai : la pièce a changé (cheminée inventée)
            return b"faux", {"cap": cap + 20.0, "demi": 15.2, "avant": b"vue", "apres": b"vue faux"}
        # la peinture tombe un peu à côté du cap visé ; plus large que la personne (son ombre) : acceptée
        return pano, {"cap": cap + 4.0, "demi": 3.0, "avant": b"vue", "apres": b"vue juste"}
    etat, tour = _tour(t3, tmp_path, studio, chat=chat)
    tour.personne_, tour.peindre = personne, peindre
    t3.poser_personnage(etat, {"fiche": "c978c4e9daaa"})
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert [t for _f, t in demandes if t] == ["a cosy grey cardigan"]           # la tenue, faite une fois
    assert (tmp_path / "cartes" / "perso_visage_face.png").read_bytes() == b"\x89PNG gros plan"
    assert (tmp_path / "cartes" / "perso_pied_trois_quarts.png").read_bytes() == b"\x89PNG 3/4"
    # peinte une fois dans le panorama, au cap du sofa, avec le gros plan de face et la photo en pied de face
    assert len(peints) == 2 and peints[0][0] == 0.0 and peints[0][2] == [b"\x89PNG gros plan", b"\x89PNG pied"]
    assert "a cosy grey cardigan" in peints[0][1] and (tmp_path / "pano_sans_personnage.png").is_file()
    assert "cream sofa" not in peints[0][1]                 # l'élément n'est pas décrit : décrit, il est repeint
    assert "Leila" not in peints[0][1]                      # ni nommée (07/10)
    assert (tmp_path / "pano.png").read_bytes() != b"faux" and (tmp_path / "pano_refuse_1.png").read_bytes() == b"faux"
    assert any(j["etape"] == "peinture_refusee" for j in etat["journal"])
    perso = etat["cartes"][-1]
    # recette du 07/10 : gros plans du visage coiffe comprise + photos en pied en hauteur, dans la tenue du lieu
    assert perso["personne"] and perso["dans_pano"]
    assert perso["images"] == ["perso_visage_face", "perso_visage_trois_quarts", "perso_pied_face",
                               "perso_pied_trois_quarts"]
    # son corps, pas la bande changée (ombre comprise) : le cap visé (0) ramené dans la bande [1, 7], ± 5°
    assert (perso["a0"], perso["a1"]) == (-4.0, 6.0)
    assert perso["description"] == "a young woman with long dark hair, wearing a cosy grey cardigan"
    # le tour part à 90° d'elle, et reste épinglé partout (« the 360° shall be done continuously as before »)
    assert etat["reglages_camera"]["cap_depart"] == -89.0
    clips = [c for g in etat["groupes"] for c in g["clips"]]
    assert clips[0]["a"] == -89.0
    # sa place (et son feu) sans épingle ni clé de fin : épinglée, elle restait figée comme une photo (07/10)
    a0, a1, ecart = etat["zones"][0]
    assert not ecart
    assert [c["fin"] for c in clips] == [not t3.chaine.dans(c["b"], a0, a1) for c in clips]
    assert not all(c["fin"] for c in clips) and clips[-1]["fin"]
    for i, c in enumerate(clips):
        assert not any(t3.chaine.dans(cap, a0, a1) for cap in t3.chaine.epingles(c, i % 3 > 0, etat["zones"]).values())
    invites = " ".join(c.get("invite") or json.dumps(c) for c in clips)
    assert "Leila" not in invites and "sits " not in invites and "enters from" not in invites
    assert [z[2] for z in etat["zones"]] == [t3.ECART_VIVANT]
    with pytest.raises(ValueError, match="déjà écrit"):
        t3.poser_personnage(etat, {"fiche": "c978c4e9daaa"})


def test_le_volume_du_personnage_dans_la_vue_vient_de_sa_place_du_plan(t3):
    # château, 07/10 : à 6 m, caméra à 1,6 m du sol ; au milieu de la vue, pieds sous l'horizon, 1,8 m de haut
    x0, y0, x1, y1 = t3.boite_personne({"x": 3.3, "z": 5.0}, 1.6, 904.0)
    d = math.hypot(3.3, 5.0)
    assert abs((x0 + x1) / 2 - t3.VUE_L / 2) < 1
    pieds, tete = t3.VUE_H / 2 + 904 * 1.6 / d, t3.VUE_H / 2 + 904 * (1.6 - 1.8) / d
    assert y0 < tete < pieds < y1 <= t3.VUE_H
    assert pieds - tete == pytest.approx(904 * 1.8 / d, abs=1)
    assert (x1 - x0) < 200                                   # un corps, pas une bande de la pièce
    # plus près : plus grand ; sur la caméra : refusé
    assert t3.boite_personne({"x": 0.0, "z": 2.5}, 1.6, 904.0)[3] == t3.VUE_H
    with pytest.raises(ValueError):
        t3.boite_personne({"x": 0.0, "z": 0.1}, 1.6, 904.0)


def test_la_consigne_qwen_du_personnage_ne_nomme_ni_lui_ni_les_meubles(t3):
    t = t3.texte_personnage_qwen("pouring wine into a goblet", "a deep green wool gown", 3)
    assert "<image2>, <image3>, <image4>" in t and "<image5>" not in t
    assert "a deep green wool gown" in t and t3.GESTE_DEFAUT in t and "wine" not in t
    assert "Leila" not in t and "the whole body" in t


def test_qwen_ne_repeint_que_le_masque(sandbox):
    import zlib
    rq = importlib.import_module("retouche_qwen")
    png = rq.masque_rectangle(8, 4, (2, 1, 5, 3))
    assert png.startswith(b"\x89PNG")
    brut = zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])
    lignes = [brut[i * 25 + 1:(i + 1) * 25] for i in range(4)]
    assert lignes[0] == lignes[3] == b"\x00" * 24
    assert lignes[1] == lignes[2] == b"\x00" * 6 + b"\xff" * 9 + b"\x00" * 9
    d = rq.demande(b"vue", [b"a", b"b"], "texte", 7, masque=png, maison=True)
    g = d["graphe"]
    assert g["41"]["inputs"]["latent_image"] == ["53", 0] and g["53"]["class_type"] == "SetLatentNoiseMask"
    assert g["52"]["inputs"]["pixels"] == ["10", 0] and "masque.png" in d["refs"]
    assert {"ImageToMask", "VAEEncode", "SetLatentNoiseMask"} <= set(d["classes"])
    assert d["base_poids"] == "/poids"
    # sans masque : la retouche entière d'avant, poids du disque Modal
    d = rq.demande(b"vue", [b"a"], "texte")
    assert "50" not in d["graphe"] and d["base_poids"] == rq.DOSSIER_POIDS


def test_la_finition_va_4k_musique_60_images_puis_compression(t3, tmp_path):
    studio = FauxStudio()
    etat, tour = _tour(t3, tmp_path, studio)
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    f = etat["finition"]
    appels = _finition(studio)
    assert [c for c, _x in appels] == ["/video-h3/finaliser", "/chanson/creer", "/video-h3/musique",
                                       "/video-h3/fluidifier", "/video-h3/compresser"]
    assert appels[0][1] == {"job": etat["film"], "echelle": "4k", "ou": "modal"}
    film_4k = studio.jobs[f["finalisation"]]["finalisation"]["film"]
    assert appels[1][1]["duree"] == "1" and appels[1][1]["lora"] is True and appels[1][1]["ou"] == "modal"
    assert appels[2][1]["film"] == film_4k and appels[2][1]["chanson"] == f["chanson"]
    # le chemin se mesure sur le montage d'avant la 4K : la 4K efface la texture d'un mur nu
    assert appels[3][1] == {"job": f["musique"], "chemin": etat["film"]}
    assert appels[4][1] == {"job": f["fluide"]}
    assert etat["film_final"] == f["compresse"] == f["film"]


def test_un_tour_tourne_ici_a_sa_musique_ici(t3, tmp_path):
    studio = FauxStudio()
    etat, tour = _tour(t3, tmp_path, studio)
    etat["ou"] = "maison"
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert [x for c, x in _finition(studio) if c == "/chanson/creer"][0]["ou"] == "ici"


def test_sans_musique_ni_carte_le_tour_finit_quand_meme(t3, tmp_path):
    studio = FauxStudio()
    etat, tour = _tour(t3, tmp_path, studio)
    reel = studio.__call__

    def refus(methode, chemin, corps=None):
        if chemin in ("/chanson/creer", "/video-h3/fluidifier"):
            studio.appels.append((methode, chemin, corps))
            return 409, {"detail": "Pas de carte ici."}
        return reel(methode, chemin, corps)

    tour.appel = refus
    tour.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    f = etat["finition"]
    assert "409" in f["sans_musique"] and "409" in f["sans_fluide"]
    compresser = next(x for c, x in _finition(studio) if c == "/video-h3/compresser")
    assert compresser == {"job": studio.jobs[f["finalisation"]]["finalisation"]["film"]}
    # reprise : rien n'est relancé, ni ce qui a réussi ni ce qui a été écarté
    avant = len(_finition(studio))
    etat["faites"].remove("finition")
    tour.appel = reel
    tour.derouler()
    assert etat["statut"] == "fini" and len(_finition(studio)) == avant


def test_la_finition_se_regle_et_refuse_l_inconnu(t3):
    assert t3.lire_finition(None) == t3.FINITION_DEFAUT
    sortie = t3.lire_finition({"musique": "", "fluide": 0})
    assert sortie["musique"] == "" and sortie["fluide"] is False and sortie["4k"] is True
    with pytest.raises(ValueError, match="Finition"):
        t3.lire_finition({"8k": True})
    etat = t3.nouvel_etat({"id": "a" * 12, "nom": "Salon", "genre": "decor"}, finition={"4k": False, "musique": ""})
    assert etat["reglages_finition"]["4k"] is False


def test_finition_sans_4k_ni_musique_fluidifie_le_montage_sans_chemin(t3, tmp_path):
    studio = FauxStudio()
    etat = t3.nouvel_etat({"id": "a" * 12, "nom": "Salon", "genre": "decor"}, "modal",
                          finition={"4k": False, "musique": "", "compresser": False})
    (tmp_path / "photo.png").write_bytes(b"\x89PNG photo")
    t3.Tour(etat, tmp_path, studio, _chat, _panorama, decouper=lambda png, x0, x1: png,
            dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert _finition(studio) == [("/video-h3/fluidifier", {"job": etat["film"]})]
    assert etat["film_final"] == etat["finition"]["fluide"]


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


def test_la_taille_des_references_se_choisit_par_tour(t3):
    # 07/10 : essai « match » contre « max » sur le château (identité de Leila)
    decor = {"id": "a" * 12, "nom": "Salon", "genre": "decor"}
    assert t3.nouvel_etat(decor)["ref_image_size"] == "match"
    assert t3.nouvel_etat(decor, ref_image_size="max")["ref_image_size"] == "max"
    with pytest.raises(ValueError, match="match"):
        t3.nouvel_etat(decor, ref_image_size="grand")


def test_le_verdict_de_la_peinture_veut_une_personne_et_rien_d_autre(t3):
    assert t3.verdict_peinture('{"personnes": 1, "autre": ""}') is None
    assert t3.verdict_peinture('{"personnes": 1, "autre": "none"}') is None
    assert "2 personne" in t3.verdict_peinture('{"personnes": 2, "autre": ""}')
    assert "cheminée" not in t3.verdict_peinture('{"personnes": 1, "autre": "a second fireplace"}')
    assert "second fireplace" in t3.verdict_peinture('{"personnes": 1, "autre": "a second fireplace"}')
    assert "illisible" in t3.verdict_peinture("oui")


def test_seul_un_grand_feu_espace_ses_epingles_une_torche_reste_epinglee(t3):
    # château, 07/10 : les torches espaçaient les épingles sur 150° et H3 y a inventé une seconde Leila
    tour = t3.Tour.__new__(t3.Tour)
    tour.etat = {"cartes": [
        {"nom": "torche", "description": "A tall wrought-iron standing torch with an open flame", "a0": -30, "a1": -20},
        {"nom": "cheminee", "description": "A huge stone fireplace with a blazing log fire", "a0": 10, "a1": 30},
        {"nom": "bougies", "description": "A row of lit candles", "a0": 100, "a1": 110}]}
    zones = tour._zones(36.6)
    assert len(zones) == 1 and zones[0][2] == t3.ECART_VIVANT and zones[0][0] < 10 < 30 < zones[0][1]
    assert t3.vivant(tour.etat["cartes"][0])                  # la torche reste dite en mouvement dans l'invite
