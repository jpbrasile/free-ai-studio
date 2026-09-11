"""Quota gratuit de Gemini epuise : le chat doit continuer ET le dire."""
from __future__ import annotations

import time

import httpx
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


class FauxAmont:
    """Remplace les fournisseurs : Gemini refuse, OpenRouter repond en flux."""

    def __init__(self, refus):
        self.refus = refus
        self.appels = []

    async def __call__(self, client, name, payload):
        self.appels.append(name)
        requete = httpx.Request("POST", f"https://{name}.invalid/chat/completions")
        if name == "gemini":
            return httpx.Response(429, json=self.refus, request=requete)
        flux = (b'data: {"choices":[{"index":0,"delta":{"content":"Bonjour"}}]}\n\n'
                b"data: [DONE]\n\n")
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=flux, request=requete)


def demander(client):
    return client.post("/v1/chat/completions", headers=CLE, json={
        "model": "free-ai-auto", "stream": True,
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
