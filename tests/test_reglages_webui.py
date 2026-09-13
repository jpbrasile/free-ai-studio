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


# --- Le reglage Images, repare a chaque demarrage (essai du 13/09/2026) ---

IMAGES = "/api/v1/images/config"
IMAGES_MAJ = "/api/v1/images/config/update"
INTERNE = "http://free-tier-manager:8000/v1"


class ReglagesImagesSimules:
    """La route des reglages Images d'Open WebUI, et elle seule."""

    def __init__(self, **cfg):
        self.config = {"ENABLE_IMAGE_GENERATION": True, "IMAGE_GENERATION_ENGINE": "openai",
                       "IMAGES_OPENAI_API_BASE_URL": INTERNE,
                       "IMAGES_OPENAI_API_KEY": "ancienne-cle",
                       "IMAGE_GENERATION_MODEL": "free-ai-image"}
        self.config.update(cfg)
        self.vus = []

    def __call__(self, requete):
        self.vus.append((requete.method, requete.url.path))
        if requete.url.path == IMAGES and requete.method == "GET":
            return httpx.Response(200, json=self.config)
        if requete.url.path == IMAGES_MAJ and requete.method == "POST":
            self.config = json.loads(requete.content)
            return httpx.Response(200, json=self.config)
        return httpx.Response(404)


def reparer_images(routeur, webui):
    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.MockTransport(webui)) as client:
            await routeur.reparer_images_webui(client, {"Authorization": "Bearer jeton"})
    asyncio.run(une_fois())


def test_images_cle_perimee_remplacee(routeur):
    # Le .env a change (refait, ou recopie d'un autre ordinateur) : le reglage
    # Images garde l'ancien mot de passe, et le routeur refuserait l'image.
    webui = ReglagesImagesSimules()
    reparer_images(routeur, webui)
    assert webui.config["IMAGES_OPENAI_API_KEY"] == "cle-interne-de-test"
    assert webui.config["IMAGE_GENERATION_MODEL"] == "free-ai-image"


def test_images_cle_gemini_collee_remplacee(routeur):
    webui = ReglagesImagesSimules(IMAGES_OPENAI_API_KEY="gemini-factice")
    reparer_images(routeur, webui)
    assert webui.config["IMAGES_OPENAI_API_KEY"] == "cle-interne-de-test"


def test_images_bonne_cle_rien_ecrit(routeur):
    webui = ReglagesImagesSimules(IMAGES_OPENAI_API_KEY="cle-interne-de-test")
    reparer_images(routeur, webui)
    assert ("POST", IMAGES_MAJ) not in webui.vus


def test_images_autre_moteur_laisse(routeur):
    # Un autre moteur, ou une autre adresse, est un choix de l'utilisateur.
    for cfg in ({"IMAGE_GENERATION_ENGINE": "gemini"},
                {"IMAGES_OPENAI_API_BASE_URL": "https://api.openai.com/v1"}):
        webui = ReglagesImagesSimules(**cfg)
        reparer_images(routeur, webui)
        assert ("POST", IMAGES_MAJ) not in webui.vus
        assert webui.config["IMAGES_OPENAI_API_KEY"] == "ancienne-cle"


# --- Le temoin des reglages n'est pose que si tout a passe ---

class OpenWebUIComplet:
    """Les routes que poser_reglages_webui appelle ; `en_panne` rend 500."""

    def __init__(self, en_panne=None):
        self.en_panne = en_panne
        self.modeles = {"DEFAULT_MODEL_PARAMS": {}}
        self.recherche = {"web": {"ENABLE_WEB_SEARCH": True, "WEB_SEARCH_ENGINE": "duckduckgo"}}
        self.images = {"ENABLE_IMAGE_GENERATION": False}

    def __call__(self, requete):
        chemin = requete.url.path
        if chemin == self.en_panne:
            return httpx.Response(500, json={"detail": "panne"})
        corps = json.loads(requete.content) if requete.method == "POST" else None
        if chemin == "/health":
            return httpx.Response(200, json={"status": True})
        if chemin == "/api/v1/configs/models":
            if corps is not None:
                self.modeles = corps
            return httpx.Response(200, json=self.modeles)
        if chemin == "/api/v1/configs/suggestions":
            return httpx.Response(200, json=corps)
        if chemin in ("/api/v1/retrieval/config", "/api/v1/retrieval/config/update"):
            if corps is not None:
                self.recherche = corps
            return httpx.Response(200, json=self.recherche)
        if chemin in (IMAGES, IMAGES_MAJ):
            if corps is not None:
                self.images = corps
            return httpx.Response(200, json=self.images)
        if chemin == EVALUATIONS:
            return httpx.Response(200, json={"ENABLE_EVALUATION_ARENA_MODELS": False})
        return httpx.Response(404)


def poser(routeur, monkeypatch, webui):
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


def test_temoin_pose_quand_tout_passe(routeur, monkeypatch):
    webui = OpenWebUIComplet()
    poser(routeur, monkeypatch, webui)
    assert routeur.REGLAGES_FAITS.exists()
    assert webui.modeles["DEFAULT_MODEL_PARAMS"]["function_calling"] == "legacy"
    assert webui.images["IMAGES_OPENAI_API_KEY"] == "cle-interne-de-test"


def test_pas_de_temoin_si_un_reglage_echoue(routeur, monkeypatch):
    # Open WebUI refuse le reglage << legacy >> : sans lui, l'interrupteur Image
    # ne fait rien. Pas de temoin : le reglage sera retente au prochain demarrage.
    poser(routeur, monkeypatch, OpenWebUIComplet(en_panne="/api/v1/configs/models"))
    assert not routeur.REGLAGES_FAITS.exists()
