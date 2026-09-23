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


def test_un_job_qui_demande_internet_part_chez_modal(sandbox, monkeypatch):
    # Aucun bac a sable d'ici n'a de reseau : ce n'est pas la ressource.
    for gpu, lettre in ((True, "f"), (False, "0")):
        appels = _brancher(sandbox, monkeypatch)
        job = _lancer(sandbox, gpu, True, lettre)
        assert appels == ["modal"], (gpu, appels)
        assert job["fallback_order"][0] == "modal"


def _carte(sandbox, monkeypatch, libre):
    """La sonde de la carte d'ici, posee ; `maison_execute` compte ses appels."""
    appels = _brancher(sandbox, monkeypatch)
    monkeypatch.setattr(sandbox, "ou_lancer_essai", lambda: (
        ("maison", "RTX 4090 libre.") if libre else ("local", "RTX 4090 occupee par julia.exe.")))

    def maison(jid, code, secondes=None):
        appels.append("maison")
        return dict(OK)

    monkeypatch.setattr(sandbox, "maison_execute", maison)
    return appels


def test_un_job_carte_passe_sur_la_carte_d_ici_quand_elle_est_libre(sandbox, monkeypatch):
    appels = _carte(sandbox, monkeypatch, libre=True)
    job = _lancer(sandbox, True, False, "1")
    assert appels == ["maison"], appels
    assert job["provider_effective"] == "maison"
    assert job["fallback_order"][0] == "maison"
    assert job["placement"] == "RTX 4090 libre."


def test_carte_d_ici_occupee_modal_prend_le_relais_et_la_fiche_dit_pourquoi(sandbox, monkeypatch):
    appels = _carte(sandbox, monkeypatch, libre=False)
    job = _lancer(sandbox, True, False, "2")
    assert appels == ["modal"], appels
    assert job["provider_effective"] == "modal"
    premier = job["fallback_attempts"][0]
    assert premier["provider"] == "maison" and premier["result"] == "not_free", premier
    assert "julia.exe" in premier["detail"]


def test_le_bac_a_sable_de_la_carte_ne_lit_le_cache_qu_en_lecture_seule():
    """Option (a) du proprietaire, 23/09/2026 : du code quelconque tourne sur la
    carte d'ici, a cote du cache des modeles de la personne. Le montage de ce
    bac a sable doit finir par `:ro` ; celui du gestionnaire, qui telecharge,
    reste en ecriture."""
    import yaml

    from conftest import RACINE
    services = yaml.safe_load((RACINE / "docker-compose.gpu.yml").read_text(encoding="utf-8"))["services"]
    cache = [v for v in services["sandbox-worker-gpu"]["volumes"] if "/cache/huggingface" in v]
    assert cache and all(v.endswith(":/cache/huggingface:ro") for v in cache), cache
    ecrit = [v for v in services["sandbox-manager"]["volumes"] if "/cache/huggingface" in v]
    assert ecrit and all(v.endswith(":/cache/huggingface") for v in ecrit), ecrit


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
