"""La base de mesures du routeur : une ligne par usage du chat, de l'image, de
la dictee, de la voix -- jamais un mot de ce que la personne ecrit
(demande du 25/09/2026 : « tu peux toujours collecter les données pour admin »)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parents[1]
CLE = {"Authorization": "Bearer cle-interne-de-test"}
SECRET = "phrase-du-client-qui-ne-doit-jamais-sortir"


def lignes(dossier: Path) -> list:
    return [json.loads(ligne) for f in sorted(dossier.glob("*.jsonl"))
            for ligne in f.read_text(encoding="utf-8").splitlines()]


def test_les_deux_exemplaires_sont_identiques():
    octets = {(RACINE / d / "mesures.py").read_bytes() for d in ("free-tier-manager", "sandbox-manager")}
    assert len(octets) == 1, "les deux exemplaires de mesures.py divergent"


def test_chaque_service_a_son_dossier(routeur, sandbox):
    assert routeur.MESURES.name == "routeur" and sandbox.MESURES.name == "bac-a-sable"
    assert routeur.MESURES.parent.name == sandbox.MESURES.parent.name == "mesures"


@pytest.fixture
def client(routeur, monkeypatch, tmp_path):
    monkeypatch.setattr(routeur, "MESURES", tmp_path / "mesures")

    async def repond(client, name, payload):
        corps = {"choices": [{"message": {"role": "assistant", "content": "réponse " + SECRET}}]}
        return httpx.Response(200, json=corps, headers={"content-type": "application/json"})

    monkeypatch.setattr(routeur, "open_upstream", repond)
    return TestClient(routeur.app), routeur


def test_une_reponse_du_chat_fait_une_ligne_sans_texte(client):
    c, routeur = client
    r = c.post("/v1/chat/completions", headers=CLE,
               json={"model": "free-ai-auto", "messages": [{"role": "user", "content": SECRET}]})
    assert r.status_code == 200
    (ligne,) = lignes(routeur.MESURES)
    assert ligne["fonction"] == "chat.reponse" and ligne["ok"] is True and ligne["motif"] == ""
    assert ligne["endroit"] in {"gemini", "openrouter"} and ligne["flux"] is False
    assert ligne["interne"] is False and "secours" in ligne
    brut = "".join(f.read_text(encoding="utf-8") for f in routeur.MESURES.glob("*.jsonl"))
    assert SECRET not in brut and "réponse" not in brut


def test_un_refus_se_mesure_un_appel_sans_cle_non(client):
    c, routeur = client
    # Modele payant demande : refuse (403), c'est un usage refuse.
    assert c.post("/v1/chat/completions", headers=CLE, json={"model": "gpt-payant"}).status_code == 403
    # Sans la cle du Studio : pas un usage, pas de ligne.
    assert c.post("/v1/chat/completions", json={"model": "free-ai-auto"}).status_code == 401
    (ligne,) = lignes(routeur.MESURES)
    assert ligne["ok"] is False and ligne["motif"] == "refus"


def test_les_pages_et_le_reste_ne_sont_pas_mesures(client):
    c, routeur = client
    c.get("/studio")
    c.get("/health")
    assert not routeur.MESURES.exists() or lignes(routeur.MESURES) == []


def test_une_mesure_ratee_ne_casse_pas_le_chat(client, monkeypatch):
    c, routeur = client

    def casse(*a, **k):
        raise OSError("disque plein")

    monkeypatch.setattr(routeur.mesures, "ecrire", casse)
    r = c.post("/v1/chat/completions", headers=CLE,
               json={"model": "free-ai-auto", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
