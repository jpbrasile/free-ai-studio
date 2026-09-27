"""Vidéo H3 (sandbox-manager/video_h3.py) : ce qui se vérifie sans louer de carte.

Le clip lui-même a tourné hors du Studio le 27/09/2026 (PLAN.md, 18.6 et 18.9).
Ici : la demande, le graphe, la garde de licence, les refus avant location, et
que rien de ComfyUI (GPL-3.0) n'est importé par le code du Studio.
"""
import ast
import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parents[1]
CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 64).decode()
PDF = base64.b64encode(b"%PDF-1.4 copie").decode()


@pytest.fixture
def h3(sandbox, monkeypatch, tmp_path):
    v = sandbox.video_h3
    monkeypatch.setattr(v, "DOSSIER_AUTORISATION", tmp_path / "h3-autorisation")
    monkeypatch.setattr(v, "FICHE_AUTORISATION", tmp_path / "h3-autorisation" / "fiche.json")
    monkeypatch.setattr(v, "FICHE_POIDS", tmp_path / "h3-poids.json")
    monkeypatch.setattr(sandbox.budget_modal, "FICHIER", tmp_path / "modal-budget.json")
    monkeypatch.setattr(sandbox.budget_modal, "_releve_reel", lambda: None)
    return sandbox


def client(sandbox):
    return TestClient(sandbox.app, base_url="http://127.0.0.1:8020")


def demande(**autres):
    d = {"mode": "texte", "image_paroles": "Une femme marche sous la pluie", "longueur": 124}
    d.update(autres)
    return d


# --- 1. La demande et le graphe ----------------------------------------------

def test_les_trois_cases_font_une_seule_invite(h3):
    v = h3.video_h3
    assert v.invite("Elle dit : \"Enfin.\"", "pluie", "") == "Elle dit : \"Enfin.\" Sound: pluie."
    assert v.invite("  un phare  ", "", "piano doux") == "un phare. Music: piano doux."
    assert v.invite("", "", "") == ""


def test_la_grille_est_celle_du_modele(h3):
    v = h3.video_h3
    assert v.LONGUEURS[0] == 124 and v.LONGUEURS[-1] == 362
    assert all((n - 5) % 17 == 0 for n in v.LONGUEURS)
    # Une seule durée mesurée : les autres n'inventent pas de prix.
    assert [d["images"] for d in v.durees() if d["prix_estime_usd"] is not None] == [124]


@pytest.mark.parametrize("mode,images,noeud,attendus", [
    ("texte", 0, "MiniMaxH3ImageToVideo", set()),
    ("premiere", 1, "MiniMaxH3ImageToVideo", {"first_frame"}),
    ("premiere_derniere", 2, "MiniMaxH3ImageToVideo", {"first_frame", "last_frame"}),
    ("references", 3, "MiniMaxH3ReferenceToVideo",
     {"ref_images.ref_image_0", "ref_images.ref_image_1", "ref_images.ref_image_2"}),
])
def test_chaque_mode_branche_ses_images(h3, mode, images, noeud, attendus):
    g = h3.video_h3.graphe(mode, "une scene", 141, 44, images)
    assert g["10"]["class_type"] == noeud
    entrees = set(g["10"]["inputs"])
    images_branchees = {k for k in entrees if k in ("first_frame", "last_frame") or k.startswith("ref_images.")}
    assert images_branchees == attendus
    assert len([n for n in g.values() if n["class_type"] == "LoadImage"]) == images
    assert g["10"]["inputs"]["length"] == 141
    assert g["12"]["inputs"]["noise_seed"] == 44
    # Chaque lien pointe vers un noeud qui existe.
    for n in g.values():
        for val in n["inputs"].values():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[1], int):
                assert val[0] in g


def test_le_graphe_reprend_le_reglage_des_essais(h3):
    g = h3.video_h3.graphe("texte", "x", 124, 1)
    assert g["8"]["inputs"]["sampler_name"] == "res_multistep"
    assert g["9"]["inputs"] == {"model": ["2", 0], "scheduler": "simple", "steps": 4, "denoise": 1.0}
    assert g["18"]["class_type"] == "SaveVideo"


@pytest.mark.parametrize("mode,images,message", [
    ("texte", [PNG], "ne prend pas d'image"),
    ("premiere", [], "demande 1 image"),
    ("premiere_derniere", [PNG], "demande 2 image"),
    ("references", [], "de 1 à 9 images"),
])
def test_le_nombre_d_images_est_controle(h3, mode, images, message):
    with pytest.raises(ValueError, match=message):
        h3.video_h3.preparer(demande(mode=mode, images=images))


def test_une_image_qui_n_en_est_pas_une_est_refusee(h3):
    faux = base64.b64encode(b"GIF89a....").decode()
    with pytest.raises(ValueError, match="PNG, JPEG et WebP"):
        h3.video_h3.preparer(demande(mode="premiere", images=[faux]))


@pytest.mark.parametrize("champ,valeur", [("longueur", 125), ("coupe_s", 0.3), ("graine", "abc")])
def test_les_reglages_hors_menu_sont_refuses(h3, champ, valeur):
    with pytest.raises(ValueError):
        h3.video_h3.preparer(demande(**{champ: valeur}))


def test_une_demande_juste_part_avec_ses_images_et_sa_graine(h3):
    plan = h3.video_h3.preparer(demande(mode="premiere_derniere", images=["data:image/png;base64," + PNG, PNG],
                                        coupe_s=0.5), graine_hasard=lambda a, b: 7)
    d = plan["demande"]
    assert sorted(d["images"]) == ["derniere.png", "premiere.png"]
    assert d["graine"] == 7 and d["coupe_s"] == 0.5 and d["classes"] == ["MiniMaxH3ImageToVideo"]
    assert plan["resume_public"]["prix_estime_usd"] is not None


# --- 2. Le script envoyé sur la machine louée ---------------------------------

def test_le_script_est_du_python_et_porte_la_demande(h3):
    v = h3.video_h3
    plan = v.preparer(demande())
    code = v.construire_script(plan["demande"])
    ast.parse(code)
    b64 = code.split('b64decode("', 1)[1].split('"', 1)[0]
    assert json.loads(base64.b64decode(b64))["graphe"] == plan["demande"]["graphe"]
    ast.parse(v.construire_script_poids())
    assert v.HF_REVISION in base64.b64decode(
        v.construire_script_poids().split('b64decode("', 1)[1].split('"', 1)[0]).decode()


def test_rien_de_comfyui_n_est_importe(h3):
    """ComfyUI est sous GPL-3.0 : il tourne à part et on lui parle par HTTP."""
    for source in (RACINE / "sandbox-manager" / "video_h3.py").read_text(encoding="utf-8"), \
            h3.video_h3.construire_script(h3.video_h3.preparer(demande())["demande"]):
        for noeud in ast.walk(ast.parse(source)):
            if isinstance(noeud, (ast.Import, ast.ImportFrom)):
                noms = [a.name for a in noeud.names] + [getattr(noeud, "module", "") or ""]
                assert not any(n.split(".")[0] in ("comfy", "comfy_extras", "nodes", "folder_paths")
                               for n in noms), noms


def test_les_echecs_du_script_ont_leur_phrase(h3):
    v = h3.video_h3
    assert "Préparer les poids" in v.phrase_d_echec("POIDS_ABSENTS vae/x")
    assert "nœud" in v.phrase_d_echec("NOEUD_ABSENT ['MiniMaxH3ReferenceToVideo']")
    assert v.phrase_d_echec("autre chose") == ""


# --- 3. La garde de licence et les refus avant location ------------------------

def test_sans_copie_d_autorisation_rien_n_est_loue(h3, monkeypatch):
    lance = []
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(h3, "run_video_h3", lambda *a: lance.append(a))
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande())
    assert r.status_code == 403 and "autorisation" in r.json()["detail"]
    r = client(h3).post("/video-h3/poids/preparer", headers=CLE, json={})
    assert r.status_code == 403
    assert lance == []


def test_la_copie_se_depose_et_se_relit(h3):
    c = client(h3)
    assert c.get("/video-h3/etat", headers=CLE).json()["autorisation"] == {"presente": False}
    r = c.post("/video-h3/autorisation", headers=CLE,
               json={"copie": "data:application/pdf;base64," + PDF, "date_autorisation": "2026-09-26"})
    assert r.status_code == 200, r.text
    a = c.get("/video-h3/etat", headers=CLE).json()["autorisation"]
    assert a["presente"] and a["date_autorisation"] == "2026-09-26"
    assert (h3.video_h3.DOSSIER_AUTORISATION / "copie.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("corps", [
    {"copie": base64.b64encode(b"texte").decode(), "date_autorisation": "2026-09-26"},
    {"copie": PDF, "date_autorisation": "26/09/2026"},
    {"copie": "", "date_autorisation": "2026-09-26"},
])
def test_une_copie_douteuse_est_refusee(h3, corps):
    r = client(h3).post("/video-h3/autorisation", headers=CLE, json=corps)
    assert r.status_code == 400


def _autoriser(h3):
    client(h3).post("/video-h3/autorisation", headers=CLE,
                    json={"copie": PNG, "date_autorisation": "2026-09-26"})


def test_sans_poids_le_clip_attend_la_preparation(h3, monkeypatch):
    _autoriser(h3)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande())
    assert r.status_code == 409 and "Préparer les poids" in r.json()["detail"]


def test_des_poids_d_une_autre_revision_ne_comptent_pas(h3):
    v = h3.video_h3
    v.poids_noter(True)
    assert v.poids_etat()["prets"]
    fiche = json.loads(v.FICHE_POIDS.read_text(encoding="utf-8"))
    fiche["revision"] = "ancienne"
    v.FICHE_POIDS.write_text(json.dumps(fiche), encoding="utf-8")
    assert not v.poids_etat()["prets"]


def test_sans_modal_branche_le_clip_est_refuse(h3):
    _autoriser(h3)
    h3.video_h3.poids_noter(True)
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande())
    assert r.status_code == 503


def test_le_budget_refuse_avant_de_louer(h3, monkeypatch):
    _autoriser(h3)
    h3.video_h3.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    lance = []
    monkeypatch.setattr(h3, "run_video_h3", lambda *a: lance.append(a))
    h3.budget_modal.poser("video", 0, h3.budget_modal.plafond_de("video") - 0.10, 1)
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande())
    assert r.status_code == 429
    assert lance == []


def test_un_clip_permis_part_et_se_suit_comme_une_video(h3, monkeypatch):
    _autoriser(h3)
    h3.video_h3.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    lance = []
    monkeypatch.setattr(h3, "run_video_h3", lambda *a: lance.append(a))
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(mode="premiere", images=[PNG]))
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    assert len(lance) == 1 and lance[0][0] == jid and "__DEMANDE_B64__" not in lance[0][1]
    j = client(h3).get("/video/jobs/" + jid, headers=CLE).json()
    assert j["status"] == "queued"
    assert j["video"]["mode"] == "premiere" and j["video"]["carte"] == h3.video_h3.GPU


def test_l_echec_d_un_clip_est_encaisse_et_explique(h3, monkeypatch):
    """Le temps de location compte même quand le clip échoue."""
    monkeypatch.setattr(h3, "modal_configured", lambda: True)

    def modal_rate(jid, code, *a, **k):
        assert k["coeurs"] == h3.video_h3.COEURS and k["gpu_type"] == h3.video_h3.GPU
        return {"exit_code": 3, "timed_out": False, "stdout": "", "stderr": "POIDS_ABSENTS vae/x",
                "artifacts": []}

    monkeypatch.setattr(h3, "modal_execute", modal_rate)
    jid = "a" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    avant = h3.budget_modal.vue("video")["appels"]["video"]
    h3.run_video_h3(jid, "print(1)")
    job = h3.read_job(jid)
    assert job["status"] == "failed"
    assert "Préparer les poids" in job["error"]
    assert h3.budget_modal.vue("video")["appels"]["video"] == avant + 1


# --- 4. La page -----------------------------------------------------------------

def test_la_page_porte_la_cle_et_les_formateurs(h3):
    html = client(h3).get("/video-h3").text
    assert "__CLE__" not in html and "cle-sandbox-de-test" in html
    assert "function renouvellementTexte(" in html and "function dateFr(" in html
    for id_ in ("image_paroles", "ambiance", "musique", "longueur", "coupe", "licence_fichier", "lecteur"):
        assert 'id="' + id_ + '"' in html


def test_l_etat_dit_les_quatre_modes_et_le_pire_cas(h3):
    d = client(h3).get("/video-h3/etat", headers=CLE).json()
    assert list(d["modes"]) == ["texte", "premiere", "premiere_derniere", "references"]
    assert all(m["essaye_le"] == "2026-09-27" for m in d["modes"].values())
    assert d["pire_cas_usd"] > 0 and "compteur_remis_a_zero_le" in d["budget"]


def test_le_registre_annonce_le_pire_cas_du_code(h3):
    reg = json.loads((RACINE / "registry" / "apps.json").read_text(encoding="utf-8"))
    entree = next(a for a in reg["applications"] if a["id"] == "video_h3")
    assert entree["modele"] == h3.video_h3.HF
    assert entree["cout_max_usd"] == h3.video_h3.pire_cas()


# --- 5. Première et dernière image : créées par l'image du Studio ou téléversées ---

class _FauxRouteur:
    """Remplace httpx.AsyncClient : rend `reponse` et garde la demande."""

    def __init__(self, statut, corps, vu):
        self.statut, self.corps, self.vu = statut, corps, vu

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.vu.update(url=url, headers=headers, json=json)
        statut, corps = self.statut, self.corps

        class R:
            status_code = statut

            def json(self):
                return corps
        return R()


def test_l_image_du_studio_passe_par_le_routeur(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    vu = {}
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(200, {"data": [{"url": "data:image/png;base64," + PNG}]}, vu))
    r = client(h3).post("/video-h3/image", headers=CLE, json={"texte": "  une rue  mouillée "})
    assert r.status_code == 200 and r.json()["image"].startswith("data:image/png;base64,")
    assert vu["url"].endswith("/v1/images/generations")
    assert vu["json"] == {"prompt": "une rue mouillée", "n": 1, "size": "1664x960"}
    assert vu["headers"]["Authorization"] == "Bearer cle-routeur-de-test"


def test_le_refus_de_l_image_est_dit(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(503, {"detail": "Ajoutez la clé Google."}, {}))
    r = client(h3).post("/video-h3/image", headers=CLE, json={"texte": "x"})
    assert r.status_code == 503 and "Ajoutez la clé Google." in r.json()["detail"]


def test_sans_cle_du_routeur_on_propose_de_televerser(h3, monkeypatch):
    monkeypatch.delenv("FREE_TIER_MANAGER_KEY", raising=False)
    r = client(h3).post("/video-h3/image", headers=CLE, json={"texte": "x"})
    assert r.status_code == 503 and "Téléversez" in r.json()["detail"]
    assert client(h3).post("/video-h3/image", headers=CLE, json={"texte": " "}).status_code == 400


def test_la_page_offre_creer_ou_televerser_pour_chaque_bord(h3):
    html = client(h3).get("/video-h3").text
    for nom in ("premiere", "derniere"):
        assert 'name="source_' + nom + '" value="creer"' in html
        assert 'name="source_' + nom + '" value="televerser"' in html
        assert 'id="invite_' + nom + '"' in html and 'id="fichier_' + nom + '"' in html
    # Les exemples des trois cases sont du vrai texte, modifiable, pas une indication grisée.
    assert "placeholder=" not in html.split('id="image_paroles"', 1)[1].split(">", 1)[0]
    assert client(h3).get("/video-h3/etat", headers=CLE).json()["taille"] == {"largeur": 832, "hauteur": 480}
