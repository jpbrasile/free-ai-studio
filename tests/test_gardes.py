"""Les boutons du Studio n'obeissent qu'aux pages du Studio (16/09/2026).

Le Studio ecoute sur cet ordinateur, sans mot de passe. Un site ouvert dans le
meme navigateur pouvait lui poster une demande sans rien lire de la reponse :
assez pour effacer une cle, lancer une mise a jour ou une reparation. Le
navigateur pose lui-meme les en-tetes verifies ici ; une page ne peut pas les
fabriquer.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

AUTRE_SITE = {"Sec-Fetch-Site": "cross-site", "Origin": "https://site-visite.example"}
LA_PAGE = {"Sec-Fetch-Site": "same-origin"}
ADRESSE = "http://localhost:8010"


def page(module, base_url=ADRESSE):
    return TestClient(module.app, base_url=base_url)


def test_un_autre_site_n_efface_pas_une_cle(routeur):
    r = page(routeur).post("/cles/oublier", headers=AUTRE_SITE, json={"fournisseur": "gemini"})
    assert r.status_code == 403
    assert "Studio" in r.json()["detail"]


def test_la_page_du_studio_efface_la_cle(routeur):
    r = page(routeur).post("/cles/oublier", headers=LA_PAGE, json={"fournisseur": "gemini"})
    assert r.status_code == 200 and r.json()["oubliee"] is True


def test_sans_en_tetes_la_demande_passe(routeur):
    # Un vieux navigateur n'envoie pas Sec-Fetch-Site : le Studio doit
    # continuer de fonctionner pour lui.
    r = page(routeur).post("/cles/oublier", json={"fournisseur": "gemini"})
    assert r.status_code == 200


def test_origine_d_un_autre_site_refusee(routeur):
    # Sans Sec-Fetch-Site, l'origine suffit a trancher.
    r = page(routeur).post("/cles/oublier", headers={"Origin": "https://site-visite.example"},
                           json={"fournisseur": "gemini"})
    assert r.status_code == 403


def test_origine_du_studio_acceptee(routeur):
    r = page(routeur).post("/cles/oublier", headers={"Origin": ADRESSE},
                           json={"fournisseur": "gemini"})
    assert r.status_code == 200


def test_formulaire_d_un_autre_site_refuse(routeur):
    # Un formulaire poste sans JavaScript : le navigateur n'y met jamais
    # application/json, et ne demande donc aucune permission au Studio.
    r = page(routeur).post("/cles/tester", headers={"Content-Type": "text/plain"},
                           content=b'{"fournisseur": "gemini", "cle": "volee"}')
    assert r.status_code == 415


def test_mise_a_jour_refusee_a_un_autre_site(routeur):
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    r = page(routeur).post("/maj/lancer", headers=AUTRE_SITE)
    assert r.status_code == 403
    assert not routeur.MAJ_DEMANDE.exists()


def test_reparation_refusee_a_un_autre_site(routeur):
    # Refus avant tout appel au chat : la reparation ne part pas.
    r = page(routeur).post("/diagnostic/reparer", headers=AUTRE_SITE)
    assert r.status_code == 403


def test_dictee_refusee_a_un_autre_site(routeur):
    r = page(routeur).post("/dictee/choix", headers=AUTRE_SITE, json={"mode": "groq"})
    assert r.status_code == 403


def test_identifiants_du_sandbox_proteges(sandbox):
    client = page(sandbox, "http://localhost:8020")
    r = client.post("/cles/oublier", headers=AUTRE_SITE, json={"backend": "modal"})
    assert r.status_code == 403
    r = client.post("/cles/tester", headers=AUTRE_SITE,
                    json={"backend": "modal", "valeurs": {"MODAL_TOKEN_ID": "x",
                                                          "MODAL_TOKEN_SECRET": "y"}})
    assert r.status_code == 403
    # Rien n'a ete essaye ni enregistre aupres de Modal.
    assert sandbox.stored_keys() == {}
