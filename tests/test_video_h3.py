"""Vidéo H3 (sandbox-manager/video_h3.py) : ce qui se vérifie sans louer de carte.

Le clip lui-même a tourné hors du Studio le 27/09/2026 (PLAN.md, 18.6 et 18.9).
Ici : la demande, le graphe, la garde de licence, les refus avant location, et
que rien de ComfyUI (GPL-3.0) n'est importé par le code du Studio.
"""
import ast
import base64
import json
import shutil
import subprocess
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
    monkeypatch.setenv("VIDEO_H3_ACTIF", "true")
    return sandbox


def client(sandbox):
    return TestClient(sandbox.app, base_url="http://127.0.0.1:8020")


# H3 est un outil du poste administrateur (PLAN 20.1) : un Studio client, sans
# le réglage, n'a ni la page, ni les routes, ni la carte d'accueil.
@pytest.mark.parametrize("methode,chemin", [
    ("get", "/video-h3"), ("get", "/video-h3/etat"), ("post", "/video-h3/autorisation"),
    ("post", "/video-h3/poids/preparer"), ("post", "/video-h3/creer"), ("post", "/video-h3/image"),
])
def test_sans_le_reglage_h3_n_existe_pas(h3, monkeypatch, methode, chemin):
    monkeypatch.delenv("VIDEO_H3_ACTIF")
    r = getattr(client(h3), methode)(chemin, headers=CLE, **({"json": {}} if methode == "post" else {}))
    assert r.status_code == 404 and "pas activée" in r.json()["detail"]


def test_la_carte_d_accueil_suit_le_reglage(routeur, monkeypatch):
    c = TestClient(routeur.app)
    monkeypatch.delenv("VIDEO_H3_ACTIF", raising=False)
    sans = c.get("/studio").text
    monkeypatch.setenv("VIDEO_H3_ACTIF", "true")
    avec = c.get("/studio").text
    assert "/video-h3" not in sans and "Vidéo H3" not in sans
    assert "/video-h3" in avec and "🎬 Vidéo" in sans


def demande(**autres):
    d = {"mode": "texte", "image_paroles": "Une femme marche sous la pluie", "longueur": 124}
    d.update(autres)
    return d


# --- 1. La demande et le graphe ----------------------------------------------

def test_les_trois_cases_font_une_seule_invite(h3):
    v = h3.video_h3
    assert v.invite("Elle dit : \"Enfin.\"", "pluie", "") == \
        "Elle dit : (S1) <d>[French] Enfin.</d> Sound: pluie. non_diegetic_music: N/A"
    assert v.invite("  un phare  ", "", "piano doux") == \
        "un phare. non_diegetic_music: piano doux."
    assert v.invite("", "", "") == ""


def test_sans_musique_demandee_la_musique_est_refusee(h3):
    # Sans rien dire, H3 ajoute une musique : le champ du guide MiniMax vaut N/A.
    v = h3.video_h3
    assert v.invite("un phare", "vent", "  ").endswith("Sound: vent. non_diegetic_music: N/A")
    assert "N/A" not in v.invite("un phare", "", "violoncelle lent")
    assert v.invite("", "", "") == ""


def test_les_paroles_sont_balisees_au_format_du_modele(h3):
    # Fiche MiniMaxAI/MiniMax-H3 : `<d>[Language] …</d>`, le locuteur (S1) juste avant.
    v = h3.video_h3
    assert v.invite("Elle dit doucement : « Enfin au sec. »") == \
        "Elle dit doucement : (S1) <d>[French] Enfin au sec.</d> non_diegetic_music: N/A"
    assert v.balises_paroles("Il dit “Bonjour” puis «Au revoir»") == \
        "Il dit (S1) <d>[French] Bonjour</d> puis (S1) <d>[French] Au revoir</d>"
    assert v.invite("Il dit « Hello. »", langue="English").startswith(
        "Il dit (S1) <d>[English] Hello.</d>")
    deja = "Elle (S1) dit <d>[English] Hello.</d>"
    assert v.balises_paroles(deja) == deja
    assert v.balises_paroles("Une rue sous la pluie") == "Une rue sous la pluie"


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


# --- 6. Prolonger (V2) : par la dernière image, ou par tronçon en option --------------

def _clip_reussi(h3, jid="b" * 32, **video):
    v = {"moteur": "MiniMax H3 (ComfyUI v0.37.0)", "mode": "premiere", "secondes": 5.17}
    v.update(video)
    job = {"id": jid, "status": "succeeded", "artifacts": [], "video": v}
    h3.write_job(jid, job)
    return job


def test_sans_l_option_rien_de_tiers_n_entre_dans_la_machine(h3, monkeypatch):
    v = h3.video_h3
    monkeypatch.delenv("H3_MOTION_CONTEXT", raising=False)
    assert v.commandes() == v.COMMANDES
    assert not any("Motion-Context" in c for c in v.commandes())
    monkeypatch.setenv("H3_MOTION_CONTEXT", "true")
    assert v.commandes()[-1].endswith("git checkout " + v.MC_COMMIT)


def test_sans_l_option_on_prolonge_par_la_derniere_image(h3, monkeypatch):
    v = h3.video_h3
    monkeypatch.delenv("H3_MOTION_CONTEXT", raising=False)
    avant = _clip_reussi(h3, latent_vers="/poids/chaines/x.safetensors")
    plan = v.preparer_prolonger(demande(coupe_s=0.5), avant, PNG)
    g, d = plan["demande"]["graphe"], plan["demande"]
    assert g["10"]["inputs"]["first_frame"] == ["60", 0] and list(d["images"]) == ["premiere.png"]
    assert not any(n["class_type"].startswith("MiniMaxH3MotionContext") for n in g.values())
    assert d["mode"] == "prolonger" and d["coupe_s"] == 0 and "contexte" not in d
    r = plan["resume_public"]
    assert r["voie"] == "image" and r["plans"] == 2 and r["precedent"] == "b" * 32
    assert v.garder_latent(d, "c" * 32) is d and "latent_vers" not in d


def test_avec_l_option_on_prolonge_par_troncon(h3, monkeypatch):
    v = h3.video_h3
    monkeypatch.setenv("H3_MOTION_CONTEXT", "true")
    avant = _clip_reussi(h3, latent_vers="/poids/chaines/" + "b" * 32 + ".safetensors", plans=2)
    plan = v.preparer_prolonger(demande(), avant)
    g, d = plan["demande"]["graphe"], plan["demande"]
    assert g["30"]["inputs"] == {"latent_path": avant["video"]["latent_vers"], "clip_index": 1}
    mc = g["31"]["inputs"]
    assert mc["context_latent"] == ["30", 0] and mc["latent"] == ["10", 1] and mc["audio_vae"] == ["5", 0]
    assert (mc["context_length"], mc["audio_context_length"]) == ("22", 24)
    assert g["13"]["inputs"]["conditioning"] == ["31", 0]
    assert g["32"]["inputs"]["trim_frames"] == ["31", 1]
    assert g["17"]["inputs"]["images"] == ["32", 0] and g["17"]["inputs"]["audio"] == ["32", 1]
    assert "first_frame" not in g["10"]["inputs"] and d["images"] == {}
    assert d["contexte"] == avant["video"]["latent_vers"]
    assert set(v.NOEUDS_TRONCON) <= set(d["classes"])
    assert plan["resume_public"]["voie"] == "troncon" and plan["resume_public"]["plans"] == 3
    # Et ce plan garde à son tour son latent pour le suivant.
    v.garder_latent(d, "c" * 32)
    assert g["19"]["class_type"] == "MiniMaxH3MotionContextSaveLatent"
    assert g["19"]["inputs"]["latent"] == ["14", 0]
    assert d["latent_vers"] == "/poids/chaines/" + "c" * 32 + ".safetensors"


def test_un_clip_sans_latent_garde_se_prolonge_par_l_image_meme_avec_l_option(h3, monkeypatch):
    monkeypatch.setenv("H3_MOTION_CONTEXT", "true")
    assert h3.video_h3.voie_prolonger(_clip_reussi(h3)) == "image"


@pytest.mark.parametrize("video,statut,message", [
    ({"moteur": "Wan 2.1"}, "succeeded", "clip H3"),
    ({}, "failed", "pas réussi"),
    ({"plans": 4}, "succeeded", "4 plans"),
])
def test_ce_qui_ne_se_prolonge_pas_est_refuse(h3, video, statut, message):
    avant = _clip_reussi(h3, **video)
    avant["status"] = statut
    with pytest.raises(ValueError, match=message):
        h3.video_h3.preparer_prolonger(demande(), avant, PNG)


def test_le_script_verifie_le_contexte_et_garde_le_latent(h3, monkeypatch):
    v = h3.video_h3
    monkeypatch.setenv("H3_MOTION_CONTEXT", "true")
    avant = _clip_reussi(h3, latent_vers="/poids/chaines/" + "b" * 32 + ".safetensors")
    d = v.garder_latent(v.preparer_prolonger(demande(), avant)["demande"], "c" * 32)
    code = v.construire_script(d)
    ast.parse(code)
    assert "CONTEXTE_ABSENT" in code and "latent_garde" in code
    assert "par la dernière image" in v.phrase_d_echec("CONTEXTE_ABSENT /poids/chaines/x")


def test_prolonger_sans_copie_d_autorisation_rien_n_est_loue(h3):
    _clip_reussi(h3)
    r = client(h3).post("/video-h3/prolonger", headers=CLE, json=demande(precedent="b" * 32))
    assert r.status_code == 403


def test_prolonger_part_de_la_derniere_image_puis_recolle(h3, monkeypatch, tmp_path):
    _autoriser(h3)
    h3.video_h3.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.delenv("H3_MOTION_CONTEXT", raising=False)
    _clip_reussi(h3)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: video)
    monkeypatch.setattr(h3.montage, "derniere_image", lambda octets: base64.b64decode(PNG))
    lance = []
    monkeypatch.setattr(h3, "run_video_h3", lambda *a: lance.append(a))
    assert client(h3).post("/video-h3/prolonger", headers=CLE,
                           json=demande(precedent="../etc")).status_code == 400
    r = client(h3).post("/video-h3/prolonger", headers=CLE, json=demande(precedent="b" * 32))
    assert r.status_code == 200, r.text
    jid, _code, precedent, retirer = lance[0]
    assert (precedent, retirer) == ("b" * 32, 1)
    j = client(h3).get("/video/jobs/" + jid, headers=CLE).json()
    assert j["video"]["mode"] == "prolonger" and j["video"]["plans"] == 2


def test_le_plan_n_est_reussi_qu_une_fois_recolle(h3, monkeypatch, tmp_path):
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: {"exit_code": 0})

    def fini(jid, ou, resultat):
        job = h3.read_job(jid)
        job["status"] = "succeeded"
        h3.write_job(jid, job)

    monkeypatch.setattr(h3, "finish_execution", fini)
    avant, plan = tmp_path / "avant.mp4", tmp_path / "plan.mp4"
    avant.write_bytes(b"A")
    plan.write_bytes(b"B")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: avant if jid == "b" * 32 else plan)
    vus = []

    def recoller(a, b, retirer):
        vus.append((a, b, retirer, h3.read_job("c" * 32)["status"]))
        return b"AB"

    monkeypatch.setattr(h3.montage, "recoller_son", recoller)
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 247)
    _clip_reussi(h3)
    h3.write_job("c" * 32, {"id": "c" * 32, "status": "queued", "artifacts": [], "video": {"plans": 2}})
    h3.run_video_h3("c" * 32, "print(1)", "b" * 32, 1)
    job = h3.read_job("c" * 32)
    # Pendant le recollage le travail n'est pas « réussi » : la page montrerait le plan seul.
    assert vus == [(b"A", b"B", 1, "running")]
    assert job["status"] == "succeeded" and job["etape"] == "" and plan.read_bytes() == b"AB"
    assert job["video"]["secondes"] == round(247 / 24, 2)


def test_un_recollage_rate_fait_echouer_le_plan(h3, monkeypatch):
    _clip_reussi(h3)
    h3.write_job("c" * 32, {"id": "c" * 32, "status": "running", "artifacts": [], "video": {}})
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: None)
    h3.recoller_h3("c" * 32, "b" * 32, 1)
    job = h3.read_job("c" * 32)
    assert job["status"] == "failed" and "introuvable" in job["error"]


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_le_recollage_garde_le_son_et_compte_les_images(h3, tmp_path):
    def clip(nom, couleur):
        chemin = tmp_path / nom
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=%s:s=64x48:r=24" % couleur, "-f", "lavfi", "-i", "sine=f=440:r=48000",
                        "-frames:v", "24", "-t", "1", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(chemin)], check=True)
        return chemin.read_bytes()

    m = h3.montage
    for retirer, attendu in ((1, 47), (0, 48)):
        sortie = tmp_path / ("ab%d.mp4" % retirer)
        sortie.write_bytes(m.recoller_son(clip("a.mp4", "red"), clip("b.mp4", "blue"), retirer))
        assert m.images(sortie) == attendu
        flux = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                               "-of", "csv=p=0", str(sortie)], capture_output=True, text=True).stdout.split()
        assert flux == ["video", "audio"]


def test_la_page_propose_de_prolonger(h3):
    html = client(h3).get("/video-h3").text
    assert 'id="prolonger"' in html and "/video-h3/prolonger" in html
    assert client(h3).get("/video-h3/etat", headers=CLE).json()["prolonger"]["plans_max"] == 4


def test_la_langue_des_paroles_se_choisit_parmi_les_onze(h3):
    v = h3.video_h3
    html = client(h3).get("/video-h3").text
    assert "__LANGUES__" not in html and '<option value="French" selected>français</option>' in html
    assert all(f'value="{code}"' in html for code in v.LANGUES_PAROLES)
    assert html.count('langue: document.getElementById("langue").value') == 2   # créer et prolonger
    plan = v.preparer(demande(image_paroles="Il dit « Hola. »", langue="Spanish"))
    assert "<d>[Spanish] Hola.</d>" in plan["resume_public"]["invite"]
    assert plan["resume_public"]["langue"] == "Spanish"
    assert v.preparer(demande())["resume_public"]["langue"] == "French"
    with pytest.raises(ValueError, match="Langue"):
        v.preparer(demande(langue="Klingon"))
