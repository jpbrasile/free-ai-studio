"""Chaîne : le fichier joint compte AVANT de lancer.

23/09/2026 : « résume et dis-moi en anglais à voix haute », avec une PHOTO jointe.
Le verdict ne savait rien du fichier : « C'est possible », chat puis voix. Au
lancement, l'image est partie comme du texte -- 540 498 jetons, refusée par
Gemini, OpenRouter et Groq (HTTP 400).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"


@pytest.fixture
def composite(sandbox):
    return sandbox.composite


def test_le_type_du_fichier_joint(composite):
    assert composite.type_d_entree("generated-image.jpg", "image/jpeg") == "image"
    assert composite.type_d_entree("note.m4a", "audio/mp4") == "audio"
    assert composite.type_d_entree("rapport.pdf", "application/pdf") == "fichier"
    assert composite.type_d_entree("", "") == composite.SANS_FICHIER
    assert composite.entree_lue("image") == "image"
    assert composite.entree_lue("<script>") is None


def test_une_image_ne_part_pas_dans_un_chat(composite):
    chaine = composite.chaine_depuis_briques(["chat_auto", "voix_en"])
    v = composite.verifier(chaine, entree="image")
    assert v["atteignable"] == composite.NON
    assert "entree_incompatible" in v["motifs"]
    assert "Vous joignez une image" in v["pourquoi"]


def test_une_image_passe_par_la_lecture_d_image(composite):
    chaine = composite.chaine_depuis_briques(["image_lecture", "chat_auto", "voix_en"])
    v = composite.verifier(chaine, entree="image")
    assert "entree_incompatible" not in v["motifs"]


def test_la_lecture_d_image_sans_image_est_refusee(composite):
    chaine = composite.chaine_depuis_briques(["image_lecture"])
    v = composite.verifier(chaine, entree=composite.SANS_FICHIER)
    assert "entree_manquante" in v["motifs"]


def test_sans_le_champ_rien_n_est_juge(composite):
    chaine = composite.chaine_depuis_briques(["image_lecture"])
    assert "entree_manquante" not in composite.verifier(chaine)["motifs"]


def test_le_compositeur_sait_ce_qui_est_joint(composite):
    vues = []

    def modele(consigne):
        vues.append(consigne)
        return '{"noeuds": ["lecture_image", "conversation", "synthese_vocale_en"]}'

    composite.compiler("résume et dis-moi en anglais à voix haute", modele, entree="image")
    assert "joint une image" in vues[0]
    assert "lecture_image" in vues[0].split("joint une image")[1]


def test_le_lancement_juge_le_vrai_fichier_avant_tout_appel(sandbox, composite, monkeypatch):
    appels = []
    monkeypatch.setattr(composite, "lancer_par_le_routeur", lambda *a, **k: appels.append(a))
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/composite/lancer", headers=CLE,
        data={"phrase": "résume et dis-moi en anglais à voix haute", "briques": "chat_auto,voix_en",
              # La page pourrait mentir ou etre ancienne : le serveur lit le fichier.
              "entree": "aucun"},
        files={"fichier": ("generated-image.jpg", b"\xff\xd8\xff\xe0" + b"0" * 64, "image/jpeg")})
    assert r.status_code >= 400
    assert "Vous joignez une image" in r.text
    assert appels == [], "une etape est partie avant le refus"


def test_la_page_envoie_le_type_et_oublie_un_verdict_perime(sandbox):
    page = TestClient(sandbox.app, base_url=LOCAL).get("/composite").text
    assert 'corps.append("entree", typeDuFichier(f));' in page
    assert 'getElementById("fichier").addEventListener("change"' in page
    assert 'headers.get("X-Composite-Ou")' in page
