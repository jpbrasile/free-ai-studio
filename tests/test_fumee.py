"""Fumee du jour du routeur (SP-FUMEE-QUOTIDIENNE, 26/09/2026).

Un faux reseau (httpx.MockTransport) remplace les services : aucun appel reel.
Ce qui est tenu : seules des listes de modeles sont demandees (jamais une
reponse), aucune cle n'est ecrite, pas de cle = << non configure >>, un modele
renomme = << echec >> avec son nom, et /diagnostic/etat porte le bloc.
"""
from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient


def faux_reseau(routeur, retires=(), statut=200):
    """Rend (client, appels) : chaque service liste les modeles du routeur,
    sauf ceux de `retires`."""
    appels = []
    attendus = routeur.fumee_modeles_attendus()

    def repondre(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        if statut != 200:
            return httpx.Response(statut, json={"error": "cle refusee gemini-factice"})
        hote = requete.url.host
        if "googleapis" in hote:
            noms = [m for m in attendus["gemini"] if m not in retires]
            return httpx.Response(200, json={"models": [{"name": "models/" + m} for m in noms]})
        nom = "groq" if "groq" in hote else "openrouter"
        noms = [m for m in attendus[nom] if m not in retires]
        return httpx.Response(200, json={"data": [{"id": m} for m in noms]})

    return httpx.Client(transport=httpx.MockTransport(repondre)), appels


def service(resultat, nom):
    return next(s for s in resultat["services"] if s["nom"] == nom)


def test_seules_des_listes_sont_demandees(routeur, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-factice")
    client, appels = faux_reseau(routeur)
    resultat = routeur.faire_la_fumee(client)
    assert appels, "aucun appel : la fumee n'a rien verifie"
    for r in appels:
        assert r.method == "GET"
        assert "completions" not in r.url.path and "generateContent" not in r.url.path
        assert r.url.path.endswith("/models")
    assert {service(resultat, n)["etat"] for n in ("gemini", "openrouter", "groq")} == {"ok"}


def test_aucune_cle_dans_le_fichier(routeur, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-factice")
    # Meme un refus dont le corps cite la cle : le corps n'est jamais recopie.
    client, _ = faux_reseau(routeur, statut=401)
    resultat = routeur.faire_la_fumee(client)
    texte = routeur.FUMEE_FICHIER.read_text(encoding="utf-8")
    for cle in ("gemini-factice", "openrouter-factice", "groq-factice"):
        assert cle not in texte
    assert service(resultat, "gemini")["etat"] == "échec"
    assert service(resultat, "gemini")["motif"] == "HTTP 401 (refus)"


def test_sans_cle_non_configure(routeur, monkeypatch):
    # Le fixture ne pose pas de cle Groq.
    client, appels = faux_reseau(routeur)
    resultat = routeur.faire_la_fumee(client)
    assert service(resultat, "groq")["etat"] == "non configuré"
    assert not any("groq" in r.url.host for r in appels)


def test_modele_renomme_echec_avec_son_nom(routeur):
    retire = routeur.PROVIDERS["gemini_max"]["model"]
    client, _ = faux_reseau(routeur, retires=(retire,))
    resultat = routeur.faire_la_fumee(client)
    gemini = service(resultat, "gemini")
    assert gemini["etat"] == "échec"
    assert retire in gemini["motif"]
    assert service(resultat, "openrouter")["etat"] == "ok"


def test_reseau_coupe_motif_court(routeur):
    def couper(requete):
        raise httpx.ConnectError("injoignable", request=requete)
    client = httpx.Client(transport=httpx.MockTransport(couper))
    resultat = routeur.faire_la_fumee(client)
    assert service(resultat, "gemini")["motif"] == "ConnectError"


def test_modal_kaggle_hf_non_couverts(routeur):
    client, _ = faux_reseau(routeur)
    resultat = routeur.faire_la_fumee(client)
    for nom in ("modal", "kaggle", "huggingface"):
        assert service(resultat, nom)["etat"] == "non couvert"


def test_diagnostic_porte_la_fumee(routeur, monkeypatch):
    async def liaison_hors_reseau(*args, **kwargs):
        return {}
    monkeypatch.setattr(routeur, "etat_liaison", liaison_hors_reseau)
    http = TestClient(routeur.app)
    assert http.get("/diagnostic/etat").json()["fumee"] is None
    client, _ = faux_reseau(routeur)
    routeur.faire_la_fumee(client)
    fumee = http.get("/diagnostic/etat").json()["fumee"]
    assert fumee == json.loads(routeur.FUMEE_FICHIER.read_text(encoding="utf-8"))
    assert service(fumee, "gemini")["etat"] == "ok"
    assert http.get("/diagnostic/fumee").json()["fumee"] == fumee
    assert "Fumee du jour" in http.get("/diagnostic").text


def test_le_fil_part_au_demarrage(routeur, monkeypatch):
    parti = []
    monkeypatch.setenv("ROUTEUR_FUMEE", "true")
    monkeypatch.setattr(routeur, "boucle_fumee", lambda: parti.append(True))

    async def rien():
        return None
    # Le demarrage d'origine pose les reglages du chat : hors reseau ici.
    monkeypatch.setattr(routeur, "poser_reglages_webui", rien)
    monkeypatch.setattr(routeur, "prechauffer_whisper", lambda: None)
    with TestClient(routeur.app) as http:
        assert http.get("/health").status_code == 200
    assert parti == [True]


def test_coupee_par_reglage(routeur, monkeypatch):
    parti = []
    monkeypatch.setattr(routeur, "boucle_fumee", lambda: parti.append(True))

    async def rien():
        return None
    monkeypatch.setattr(routeur, "poser_reglages_webui", rien)
    monkeypatch.setattr(routeur, "prechauffer_whisper", lambda: None)
    with TestClient(routeur.app):
        pass
    assert parti == []
