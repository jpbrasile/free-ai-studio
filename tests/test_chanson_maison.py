"""La chanson sur la carte de cet ordinateur (26/09/2026) -- le patron de la video.

Tout est faux ici : ni carte, ni bac a sable, ni YuE2. Ce qui est verifie,
c'est la DECISION prise avant de lancer, et qu'aucun << non >> ne bloque une
chanson qui partait hier chez le loueur. Qu'une chanson se fasse vraiment sur
la 4090 par ce chemin n'est PAS verifie : l'image du bac a sable de la carte
n'a pas YuE2 (voir PLAN.md, point 15.5).
"""
from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
PAROLES = "[Verse]\nPaper boats along the stream\n[Chorus]\nSing it low and sing it clear"


def libre(besoin_mo, delai_s=None):
    libre.vus.append(besoin_mo)
    return True, "RTX 4090 : 22,0 Go libres.", {"vue": True, "libre_mo": 22000}


def prise(besoin_mo, delai_s=None):
    return False, "RTX 4090 : julia.exe tient la carte.", {"vue": True, "libre_mo": 3000}


def jamais(*a, **k):
    raise AssertionError("ne devait pas etre appele")


@pytest.fixture
def cm(sandbox):
    libre.vus = []
    return sandbox.chanson_maison


# --- 1. La decision, seule -------------------------------------------------

def test_libre_et_prete_la_chanson_se_fait_ici(cm):
    d = cm.decider("3", False, "maison-si-libre", lambda: (True, ""), libre)
    assert d["ou"] == cm.MAISON and "gratuitement" in d["pourquoi"]
    # Le pic mesure le 23/09 sur la 4090, et pas un chiffre rond.
    assert libre.vus == [8622] and d["besoin_mo"] == 8622
    assert d["besoin_est_mesure"] is True


def test_les_durees_courtes_prennent_le_majorant_et_ne_se_disent_pas_mesurees(cm):
    for duree in ("1", "2"):
        d = cm.decider(duree, False, "maison-si-libre", lambda: (True, ""), libre)
        assert d["ou"] == cm.MAISON and d["besoin_mo"] == 8622
        assert d["besoin_est_mesure"] is False


def test_carte_prise_la_chanson_part_chez_le_loueur_sans_arreter_personne(cm):
    d = cm.decider("1", False, "maison-si-libre", lambda: (True, ""), prise, loueur="Kaggle")
    assert d["ou"] == cm.LOUEUR
    assert "julia.exe" in d["pourquoi"] and "Kaggle" in d["pourquoi"]


def test_pas_prete_on_ne_sonde_meme_pas_la_carte(cm):
    d = cm.decider("1", False, "maison-si-libre",
                   lambda: (False, "Le bac à sable n'a pas YuE2."), jamais)
    assert d["ou"] == cm.LOUEUR and "YuE2" in d["pourquoi"]


def test_toujours_louer_ne_demande_rien_a_la_carte(cm):
    d = cm.decider("1", False, "toujours-modal", jamais, jamais)
    assert d["ou"] == cm.LOUEUR


def test_la_version_instrumentale_reste_chez_modal(cm):
    """Verifiee sur L4 seulement : ni memoire ni resultat mesures ici."""
    d = cm.decider("1", True, "maison-si-libre", jamais, jamais)
    assert d["ou"] == cm.LOUEUR and "L4" in d["pourquoi"]


def test_une_duree_inconnue_ne_se_devine_pas(cm):
    d = cm.decider("7", False, "maison-si-libre", jamais, jamais)
    assert d["ou"] == cm.LOUEUR and "pas été mesurée" in d["pourquoi"]


def test_toujours_a_la_maison_ne_bloque_pas_la_chanson(cm):
    """Decision du 26/09 : la page ne sait ni demander ni attendre ; ce reglage
    se lit comme << maison si libre >>, jamais comme un refus."""
    d = cm.decider("1", False, "toujours-maison", lambda: (False, "Pas prête."), jamais)
    assert d["ou"] == cm.LOUEUR
    d = cm.decider("1", False, "toujours-maison", lambda: (True, ""), prise)
    assert d["ou"] == cm.LOUEUR


# --- 2. Les poids, dans le cache partage -----------------------------------

def _poser(cm, racine, hf, rev, incomplet=False, sans_poids=False):
    depot = racine / "hub" / ("models--" + hf.replace("/", "--"))
    instant = depot / "snapshots" / rev
    instant.mkdir(parents=True)
    (instant / "config.json").write_text("{}", encoding="utf-8")
    if not sans_poids:
        (instant / "model.safetensors").write_bytes(b"x")
    (depot / "blobs").mkdir()
    if incomplet:
        (depot / "blobs" / "abc.incomplete").write_bytes(b"")


def test_poids_absents_presents_incomplets(cm, tmp_path):
    m = cm.chanson.MODELE
    ok, motif = cm.poids_presents(tmp_path)
    assert ok is False and m["hf"] in motif
    _poser(cm, tmp_path, m["hf"], m["revision"])
    ok, motif = cm.poids_presents(tmp_path)
    assert ok is False and m["vae"] in motif
    _poser(cm, tmp_path, m["vae"], m["vae_revision"], incomplet=True)
    ok, motif = cm.poids_presents(tmp_path)
    assert ok is False and "en cours" in motif
    (tmp_path / "hub" / ("models--" + m["vae"].replace("/", "--")) / "blobs"
     / "abc.incomplete").unlink()
    assert cm.poids_presents(tmp_path) == (True, "")


def test_une_autre_revision_ne_compte_pas(cm, tmp_path):
    m = cm.chanson.MODELE
    _poser(cm, tmp_path, m["hf"], "0" * 40)
    _poser(cm, tmp_path, m["vae"], m["vae_revision"])
    assert cm.poids_presents(tmp_path)[0] is False


def test_un_depot_sans_safetensors_est_incomplet(cm, tmp_path):
    m = cm.chanson.MODELE
    _poser(cm, tmp_path, m["hf"], m["revision"], sans_poids=True)
    ok, motif = cm.poids_presents(tmp_path)
    assert ok is False and "incomplet" in motif


# --- 3. Le script pour la carte d'ici --------------------------------------

def test_le_script_maison_n_installe_rien_et_lit_le_cache_partage(sandbox):
    plan = sandbox.chanson.preparer({"style": "pop", "paroles": PAROLES}, "maison")
    assert plan["demande"]["installer"] is False
    assert plan["demande"]["cache"] == "/cache/huggingface"
    assert plan["resume_public"]["carte"] == "la carte de cet ordinateur"
    compile(sandbox.chanson.construire_script(plan["demande"]), "chanson.py", "exec")


# --- 4. La route -----------------------------------------------------------

@pytest.fixture
def route(sandbox, monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.budget_modal, "FICHIER", tmp_path / "modal-budget.json")
    monkeypatch.setattr(sandbox.ou_calculer, "reglage_lu", lambda: "maison-si-libre")
    lances = []
    monkeypatch.setattr(sandbox, "run_chanson", lambda *args: lances.append(args))
    sandbox._lances = lances
    return sandbox


def attendre(lances):
    for _ in range(100):
        if lances:
            return
        time.sleep(0.02)


def test_sans_carte_rien_ne_change(route, monkeypatch):
    monkeypatch.setattr(route, "WORKER_GPU_URL", "")
    monkeypatch.setattr(route, "modal_configured", lambda: True)
    monkeypatch.setattr(route.gpu_local, "utilisable", jamais)
    r = TestClient(route.app, base_url=LOCAL).post(
        "/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 200
    attendre(route._lances)
    assert route._lances[0][2] == "modal"
    assert "pas de carte" in r.json()["chanson"]["ou_pourquoi"]


def test_carte_prete_et_libre_la_chanson_part_ici_sans_jeton_ni_budget(route, monkeypatch):
    monkeypatch.setattr(route, "chanson_maison_prete", lambda: (True, ""))
    monkeypatch.setattr(route.gpu_local, "utilisable", libre)
    # Ni Modal branche, ni budget restant : la carte d'ici n'en a pas besoin.
    monkeypatch.setattr(route, "modal_configured", lambda: False)
    route.chanson.budget_ecrire(0, route.chanson.BUDGET_MENSUEL_USD, 9)
    r = TestClient(route.app, base_url=LOCAL).post(
        "/chanson/creer", headers=CLE,
        json={"style": "pop", "paroles": PAROLES, "duree": "3"})
    assert r.status_code == 200, r.text
    attendre(route._lances)
    jid, code, ou = route._lances[0]
    assert ou == "maison"
    job = r.json()
    assert job["provider"] == "maison" and job["internet"] is False
    assert job["chanson"]["carte"] == "la carte de cet ordinateur"
    charge = code.split('b64decode("', 1)[1].split('"', 1)[0]
    demande = json.loads(base64.b64decode(charge).decode("utf-8"))
    assert demande["installer"] is False and demande["cache"] == "/cache/huggingface"
    assert libre.vus == [8622]


def test_carte_prise_la_chanson_part_chez_le_loueur_choisi(route, monkeypatch):
    monkeypatch.setattr(route, "chanson_maison_prete", lambda: (True, ""))
    monkeypatch.setattr(route.gpu_local, "utilisable", prise)
    monkeypatch.setattr(route, "modal_configured", lambda: True)
    r = TestClient(route.app, base_url=LOCAL).post(
        "/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 200
    attendre(route._lances)
    assert route._lances[0][2] == "modal"
    assert "julia.exe" in r.json()["chanson"]["ou_pourquoi"]


def test_la_version_instrumentale_ne_part_jamais_ici(route, monkeypatch):
    monkeypatch.setattr(route, "chanson_maison_prete", jamais)
    monkeypatch.setattr(route.gpu_local, "utilisable", jamais)
    monkeypatch.setattr(route, "modal_configured", lambda: True)
    r = TestClient(route.app, base_url=LOCAL).post(
        "/chanson/creer", headers=CLE, json={"style": "pop", "lora": True})
    assert r.status_code == 200, r.text
    attendre(route._lances)
    assert route._lances[0][2] == "modal"


# --- 5. Pret ou pas : ce que le bac a sable de la carte repond -------------

class _Reponse:
    def __init__(self, charge):
        self._charge = charge

    def json(self):
        return self._charge


def _client(charge):
    class Faux:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _Reponse(charge)
    return Faux


def test_sans_yue2_dans_l_image_pas_prete(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://sandbox-worker-gpu:8000")
    monkeypatch.setattr(sandbox.httpx, "Client", _client({"ok": True, "poids_presents": True}))
    ok, motif = sandbox.chanson_maison_prete()
    assert ok is False and "YuE2" in motif


def test_avec_yue2_et_les_poids_prete(sandbox, monkeypatch, tmp_path):
    m = sandbox.chanson.MODELE
    _poser(None, tmp_path, m["hf"], m["revision"])
    _poser(None, tmp_path, m["vae"], m["vae_revision"])
    monkeypatch.setattr(sandbox.chanson_maison, "POIDS_DIR", tmp_path)
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://sandbox-worker-gpu:8000")
    monkeypatch.setattr(sandbox.httpx, "Client", _client({"ok": True, "yue2": True}))
    assert sandbox.chanson_maison_prete() == (True, "")


def test_carte_debranchee_le_dit_aussi_pour_la_chanson(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "")
    monkeypatch.setattr(sandbox, "carte_debranchee", lambda: True)
    ok, motif = sandbox.chanson_maison_prete()
    assert ok is False and "demarrer.cmd" in motif


# --- 6. L'execution : rien a encaisser -------------------------------------

def test_une_chanson_faite_ici_ne_touche_pas_au_compteur_modal(sandbox, monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.budget_modal, "FICHIER", tmp_path / "modal-budget.json")
    appels = []
    monkeypatch.setattr(sandbox, "maison_execute",
                        lambda jid, code, secondes=None: appels.append(secondes) or {"ok": True})
    monkeypatch.setattr(sandbox, "finish_execution", lambda *a: None)
    monkeypatch.setattr(sandbox.chanson, "budget_consommer", jamais)
    jid = "c0ffee"
    sandbox.write_job(jid, {"id": jid, "status": "queued"})
    sandbox.run_chanson(jid, "print(1)", "maison")
    assert appels == [sandbox.chanson.DUREE_MAX_S]


def test_le_bac_a_sable_dit_s_il_a_yue2(monkeypatch):
    import importlib

    conftest = importlib.import_module("conftest")
    worker = conftest.charger("sandbox-worker")
    assert worker.health()["yue2"] in (True, False)
