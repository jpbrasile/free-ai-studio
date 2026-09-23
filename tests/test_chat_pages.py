"""Le chat connaît les pages du Studio, et la chaîne n'en est pas polluée.

Friction du 23/09/2026 : « on ne peut pas demander une chaîne depuis le chat ».
Le chat ne lance toujours rien : il donne le lien, et /composite?phrase= pose la
demande dans la case sans l'envoyer. Les appels internes de la chaîne passent
X-Studio-Interne et ne reçoivent pas la consigne, qui fausserait leur lecture.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-interne-de-test"}


class Espion:
    def __init__(self):
        self.charges = []

    async def __call__(self, client, name, payload):
        self.charges.append(payload)
        requete = httpx.Request("POST", f"https://{name}.invalid/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
                              request=requete)


def envoyer(routeur, monkeypatch, messages, entetes=None):
    espion = Espion()
    monkeypatch.setattr(routeur, "open_upstream", espion)
    r = TestClient(routeur.app).post("/v1/chat/completions", headers={**CLE, **(entetes or {})},
                                     json={"model": "free-ai-auto", "stream": False, "messages": messages})
    assert r.status_code == 200, r.text
    return espion.charges[0]["messages"]


def test_le_chat_recoit_les_pages_du_studio(routeur, monkeypatch):
    messages = envoyer(routeur, monkeypatch, [{"role": "user", "content": "résume ce PDF puis lis-le"}])
    assert messages[0]["role"] == "system"
    assert "http://localhost:8020/composite?phrase=" in messages[0]["content"]
    assert "http://localhost:8020/video" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "résume ce PDF puis lis-le"}


def test_la_consigne_de_la_personne_est_gardee(routeur, monkeypatch):
    messages = envoyer(routeur, monkeypatch, [{"role": "system", "content": "Réponds en vers."},
                                              {"role": "user", "content": "Bonjour"}])
    assert [m["role"] for m in messages] == ["system", "user"], "deux messages systeme"
    assert messages[0]["content"].startswith(routeur.CONSIGNE_STUDIO)
    assert messages[0]["content"].endswith("Réponds en vers.")


def test_un_appel_interne_n_a_pas_la_consigne(routeur, monkeypatch):
    envoye = [{"role": "user", "content": "Découpe cette phrase en étapes."}]
    assert envoyer(routeur, monkeypatch, envoye, {"X-Studio-Interne": "1"}) == envoye


def test_la_chaine_se_dit_interne_en_lisant_la_phrase(sandbox, monkeypatch):
    composite = sandbox.composite
    vus = []

    class FauxClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None, **k):
            vus.append(headers or {})
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]},
                                  request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", FauxClient)
    monkeypatch.setattr(composite, "_cle_du_routeur", lambda: "x")
    try:
        composite.appeler_le_modele("consigne")
    except Exception:  # noqa: BLE001 -- seul l'en-tete envoye compte ici
        pass
    assert vus and vus[0].get("X-Studio-Interne") == "1"
    assert "**ENTETE_INTERNE}" in open(composite.__file__, encoding="utf-8").read().split(
        "def appeler_le_modele")[1], "les etapes de la chaine appellent le chat sans se dire internes"


def test_le_lien_pose_la_phrase_sans_rien_lancer(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = TestClient(sandbox.app, base_url="http://127.0.0.1:8020").get("/composite").text
    debut = page.index("try {\n  const venue")
    fin = page.index("} catch (e) {}", debut) + len("} catch (e) {}")
    code = ("const champs = {phrase: {value: ''}, voir: {focus(){ this.pris = true; }}};\n"
            "const document = {getElementById: id => champs[id]};\n"
            "const location = {search: '?phrase=' + encodeURIComponent('résume ce PDF, puis lis-le')};\n"
            + page[debut:fin]
            + "\nconsole.log(JSON.stringify({phrase: champs.phrase.value, pris: !!champs.voir.pris}));\n")
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    assert json.loads(sortie.stdout) == {"phrase": "résume ce PDF, puis lis-le", "pris": True}
    bloc = page[debut:fin]
    assert "fetch(" not in bloc and ".click()" not in bloc, "le lien lance quelque chose sans clic"
