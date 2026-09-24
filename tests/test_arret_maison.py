"""Arrêter une vidéo fabriquée sur la carte de cet ordinateur.

24/09/2026, le propriétaire : « l'arrêt d'une vidéo fabriquée sur la carte de
ce PC : à implémenter ». Jusque-là le bac à sable de la carte lançait le script
par un `subprocess.run` bloquant : le bouton d'arrêt disait « rien à arrêter à
distance » et le clip tenait la carte jusqu'à sa fin. Maintenant le bac à sable
garde le processus de chaque travail, et `/stop` le tue.
"""

from __future__ import annotations

import sys
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import charger

CLE_WORKER = {"Authorization": "Bearer cle-worker-de-test"}
CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
GPU_URL = "http://sandbox-worker-gpu:8000"


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv("SANDBOX_WORKER_KEY", "cle-worker-de-test")
    monkeypatch.setenv("SANDBOX_TIMEOUT_SECONDS", "60")
    module = charger("sandbox-worker")
    # Le module neuf n'est pas dans sys.modules : pydantic n'y retrouverait
    # pas les annotations (`from __future__ import annotations`) des requêtes.
    monkeypatch.setitem(sys.modules, module.__name__, module)
    module.RunRequest.model_rebuild()
    module.StopRequest.model_rebuild()
    return module


def test_stop_tue_le_script_en_cours_et_le_dit(worker):
    client = TestClient(worker.app)
    rendu = {}
    fil = threading.Thread(target=lambda: rendu.update(client.post(
        "/run", headers=CLE_WORKER,
        json={"job_id": "clip1", "code": "import time\ntime.sleep(50)\n"}).json()))
    debut = time.monotonic()
    fil.start()
    for _ in range(500):
        if "clip1" in worker.PROCESSUS:
            break
        time.sleep(0.01)
    assert "clip1" in worker.PROCESSUS, "le script n'a jamais démarré"
    r = client.post("/stop", headers=CLE_WORKER, json={"job_id": "clip1"})
    assert r.json() == {"job_id": "clip1", "arrete": True, "en_cours": True}
    fil.join(20)
    assert not fil.is_alive() and time.monotonic() - debut < 20, "le script de 50 s a tenu"
    assert rendu["arrete"] is True and rendu["exit_code"] != 0, rendu
    assert rendu["timed_out"] is False
    assert "clip1" not in worker.PROCESSUS and "clip1" not in worker.ARRETES, "rien ne traîne"


def test_un_arret_avant_le_calcul_empeche_le_depart(worker):
    client = TestClient(worker.app)
    r = client.post("/stop", headers=CLE_WORKER, json={"job_id": "clip2"})
    assert r.json()["en_cours"] is False
    rendu = client.post("/run", headers=CLE_WORKER,
                        json={"job_id": "clip2", "code": "open('trace', 'w').write('parti')\n"}).json()
    assert rendu["arrete"] is True and rendu["exit_code"] == 137
    assert not (worker.ROOT / "clip2" / "trace").exists(), "le script est parti quand même"
    ensuite = client.post("/run", headers=CLE_WORKER, json={"job_id": "clip2", "code": "print(1)\n"}).json()
    assert ensuite["exit_code"] == 0 and ensuite["arrete"] is False, "l'arrêt ne vaut qu'une fois"


def test_stop_demande_la_cle(worker):
    assert TestClient(worker.app).post("/stop", json={"job_id": "x"}).status_code == 401


def _travail_maison(sandbox, monkeypatch, reponse):
    """Une fiche « maison » en cours ; le bac à sable de la carte répond `reponse`."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", GPU_URL)
    vues = []

    def transport(requete):
        vues.append((requete.url.path, requete.content))
        return reponse(requete)

    vrai = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kw: vrai(transport=httpx.MockTransport(transport), **kw))
    jid = "9" * 32
    sandbox.write_job(jid, {"id": jid, "status": "running", "provider_effective": "maison",
                            "artifacts": []})
    r = TestClient(sandbox.app, base_url=LOCAL).post("/jobs/%s/arreter" % jid, headers=CLE)
    assert r.status_code == 200, r.text
    return jid, r.json(), vues


def test_le_bouton_arrete_le_calcul_sur_la_carte(sandbox, monkeypatch):
    jid, r, vues = _travail_maison(sandbox, monkeypatch, lambda _q: httpx.Response(
        200, json={"job_id": "9" * 32, "arrete": True, "en_cours": True}))
    assert [v[0] for v in vues] == ["/stop"] and b"9" * 32 in vues[0][1]
    assert r["status"] == "cancelled" and r["arretees"] == 1
    assert r["detail"] == "Le calcul sur la carte de cet ordinateur est arrêté : la carte est libérée."
    assert sandbox.read_job(jid)["status"] == "cancelled"


def test_un_calcul_pas_encore_parti_est_dit_tel_quel(sandbox, monkeypatch):
    _, r, _ = _travail_maison(sandbox, monkeypatch, lambda _q: httpx.Response(
        200, json={"arrete": True, "en_cours": False}))
    assert r["arretees"] == 0 and "il ne partira pas" in r["detail"]


def test_un_arret_rate_ne_se_fait_pas_passer_pour_reussi(sandbox, monkeypatch):
    _, r, _ = _travail_maison(sandbox, monkeypatch, lambda _q: httpx.Response(500))
    assert r["arretees"] == 0
    assert "n'a pas pu être arrêté" in r["detail"] and "il continue" in r["detail"]


def test_la_fin_du_calcul_tue_n_efface_pas_l_arret(sandbox):
    """Le script tué rend un code d'erreur au fil qui l'attendait : c'est la
    preuve de l'arrêt, pas un échec. La fiche reste « arrêtée »."""
    jid = "8" * 32
    sandbox.write_job(jid, {"id": jid, "status": "cancelled", "arret_demande": True,
                            "provider_effective": "maison", "artifacts": []})
    sandbox.finish_execution(jid, "maison", {"exit_code": -9, "stdout": "", "stderr": "",
                                             "artifacts": [], "arrete": True})
    assert sandbox.read_job(jid)["status"] == "cancelled"
    # Sans arrêt demandé, un code d'erreur reste un échec.
    jid = "7" * 32
    sandbox.write_job(jid, {"id": jid, "status": "running", "artifacts": []})
    sandbox.finish_execution(jid, "maison", {"exit_code": 1, "stdout": "", "stderr": "",
                                             "artifacts": []})
    assert sandbox.read_job(jid)["status"] == "failed"


def test_la_page_video_a_son_bouton_et_dit_l_arret(sandbox, monkeypatch):
    """Jusqu'au 24/09 la page vidéo n'avait AUCUN bouton d'arrêt : un clip fait
    sur la carte ne s'arrêtait que depuis Enchaîner. Et un clip arrêté y serait
    apparu « ✖ Échec »."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/video").text
    assert '<button id="arreter" class="danger" hidden>' in page
    assert '"/jobs/" + travailEnCours + "/arreter"' in page
    assert 'j.status === "cancelled"' in page and "⛔ Arrêté" in page
    jid, _, _ = _travail_maison(sandbox, monkeypatch, lambda _q: httpx.Response(
        200, json={"arrete": True, "en_cours": True}))
    suivi = TestClient(sandbox.app, base_url=LOCAL).get("/video/jobs/" + jid, headers=CLE).json()
    assert suivi["status"] == "cancelled"
    assert suivi["arret_detail"].startswith("Le calcul sur la carte de cet ordinateur est arrêté")
