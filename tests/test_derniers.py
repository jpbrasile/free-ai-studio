"""Une page rechargee retrouve le travail qu'elle suivait.

Friction du 23/09/2026 (docs/FRICTIONS.md) : un clip loue chez Modal a
<< disparu >> au rechargement de /video, alors qu'il tournait encore, facture.
Ces tests jugent les deux moities : la liste lue dans les fiches, et le script
de la page qui reprend le suivi tout seul.
"""
from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import RACINE

sys.path.insert(0, str(RACINE / "sandbox-manager"))
derniers = importlib.import_module("derniers")

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"


def fiche(dossier, jid, **champs):
    (dossier / jid).mkdir(parents=True, exist_ok=True)
    job = {"id": jid, "status": "succeeded", "created_at": 1000.0, "provider": "modal"}
    job.update(champs)
    (dossier / jid / "job.json").write_text(json.dumps(job), encoding="utf-8")


@pytest.fixture
def jobs(tmp_path):
    fiche(tmp_path, "v1", created_at=1000.0, video={"description": "un phare"})
    fiche(tmp_path, "v2", created_at=2000.0, status="running", provider_effective="modal",
          video={"description": "the cat wakes up", "maison": False})
    fiche(tmp_path, "v3", created_at=1500.0, provider="maison",
          video={"description": "x " * 80, "maison": True})
    fiche(tmp_path, "c1", created_at=3000.0, chanson={"secondes_max": 60})
    fiche(tmp_path, "d1", created_at=3100.0, provider="kaggle", dialogue={},
          dialogue_repliques=["[S1]Bonjour à vous", "[S2]Salut"])
    fiche(tmp_path, "autre", created_at=4000.0)            # un bac a sable
    (tmp_path / "casse").mkdir()
    (tmp_path / "casse" / "job.json").write_text("{pas du json", encoding="utf-8")
    return tmp_path


def test_la_liste_ne_garde_que_la_page_demandee_la_plus_recente_d_abord(jobs):
    liste = derniers.lister(jobs, "video")
    assert [t["id"] for t in liste] == ["v2", "v3", "v1"]


def test_un_travail_en_cours_est_marque_et_le_loue_est_dit(jobs):
    v2, v3, v1 = derniers.lister(jobs, "video")
    assert v2["en_cours"] is True and v2["loue"] is True
    assert v3["en_cours"] is False and v3["loue"] is False
    assert v2["libelle"] == "the cat wakes up"
    assert len(v3["libelle"]) <= 70 and v3["libelle"].endswith("…")


def test_chanson_et_dialogue_ont_un_libelle_reconnaissable(jobs):
    assert derniers.lister(jobs, "chanson")[0]["libelle"] == "chanson de 60 s au plus"
    d = derniers.lister(jobs, "dialogue")[0]
    assert d["libelle"] == "Bonjour à vous"
    assert d["loue"] is False                      # Kaggle ne se paie pas


def test_la_liste_est_bornee(tmp_path):
    for i in range(20):
        fiche(tmp_path, "v%02d" % i, created_at=float(i), video={"description": str(i)})
    assert len(derniers.lister(tmp_path, "video")) == derniers.NOMBRE


def test_un_usage_inconnu_est_refuse(tmp_path):
    with pytest.raises(ValueError):
        derniers.lister(tmp_path, "bac_a_sable")


@pytest.mark.parametrize("usage", derniers.USAGES)
def test_la_route_rend_la_liste_et_demande_la_cle(sandbox, monkeypatch, jobs, usage):
    monkeypatch.setattr(sandbox, "JOBS", jobs)
    client = TestClient(sandbox.app, base_url=LOCAL)
    assert client.get("/%s/derniers" % usage).status_code == 401
    r = client.get("/%s/derniers" % usage, headers=CLE)
    assert r.status_code == 200
    assert r.json() == derniers.lister(jobs, usage)


@pytest.mark.parametrize("usage", derniers.USAGES)
def test_chaque_page_porte_la_liste_APRES_son_propre_script(sandbox, usage):
    page = TestClient(sandbox.app, base_url=LOCAL).get("/" + usage, headers=CLE).text
    assert 'id="derniers"' in page
    assert 'const USAGE = "%s";' % usage in page
    # Le script ajoute appelle suivre() et lit minuteur : ils doivent exister avant.
    assert page.index("function suivre(") < page.index('id="derniers"')
    assert "let minuteur" in page
    # Les formateurs restent poses une seule fois, dans le premier script.
    assert page.count("function moFr(") == 1


def _script_injecte(usage: str) -> str:
    bloc = derniers.dans_la_page('<body><button id="lancer"></button></body>', usage)
    return re.search(r"<script>(.*)</script>", bloc, re.S).group(1)


def _jouer(usage: str, liste: list, tmp_path) -> dict:
    """Le script de la page, joue dans node contre un faux document."""
    if not shutil.which("node"):
        pytest.skip("node absent")
    faux = """
const vus = {suivis: [], etat: "", lancer: false, visible: false};
let minuteur = null;
const CLE = "x";
// Le rafraichissement toutes les 30 s garderait node en vie pour toujours.
const setInterval = () => 0;
function suivre(id){ vus.suivis.push(id); }
const elements = {};
function el(id){
  if(!elements[id]) elements[id] = {id, hidden: true, disabled: false, textContent: "",
    innerHTML: "", querySelectorAll: () => [], dataset: {}};
  return elements[id];
}
const document = {getElementById: el};
const fetch = (url) => Promise.resolve({ok: true, json: () => Promise.resolve(LISTE)});
const LISTE = %s;
""" % json.dumps(liste)
    fin = """
setTimeout(() => {
  vus.etat = el("etat").textContent; vus.lancer = el("lancer").disabled;
  vus.visible = !el("derniers").hidden; vus.html = el("derniers-liste").innerHTML;
  console.log(JSON.stringify(vus));
}, 20);
"""
    fichier = tmp_path / "derniers.js"
    fichier.write_text(faux + _script_injecte(usage) + fin, encoding="utf-8")
    fait = subprocess.run(["node", str(fichier)], capture_output=True, text=True,
                          encoding="utf-8", timeout=20)
    assert fait.returncode == 0, fait.stderr
    return json.loads(fait.stdout)


def test_la_page_rechargee_REPREND_le_travail_en_cours_sans_clic(tmp_path, jobs):
    vus = _jouer("video", derniers.lister(jobs, "video"), tmp_path)
    assert vus["suivis"] == ["v2"]
    assert vus["lancer"] is True                   # pas de second clip par megarde
    assert "Suivi repris" in vus["etat"]
    assert vus["visible"] is True
    assert "the cat wakes up" in vus["html"] and "(loué)" in vus["html"]


def test_rien_en_cours_rien_n_est_relance(tmp_path, jobs):
    vus = _jouer("chanson", derniers.lister(jobs, "chanson"), tmp_path)
    assert vus["suivis"] == []
    assert vus["visible"] is True


def test_aucun_travail_la_liste_reste_cachee(tmp_path):
    vus = _jouer("dialogue", [], tmp_path)
    assert vus["suivis"] == [] and vus["visible"] is False


def test_un_libelle_ne_redevient_jamais_du_code(tmp_path):
    piege = [{"id": "p1", "status": "succeeded", "en_cours": False, "created_at": 1.0,
              "loue": False, "libelle": "<img src=x onerror=alert(1)>"}]
    vus = _jouer("video", piege, tmp_path)
    assert "<img" not in vus["html"] and "&lt;img" in vus["html"]


# --- Telecharger et supprimer (demande du proprietaire, 23/09) ---------------

def _avec_fichier(sandbox, jobs, jid, usage, nom):
    """Un travail fini avec un vrai artefact, range comme add_artifact le range."""
    art = jobs.parent / ("art-" + jobs.name)
    art.mkdir(exist_ok=True)
    (art / ("a1--" + nom)).write_bytes(b"son")
    (art / "a1.json").write_text("{}", encoding="utf-8")
    fiche(jobs, jid, **{usage: {}, "artifacts": [
        {"id": "a1", "name": nom, "path": "a1--" + nom}]})
    return art


def test_un_travail_fini_porte_son_lien_de_telechargement(sandbox, monkeypatch, jobs):
    art = _avec_fichier(sandbox, jobs, "f1", "video", "video.mp4")
    monkeypatch.setattr(sandbox, "JOBS", jobs)
    monkeypatch.setattr(sandbox, "ART", art)
    liste = TestClient(sandbox.app, base_url=LOCAL).get("/video/derniers", headers=CLE).json()
    f1 = next(t for t in liste if t["id"] == "f1")
    assert f1["telecharger"].startswith("/video/jobs/f1/fichier?cle=")
    assert f1["telecharger"].endswith("&telecharger=1&nom=video.mp4")
    # En cours ou sans fichier : pas de lien, plutot qu'un lien vers rien.
    assert next(t for t in liste if t["id"] == "v2")["telecharger"] == ""
    assert next(t for t in liste if t["id"] == "v1")["telecharger"] == ""


def test_supprimer_efface_la_fiche_ET_les_fichiers(sandbox, monkeypatch, jobs):
    art = _avec_fichier(sandbox, jobs, "f1", "chanson", "chanson.flac")
    monkeypatch.setattr(sandbox, "JOBS", jobs)
    monkeypatch.setattr(sandbox, "ART", art)
    client = TestClient(sandbox.app, base_url=LOCAL)
    assert client.delete("/chanson/jobs/f1").status_code == 401
    r = client.delete("/chanson/jobs/f1", headers=CLE)
    assert r.status_code == 200 and r.json()["arret"] == ""
    assert not (jobs / "f1").exists()
    assert list(art.iterdir()) == []
    assert "f1" not in [t["id"] for t in client.get("/chanson/derniers", headers=CLE).json()]


def test_une_page_n_efface_pas_le_travail_d_une_autre(sandbox, monkeypatch, jobs):
    monkeypatch.setattr(sandbox, "JOBS", jobs)
    r = TestClient(sandbox.app, base_url=LOCAL).delete("/video/jobs/c1", headers=CLE)
    assert r.status_code == 404
    assert (jobs / "c1").exists()


@pytest.mark.parametrize("jid", ["..", "a.b", "x" * 65])
def test_un_identifiant_douteux_n_efface_rien(sandbox, monkeypatch, jobs, jid):
    monkeypatch.setattr(sandbox, "JOBS", jobs)
    r = TestClient(sandbox.app, base_url=LOCAL).delete("/video/jobs/" + jid, headers=CLE)
    assert r.status_code in (404, 405)
    assert (jobs / "v1").exists()


def test_un_nom_de_fichier_qui_sort_du_dossier_est_ignore(tmp_path):
    jobs, art = tmp_path / "jobs", tmp_path / "art"
    art.mkdir()
    precieux = tmp_path / "precieux.txt"
    precieux.write_text("garde-moi", encoding="utf-8")
    fiche(jobs, "f1", video={}, artifacts=[{"id": "a1", "path": "../precieux.txt"}])
    derniers.supprimer(jobs, art, "video", "f1")
    assert precieux.exists()


def test_EN_COURS_supprimer_ARRETE_d_abord_puis_efface(sandbox, monkeypatch, jobs):
    """<< refusee si en cours : non, ca devient abort >> (proprietaire, 23/09)."""
    monkeypatch.setattr(sandbox, "JOBS", jobs)
    arrets = []
    monkeypatch.setattr(sandbox, "arreter_modal", lambda jid: arrets.append(jid) or
                        {"arretees": 1, "detail": "La machine Modal est terminée."})
    r = TestClient(sandbox.app, base_url=LOCAL).delete("/video/jobs/v2", headers=CLE)
    assert r.status_code == 200
    assert arrets == ["v2"]                        # la machine louee est coupee
    assert "terminée" in r.json()["arret"]
    assert not (jobs / "v2").exists()


def test_le_fil_qui_suivait_ne_fait_pas_revenir_un_fantome(sandbox, monkeypatch, jobs):
    """Le fil d'un travail efface finit plus tard et reecrit sa fiche :
    write_job recreerait le dossier, et le travail reviendrait dans la liste."""
    monkeypatch.setattr(sandbox, "JOBS", jobs)
    monkeypatch.setattr(sandbox, "arreter_modal", lambda jid: {"arretees": 1, "detail": ""})
    TestClient(sandbox.app, base_url=LOCAL).delete("/video/jobs/v2", headers=CLE)
    sandbox.write_job("v2", {"id": "v2", "status": "failed", "video": {}})
    assert not (jobs / "v2").exists()


def test_derniers_refuse_d_effacer_un_travail_en_cours_s_il_n_a_pas_ete_arrete(jobs):
    with pytest.raises(derniers.TravailEnCours):
        derniers.supprimer(jobs, jobs, "video", "v2")
    assert (jobs / "v2").exists()


def test_la_page_propose_d_arreter_ET_supprimer_un_travail_en_cours(tmp_path, jobs):
    vus = _jouer("video", derniers.lister(jobs, "video"), tmp_path)
    assert "Arrêter et supprimer" in vus["html"]
    assert vus["html"].count("🗑️ Supprimer") == 2  # les deux finis


# --- Titres et lecture depuis la liste (proprietaire, 23/09) -----------------
# << on a bien l'historique des chansons mais on ne peut pas les jouer ;
# rajouter un titre lors des creations ; generalise a tout >>

@pytest.mark.parametrize("usage,payload,attendu", [
    ("video", {"titre": "  Le phare  ", "description": "x"}, "Le phare"),
    ("video", {"description": "un phare dans la tempête"}, "un phare dans la tempête"),
    ("chanson", {"paroles": "[verse]\nSous la pluie de Brest\n[chorus]\nla la", "style": "pop"},
     "Sous la pluie de Brest"),
    ("chanson", {"paroles": "", "style": "pop, voix douce"}, "pop, voix douce"),
    ("dialogue", {"texte": "[S1]Tu as vu le studio ?\n[S2]Oui."}, "Tu as vu le studio ?"),
])
def test_le_titre_est_celui_tape_SINON_le_debut_du_texte(usage, payload, attendu):
    assert derniers.titre(payload, usage) == attendu


def test_un_titre_trop_long_est_coupe_proprement():
    t = derniers.titre({"titre": "mot " * 40}, "video")
    assert len(t) <= derniers.TITRE_MAX and t.endswith("…")


def test_le_nom_du_fichier_vient_du_titre_sans_accent_ni_espace():
    assert derniers.nom_de_fichier("Été à Brest !", ".flac") == "ete-a-brest.flac"
    assert derniers.nom_de_fichier("", ".mp4") == "travail.mp4"


def test_la_liste_montre_le_titre(tmp_path):
    fiche(tmp_path, "c9", chanson={"secondes_max": 60}, titre="Sous la pluie de Brest")
    assert derniers.lister(tmp_path, "chanson")[0]["libelle"] == "Sous la pluie de Brest"


def test_un_clip_cree_garde_son_titre(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "")
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: None)
    r = TestClient(sandbox.app, base_url=LOCAL).post("/video/creer", headers=CLE, json={
        "description": "un phare", "duree": "3", "ou": "modal", "titre": "Phare breton"})
    assert r.status_code == 200
    assert r.json()["titre"] == "Phare breton"


@pytest.mark.parametrize("usage", derniers.USAGES)
def test_chaque_creation_enregistre_un_titre(usage):
    source = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    assert '"titre": derniers.titre(payload, "%s"),' % usage in source


@pytest.mark.parametrize("usage", derniers.USAGES)
def test_l_etat_du_travail_rend_le_titre(sandbox, monkeypatch, tmp_path, usage):
    monkeypatch.setattr(sandbox, "JOBS", tmp_path)
    fiche(tmp_path, "t1", **{usage: {}, "titre": "Mon titre"})
    r = TestClient(sandbox.app, base_url=LOCAL).get("/%s/jobs/t1" % usage, headers=CLE)
    assert r.json()["titre"] == "Mon titre"


@pytest.mark.parametrize("usage", derniers.USAGES)
def test_chaque_page_a_un_champ_titre_ENVOYE_avec_la_demande(sandbox, usage):
    page = TestClient(sandbox.app, base_url=LOCAL).get("/" + usage, headers=CLE).text
    assert page.index('id="titre"') < page.index('<button id="lancer"')
    assert 'titre: (document.getElementById("titre") || {}).value || ""' in page


@pytest.mark.parametrize("usage", derniers.USAGES)
def test_un_travail_relu_s_affiche_TOUT_DE_SUITE(sandbox, usage):
    """Avant : le premier tour du suivi venait 4 a 5 s apres le clic."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/" + usage, headers=CLE).text
    debut = page.index("function suivre(")
    corps = page[debut:page.index("\n}\n", debut)]
    assert "minuteur = setInterval(tour," in corps and corps.rstrip().endswith("tour();")


def test_chaque_ligne_a_un_VRAI_bouton_pour_ecouter(tmp_path, jobs):
    vus = _jouer("chanson", derniers.lister(jobs, "chanson"), tmp_path)
    assert "▶ Écouter" in vus["html"]
    vus = _jouer("video", derniers.lister(jobs, "video"), tmp_path)
    assert "▶ Voir" in vus["html"] and "Suivre" in vus["html"]
