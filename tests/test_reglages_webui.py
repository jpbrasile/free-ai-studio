"""Open WebUI : « Arena Model » retire du chat une fois, puis laisse a l'utilisateur."""
from __future__ import annotations

import asyncio
import json

import httpx

EVALUATIONS = "/api/v1/evaluations/config"


class OpenWebUISimule:
    """Les seules routes d'Open WebUI que ces tests touchent."""

    def __init__(self, arena=True, panne=False):
        self.config = {"ENABLE_EVALUATION_ARENA_MODELS": arena, "EVALUATION_ARENA_MODELS": []}
        self.panne = panne
        self.vus = []

    def __call__(self, requete):
        self.vus.append((requete.method, requete.url.path))
        if self.panne:
            return httpx.Response(500, json={"detail": "panne"})
        if requete.url.path == "/health":
            return httpx.Response(200, json={"status": True})
        if requete.url.path == EVALUATIONS:
            if requete.method == "POST":
                self.config.update(json.loads(requete.content))
            return httpx.Response(200, json=self.config)
        return httpx.Response(404)


def masquer(routeur, webui):
    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.MockTransport(webui)) as client:
            await routeur.masquer_arena(client, {"Authorization": "Bearer jeton"})
    asyncio.run(une_fois())


def test_arena_retire_une_fois_puis_laisse(routeur):
    webui = OpenWebUISimule()
    masquer(routeur, webui)
    assert webui.config["ENABLE_EVALUATION_ARENA_MODELS"] is False
    assert ("POST", EVALUATIONS) in webui.vus
    assert routeur.ARENA_FAIT.exists()

    # L'utilisateur le remet dans Admin > Evaluations : le Studio n'y touche plus.
    webui.config["ENABLE_EVALUATION_ARENA_MODELS"] = True
    webui.vus.clear()
    masquer(routeur, webui)
    assert webui.vus == []
    assert webui.config["ENABLE_EVALUATION_ARENA_MODELS"] is True


def test_arena_en_panne_pas_de_temoin(routeur):
    # Sans temoin, le reglage sera retente au prochain demarrage.
    masquer(routeur, OpenWebUISimule(panne=True))
    assert not routeur.ARENA_FAIT.exists()


def test_installation_existante_recoit_le_reglage(routeur, monkeypatch):
    # Le temoin des reglages de confort existe deja : Arena est retire quand
    # meme, et les reglages de confort ne sont pas refaits.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.REGLAGES_FAITS.write_text("{}", encoding="utf-8")
    webui = OpenWebUISimule()

    async def jeton(client):
        return "jeton"

    async def liaison(client, entetes):
        return None

    monkeypatch.setattr(routeur, "webui_jeton", jeton)
    monkeypatch.setattr(routeur, "reparer_connexion_webui", liaison)
    vrai = httpx.AsyncClient
    monkeypatch.setattr(routeur.httpx, "AsyncClient",
                        lambda **kw: vrai(transport=httpx.MockTransport(webui), **kw))
    asyncio.run(routeur.poser_reglages_webui())
    assert webui.config["ENABLE_EVALUATION_ARENA_MODELS"] is False
    assert [v for v in webui.vus if v[0] == "POST"] == [("POST", EVALUATIONS)]
