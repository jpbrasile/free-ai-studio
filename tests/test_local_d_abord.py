"""Mode auto du bac a sable : votre ordinateur d'abord, quand il suffit.

Ordre du proprietaire, 23/09/2026 : << local first before modal if ressources
available >>. Le bac a sable local tourne sur processeur, sans Internet : un job
qui ne demande ni carte ni reseau part donc ICI d'abord, et Modal n'est plus que
son secours. Un job qui demande une carte ou Internet garde Modal en tete.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
OK = {"exit_code": 0, "stdout": "", "stderr": "", "artifacts": []}


def _brancher(sandbox, monkeypatch, local_marche=True):
    appels = []

    def local(jid, code):
        appels.append("local")
        if not local_marche:
            raise sandbox.BackendUnavailable("pas de worker")
        return dict(OK)

    def modal(jid, code, gpu, internet):
        appels.append("modal")
        return dict(OK)

    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "local_execute", local)
    monkeypatch.setattr(sandbox, "modal_execute", modal)
    return appels


def _lancer(sandbox, gpu, internet, lettre):
    jid = lettre * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_auto(jid, "print(1)", gpu, internet)
    return sandbox.read_job(jid)


def test_sans_carte_ni_internet_le_job_reste_ici_meme_modal_configure(sandbox, monkeypatch):
    appels = _brancher(sandbox, monkeypatch)
    job = _lancer(sandbox, False, False, "d")
    assert appels == ["local"], appels
    assert job["provider_effective"] == "local"
    assert job["fallback_order"][0] == "local"


def test_ordinateur_indisponible_modal_prend_le_relais(sandbox, monkeypatch):
    appels = _brancher(sandbox, monkeypatch, local_marche=False)
    job = _lancer(sandbox, False, False, "e")
    assert appels == ["local", "modal"], appels
    assert job["provider_effective"] == "modal"
    assert job["fallback_attempts"][0]["result"] == "unavailable"


def test_un_job_qui_demande_une_carte_ou_internet_part_chez_modal(sandbox, monkeypatch):
    # Le bac a sable local n'a ni carte ni reseau : ce n'est pas la ressource.
    for gpu, internet, lettre in ((True, False, "f"), (False, True, "0")):
        appels = _brancher(sandbox, monkeypatch)
        job = _lancer(sandbox, gpu, internet, lettre)
        assert appels == ["modal"], (gpu, internet, appels)
        assert job["fallback_order"][0] == "modal"


def test_les_pages_et_l_api_disent_le_meme_ordre(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    client = TestClient(sandbox.app, base_url=LOCAL)
    etat = client.get("/etat").json()
    assert etat["backend_automatique"] == "local"
    assert etat["backend_carte_ou_internet"] == "modal"
    fournisseurs = client.get("/providers", headers=CLE).json()
    assert fournisseurs["automatic_order"][0] == "local"
    assert fournisseurs["automatic_order_gpu_or_internet"][0] == "modal"
    accueil = client.get("/").text
    assert "votre ordinateur d’abord" in accueil
    assert "Modal en priorité" not in accueil
