"""GET /jobs : une liste bornee en nombre ET en poids, sans casser ses lecteurs.

Point ouvert de PLAN.md (18/09/2026) : << la liste des travaux grossit sans
limite, elle franchira la nouvelle borne [2 000 000 d'octets de l'auto-test] a
son tour >>. Le nombre etait deja borne a 100 ; le poids d'une fiche ne l'etait
pas (stdout, stderr, code gardes entiers). Ces tests fixent le correctif du
26/09/2026 : sans parametre, rien ne change ; `limite` raccourcit, `abrege=1`
retire les champs sans borne, `X-Total-Count` dit combien il y en a en tout.
"""
from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"


def fiche(dossier, jid, date, **champs):
    (dossier / jid).mkdir(parents=True, exist_ok=True)
    job = {"id": jid, "status": "succeeded", "provider": "local"}
    job.update(champs)
    chemin = dossier / jid / "job.json"
    chemin.write_text(json.dumps(job), encoding="utf-8")
    # L'ordre suit la date de la fiche sur le disque : on la pose, on ne
    # l'attend pas.
    os.utime(chemin, (date, date))


def client(sandbox, monkeypatch, dossier):
    monkeypatch.setattr(sandbox, "JOBS", dossier)
    return TestClient(sandbox.app, base_url=LOCAL)


def test_sans_parametre_la_reponse_reste_une_LISTE_de_fiches_entieres(sandbox, monkeypatch,
                                                                      tmp_path):
    """Le lecteur d'avant (auto-test, scripts/sandbox.py jobs) lit une liste."""
    fiche(tmp_path, "ancien", 1000, stdout="bonjour")
    fiche(tmp_path, "recent", 2000, stdout="au revoir", code="print(1)")

    r = client(sandbox, monkeypatch, tmp_path).get("/jobs", headers=CLE)

    assert r.status_code == 200
    corps = r.json()
    assert isinstance(corps, list)
    assert [j["id"] for j in corps] == ["recent", "ancien"], "la plus recente d'abord"
    assert corps[0]["stdout"] == "au revoir" and corps[0]["code"] == "print(1)"
    assert r.headers["X-Total-Count"] == "2"


def test_le_nombre_est_borne_a_100_et_le_total_se_dit_quand_meme(sandbox, monkeypatch,
                                                                  tmp_path):
    for i in range(105):
        fiche(tmp_path, "t%03d" % i, 1000 + i)

    r = client(sandbox, monkeypatch, tmp_path).get("/jobs", headers=CLE)

    assert len(r.json()) == 100
    assert r.json()[0]["id"] == "t104"
    assert r.headers["X-Total-Count"] == "105"


def test_limite_raccourcit_la_liste_en_gardant_les_plus_recentes(sandbox, monkeypatch,
                                                                  tmp_path):
    for i in range(5):
        fiche(tmp_path, "t%d" % i, 1000 + i)

    r = client(sandbox, monkeypatch, tmp_path).get("/jobs?limite=2", headers=CLE)

    assert [j["id"] for j in r.json()] == ["t4", "t3"]
    assert r.headers["X-Total-Count"] == "5"


def test_limite_hors_bornes_est_REFUSEE_et_non_relevee_en_silence(sandbox, monkeypatch,
                                                                  tmp_path):
    c = client(sandbox, monkeypatch, tmp_path)
    assert c.get("/jobs?limite=0", headers=CLE).status_code == 422
    assert c.get("/jobs?limite=101", headers=CLE).status_code == 422


def test_abrege_retire_les_champs_SANS_BORNE_et_garde_ce_que_l_auto_test_lit(
        sandbox, monkeypatch, tmp_path):
    """L'auto-test lit id, status et video ; un journal d'un mega ne doit pas
    voyager avec."""
    bavard = "x" * 1_000_000
    fiche(tmp_path, "clip", 1000, stdout=bavard, stderr=bavard, code="import os",
          submit_log="envoye", video={"description": "un phare"})

    r = client(sandbox, monkeypatch, tmp_path).get("/jobs?abrege=1", headers=CLE)

    (job,) = r.json()
    for champ in ("stdout", "stderr", "code", "submit_log"):
        assert champ not in job, champ
    assert job["id"] == "clip" and job["status"] == "succeeded"
    assert job["video"] == {"description": "un phare"}
    assert len(r.content) < 10_000


def test_la_liste_reste_derriere_la_cle(sandbox, monkeypatch, tmp_path):
    r = client(sandbox, monkeypatch, tmp_path).get("/jobs?limite=1")
    assert r.status_code in (401, 403)
