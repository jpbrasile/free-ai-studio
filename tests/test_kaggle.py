"""Kaggle automatique : identifiants personnels, machine personnelle.

Des que le Studio semble servir d'autres personnes, le Sandbox ne pilote plus
Kaggle et ne garde plus d'identifiants Kaggle : il ne reste que le lien manuel.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import charger

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
RESEAU = "http://192.168.1.20:8020"


def test_sur_la_machine_kaggle_permis(sandbox):
    etat = TestClient(sandbox.app, base_url=LOCAL).get("/etat").json()
    assert etat["kaggle"]["automatique_permis"] is True
    etat = TestClient(sandbox.app, base_url="http://localhost:8020").get("/etat").json()
    assert etat["kaggle"]["automatique_permis"] is True


def test_acces_par_le_reseau_coupe_kaggle(sandbox):
    client = TestClient(sandbox.app, base_url=RESEAU)
    etat = client.get("/etat").json()
    assert etat["kaggle"]["automatique_permis"] is False
    assert "192.168.1.20" in etat["kaggle"]["raison"]

    r = client.post("/jobs", headers=CLE, json={"provider": "kaggle", "code": "print(1)"})
    assert r.status_code == 403
    assert "kaggle.com/code" in r.json()["detail"]

    r = client.post("/video/creer", headers=CLE, json={"ou": "kaggle", "description": "un phare"})
    assert r.status_code == 403

    # Refus AVANT tout appel a Kaggle : des identifiants de tiers ne sont ni
    # essayes ni enregistres.
    r = client.post("/cles/tester", json={"backend": "kaggle",
                                          "valeurs": {"KAGGLE_USERNAME": "x", "KAGGLE_KEY": "y"}})
    assert r.status_code == 403
    assert sandbox.stored_keys() == {}


def test_proxy_coupe_kaggle(sandbox):
    client = TestClient(sandbox.app, base_url=LOCAL)
    etat = client.get("/etat", headers={"X-Forwarded-For": "203.0.113.9"}).json()
    assert etat["kaggle"]["automatique_permis"] is False


def test_webui_auth_coupe_kaggle(monkeypatch):
    """Plusieurs comptes sur le Studio : les calculs des autres partiraient
    sur le compte Kaggle du proprietaire."""
    monkeypatch.setenv("WEBUI_AUTH", "true")
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-sandbox-de-test")
    module = charger("sandbox-manager")
    etat = TestClient(module.app, base_url=LOCAL).get("/etat").json()
    assert etat["kaggle"]["automatique_permis"] is False


def test_studio_heberge_ne_degrade_plus_il_refuse(monkeypatch):
    """CHANGEMENT DU 19/09/2026, et il faut le lire comme tel.

    Jusqu'ici STUDIO_HEBERGE=true coupait Kaggle automatique et le service
    continuait de tourner. Depuis la decision 3 du paragraphe 8, il REFUSE DE
    DEMARRER : ce service ecrit les jetons Modal et Kaggle en clair dans
    config/sandbox-keys.json, et une instance hebergee les expose.

    Consequence assumee : la branche STUDIO_HEBERGE de contexte_partage() n'est
    plus atteignable a l'import -- on ne peut plus lancer un Studio declare
    heberge du tout. Les deux autres branches (WEBUI_AUTH, adresse de la
    requete) restent vivantes, et le test suivant garde la premiere.
    """
    monkeypatch.setenv("STUDIO_HEBERGE", "true")
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-sandbox-de-test")
    with pytest.raises(Exception) as leve:
        charger("sandbox-manager")
    assert "DEMARRAGE REFUSE" in str(leve.value)


def test_la_regle_de_partage_reste_ecrite_pour_studio_heberge(sandbox, monkeypatch):
    """La branche devenue inatteignable a l'import reste juste, et testee.

    Le jour ou les cles seront chiffrees et le refus rouvert, c'est elle qui
    reprendra du service. L'effacer maintenant la ferait revenir fausse.
    """
    monkeypatch.setattr(sandbox, "STUDIO_HEBERGE", True)
    assert sandbox.contexte_partage() == (
        "STUDIO_HEBERGE=true : instance declaree hebergee"
    )


def test_auto_saute_kaggle_en_contexte_partage(sandbox, monkeypatch):
    """Modal absent, worker local en panne, Kaggle configure : sur la machine
    du proprietaire, auto irait sur Kaggle ; en contexte partage, il doit
    preparer le notebook Colab a la place."""
    lances = []

    def worker_absent(*_):
        raise sandbox.BackendUnavailable("pas de worker")

    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    monkeypatch.setattr(sandbox, "local_execute", worker_absent)
    monkeypatch.setattr(sandbox, "run_kaggle", lambda *args: lances.append(args))

    jid = "a" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_auto(jid, "print(1)", False, False, kaggle_permis=False)

    job = sandbox.read_job(jid)
    assert lances == []
    assert job["status"] == "handoff_ready"
    assert {"provider": "kaggle", "result": "disabled_shared_context"} in job["fallback_attempts"]


def lancer_auto(sandbox, monkeypatch, gpu):
    """Modal absent, worker local en panne, Kaggle configure, machine du
    proprietaire : seul le drapeau gpu decide si auto part sur Kaggle."""
    lances = []

    def worker_absent(*_):
        raise sandbox.BackendUnavailable("pas de worker")

    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    monkeypatch.setattr(sandbox, "local_execute", worker_absent)
    monkeypatch.setattr(sandbox, "run_kaggle", lambda *args: lances.append(args))
    jid = ("c" if gpu else "b") * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_auto(jid, "print(1)", gpu, False, kaggle_permis=True)
    return lances, sandbox.read_job(jid)


def test_auto_n_envoie_pas_un_job_cpu_sur_kaggle(sandbox, monkeypatch):
    # Politique d'usage de Kaggle : pas un code quelconque.
    lances, job = lancer_auto(sandbox, monkeypatch, gpu=False)
    assert lances == []
    assert job["status"] == "handoff_ready"
    assert {"provider": "kaggle", "result": "cpu_job_not_sent"} in job["fallback_attempts"]


def test_auto_envoie_un_job_gpu_sur_kaggle(sandbox, monkeypatch):
    lances, job = lancer_auto(sandbox, monkeypatch, gpu=True)
    assert len(lances) == 1 and lances[0][2] is True
    assert {"provider": "kaggle", "result": "selected"} in job["fallback_attempts"]


def test_kaggle_jamais_destination_ordinaire(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    client = TestClient(sandbox.app, base_url=LOCAL)
    assert client.get("/etat").json()["backend_automatique"] == "local"
    fournisseurs = client.get("/providers", headers=CLE).json()
    assert fournisseurs["kaggle"]["automatic_only_for"] == "gpu_jobs"
