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
    monkeypatch.setattr(v, "DOSSIER_FICHES", tmp_path / "h3-fiches")
    monkeypatch.setattr(v, "DOSSIER_SCENARIOS", tmp_path / "h3-scenarios")
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
    ("get", "/video-h3/fiches"), ("post", "/video-h3/fiches"),
    ("get", "/video-h3/clips"), ("post", "/video-h3/scenario/ordonner"), ("post", "/video-h3/montage"),
    ("post", "/video-h3/scenario/decouper"), ("post", "/video-h3/scenario/tourner"),
    ("get", "/video-h3/scenario/" + "a" * 32), ("post", "/video-h3/musique"), ("get", "/video-h3/scenarios"),
    ("post", "/video-h3/scenario/" + "a" * 32 + "/juger"), ("post", "/video-h3/scenario/" + "a" * 32 + "/corriger"),
    ("post", "/video-h3/scenario/" + "a" * 32 + "/rejouer"),
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


@pytest.mark.parametrize("champ,valeur", [("longueur", 125), ("coupe_s", 0.3), ("graine", "abc"),
                                          ("definition", "1080p")])
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
    assert plan["resume_public"]["taille"] == "832x480"


def test_la_definition_768p_change_la_taille_et_tait_le_prix(h3):
    # Le LoRA Turbo a été entraîné en 1344 × 768 ; aucune durée n'y est encore mesurée.
    plan = h3.video_h3.preparer(demande(definition="768p"))
    noeud = plan["demande"]["graphe"]["10"]["inputs"]
    assert (noeud["width"], noeud["height"]) == (1344, 768)
    assert plan["resume_public"]["taille"] == "1344x768"
    assert plan["resume_public"]["prix_estime_usd"] is None
    g = h3.video_h3.graphe("texte", "x", 124, 1)
    assert (g["10"]["inputs"]["width"], g["10"]["inputs"]["height"]) == (832, 480)


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


class _FauxRouteurSuite(_FauxRouteur):
    """Rend les contenus de `contenus` l'un après l'autre ; garde chaque demande dans `vus`."""

    def __init__(self, contenus, vus):
        super().__init__(200, None, {})
        self.contenus, self.vus = list(contenus), vus

    async def post(self, url, headers=None, json=None):
        self.vus.append(json)
        self.corps = {"choices": [{"message": {"content": self.contenus.pop(0)}}]}
        return await super().post(url, headers, json)


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
    assert client(h3).get("/video-h3/etat", headers=CLE).json()["definitions"] == {
        "480p": {"largeur": 832, "hauteur": 480}, "768p": {"largeur": 1344, "hauteur": 768}}
    assert '<select id="definition">' in html and html.count('definition: document.getElementById("definition")') == 3


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
    assert html.count('langue: document.getElementById("langue").value') == 2   # créer, prolonger
    # Le scénario prend la langue du personnage, sinon celle du clip.
    assert 'langue: f1 ? l1 : document.getElementById("langue").value' in html
    assert 'id="scenario_langue1"' in html and 'id="scenario_langue2"' in html
    plan = v.preparer(demande(image_paroles="Il dit « Hola. »", langue="Spanish"))
    assert "<d>[Spanish] Hola.</d>" in plan["resume_public"]["invite"]
    assert plan["resume_public"]["langue"] == "Spanish"
    assert v.preparer(demande())["resume_public"]["langue"] == "French"
    with pytest.raises(ValueError, match="Langue"):
        v.preparer(demande(langue="Klingon"))


# --- Fiches de casting (PLAN 18.9) ------------------------------------------------

JPG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\0" * 64).decode()


def test_une_fiche_se_cree_image_par_image_se_rejoue_et_se_supprime(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    c = client(h3)
    assert c.post("/video-h3/fiches", headers=CLE, json={"nom": "", "description": "x"}).status_code == 400
    f = c.post("/video-h3/fiches", headers=CLE,
               json={"nom": "Léa", "description": "Femme de 35 ans, manteau rouge"}).json()
    fid = f["id"]
    # Les autres angles partent du portrait de face : sans lui, refus.
    r = c.post(f"/video-h3/fiches/{fid}/images/profil", headers=CLE, json={})
    assert r.status_code == 400 and "portrait de face" in r.json()["detail"]

    vu = {}
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(200, {"data": [{"url": "data:image/png;base64," + PNG}]}, vu))
    f = c.post(f"/video-h3/fiches/{fid}/images/face", headers=CLE, json={}).json()
    assert "Femme de 35 ans, manteau rouge" in vu["json"]["prompt"] and "image_reference" not in vu["json"]
    assert f["images"]["face"] == "data:image/png;base64," + PNG

    f = c.post(f"/video-h3/fiches/{fid}/images/trois_quarts", headers=CLE, json={}).json()
    assert vu["json"]["image_reference"] == "data:image/png;base64," + PNG   # le visage suit
    assert "même personne" in vu["json"]["prompt"]
    # Rejouer = redemander le même angle ; un téléversement remplace sans appeler Google.
    vu.clear()
    f = c.post(f"/video-h3/fiches/{fid}/images/trois_quarts", headers=CLE, json={"image": JPG}).json()
    assert vu == {} and f["images"]["trois_quarts"].startswith("data:image/jpeg;base64,")
    assert sorted(p.name for p in (h3.video_h3.DOSSIER_FICHES / fid).iterdir()) == \
        ["face.png", "fiche.json", "trois_quarts.jpg"]

    liste = c.get("/video-h3/fiches", headers=CLE).json()
    assert [x["angles"] for x in liste["fiches"]] == [["face", "trois_quarts"]]
    assert list(liste["angles"]) == ["face", "trois_quarts", "pied", "profil"]

    f = c.delete(f"/video-h3/fiches/{fid}/images/face", headers=CLE).json()
    assert list(f["images"]) == ["trois_quarts"]
    assert c.delete(f"/video-h3/fiches/{fid}", headers=CLE).status_code == 200
    assert c.get(f"/video-h3/fiches/{fid}", headers=CLE).status_code == 404
    assert not (h3.video_h3.DOSSIER_FICHES / fid).exists()


def test_une_fiche_refuse_les_identifiants_et_angles_inventes(h3):
    c = client(h3)
    for chemin in ("/video-h3/fiches/..%2F..%2Fsecrets", "/video-h3/fiches/abc"):
        assert c.get(chemin, headers=CLE).status_code == 404
    fid = h3.video_h3.fiche_creer("Léa", "une femme")["id"]
    r = c.post(f"/video-h3/fiches/{fid}/images/dos", headers=CLE, json={"image": PNG})
    assert r.status_code == 400 and "Angle" in r.json()["detail"]
    assert c.get("/video-h3/fiches", headers={"Authorization": "Bearer faux"}).status_code in (401, 403)


def test_un_clip_avec_une_fiche_nomme_le_personnage_comme_le_guide_de_minimax(h3):
    v = h3.video_h3
    fid = v.fiche_creer("Léa", "femme de 35 ans, manteau rouge")["id"]
    with pytest.raises(ValueError, match="aucune image"):
        v.preparer(demande(mode="references", fiche=fid))
    v.fiche_poser_image(fid, "face", PNG)
    v.fiche_poser_image(fid, "pied", JPG)
    plan = v.preparer(demande(mode="references", fiche=fid, images=[PNG],
                              image_paroles="Elle sourit et dit « Bonjour. »"))
    invite = plan["resume_public"]["invite"]
    assert invite.startswith("subject_definitions: <Subject 1> is the person in <Picture 1>, <Picture 2>. "
                             "retention_analysis: <Subject 1> keeps the face, hair and clothing of the "
                             "reference pictures. detailed_description: In the foreground: only <Subject 1>, "
                             "each of them one single person shown once. "
                             "Elle sourit")
    # La description sert aux images de la fiche, jamais à l'invite : le 28/09, le
    # personnage l'a récitée.
    assert "manteau rouge" not in invite and "Léa" not in invite
    assert "<Subject 1> (S1) <d>[French] Bonjour.</d>" in invite
    assert list(plan["demande"]["images"]) == ["ref_0.png", "ref_1.png", "ref_2.png"]   # fiche, puis ajout
    assert plan["resume_public"]["fiche"] == {"id": fid, "nom": "Léa"}
    with pytest.raises(ValueError, match="Références"):
        v.preparer(demande(mode="texte", fiche=fid))
    with pytest.raises(ValueError, match="inconnue"):
        v.preparer(demande(mode="references", fiche="0123456789ab"))


def test_la_page_propose_les_fiches(h3):
    html = client(h3).get("/video-h3").text
    for morceau in ('id="fiche_choix"', 'id="fiche_ref"', "/video-h3/fiches/", "Rejouer", "Supprimer",
                    'fiche: m === "references"'):
        assert morceau in html


def test_la_traduction_garde_les_repliques_mot_pour_mot(h3):
    v = h3.video_h3
    p = {"mode": "references", "image_paroles": "Elle s'assoit et dit « Un café, s'il vous plaît. »",
         "ambiance": "Brouhaha d'un café", "musique": ""}
    assert v.a_traduire(p) and not v.a_traduire(dict(p, mode="premiere"))
    assert '« Un café' in v.consigne_traduction(p) and "EXACTLY" in v.consigne_traduction(p)
    bon = ('```json\n{"image_paroles": "She sits down and says « Un café, s\'il vous plaît. »", '
           '"ambiance": "Café chatter", "musique": ""}\n```')
    t = v.lire_traduction(bon, p)
    assert t["ambiance"] == "Café chatter" and t["mode"] == "references"
    assert v.invite(t["image_paroles"]).startswith("She sits down and says (S1) <d>[French] Un café, s'il")
    traduite = '{"image_paroles": "She says « A coffee, please. »", "ambiance": "x", "musique": ""}'
    with pytest.raises(ValueError, match="réplique"):
        v.lire_traduction(traduite, p)
    with pytest.raises(ValueError, match="lue"):
        v.lire_traduction("Désolé, je ne peux pas.", p)


def test_en_mode_references_le_clip_part_traduit(h3, monkeypatch):
    _autoriser(h3)
    h3.video_h3.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(h3, "run_video_h3", lambda *a: None)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    vu = {}
    reponse = {"choices": [{"message": {"content":
               '{"image_paroles": "In a café she says « Bonjour. »", "ambiance": "Café chatter", "musique": ""}'}}]}
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(200, reponse, vu))
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(
        mode="references", images=[PNG], image_paroles="Dans un café elle dit « Bonjour. »",
        ambiance="Brouhaha"))
    assert r.status_code == 200, r.text
    assert vu["url"].endswith("/v1/chat/completions")
    v = r.json()["video"]
    assert v["invite"].startswith("In a café she says (S1) <d>[French] Bonjour.</d> Sound: Café chatter.")
    assert v["traduit_en_anglais"] is True
    # Un refus du chat : rien ne part.
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(503, {}, {}))
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(mode="references", images=[PNG]))
    assert r.status_code == 502 and "rien n'est lancé" in r.json()["detail"]


# --- 8. Le scénario monté après coup : des clips déjà faits, recollés dans l'ordre ---

def _deux_clips(h3, monkeypatch, tmp_path):
    fichiers = {}
    for jid, octets, invite in (("a" * 32, b"A", "Elle entre dans le café"), ("b" * 32, b"B", "Elle commande")):
        _clip_reussi(h3, jid, invite=invite)
        fichiers[jid] = tmp_path / (jid[0] + ".mp4")
        fichiers[jid].write_bytes(octets)
    _clip_reussi(h3, "d" * 32, moteur="Wan 2.1")   # pas un clip H3 : jamais proposé
    fichiers["d" * 32] = tmp_path / "d.mp4"
    fichiers["d" * 32].write_bytes(b"D")
    vrai = h3._video_h3_octets
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: fichiers.get(jid) or vrai(jid))
    return fichiers


def test_l_ordre_des_clips_est_controle(h3):
    v = h3.video_h3
    a, b = "a" * 32, "b" * 32
    for mauvais, message in (([a], "de 2"), ([a, a], "deux fois"), (["../x", a], "illisible"), ("ab", "illisible")):
        with pytest.raises(ValueError, match=message):
            v.verifier_ordre(mauvais)
    assert v.lire_ordre('```json\n["%s", "%s"]\n```' % (b, a), {a: "", b: ""}) == [b, a]
    with pytest.raises(ValueError, match="pas dans la liste"):
        v.lire_ordre('["%s", "%s"]' % (b, "c" * 32), {a: "", b: ""})
    with pytest.raises(ValueError, match="pas pu être lu"):
        v.lire_ordre("Je ne sais pas.", {a: "", b: ""})
    assert "Elle entre" in v.consigne_ordre("Léa entre, puis commande.", {a: "Elle entre"})


def test_le_film_recolle_les_clips_dans_l_ordre_sans_rien_louer(h3, monkeypatch, tmp_path):
    _deux_clips(h3, monkeypatch, tmp_path)
    vus = []

    def recoller(a, b, retirer):
        vus.append(retirer)
        return a + b

    monkeypatch.setattr(h3.montage, "recoller_son", recoller)
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 248)
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: pytest.fail("rien ne se loue"))
    c = client(h3)
    liste = c.get("/video-h3/clips", headers=CLE).json()["clips"]
    assert {x["id"] for x in liste} == {"a" * 32, "b" * 32}
    r = c.post("/video-h3/montage", headers=CLE, json={"clips": ["b" * 32, "a" * 32], "scenario": "Léa"})
    assert r.status_code == 200, r.text
    film = r.json()
    assert film["status"] == "succeeded" and vus == [0]
    assert film["video"]["clips"] == ["b" * 32, "a" * 32] and film["video"]["plans"] == 2
    assert film["video"]["secondes"] == round(248 / 24, 2)
    j = c.get("/video/jobs/" + film["id"], headers=CLE).json()
    assert c.get(j["video_url"]).content == b"BA"
    # Un clip qui n'est pas H3, ou qui n'existe plus : refusé.
    for clips in (["a" * 32, "d" * 32], ["a" * 32, "e" * 32]):
        assert c.post("/video-h3/montage", headers=CLE, json={"clips": clips}).status_code == 404
    assert c.post("/video-h3/montage", headers=CLE, json={"clips": ["a" * 32]}).status_code == 400


def test_le_chat_range_les_clips_selon_le_scenario(h3, monkeypatch, tmp_path):
    _deux_clips(h3, monkeypatch, tmp_path)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    vu = {}
    reponse = {"choices": [{"message": {"content": '["%s", "%s"]' % ("a" * 32, "b" * 32)}}]}
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(200, reponse, vu))
    corps = {"scenario": "Léa entre dans le café, puis commande.", "clips": ["b" * 32, "a" * 32]}
    r = client(h3).post("/video-h3/scenario/ordonner", headers=CLE, json=corps)
    assert r.status_code == 200, r.text
    assert r.json()["ordre"] == ["a" * 32, "b" * 32]
    assert vu["url"].endswith("/v1/chat/completions")
    invente = {"choices": [{"message": {"content": '["%s", "%s"]' % ("a" * 32, "d" * 32)}}]}
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(200, invente, {}))
    r = client(h3).post("/video-h3/scenario/ordonner", headers=CLE, json=corps)
    assert r.status_code == 502 and "pas dans la liste" in r.json()["detail"]
    r = client(h3).post("/video-h3/scenario/ordonner", headers=CLE, json=dict(corps, scenario=""))
    assert r.status_code == 400


def test_la_page_propose_de_monter_un_scenario(h3):
    html = client(h3).get("/video-h3").text
    for morceau in ('id="scenario"', 'id="clips_liste"', "/video-h3/scenario/ordonner", "/video-h3/montage",
                    "rien n'est loué", "/video-h3/scenario/decouper", "/video-h3/scenario/tourner",
                    '"suite": "Suite directe'):
        assert morceau in html
    assert "__ENCHAINEMENTS__" not in html


# --- 9. Le scénario neuf, tourné plan par plan (conservé pour les futurs scénarios) ---

def test_le_decoupage_est_controle(h3):
    v = h3.video_h3
    scenario = "Léa entre dans le café. Elle dit « Un café, s'il vous plaît. »"
    bon = ('[{"image_paroles": "Léa entre", "ambiance": "Brouhaha", "enchainement": "suite"}, '
           '{"image_paroles": "Elle dit « Un café, s\'il vous plaît. »", "ambiance": "", "enchainement": "suite"}]')
    plans = v.lire_decoupage(bon, scenario)
    assert [p["enchainement"] for p in plans] == ["coupe", "suite"]   # le premier n'a rien avant lui
    invente = '[{"image_paroles": "Elle dit « Deux cafés. »", "ambiance": "", "enchainement": "coupe"}]'
    with pytest.raises(ValueError, match="inventé"):
        v.lire_decoupage(invente, scenario)
    with pytest.raises(ValueError, match="pas pu être lu"):
        v.lire_decoupage("[]", scenario)
    trop = [{"image_paroles": "x", "ambiance": "", "enchainement": "coupe"}] * (v.SCENARIO_PLANS_MAX + 1)
    for mauvais, message in ((trop, "au plus"), ([{"image_paroles": " "}], "décrivez"),
                             ([{"image_paroles": "x", "enchainement": "fondu"}], "inconnu")):
        with pytest.raises(ValueError, match=message):
            v.verifier_plans(mauvais)


def test_un_scenario_se_tourne_plan_par_plan_et_se_recolle(h3, monkeypatch, tmp_path):
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    reponse = {"choices": [{"message": {"content":
               '{"image_paroles": "Lea walks into the café", "ambiance": "Chatter", "musique": ""}'}}]}
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(200, reponse, {}))
    fid = v.fiche_creer("Léa", "femme de 35 ans")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    plans = [{"image_paroles": "Léa entre dans le café", "ambiance": "Brouhaha", "enchainement": "coupe"},
             {"image_paroles": "Elle dit « Bonjour. »", "ambiance": "", "enchainement": "suite"}]
    c = client(h3)
    r = c.post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "longueur": 124})
    assert r.status_code == 400 and "fiche" in r.json()["detail"]

    video = tmp_path / "plan.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: video)
    monkeypatch.setattr(h3.montage, "derniere_image", lambda octets: base64.b64decode(PNG))
    tournes = []

    def tourner(jid, code, precedent, retirer):
        tournes.append((jid, precedent, retirer, h3.read_job(jid)["video"]))
        job = h3.read_job(jid)
        job["status"] = "succeeded"
        h3.write_job(jid, job)

    monkeypatch.setattr(h3, "run_video_h3", tourner)

    fils, vrai = [], h3.run_scenario_h3
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    r = c.post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 200, r.text
    vrai(*fils[0])   # le fil, joué ici pour attendre sa fin
    sc = c.get("/video-h3/scenario/" + r.json()["id"], headers=CLE).json()
    assert sc["etat"] == "réussi" and len(tournes) == 2
    (j1, p1, r1, v1), (j2, p2, r2, v2) = tournes
    # Le premier plan, avec la fiche, part traduit ; la suite part de sa dernière image et s'y recolle.
    assert p1 is None and v1["mode"] == "references" and v1["traduit_en_anglais"] is True
    # Le nom, même traduit sans accent, devient <Subject 1> : dit tel quel, il a été récité.
    assert v1["invite"].startswith("subject_definitions:") and "<Subject 1> walks" in v1["invite"]
    assert (p2, r2) == (j1, 1) and v2["mode"] == "prolonger" and v2["plans"] == 2
    assert "(S1) <d>[French] Bonjour.</d>" in v2["invite"]
    assert sc["film"] == j2 and sc["travaux"] == [j1, j2] and "video_url" in sc


def test_un_plan_en_echec_arrete_le_scenario(h3, monkeypatch):
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    fid = v.fiche_creer("Léa", "x")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    tournes = []

    def rate(jid, *a):
        tournes.append(jid)
        job = h3.read_job(jid)
        job.update(status="failed", error="Plus de mémoire.")
        h3.write_job(jid, job)

    monkeypatch.setattr(h3, "run_video_h3", rate)
    sid = "f" * 32
    v.scenario_ecrire({"id": sid, "etat": "en cours", "erreur": "", "plans": [], "travaux": [], "film": None})
    p = {"mode": "references", "fiche": fid, "image_paroles": "Elle entre", "longueur": 124, "images": []}
    h3.run_scenario_h3(sid, [{"enchainement": "coupe", "payload": p}, {"enchainement": "coupe", "payload": p}])
    sc = v.scenario_lire(sid)
    assert len(tournes) == 1 and sc["etat"] == "échoué" and sc["erreur"] == "Plan 1 : Plus de mémoire."
    # Un scénario « en cours » dont le fil a disparu (Studio redémarré) le dit.
    v.scenario_noter(sid, etat="en cours")
    assert client(h3).get("/video-h3/scenario/" + sid, headers=CLE).json()["etat"] == "interrompu"


# --- 10. Deux personnages, deux langues, une musique posée après coup (28/09) ---

def test_chaque_replique_va_au_personnage_nomme_dans_sa_phrase(h3):
    v = h3.video_h3
    texte = ("Léa sourit à James. James dit « Hello Léa, is this seat taken? » Lea répond "
             "« Non, asseyez-vous. » Puis « Bon café. »")
    assert v.attribuer_repliques(texte, [("Léa", "French"), ("James", "English")]) == (
        # Forme du guide (5.4) : (Sx) suit le nom du locuteur dans sa phrase, jamais un second nom.
        "<Subject 1> sourit à <Subject 2>. <Subject 2> (S1) dit <d>[English] Hello Léa, is this "
        "seat taken?</d> <Subject 1> (S2) répond <d>[French] Non, asseyez-vous.</d> "
        "Puis <Subject 1> (S2) <d>[French] Bon café.</d>")
    # Un nom dans un autre mot n'est pas un personnage.
    assert v.attribuer_repliques("Jameson entre.", [("James", "English")]) == "Jameson entre."


def test_premier_plan_et_cadrage_sont_generiques(h3):
    v = h3.video_h3
    # Compté sur les sujets du plan, pas sur les fiches du scénario : un plan à un seul personnage.
    assert v.premier_plan("<Subject 2> marche seul.") == ("In the foreground: only <Subject 2>, each of them one "
                                                          "single person shown once.")
    assert "only <Subject 1>, <Subject 2> and <Subject 3>," in v.premier_plan("<Subject 3> <Subject 1> <Subject 2>")
    assert v.premier_plan("Une rue vide.") == ""
    # Règle 2, dans le découpage comme dans la correction ; aucun nom de personnage dans la règle.
    assert v.CADRAGE in v.consigne_decoupage("Un film.") and "at most %d shots" % v.SCENARIO_PLANS_MAX in \
        v.consigne_decoupage("Un film.")
    assert v.CADRAGE in v.consigne_correction([], "retour")
    assert "close-up shows one character only" in v.CADRAGE


def test_deux_fiches_font_deux_sujets_chacun_sa_langue(h3):
    v = h3.video_h3
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    v.fiche_poser_image(lea, "pied", JPG)
    v.fiche_poser_image(james, "face", PNG)
    d = demande(mode="references", fiches=[lea, james], langues={lea: "French", james: "English"},
                image_paroles="James demande « Is this seat taken? » Léa répond « Oui. »")
    plan = v.preparer(d)
    assert plan["resume_public"]["invite"] == (
        "subject_definitions: <Subject 1> is the person in <Picture 1>, <Picture 2>. <Subject 2> is the "
        "person in <Picture 3>. retention_analysis: <Subject 1> keeps the face, hair and clothing of the "
        "reference pictures. <Subject 2> keeps the face, hair and clothing of the reference pictures. "
        # Règle 1 (28/09) : le Studio compte lui-même qui est au premier plan.
        "detailed_description: In the foreground: only <Subject 1> and <Subject 2>, each of them one single "
        "person shown once. <Subject 2> (S1) demande <d>[English] Is this seat taken?</d> "
        "<Subject 1> (S2) répond <d>[French] Oui.</d> non_diegetic_music: N/A")
    assert list(plan["demande"]["images"]) == ["ref_0.png", "ref_1.png", "ref_2.png"]
    assert [f["nom"] for f in plan["resume_public"]["fiches"]] == ["Léa", "James"]
    for mauvais, message in (({"langues": {lea: "Klingon"}}, "inconnue"), ({"fiches": [lea, lea]}, "illisible")):
        with pytest.raises(ValueError, match=message):
            v.preparer(dict(d, **mauvais))


def _volume_max(chemin, debut, duree):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(debut), "-t", str(duree), "-i", str(chemin),
                          "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(err.split("max_volume:")[1].split("dB")[0])


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_la_musique_part_a_son_heure_et_decroit_jusqu_a_la_fin(h3, tmp_path):
    film, musique = tmp_path / "film.mp4", tmp_path / "musique.flac"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x48:r=24",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-frames:v", "72", "-t", "3",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(film)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=880:r=48000",
                    "-t", "10", str(musique)], check=True)
    m = h3.montage
    sortie = tmp_path / "avec.mp4"
    sortie.write_bytes(m.poser_musique(film.read_bytes(), musique.read_bytes(), 1.0))
    assert m.images(sortie) == 72
    avant, pendant, fin = _volume_max(sortie, 0, 0.8), _volume_max(sortie, 1.5, 0.5), _volume_max(sortie, 2.85, 0.15)
    assert avant < -60 < pendant and fin < pendant - 6   # silence, puis la musique, puis le decrescendo
    with pytest.raises(m.MontageImpossible, match="après la fin"):
        m.poser_musique(film.read_bytes(), musique.read_bytes(), 2.8)


def test_une_musique_du_studio_se_pose_sous_un_film(h3, monkeypatch, tmp_path):
    _deux_clips(h3, monkeypatch, tmp_path)
    son = tmp_path / "son.flac"
    son.write_bytes(b"SON")
    c_id = "c" * 32
    monkeypatch.setattr(h3, "_chansons_pretes", lambda: [{"id": c_id, "titre": "Jazz", "cree_a": 0}])
    monkeypatch.setattr(h3, "chanson_fichiers", lambda jid: {"son": {"path": str(son)}})
    vus = []
    monkeypatch.setattr(h3.montage, "poser_musique", lambda f, s, d, vol: vus.append((f, s, d, vol)) or f + s)
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 248)
    c = client(h3)
    assert [x["id"] for x in c.get("/video-h3/clips", headers=CLE).json()["chansons"]] == [c_id]
    r = c.post("/video-h3/musique", headers=CLE, json={"film": "a" * 32, "chanson": c_id, "debut_s": 5.17})
    assert r.status_code == 200, r.text
    assert vus == [(b"A", b"SON", 5.17, 0.3)]
    assert r.json()["video"]["musique"] == {"chanson": c_id, "debut_s": 5.17, "volume": 0.3}
    for corps, code in (({"chanson": "e" * 32}, 404), ({"film": "e" * 32}, 404), ({"volume": 2}, 400)):
        base = {"film": "a" * 32, "chanson": c_id, "debut_s": 1}
        assert c.post("/video-h3/musique", headers=CLE, json=dict(base, **corps)).status_code == code


def test_un_scenario_a_deux_pose_la_musique_des_le_plan_voulu(h3, monkeypatch):
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    v.fiche_poser_image(james, "face", PNG)
    c_id = "c" * 32
    monkeypatch.setattr(h3, "_chansons_pretes", lambda: [{"id": c_id, "titre": "Jazz", "cree_a": 0}])
    plans = [{"image_paroles": "James demande « Is this seat taken? »", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Léa répond « Non. »", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Ils marchent", "ambiance": "", "enchainement": "coupe"}]
    corps = {"plans": plans, "fiches": [lea, james], "langues": {lea: "French", james: "English"},
             "musique": "Piano", "musique_chanson": c_id, "musique_a_partir_du_plan": 2, "longueur": 124}
    c = client(h3)
    for autre, message in (({"musique_chanson": "e" * 32}, "musique"), ({"musique_a_partir_du_plan": 4}, "plans")):
        r = c.post("/video-h3/scenario/tourner", headers=CLE, json=dict(corps, **autre))
        assert r.status_code == 400 and message in r.json()["detail"]

    tournes = []

    def tourner(jid, *a):
        job = h3.read_job(jid)
        tournes.append(job["video"])
        job["video"]["secondes"] = round(5.17 * len(tournes), 2)   # la chaine recollee
        job["status"] = "succeeded"
        h3.write_job(jid, job)

    monkeypatch.setattr(h3, "run_video_h3", tourner)
    poses = []
    monkeypatch.setattr(h3, "_mettre_musique", lambda *a: poses.append(a) or "e" * 32)
    fils, vrai = [], h3.run_scenario_h3
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    r = c.post("/video-h3/scenario/tourner", headers=CLE, json=corps)
    assert r.status_code == 200, r.text
    vrai(*fils[0])
    sc = v.scenario_lire(r.json()["id"])
    assert sc["etat"] == "réussi" and len(tournes) == 3
    # Chaque plan porte les deux personnages ; H3 ne fait aucune musique, elle est posée une fois.
    for vid in tournes:
        assert vid["invite"].startswith("subject_definitions: <Subject 1> is the person in <Picture 1>. "
                                        "<Subject 2> is the person in <Picture 2>.")
        assert vid["invite"].endswith("non_diegetic_music: N/A") and "Piano" not in vid["invite"]
    assert "<Subject 2> (S1) demande <d>[English] Is this seat taken?</d>" in tournes[0]["invite"]
    assert "<Subject 1> (S1) répond <d>[French] Non.</d>" in tournes[1]["invite"]
    # Le départ se compte en images (124 à la fin du plan 1), pas en secondes arrondies.
    assert poses == [(sc["travaux"][2], c_id, pytest.approx(124 / 24), 0.3)]
    assert sc["fins_images"] == [124, 248, 372]
    assert sc["film"] == "e" * 32 and sc["film_sans_musique"] == sc["travaux"][2]
    assert sc["fiches"] == [lea, james] and sc["musique"]["a_partir_du_plan"] == 2


# --- 11. Juger, corriger, rejouer un scénario tourné (28/09) ---

def test_le_jugement_se_lit_en_numero_d_image_et_l_heure_se_calcule_ici(h3):
    v = h3.video_h3
    assert "Image 1 shows Léa" in v.consigne_jugement(["Léa", "James"])
    rep = ('```json\n{"verdict": "defaut", "defauts": [{"image": 9, "quoi": "Léa porte une veste grise"}, '
           '{"image": 40, "quoi": "hors planche"}, {"image": "x", "quoi": "illisible"}]}\n```')
    assert v.lire_jugement(rep, 5.17, 11) == {"verdict": "defaut",
                                              "defauts": [{"t_s": 9.2, "quoi": "Léa porte une veste grise"}]}
    with pytest.raises(ValueError, match="pas pu être lu"):
        v.lire_jugement("Tout va bien.", 0, 11)


def test_la_correction_garde_chaque_replique_a_sa_place(h3):
    v = h3.video_h3
    plans = [{"image_paroles": "Léa entre.", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Léa dit « Bonjour. »", "ambiance": "", "enchainement": "coupe"}]
    bon = json.dumps([{"image_paroles": "Léa, seule, entre.", "ambiance": "", "enchainement": "suite"},
                      {"image_paroles": "Léa, manteau rouge, dit « Bonjour. »", "ambiance": ""}], ensure_ascii=False)
    corriges = v.lire_correction(bon, plans)
    assert [p["enchainement"] for p in corriges] == ["coupe", "coupe"]   # l'enchaînement ne bouge pas
    assert corriges[1]["image_paroles"] == "Léa, manteau rouge, dit « Bonjour. »"
    deplace = json.dumps([{"image_paroles": "Léa entre et dit « Bonjour. »", "ambiance": ""},
                          {"image_paroles": "Léa sourit.", "ambiance": ""}], ensure_ascii=False)
    with pytest.raises(ValueError, match="déplacé"):
        v.lire_correction(deplace, plans)
    with pytest.raises(ValueError, match="nombre de plans"):
        v.lire_correction(json.dumps(plans[:1], ensure_ascii=False), plans)


def test_seuls_les_plans_changes_ou_coches_sont_retournes(h3):
    v = h3.video_h3
    p = [{"image_paroles": t, "ambiance": "", "enchainement": e}
         for t, e in (("a", "coupe"), ("b", "coupe"), ("c", "suite"), ("d", "coupe"))]
    change = [dict(p[0]), dict(p[1], image_paroles="b, seule"), dict(p[2]), dict(p[3])]
    # Le plan 3 est une suite du plan 2 retourné : il repart de sa nouvelle dernière image.
    assert v.plans_a_reprendre(p, change) == [0, 3]
    assert v.plans_a_reprendre(p, p, retourner={4}) == [0, 1, 2]


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_planche_et_reprise_d_un_plan(h3, tmp_path):
    film = tmp_path / "film.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=64x48:r=24",
                    "-f", "lavfi", "-i", "sine=f=440:r=48000", "-frames:v", "96", "-t", "4",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(film)], check=True)
    m = h3.montage
    png, nombre = m.planche(film.read_bytes(), 1.0, 2.5)
    assert png.startswith(b"\x89PNG") and nombre == 5
    extrait = tmp_path / "extrait.mp4"
    extrait.write_bytes(m.extraire(film.read_bytes(), 24, 72))
    assert m.images(extrait) == 48
    flux = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                           str(extrait)], capture_output=True, text=True).stdout.split()
    assert flux == ["video", "audio"]
    with pytest.raises(m.MontageImpossible, match="vide"):
        m.extraire(film.read_bytes(), 10, 10)


def _scenario_tourne(h3, monkeypatch, tmp_path):
    """Un scénario à deux, réussi, de trois plans de 124 images, avec sa musique."""
    v = h3.video_h3
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    v.fiche_poser_image(james, "face", PNG)
    film = tmp_path / "sans.mp4"
    film.write_bytes(b"FILM")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: film if jid else None)
    plans = [{"image_paroles": "James demande « Is this seat taken? »", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Léa répond « Non. »", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Ils marchent", "ambiance": "", "enchainement": "coupe"}]
    sid = "5" * 32
    v.scenario_ecrire({"id": sid, "etat": "réussi", "erreur": "", "plans": plans, "travaux": ["1" * 32] * 3,
                       "fins_images": [124, 248, 372], "film": "f" * 32, "film_sans_musique": "e" * 32,
                       "fiche": lea, "fiches": [lea, james],
                       "reglages": {"fiche": None, "fiches": [lea, james], "langues": {lea: "French",
                                    james: "English"}, "langue": "French", "musique": "", "longueur": 124,
                                    "graine": 2809},
                       "musique": {"chanson": "c" * 32, "a_partir_du_plan": 2}})
    monkeypatch.setattr(h3, "_chansons_pretes", lambda: [{"id": "c" * 32, "titre": "Jazz", "cree_a": 0}])
    return sid, plans


def test_juger_montre_chaque_plan_et_les_fiches_au_chat(h3, monkeypatch, tmp_path):
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    planches = []
    monkeypatch.setattr(h3.montage, "planche", lambda film, debut, duree: planches.append(
        (film, round(debut, 3), round(duree, 3))) or (b"\x89PNG", 11))
    vu = {}
    rep = {"choices": [{"message": {"content": '{"verdict": "defaut", "defauts": [{"image": 9, "quoi": "veste grise"}]}'}}]}
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(200, rep, vu))
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: pytest.fail("rien ne se loue"))
    # Le juge lit l'histoire du scénario INITIAL, pas le texte corrigé depuis.
    initiaux = [dict(p) for p in plans]
    initiaux[2]["image_paroles"] = "Léa et James marchent, puis James dit « Thank you. »"
    h3.video_h3.scenario_noter(sid, plans_initiaux=initiaux)
    r = client(h3).post(f"/video-h3/scenario/{sid}/juger", headers=CLE)
    assert r.status_code == 200, r.text
    # Le film SANS musique, découpé plan par plan aux images notées.
    assert planches == [(b"FILM", 0.0, 5.167), (b"FILM", 5.167, 5.167), (b"FILM", 10.333, 5.167)]
    contenu = vu["json"]["messages"][0]["content"]
    assert vu["json"]["model"] == "free-ai-max"   # « Auto » manquait les défauts le 28/09
    assert contenu[0]["type"] == "text" and "Image 1 shows Léa" in contenu[0]["text"]
    # Le texte du plan jugé (le dernier) part aussi : la vidéo doit faire ce qu'il dit, dans l'ordre.
    assert "Léa et James marchent, puis James dit « Thank you. »" in contenu[0]["text"]
    assert plans[2]["image_paroles"] not in contenu[0]["text"]
    assert "not in this order" in contenu[0]["text"]
    assert [c["type"] for c in contenu[1:]] == ["image_url"] * 3   # deux fiches, puis la planche
    assert r.json()["jugement"][1] == {"plan": 2, "verdict": "defaut",
                                       "defauts": [{"t_s": 9.2, "quoi": "veste grise"}]}
    assert client(h3).post("/video-h3/scenario/" + "9" * 32 + "/juger", headers=CLE).status_code == 404


def test_corriger_part_des_retours_et_du_jugement(h3, monkeypatch, tmp_path):
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    c = client(h3)
    assert c.post(f"/video-h3/scenario/{sid}/corriger", headers=CLE, json={}).status_code == 400
    corriges = [dict(plans[0]), dict(plans[1], image_paroles="Léa, en manteau rouge, répond « Non. »"),
                dict(plans[2])]
    vus = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [json.dumps(corriges, ensure_ascii=False), '{"etats": [], "problemes": []}'], vus))
    # Seuls les défauts gardés par le propriétaire partent (la fausse alerte décochée, non).
    r = c.post(f"/video-h3/scenario/{sid}/corriger", headers=CLE, json={
        "retours": "Ils doivent marcher.", "defauts": [{"plan": 2, "t_s": 9.2, "quoi": "veste grise"}]})
    assert r.status_code == 200, r.text
    assert "Ils doivent marcher." in r.json()["retours"] and "Shot 2, at 9.2 s: veste grise" in r.json()["retours"]
    assert r.json()["plans"][1]["image_paroles"] == "Léa, en manteau rouge, répond « Non. »"
    assert "veste grise" in vus[0]["messages"][0]["content"]
    assert "never what happens" in vus[0]["messages"][0]["content"]
    # Puis le contrôle de continuité, sur l'histoire du scénario initial.
    assert vus[1]["model"] == "free-ai-max" and plans[0]["image_paroles"] in vus[1]["messages"][0]["content"]
    assert r.json()["continuite"]["ok"] is True
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(
        200, {"choices": [{"message": {"content": json.dumps(corriges, ensure_ascii=False)}}]}, {}))
    # Le 28/09, dix défauts de 150 caractères pour un seul plan ont fait « Retours trop longs » :
    # trois par plan partent, le reste est laissé.
    bavard = [{"plan": 1, "t_s": k / 2, "quoi": "deux femmes identiques en manteau rouge " * 4} for k in range(10)]
    r = c.post(f"/video-h3/scenario/{sid}/corriger", headers=CLE, json={"defauts": bavard + [
        {"plan": 2, "t_s": 9.2, "quoi": "veste grise"}]})
    assert r.status_code == 200, r.text
    assert r.json()["retours"].count("Shot 1,") == 3 and "Shot 2, at 9.2 s: veste grise" in r.json()["retours"]
    assert c.post(f"/video-h3/scenario/{sid}/corriger", headers=CLE,
                  json={"retours": "x" * 2001}).status_code == 400


def test_une_correction_qui_casse_la_continuite_est_refaite_une_fois(h3, monkeypatch, tmp_path):
    # Le 28/09 : pour effacer un défaut d'image, la correction a fait asseoir James
    # avant que Léa l'y invite. Le contrôle le voit ; un second essai lui est demandé.
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    # Les plans du scénario ont déjà été abîmés par une correction : la correction
    # reçoit aussi l'histoire du scénario INITIAL, à chaque essai.
    initiaux = [dict(p) for p in plans]
    initiaux[1]["image_paroles"] = "Léa répond « Non. », puis James s'assoit."
    h3.video_h3.scenario_noter(sid, plans_initiaux=initiaux)
    casse =[dict(plans[0]), dict(plans[1], image_paroles="James est déjà assis. Léa répond « Non. »"), dict(plans[2])]
    bon = [dict(plans[0]), dict(plans[1], image_paroles="Léa répond « Non. » James s'assoit."), dict(plans[2])]
    probleme = '{"problemes": [{"plan": 2, "quoi": "James est assis avant d\'être invité"}]}'
    vus = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [json.dumps(casse, ensure_ascii=False), probleme, json.dumps(bon, ensure_ascii=False), '{"problemes": []}'],
        vus))
    r = client(h3).post(f"/video-h3/scenario/{sid}/corriger", headers=CLE, json={"retours": "Léa disparaît."})
    assert r.status_code == 200, r.text
    assert len(vus) == 4 and "James est assis avant d'être invité" in vus[2]["messages"][0]["content"]
    for essai in (vus[0], vus[2]):
        assert "it must stay true" in essai["messages"][0]["content"]
        assert "lines of dialogue included" in essai["messages"][0]["content"]
        assert initiaux[1]["image_paroles"] in essai["messages"][0]["content"]
    assert r.json()["plans"][1]["image_paroles"] == "Léa répond « Non. » James s'assoit."
    assert r.json()["continuite"]["ok"] is True
    # Toujours cassée au second essai : rendue telle quelle, le problème affiché (la page n'en rejoue rien).
    vus.clear()
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [json.dumps(casse, ensure_ascii=False), probleme] * 2, vus))
    r = client(h3).post(f"/video-h3/scenario/{sid}/corriger", headers=CLE, json={"retours": "Léa disparaît."})
    assert r.status_code == 200 and len(vus) == 4
    assert r.json()["continuite"] == {"ok": False, "etats": [], "problemes": [
        {"plan": 2, "quoi": "James est assis avant d'être invité"}]}


def test_la_continuite_se_lit_et_ne_garde_que_les_plans_du_film(h3):
    v = h3.video_h3
    c = v.lire_continuite('Voici : {"etats": [{"plan": 1, "debut": "a", "fin": "b"}], "problemes": '
                          '[{"plan": 2, "quoi": "  assis   trop tôt "}, {"plan": 9, "quoi": "hors film"}, {"plan": 1}]}', 3)
    assert c == {"ok": False, "etats": [{"plan": 1, "debut": "a", "fin": "b"}],
                 "problemes": [{"plan": 2, "quoi": "assis trop tôt"}]}
    assert v.lire_continuite('{"problemes": []}', 3)["ok"] is True
    with pytest.raises(ValueError, match="pas pu être lu"):
        v.lire_continuite("tout va bien", 3)
    consigne = v.consigne_continuite([{"image_paroles": "Léa s'assoit.", "ambiance": "x", "enchainement": "coupe"}],
                                     "Léa arrive puis s'assoit.")
    assert "Léa arrive puis s'assoit." in consigne and "after what causes it" in consigne and '"x"' not in consigne
    # Le 28/09, une correction a retiré « James s'assoit » sans que le contrôle le relève.
    assert "none missing" in consigne


def test_rejouer_ne_retourne_que_le_plan_change_et_repose_la_musique(h3, monkeypatch, tmp_path):
    v = h3.video_h3
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    v.scenario_ecrire(dict(v.scenario_lire(sid), reglages=dict(v.scenario_lire(sid)["reglages"], definition="768p")))
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    extraits = []
    monkeypatch.setattr(h3.montage, "extraire", lambda f, a, b: extraits.append((a, b)) or b"X%d" % a)
    monkeypatch.setattr(h3.montage, "recoller_son", lambda a, b, retirer: a + b)
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 124)
    tournes = []

    def tourner(jid, code, precedent, retirer):
        job = h3.read_job(jid)
        tournes.append((precedent, job["video"]))
        job["video"]["secondes"] = round(248 / 24, 2)   # la chaîne : plan 1 repris + plan 2 neuf
        job["status"] = "succeeded"
        h3.write_job(jid, job)

    monkeypatch.setattr(h3, "run_video_h3", tourner)
    poses = []
    monkeypatch.setattr(h3, "_mettre_musique", lambda *a: poses.append(a) or "d" * 32)
    fils, vrai = [], h3.run_scenario_h3
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    c = client(h3)
    r = c.post(f"/video-h3/scenario/{sid}/rejouer", headers=CLE, json={"plans": plans})
    assert r.status_code == 400 and "Aucun plan n'a changé" in r.json()["detail"]
    nouveaux = [dict(plans[0]), dict(plans[1], image_paroles="Léa, en manteau rouge, répond « Non. »"),
                dict(plans[2])]
    r = c.post(f"/video-h3/scenario/{sid}/rejouer", headers=CLE, json={"plans": nouveaux})
    assert r.status_code == 200, r.text
    assert r.json()["repris"] == [1, 3] and r.json()["parent"] == sid
    assert r.json()["plans_initiaux"] == plans
    vrai(*fils[0])
    sc = v.scenario_lire(r.json()["id"])
    assert sc["etat"] == "réussi", sc["erreur"]
    assert extraits == [(0, 124), (248, 372)]   # plans 1 et 3 découpés dans l'ancien film
    (precedent, video), = tournes                 # un seul plan loué
    assert h3.read_job(precedent)["video"]["mode"] == "reprise"   # il se recolle au plan 1 repris
    assert video["graine"] != 2809 and "manteau rouge" in video["invite"]
    assert video["taille"] == "1344x768"   # le plan neuf garde la définition du scénario
    assert sc["fins_images"] == [124, 248, 372]
    assert poses and poses[0][1:] == ("c" * 32, pytest.approx(124 / 24), 0.3)
    assert sc["film"] == "d" * 32


def test_un_seul_rejeu_a_la_fois_par_scenario(h3, monkeypatch, tmp_path):
    # Le 28/09, un second clic pendant le premier rejeu a payé deux fois le même plan.
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    _autoriser(h3)
    h3.video_h3.scenario_ecrire({"id": "6" * 32, "etat": "en cours", "parent": sid, "plans": plans, "travaux": []})
    monkeypatch.setattr(h3, "_SCENARIOS_VIVANTS", {"6" * 32})
    r = client(h3).post(f"/video-h3/scenario/{sid}/rejouer", headers=CLE, json={"plans": plans, "retourner": [2]})
    assert r.status_code == 409 and "tourne déjà" in r.json()["detail"]


def test_la_page_propose_juger_corriger_rejouer_et_la_musique(h3):
    html = client(h3).get("/video-h3").text
    # Un menu « Que faire ? » et un seul bouton ; un bandeau avec chronomètre verrouille les
    # commandes pendant une action (le 28/09, un second clic a payé deux fois le même plan).
    for morceau in ('id="suite_action"', 'value="juger"', 'value="corriger"', 'value="rejouer"', 'id="suite_lancer"',
                    'id="scenario_occupe"', "function verrouiller", "occupe(", 'id="suite_pause"', 'id="retours"',
                    'id="scenario_choix"', "/video-h3/scenarios", "function diffGras", 'id="musique_poser"',
                    "/video-h3/musique", "Retourner ce plan même inchangé", "defauts: DEFAUTS.filter",
                    'value="auto"', "function texteContinuite", "c.continuite.ok === false",
                    # Pause avant de payer : les défauts gardés seuls font rejouer.
                    'id="auto_sans_arret"', 'id="scenario_auto_payer"', "await attendreAccord()",
                    "gardes.map(d => d.plan)"):
        assert morceau in html


def test_le_routeur_envoie_l_image_de_depart_a_google(routeur, monkeypatch):
    vu = {}
    reponse = {"candidates": [{"content": {"parts": [{"inlineData": {"data": PNG, "mimeType": "image/png"}}]}}]}
    monkeypatch.setattr(routeur.httpx, "AsyncClient", _FauxRouteur(200, reponse, vu))
    c = TestClient(routeur.app)
    entete = {"Authorization": "Bearer cle-interne-de-test"}
    r = c.post("/v1/images/generations", headers=entete,
               json={"prompt": "la même, de profil", "image_reference": "data:image/jpeg;base64," + JPG})
    assert r.status_code == 200
    assert vu["json"]["contents"][0]["parts"] == [
        {"inlineData": {"mimeType": "image/jpeg", "data": JPG}}, {"text": "la même, de profil"}]
    r = c.post("/v1/images/generations", headers=entete, json={"prompt": "x", "image_reference": "http://ailleurs"})
    assert r.status_code == 400
    vu.clear()
    c.post("/v1/images/generations", headers=entete, json={"prompt": "sans départ"})
    assert vu["json"]["contents"][0]["parts"] == [{"text": "sans départ"}]
