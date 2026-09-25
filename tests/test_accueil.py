"""Le bouton « 🏠 Studio » sur chaque page (accueil.py, demande du 25/09/2026)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parents[1]
MARQUE = 'id="studio-accueil"'


def pages_html(app) -> set:
    return {r.path for r in app.routes
            if getattr(r, "response_class", None) is HTMLResponse and "GET" in getattr(r, "methods", ())}


def test_les_deux_exemplaires_sont_identiques():
    octets = {(RACINE / d / "accueil.py").read_bytes() for d in ("free-tier-manager", "sandbox-manager")}
    assert len(octets) == 1, "les deux exemplaires de accueil.py divergent"


def test_le_routeur_declare_toutes_ses_pages_sauf_studio(routeur):
    assert pages_html(routeur.app) - {"/studio"} == set(routeur.PAGES_HTML)


def test_le_bac_a_sable_declare_toutes_ses_pages(sandbox):
    assert pages_html(sandbox.app) == set(sandbox.PAGES_HTML)


@pytest.mark.parametrize("service", ["routeur", "sandbox"])
def test_chaque_page_porte_le_bouton_une_fois(service, request):
    module = request.getfixturevalue(service)
    client = TestClient(module.app, base_url="http://localhost")
    vues = 0
    for chemin in module.PAGES_HTML:
        r = client.get(chemin)
        if r.status_code != 200:
            continue
        vues += 1
        assert r.text.count(MARQUE) == 1, chemin
        if "</body>" in r.text:   # sinon le bouton est ajoute a la fin, lu pareil
            assert r.text.index(MARQUE) < r.text.rindex("</body>"), chemin
        assert "content-length" not in r.headers or int(r.headers["content-length"]) == len(r.content)
    assert vues >= 3


def test_la_page_studio_et_les_reponses_json_restent_intactes(routeur):
    client = TestClient(routeur.app, base_url="http://localhost")
    assert MARQUE not in client.get("/studio").text
    assert MARQUE not in client.get("/health").text


def test_poser_une_seule_fois_et_sans_body(sandbox):
    accueil = sandbox.accueil
    une = accueil.poser(b"<html><body><p>x</p></body></html>")
    assert accueil.poser(une) == une and une.count(MARQUE.encode()) == 1
    assert accueil.poser(b"<p>sans body</p>").endswith(b"</script>")
