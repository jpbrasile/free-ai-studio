"""Chaîne : le texte rendu en chemin se voit, à côté du son.

23/09/2026 : « décris le fichier joint en anglais à voix haute, rajoute le texte
lu » -- la chaîne a marché (lecture d'image, chat, voix anglaise), mais « on a
la voix mais pas le texte ». Et une chaîne finissant par du texte ne montrait
qu'un lien « Télécharger » : la page lisait toute réponse comme un fichier.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
SON = b"RIFF\x24\x00\x00\x00WAVEfmt "


def rendus(etape, entree):
    return {"image_lecture": "A lighthouse in the rain.",
            "chat_auto": "A <b>lighthouse</b> stands in heavy rain.",
            "voix_en": SON}[etape["brique"]]


def lancer(sandbox, monkeypatch, briques, fichier=None):
    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur", rendus)
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/composite/lancer", headers=CLE, data={"phrase": "décris", "briques": briques},
        files={"fichier": fichier} if fichier else None)
    assert r.status_code == 200, r.text
    return r.json()


def test_le_son_voyage_avec_les_textes(sandbox, monkeypatch):
    d = lancer(sandbox, monkeypatch, "image_lecture,chat_auto,voix_en",
               ("photo.jpg", b"\xff\xd8\xff\xe0" + b"0" * 32, "image/jpeg"))
    assert base64.b64decode(d["fichier"]) == SON
    assert d["type"].startswith("audio/")
    assert [t["texte"] for t in d["textes"]] == ["A lighthouse in the rain.",
                                                  "A <b>lighthouse</b> stands in heavy rain."]
    assert d["derniere"] == "Lire à haute voix, anglais"


def test_une_chaine_de_texte_rend_son_texte(sandbox, monkeypatch):
    d = lancer(sandbox, monkeypatch, "chat_auto")
    assert d["texte"] == "A <b>lighthouse</b> stands in heavy rain."
    assert "fichier" not in d


def afficher(page: str, reponse: dict) -> str:
    debut = page.index("function phraseEcoute(e){")
    fin = page.index("\nfunction typeDuFichier", debut)
    rendu_debut = page.index("    const d = await r.corps.json();")
    rendu_fin = page.index("  } finally {", rendu_debut)
    code = (page[debut:fin]
            + "\nconst champs = {resultat: {innerHTML: ''}};\n"
            + "const document = {getElementById: id => champs[id]};\n"
            + "(async () => {\n"
            + "const r = {corps: {json: async () => (" + json.dumps(reponse) + ")}};\n"
            + page[rendu_debut:rendu_fin]
            + "\nconsole.log(champs.resultat.innerHTML);\n})();\n")
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    return sortie.stdout


@pytest.fixture
def page(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    return TestClient(sandbox.app, base_url=LOCAL).get("/composite").text


def test_la_page_montre_le_texte_lu_sous_la_voix(page):
    html = afficher(page, {"fichier": base64.b64encode(SON).decode(), "type": "audio/wav",
                           "nom": "sortie.wav", "derniere": "Lire à haute voix, anglais",
                           "textes": [{"fonction": "Lecture d'image", "texte": "A lighthouse in the rain."},
                                      {"fonction": "Chat, Free AI Auto", "texte": "A <b>lighthouse</b>."}]})
    assert "<audio controls" in html
    assert "Le texte transmis à « Lire à haute voix, anglais »" in html
    assert "A &lt;b&gt;lighthouse&lt;/b&gt;." in html, "texte du modele non echappe"
    assert "<details><summary>Rendu par Lecture d&#39;image" in html


def test_la_page_montre_enfin_un_resultat_texte(page):
    html = afficher(page, {"texte": "Bonjour.", "derniere": "Chat, Free AI Auto",
                           "textes": [{"fonction": "Chat, Free AI Auto", "texte": "Bonjour."}]})
    assert "<div class=texte><p>Bonjour.</p></div>" in html
    assert "Télécharger" not in html
