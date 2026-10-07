"""Le chemin de la caméra d'un tour 360° et ses groupes de clips H3 (PLAN 21.6 étape 4, recette du tour v3 du 06/10 :
vues exactes épinglées tous les 7,5°, clips enchaînés par le latent)."""
import base64
import importlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


@pytest.fixture
def ch(sandbox):
    return importlib.import_module("tour360_chaine")


def _chemin(ch, **r):
    return ch.chemin(ch.lire_camera(r))


def test_le_tour_de_30_s_est_celui_de_l_atelier(ch):
    groupes = _chemin(ch)
    assert [len(g) for g in groupes] == [3, 3]
    assert [(c["a"], c["b"]) for g in groupes for c in g] == [(60 * k, 60 * (k + 1)) for k in range(6)]
    # les images épinglées du tour v3 (graphe.json du groupe 0, 06/10)
    assert sorted(ch.epingles(groupes[0][0], False)) == [15, 31, 46, 62, 77, 92, 108]
    assert sorted(ch.epingles(groupes[0][1], True)) == [36, 51, 66, 81, 95, 110, 125]
    assert ch.epingles(groupes[0][0], False)[62] == pytest.approx(60 * 62 / 123)


def test_chaque_camera_et_sa_duree(ch):
    g = _chemin(ch, camera="tour_gauche", duree_s=60)
    assert [len(x) for x in g] == [4, 4, 4] and g[0][0] == {"a": 0.0, "b": -30.0, "arret": False}
    assert g[-1][-1]["b"] == -360.0 and g[-1][-1]["arret"]
    assert sorted(ch.epingles(g[0][0], False)) == [31, 62, 92]              # 30° : 3 vues entre les clés
    g = _chemin(ch, camera="quart_de_tour", duree_s=10, cap_depart=200)
    assert g == [[{"a": -160.0, "b": -115.0, "arret": False}, {"a": -115.0, "b": -70.0, "arret": True}]]
    g = _chemin(ch, camera="aller_retour", duree_s=25, angle=-60)           # 5 clips -> 6, 3 aller + 3 retour
    assert [[(c["a"], c["b"], c["arret"]) for c in x] for x in g] == [
        [(0.0, -20.0, False), (-20.0, -40.0, False), (-40.0, -60.0, True)],
        [(-60.0, -40.0, False), (-40.0, -20.0, False), (-20.0, 0.0, True)]]


@pytest.mark.parametrize("reglages, phrase", [
    ({"camera": "tour_droite", "duree_s": 15}, "Trop rapide"),
    ({"camera": "quart_de_tour", "duree_s": 120}, "Trop lent"),
    ({"camera": "vol_plane"}, "Caméra inconnue"),
    ({"duree_s": 5}, "Durée du tour"),
    ({"camera": "aller_retour", "angle": 5}, "Angle"),
    ({"vitesse": 3}, "Caméra :"),
])
def test_les_reglages_impossibles_sont_refuses_avant_tout_calcul(ch, reglages, phrase):
    with pytest.raises(ValueError, match=phrase):
        ch.lire_camera(reglages)


def test_le_groupe_a_le_graphe_de_l_atelier(ch):
    clips = _chemin(ch)[0]
    sujets = [["sofa"], ["sofa", "lampe"], []]
    d = ch.demande_groupe(clips, ["invite %d" % i for i in range(3)], sujets,
                          {"sofa": b"\x89PNG sofa", "lampe": b"\x89PNG lampe"}, b"\x89PNG pano", 904.0, 11, 1680)
    g = d["graphe"]
    guides = [n for n in g.values() if n["class_type"] == "MiniMaxH3AddGuide"]
    # comme le tour v3 : 1 + 7 + 1 au clip de tête, 7 + 1 à chacun des suivants
    assert len(guides) == 25
    assert sorted(n["inputs"]["frame_idx"] for n in guides) == sorted(
        [0, -1, 15, 31, 46, 62, 77, 92, 108] + 2 * [-1, 36, 51, 66, 81, 95, 110, 125])
    assert g["b31"]["inputs"]["context_latent"] == ["14", 0] and g["c31"]["inputs"]["context_latent"] == ["b14", 0]
    assert g["b13"]["inputs"]["conditioning"] == ["b31", 0] and g["13"]["inputs"]["conditioning"] == ["19", 0]
    assert g["b17"]["inputs"]["images"] == ["b32", 0] and g["10"]["inputs"]["length"] == 124
    assert g["b10"]["inputs"]["length"] == 141 and g["c10"]["inputs"]["prompt"] == "invite 2"
    assert [g[k]["inputs"]["filename_prefix"] for k in ("18", "b18", "c18")] == ["h3/clip_1", "h3/clip_2", "h3/clip_3"]
    # chaque image chargée existe : carte envoyée, ou vue découpée sur la machine
    charge = {n["inputs"]["image"] for n in g.values() if n["class_type"] == "LoadImage"}
    assert charge == set(d["images"]) | set(d["vues"]["caps"])
    assert d["vues"]["caps"]["_ref_0.png"] == 0 and d["vues"]["caps"]["_ref_1.png"] == 60
    assert d["vues"]["caps"]["c_ref_0.png"] == 180 and base64.b64decode(d["images"]["b_ref_2.png"]) == b"\x89PNG lampe"
    assert {"MiniMaxH3MotionContext", "MiniMaxH3MotionContextTrim", "LoadImage"} <= set(d["classes"])
    assert d["assembler"] and d["coupe_s"] == 0 and d["delai_s"] == 1680
    with pytest.raises(ValueError):
        ch.demande_groupe(clips, ["a"], [[]], {}, b"", 904.0, 11, 60)


def test_les_zones_espacent_ou_retirent_les_epingles(ch):
    clip = _chemin(ch)[0][0]                                      # 0 -> 60°, épingles tous les 7,5°
    tout = ch.epingles(clip, False)
    # un feu vu de 20 à 50° : une épingle tous les 22,5° dans ce secteur (caps multiples de 22,5), 7,5° ailleurs
    feu = ch.epingles(clip, False, [(20.0, 50.0, 22.5)])
    assert sorted(round(c, 1) for c in tout.values()) == [7.3, 15.1, 22.4, 30.2, 37.6, 44.9, 52.7]
    assert sorted(round(c, 1) for c in feu.values()) == [7.3, 15.1, 22.4, 44.9, 52.7]
    # un personnage vu de 20 à 50° : aucune épingle dans ce secteur
    perso = ch.epingles(clip, False, [(20.0, 50.0, None)])
    assert sorted(round(c, 1) for c in perso.values()) == [7.3, 15.1, 52.7]
    assert set(perso) < set(feu) < set(tout)
    # un secteur à cheval sur 0° : à 360° près
    assert ch.dans(355.0, -10.0, 10.0) and ch.dans(-350.0, 5.0, 15.0) and not ch.dans(30.0, -10.0, 10.0)


def test_un_clip_sans_cle_d_arrivee_n_a_ni_reference_ni_epingle_de_fin(ch):
    clips = [dict(c) for c in _chemin(ch)[0]]
    clips[1]["fin"] = False
    d = ch.demande_groupe(clips, ["a", "b", "c"], [["sofa"], ["perso_tenue", "perso_visage"], []],
                          {"sofa": b"\x89PNG sofa", "perso_tenue": b"\x89PNG t", "perso_visage": b"\x89PNG v"},
                          b"\x89PNG pano", 904.0, 11, 1680, zones=[(50.0, 130.0, None)])
    g = d["graphe"]
    assert "b19" not in g and "19" in g and "c19" in g            # la fin du clip 2 n'est pas épinglée
    # ses deux images sont les photos du personnage, sans clé d'arrivée
    assert base64.b64decode(d["images"]["b_ref_0.png"]) == b"\x89PNG t" and "b_ref_0.png" not in d["vues"]["caps"]
    assert not [c for n, c in d["vues"]["caps"].items() if "_pin_" in n and 50 <= c <= 130]
    with pytest.raises(ValueError, match="premier clip"):
        ch.demande_groupe([dict(clips[0], debut=False)], ["a"], [[]], {}, b"", 904.0, 11, 60)


def test_le_script_decoupe_les_vues_et_recolle_les_clips(ch):
    d = ch.demande_groupe(_chemin(ch)[0][:1], ["x"], [[]], {}, b"\x89PNG pano", 904.0, 11, 60)
    script = ch.construire_script(d)
    compile(script, "groupe.py", "exec")
    assert script.index("if D.get(\"vues\"):") < script.index('(COMFY / "input").mkdir')
    assert "elif D.get(\"assembler\"):" in script and '"-f", "concat"' in script


def test_les_vues_de_la_machine_sont_celles_des_cles(ch):
    """Le code envoyé découpe chaque vue comme tour360_pano.vue, qui a fait les clés et les cartes."""
    np = pytest.importorskip("numpy")
    image = pytest.importorskip("PIL.Image")
    chemin = Path(importlib.import_module("tour360").__file__).with_name("tour360_pano.py")
    spec = importlib.util.spec_from_file_location("tour360_pano_vues", chemin)
    tp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tp)
    pano = np.random.default_rng(3).integers(0, 255, (256, 512, 3), dtype=np.uint8)
    tampon = io.BytesIO()
    image.fromarray(pano).save(tampon, format="PNG")
    caps = {"a.png": 0.0, "b.png": 97.5, "c.png": -172.0}
    d = {"vues": {"pano": base64.b64encode(tampon.getvalue()).decode(), "fx": 904.0, "l": 1344, "h": 768,
                  "caps": caps}, "images": {}}
    exec(ch._VUES, {"base64": base64, "D": d, "json": json})   # noqa: S102 -- le code même du script
    for nom, cap in caps.items():
        rendu = np.asarray(image.open(io.BytesIO(base64.b64decode(d["images"][nom]))))
        attendu = tp.vue(pano, cap, 904.0)
        assert rendu.shape == attendu.shape == (768, 1344, 3)
        assert np.abs(rendu.astype(int) - attendu.astype(int)).max() <= 1
