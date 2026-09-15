"""Dessins SVG montres sous la reponse et telechargeables (demande du 15/09/2026)."""
from __future__ import annotations

import json
import logging
import re

import httpx
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-interne-de-test"}
SVG = '<svg viewBox="0 0 10 10"><rect width="10" height="10" fill="teal"/></svg>'
FIN = b"data: [DONE]\n\n"


def morceau(texte):
    return ("data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": texte}}]})
            + "\n\n").encode("utf-8")


class Amont:
    """Remplace les fournisseurs. La reponse arrive en morceaux de 7 octets,
    coupes n'importe ou : au milieu d'une ligne, du dessin, du marqueur final.
    Ceux de `refuse` renvoient 400."""

    def __init__(self, octets, type_="text/event-stream", refuse=()):
        self.octets = octets
        self.type_ = type_
        self.refuse = refuse

    async def __call__(self, client, name, payload):
        requete = httpx.Request("POST", f"https://{name}.invalid/chat/completions")
        if name in self.refuse:
            return httpx.Response(400, json={"error": {
                "code": 400, "message": "Invalid value at 'contents[0]'", "status": "INVALID_ARGUMENT"}},
                request=requete)
        octets = self.octets

        async def morceaux():
            for i in range(0, len(octets), 7):
                yield octets[i:i + 7]
        return httpx.Response(200, headers={"content-type": self.type_}, content=morceaux(),
                              request=requete)


def demander(client, stream=True):
    return client.post("/v1/chat/completions", headers=CLE, json={
        "model": "free-ai-auto", "stream": stream,
        "messages": [{"role": "user", "content": "fais moi un cube en svg"}],
    })


def ajout_dessin(texte):
    """Le texte du morceau ajoute par le routeur, et l'adresse du dessin."""
    ligne = next(x for x in texte.splitlines() if "free-ai-dessin" in x)
    contenu = json.loads(ligne[5:])["choices"][0]["delta"]["content"]
    adresse = re.search(r"\((http://localhost:8010(/dessins/[0-9a-f]{16}\.svg))\)", contenu)
    return contenu, adresse.group(2)


def test_flux_sans_dessin_inchange(routeur, monkeypatch):
    flux = morceau("Bonjour") + morceau(" toi, voici `<svg>` et `</svg>`.") + FIN
    monkeypatch.setattr(routeur, "open_upstream", Amont(flux))
    r = demander(TestClient(routeur.app))
    assert r.status_code == 200
    assert r.content == flux


def test_flux_avec_dessin_montre_et_telechargeable(routeur, monkeypatch):
    flux = morceau("Voici :\n```svg\n" + SVG[:20]) + morceau(SVG[20:] + "\n```") + FIN
    monkeypatch.setattr(routeur, "open_upstream", Amont(flux))
    client = TestClient(routeur.app)
    r = demander(client)
    assert r.status_code == 200
    # Le texte du fournisseur passe tel quel ; l'ajout vient avant [DONE].
    assert r.content.startswith(flux[:-len(FIN)])
    assert r.content.endswith(FIN)
    contenu, chemin = ajout_dessin(r.text)
    assert "![dessin-" in contenu
    assert "Télécharger dessin-" in contenu

    vu = client.get(chemin)
    assert vu.status_code == 200
    assert vu.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in vu.headers["content-security-policy"]
    assert "content-disposition" not in vu.headers
    # Sans xmlns, une balise <img> n'afficherait rien.
    assert vu.text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox=')

    pris = client.get(chemin + "?telecharger=1")
    assert pris.status_code == 200
    assert pris.headers["content-disposition"].startswith('attachment; filename="dessin-')
    assert pris.content == vu.content


def test_flux_sans_marqueur_final(routeur, monkeypatch):
    monkeypatch.setattr(routeur, "open_upstream", Amont(morceau(SVG)))
    r = demander(TestClient(routeur.app))
    assert r.text.startswith(morceau(SVG).decode())
    ajout_dessin(r.text)


def test_reponse_d_un_bloc(routeur, monkeypatch):
    corps = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant", "content": SVG}}]})
    monkeypatch.setattr(routeur, "open_upstream", Amont(corps.encode(), type_="application/json"))
    r = demander(TestClient(routeur.app), stream=False)
    contenu = r.json()["choices"][0]["message"]["content"]
    assert contenu.startswith(SVG)
    assert "Télécharger dessin-" in contenu


def test_extraire_svg(routeur):
    ext = routeur.extraire_svg
    assert ext("la balise `<svg>` puis `</svg>`") == []
    assert ext("<svg></svg>") == []
    deja = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>'
    assert ext(deja) == [deja]
    assert ext(deja + " " + deja) == [deja]
    quatre = "".join('<svg><circle r="%d"/></svg>' % i for i in range(4))
    assert len(ext(quatre)) == 3
    enorme = "<svg><g>" + "x" * routeur.DESSIN_MAX_OCTETS + "</g></svg>"
    assert ext(enorme) == []


def test_taille_en_pixels(routeur):
    # Le cube du 15/09 : width="100%", affiche en 0 x 0 dans Open WebUI.
    (cube,) = routeur.extraire_svg('<svg viewBox="0 0 200 100" width="100%" height="100%"><rect/></svg>')
    assert 'width="320" height="160"' in cube
    assert "100%" not in cube
    # Taille deja en pixels : rien ne change.
    fixe = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9" width="90" height="90px"><rect/></svg>'
    assert routeur.extraire_svg(fixe) == [fixe]
    # Ni taille ni viewBox : rien a tirer, rien ne change.
    nu = '<svg xmlns="http://www.w3.org/2000/svg"><rect stroke-width="2"/></svg>'
    assert routeur.extraire_svg(nu) == [nu]


def test_dessins_les_plus_anciens_partent(routeur, monkeypatch):
    monkeypatch.setattr(routeur, "DESSINS_MAX", 2)
    noms = [routeur.ranger_dessin('<svg><circle r="%d"/></svg>' % i) for i in range(3)]
    restants = sorted(p.name for p in routeur.DESSINS_DIR.glob("*.svg"))
    assert len(restants) == 2
    assert noms[-1] in restants


def test_nom_de_dessin_controle(routeur):
    client = TestClient(routeur.app)
    for nom in ("x.svg", "0123456789ABCDEF.svg", "0123456789abcdef.svg.html",
                "0123456789abcdef.svg"):
        assert client.get("/dessins/" + nom).status_code == 404


def test_refus_du_fournisseur_dit_dans_le_journal(routeur, monkeypatch, caplog):
    # Le 15/09/2026, la cause d'un 400 de Gemini etait perdue : stats ne la
    # garde que jusqu'au succes suivant.
    monkeypatch.setattr(routeur, "open_upstream", Amont(morceau("Bonjour") + FIN, refuse=("gemini",)))
    with caplog.at_level(logging.WARNING):
        r = demander(TestClient(routeur.app))
    assert r.status_code == 200
    assert "Invalid value at 'contents[0]'" in caplog.text
    assert "gemini-factice" not in caplog.text
