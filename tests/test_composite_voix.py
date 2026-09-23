"""Chaîne : la voix dit des phrases, pas du Markdown, et passe par l'écoute.

23/09/2026, image → chat → voix anglaise : Piper a lu « ### », « ** », des
numéros de liste et le titre « English Text to Read Aloud ». Et le
propriétaire : « on avait évité les erreurs dans la restitution vocale en ayant
ajouté un filtre basé sur la cohérence avec le stt » -- le filtre du dialogue,
que la voix d'une chaîne ne traversait pas. Le texte montré, lui, restait en
Markdown brut.
"""
from __future__ import annotations

import array
import io
import json
import math
import shutil
import subprocess
import wave

import pytest
from fastapi.testclient import TestClient

LOCAL = "http://127.0.0.1:8020"

EXPOSE = """### Description
Here is the text:

### English Text to Read Aloud
**A lighthouse** stands in the *rain*.
1. The sea is grey.
- Waves hit the rocks
---
| a | b |
|---|---|
"""


@pytest.fixture
def composite(sandbox):
    return sandbox.composite


def test_la_voix_ne_lit_ni_titres_ni_symboles(composite):
    dit = composite.texte_a_dire(EXPOSE)
    assert "English Text to Read Aloud" not in dit
    assert "#" not in dit and "*" not in dit and "---" not in dit
    assert dit.splitlines() == ["Here is the text:", "A lighthouse stands in the rain.",
                                "The sea is grey.", "Waves hit the rocks.", "a, b."]


def test_le_chat_sait_qu_il_ecrit_pour_une_voix(composite):
    etape = {"brique": "chat_auto", "fonction": "Chat", "demande": "décris en anglais"}
    assert "lue à haute voix" not in composite._consigne_du_chat(etape, "texte")
    oral = composite._consigne_du_chat(dict(etape, suivante="voix_en"), "texte")
    assert "lue à haute voix" in oral and "en anglais" in oral and "pas de titre" in oral
    assert "en français" in composite._consigne_du_chat(dict(etape, suivante="voix_fr"), None)


def test_executer_dit_a_chaque_etape_ce_qui_suit(composite):
    vus = []

    def lancer(etape, entree):
        vus.append((etape["brique"], etape["suivante"]))
        return "texte"

    chaine = {"phrase": "p", "etapes": [{"brique": "image_lecture", "fonction": "a"},
                                        {"brique": "chat_auto", "fonction": "b"},
                                        {"brique": "voix_en", "fonction": "c"}]}
    composite.executer(chaine, lancer, garde_budget=lambda e: None)
    assert vus == [("image_lecture", "chat_auto"), ("chat_auto", "voix_en"), ("voix_en", None)]


def son_de(secondes: float, taux: int = 16000) -> bytes:
    x = array.array("h", (int(8000 * math.sin(2 * math.pi * 220 * i / taux))
                          for i in range(int(secondes * taux))))
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taux)
        w.writeframes(x.tobytes())
    return tampon.getvalue()


class Reponse:
    def __init__(self, mots):
        self.mots = mots

    def raise_for_status(self):
        pass

    def json(self):
        return {"mots": self.mots}


class Client:
    def __init__(self, mots=None, panne=None):
        self.mots, self.panne, self.appels = mots, panne, []

    def post(self, url, **k):
        self.appels.append((url, k.get("data")))
        if self.panne:
            raise self.panne
        return Reponse(self.mots)


def mots(*triplets):
    return [{"mot": m, "debut": a, "fin": b} for m, a, b in triplets]


def test_l_ecoute_retire_la_parole_ajoutee(composite):
    son = son_de(3.0)
    client = Client(mots(("The", 0.1, 0.3), ("sea", 0.35, 0.6), ("banana", 1.0, 1.6),
                         ("is", 2.0, 2.2), ("grey.", 2.3, 2.7)))
    rendu = composite.ecouter(son, "The sea is grey.", "en", client, {})
    e = rendu.ecoute
    assert client.appels == [(composite.ROUTEUR + "/v1/audio/alignement", {"langue": "en"})]
    assert e["fait"] and e["attendus"] == 4 and e["retrouves"] == 4 and not e["ecart"]
    assert e["coupes"] == 1 and e["retires"] == ["banana"]
    assert len(rendu) < len(son), "le son nettoye n'a pas remplace l'original"


def test_une_voix_qui_s_ecarte_se_dit(composite):
    e = composite.ecouter(son_de(2.0), "The sea is grey and calm today.", "en",
                          Client(mots(("The", 0.1, 0.3), ("sky", 0.4, 0.8))), {}).ecoute
    assert e["fait"] and e["ecart"]


def test_l_ecoute_en_panne_garde_le_son(composite):
    son = son_de(1.0)
    rendu = composite.ecouter(son, "Hello.", "en", Client(panne=OSError("injoignable")), {})
    assert bytes(rendu) == son
    assert rendu.ecoute["fait"] is False and "injoignable" in rendu.ecoute["motif"]


def test_un_nombre_en_chiffres_n_est_pas_coupe(composite):
    rendu = composite.ecouter(son_de(2.0), "I see ten boats.", "en",
                              Client(mots(("I", 0.1, 0.2), ("see", 0.3, 0.5),
                                          ("10", 0.6, 1.0), ("boats.", 1.1, 1.5))), {})
    assert rendu.ecoute["coupes"] == 0


def extrait(page: str) -> str:
    debut = page.index("function phraseEcoute(e){")
    return page[debut:page.index("\n// Un verdict rendu pour un autre fichier", debut)]


def node(code: str) -> str:
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    return sortie.stdout


@pytest.fixture
def page(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    return TestClient(sandbox.app, base_url=LOCAL).get("/composite").text


def test_le_markdown_est_mis_en_forme_et_reste_echappe(page):
    html = node(extrait(page) + "\nconsole.log(miseEnForme(" + json.dumps(
        EXPOSE + "\n<script>alert(1)</script> et `code`") + "));")
    assert "<h4>English Text to Read Aloud</h4>" in html
    assert "<strong>A lighthouse</strong>" in html and "<em>rain</em>" in html
    assert "<ol><li>The sea is grey.</li></ol><ul><li>Waves hit the rocks</li></ul><hr>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<code>code</code>" in html


def test_l_ecoute_se_lit_sur_la_page(page):
    html = node(extrait(page) + "\nconsole.log(phraseEcoute(" + json.dumps(
        {"fait": True, "attendus": 12, "retrouves": 11, "coupes": 1, "retires": ["banana"],
         "ecart": False}) + "));\nconsole.log(phraseEcoute({fait: false, motif: 'lent'}));")
    assert "11 mots retrouvés sur 12" in html and "« banana »" in html
    assert "non faite (lent)" in html


def test_le_fichier_joint_se_montre(page):
    code = (extrait(page)
            + "\nconst zone = {innerHTML: ''};"
            + "\nconst document = {getElementById: () => zone};"
            + "\nconst URL = {createObjectURL: () => 'blob:x', revokeObjectURL: () => {}};"
            + "\nmontrerFichier({name: 'phare<1>.jpg', type: 'image/jpeg', size: 2048});"
            + "\nconsole.log(zone.innerHTML);"
            + "\nmontrerFichier({name: 'notes.pdf', type: 'application/pdf', size: 3145728});"
            + "\nconsole.log(zone.innerHTML);")
    html = node(code)
    assert "<img class=vignette src='blob:x'" in html
    assert "phare&lt;1&gt;.jpg — 2 ko" in html
    assert "notes.pdf — 3,0 Mo" in html
