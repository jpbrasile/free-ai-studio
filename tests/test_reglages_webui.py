"""Open WebUI : « Arena Model » retire du chat une fois, puis laisse a l'utilisateur."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parents[1]

EVALUATIONS = "/api/v1/evaluations/config"
CODE = "/api/v1/configs/code_execution"


def reglage_execution(interpreteur=True):
    """Le formulaire que rend Open WebUI 0.11.3, sans les champs Jupyter."""
    return {"ENABLE_CODE_EXECUTION": True, "CODE_EXECUTION_ENGINE": "pyodide",
            "ENABLE_CODE_INTERPRETER": interpreteur, "CODE_INTERPRETER_ENGINE": "pyodide",
            "CODE_INTERPRETER_PROMPT_TEMPLATE": ""}


class OpenWebUISimule:
    """Les seules routes d'Open WebUI que ces tests touchent."""

    def __init__(self, arena=True, panne=False, interpreteur=True):
        self.config = {"ENABLE_EVALUATION_ARENA_MODELS": arena, "EVALUATION_ARENA_MODELS": []}
        self.execution = reglage_execution(interpreteur)
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
        if requete.url.path == CODE:
            if requete.method == "POST":
                self.execution = json.loads(requete.content)
            return httpx.Response(200, json=self.execution)
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


def jeton_face_a(routeur, monkeypatch, reponses):
    """Rejoue webui_jeton contre une suite de reponses a la connexion."""
    monkeypatch.setattr(routeur, "WEBUI_JETON_PAUSE", 0)
    vues = []

    def webui(requete):
        vues.append(requete.url.path)
        reponse = reponses[min(len(vues), len(reponses)) - 1]
        if isinstance(reponse, Exception):
            raise reponse
        return reponse

    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.MockTransport(webui)) as client:
            return await routeur.webui_jeton(client)
    return asyncio.run(une_fois()), len(vues)


def test_connexion_en_course_retentee(routeur, monkeypatch):
    # Essai du 23/09/2026 : deux connexions simultanees creent admin@localhost
    # ensemble, la seconde prend un 500. Le routeur doit retenter, pas renoncer.
    jeton, appels = jeton_face_a(routeur, monkeypatch, [
        httpx.Response(500, json={"detail": "UNIQUE constraint failed"}),
        httpx.Response(200, json={"token": "t"}),
    ])
    assert (jeton, appels) == ("t", 2)


def test_connexion_coupee_retentee(routeur, monkeypatch):
    jeton, appels = jeton_face_a(routeur, monkeypatch, [
        httpx.ConnectError("coupe"), httpx.Response(200, json={"token": "t"})])
    assert (jeton, appels) == ("t", 2)


def test_vrai_compte_refus_definitif(routeur, monkeypatch):
    # Un 4xx veut dire un vrai compte : retenter ne changerait rien.
    jeton, appels = jeton_face_a(routeur, monkeypatch, [httpx.Response(400)])
    assert (jeton, appels) == (None, 1)


def test_panne_durable_abandon_borne(routeur, monkeypatch):
    jeton, appels = jeton_face_a(routeur, monkeypatch, [httpx.Response(500)])
    assert (jeton, appels) == (None, routeur.WEBUI_JETON_ESSAIS)


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
    # Meme chemin pour l'interpreteur de code : c'est celui de ce PC et de
    # l'autre ordinateur, qui ont tous deux le temoin des reglages.
    assert webui.execution["ENABLE_CODE_INTERPRETER"] is False
    assert [v for v in webui.vus if v[0] == "POST"] == [("POST", EVALUATIONS), ("POST", CODE)]


# --- L'interpreteur de code, coupe une fois (15/09/2026) ---

def couper(routeur, webui):
    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.MockTransport(webui)) as client:
            await routeur.couper_interpreteur(client, {"Authorization": "Bearer jeton"})
    asyncio.run(une_fois())


def test_interpreteur_coupe_une_fois_puis_laisse(routeur):
    webui = OpenWebUISimule()
    couper(routeur, webui)
    assert webui.execution["ENABLE_CODE_INTERPRETER"] is False
    # Le bouton << Executer >> d'un bloc de code reste : la personne le declenche.
    assert webui.execution["ENABLE_CODE_EXECUTION"] is True
    assert webui.execution["CODE_INTERPRETER_ENGINE"] == "pyodide"
    assert routeur.INTERPRETEUR_FAIT.exists()

    # Remis par l'utilisateur dans l'administration : le Studio n'y touche plus.
    webui.execution["ENABLE_CODE_INTERPRETER"] = True
    webui.vus.clear()
    couper(routeur, webui)
    assert webui.vus == []
    assert webui.execution["ENABLE_CODE_INTERPRETER"] is True


def test_interpreteur_deja_coupe_rien_ecrit(routeur):
    webui = OpenWebUISimule(interpreteur=False)
    couper(routeur, webui)
    assert ("POST", CODE) not in webui.vus
    assert routeur.INTERPRETEUR_FAIT.exists()


def test_interpreteur_en_panne_pas_de_temoin(routeur):
    couper(routeur, OpenWebUISimule(panne=True))
    assert not routeur.INTERPRETEUR_FAIT.exists()


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
        self.execution = reglage_execution()

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
        if chemin == CODE:
            if corps is not None:
                self.execution = corps
            return httpx.Response(200, json=self.execution)
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
    assert webui.execution["ENABLE_CODE_INTERPRETER"] is False


def test_pas_de_temoin_si_un_reglage_echoue(routeur, monkeypatch):
    # Open WebUI refuse le reglage << legacy >> : sans lui, l'interrupteur Image
    # ne fait rien. Pas de temoin : le reglage sera retente au prochain demarrage.
    poser(routeur, monkeypatch, OpenWebUIComplet(en_panne="/api/v1/configs/models"))
    assert not routeur.REGLAGES_FAITS.exists()


# --- Le demarrage, apres le passage a `lifespan` (20/09/2026) ----------------
#
# `@app.on_event("startup")` est deprecie par FastAPI. Le plan (etape 7) disait
# << passer a `lifespan` au prochain changement du demarrage >> ; ce changement
# a eu lieu le 20/09 dans l'autre service, la dette se paie ici le meme jour.
#
# Une migration de demarrage se rate en silence : le service monte, il repond a
# /health, et rien de ce qui devait partir n'est parti. Les reglages d'Open WebUI
# ne sont pas poses, la dictee n'est pas prechauffee, et cela ne se voit qu'au
# premier usage. Ce test regarde donc ce qui PART, pas ce qui est ecrit.


def test_le_demarrage_lance_bien_ses_deux_taches(routeur, service_voix, monkeypatch):
    """Les taches du demarrage partent, et aucun service ne les attend.

    Elles sont detachees expres : le prechauffage de la dictee peut telecharger
    464 Mo, et un routeur qui attendrait cela ne repondrait pas avant plusieurs
    minutes. Le test les remplace par des temoins, ouvre chaque service comme
    un vrai serveur le fait (le `with` declenche le cycle de vie), et verifie
    qu'elles ont ete appelees. Le prechauffage des voix est parti avec Piper
    dans le service `voix` le 23/09/2026 : il est verifie la-bas.
    """
    partis = []

    async def faux_reglages():
        partis.append("reglages")

    monkeypatch.setattr(routeur, "poser_reglages_webui", faux_reglages)
    monkeypatch.setattr(routeur, "prechauffer_whisper", lambda: partis.append("whisper"))
    monkeypatch.setattr(service_voix, "prechauffer_voix", lambda: partis.append("voix"))

    for app in (routeur.app, service_voix.app):
        with TestClient(app) as client:
            assert client.get("/health").json()["ok"] is True
            # Les taches sont detachees : on laisse la boucle leur donner un tour.
            for _ in range(50):
                if len(partis) == (2 if app is routeur.app else 3):
                    break
                time.sleep(0.02)

    assert sorted(partis) == ["reglages", "voix", "whisper"], partis


def test_le_demarrage_ne_passe_plus_par_on_event(routeur):
    """La dette est payee, pas contournee.

    Un `on_event` qui reviendrait ne casserait rien tout de suite : il
    marcherait, en ajoutant un avertissement par test -- il y en avait 210.
    C'est exactement le genre de dette qui reste dix mois.
    """
    source = (RACINE / "free-tier-manager" / "app.py").read_text(encoding="utf-8")
    # Un decorateur commence la ligne. Le module cite `@app.on_event` dans une
    # phrase pour dire ce qu'il remplace, et cette phrase doit pouvoir rester.
    decorateurs = [l for l in source.splitlines() if l.startswith("@app.on_event")]
    assert decorateurs == [], decorateurs
    assert "lifespan=demarrage_et_arret" in source
