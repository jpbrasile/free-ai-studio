"""Colab par le carnet ouvert (PLAN.md 17.4), sans Colab.

Un FAUX carnet parle le protocole de googlecolab/colab-mcp (JSON-RPC, outils
add_code_cell / run_code_cell / update_cell / delete_cell / get_cells, reponses
au format releve par le fork xynogen sur le vrai Colab) et EXECUTE vraiment les
cellules que le Studio lui envoie, dans un dossier jetable a la place de
/content. Ce qui est verifie ici : le dialogue, les cellules elles-memes, le
rapatriement des fichiers, l'arret, le delai, les refus. Ce qui ne l'est pas :
le vrai Colab -- voir PLAN.md 17.4.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "sandbox-manager"))
import colab_pont  # noqa: E402

COLAB = "https://colab.research.google.com"
FIN = "__fin_du_carnet__"


class FauxCarnet:
    """Un onglet Colab : serveur MCP, noyau Python, cellules numerotees."""

    def __init__(self, racine: Path, carte: bool = False):
        self.racine = racine
        self.carte = carte
        self.noyau: dict = {}
        self.cellules: dict[str, str] = {}
        self.ordre: list[str] = []
        self.lancees: list[str] = []
        self.muettes = 0
        self.lancees_codes: list[str] = []
        self._n = 0

    def _code(self, code: str) -> str:
        code = code.replace("/content", self.racine.as_posix())
        code = code.replace('shutil.which("nvidia-smi")', "True" if self.carte else "None")
        return code.replace('["nvidia-smi", "-L"]',
                            '[sys.executable, "-c", "print(\'GPU 0: Tesla T4 (factice)\')"]')

    def outil(self, nom: str, a: dict):
        if nom == "get_cells":
            return {"cells": [{"cell_type": "code", "id": i, "source": [self.cellules[i]]} for i in self.ordre]}
        if nom == "add_code_cell":
            self._n += 1
            ident = "c%d" % self._n
            self.cellules[ident] = a["code"]
            self.ordre.insert(min(int(a["cellIndex"]), len(self.ordre)), ident)
            return {"newCellId": ident}
        if nom == "update_cell":
            self.cellules[a["cellId"]] = a["content"]
            return {}
        if nom == "delete_cell":
            self.cellules.pop(a["cellId"], None)
            self.ordre.remove(a["cellId"])
            return {}
        if nom == "run_code_cell":
            self.lancees.append(a["cellId"])
            self.lancees_codes.append(self.cellules[a["cellId"]])
            if self.muettes:
                # L'avertissement « pas créé par Google » attend un clic : rien ne tourne.
                self.muettes -= 1
                return {"outputs": []}
            sortie = io.StringIO()
            try:
                with contextlib.redirect_stdout(sortie):
                    exec(self._code(self.cellules[a["cellId"]]), self.noyau)  # noqa: S102
            except Exception as exc:  # noqa: BLE001
                return {"outputs": [{"output_type": "error", "ename": type(exc).__name__, "evalue": str(exc)}]}
            # Le vrai Colab rend le texte en liste de lignes.
            return {"outputs": [{"output_type": "stream", "name": "stdout",
                                 "text": sortie.getvalue().splitlines(keepends=True)}]}
        raise KeyError(nom)

    def repondre(self, brut: str):
        m = json.loads(brut)
        if "id" not in m:
            return None
        if m["method"] == "initialize":
            return {"jsonrpc": "2.0", "id": m["id"], "result": {
                "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                "serverInfo": {"name": "colab-faux", "version": "0"}}}
        if m["method"] == "tools/list":
            return {"jsonrpc": "2.0", "id": m["id"], "result": {"tools": [
                {"name": n} for n in ("add_code_cell", "run_code_cell", "update_cell", "delete_cell", "get_cells")]}}
        if m["method"] == "tools/call":
            try:
                res = self.outil(m["params"]["name"], m["params"]["arguments"])
            except KeyError as exc:
                return {"jsonrpc": "2.0", "id": m["id"], "result": {
                    "isError": True, "content": [{"type": "text", "text": "outil inconnu %s" % exc}]}}
            return {"jsonrpc": "2.0", "id": m["id"], "result": {
                "content": [{"type": "text", "text": json.dumps(res)}]}}
        return {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "?"}}


class Banc:
    """Le pont servi dans sa propre boucle, comme dans le service ; le faux
    carnet a l'autre bout du fil."""

    def __init__(self, pont: colab_pont.Pont, carnet: FauxCarnet):
        self.pont = pont
        self.carnet = carnet
        self.boucle = asyncio.new_event_loop()
        self.fil = threading.Thread(target=self.boucle.run_forever, daemon=True)
        self.fil.start()
        self.file = asyncio.run_coroutine_threadsafe(self._file(), self.boucle).result()
        self.muet = False

        async def envoyer(texte: str) -> None:
            if self.muet:
                return
            rep = carnet.repondre(texte)
            if rep is not None:
                await self.file.put(json.dumps(rep))

        async def recevoir() -> str:
            m = await self.file.get()
            if m == FIN:
                raise ConnectionError("onglet ferme")
            return m

        self.service = asyncio.run_coroutine_threadsafe(pont.servir(envoyer, recevoir), self.boucle)
        fin = time.time() + 5
        while not pont.branche() and time.time() < fin:
            time.sleep(0.01)
        assert pont.branche()

    async def _file(self):
        return asyncio.Queue()

    def fermer_l_onglet(self):
        self.boucle.call_soon_threadsafe(self.file.put_nowait, FIN)
        with contextlib.suppress(Exception):
            self.service.result(5)

    def arreter(self):
        self.fermer_l_onglet()
        self.boucle.call_soon_threadsafe(self.boucle.stop)
        self.fil.join(5)


@pytest.fixture
def banc(tmp_path, monkeypatch):
    monkeypatch.setattr(colab_pont, "SUIVI_S", 0.05)
    bancs = []

    def fabriquer(carte=False):
        b = Banc(colab_pont.Pont(), FauxCarnet(tmp_path / "colab", carte=carte))
        bancs.append(b)
        return b

    yield fabriquer
    for b in bancs:
        b.arreter()


def test_le_branchement_lit_les_outils_de_colab(banc):
    b = banc()
    e = b.pont.etat()
    assert e["branche"] and not e["occupe"]
    assert "run_code_cell" in e["outils"]
    assert e["serveur"]["name"] == "colab-faux"


def test_un_travail_tourne_et_ses_fichiers_reviennent_intacts(banc, tmp_path):
    b = banc()
    # Plus grand que deux morceaux : le rapatriement doit recoller trois lectures.
    code = ("import os\n"
            "d = os.environ['FREE_AI_OUTPUT_DIR']\n"
            "open(os.path.join(d, 'clip.mp4'), 'wb').write(bytes(range(256)) * 2400)\n"
            "os.makedirs(os.path.join(d, 'sous'))\n"
            "open(os.path.join(d, 'sous', 'resume.json'), 'w').write('{\"ok\": 1}')\n"
            "print('fabrique')\n")
    etapes = []
    r = colab_pont.executer(b.pont, code, tmp_path / "sortie", 60, progres=etapes.append)
    assert r["exit_code"] == 0 and not r["timed_out"] and not r["arrete"]
    assert "fabrique" in r["stdout"]
    assert (tmp_path / "sortie" / "clip.mp4").read_bytes() == bytes(range(256)) * 2400
    assert json.loads((tmp_path / "sortie" / "sous" / "resume.json").read_text()) == {"ok": 1}
    assert sorted(p.name for p in r["fichiers"]) == ["clip.mp4", "resume.json"]
    assert etapes[0]["etape"] == "lance"
    # 614 400 octets en morceaux de 256 Kio : trois lectures du meme fichier.
    assert (256 * 2400) // colab_pont.MORCEAU + 1 == 3
    # Le carnet est rendu propre : toutes les cellules du Studio sont retirees.
    assert b.carnet.ordre == []


def test_le_travail_attend_le_clic_sur_l_avertissement_de_colab(banc, tmp_path):
    """Vu le 25/09/2026 : carnet venu de GitHub, premiere cellule sans reponse
    tant que « Exécuter quand même » n'est pas clique -> clip en echec a 55 s."""
    b = banc()
    b.carnet.muettes = 3
    etapes = []
    r = colab_pont.executer(b.pont, "print('ok')\n", tmp_path / "sortie", 60, progres=etapes.append)
    assert r["exit_code"] == 0 and "ok" in r["stdout"]
    assert [e["etape"] for e in etapes[:3]] == ["attente"] * 3
    assert b.carnet.ordre == []


def test_un_carnet_qui_ne_repond_pas_du_tout_est_aussi_attendu(banc, tmp_path, monkeypatch):
    """Vu le 26/09/2026 : deuxieme essai, pas de reponse du tout en 60 s ; le
    Studio abandonnait en disant « 5 minutes » au bout d'une."""
    b = banc()
    vrai = b.pont.outil
    silences = [1, 1]

    def outil(nom, arguments, delai=colab_pont.APPEL_S):
        if nom == "run_code_cell" and silences:
            silences.pop()
            raise colab_pont.ColabErreur("Colab n'a pas répondu à tools/call en 90 s.")
        return vrai(nom, arguments, delai)

    monkeypatch.setattr(b.pont, "outil", outil)
    r = colab_pont.executer(b.pont, "print('ok')\n", tmp_path / "sortie", 60)
    assert r["exit_code"] == 0 and silences == []


def test_sans_clic_en_5_minutes_le_studio_dit_quoi_faire(banc, tmp_path, monkeypatch):
    b = banc()
    b.carnet.muettes = 10 ** 6
    monkeypatch.setattr(colab_pont, "PRET_S", 0.2)
    with pytest.raises(colab_pont.ColabErreur) as e:
        colab_pont.executer(b.pont, "open('/tmp/jamais', 'w')\n", tmp_path / "sortie", 60)
    assert "Exécuter quand même" in str(e.value)
    assert "_free_ai_studio" not in b.carnet.noyau and b.carnet.ordre == []


def test_un_code_qui_echoue_rend_son_code_de_retour_et_son_erreur(banc, tmp_path):
    b = banc()
    r = colab_pont.executer(b.pont, "import sys\nprint('avant')\nsys.exit('mauvais code')\n",
                            tmp_path / "sortie", 60)
    assert r["exit_code"] == 1
    assert "avant" in r["stdout"] and "mauvais code" in r["stderr"]
    assert r["fichiers"] == []
    assert b.carnet.ordre == []


def test_sans_carte_le_travail_gpu_ne_part_pas_et_dit_quel_menu_ouvrir(banc, tmp_path):
    b = banc(carte=False)
    with pytest.raises(colab_pont.ColabSansCarte) as e:
        colab_pont.executer(b.pont, "open('/tmp/jamais', 'w')\n", tmp_path / "sortie", 60, gpu=True)
    assert "Modifier le type d’exécution" in str(e.value)
    assert "_free_ai_studio" not in b.carnet.noyau
    assert b.carnet.ordre == []


def test_avec_carte_la_fiche_garde_la_carte_donnee_par_colab(banc, tmp_path):
    b = banc(carte=True)
    r = colab_pont.executer(b.pont, "print('ok')\n", tmp_path / "sortie", 60, gpu=True)
    assert r["exit_code"] == 0
    assert "Tesla T4" in r["gpu"]


def test_l_arret_tue_le_calcul_dans_le_carnet(banc, tmp_path):
    b = banc()
    demande = {"n": 0}

    def arret():
        demande["n"] += 1
        return demande["n"] >= 2

    t0 = time.time()
    r = colab_pont.executer(b.pont, "import time\ntime.sleep(60)\n", tmp_path / "sortie", 600, arret=arret)
    assert r["arrete"] and r["exit_code"] != 0
    assert time.time() - t0 < 30
    _, (p, _) = b.carnet.noyau["_free_ai_studio"].popitem()
    assert p.poll() is not None
    assert b.carnet.ordre == []


def test_le_delai_tue_le_calcul_et_le_dit(banc, tmp_path):
    b = banc()
    r = colab_pont.executer(b.pont, "import time\ntime.sleep(60)\n", tmp_path / "sortie", 1)
    assert r["timed_out"] and r["exit_code"] == 124


def test_un_seul_travail_a_la_fois(banc):
    b = banc()
    with b.pont.reserver():
        with pytest.raises(colab_pont.ColabOccupe):
            b.pont.reserver()
        assert b.pont.etat()["occupe"]
    assert not b.pont.etat()["occupe"]


def test_sans_carnet_branche_rien_ne_part(tmp_path):
    pont = colab_pont.Pont()
    with pytest.raises(colab_pont.ColabAbsent) as e:
        colab_pont.executer(pont, "print(1)\n", tmp_path / "sortie", 60)
    assert "Ouvrir Colab" in str(e.value)


def test_un_onglet_ferme_en_route_leve_et_rend_le_carnet(banc, tmp_path):
    b = banc()
    b.muet = True   # l'onglet ne repond plus...
    fut = []

    def travail():
        try:
            colab_pont.executer(b.pont, "print(1)\n", tmp_path / "sortie", 60)
        except Exception as exc:  # noqa: BLE001
            fut.append(exc)

    t = threading.Thread(target=travail)
    t.start()
    time.sleep(0.2)
    b.fermer_l_onglet()   # ...puis se ferme
    t.join(10)
    assert fut and isinstance(fut[0], colab_pont.ColabErreur)
    assert not b.pont.branche()


def test_les_refus_du_branchement():
    pont = colab_pont.Pont()
    assert "origine" in pont.refus("https://exemple.com", pont.jeton)
    assert "origine" in pont.refus(None, pont.jeton)
    assert "jeton" in pont.refus(COLAB, "mauvais")
    assert "jeton" in pont.refus(COLAB, "")
    assert pont.refus(COLAB, pont.jeton) is None
    assert pont.refus("https://colab.google.com", pont.jeton) is None


def test_un_second_carnet_est_refuse_et_le_jeton_change_au_debranchement(banc):
    b = banc()
    ancien = b.pont.jeton
    assert "déjà branché" in b.pont.refus(COLAB, ancien)
    b.fermer_l_onglet()
    assert not b.pont.branche()
    assert b.pont.jeton != ancien


def test_l_adresse_du_carnet_porte_le_jeton_et_le_port_publie():
    pont = colab_pont.Pont()
    a = pont.adresse(8020)
    assert a.startswith("https://colab.research.google.com/github/jpbrasile/free-ai-studio/blob/main/"
                        "notebooks/carnet-studio-colab.ipynb#")
    assert "mcpProxyToken=%s" % pont.jeton in a and a.endswith("mcpProxyPort=8020")


def test_un_nom_de_fichier_qui_sort_du_dossier_est_refuse(tmp_path):
    with pytest.raises(colab_pont.ColabErreur):
        colab_pont.rapatrier(colab_pont.Pont(), {"n": "x", "marque": colab_pont.MARQUE},
                             [{"nom": "../evade.txt", "taille": 1, "sha256": "0"}], tmp_path / "s", 0, [])
    assert not (tmp_path / "evade.txt").exists()


def test_un_fichier_abime_en_route_est_refuse(banc, tmp_path):
    b = banc()
    d = tmp_path / "colab" / "free_ai_studio" / "tx" / "free_ai_output"
    d.mkdir(parents=True)
    (d / "a.bin").write_bytes(b"contenu")
    with pytest.raises(colab_pont.ColabErreur) as e:
        colab_pont.rapatrier(b.pont, {"n": "tx", "marque": colab_pont.MARQUE},
                             [{"nom": "a.bin", "taille": 7, "sha256": "0" * 64}], tmp_path / "s", 0, [])
    assert "abîmé" in str(e.value)


def test_une_erreur_python_dans_la_cellule_remonte_avec_son_nom():
    texte = json.dumps({"outputs": [{"output_type": "error", "ename": "MemoryError", "evalue": "RAM"}]})
    with pytest.raises(colab_pont.ColabErreur) as e:
        colab_pont.sortie_de(texte)
    assert "MemoryError" in str(e.value)


def test_la_sortie_marquee_se_lit_en_chaine_ou_en_liste():
    for texte in ("bruit\n@@FAIS@@{\"a\": 1}\n", ["bruit\n", "@@FAIS@@{\"a\": 1}\n"]):
        brut = json.dumps({"outputs": [{"output_type": "stream", "name": "stdout", "text": texte}]})
        assert json.loads(colab_pont.sortie_de(brut)) == {"a": 1}


# --- Le service : la route du branchement, l'etat, la video, le mode auto ---

@pytest.fixture
def client(sandbox):
    from fastapi.testclient import TestClient
    sandbox.colab_pont.PONT = sandbox.colab_pont.Pont()
    # Ouverte par localhost, comme la page du Studio personnel.
    return TestClient(sandbox.app, base_url="http://localhost"), sandbox


ENTETE = {"Authorization": "Bearer cle-sandbox-de-test"}


def test_l_etat_donne_l_adresse_contre_la_cle_seulement(client):
    c, sb = client
    assert c.get("/colab/etat").status_code == 401
    e = c.get("/colab/etat", headers=ENTETE).json()
    assert e["branche"] is False and e["coupe"] is None
    assert e["adresse"].endswith("mcpProxyPort=8020")
    assert sb.colab_pont.PONT.jeton in e["adresse"]


def test_en_studio_partage_pas_d_adresse_ni_de_video_colab(sandbox):
    from fastapi.testclient import TestClient
    c = TestClient(sandbox.app, base_url="http://192.168.1.20")
    e = c.get("/colab/etat", headers=ENTETE).json()
    assert e["coupe"] and "adresse" not in e
    r = c.post("/video/creer", headers=ENTETE, json={"description": "un phare", "ou": "colab", "duree": "1"})
    assert r.status_code == 403 and "une seule personne" in r.json()["detail"]


def test_la_route_refuse_un_autre_site_et_un_mauvais_jeton(client):
    c, sb = client
    jeton = sb.colab_pont.PONT.jeton
    for chemin, origine in (("/?access_token=" + jeton, "https://exemple.com"),
                            ("/?access_token=faux", COLAB),
                            ("/", COLAB)):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(chemin, headers={"origin": origine}, subprotocols=["mcp"]) as ws:
                ws.receive_text()
    assert not sb.colab_pont.PONT.branche()
    assert sb.colab_pont.PONT.dernier_refus


def test_la_route_branche_un_vrai_dialogue_mcp(client):
    c, sb = client
    jeton = sb.colab_pont.PONT.jeton
    with c.websocket_connect("/?access_token=" + jeton, headers={"origin": COLAB},
                             subprotocols=["mcp"]) as ws:
        m = ws.receive_json()
        assert m["method"] == "initialize"
        ws.send_json({"jsonrpc": "2.0", "id": m["id"], "result": {"serverInfo": {"name": "colab"}}})
        assert ws.receive_json()["method"] == "notifications/initialized"
        m = ws.receive_json()
        assert m["method"] == "tools/list"
        ws.send_json({"jsonrpc": "2.0", "id": m["id"], "result": {"tools": [{"name": "run_code_cell"}]}})
        fin = time.time() + 5
        while not c.get("/colab/etat", headers=ENTETE).json()["branche"] and time.time() < fin:
            time.sleep(0.02)
        e = c.get("/colab/etat", headers=ENTETE).json()
        assert e["branche"] and e["outils"] == ["run_code_cell"]
        # Un ping de Colab recoit sa reponse.
        ws.send_json({"jsonrpc": "2.0", "id": 99, "method": "ping"})
        assert ws.receive_json() == {"jsonrpc": "2.0", "id": 99, "result": {}}
    fin = time.time() + 5
    while sb.colab_pont.PONT.branche() and time.time() < fin:
        time.sleep(0.02)
    assert not sb.colab_pont.PONT.branche()


def test_une_video_sur_colab_sans_carnet_dit_quoi_faire(client):
    c, sb = client
    r = c.post("/video/creer", headers=ENTETE, json={"description": "un phare", "ou": "colab", "duree": "1"})
    assert r.status_code == 503
    assert "Ouvrir Colab" in r.json()["detail"]


def test_le_mode_auto_sans_carnet_garde_le_carnet_a_importer(sandbox, monkeypatch):
    sandbox.colab_pont.PONT = sandbox.colab_pont.Pont()
    jid = "colabauto0001"
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    attempts: list = []
    assert sandbox._essayer_colab(jid, "print(1)", False, attempts) is False
    assert attempts == [{"provider": "colab", "result": "not_connected"}]


def test_le_mode_auto_avec_carnet_y_fait_le_travail(sandbox, monkeypatch, tmp_path):
    jid = "colabauto0002"
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    vu = {}

    def faux_executer(pont, code, sortie, delai, gpu=False, arret=None, progres=None, liberer=False):
        vu.update(code=code, gpu=gpu, delai=delai, liberer=liberer)
        sortie.mkdir(parents=True, exist_ok=True)
        f = sortie / "r.txt"
        f.write_text("resultat")
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False, "arrete": False,
                "fichiers": [f], "gpu": "Tesla T4"}

    monkeypatch.setattr(sandbox.colab_pont.PONT, "branche", lambda: True)
    monkeypatch.setattr(sandbox.colab_pont, "executer", faux_executer)
    attempts: list = []
    assert sandbox._essayer_colab(jid, "print(1)", True, attempts) is True
    job = sandbox.read_job(jid)
    assert job["status"] == "succeeded" and job["provider_effective"] == "colab"
    assert job["remote_gpu"] == "Tesla T4"
    assert [(a["name"], a["source"]) for a in job["artifacts"]] == [("r.txt", "colab")]
    assert vu["gpu"] is True and vu["code"] == "print(1)"
    # Un travail sur carte rend la machine a la fin (26/09/2026).
    assert vu["liberer"] is True


def test_la_machine_est_rendue_a_colab_apres_le_travail(banc, tmp_path):
    b = banc(carte=True)
    r = colab_pont.executer(b.pont, "print('ok')\n", tmp_path / "sortie", 60, gpu=True, liberer=True)
    assert r["exit_code"] == 0
    # Derniere cellule lancee : la liberation (le faux carnet n'a pas google.colab,
    # l'erreur est avalee comme la reponse manquante du vrai), puis rien ne reste.
    assert "runtime.unassign()" in b.carnet.lancees_codes[-1]
    assert b.carnet.ordre == []
    colab_pont.executer(b.pont, "print('ok')\n", tmp_path / "sortie2", 60, gpu=True)
    assert "runtime.unassign()" not in b.carnet.lancees_codes[-1]


def test_l_arret_d_un_travail_colab_dit_ce_qu_il_fait(client, monkeypatch):
    c, sb = client
    jid = "colabarret001"
    sb.write_job(jid, {"id": jid, "status": "running", "provider_effective": "colab", "artifacts": []})
    monkeypatch.setattr(sb.colab_pont.PONT, "branche", lambda: True)
    r = c.post("/jobs/%s/arreter" % jid, headers=ENTETE).json()
    assert r["status"] == "cancelled" and r["arretees"] == 1
    assert "carnet Colab" in r["detail"]
    assert sb.read_job(jid)["arret_demande"] is True


def test_la_page_video_propose_colab_et_sa_boite(sandbox):
    page = sandbox.video.PAGE_HTML
    assert 'value="colab"' in page
    assert 'id="colabBoite"' in page and "/colab/etat" in page
    assert "Connect to a local Colab MCP server" in page
    # On ne << loue >> rien chez Colab : le bouton de la boite carte-prise le dit.
    assert "Envoyer à votre carnet Colab" in page



def test_le_carnet_ouvert_est_deja_regle_sur_la_carte_t4():
    """« trop de réglage colab manuel » (25/09/2026) : le carnet ouvert est
    celui du depot, dont les metadonnees demandent la T4."""
    assert colab_pont.CARNET.endswith("/notebooks/carnet-studio-colab.ipynb")
    assert colab_pont.CARNET.startswith(
        "https://colab.research.google.com/github/jpbrasile/free-ai-studio/blob/main/")
    carnet = json.loads((RACINE / "notebooks" / "carnet-studio-colab.ipynb").read_text(encoding="utf-8"))
    assert carnet["metadata"]["accelerator"] == "GPU"
    assert carnet["metadata"]["colab"]["gpuType"] == "T4"
    assert colab_pont.PONT.adresse(8020).startswith(colab_pont.CARNET + "#mcpProxyToken=")
    # La page ne demande plus de regler la carte a la main.
    page = (RACINE / "sandbox-manager" / "video.py").read_text(encoding="utf-8")
    assert "Modifier le type d’exécution » › « GPU T4 », puis « Enregistrer »" not in page


def test_le_jeton_du_carnet_ne_s_ecrit_pas_dans_le_journal(sandbox):
    """Vu le 25/09/2026 : uvicorn ecrivait « WebSocket /?access_token=... » en clair."""
    import logging
    filtre = sandbox.MasquerJeton()
    for nom, msg, args in [
        ("uvicorn.error", '%s - "WebSocket %s" [accepted]', ("172.25.0.1:1", "/?access_token=SECRET-1")),
        ("uvicorn.access", '%s - "%s %s HTTP/%s" %d', ("172.25.0.1:1", "GET", "/x?a=1&access_token=SECRET-2", "1.1", 200)),
    ]:
        rec = logging.LogRecord(nom, logging.INFO, __file__, 1, msg, args, None)
        assert filtre.filter(rec)
        assert "SECRET" not in rec.getMessage() and "access_token=***" in rec.getMessage()
    assert any(isinstance(f, sandbox.MasquerJeton) for f in logging.getLogger("uvicorn.error").filters)
    assert any(isinstance(f, sandbox.MasquerJeton) for f in logging.getLogger("uvicorn.access").filters)


def test_seul_colab_charge_le_modele_en_mode_econome(client, monkeypatch):
    """Vu le 25/09/2026 : le clip Colab tue (-9) a 98 % du chargement, faute de
    memoire vive (12,7 Go). Le lecteur de texte (11,4 Go) va alors droit sur la carte."""
    c, sb = client
    demandes = []
    vrai = sb.video.construire_script
    monkeypatch.setattr(sb.video, "construire_script", lambda d: demandes.append(dict(d)) or vrai(d))
    monkeypatch.setattr(sb, "run_video", lambda *a, **k: None)
    monkeypatch.setattr(sb.colab_pont.PONT, "branche", lambda: True)
    monkeypatch.setattr(sb, "WORKER_GPU_URL", "")
    monkeypatch.setattr(sb, "modal_configured", lambda: True)
    for ou in ("colab", "modal"):
        r = c.post("/video/creer", headers=ENTETE, json={"description": "un phare", "ou": ou, "duree": "1"})
        assert r.status_code == 200, r.text
    assert [d.get("peu_de_ram", False) for d in demandes] == [True, False]
    script = vrai(demandes[0])
    assert 'device_map="cuda"' in script and "prompt_embeds=lectures[0]" in script
    compile(script, "clip.py", "exec")


def test_un_clip_colab_tue_dit_pourquoi_et_propose_kaggle(client):
    c, sb = client
    jid = "colabtue00001"
    sb.write_job(jid, {"id": jid, "status": "failed", "provider_effective": "colab", "exit_code": -9,
                       "stderr": "Loading checkpoint shards:  98%", "artifacts": [], "video": {}})
    d = c.get("/video/jobs/" + jid, headers=ENTETE).json()
    assert "mémoire vive" in d["message"] and "Kaggle" in d["message"]
    # Ailleurs, le meme arret net recoit une phrase, sans parler de Colab.
    sb.write_job(jid, {"id": jid, "status": "failed", "provider_effective": "modal", "exit_code": -9,
                       "stderr": "", "artifacts": [], "video": {}})
    d = c.get("/video/jobs/" + jid, headers=ENTETE).json()
    assert "mémoire vive" in d["message"] and "Colab" not in d["message"]


def test_la_page_previent_avant_un_clip_colab():
    page = (RACINE / "sandbox-manager" / "video.py").read_text(encoding="utf-8")
    assert "Colab gratuit a peu de mémoire vive (12,7 Go)" in page
