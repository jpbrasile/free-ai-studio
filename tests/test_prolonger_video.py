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
    for ident in ("duree@1", "loueur@1", "traduire@1", "enrichir@1", "definition@1"):
        assert ident in ids, sorted(ids)
    # La suite part toujours chez le loueur : pas de choix « carte de ce PC ».
    assert "ou_calculer@1" not in ids
    assert ids["duree@1"]["choix"][0]["nom"].endswith("s de plus")


def test_prolonger_est_une_brique_du_loueur_seul(composite):
    assert "video_prolonger" in composite.LOUEUR_SEUL
    assert composite.BUDGET_PAR_BRIQUE["video_prolonger"] == "video"
    assert composite.donnees_de("video_prolonger")["sort"] == "oui"


def test_le_pretraitement_prepare_la_consigne_d_une_etape_qui_recoit_une_video(
        composite, monkeypatch):
    monkeypatch.setattr(composite, "appeler_le_modele", lambda _c: "a lighthouse")
    pret = composite.pretraiter_par_le_chat(
        etape_prolonger(composite, enrichir="non"), b"\x00\x00\x00\x18ftypmp42")
    assert pret == {"avant": "un phare", "apres": "a lighthouse", "enrichie": False}
