"""Chanson : paroles chantees par YuE2-3B, sur Modal, Kaggle ou Colab.

Aucun appel reseau : Modal, Kaggle et le GPU ne sont jamais touches. Ce qui est
verifie ici, c'est ce qui se decide AVANT de lancer (demande bornee, plafond,
garde Kaggle, carte demandee) et que le script envoye au GPU est du Python valide.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
RESEAU = "http://192.168.1.20:8020"
PAROLES = "[Verse]\nPaper boats along the stream\n[Chorus]\nSing it low and sing it clear"


@pytest.fixture
def ch(sandbox, monkeypatch, tmp_path):
    """Le module chanson, avec un compteur de depense jetable."""
    module = sandbox.chanson
    monkeypatch.setattr(module, "BUDGET_FICHIER", tmp_path / "chanson-budget.json")
    return module


def test_demande_bornee(ch):
    with pytest.raises(ValueError):
        ch.preparer({"style": "pop", "paroles": "  "})
    with pytest.raises(ValueError):
        ch.preparer({"style": "", "paroles": PAROLES})
    with pytest.raises(ValueError):
        ch.preparer({"style": "pop", "paroles": "la " * 2000})

    plan = ch.preparer({"style": "English, folk", "paroles": PAROLES, "duree": "2", "graine": 7})
    d = plan["demande"]
    assert d["jetons"] == 3000 and d["graine"] == 7
    assert d["paroles"] == PAROLES
    assert d["revision"] == ch.MODELE["revision"]
    assert plan["resume_public"]["balise_ajoutee"] is False

    # Duree inconnue : la plus courte. Pas de section : un couplet, et c'est dit.
    plan = ch.preparer({"style": "pop", "paroles": "juste une ligne", "duree": "9", "graine": -3})
    assert plan["demande"]["jetons"] == 1500
    assert plan["demande"]["paroles"].startswith("[Verse]\n")
    assert plan["resume_public"]["balise_ajoutee"] is True
    assert 0 <= plan["demande"]["graine"] < 2 ** 31


def test_modal_garde_le_cache_kaggle_installe(ch):
    modal = ch.preparer({"style": "pop", "paroles": PAROLES}, "modal")["demande"]
    assert modal["cache"] == ch.CACHE_MODAL and modal["installer"] is False
    for ou in ("kaggle", "colab"):
        autre = ch.preparer({"style": "pop", "paroles": PAROLES}, ou)["demande"]
        assert autre["cache"] == "" and autre["installer"] is True


def test_script_et_carnet_sont_du_python_valide(ch):
    demande = ch.preparer({"style": "pop « é »", "paroles": PAROLES}, "colab")["demande"]
    script = ch.construire_script(demande)
    assert "__DEMANDE__" not in script
    compile(script, "chanson_job.py", "exec")

    carnet = ch.carnet_colab(demande)
    codes = [c["source"] for c in carnet["cells"] if c["cell_type"] == "code"]
    assert script in codes
    for source in codes:
        compile(source, "cellule", "exec")
    assert "CC BY-NC 4.0" in carnet["cells"][0]["source"]


def test_prix_compte_la_memoire(ch, monkeypatch):
    monkeypatch.setenv("MODAL_CPU", "1.0")
    attendu = 0.000222 + 0.0000131 + 0.00000222 * ch.MEMOIRE_MB / 1024
    assert ch.prix_seconde("L4") == pytest.approx(attendu)
    # Carte inconnue : comptee au prix de la plus chere, jamais moins.
    assert ch.prix_seconde("X9") > ch.prix_seconde("L40S") - 1e-12


def test_compteur_video_compte_aussi_cpu_memoire(sandbox, monkeypatch):
    """Jusqu'au 15/09, la video ne comptait que la carte : 18 % de moins en L4."""
    monkeypatch.setenv("MODAL_CPU", "1.0")
    monkeypatch.setenv("VIDEO_MEMORY_MB", "16384")
    assert sandbox.video.prix_seconde("L4") == pytest.approx(0.000222 + 0.0000131 + 0.00000222 * 16)


def test_plafond_refuse_avant_de_lancer(sandbox, ch, monkeypatch):
    lances = []
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_chanson", lambda *args: lances.append(args))
    ch.budget_ecrire(0, ch.BUDGET_MENSUEL_USD - 0.01, 3)

    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 429
    assert "Kaggle et Colab" in r.json()["detail"]
    assert lances == []

    ch.budget_ecrire(0, 0, 0)
    r = client.post("/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 200
    for _ in range(50):
        if lances:
            break
        time.sleep(0.02)
    assert len(lances) == 1 and lances[0][2] == "modal"


def test_modal_absent_503(sandbox, ch):
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 503


def test_echec_modal_encaisse_quand_meme(sandbox, ch, monkeypatch):
    def en_panne(*args, **kwargs):
        raise sandbox.BackendUnavailable("Modal unavailable: essai")

    monkeypatch.setattr(sandbox, "modal_execute", en_panne)
    jid = "f" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_chanson(jid, "print(1)", "modal")
    job = sandbox.read_job(jid)
    assert job["status"] == "failed"
    assert ch.budget_lire()["chansons"] == 1
    assert job["budget"]["chansons"] == 1


def test_kaggle_coupe_par_le_reseau(sandbox, ch):
    client = TestClient(sandbox.app, base_url=RESEAU)
    r = client.post("/chanson/creer", headers=CLE,
                    json={"ou": "kaggle", "style": "pop", "paroles": PAROLES})
    assert r.status_code == 403
    assert client.get("/chanson/etat", headers=CLE).json()["kaggle_permis"] is False

    # Le carnet Colab part chez la personne, sur son compte : pas de garde.
    r = client.post("/chanson/colab", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert json.loads(r.content)["nbformat"] == 4


def test_kaggle_demande_un_t4_seulement_pour_la_chanson(sandbox, monkeypatch):
    class Refus:
        returncode = 1
        stdout = ""
        stderr = "refus d'essai"

    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    monkeypatch.setenv("KAGGLE_USERNAME", "moi")
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: Refus())
    for jid, forme in (("d" * 32, "NvidiaTeslaT4"), ("e" * 32, None)):
        sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
        sandbox.run_kaggle(jid, "print(1)", True, True, machine_shape=forme)
        meta = json.loads((sandbox.JOBS / jid / "kaggle" / "kernel-metadata.json").read_text(encoding="utf-8"))
        assert meta.get("machine_shape") == forme
        assert sandbox.read_job(jid)["status"] == "failed"


def test_kaggle_arrete_le_notebook_a_son_delai(sandbox, monkeypatch):
    """Kaggle arrete lui-meme le notebook au delai (-t) : plus de notebook laisse en route."""
    appels = []

    class Refus:
        returncode = 1
        stdout = ""
        stderr = "refus d'essai"

    def faux_run(args, **kwargs):
        appels.append(list(args))
        return Refus()

    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    monkeypatch.setenv("KAGGLE_USERNAME", "moi")
    monkeypatch.delenv("KAGGLE_JOB_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(sandbox.subprocess, "run", faux_run)
    for jid, delai, attendu in (("a" * 32, 5400, "5400"), ("b" * 32, None, "3600")):
        sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
        sandbox.run_kaggle(jid, "print(1)", True, True, timeout_s=delai)
        push = [a for a in appels if a[:3] == ["kaggle", "kernels", "push"]][-1]
        assert push[push.index("-t") + 1] == attendu


def test_page_etat_et_jeton(sandbox, ch):
    client = TestClient(sandbox.app, base_url=LOCAL)
    page = client.get("/chanson")
    assert page.status_code == 200 and "cle-sandbox-de-test" in page.text
    assert client.get("/chanson/etat").status_code == 401
    etat = client.get("/chanson/etat", headers=CLE).json()
    assert etat["kaggle_permis"] is True
    assert etat["modele"]["licence"] == "CC BY-NC 4.0"
    assert etat["cout_max_modal_usd"] > 0

    jid = "0" * 32
    sandbox.write_job(jid, {"id": jid, "status": "succeeded", "artifacts": []})
    assert client.get(f"/chanson/jobs/{jid}/fichier?cle=faux").status_code == 401
    bon = sandbox.jeton_chanson(jid)
    assert bon != sandbox.jeton_video(jid)
    assert client.get(f"/chanson/jobs/{jid}/fichier?cle={bon}").status_code == 404
