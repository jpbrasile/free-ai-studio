"""La dictee (15/09/2026) : le routeur choisit, a chaque dictee, entre Groq et
son propre Whisper ; le choix << sur cet ordinateur >> ne laisse jamais partir
la voix."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from types import SimpleNamespace

import httpx

AUDIO = "/api/v1/audio/config"
AUDIO_MAJ = "/api/v1/audio/config/update"
INTERNE = "http://free-tier-manager:8000/v1"


def reglage_stt(**champs):
    """Le formulaire STT que rend Open WebUI 0.11.3 (releve sur ce PC, 15/09)."""
    stt = {"OPENAI_API_BASE_URL": "https://api.openai.com/v1", "OPENAI_API_KEY": "",
           "OPENAI_API_REQUEST_FORMAT": "multipart", "ENGINE": "", "MODEL": "",
           "SUPPORTED_CONTENT_TYPES": [], "ALLOWED_EXTENSIONS": ["mp3", "wav", "webm"],
           "WHISPER_MODEL": "base", "DEEPGRAM_API_KEY": "", "AZURE_API_KEY": "",
           "AZURE_REGION": "", "AZURE_LOCALES": "", "AZURE_BASE_URL": "",
           "AZURE_MAX_SPEAKERS": "", "MISTRAL_API_KEY": "",
           "MISTRAL_API_BASE_URL": "https://api.mistral.ai/v1",
           "MISTRAL_USE_CHAT_COMPLETIONS": False}
    stt.update(champs)
    return stt


class ReglagesAudioSimules:
    """Les deux routes des reglages audio d'Open WebUI, et elles seules."""

    def __init__(self, panne=False, **stt):
        self.config = {"tts": {"ENGINE": "", "VOICE": "alloy"}, "stt": reglage_stt(**stt)}
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
            await routeur.aligner_dictee(client, {"Authorization": "Bearer jeton"})
    asyncio.run(une_fois())


def brancher_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-factice")
    monkeypatch.setenv("ENABLE_GROQ", "true")


# --- La dictee d'Open WebUI confiee au routeur, une fois ---

def test_premiere_fois_la_dictee_va_au_routeur(routeur):
    webui = ReglagesAudioSimules()
    aligner(routeur, webui)
    stt = webui.config["stt"]
    assert stt["ENGINE"] == "openai"
    assert stt["OPENAI_API_BASE_URL"] == INTERNE
    # Le mot de passe interne, jamais une cle de fournisseur.
    assert stt["OPENAI_API_KEY"] == "cle-interne-de-test"
    assert stt["MODEL"] == "free-ai-dictee"
    # La lecture a haute voix n'est pas touchee.
    assert webui.config["tts"] == {"ENGINE": "", "VOICE": "alloy"}
    assert routeur.DICTEE_FAIT.exists()


def test_cle_interne_perimee_remplacee(routeur):
    webui = ReglagesAudioSimules(ENGINE="openai", OPENAI_API_BASE_URL=INTERNE,
                                 OPENAI_API_KEY="ancienne-cle", MODEL="free-ai-dictee")
    aligner(routeur, webui)
    assert webui.config["stt"]["OPENAI_API_KEY"] == "cle-interne-de-test"


def test_bonne_liaison_rien_ecrit(routeur):
    webui = ReglagesAudioSimules(ENGINE="openai", OPENAI_API_BASE_URL=INTERNE,
                                 OPENAI_API_KEY="cle-interne-de-test", MODEL="free-ai-dictee")
    aligner(routeur, webui)
    assert ("POST", AUDIO_MAJ) not in webui.vus


def test_autre_moteur_laisse(routeur):
    # Deepgram, le navigateur, une autre adresse : un choix de l'administration.
    for stt in ({"ENGINE": "deepgram"}, {"ENGINE": "web"},
                {"ENGINE": "openai", "OPENAI_API_BASE_URL": "https://api.openai.com/v1"}):
        webui = ReglagesAudioSimules(**stt)
        aligner(routeur, webui)
        assert ("POST", AUDIO_MAJ) not in webui.vus


def test_whisper_d_open_webui_remis_reste(routeur):
    webui = ReglagesAudioSimules()
    aligner(routeur, webui)
    # Quelqu'un remet le Whisper d'Open WebUI dans l'administration : il reste.
    webui.config["stt"]["ENGINE"] = ""
    webui.vus.clear()
    aligner(routeur, webui)
    assert ("POST", AUDIO_MAJ) not in webui.vus
    assert webui.config["stt"]["ENGINE"] == ""


def test_open_webui_en_panne_pas_de_temoin(routeur):
    aligner(routeur, ReglagesAudioSimules(panne=True))
    assert not routeur.DICTEE_FAIT.exists()


# --- La route /v1/audio/transcriptions ---

class GroqSimule:
    def __init__(self, statut=200, corps=None, coupe=False):
        self.statut = statut
        self.corps = corps if corps is not None else {"text": " Trois fois cinq, quinze. "}
        self.coupe = coupe
        self.requetes = []

    def __call__(self, requete):
        self.requetes.append(requete)
        if self.coupe:
            raise httpx.ConnectError("reseau coupe", request=requete)
        return httpx.Response(self.statut, json=self.corps)


class WhisperSimule:
    """Remplace le Whisper du routeur : ni modele, ni calcul dans les tests."""

    def __init__(self, texte="texte de l'ordinateur", panne=False):
        self.texte = texte
        self.panne = panne
        self.appels = []

    def __call__(self, audio, langue):
        self.appels.append((audio, langue))
        if self.panne:
            raise RuntimeError("modele absent")
        return self.texte


def dicter(routeur, monkeypatch, groq, local=None, champs=None, audio=b"ID3 faux mp3",
           cle="cle-interne-de-test"):
    monkeypatch.setattr(routeur, "transcrire_local", local or WhisperSimule())
    vrai = httpx.AsyncClient
    monkeypatch.setattr(routeur.httpx, "AsyncClient",
                        lambda **kw: vrai(transport=httpx.MockTransport(groq), **kw))

    async def une_fois():
        async with vrai(transport=httpx.ASGITransport(app=routeur.app),
                        base_url="http://routeur") as client:
            return await client.post(
                "/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {cle}"},
                data=champs if champs is not None else {"model": "free-ai-dictee",
                                                        "language": "fr"},
                files={"file": ("dictee.mp3", audio, "audio/mpeg")},
            )
    return asyncio.run(une_fois())


def test_groq_transcrit(routeur, monkeypatch):
    brancher_groq(monkeypatch)
    groq, local = GroqSimule(), WhisperSimule()
    r = dicter(routeur, monkeypatch, groq, local)
    assert r.status_code == 200
    assert r.json() == {"text": "Trois fois cinq, quinze."}
    assert local.appels == []
    envoi = groq.requetes[0]
    assert str(envoi.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert envoi.headers["Authorization"] == "Bearer groq-factice"
    assert b'name="model"\r\n\r\nwhisper-large-v3\r\n' in envoi.content
    # Aucune langue imposee : Whisper reconnait celle qui est parlee.
    assert b'name="language"' not in envoi.content
    assert b"ID3 faux mp3" in envoi.content


def test_langue_d_open_webui_ignoree(routeur, monkeypatch):
    # Open WebUI envoie toujours << fr >> (son WHISPER_LANGUAGE). Jusqu'au
    # 15/09/2026, le routeur le suivait : une dictee en anglais revenait
    # traduite en francais.
    brancher_groq(monkeypatch)
    groq = GroqSimule()
    dicter(routeur, monkeypatch, groq, champs={"model": "free-ai-dictee", "language": "fr"})
    assert b'name="language"' not in groq.requetes[0].content


def test_langue_d_open_webui_ignoree_sur_l_ordinateur(routeur, monkeypatch):
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.DICTEE_CHOIX.write_text('{"mode": "local"}', encoding="utf-8")
    local = WhisperSimule()
    dicter(routeur, monkeypatch, GroqSimule(), local,
           champs={"model": "free-ai-dictee", "language": "fr"})
    assert local.appels == [(b"ID3 faux mp3", None)]


def test_langue_forcee_par_le_studio(routeur, monkeypatch):
    brancher_groq(monkeypatch)
    monkeypatch.setattr(routeur, "DICTEE_LANGUE", "en")
    groq = GroqSimule()
    dicter(routeur, monkeypatch, groq)
    assert b'name="language"\r\n\r\nen\r\n' in groq.requetes[0].content


def test_reglage_de_la_langue(routeur):
    assert routeur.DICTEE_LANGUE is None
    assert routeur.langue_de_dictee("auto") is None
    assert routeur.langue_de_dictee("") is None
    assert routeur.langue_de_dictee(" FR ") == "fr"
    assert routeur.DICTEE_LANGUES == ["fr", "en"]


def test_whisper_local_reste_dans_les_langues_permises(routeur):
    permises = ["fr", "en"]
    assert routeur.langue_retenue("en", [("en", 0.9), ("fr", 0.1)], permises) == "en"
    # Une dictee courte prise pour du portugais : la plus probable des permises.
    assert routeur.langue_retenue("pt", [("pt", 0.5), ("en", 0.2), ("fr", 0.3)], permises) == "fr"
    assert routeur.langue_retenue("pt", None, permises) == "fr"


class ModeleWhisperSimule:
    """Le WhisperModel de faster-whisper 1.2.1 : la langue reconnue, puis le texte."""

    def __init__(self, reconnue, probas):
        self.reconnue, self.probas = reconnue, probas
        self.langues = []

    def transcribe(self, audio, beam_size, vad_filter, language):
        self.langues.append(language)
        langue = language or self.reconnue
        info = SimpleNamespace(language=langue,
                               all_language_probs=None if language else self.probas)
        return iter([SimpleNamespace(text=f" dit en {langue}")]), info


def transcrire_avec(routeur, monkeypatch, modele):
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=None))
    monkeypatch.setitem(routeur._whisper, "modele", modele)
    return routeur.transcrire_local(b"ID3 faux mp3", None)


def test_whisper_local_garde_l_anglais_reconnu(routeur, monkeypatch):
    modele = ModeleWhisperSimule("en", [("en", 0.9), ("fr", 0.1)])
    assert transcrire_avec(routeur, monkeypatch, modele) == "dit en en"
    assert modele.langues == [None]


def test_whisper_local_refait_hors_des_langues_permises(routeur, monkeypatch):
    modele = ModeleWhisperSimule("pt", [("pt", 0.5), ("fr", 0.3), ("en", 0.2)])
    assert transcrire_avec(routeur, monkeypatch, modele) == "dit en fr"
    assert modele.langues == [None, "fr"]


def test_groq_refuse_repli_sur_l_ordinateur(routeur, monkeypatch, caplog):
    brancher_groq(monkeypatch)
    groq = GroqSimule(429, {"error": {"message": "Rate limit reached for model whisper-large-v3"}})
    local = WhisperSimule()
    with caplog.at_level(logging.INFO):
        r = dicter(routeur, monkeypatch, groq, local)
    # Aucune erreur pour la personne qui dicte : l'ordinateur a pris le relais.
    assert r.status_code == 200
    assert r.json() == {"text": "texte de l'ordinateur"}
    assert local.appels == [(b"ID3 faux mp3", None)]
    assert "Rate limit reached" in caplog.text
    assert "repli" in caplog.text
    assert "groq-factice" not in caplog.text


def test_groq_injoignable_repli_sur_l_ordinateur(routeur, monkeypatch):
    brancher_groq(monkeypatch)
    local = WhisperSimule()
    r = dicter(routeur, monkeypatch, GroqSimule(coupe=True), local)
    assert r.status_code == 200
    assert len(local.appels) == 1


def test_choix_local_la_voix_ne_part_pas(routeur, monkeypatch):
    brancher_groq(monkeypatch)
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.DICTEE_CHOIX.write_text('{"mode": "local"}', encoding="utf-8")
    groq, local = GroqSimule(), WhisperSimule()
    r = dicter(routeur, monkeypatch, groq, local)
    assert r.status_code == 200
    assert groq.requetes == []
    assert local.appels == [(b"ID3 faux mp3", None)]


def test_sans_cle_groq_l_ordinateur(routeur, monkeypatch):
    groq, local = GroqSimule(), WhisperSimule()
    r = dicter(routeur, monkeypatch, groq, local)
    assert r.status_code == 200
    assert groq.requetes == []
    assert len(local.appels) == 1


def test_trop_gros_pour_groq_l_ordinateur(routeur, monkeypatch):
    brancher_groq(monkeypatch)
    monkeypatch.setattr(routeur, "DICTEE_MAX_OCTETS", 5)
    groq, local = GroqSimule(), WhisperSimule()
    r = dicter(routeur, monkeypatch, groq, local)
    assert r.status_code == 200
    assert groq.requetes == []
    assert len(local.appels) == 1


def test_ordinateur_en_echec_message_clair(routeur, monkeypatch):
    r = dicter(routeur, monkeypatch, GroqSimule(), WhisperSimule(panne=True))
    assert r.status_code == 500
    assert "se telecharge" in r.json()["error"]["message"]


def test_mauvais_mot_de_passe_refuse(routeur, monkeypatch):
    brancher_groq(monkeypatch)
    groq, local = GroqSimule(), WhisperSimule()
    r = dicter(routeur, monkeypatch, groq, local, cle="mauvaise")
    assert r.status_code == 401
    assert groq.requetes == [] and local.appels == []


# --- Le bouton de la page d'accueil ---

def appeler(routeur, methode, chemin, **kw):
    async def une_fois():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=routeur.app),
                                     base_url="http://routeur") as client:
            return await client.request(methode, chemin, **kw)
    return asyncio.run(une_fois())


def test_choix_enregistre_et_relu(routeur):
    assert appeler(routeur, "GET", "/dictee/etat").json()["mode"] == "groq"
    r = appeler(routeur, "POST", "/dictee/choix", json={"mode": "local"})
    assert r.status_code == 200 and r.json()["mode"] == "local"
    assert appeler(routeur, "GET", "/dictee/etat").json()["mode"] == "local"
    assert routeur.dictee_mode() == "local"


def test_choix_sans_json_refuse(routeur):
    # Ce qu'un autre site peut envoyer sans verification du navigateur.
    appeler(routeur, "POST", "/dictee/choix", json={"mode": "local"})
    r = appeler(routeur, "POST", "/dictee/choix", content=b'{"mode": "groq"}',
                headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert routeur.dictee_mode() == "local"


def test_choix_inconnu_refuse(routeur):
    r = appeler(routeur, "POST", "/dictee/choix", json={"mode": "nuage"})
    assert r.status_code == 400
    assert routeur.dictee_mode() == "groq"


def test_choix_de_depart_du_env(routeur, monkeypatch):
    monkeypatch.setenv("DICTEE_MODE", "local")
    assert routeur.dictee_mode() == "local"
    monkeypatch.setenv("DICTEE_MODE", "nimporte")
    assert routeur.dictee_mode() == "groq"
