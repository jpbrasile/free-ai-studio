"""Lire a haute voix (15/09/2026, deux langues le 16/09) : le routeur lit avec
Piper, une voix par langue, choisie phrase par phrase ; Open WebUI lui confie
son 🔊 une fois. Depuis le 23/09, Piper tourne dans le service `voix` et le
routeur l'appelle par HTTP. Ni Piper ni reseau ici."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import wave
from pathlib import Path

import httpx

AUDIO = "/api/v1/audio/config"
AUDIO_MAJ = "/api/v1/audio/config/update"
INTERNE = "http://free-tier-manager:8000/v1"


def reglage_tts(**champs):
    """Le formulaire TTS que rend Open WebUI 0.11.3 (releve sur ce PC, 15/09)."""
    tts = {"API_KEY": "", "AZURE_SPEECH_BASE_URL": "",
           "AZURE_SPEECH_OUTPUT_FORMAT": "audio-24khz-160kbitrate-mono-mp3",
           "AZURE_SPEECH_REGION": "", "ENGINE": "", "MISTRAL_API_BASE_URL": "https://api.mistral.ai/v1",
           "MISTRAL_API_KEY": "", "MODEL": "tts-1", "OPENAI_API_BASE_URL": "https://api.openai.com/v1",
           "OPENAI_API_KEY": "", "OPENAI_PARAMS": {}, "SPLIT_ON": "punctuation", "VOICE": "alloy"}
    tts.update(champs)
    return tts


class ReglagesAudioSimules:
    """Les deux routes des reglages audio d'Open WebUI, et elles seules."""

    def __init__(self, panne=False, **tts):
        self.config = {"tts": reglage_tts(**tts),
                       "stt": {"ENGINE": "openai", "OPENAI_API_BASE_URL": INTERNE,
                               "MODEL": "free-ai-dictee"}}
        self.panne = panne
        self.vus = []

    def __call__(self, requete):
        self.vus.append((requete.method, requete.url.path))
        if self.panne:
            return httpx.Response(500, json={"detail": "panne"})
        if requete.url.path == AUDIO and requete.method == "GET":
            return httpx.Response(200, json=self.config)
        if requete.url.path == AUDIO_MAJ and requete.method == "POST":
            self.config = json.loads(requete.content)
            return httpx.Response(200, json=self.config)
        return httpx.Response(404)


def aligner(routeur, webui):
    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.MockTransport(webui)) as client:
            await routeur.aligner_voix(client, {"Authorization": "Bearer jeton"})
    asyncio.run(une_fois())


# --- Le 🔊 d'Open WebUI confie au routeur, une fois ---

def test_premiere_fois_la_voix_va_au_routeur(routeur):
    webui = ReglagesAudioSimules()
    stt_avant = dict(webui.config["stt"])
    aligner(routeur, webui)
    tts = webui.config["tts"]
    assert tts["ENGINE"] == "openai"
    assert tts["OPENAI_API_BASE_URL"] == INTERNE
    # Le mot de passe interne, jamais une cle de fournisseur.
    assert tts["OPENAI_API_KEY"] == "cle-interne-de-test"
    assert tts["MODEL"] == "free-ai-voix"
    assert tts["VOICE"] == "fr_FR-siwis-medium"
    # Le decoupage par phrase d'Open WebUI reste : la premiere phrase part tout de suite.
    assert tts["SPLIT_ON"] == "punctuation"
    # La dictee n'est pas touchee.
    assert webui.config["stt"] == stt_avant
    assert routeur.VOIX_FAIT.exists()


def test_cle_interne_perimee_remplacee(routeur):
    webui = ReglagesAudioSimules(ENGINE="openai", OPENAI_API_BASE_URL=INTERNE,
                                 OPENAI_API_KEY="ancienne-cle", MODEL="free-ai-voix")
    aligner(routeur, webui)
    assert webui.config["tts"]["OPENAI_API_KEY"] == "cle-interne-de-test"


def test_bonne_liaison_rien_ecrit(routeur):
    webui = ReglagesAudioSimules(ENGINE="openai", OPENAI_API_BASE_URL=INTERNE,
                                 OPENAI_API_KEY="cle-interne-de-test", MODEL="free-ai-voix")
    aligner(routeur, webui)
    assert ("POST", AUDIO_MAJ) not in webui.vus


def test_autre_moteur_laisse(routeur):
    # ElevenLabs, Azure, le modele local d'Open WebUI, OpenAI : un choix de l'administration.
    for tts in ({"ENGINE": "elevenlabs"}, {"ENGINE": "azure"}, {"ENGINE": "transformers"},
                {"ENGINE": "openai", "OPENAI_API_BASE_URL": "https://api.openai.com/v1"}):
        webui = ReglagesAudioSimules(**tts)
        aligner(routeur, webui)
        assert ("POST", AUDIO_MAJ) not in webui.vus


def test_voix_du_navigateur_remise_reste(routeur):
    webui = ReglagesAudioSimules()
    aligner(routeur, webui)
    # Quelqu'un remet la voix du navigateur dans l'administration : elle reste.
    webui.config["tts"]["ENGINE"] = ""
    webui.vus.clear()
    aligner(routeur, webui)
    assert ("POST", AUDIO_MAJ) not in webui.vus
    assert webui.config["tts"]["ENGINE"] == ""


def test_open_webui_en_panne_pas_de_temoin(routeur):
    aligner(routeur, ReglagesAudioSimules(panne=True))
    assert not routeur.VOIX_FAIT.exists()


# --- La route /v1/audio/speech ---

def petit_wav() -> bytes:
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 220)
    return tampon.getvalue()


class PiperSimule:
    """Remplace la voix du routeur : ni modele, ni calcul dans les tests."""

    def __init__(self, panne=False):
        self.panne = panne
        self.appels = []

    def __call__(self, texte, vitesse):
        self.appels.append((texte, vitesse))
        if self.panne:
            raise RuntimeError("voix absente")
        return petit_wav()


def lire(routeur, monkeypatch, corps, piper=None, cle="cle-interne-de-test"):
    monkeypatch.setattr(routeur, "lire_local", piper if piper is not None else PiperSimule())

    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=routeur.app),
                                     base_url="http://routeur") as client:
            return await client.post("/v1/audio/speech", json=corps,
                                     headers={"Authorization": f"Bearer {cle}"})
    return asyncio.run(une_fois())


def test_lecture_rend_du_wav(routeur, monkeypatch):
    piper = PiperSimule()
    # Ce qu'envoie Open WebUI : la phrase, le modele et la voix de ses reglages.
    r = lire(routeur, monkeypatch, {"input": "Bonjour, je lis en français.",
                                    "model": "free-ai-voix", "voice": "fr_FR-siwis-medium"}, piper)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    assert piper.appels == [("Bonjour, je lis en français.", 1.0)]


def test_mise_en_forme_retiree(routeur, monkeypatch):
    piper = PiperSimule()
    lire(routeur, monkeypatch, {"input": "**Gras** et `code` ## Titre\n```python\nprint(1)\n```\n"
                                         "Fin https://exemple.fr/page"}, piper)
    assert piper.appels[0][0] == "Gras et code Titre Fin"


def test_vitesse_bornee(routeur, monkeypatch):
    piper = PiperSimule()
    for vitesse in (10, 0.1, 1.5):
        lire(routeur, monkeypatch, {"input": "Une phrase.", "speed": vitesse}, piper)
    assert [v for _, v in piper.appels] == [2.0, 0.5, 1.5]


def test_rien_a_lire_ou_trop_long(routeur, monkeypatch):
    piper = PiperSimule()
    for texte in ("", "  ** ## ", "a" * (routeur.VOIX_MAX_CARACTERES + 1)):
        r = lire(routeur, monkeypatch, {"input": texte}, piper)
        assert r.status_code == 400
        assert r.json()["error"]["message"]
    assert piper.appels == []


def test_voix_en_echec_message_clair(routeur, monkeypatch):
    r = lire(routeur, monkeypatch, {"input": "Une phrase."}, PiperSimule(panne=True))
    assert r.status_code == 500
    assert "se telecharge" in r.json()["error"]["message"]


def test_mauvais_mot_de_passe_refuse(routeur, monkeypatch):
    piper = PiperSimule()
    r = lire(routeur, monkeypatch, {"input": "Une phrase."}, piper, cle="mauvaise")
    assert r.status_code == 401
    assert piper.appels == []


# --- Piper hors du routeur (23/09/2026, PLAN.md point 15) ---
# Piper est GPL-3.0-or-later ; le routeur est MIT. Il l'appelle par HTTP dans
# le service `voix` et n'en importe plus rien.

def test_le_routeur_n_importe_plus_piper():
    racine = Path(__file__).resolve().parents[1]
    source = (racine / "free-tier-manager" / "app.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+piper\b", source, re.M)
    exigences = (racine / "free-tier-manager" / "requirements.txt").read_text(encoding="utf-8")
    assert not re.search(r"^piper", exigences, re.M)


def test_les_noms_des_voix_sont_les_memes_des_deux_cotes(routeur, service_voix):
    assert {langue: v["nom"] for langue, v in routeur.VOIX.items()} == \
           {langue: v["nom"] for langue, v in service_voix.VOIX.items()}


def test_le_routeur_demande_chaque_morceau_au_service(routeur, monkeypatch):
    demandes = []

    def service(requete):
        demandes.append((str(requete.url), json.loads(requete.content)))
        return httpx.Response(200, content=petit_wav())

    vrai = httpx.Client
    monkeypatch.setattr(routeur.httpx, "Client",
                        lambda **kw: vrai(transport=httpx.MockTransport(service), **kw))
    son = routeur.lire_local("Voici la reponse. This is the English part.", 1.25)
    assert [d[0] for d in demandes] == ["http://voix:8000/lire"] * 2
    assert [(d[1]["langue"], d[1]["vitesse"]) for d in demandes] == [("fr", 1.25), ("en", 1.25)]
    with wave.open(io.BytesIO(son), "rb") as lu:
        assert lu.getnframes() == 440


def test_service_absent_message_clair(routeur, monkeypatch):
    """Le conteneur de la voix arrete : le 🔊 dit un message, le routeur tient."""
    def eteint(requete):
        raise httpx.ConnectError("voix injoignable", request=requete)

    vrai = httpx.Client
    monkeypatch.setattr(routeur.httpx, "Client",
                        lambda **kw: vrai(transport=httpx.MockTransport(eteint), **kw))

    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=routeur.app),
                                     base_url="http://routeur") as client:
            return await client.post("/v1/audio/speech", json={"input": "Une phrase."},
                                     headers={"Authorization": "Bearer cle-interne-de-test"})
    r = asyncio.run(une_fois())
    assert r.status_code == 500
    assert r.json()["error"]["message"]


# --- Le service de la voix ---

def lire_au_service(service_voix, corps):
    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service_voix.app),
                                     base_url="http://voix") as client:
            return await client.post("/lire", json=corps)
    return asyncio.run(une_fois())


def test_le_service_lit_un_morceau(service_voix, monkeypatch):
    appels = []
    monkeypatch.setattr(service_voix, "synthetiser",
                        lambda langue, texte, vitesse: appels.append((langue, texte, vitesse))
                        or petit_wav())
    r = lire_au_service(service_voix, {"langue": "en", "texte": "Hello.", "vitesse": 9})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert appels == [("en", "Hello.", 2.0)]


def test_le_service_refuse_ce_qu_il_ne_sait_pas_lire(service_voix, monkeypatch):
    appels = []
    monkeypatch.setattr(service_voix, "synthetiser", lambda *a: appels.append(a) or petit_wav())
    for corps in ({"langue": "de", "texte": "Hallo."}, {"langue": "fr", "texte": "  "},
                  {"langue": "fr", "texte": "a" * (service_voix.VOIX_MAX_CARACTERES + 1)}):
        assert lire_au_service(service_voix, corps).status_code == 400
    assert appels == []


def test_le_service_en_panne_rend_503(service_voix, monkeypatch):
    def panne(*_):
        raise RuntimeError("voix absente")
    monkeypatch.setattr(service_voix, "synthetiser", panne)
    assert lire_au_service(service_voix, {"langue": "fr", "texte": "Une phrase."}).status_code == 503


# --- Le telechargement de la voix (dans le service) ---

def brancher_hugging_face(service_voix, monkeypatch, contenu: bytes):
    demandes = []

    def repondre(requete):
        demandes.append(requete.url.path)
        return httpx.Response(200, content=contenu)

    vrai = httpx.Client
    monkeypatch.setattr(service_voix.httpx, "Client",
                        lambda **kw: vrai(transport=httpx.MockTransport(repondre), **kw))
    return demandes


def test_voix_abimee_refusee(service_voix, monkeypatch, tmp_path):
    monkeypatch.setattr(service_voix, "VOIX_DOSSIER", tmp_path)
    brancher_hugging_face(service_voix, monkeypatch, b"pas la voix")
    try:
        service_voix.telecharger_voix()
    except RuntimeError as exc:
        assert "empreinte" in str(exc)
    else:
        raise AssertionError("une voix abimee a ete acceptee")
    assert not (tmp_path / "fr_FR-siwis-medium.onnx").exists()
    assert not list(tmp_path.glob("*.partiel"))


def test_voix_telechargee_une_fois_a_la_revision_fixe(service_voix, monkeypatch, tmp_path):
    contenu = b"voix factice"
    monkeypatch.setattr(service_voix, "VOIX_DOSSIER", tmp_path)
    monkeypatch.setitem(service_voix.VOIX["fr"], "sha256", hashlib.sha256(contenu).hexdigest())
    demandes = brancher_hugging_face(service_voix, monkeypatch, contenu)
    assert service_voix.telecharger_voix() == tmp_path / "fr_FR-siwis-medium.onnx"
    assert len(demandes) == 2
    assert all(service_voix.VOIX_REVISION in d for d in demandes)
    service_voix.telecharger_voix()
    assert len(demandes) == 2


def test_voix_anglaise_telechargee_a_part(service_voix, monkeypatch, tmp_path):
    contenu = b"voix factice"
    monkeypatch.setattr(service_voix, "VOIX_DOSSIER", tmp_path)
    monkeypatch.setitem(service_voix.VOIX["en"], "sha256", hashlib.sha256(contenu).hexdigest())
    demandes = brancher_hugging_face(service_voix, monkeypatch, contenu)
    assert service_voix.telecharger_voix("en") == tmp_path / "en_US-norman-medium.onnx"
    assert all("en/en_US/norman/medium" in d for d in demandes)
    assert all(service_voix.VOIX_REVISION in d for d in demandes)


# --- Une voix par langue (16/09/2026) ---
# Avant : la voix francaise lisait l'anglais, avec l'accent francais.

def test_langue_reconnue(routeur):
    assert routeur.langue_du_texte("Bonjour, je lis une phrase en français.") == "fr"
    assert routeur.langue_du_texte("This is a sentence that you can read.") == "en"
    # Sans aucun indice, la langue de la phrase precedente continue.
    assert routeur.langue_du_texte("Python 3.12", "en") == "en"
    assert routeur.langue_du_texte("Python 3.12", "fr") == "fr"


def test_phrases_melangees_donnent_deux_voix(routeur):
    texte = "Voici la reponse. This is the English part. Merci de votre patience."
    morceaux = routeur.decouper_par_langue(texte)
    assert [langue for langue, _ in morceaux] == ["fr", "en", "fr"]
    # Rien n'est perdu en chemin : tout le texte est lu, une fois.
    assert "".join(m for _, m in morceaux).strip() == texte


def test_phrases_voisines_de_meme_langue_collees(routeur):
    morceaux = routeur.decouper_par_langue("The cat is here. It can read. Bonjour a vous.")
    assert [langue for langue, _ in morceaux] == ["en", "fr"]


def test_sons_colles_bout_a_bout(routeur):
    colle = routeur.coller_wav([petit_wav(), petit_wav()])
    with wave.open(io.BytesIO(colle), "rb") as lu:
        assert lu.getnframes() == 440
        assert (lu.getframerate(), lu.getnchannels(), lu.getsampwidth()) == (22050, 1, 2)


def test_un_seul_son_rendu_tel_quel(routeur):
    son = petit_wav()
    assert routeur.coller_wav([son]) is son
