"""Quota gratuit de Gemini epuise : le chat doit continuer ET le dire."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-interne-de-test"}

# Refus au format des reponses reelles de Gemini : une liste, un detail
# QuotaFailure et un RetryInfo. La page officielle des erreurs ne documente que
# {"error": {"code", "message"}} avec les codes quota_exceeded (jour) et
# rate_limit_exceeded (minute) : les deux formes sont essayees.
REFUS_JOUR = [{"error": {
    "code": 429,
    "message": "You exceeded your current quota. Quota exceeded for metric: "
               "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
               "limit: 20, model: gemini-3.5-flash-lite\nPlease retry in 31.5s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{
             "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
             "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
             "quotaDimensions": {"location": "global", "model": "gemini-3.5-flash-lite"},
             "quotaValue": "20",
         }]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "31s"},
    ],
}}]
REFUS_JOUR_DOC = {"error": {"code": "quota_exceeded", "message": "You have exceeded your daily quota."}}
REFUS_MINUTE = {"error": {"code": "rate_limit_exceeded", "message": "Too many requests. Please retry in 12s."}}
# Le meme refus, pour le modele de Free AI Max : Google compte le quota par modele.
REFUS_JOUR_MAX = json.loads(json.dumps(REFUS_JOUR).replace("gemini-3.5-flash-lite", "gemini-3.8-flash"))


class FauxAmont:
    """Remplace les fournisseurs : ceux de `refuse` renvoient 429, les autres
    repondent en flux."""

    def __init__(self, refus, refuse=("gemini",)):
        self.refus = refus
        self.refuse = refuse
        self.appels = []

    async def __call__(self, client, name, payload):
        self.appels.append(name)
        requete = httpx.Request("POST", f"https://{name}.invalid/chat/completions")
        if name in self.refuse:
            return httpx.Response(429, json=self.refus, request=requete)
        flux = (b'data: {"choices":[{"index":0,"delta":{"content":"Bonjour"}}]}\n\n'
                b"data: [DONE]\n\n")
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=flux, request=requete)


def demander(client, modele="free-ai-auto"):
    return client.post("/v1/chat/completions", headers=CLE, json={
        "model": modele, "stream": True,
        "messages": [{"role": "user", "content": "Bonjour"}],
    })


def fiche(etat, nom):
    return next(f for f in etat["fournisseurs"] if f["nom"] == nom)


def test_defaut_flash_lite(routeur):
    assert routeur.PROVIDERS["gemini"]["model"] == "gemini-3.5-flash-lite"


def test_lire_quota_forme_reelle(routeur):
    q = routeur.lire_quota(REFUS_JOUR)
    assert q["par_jour"] is True
    assert q["limite"] == 20
    assert q["modele"] == "gemini-3.5-flash-lite"


def test_lire_quota_forme_documentee(routeur):
    assert routeur.lire_quota(REFUS_JOUR_DOC)["par_jour"] is True
    q = routeur.lire_quota(REFUS_MINUTE)
    assert q["par_jour"] is False
    assert q["attente_s"] == 12.0


def test_lire_quota_corps_illisible(routeur):
    assert routeur.lire_quota(None) == {}
    assert routeur.lire_quota("pas du json") == {}
    assert routeur.lire_quota([1, {"x": [None]}]) == {}


def test_minuit_pacifique(routeur):
    maintenant = time.time()
    # 25 h : le jour du passage a l'heure d'hiver dure une heure de plus.
    assert 0 < routeur.minuit_pacifique(maintenant) - maintenant <= 25 * 3600


def test_quota_du_jour_bascule_annoncee_puis_pause(routeur, monkeypatch):
    amont = FauxAmont(REFUS_JOUR)
    monkeypatch.setattr(routeur, "open_upstream", amont)
    client = TestClient(routeur.app)

    r1 = demander(client)
    assert r1.status_code == 200
    assert amont.appels == ["gemini", "openrouter"]
    assert "limite gratuite du jour" in r1.text
    assert "20 demandes" in r1.text
    # L'avis passe AVANT la reponse, pas noye a la fin.
    assert r1.text.index("limite gratuite") < r1.text.index("Bonjour")

    # Message suivant : Gemini n'est plus sollicite (pause jusqu'a minuit,
    # heure du Pacifique) et l'avis n'est pas repete a chaque message.
    r2 = demander(client)
    assert r2.status_code == 200
    assert amont.appels == ["gemini", "openrouter", "openrouter"]
    assert "limite gratuite" not in r2.text

    etat = client.get("/quotas/etat").json()
    gemini = fiche(etat, "gemini")
    assert gemini["en_pause"] is True
    assert gemini["quota_du_jour_atteint"] is True
    assert gemini["limite_annoncee"] == 20
    assert abs(gemini["reprise_a"] - routeur.minuit_pacifique(time.time())) < 5
    assert etat["secours_en_cours"] is True
    assert etat["dernier_service"]["fournisseur"] == "openrouter"
    assert etat["dernier_service"]["bascule"] is True

    # La page Diagnostic porte le meme etat. Sa verification de la liaison avec
    # Open WebUI appelle le reseau : remplacee ici, elle n'est pas l'objet du test.
    async def liaison_hors_reseau(*args, **kwargs):
        return {}
    monkeypatch.setattr(routeur, "etat_liaison", liaison_hors_reseau)
    assert fiche(client.get("/diagnostic/etat").json()["quotas"], "gemini")["en_pause"] is True


def test_limite_minute_pause_courte(routeur, monkeypatch):
    amont = FauxAmont(REFUS_MINUTE)
    monkeypatch.setattr(routeur, "open_upstream", amont)
    client = TestClient(routeur.app)

    r = demander(client)
    assert r.status_code == 200
    assert "sature" in r.text or "saturé" in r.text
    gemini = fiche(client.get("/quotas/etat").json(), "gemini")
    assert gemini["en_pause"] is True
    assert gemini["quota_du_jour_atteint"] is False
    assert gemini["reprise_a"] - time.time() <= 300


def test_sans_bascule_aucun_avis(routeur, monkeypatch):
    class ToutVaBien(FauxAmont):
        async def __call__(self, client, name, payload):
            self.appels.append(name)
            requete = httpx.Request("POST", "https://gemini.invalid/chat/completions")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=b'data: {"choices":[]}\n\ndata: [DONE]\n\n',
                                  request=requete)

    amont = ToutVaBien(None)
    monkeypatch.setattr(routeur, "open_upstream", amont)
    client = TestClient(routeur.app)
    r = demander(client)
    assert amont.appels == ["gemini"]
    assert "free-ai-avis" not in r.text
    assert client.get("/quotas/etat").json()["secours_en_cours"] is False


def modeles_proposes(client):
    return [m["id"] for m in client.get("/v1/models", headers=CLE).json()["data"]]


def test_deux_choix_dans_le_chat(routeur):
    assert modeles_proposes(TestClient(routeur.app)) == ["free-ai-auto", "free-ai-max"]
    assert routeur.PROVIDERS["gemini_max"]["model"] == "gemini-3.8-flash"


def test_max_absent_sans_cle_gemini(routeur, monkeypatch):
    # Sans cle Gemini, Max repondrait comme Auto sous un nom qui promet plus.
    monkeypatch.delenv("GEMINI_API_KEY")
    assert modeles_proposes(TestClient(routeur.app)) == ["free-ai-auto"]


def test_choix_direct_d_un_modele_refuse(routeur):
    r = TestClient(routeur.app).post("/v1/chat/completions", headers=CLE, json={
        "model": "gemini-3.8-flash", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 403


def test_max_quota_a_part(routeur, monkeypatch):
    amont = FauxAmont(REFUS_JOUR_MAX, refuse=("gemini_max",))
    monkeypatch.setattr(routeur, "open_upstream", amont)
    client = TestClient(routeur.app)

    # Max essaie le modele fort ; refuse pour la journee, Flash-Lite prend le
    # relais, et l'avis nomme les deux.
    r1 = demander(client, "free-ai-max")
    assert r1.status_code == 200
    assert amont.appels == ["gemini_max", "gemini"]
    assert "Gemini Max" in r1.text
    assert "limite gratuite du jour" in r1.text
    assert "gemini-3.5-flash-lite" in r1.text
    assert r1.text.index("limite gratuite") < r1.text.index("Bonjour")

    # Le quota de Max est a part : Auto sert toujours avec Flash-Lite, sans
    # avis, et Max ne resollicite pas le modele en pause.
    r2 = demander(client, "free-ai-auto")
    assert "free-ai-avis" not in r2.text
    demander(client, "free-ai-max")
    assert amont.appels == ["gemini_max", "gemini", "gemini", "gemini"]

    etat = client.get("/quotas/etat").json()
    assert fiche(etat, "gemini_max")["quota_du_jour_atteint"] is True
    assert abs(fiche(etat, "gemini_max")["reprise_a"] - routeur.minuit_pacifique(time.time())) < 5
    assert fiche(etat, "gemini")["en_pause"] is False
    assert etat["secours_max_en_cours"] is True
    assert etat["secours_en_cours"] is False


def test_pause_de_gemini_pendant_max_est_dite_a_auto(routeur, monkeypatch):
    # Flash-Lite atteint sa limite pendant une demande Max : la demande Auto
    # suivante, servie par le secours, doit le dire.
    amont = FauxAmont(REFUS_JOUR, refuse=("gemini_max", "gemini"))
    monkeypatch.setattr(routeur, "open_upstream", amont)
    client = TestClient(routeur.app)

    assert demander(client, "free-ai-max").status_code == 200
    assert amont.appels == ["gemini_max", "gemini", "openrouter"]
    r2 = demander(client, "free-ai-auto")
    assert r2.status_code == 200
    assert amont.appels[3:] == ["openrouter"]
    assert "free-ai-avis" in r2.text
    assert "limite gratuite du jour" in r2.text
    assert r2.text.index("limite gratuite") < r2.text.index("Bonjour")


def test_une_seule_cle_refus_du_jour_des_la_premiere_demande(routeur, monkeypatch):
    # Le cas du debutant : une cle Gemini, rien d'autre. Le refus du jour doit
    # arriver en francais des la premiere demande, pas en erreur technique.
    monkeypatch.delenv("OPENROUTER_API_KEY")
    amont = FauxAmont(REFUS_JOUR)
    monkeypatch.setattr(routeur, "open_upstream", amont)
    client = TestClient(routeur.app)

    r1 = demander(client)
    assert r1.status_code == 429
    assert "ont atteint leur limite" in r1.json()["detail"]
    assert "Free AI Max" in r1.json()["detail"]
    assert int(r1.headers["retry-after"]) > 0
    r2 = demander(client)
    assert r2.status_code == 429
    assert amont.appels == ["gemini"]


class Coupure(FauxAmont):
    """Les services de `refuse` ne repondent pas : 503, ou coupure reseau."""

    def __init__(self, maniere, refuse=("gemini",)):
        super().__init__(None, refuse)
        self.maniere = maniere

    async def __call__(self, client, name, payload):
        if name not in self.refuse:
            return await super().__call__(client, name, payload)
        self.appels.append(name)
        requete = httpx.Request("POST", f"https://{name}.invalid/chat/completions")
        if self.maniere == "coupure":
            raise httpx.ConnectError("coupure", request=requete)
        return httpx.Response(503, json={"error": {"code": 503, "message": "The model is overloaded."}},
                              request=requete)


@pytest.mark.parametrize("maniere", ["503", "coupure"])
def test_service_qui_ne_repond_pas(routeur, monkeypatch, maniere):
    amont = Coupure(maniere)
    monkeypatch.setattr(routeur, "open_upstream", amont)
    client = TestClient(routeur.app)

    r1 = demander(client)
    assert r1.status_code == 200
    assert "ne répond pas" in r1.text
    assert r1.text.index("ne répond pas") < r1.text.index("Bonjour")
    # Pause courte : le message suivant ne repaie pas l'aller-retour rate, et
    # l'avis n'est pas repete.
    r2 = demander(client)
    assert amont.appels == ["gemini", "openrouter", "openrouter"]
    assert "free-ai-avis" not in r2.text
    gemini = fiche(client.get("/quotas/etat").json(), "gemini")
    assert gemini["en_pause"] is True
    assert gemini["indisponible"] is True
    assert gemini["quota_du_jour_atteint"] is False
    assert gemini["reprise_a"] - time.time() <= 60


def test_tout_coupe_dit_503_en_francais(routeur, monkeypatch):
    monkeypatch.setattr(routeur, "open_upstream", Coupure("coupure", refuse=("gemini", "openrouter")))
    r = demander(TestClient(routeur.app))
    assert r.status_code == 503
    assert "Aucun service gratuit branché ne répond" in r.json()["detail"]


def test_enable_gemini_max_false_meme_cle_saisie_dans_cles(routeur, monkeypatch):
    # La cle collee dans /cles active Gemini ; elle ne doit pas ramener Max.
    monkeypatch.delenv("GEMINI_API_KEY")
    routeur.store_key("GEMINI_API_KEY", "gemini-factice")
    client = TestClient(routeur.app)
    assert modeles_proposes(client) == ["free-ai-auto", "free-ai-max"]
    monkeypatch.setenv("ENABLE_GEMINI_MAX", "false")
    assert modeles_proposes(client) == ["free-ai-auto"]


def test_sans_cle_le_chat_envoie_a_la_page_cles(routeur, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    r = demander(TestClient(routeur.app))
    assert r.status_code == 503
    assert "http://localhost:8010/cles" in r.json()["detail"]
    assert ".env" not in r.json()["detail"]


def test_fausse_cle_gemini_message_francais(routeur, monkeypatch):
    # Refus releve sur la machine vierge : Google repond 400, pas 401.
    def refus(requete):
        return httpx.Response(400, json={"error": {"code": 400, "message": "Please pass a valid API key",
                                                   "status": "INVALID_ARGUMENT"}})

    vrai = httpx.AsyncClient
    monkeypatch.setattr(routeur.httpx, "AsyncClient",
                        lambda **kw: vrai(transport=httpx.MockTransport(refus), **kw))
    r = asyncio.run(routeur.verify_key("gemini", "cle-factice-du-debutant"))
    assert r["valide"] is False
    assert r["message"].startswith("Cle refusee.")
    assert "en anglais : Please pass a valid API key" in r["message"]
