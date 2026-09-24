"""Enchaîner, suivi pas à pas et arrêtable.

24/09/2026, le propriétaire : « enchaîner : pas de visualisation
intermédiaire, ni d'abort button », puis « il faut les y mettre dans l'ui de
pilotage ». `/composite/lancer` rendait tout à la fin, d'un bloc, et rien ne
l'arrêtait. Une COURSE tourne maintenant dans un fil : la page lit son
avancement, montre chaque sortie dès qu'elle existe, et peut l'arrêter.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

LOCAL = "http://127.0.0.1:8020"
CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
PNG = b"\x89PNG\r\n\x1a\n" + b"phare"


def test_executer_dit_chaque_etape_et_sa_sortie(sandbox):
    c = sandbox.composite
    vus = []
    chaine = {"phrase": "p", "etapes": [{"brique": "image_fabrication", "fonction": "Image"},
                                        {"brique": "image_lecture", "fonction": "Lecture"}]}
    trace = c.executer(chaine, lambda e, _x: PNG if e["brique"] == "image_fabrication" else "Un phare.",
                       garde_budget=lambda _e: None,
                       suivi=lambda r, s, _rendu, sortie: vus.append((r, s, type(sortie).__name__)))
    assert trace["resultat"] == "rendu"
    assert vus == [(0, "en_cours", "NoneType"), (0, "rendu", "bytes"),
                   (1, "en_cours", "NoneType"), (1, "rendu", "str")]


def test_un_arret_ne_lance_plus_aucune_etape(sandbox):
    c = sandbox.composite
    arret = threading.Event()
    lances = []

    def lancer(e, _x):
        lances.append(e["brique"])
        arret.set()
        return "texte"

    trace = c.executer({"phrase": "p", "etapes": [{"brique": "chat_auto", "fonction": "Chat"},
                                                  {"brique": "voix_fr", "fonction": "Voix"}]},
                       lancer, garde_budget=lambda _e: None, arret=arret)
    assert lances == ["chat_auto"]
    assert trace["motif"] == c.ARRETE_PAR_LE_CLIENT
    assert "avant « Voix »" in trace["phrase"]
    assert trace["etapes"][0]["resultat"] == "rendu", "ce qui est fait reste"


def test_un_travail_en_cours_est_arrete_pour_de_bon(sandbox, monkeypatch):
    """Pas seulement « on cesse d'attendre » : la route du bouton des pages est
    appelée, et sa phrase (Modal terminé, Kaggle sans annulation) est reprise."""
    c = sandbox.composite
    vues = []

    def transport(requete):
        vues.append((requete.method, requete.url.path))
        if requete.url.path.endswith("/creer"):
            return httpx.Response(200, json={"id": "j1"})
        if requete.url.path.endswith("/arreter"):
            return httpx.Response(200, json={"detail": "La machine Modal est terminée."})
        return httpx.Response(200, json={"status": "running"})

    vrai = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kw: vrai(transport=httpx.MockTransport(transport), **kw))
    monkeypatch.setattr(c, "_cle_du_sandbox", lambda: "k")
    arret = threading.Event()
    arret.set()
    etape = dict(c.chaine_depuis_briques(["video_maison"])["etapes"][0],
                 demande="un phare", arret=arret)
    with pytest.raises(c.CompositeRefuse) as refus:
        c.lancer_un_travail(etape, "")
    assert refus.value.motif == c.ARRETE_PAR_LE_CLIENT
    assert "La machine Modal est terminée." in refus.value.phrase
    assert ("POST", "/jobs/j1/arreter") in vues


def attendre(client, cid, condition):
    for _ in range(500):
        s = client.get("/composite/courses/" + cid, headers=CLE).json()
        if condition(s):
            return s
        time.sleep(0.01)
    raise AssertionError(s)


def test_la_course_montre_chaque_sortie_des_qu_elle_existe(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur",
                        lambda e, _x: PNG if e["brique"] == "image_fabrication" else "Un phare la nuit.")
    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/composite/demarrer", headers=CLE,
                    data={"phrase": "p", "briques": "image_fabrication,image_lecture"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    s = attendre(client, cid, lambda s: s["etat"] != "en_cours")
    assert s["etat"] == "rendu", s
    assert [e["statut"] for e in s["etapes"]] == ["rendu", "rendu"]
    assert s["etapes"][0]["type"] == "image/png"
    assert s["etapes"][1]["texte"] == "Un phare la nuit."
    f = client.get("/composite/courses/%s/etapes/0" % cid, headers=CLE)
    assert f.content == PNG and f.headers["content-type"] == "image/png"
    assert client.get("/composite/courses/%s/etapes/1" % cid, headers=CLE).status_code == 404
    assert s["resultat"]["texte"] == "Un phare la nuit.", "le resultat final, comme /lancer"


def test_arreter_depuis_la_page(sandbox, monkeypatch):
    continuer = threading.Event()

    def lancer(_e, _x):
        continuer.wait(5)
        return "texte"

    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur", lancer)
    client = TestClient(sandbox.app, base_url=LOCAL)
    cid = client.post("/composite/demarrer", headers=CLE,
                      data={"phrase": "p", "briques": "chat_auto,voix_fr"}).json()["id"]
    attendre(client, cid, lambda s: s["etapes"][0]["statut"] == "en_cours")
    a = client.post("/composite/courses/%s/arreter" % cid, headers=CLE).json()
    assert "Aucune étape de plus ne part" in a["detail"]
    continuer.set()
    s = attendre(client, cid, lambda s: s["etat"] != "en_cours")
    assert s["etat"] == "arrete" and s["arret_demande"]
    assert [e["statut"] for e in s["etapes"]] == ["rendu", "refus"]
    assert "avant « " in s["erreur"]["detail"]
    fini = client.post("/composite/courses/%s/arreter" % cid, headers=CLE).json()
    assert fini["detail"].startswith("Cette chaîne est déjà finie")
    assert client.get("/composite/courses/inconnue", headers=CLE).status_code == 404
    assert client.get("/composite/courses/%s" % cid).status_code == 401


def test_la_page_suit_les_etapes_sans_tout_redessiner(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = TestClient(sandbox.app, base_url=LOCAL).get("/composite").text
    assert "<button id=arreter hidden>" in page and "/composite/demarrer" in page
    debut = page.index("function phraseEcoute(e){")
    fin = page.index("\nfunction typeDuFichier", debut)
    pas_debut = page.index("const STATUTS = {")
    pas_fin = page.index('document.getElementById("arreter").onclick', pas_debut)
    etat = {"etapes": [{"fonction": "Image", "statut": "rendu", "texte": "Un <b>phare</b>."},
                       {"fonction": "Lecture", "statut": "en_cours"}]}
    code = (page[debut:fin] + page[pas_debut:pas_fin]
            + "\nconst CLE = 'k';"
            + "\nconst lignes = [{}, {}];"
            + "\nconst document = {getElementById: () => ({children: lignes})};"
            + "\n(async () => { const vus = {};"
            + "\nawait montrerPas('c', " + json.dumps(etat) + ", vus);"
            + "\nconsole.log(lignes[0].className, '|', lignes[0].innerHTML);"
            + "\nconsole.log(lignes[1].className, '|', lignes[1].innerHTML);"
            + "\nlignes[0].innerHTML = 'intact';"
            + "\nawait montrerPas('c', " + json.dumps(etat) + ", vus);"
            + "\nconsole.log(lignes[0].innerHTML); })();")
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    premiere, seconde, rejouee = sortie.stdout.strip().splitlines()
    assert premiere.startswith("rendu |") and "<strong>Image</strong>" in premiere
    assert "fait" in premiere and "&lt;b&gt;phare&lt;/b&gt;" in premiere
    assert seconde.startswith("en_cours |") and "en cours" in seconde
    assert rejouee == "intact", "une ligne dont le statut n'a pas change n'est pas redessinee"


# --- D'un trait ou pas a pas (24/09/2026) --------------------------------------
# « on devrait pouvoir choisir pour un flow one shot ou step by step ».


def test_la_pause_passe_avant_chaque_etape_suivante_et_sa_consigne_part(sandbox):
    c = sandbox.composite
    pauses, demandes = [], []

    def pause(rang, etape):
        pauses.append((rang, etape["fonction"]))
        return "Lis seulement la premiere phrase."

    def lancer(e, _x):
        demandes.append(e["demande"])
        return "texte"

    trace = c.executer({"phrase": "p", "etapes": [{"brique": "chat_auto", "fonction": "Chat"},
                                                  {"brique": "voix_fr", "fonction": "Voix"}]},
                       lancer, garde_budget=lambda _e: None, pause=pause)
    assert trace["resultat"] == "rendu"
    assert pauses == [(1, "Voix")], "pas de pause avant la premiere : Lancer vaut feu vert"
    assert demandes == ["p", "Lis seulement la premiere phrase."]


def _course_pas_a_pas(sandbox, monkeypatch):
    demandes = []

    def lancer(e, _x):
        demandes.append(e["demande"])
        return "texte"

    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur", lancer)
    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/composite/demarrer", headers=CLE,
                    data={"phrase": "p", "briques": "chat_auto,voix_fr", "pas_a_pas": "1"})
    assert r.status_code == 200, r.text
    return client, r.json()["id"], demandes


def test_pas_a_pas_attend_le_feu_vert_et_prend_la_consigne_retouchee(sandbox, monkeypatch):
    client, cid, demandes = _course_pas_a_pas(sandbox, monkeypatch)
    s = attendre(client, cid, lambda s: s["pause"])
    assert s["pas_a_pas"] is True and s["etat"] == "en_cours"
    assert s["pause"] == {"avant": 1, "fonction": s["etapes"][1]["fonction"], "consigne": "p"}
    assert [e["statut"] for e in s["etapes"]] == ["rendu", "pause"]
    time.sleep(0.3)
    assert demandes == ["p"], "l'etape suivante est partie sans feu vert"
    r = client.post("/composite/courses/%s/continuer" % cid, headers=CLE,
                    data={"consigne": "Lis-le lentement."})
    assert r.status_code == 200 and "part" in r.json()["detail"]
    s = attendre(client, cid, lambda s: s["etat"] != "en_cours")
    assert s["etat"] == "rendu" and s["pause"] is None
    assert demandes == ["p", "Lis-le lentement."]
    fini = client.post("/composite/courses/%s/continuer" % cid, headers=CLE)
    assert fini.status_code == 409


def test_d_un_trait_ne_s_arrete_jamais_en_route(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur", lambda _e, _x: "texte")
    client = TestClient(sandbox.app, base_url=LOCAL)
    cid = client.post("/composite/demarrer", headers=CLE,
                      data={"phrase": "p", "briques": "chat_auto,voix_fr"}).json()["id"]
    s = attendre(client, cid, lambda s: s["etat"] != "en_cours")
    assert s["etat"] == "rendu" and s["pas_a_pas"] is False and s["pause"] is None


def test_arreter_pendant_la_pause(sandbox, monkeypatch):
    client, cid, demandes = _course_pas_a_pas(sandbox, monkeypatch)
    attendre(client, cid, lambda s: s["pause"])
    client.post("/composite/courses/%s/arreter" % cid, headers=CLE)
    s = attendre(client, cid, lambda s: s["etat"] != "en_cours")
    assert s["etat"] == "arrete" and demandes == ["p"]
    assert [e["statut"] for e in s["etapes"]] == ["rendu", "refus"]


def test_une_pause_oubliee_finit_par_s_arreter_et_le_dit(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "PAUSE_MAX_S", 0)
    client, cid, demandes = _course_pas_a_pas(sandbox, monkeypatch)
    s = attendre(client, cid, lambda s: s["etat"] != "en_cours")
    assert s["etat"] == "arrete" and demandes == ["p"]
    assert "En pause depuis plus de" in s["erreur"]["detail"]


def test_la_page_propose_les_deux_modes_et_montre_la_pause(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = TestClient(sandbox.app, base_url=LOCAL).get("/composite").text
    assert "value=trait checked" in page and "value=pas>" in page
    assert 'corps.append("pas_a_pas", "1")' in page
    debut = page.index("function montrerPause(s, vue){")
    fin = page.index('\ndocument.getElementById("arreter").onclick', debut)
    pause = {"pause": {"avant": 1, "fonction": "Voix", "consigne": "Lis <vite>"}}
    code = ("function echapper(s){ return String(s).replace(/</g, '&lt;').replace(/>/g, '&gt;'); }"
            + "\nconst zone = {innerHTML: ''}; const bouton = {};"
            + "\nconst document = {getElementById: id => id === 'pause' ? zone : bouton};"
            + "\n" + page[debut:fin]
            + "\nconst vue = {};"
            + "\nmontrerPause(" + json.dumps(pause) + ", vue); console.log(zone.innerHTML);"
            + "\nconsole.log(typeof bouton.onclick);"
            + "\nzone.innerHTML = 'intact'; montrerPause(" + json.dumps(pause) + ", vue);"
            + "\nconsole.log(zone.innerHTML);"
            + "\nmontrerPause({pause: null}, vue); console.log('[' + zone.innerHTML + ']');")
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    bloc, clic, rejoue, vide = sortie.stdout.strip().splitlines()
    assert "« Voix »" in bloc and "Lis &lt;vite&gt;</textarea>" in bloc and "Continuer" in bloc
    assert clic == "function"
    assert rejoue == "intact", "une consigne en cours de frappe serait effacee"
    assert vide == "[]"
