"""La fluidification à 60 images/s (PLAN 21.6 étape 5) : le script envoyé à la carte d'ici, ses phrases, et l'AV1
qui garde la cadence du film au lieu de tout refaire à 24 images/s."""
import base64
import importlib
import json
import shutil
import subprocess

import pytest


@pytest.fixture
def fl(sandbox):
    return importlib.import_module("fluide")


def test_le_script_compile_et_porte_la_demande(fl):
    script = fl.construire_script(b"film", b"montage")
    compile(script, "fluide_script.py", "exec")
    d = json.loads(base64.b64decode(script.split('b64decode("')[1].split('"')[0]).decode())
    assert base64.b64decode(d["video"]) == b"film" and base64.b64decode(d["chemin"]) == b"montage"
    assert d["ips"] == 60 and d["noeud"] == fl.NOEUD and d["fichiers"] == list(fl.FICHIERS)
    # les deux lectures du film image par image ne doivent jamais dupliquer une image (06/10 : 244 lues pour 243)
    assert script.count('"-fps_mode", "passthrough"') == 2
    assert json.loads(base64.b64decode(fl.construire_script(b"film").split('b64decode("')[1].split('"')[0])
                      )["chemin"] == ""


def test_phrases_d_echec(fl):
    assert "GIMM-VFI" in fl.phrase_d_echec("... GIMM_ABSENT ...")
    assert "nombre d'images" in fl.phrase_d_echec("CHEMIN_ECART 244 images mesurées, 243 dans le film")
    assert fl.phrase_d_echec("autre chose") == ""


def test_un_tour_de_30_s_en_4k_tient_dans_le_plafond(fl):
    assert fl.estimation_s(720, 2160) == pytest.approx(761.2)
    assert fl.tient(720, 2160) and fl.tient(720, 768)
    assert not fl.tient(100000, 2160)
    with pytest.raises(ValueError):
        fl.demande(b"x" * (fl.VIDEO_MAX_OCTETS + 1))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
@pytest.mark.parametrize("ips, attendu", [("60", 60), ("24", 24), ("24.77", 24), ("59.94", 60)])
def test_l_av1_garde_la_cadence_du_film(sandbox, tmp_path, ips, attendu):
    montage = importlib.import_module("montage")
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=%s:duration=0.5" % ips,
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    assert montage.cadence_av1(clip) == attendu
