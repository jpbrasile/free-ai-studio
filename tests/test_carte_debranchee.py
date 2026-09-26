"""SP-CARTE-DEBRANCHEE-AU-REDEMARRAGE : une carte debranchee n'a plus le droit d'etre muette.

Le 22/09/2026, un `docker compose up -d` sans la surcouche GPU avait recree le
gestionnaire sans `SANDBOX_WORKER_GPU_URL` pendant que `sandbox-worker-gpu`
tournait a cote (Up 33 h, carte libre) : le Studio disait calmement << pas de
carte >> et un clip a ete facture 0,24 $. Ce controle rougit sur ce cas-la,
et sur lui seul : une machine VRAIMENT sans carte garde sa phrase calme.

Tout est faux ici : aucun reseau, aucun conteneur. Le vrai nom
`sandbox-worker-gpu` n'est resolu qu'en production -- non vu en reel.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parents[1]
CONNU = "http://sandbox-worker-gpu:8000"


class FausseReponse:
    def __init__(self, charge):
        self._charge = charge

    def json(self):
        return self._charge


def faux_client(charge=None, panne=None, appels=None):
    class FauxClient:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            if appels is not None:
                appels.append(url)
            if panne is not None:
                raise panne
            return FausseReponse(charge)
    return FauxClient


def debranche(sandbox, monkeypatch, charge=None, panne=None, appels=None):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "")
    monkeypatch.setattr(sandbox, "WORKER_GPU_CONNU", CONNU)
    monkeypatch.setattr(sandbox, "_debranchee", {"le": 0.0, "vu": None})
    monkeypatch.setattr(sandbox.httpx, "Client", faux_client(charge, panne, appels))


def test_le_cas_du_22_09_rougit(sandbox, monkeypatch):
    """Pas d'adresse de carte, mais le bac a sable de la carte repond : rouge."""
    appels = []
    debranche(sandbox, monkeypatch, charge={"ok": True, "poids_presents": True}, appels=appels)
    assert sandbox.carte_debranchee() is True
    assert appels == [CONNU + "/health"]
    prete, motif, ca_s_arrange = sandbox.maison_prete()
    # Le verdict ne change pas -- le clip part chez le loueur -- mais la phrase
    # nomme la cause et le geste.
    assert prete is False and ca_s_arrange is False
    assert "demarrer.cmd" in motif and "pas de carte" not in motif


def test_une_machine_sans_carte_garde_sa_phrase_calme(sandbox, monkeypatch):
    import httpx
    debranche(sandbox, monkeypatch, panne=httpx.ConnectError("nom inconnu"))
    assert sandbox.carte_debranchee() is False
    assert sandbox.maison_prete() == (
        False, "Cet ordinateur n'a pas de carte branchee au Studio", False)


def test_une_reponse_qui_ne_dit_pas_ok_ne_rougit_pas(sandbox, monkeypatch):
    debranche(sandbox, monkeypatch, charge={"detail": "Not Found"})
    assert sandbox.carte_debranchee() is False


def test_carte_branchee_rien_a_chercher(sandbox, monkeypatch):
    appels = []
    debranche(sandbox, monkeypatch, charge={"ok": True}, appels=appels)
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", CONNU)
    assert sandbox.carte_debranchee() is False
    assert appels == []


def test_controle_eteint_rend_none_et_non_faux(sandbox, monkeypatch):
    """Sans adresse connue, le controle n'a pas eu lieu : il ne dit pas << tout va bien >>."""
    appels = []
    debranche(sandbox, monkeypatch, charge={"ok": True}, appels=appels)
    monkeypatch.setattr(sandbox, "WORKER_GPU_CONNU", "")
    assert sandbox.carte_debranchee() is None
    assert appels == []


def test_la_reponse_est_gardee_30_secondes(sandbox, monkeypatch):
    appels = []
    debranche(sandbox, monkeypatch, charge={"ok": True}, appels=appels)
    assert sandbox.carte_debranchee(maintenant=1000.0) is True
    assert sandbox.carte_debranchee(maintenant=1029.0) is True
    assert len(appels) == 1
    assert sandbox.carte_debranchee(maintenant=1031.0) is True
    assert len(appels) == 2


def test_health_porte_la_ligne_rouge_et_reste_ok(sandbox, monkeypatch):
    debranche(sandbox, monkeypatch, charge={"ok": True})
    rendu = TestClient(sandbox.app).get("/health").json()
    assert rendu["ok"] is True
    assert rendu["carte_debranchee"] is True
    assert "demarrer.cmd" in rendu["alerte"]


def test_health_sans_carte_n_alerte_pas(sandbox, monkeypatch):
    import httpx
    debranche(sandbox, monkeypatch, panne=httpx.ConnectError("nom inconnu"))
    rendu = TestClient(sandbox.app).get("/health").json()
    assert rendu["carte_debranchee"] is False and "alerte" not in rendu


def test_essai_carte_porte_le_drapeau(sandbox, monkeypatch):
    debranche(sandbox, monkeypatch, charge={"ok": True})
    monkeypatch.setattr(sandbox.gpu_local, "releve", lambda *a, **k: {"vue": False})
    rendu = TestClient(sandbox.app).get(
        "/essai/carte", headers={"Authorization": "Bearer cle-sandbox-de-test"}).json()
    assert rendu["carte_debranchee"] is True


def test_compose_pose_l_adresse_connue_hors_surcouche():
    """L'adresse doit etre dans le fichier de BASE : c'est justement quand la
    surcouche manque qu'on en a besoin."""
    base = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
    surcouche = (RACINE / "docker-compose.gpu.yml").read_text(encoding="utf-8")
    assert "SANDBOX_WORKER_GPU_CONNU: " + CONNU in base
    assert "SANDBOX_WORKER_GPU_CONNU" not in surcouche
    # Et le nom est bien celui du service de la surcouche.
    assert "\n  sandbox-worker-gpu:\n" in surcouche


def _ligne_carte():
    """La fonction de scripts/self-test.py, seule : le script entier interroge le Studio vivant."""
    source = (RACINE / "scripts" / "self-test.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    fonction = next(n for n in arbre.body
                    if isinstance(n, ast.FunctionDef) and n.name == "ligne_carte")
    espace: dict = {}
    exec(compile(ast.Module(body=[fonction], type_ignores=[]), "self-test.py", "exec"), espace)
    return espace["ligne_carte"]


def test_l_auto_test_rougit_sur_une_carte_debranchee():
    ligne_carte = _ligne_carte()
    ok, detail = ligne_carte(json.loads(json.dumps(
        {"ok": True, "carte_debranchee": True, "alerte": "relancez par demarrer.cmd"})))
    assert ok is False and "demarrer.cmd" in detail
    assert ligne_carte({"ok": True, "carte_debranchee": False})[0] is True
    # Gestionnaire plus ancien : pas de champ, donc << non controle >>, pas vert.
    assert ligne_carte({"ok": True}) is None
