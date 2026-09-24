"""La brique « Prolonger la vidéo » (24/09/2026).

Le modele loue ne fait que 5 s (81 images). Demande du proprietaire : 5 s est
un minimum d'usage, 10 s ou plus serait mieux, et « le recollage en un clip est
un composite du studio ». Un second clip part de la derniere image du premier ;
les deux sont recolles, la premiere image du second retiree.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess

import pytest

AVEC_FFMPEG = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                 reason="ffmpeg absent")


@pytest.fixture
def composite(sandbox):
    return sandbox.composite


def clip(tmp_path, nom, couleur, images=17):
    """Un petit mp4 d'une couleur, 16 images/s, comme le modele loue."""
    chemin = tmp_path / nom
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=%s:s=64x48:r=16" % couleur, "-frames:v", str(images),
                    "-pix_fmt", "yuv420p", str(chemin)], check=True)
    return chemin.read_bytes()


def images_de(tmp_path, video):
    chemin = tmp_path / "compte.mp4"
    chemin.write_bytes(video)
    sortie = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                             "-show_entries", "stream=nb_read_frames", "-of", "json",
                             str(chemin)], capture_output=True, text=True, check=True)
    return int(json.loads(sortie.stdout)["streams"][0]["nb_read_frames"])


# --- Le montage ---------------------------------------------------------------

@AVEC_FFMPEG
def test_la_derniere_image_est_celle_de_la_fin(sandbox, tmp_path):
    import montage

    png = montage.derniere_image(clip(tmp_path, "rouge.mp4", "red"))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


@AVEC_FFMPEG
def test_le_recollage_ne_montre_pas_deux_fois_l_image_de_jointure(sandbox, tmp_path):
    import montage

    a, b = clip(tmp_path, "a.mp4", "red"), clip(tmp_path, "b.mp4", "blue")
    # 17 + 17 - 1 : la premiere image de la suite EST la derniere du debut.
    assert images_de(tmp_path, montage.recoller(a, b)) == 33


@AVEC_FFMPEG
def test_une_image_perdue_au_recollage_arrete_tout(sandbox, tmp_path, monkeypatch):
    """24/09 : ffmpeg 7.1.5 perdait une image que le 6.1 gardait. Le recollage
    recompte ; un clip ampute n'est jamais rendu."""
    import montage

    a, b = clip(tmp_path, "a.mp4", "red"), clip(tmp_path, "b.mp4", "blue")
    vrai = montage.images
    appels = []

    def compte(chemin):
        appels.append(chemin.name)
        n = vrai(chemin)
        return n - 1 if chemin.name == "ab.mp4" else n
    monkeypatch.setattr(montage, "images", compte)
    with pytest.raises(montage.MontageImpossible) as refus:
        montage.recoller(a, b)
    assert "32 images au lieu de 33" in str(refus.value)
    assert appels == ["a.mp4", "b.mp4", "ab.mp4"]


@AVEC_FFMPEG
def test_le_recollage_garde_la_cadence_du_clip(sandbox, tmp_path):
    import montage

    a = clip(tmp_path, "a.mp4", "red")
    sortie = tmp_path / "ab.mp4"
    sortie.write_bytes(montage.recoller(a, clip(tmp_path, "b.mp4", "blue")))
    assert montage._cadence(sortie) == (16, 1)


def test_sans_ffmpeg_la_brique_le_dit(sandbox, monkeypatch):
    import montage

    monkeypatch.setattr(montage.shutil, "which", lambda _n: None)
    with pytest.raises(montage.MontageImpossible) as refus:
        montage.derniere_image(b"x")
    assert "ffmpeg" in str(refus.value) and "demarrer.cmd" in str(refus.value)


def test_une_video_illisible_se_refuse_en_francais(sandbox):
    import montage

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg absent")
    with pytest.raises(montage.MontageImpossible):
        montage.derniere_image(b"pas une video")


# --- La brique dans la chaine ---------------------------------------------------

def etape_prolonger(composite, **reglages):
    etape = composite.chaine_depuis_briques(["video_rapide", "video_prolonger"],
                                            composite.charger_registre())["etapes"][1]
    return dict(etape, demande="un phare", reglages=reglages)


@AVEC_FFMPEG
def test_prolonger_part_de_la_derniere_image_toujours_chez_le_loueur(composite, tmp_path):
    video = clip(tmp_path, "a.mp4", "red")
    etape = dict(etape_prolonger(composite, duree="5"), texte_prepare="a lighthouse")
    usage, demande = composite.demande_du_travail(etape, video)
    assert usage == "video"
    assert demande["description"] == "a lighthouse"
    assert demande["ou_calculer"] == "toujours-modal" and demande["qualite"] == "rapide"
    assert base64.b64decode(demande["image_depart"])[:4] == b"\x89PNG"
    assert demande["duree"] == "5"


def test_une_chaine_de_10_s_se_lie_et_montre_ses_reglages(composite):
    c = composite.chaine_depuis_briques(["video_rapide", "video_prolonger"],
                                        composite.charger_registre())
    ids = {p["id"]: p for p in composite.proprietes_montrees(c)}
    for ident in ("duree@1", "loueur@1", "traduire@1", "enrichir@1", "definition@1", "clips@1"):
        assert ident in ids, sorted(ids)
    # La suite part toujours chez le loueur : pas de choix « carte de ce PC ».
    assert "ou_calculer@1" not in ids
    assert ids["duree@1"]["choix"][0]["nom"].endswith("s par clip ajouté")
    # Le premier clip aussi, puisqu'il est prolonge : une seule taille, louee.
    assert "ou_calculer@0" not in ids
    assert ids["definition@0"]["choix"][0]["nom"].startswith("832 × 480 chez le loueur")
    assert "1280" not in ids["definition@0"]["choix"][0]["nom"]
    # La duree et le nombre de clips changent le prix : le verdict se refait.
    assert ids["duree@0"]["refait"] and ids["duree@1"]["refait"] and ids["clips@1"]["refait"]
    assert [c["valeur"] for c in ids["clips@1"]["choix"]] == ["1", "2", "3", "4"]


def test_prolonger_est_une_brique_du_loueur_seul(composite):
    assert "video_prolonger" in composite.LOUEUR_SEUL
    assert composite.BUDGET_PAR_BRIQUE["video_prolonger"] == "video"
    assert composite.donnees_de("video_prolonger")["sort"] == "oui"


def test_prolonger_reprend_la_description_deja_preparee(composite, monkeypatch):
    """24/09, course 3f2a75ba : deux descriptions du meme phare de part et d'autre
    de la jointure. La suite reprend celle du debut, sans rappeler le chat."""
    appels = []
    monkeypatch.setattr(composite, "appeler_le_modele",
                        lambda c: appels.append(c) or "A lighthouse in the rain, waves, beam turning.")
    c = composite.chaine_depuis_briques(["video_rapide", "video_prolonger"],
                                        composite.charger_registre())
    c["phrase"] = "un phare breton sous la pluie"
    vus = []

    def lancer(etape, entree):
        vus.append(etape.get("texte_prepare"))
        return b"\x00\x00\x00\x18ftypmp42"

    trace = composite.executer(c, lancer, None, garde_budget=lambda _e: None,
                               pretraiter=composite.pretraiter_par_le_chat)
    assert trace["resultat"] == "rendu", trace
    assert len(appels) == 1, "un seul appel au chat pour les deux clips"
    assert vus[0] == vus[1] == "A lighthouse in the rain, waves, beam turning."
    assert trace["etapes"][1]["pretraitement"]["reprise"] is True
    assert "reprise" not in trace["etapes"][0]["pretraitement"]


def test_prolonger_redemande_si_la_consigne_ou_le_reglage_change(composite, monkeypatch):
    nuit = "a white lighthouse at night in the rain"
    monkeypatch.setattr(composite, "appeler_le_modele", lambda _c: nuit)
    precedent = {"avant": "un phare", "apres": "A lighthouse.", "enrichie": True}
    etape = dict(etape_prolonger(composite), demande="un phare la nuit",
                 pretraitement_precedent=precedent)
    assert composite.pretraiter_par_le_chat(etape, b"x")["apres"] == nuit
    etape = dict(etape_prolonger(composite, enrichir="non"), pretraitement_precedent=precedent)
    assert "reprise" not in composite.pretraiter_par_le_chat(etape, b"x")


def test_la_page_dit_quand_la_description_est_reprise(sandbox):
    from fastapi.testclient import TestClient

    page = TestClient(sandbox.app, base_url="http://127.0.0.1:8020").get(
        "/composite", headers={"Authorization": "Bearer cle-sandbox-de-test"}).text
    assert "(p.reprise ?" in page and "même description que l’étape précédente" in page


def test_le_pretraitement_prepare_la_consigne_d_une_etape_qui_recoit_une_video(
        composite, monkeypatch):
    monkeypatch.setattr(composite, "appeler_le_modele", lambda _c: "a lighthouse")
    pret = composite.pretraiter_par_le_chat(
        etape_prolonger(composite, enrichir="non"), b"\x00\x00\x00\x18ftypmp42")
    assert pret == {"avant": "un phare", "apres": "a lighthouse", "enrichie": False}


# --- 24/09, la page avant de lancer ------------------------------------------

def chaine_10_s(composite, **proprietes):
    c = composite.chaine_depuis_briques(["video_rapide", "video_prolonger"],
                                        composite.charger_registre())
    c["proprietes"] = dict(proprietes)
    return c


def test_le_cout_suit_la_duree_et_le_nombre_de_clips(composite):
    import video

    un = video.prix_estime("rapide", "1")
    etapes = composite.etapes_reglees(chaine_10_s(
        composite, **{"duree@0": "1", "duree@1": "1", "clips@1": "3"}))
    assert etapes[0]["cout_max_usd"] == un
    assert etapes[1]["cout_max_usd"] == round(3 * un, 4)
    # Kaggle : gratuit, quel que soit le nombre de clips.
    etapes = composite.etapes_reglees(chaine_10_s(
        composite, **{"loueur@1": "kaggle", "clips@1": "3"}))
    assert etapes[1]["cout_max_usd"] == 0.0


def test_la_garde_compte_un_travail_par_clip(composite, monkeypatch):
    import video

    monkeypatch.setattr(video, "budget_verifier",
                        lambda _g, _d: {"cout_max_usd": 0.5, "plafond_usd": 10, "usd": 0})
    etape = composite.etapes_reglees(chaine_10_s(composite, **{"clips@1": "3"}))[1]
    assert composite.mesure_du_noeud(etape)["cout_max_usd"] == 1.5


def test_le_premier_clip_prolonge_part_chez_le_loueur(composite):
    etapes = composite.etapes_reglees(chaine_10_s(composite, **{"ou_calculer@0": "maison-si-libre"}))
    assert etapes[0]["reglages"]["ou_calculer"] == "toujours-modal"
    assert composite.loueur_seul(etapes[0])
    etape = dict(etapes[0], demande="un phare", suivante="video_prolonger")
    _, demande = composite.demande_du_travail(etape, None)
    assert demande["ou_calculer"] == "toujours-modal"


def test_une_video_de_la_carte_d_ici_ne_se_prolonge_pas(composite):
    c = composite.chaine_depuis_briques(["video_maison", "video_prolonger"],
                                        composite.charger_registre())
    verdict = composite.verifier(c, sonde_budget=lambda _e: None, sonde_carte=lambda _m: (True, "", {}))
    assert verdict["atteignable"] == composite.NON
    assert "prolongation_impossible" in verdict["motifs"]


@pytest.mark.parametrize("voulu, attendu, note", [
    (10, {"duree@0": "5", "duree@1": "5", "clips@1": "1"}, False),
    (2, {"duree@0": "2"}, False),
    (15, {"duree@0": "5", "duree@1": "5", "clips@1": "2"}, False),
    (12, {"duree@0": "5", "duree@1": "4", "clips@1": "2"}, True),
    (60, {"duree@0": "5", "duree@1": "5", "clips@1": "4"}, True),
])
def test_la_duree_demandee_se_repartit_entre_les_clips(composite, voulu, attendu, note):
    c = chaine_10_s(composite)
    valeurs, sans_effet = composite.appliquer_proposees(c, {"proprietes": {"duree": voulu}})
    assert valeurs == attendu
    assert bool(sans_effet) is note, sans_effet


def test_le_lecteur_de_phrase_laisse_la_suite_sur_la_meme_scene(composite):
    reponse = json.dumps({"noeuds": ["video_rapide", "video_prolonger"],
                          "consignes": ["Un phare breton sous la pluie.",
                                        "Prolonge la video de 5 secondes."],
                          "proprietes": {"duree": 10}})
    graphe = composite.compiler("une video de 10 s d'un phare", lambda _c: reponse)
    assert [n.get("consigne") for n in graphe["noeuds"]] == ["Un phare breton sous la pluie.", ""]
    assert "video_prolonger" in composite.CONSIGNE


def test_la_suite_sans_description_reprend_la_scene_d_avant(composite):
    vues = []

    def lancer(etape, _entree):
        vues.append(etape["demande"])
        return b"\x00\x00\x00\x18ftypmp42"

    c = chaine_10_s(composite)
    c["phrase"] = "une video de 10 s"
    c["etapes"][0]["consigne"] = "un phare breton"
    composite.executer(c, lancer, None, garde_budget=lambda _e: None)
    assert vues == ["un phare breton", "un phare breton"]
    # Ecrite, elle fait evoluer la scene.
    vues.clear()
    c["etapes"][1]["consigne"] = "le phare s'eteint"
    composite.executer(c, lancer, None, garde_budget=lambda _e: None)
    assert vues == ["un phare breton", "le phare s'eteint"]


def test_prolonger_lance_un_travail_par_clip(composite, monkeypatch):
    appels, gardes = [], []
    monkeypatch.setattr(composite, "_un_travail",
                        lambda _e, entree: appels.append(entree) or (entree + b"+"))
    monkeypatch.setattr(composite, "_budget_verifie", lambda e: gardes.append(e["brique"]))
    etape = {"brique": "video_prolonger", "reglages": {"clips": "3"}}
    assert composite.lancer_un_travail(etape, b"v") == b"v+++"
    assert appels == [b"v", b"v+", b"v++"]
    assert len(gardes) == 2, "la garde avant chaque clip au-dela du premier"


def test_un_arret_entre_deux_clips_garde_ceux_deja_payes(composite, monkeypatch):
    import threading

    arret = threading.Event()

    def un(_e, entree):
        arret.set()
        return entree + b"+"
    monkeypatch.setattr(composite, "_un_travail", un)
    etape = {"brique": "video_prolonger", "reglages": {"clips": "3"}, "arret": arret}
    assert composite.lancer_un_travail(etape, b"v") == b"v+"


def test_la_page_montre_le_cout_estime_et_la_suite_par_defaut(sandbox):
    from fastapi.testclient import TestClient

    page = TestClient(sandbox.app, base_url="http://127.0.0.1:8020").get(
        "/composite", headers={"Authorization": "Bearer cle-sandbox-de-test"}).text
    assert "function coutEstime(v)" in page and "Coût estimé" in page
    assert "function suiteParDefaut(v, i)" in page and "Description de la suite" in page


def test_le_premier_clip_prolonge_ne_promet_pas_la_carte_d_ici(composite):
    """Releve sur la page le 24/09 : « Sur votre carte si elle est libre » pour un
    clip qui part chez le loueur d'office."""
    verdict = composite.verifier(chaine_10_s(composite), sonde_budget=lambda _e: None,
                                 sonde_carte=lambda _m: (True, "", {}))
    premier = verdict["etapes"][0]["donnees"]
    assert premier["sort"] == "oui" and "carte" not in premier["phrase"]
    assert verdict["etapes"][0]["loue"] and verdict["etapes"][1]["prolonge"]
