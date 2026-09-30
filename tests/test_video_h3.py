"""Vidéo H3 (sandbox-manager/video_h3.py) : ce qui se vérifie sans louer de carte.

Le clip lui-même a tourné hors du Studio le 27/09/2026 (PLAN.md, 18.6 et 18.9).
Ici : la demande, le graphe, la garde de licence, les refus avant location, et
que rien de ComfyUI (GPL-3.0) n'est importé par le code du Studio.
"""
import ast
import asyncio
import base64
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parents[1]
CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 64).decode()
PDF = base64.b64encode(b"%PDF-1.4 copie").decode()
CADRE = b"\x89PNG\r\n\x1a\n" + b"\1" * 64   # une image recadrée, pour les tests


@pytest.fixture
def h3(sandbox, monkeypatch, tmp_path):
    v = sandbox.video_h3
    monkeypatch.setattr(v, "DOSSIER_AUTORISATION", tmp_path / "h3-autorisation")
    monkeypatch.setattr(v, "FICHE_AUTORISATION", tmp_path / "h3-autorisation" / "fiche.json")
    monkeypatch.setattr(v, "FICHE_POIDS", tmp_path / "h3-poids.json")
    monkeypatch.setattr(v, "DOSSIER_FICHES", tmp_path / "h3-fiches")
    monkeypatch.setattr(v, "DOSSIER_SCENARIOS", tmp_path / "h3-scenarios")
    monkeypatch.setattr(v, "DOSSIER_DEPARTS", tmp_path / "h3-departs")
    monkeypatch.setattr(sandbox.budget_modal, "FICHIER", tmp_path / "modal-budget.json")
    monkeypatch.setattr(sandbox.budget_modal, "_releve_reel", lambda: None)
    monkeypatch.setenv("VIDEO_H3_ACTIF", "true")
    return sandbox


@pytest.fixture
def sans_traduction(h3, monkeypatch):
    """Les tests du découpage écrits avant la règle 0 (30/09) : l'histoire part telle
    quelle, la traduction a ses propres tests."""
    async def telle_quelle(histoire):
        return histoire
    monkeypatch.setattr(h3, "_histoire_en_anglais", telle_quelle)


@pytest.fixture
def sans_regles(h3, monkeypatch):
    """Les tests du tournage et du juge écrits avant les règles numérotées (30/09) :
    ni garde, ni contrôle de la dernière image, ni règles 10 à 12 ; elles ont leurs tests."""
    async def aucune_garde(plans, commun, forcer, tournes=None):
        return []

    async def aucune_regle_clip(*a, **k):
        return {}
    monkeypatch.setattr(h3, "_garde_des_regles", aucune_garde)
    monkeypatch.setattr(h3, "_controle_derniere_image", lambda sid, i, image: None)
    monkeypatch.setattr(h3, "_regles_clip", aucune_regle_clip)


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
    ("post", "/video-h3/scenario/verifier"),
    ("get", "/video-h3/scenario/" + "a" * 32), ("post", "/video-h3/musique"), ("get", "/video-h3/scenarios"),
    ("post", "/video-h3/scenario/" + "a" * 32 + "/juger"), ("post", "/video-h3/scenario/" + "a" * 32 + "/corriger"),
    ("post", "/video-h3/scenario/" + "a" * 32 + "/rejouer"), ("post", "/video-h3/depart/" + "a" * 24 + "/comparer"),
    ("post", "/video-h3/visage/comparer"), ("post", "/video-h3/fiches/" + "a" * 12 + "/planche"),
    ("delete", "/video-h3/fiches/" + "a" * 12 + "/planche"),
    ("get", "/video-h3/agrandir/prix?job=" + "a" * 32), ("post", "/video-h3/agrandir"),
    ("get", "/video-h3/visages/prix?job=" + "a" * 32), ("post", "/video-h3/visages"),
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


def test_l_accueil_du_sandbox_mene_a_h3_selon_le_reglage(h3, monkeypatch):
    c = client(h3)
    avec = c.get("/").text
    monkeypatch.delenv("VIDEO_H3_ACTIF")
    sans = c.get("/").text
    assert "href='/video-h3'" in avec and "/video-h3" not in sans
    assert "__H3__" not in avec + sans and "href='/video'" in sans


def test_la_page_se_parcourt_par_un_menu(h3):
    page = client(h3).get("/video-h3", headers=CLE).text
    menu = re.search(r'<select id="section_choix"[^>]*>(.*?)</select>', page, re.S).group(1)
    parties = re.findall(r'<option value="(\w+)"', menu)
    assert parties == ["clip", "casting", "montage_bloc", "musique_bloc", "reglages"]
    for p in parties:
        assert re.search(r'class="[^"]*\bsection\b[^"]*" id="%s"' % p, page), p
    assert page.count('class="bloc section"') + page.count('class="section"') == len(parties)
    assert 'href="http://localhost:8000/studio"' in page
    # Le verrou d'un tournage couvre aussi la musique, sortie du bloc du scénario.
    assert "#musique_bloc button" in page
    # Un scénario tourné est jugé de lui-même (gratuit).
    assert "if (SCENARIO_TOURNE === d.id) await actionJuger();" in page
    # Aucun lecteur dans une partie repliée : le 29/09, le film tourné y était caché.
    replies = "".join(re.findall(r"<details.*?</details>", page, re.S))
    assert page.count("<video") == 3 and "<video" not in replies
    # Les réglages rares sont repliés, pas retirés.
    for i in ("definition", "coupe", "graine", "ambiance", "musique_fondu", "clips_liste"):
        assert 'id="%s"' % i in page, i


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
    monkeypatch.setattr(h3.video_h3, "a_traduire", lambda p: False)   # la traduction a ses tests
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

    async def post(self, url, headers=None, json=None, files=None, data=None):
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


class _FauxRouteurOreille(_FauxRouteur):
    """Le chat rend `chat` ; le Whisper du routeur rend `entendus` l'un après l'autre."""

    def __init__(self, chat, entendus, ecoutes, vu):
        super().__init__(200, None, vu)
        self.chat, self.entendus, self.ecoutes = chat, list(entendus), ecoutes

    async def post(self, url, headers=None, json=None, files=None, data=None):
        if url.endswith("/v1/audio/transcriptions"):
            self.ecoutes.append((files["file"][1], data))
            e = self.entendus.pop(0)
            self.corps = e if isinstance(e, dict) else {"text": e}
        else:
            self.vu.setdefault("chats", []).append(json)
            self.corps = {"choices": [{"message": {"content": self.chat}}]}
        return await super().post(url, headers, json)


def test_l_image_du_studio_passe_par_le_routeur(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    vu = {}
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(200, {"data": [{"url": "data:image/png;base64," + PNG}]}, vu))
    r = client(h3).post("/video-h3/image", headers=CLE, json={"texte": "  une rue  mouillée "})
    assert r.status_code == 200 and r.json()["image"].startswith("data:image/png;base64,")
    assert vu["url"].endswith("/v1/images/generations")
    # Les figurants restent loin : le modèle vidéo perd ce qui est proche (28/09).
    assert vu["json"] == {"prompt": "une rue mouillée " + h3.video_h3.FIGURANTS_IMAGE, "n": 1, "size": "1664x960"}
    assert "jamais au premier plan" in h3.video_h3.FIGURANTS_IMAGE
    assert r.json()["texte"] == "une rue mouillée"
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


def test_le_client_fait_refaire_l_image_en_disant_ce_qui_change(h3, monkeypatch):
    v = h3.video_h3
    assert v.texte_image(" une rue ", [" plus  de pluie ", "", "un nom lisible"]) == (
        "une rue Améliorations demandées : plus de pluie ; un nom lisible.")
    with pytest.raises(ValueError):
        v.texte_image("x", "pas une liste")
    with pytest.raises(ValueError, match="Dix"):
        v.texte_image("x", ["a"] * 11)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    vu = {}
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(200, {"data": [{"url": "data:image/png;base64," + PNG}]}, vu))
    r = client(h3).post("/video-h3/image", headers=CLE, json={"texte": "une rue", "ameliorations": ["la nuit"]})
    assert r.status_code == 200
    assert r.json()["texte"] == "une rue Améliorations demandées : la nuit."
    assert vu["json"]["prompt"] == r.json()["texte"] + " " + h3.video_h3.FIGURANTS_IMAGE
    html = client(h3).get("/video-h3").text
    for nom in ("premiere", "derniere"):
        assert 'id="amelioration_' + nom + '"' in html and 'id="ameliorer_' + nom + '"' in html


def test_la_description_de_l_image_creee_passe_a_h3(h3):
    v = h3.video_h3
    p = v.preparer(demande(mode="premiere", images=[PNG], description_premiere="Un café bondé",
                           description_derniere="ignorée : pas de dernière image dans ce mode"))
    invite = p["resume_public"]["invite"]
    assert invite.startswith("First frame: Un café bondé. ") and "ignorée" not in invite
    p = v.preparer(demande(mode="premiere_derniere", images=[PNG, PNG],
                           description_premiere="Début.", description_derniere="Fin."))
    assert p["resume_public"]["invite"].startswith("First frame: Début. Last frame: Fin. ")
    # Image téléversée (sans description) ou autre mode : rien n'est ajouté.
    assert "frame:" not in v.preparer(demande(mode="premiere", images=[PNG]))["resume_public"]["invite"]
    assert "frame:" not in v.preparer(demande(description_premiere="x"))["resume_public"]["invite"]
    html = client(h3).get("/video-h3").text
    assert "description_premiere: m === " in html and "description_derniere: m === " in html


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


def test_une_suite_en_references_epingle_les_22_dernieres_images_et_leur_son(h3, monkeypatch):
    """Film campus, 30/09 : le plan 2 partait en plan large après le plan moyen du plan 1 —
    le nœud Références n'a pas d'entrée first_frame. MiniMaxH3AddGuide épingle la fin du
    plan précédent, image et son, à l'image 0 (PR Comfy-Org/ComfyUI #15439)."""
    v = h3.video_h3
    monkeypatch.delenv("H3_MOTION_CONTEXT", raising=False)
    lea = v.fiche_creer("Léa", "x")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    d = demande(mode="references", fiches=[lea], image_paroles="Léa dit « Oui. »", longueur=124)
    plan = v.preparer_prolonger(d, _clip_reussi(h3), PNG, fin_b64="UkFDQ09SRA==")
    dem, g = plan["demande"], plan["demande"]["graphe"]
    assert g["80"] == {"class_type": "LoadVideo", "inputs": {"file": "raccord.mp4"}}
    assert g["81"]["class_type"] == "GetVideoComponents" and g["81"]["inputs"] == {"video": ["80", 0]}
    assert g["11"]["class_type"] == "MiniMaxH3AddGuide"
    assert g["11"]["inputs"] == {"positive": ["10", 0], "vae": ["4", 0], "audio_vae": ["5", 0], "latent": ["10", 1],
                                 "image": ["81", 0], "audio": ["81", 1], "frame_idx": 0}
    assert g["13"]["inputs"]["conditioning"] == ["11", 0]   # le guide passe par le raccord
    assert g["10"]["class_type"] == "MiniMaxH3ReferenceToVideo"   # les fiches restent
    assert dem["videos"] == {"raccord.mp4": "UkFDQ09SRA=="}
    assert set(v.NOEUDS_RACCORD) <= set(dem["classes"])
    # Plan 4 du film campus (30/09) : H3 a coupé vers le cadrage du texte après les 22
    # images. AddGuide ne passe rien au texte (« is not visible to the text encoder ») :
    # la fin part aussi en <Video 1>, et le texte la dit continuée sans coupe, en
    # « video continuation » (guide de MiniMax). Elle remplace la dernière image en <Picture N>.
    assert g["10"]["inputs"]["ref_videos.ref_video_0"] == ["81", 0]
    assert not any(k.startswith("ref_video_audios") for k in g["10"]["inputs"])   # les <Audio j> ne bougent pas
    assert list(dem["images"]) == ["ref_0.png"]
    invite = plan["resume_public"]["invite"]
    assert "<Video 1> is the end of the previous shot." in invite
    assert "summary: [video continuation + reference generation] The target video is a single shot with " \
           "<Subject 1>, continuing <Video 1> without a cut. " in invite
    assert v.SUITE_GARDE in invite and "<Picture 2>" not in invite
    assert "detailed_description: [Shot 1] " + v.SUITE_DEBUT in invite
    # 17 images de plus, pour que les 22 reprises ne raccourcissent pas le plan ; retirées au recollage.
    assert plan["resume_public"]["images"] == 141 and dem["longueur"] == 141
    assert plan["resume_public"]["voie"] == "raccord" and v.images_a_retirer(plan) == 22
    assert "22 dernières images" in plan["resume_public"]["mode_titre"]
    # Le script écrit la vidéo du raccord dans l'entrée de ComfyUI.
    assert '**(D.get("videos") or {})' in v.construire_script(dem)
    # Au bout de la grille, pas de pas de plus.
    assert v.longueur_avec_raccord(v.LONGUEURS[-1]) == v.LONGUEURS[-1]
    # Sans fin fournie, rien ne change : la dernière image, 1 image retirée.
    plan = v.preparer_prolonger(d, _clip_reussi(h3), PNG)
    assert "11" not in plan["demande"]["graphe"] and v.images_a_retirer(plan) == 1


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_la_fin_d_un_film_rend_ses_22_dernieres_images_et_son_son(h3, tmp_path):
    m = h3.montage
    film = tmp_path / "film.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(film)], check=True)
    fin = tmp_path / "fin.mp4"
    fin.write_bytes(m.fin(film.read_bytes(), 22))
    assert m.images(fin) == 22
    son = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", str(fin)], capture_output=True, text=True).stdout.strip()
    assert son == "audio"
    with pytest.raises(m.MontageImpossible, match="moins que"):
        m.fin(film.read_bytes(), 60)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_un_plan_recolle_prend_le_niveau_sonore_du_film(h3, tmp_path):
    """Film campus, 30/09 : le plan 5, une coupe, 5 à 6 dB sous les quatre premiers.
    « applique au studio de façon systématique » : chaque recollage harmonise."""
    m = h3.montage

    def clip(nom, volume, frequence=440):
        f = tmp_path / nom
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=%d" % frequence, "-t", "3", "-af", "volume=%s" % volume,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(f)], check=True)
        return f
    fort, faible = clip("fort.mp4", "0.5"), clip("faible.mp4", "0.05", 660)
    assert m.sonie(fort) - m.sonie(faible) == pytest.approx(20, abs=1)
    assert m.gain_de_suite(fort, faible) == m.ECART_SONIE_MAX_DB   # 20 dB d'écart, 12 au plus
    moyen = clip("moyen.mp4", "0.25", 660)   # 6 dB sous le fort : comblés entièrement
    assert m.gain_de_suite(fort, moyen) == pytest.approx(m.sonie(fort) - m.sonie(moyen), abs=0.01)
    film = tmp_path / "film.mp4"
    film.write_bytes(m.recoller_son(fort.read_bytes(), faible.read_bytes(), 0))
    avant, apres = m.sonie(fort), m.sonie(film, 3.2)
    # Au plus 12 dB de gain : le plan faible remonte de 12 dB, pas de 20.
    assert apres == pytest.approx(m.sonie(faible) + m.ECART_SONIE_MAX_DB, abs=1) and apres < avant
    # Deux plans au même niveau : rien n'est touché.
    assert m.gain_de_suite(fort, clip("pareil.mp4", "0.5", 660)) == 0.0
    # Un plan muet ne se pousse pas.
    muet = clip("muet.mp4", "0")
    assert m.sonie(muet) is None and m.gain_de_suite(fort, muet) == 0.0


def test_une_suite_avec_fiches_garde_ses_sujets_et_part_de_la_derniere_image(h3, monkeypatch):
    """30/09 : une suite partait de la dernière image seule, en texte brut ; Marc y était
    réinventé, sa voix aussi. Elle garde maintenant ses fiches quand elles tiennent."""
    v = h3.video_h3
    monkeypatch.delenv("H3_MOTION_CONTEXT", raising=False)
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    v.fiche_poser_image(james, "face", PNG)
    d = demande(mode="references", fiches=[lea, james], langues={lea: "French", james: "English"},
                image_paroles="Léa regarde the James et dit « Oui. »")
    plan = v.preparer_prolonger(d, _clip_reussi(h3), PNG)
    invite = plan["resume_public"]["invite"]
    assert invite.startswith("subject_definitions: <Subject 1> is the person in <Picture 1>. "
                             "<Subject 2> is the person in <Picture 2>. ")
    # Forme du guide de MiniMax (ref-en.txt, 2.2, 3, 4.1, 5.3).
    assert "<Subject 2> is the person in <Picture 2>. <Picture 3> is the first frame of [Shot 1]. " in invite
    assert "summary: [reference generation + keyframe completion] The target video is a single shot with " \
           "<Subject 1> and <Subject 2>, beginning from <Picture 3>. " in invite
    assert "<Picture 3> ([Shot 1] first frame): fully_preserved - the shot begins exactly on <Picture 3>" in invite
    assert "detailed_description: [Shot 1] The shot begins from <Picture 3>. " in invite
    assert "<Subject 1> (S1) regarde <Subject 2> et dit <d>[French] Oui.</d>" in invite
    assert list(plan["demande"]["images"]) == ["ref_0.png", "ref_1.png", "ref_2.png"]
    assert plan["resume_public"]["voie"] == "image"
    # Sans fiche, rien ne change : la dernière image seule.
    seule = v.preparer_prolonger(demande(), _clip_reussi(h3, "d" * 32), PNG)
    assert list(seule["demande"]["images"]) == ["premiere.png"]


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
    monkeypatch.setattr(h3.montage, "fin", lambda octets, n: b"raccord")
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
                             "summary: [reference generation] The target video is a single shot with "
                             "<Subject 1>. retention_analysis: <Subject 1> (appears in [Shot 1]): "
                             "fully_preserved - the face, hair and clothing "
                             "of the person in <Picture 1>, <Picture 2> are retained, as one single person. "
                             "detailed_description: [Shot 1] Elle sourit")
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
    # Tous les modes : en « Première image », le français hors guillemets a été dit (28/09).
    assert v.a_traduire(p) and v.a_traduire(dict(p, mode="premiere"))
    assert not v.a_traduire({"mode": "premiere", "image_paroles": " "})
    d = {"mode": "premiere", "image_paroles": "Il dit « Hi. »", "description_premiere": "Une terrasse bondée"}
    assert '"description_premiere": "Une terrasse bondée"' in v.consigne_traduction(d)
    t = v.lire_traduction('{"image_paroles": "He says « Hi. »", "description_premiere": "A crowded terrace"}', d)
    assert t["description_premiere"] == "A crowded terrace"
    with pytest.raises(ValueError, match="perdu"):
        v.lire_traduction('{"image_paroles": "He says « Hi. »"}', d)
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
    # 28/09 (clip 1180fae1) : une case rendue encore en français passait.
    reste = ('{"image_paroles": "Léa marche sur l\'allée vers la caméra et sourit. Elle ne parle pas.", '
             '"ambiance": "x", "musique": ""}')
    with pytest.raises(ValueError, match="laissé du français"):
        v.lire_traduction(reste, dict(p, image_paroles="Léa marche sur l'allée vers la caméra et sourit. "
                                                       "Elle ne parle pas."))
    # Répliques balisées à la main : l'écoute les attend aussi (clip 841ec33e, 28/09).
    assert v.repliques("Elle dit « Salut » puis (S1) <d>[French] Bonjour !</d> et (S1) <d>[English] Nice "
                       "to meet you!</d>") == ["Salut", "Bonjour !", "Nice to meet you!"]
    # Les répliques françaises, elles, restent en français sans lever l'alarme.
    assert not v.reste_du_francais("She says (S1) <d>[French] Merci pour le colis et la carte !</d>")


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
    with pytest.raises(ValueError, match="« Deux cafés. » n'est pas dans le scénario"):
        v.lire_decoupage(invente, scenario)
    # Ponctuation ou majuscule changée : acceptée, et la réplique d'origine revient.
    retouche = '[{"image_paroles": "Elle dit « un café s\'il vous plaît »", "ambiance": "", "enchainement": "coupe"}]'
    assert "« Un café, s'il vous plaît. »" in v.lire_decoupage(retouche, scenario)[0]["image_paroles"]
    # Une longue réplique coupée en deux plans : acceptée si les morceaux la refont entière.
    long = "Tom dit « Bonjour Léa, tu viens avec nous ce soir ? »"
    coupee = ('[{"image_paroles": "Tom dit « Bonjour Léa, »", "ambiance": "", "enchainement": "coupe"}, '
              '{"image_paroles": "Il ajoute « tu viens avec nous ce soir ? »", "ambiance": "", "enchainement": "suite"}]')
    assert len(v.lire_decoupage(coupee, long)) == 2
    tronquee = '[{"image_paroles": "Tom dit « Bonjour Léa, »", "ambiance": "", "enchainement": "coupe"}]'
    with pytest.raises(ValueError, match="sans la garder entière"):
        v.lire_decoupage(tronquee, long)
    etiquete = '[{"image_paroles": "image_paroles: Plan moyen.", "ambiance": "ambiance : vent", "enchainement": "coupe"}]'
    lu = v.lire_decoupage(etiquete, "Plan moyen.")[0]
    assert (lu["image_paroles"], lu["ambiance"]) == ("Plan moyen.", "vent")
    vide = '[{"image_paroles": "Elle sourit « ».", "ambiance": "", "enchainement": "coupe"}]'
    assert v.lire_decoupage(vide, "Elle sourit.")[0]["image_paroles"] == "Elle sourit ."
    with pytest.raises(ValueError, match="pas pu être lu"):
        v.lire_decoupage("[]", scenario)
    trop = [{"image_paroles": "x", "ambiance": "", "enchainement": "coupe"}] * (v.SCENARIO_PLANS_MAX + 1)
    for mauvais, message in ((trop, "au plus"), ([{"image_paroles": " "}], "décrivez"),
                             ([{"image_paroles": "x", "enchainement": "fondu"}], "inconnu")):
        with pytest.raises(ValueError, match=message):
            v.verifier_plans(mauvais)


def test_le_relecteur_du_scenario_complet_corrige_avant_de_montrer_les_plans(h3, monkeypatch, sans_traduction):
    """29/09 : « rajoute un reviewer pour le scénario complet qui fera comme toi »."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    scenario = "Léa est seule à une table. Tom arrive, pose un livre et dit « Tiens. »"
    decoupe = json.dumps([
        {"image_paroles": "À gauche, Léa seule à une table ; le livre est sur la table.", "ambiance": "",
         "enchainement": "coupe"},
        {"image_paroles": "À droite, Tom pose le livre et dit « Tiens. »", "ambiance": "", "enchainement": "suite"}],
        ensure_ascii=False)
    probleme = '{"etats": [], "problemes": [{"plan": 1, "quoi": "Le livre est là avant que Tom le pose."}]}'
    corrige = json.dumps([
        {"image_paroles": "À gauche, Léa seule à une table vide.", "ambiance": "", "enchainement": "coupe"},
        {"image_paroles": "À droite, Tom arrive, pose le livre et dit « Tiens. »", "ambiance": "",
         "enchainement": "suite"}], ensure_ascii=False)
    vus = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [decoupe, probleme, corrige, '{"etats": [], "problemes": []}',
         '[{"n": 1, "language": "French", "emotion": null}]'], vus))
    r = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": scenario})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plans"][0]["image_paroles"] == "À gauche, Léa seule à une table vide."
    # 30/09 : la réplique reçoit sa marque de langue, posée par le Studio.
    assert d["plans"][1]["image_paroles"].endswith("« [French] Tiens. »")
    assert d["marques"] == {"demandees": 1, "sans_langue_ou_emotion": 1}
    assert d["relecture"] == {"trouves": [{"plan": 1, "quoi": "Le livre est là avant que Tom le pose."}],
                              "corrige": True}
    assert d["continuite"]["ok"] is True
    relecture = vus[1]["messages"][0]["content"]
    texte = relecture if isinstance(relecture, str) else relecture[0]["text"]
    for regle in ("script supervisor", "same place in the frame", "before it arrives in the story",
                  "placed and visible from the first shot", "quick gesture spread over several shots",
                  "elsewhere in the frame without walking to it", "an object appears twice",
                  "still moving at the end of a shot",
                  "camera stay on the same side"):
        assert regle in texte, regle
    assert "BEFORE shooting" in json.dumps(vus[2], ensure_ascii=False)


def test_le_relecteur_garde_le_texte_si_la_correction_ne_fait_pas_mieux(h3, monkeypatch, sans_traduction):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    scenario = "Léa lance le ballon vers le panier."
    decoupe = '[{"image_paroles": "Léa lance le ballon.", "ambiance": "", "enchainement": "coupe"}]'
    probleme = '{"etats": [], "problemes": [{"plan": 1, "quoi": "Le panier n\'est pas placé."}]}'
    pire = ('{"etats": [], "problemes": [{"plan": 1, "quoi": "Le panier n\'est pas placé."}, '
            '{"plan": 1, "quoi": "Le ballon n\'arrive nulle part."}]}')
    corrige = '[{"image_paroles": "Léa lance le ballon en l\'air.", "ambiance": "", "enchainement": "coupe"}]'
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([decoupe, probleme, corrige, pire], []))
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": scenario}).json()
    assert d["plans"][0]["image_paroles"] == "Léa lance le ballon."
    assert d["relecture"]["corrige"] is False and "texte d'origine est gardé" in d["relecture"]["erreur"]
    assert d["continuite"]["problemes"] == [{"plan": 1, "quoi": "Le panier n'est pas placé."}]


def test_la_correction_demande_le_modele_haut_de_gamme_gratuit(h3, monkeypatch, sans_traduction):
    """29/09 : free-ai-auto rendait 5 plans au lieu de 4 (4 corrections lues sur 15),
    free-ai-max 15 sur 15."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    decoupe = '[{"image_paroles": "Léa lance le ballon.", "ambiance": "", "enchainement": "coupe"}]'
    probleme = '{"etats": [], "problemes": [{"plan": 1, "quoi": "Le panier n\'est pas placé."}]}'
    corrige = '[{"image_paroles": "Léa lance le ballon vers le panier.", "ambiance": "", "enchainement": "coupe"}]'
    vus = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [decoupe, probleme, corrige, '{"etats": [], "problemes": []}'], vus))
    client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": "Léa lance le ballon."})
    assert h3.MODELE_CORRECTION == "free-ai-max"
    # Le découpage reste sur free-ai-auto ; la relecture était déjà sur free-ai-max.
    assert [v["model"] for v in vus] == ["free-ai-auto", "free-ai-max", "free-ai-max", "free-ai-max"]


def test_une_correction_qui_retire_les_mots_cites_est_gardee_meme_a_compte_egal(h3, monkeypatch, sans_traduction):
    """29/09 : « face caméra » puis « se tourne vers la caméra » ; corrigé, la seconde
    relecture relevait un autre petit point et le compte égal rejetait la correction."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    scenario = "Leila se retourne vers nous et sourit."
    decoupe = ('[{"image_paroles": "Leila est face à la caméra. Leila se retourne vers la caméra et sourit.", '
               '"ambiance": "", "enchainement": "coupe"}]')
    probleme = ('{"etats": [], "problemes": [{"plan": 1, "citation": "Leila est face à la caméra", '
                '"quoi": "La pose de départ est le résultat du mouvement."}]}')
    corrige = ('[{"image_paroles": "Leila est de dos. Leila se retourne vers la caméra et sourit.", '
               '"ambiance": "", "enchainement": "coupe"}]')
    autre = '{"etats": [], "problemes": [{"plan": 1, "citation": "", "quoi": "Le lieu n\'est pas nommé."}]}'
    # Le second tour corrige ce que la seconde relecture a trouvé (29/09, parapluie de la gare).
    lieu = corrige.replace("Leila est de dos.", "Sur un terrain de basket, Leila est de dos.")
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [decoupe, probleme, corrige, autre, lieu, '{"etats": [], "problemes": []}'], []))
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": scenario}).json()
    assert d["relecture"]["corrige"] is True
    assert d["relecture"]["second_tour"] == {"trouves": [{"plan": 1, "quoi": "Le lieu n'est pas nommé."}],
                                             "corrige": True}
    assert d["plans"][0]["image_paroles"].startswith("Sur un terrain de basket, Leila est de dos.")
    assert d["continuite"]["ok"] is True
    # Les mots cités encore là : à compte égal, le texte d'origine reste.
    reste = ('{"etats": [], "problemes": [{"plan": 1, "citation": "", "quoi": "Autre chose."}]}')
    corrige_mal = decoupe.replace("et sourit", "et sourit largement")
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([decoupe, probleme, corrige_mal, reste], []))
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": scenario}).json()
    assert d["relecture"]["corrige"] is False


def test_une_correction_n_est_jugee_que_sur_les_plans_qu_elle_change(h3, monkeypatch, sans_traduction):
    """29/09, 3 essais : le plan 3 réparé les trois fois, puis la seconde relecture
    ajoutait des remarques mineures sur les plans 1 et 2, restés tels quels."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    scenario = "Leila dribble, tire, puis se retourne vers nous et lève le poing."
    decoupe = json.dumps([
        {"image_paroles": "Leila dribble.", "ambiance": "", "enchainement": "coupe"},
        {"image_paroles": "Leila tire.", "ambiance": "", "enchainement": "suite"},
        {"image_paroles": "Leila est face à la caméra et lève le poing.", "ambiance": "", "enchainement": "suite"}],
        ensure_ascii=False)
    probleme = ('{"etats": [], "problemes": [{"plan": 3, "citation": "Leila est face à la caméra", '
                '"quoi": "Le retournement de l\'histoire est sauté."}]}')
    corrige = decoupe.replace("Leila est face à la caméra et", "Leila, de profil, se retourne vers la caméra et")
    mineures = ('{"etats": [], "problemes": [{"plan": 1, "quoi": "Rappeler le décor."}, '
                '{"plan": 2, "quoi": "Nommer la surface."}]}')
    # Le second tour ne change rien : le premier reste, les remarques restent montrées.
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([decoupe, probleme, corrige, mineures, corrige], []))
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": scenario}).json()
    assert d["relecture"]["corrige"] is True and "se retourne" in d["plans"][2]["image_paroles"]
    assert d["relecture"]["second_tour"]["corrige"] is False and "rien changé" in d["relecture"]["second_tour"]["erreur"]
    assert [p["plan"] for p in d["continuite"]["problemes"]] == [1, 2]   # montrées, pas comptées contre elle
    # Un problème de plus DANS le plan changé : la correction reste écartée.
    pire = ('{"etats": [], "problemes": [{"plan": 3, "quoi": "Le poing n\'est pas dit."}, '
            '{"plan": 3, "quoi": "Le lieu manque."}]}')
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([decoupe, probleme, corrige, pire], []))
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": scenario}).json()
    assert d["relecture"]["corrige"] is False


def test_une_fiche_objet_devient_un_sujet_unique_qui_ne_parle_pas(h3):
    """29/09 : « un nom comme <le ballon> pour le même objet tout le long du script »."""
    v = h3.video_h3
    lea = v.fiche_creer("Léa", "femme")["id"]
    ballon = v.fiche_creer("basketball", "ballon de basket orange", genre="objet")["id"]
    for f in (lea, ballon):
        v.fiche_poser_image(f, "face", PNG)
    with pytest.raises(ValueError, match="objet"):
        v.fiche_creer("x", "y", genre="animal")
    assert {f["id"]: f["genre"] for f in v.fiches_liste()} == {lea: "personne", ballon: "objet"}
    d = v.preparer({"mode": "references", "fiches": [lea, ballon], "longueur": 124,
                    "image_paroles": "The basketball lies on the floor. Léa picks up the basketball and says « Go. »",
                    "tenues_ecrites": {lea: "a red coat"}})
    inv = d["resume_public"]["invite"]
    assert "<Subject 2> is the object in <Picture 2>." in inv
    assert "there is exactly one of it in every frame" in inv
    assert "<Subject 2> lies on the floor" in inv and "picks up <Subject 2>" in inv
    assert "<Subject 2> wears" not in inv and "<Subject 1> wears a red coat" in inv
    # La réplique va à Léa, jamais à l'objet nommé dans la même phrase.
    assert "<Subject 2> (S1)" not in inv and "(S1)" in inv


def test_les_mains_une_pose_de_reference_une_regle_et_le_juge(h3):
    """29/09, « améliorer les mains » : le geste écrit, une pose en image, le juge qui regarde."""
    v = h3.video_h3
    lea = v.fiche_creer("Léa", "femme")["id"]
    prise = v.fiche_creer("shooting grip", "deux mains sur un ballon", genre="pose")["id"]
    for f in (lea, prise):
        v.fiche_poser_image(f, "face", PNG)
    inv = v.preparer({"mode": "references", "fiches": [lea, prise], "longueur": 124,
                      "image_paroles": "Léa holds the ball in the shooting grip and says « Go. »"})["resume_public"]["invite"]
    assert "<Subject 2> is the hand pose in <Picture 2>." in inv and "it adds no person" in inv
    assert "in <Subject 2>" in inv and "the <Subject 2>" not in inv and "<Subject 2> (S1)" not in inv
    assert "what each hand and its fingers do" in v.consigne_decoupage("x")
    assert "concrete gesture" in v.consigne_continuite([{"image_paroles": "x", "enchainement": "coupe"}], "x")
    assert "Look at the hands" in v.consigne_jugement(["Léa"], "x")


def test_la_page_cree_objets_et_poses_et_montre_le_tableau(h3):
    """29/09, « oui fais-le » : l'objet et la pose se créent depuis la page, avec
    une seule image adaptée ; le scénario les coche ; le tableau des éléments se voit."""
    v = h3.video_h3
    ballon = v.fiche_creer("basketball", "ballon de basket orange uni", genre="objet")
    prise = v.fiche_creer("shooting grip", "main droite sous le ballon", genre="pose")
    d = v.fiche_demande_image(ballon, "face")
    assert "sans marque, logo ni texte" in d["prompt"] and "image_reference" not in d
    assert "une seule personne" not in d["prompt"]
    assert "cinq doigts" in v.fiche_demande_image(prise, "face")["prompt"]
    for fiche in (ballon, prise):
        with pytest.raises(ValueError, match="qu'une image"):
            v.fiche_demande_image(fiche, "profil")
    with pytest.raises(ValueError, match="forme, couleur"):
        v.fiche_creer("x", "", genre="objet")
    html = client(h3).get("/video-h3").text
    for morceau in ('id="fiche_genre"', '<option value="pose">', "genre: genreFiche()",
                    'id="scenario_objets"', "concat(objetsDuScenario())", "tableauElements(p.elements)",
                    'x.genre === "personne"'):
        assert morceau in html


def test_chaque_plan_a_son_tableau_depart_mouvement_arrivee(h3, monkeypatch, sans_traduction):
    """29/09, demande du propriétaire : chaque élément clé avec sa place de départ,
    son mouvement et sa place d'arrivée ; un élément qui surgit sans origine se
    voit par le code."""
    v = h3.video_h3
    c = v.consigne_decoupage("Leila tire.")
    assert '"elements"' in c and "copies WORD FOR WORD" in c and '"mouvement"' in c
    assert "Keep \"elements\" true" in v.consigne_correction([{"image_paroles": "x"}], "y")
    sale = [{"nom": " Ballon ", "debut": "dans  ses mains", "mouvement": "none", "fin": "au sol"},
            {"nom": "", "debut": "x"}, "pas un dict", {"nom": "Leila", "debut": 3}]
    assert v.lire_tableau(sale) == [{"nom": "Ballon", "debut": "dans ses mains", "mouvement": "none", "fin": "au sol"}]
    assert v.lire_tableau(None) == [] and len(v.lire_tableau([sale[0]] * 20)) == v.TABLEAU_MAX
    ballon = lambda debut, fin: {"nom": "le ballon", "debut": debut, "mouvement": "", "fin": fin}  # noqa: E731
    verre = lambda debut: {"nom": "the glass", "debut": debut, "mouvement": "", "fin": "x"}  # noqa: E731
    tom = {"nom": "Tom", "debut": "Off-frame.", "mouvement": "walks in", "fin": "at the table"}
    plans = [{"enchainement": "coupe", "elements": [ballon("dans ses mains", "immobile au sol à droite")]},
             # Mots dans un autre ordre : plus une alerte (2 fausses sur 7 découpages, 29/09).
             {"enchainement": "suite", "elements": [ballon("à droite, immobile au sol", "idem"), tom]},
             {"enchainement": "suite", "elements": [verre("on the table"), verre("none")]},
             {"enchainement": "coupe", "elements": [{"nom": "la cuisine", "debut": "au fond", "mouvement": "",
                                                      "fin": ""}]}]
    ruptures = v.apparitions_du_tableau(plans)
    # Tom entre depuis le hors-champ ; le verre surgit ; une coupe peut changer de lieu.
    assert [r["plan"] for r in ruptures] == [3, 3]
    assert "sans avoir été vu avant" in ruptures[0]["quoi"] and "off-frame" in ruptures[1]["quoi"]
    c = v.consigne_decoupage("x")
    assert '"off-frame"' in c and "at most three simple steps" in c and "a cut (\"coupe\") skip the minor steps" in c
    # 29/09 : le sens d'un objet tenu, non écrit au plan 1, a été hérité à l'envers par la suite.
    assert "which end is up or in the hand, and its state" in c
    assert "which end is up or in the hand" in v.consigne_correction([{"image_paroles": "x"}], "y")
    relu = v.consigne_continuite([{"image_paroles": "x", "enchainement": "coupe"}], "x")
    # 29/09 : « divisez le plan en deux » menait la correction à un 5e plan, refusé (2 fois sur 3).
    assert "(8) does the number of shots fit the actions" in relu and "never ask to split a shot" in relu
    assert "is not a missing event" in relu
    # 29/09, quai de gare : deux personnages actifs dans un plan ; le train, but de la marche, absent.
    assert "Count the characters who act in each shot" in relu and "where a character walks" in relu
    assert "are TWO main actions" in c and "walks, runs, drives or looks toward" in c
    # 29/09 : « une règle de cohérence entre le nombre de plans et d'actions, exemple en 3 plans ».
    assert "The NUMBER of shots follows the actions" in c and "Example, in 3 shots" in c

    # Au découpage : le tableau est gardé, et la rupture rejoint la relecture.
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    decoupe = json.dumps([
        {"elements": [ballon("dans ses mains", "au sol à droite")], "image_paroles": "Leila tire.",
         "ambiance": "", "enchainement": "coupe"},
        {"elements": [ballon("au sol à droite", "au sol"), verre("none")], "image_paroles": "Le ballon est au sol.",
         "ambiance": "", "enchainement": "suite"}], ensure_ascii=False)
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [decoupe, '{"etats": [], "problemes": []}', decoupe], []))
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": "Leila tire."}).json()
    assert d["plans"][0]["elements"][0]["debut"] == "dans ses mains"
    assert [p["plan"] for p in d["relecture"]["trouves"]] == [2]


def test_le_relecteur_ecarte_une_citation_absente_et_une_correction_identique(h3, monkeypatch, sans_traduction):
    """Premier essai réel (29/09) : alertes sur des mots que le plan n'a pas, et
    « corrigé » annoncé sur un texte resté le même."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    scenario = "Tom pose un livre sur la table."
    decoupe = '[{"image_paroles": "À droite, Tom pose le livre sur la table.", "ambiance": "", "enchainement": "coupe"}]'
    problemes = ('{"etats": [], "problemes": ['
                 '{"plan": 1, "citation": "Tom  pose le livre", "quoi": "Tom devrait arriver avant."}, '
                 '{"plan": 1, "citation": "table rouge", "quoi": "La table change de couleur."}]}')
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([decoupe, problemes, decoupe], []))
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE, json={"scenario": scenario}).json()
    assert d["relecture"]["trouves"] == [{"plan": 1, "quoi": "Tom devrait arriver avant.",
                                          "citation": "Tom pose le livre"}]
    assert d["relecture"]["corrige"] is False and "rien changé" in d["relecture"]["erreur"]


def test_un_scenario_se_tourne_plan_par_plan_et_se_recolle(h3, monkeypatch, tmp_path, sans_regles):
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    # Chaque plan part traduit, la suite aussi (28/09) : deux réponses du chat.
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([
        '{"tenues": [{"nom": "Léa", "tenue": ""}]}',   # le relevé des tenues : celle de la fiche
        '{"tenue": "a red coat"}',                      # lue sur sa photo, écrite dans le plan
        '{"image_paroles": "Lea walks into the café", "ambiance": "Chatter", "musique": ""}',
        '{"image_paroles": "She says « Bonjour. »", "ambiance": "", "musique": ""}'], []))
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
    monkeypatch.setattr(h3.montage, "fin", lambda octets, n: b"raccord")
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
    assert "<Subject 1> wears a red coat in every frame, also when seen from behind" in v1["invite"]
    assert v.fiche_tenue_de_base(fid) == "a red coat"
    # Suite avec fiche : le raccord natif (30/09), 22 images reprises puis retirées au recollage.
    assert (p2, r2) == (j1, 22) and v2["mode"] == "prolonger" and v2["plans"] == 2
    assert v2["voie"] == "raccord" and v2["images"] == 141
    assert "(S1) <d>[French] Bonjour.</d>" in v2["invite"]
    assert sc["film"] == j2 and sc["travaux"] == [j1, j2] and "video_url" in sc


def test_une_tenue_changee_par_le_scenario_ajoute_sa_photo_a_tous_les_plans(h3, monkeypatch, sans_regles):
    """29/09 : « si on change les vêtements on le fait pour tous les plans et on rajoute
    une photo de référence pour la consistance »."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    fid = v.fiche_creer("Léa", "femme de 35 ans, manteau rouge")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    vus, demandes = [], []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        ['{"tenues": [{"nom": "Léa", "tenue": "robe de cocktail noire"}, {"nom": "Inconnu", "tenue": "x"}]}'], vus))

    async def image(demande):
        demandes.append(demande)
        return "data:image/png;base64," + PNG

    monkeypatch.setattr(h3, "_image_du_studio", image)
    fils = []
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    plans = [{"image_paroles": "Léa, en robe de cocktail noire, entre.", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Léa, en robe de cocktail noire, s'assoit.", "ambiance": "", "enchainement": "coupe"}]
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 200, r.text
    # Le nom seul : la description d'une fiche (un âge) a fait filtrer la demande (29/09).
    assert "manteau rouge" not in json.dumps(vus[0], ensure_ascii=False)
    assert "robe de cocktail noire" in demandes[0]["prompt"] and demandes[0]["image_reference"]
    sc = r.json()
    assert [(t["nom"], t["tenue"]) for t in sc["tenues"]] == [("Léa", "robe de cocktail noire")]
    for p in fils[0][1]:
        assert p["payload"]["tenues"] == {fid: PNG}
        invite = v.preparer(p["payload"])["resume_public"]["invite"]
        assert "with the clothing of <Picture 2>, as one single person" in invite
    assert v.lire_tenues("rien de lisible", ["Léa"]) == {}


def test_un_refus_du_filtre_du_modele_se_dit(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteur(
        200, {"choices": [{"finish_reason": "content_filter: PROHIBITED_CONTENT", "index": 0}]}, {}))
    with pytest.raises(h3.HTTPException, match="filtre du modèle a refusé le relevé"):
        asyncio.run(h3._chat_du_studio("x", "le relevé des tenues"))


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


def test_cadrage_generique_et_personnages_places_une_seule_fois(h3):
    v = h3.video_h3
    # Le 28/09, « In the foreground: only <Subject 1>… » puis la description ont placé Léa deux fois.
    assert not hasattr(v, "premier_plan")
    assert "foreground" not in v.sujets_des_fiches([2, 1])
    # Règle 2, dans le découpage comme dans la correction ; aucun nom de personnage dans la règle.
    assert v.CADRAGE in v.consigne_decoupage("Un film.") and "at most %d shots" % v.SCENARIO_PLANS_MAX in \
        v.consigne_decoupage("Un film.")
    # Essai du 29/09 : geste étalé sur trois plans, élément du lieu absent au départ, caméra qui avance.
    for regle in ("never spread one gesture over several shots", "already visible from the start",
                  "the camera stays at that framing", "fix the STAGING of each place",
                  "every shot's text states the position of each key element", "what moves the object",
                  "walking to it first", "plain sentences. When", "never tells again an action that ended",
                  "An object still moving when a shot starts",
                  "These positions describe the START of the shot"):
        assert regle in v.consigne_decoupage("Un film."), regle
    assert v.CADRAGE in v.consigne_correction([], "retour")
    assert "close-up shows one character only" in v.CADRAGE
    assert "Place each character once" in v.CADRAGE
    assert "say how the movement ends" in v.CADRAGE
    assert "Background people" in v.CADRAGE and "never in the foreground" in v.CADRAGE
    assert "Never add or remove a character of the story" in v.CADRAGE
    # Le juge signale aussi ce qui disparaît sans sortir du cadre.
    assert "disappears or appears without leaving or entering the frame" in v.consigne_jugement([])
    assert "disappears or appears" in v.consigne_jugement(["Léa"], "Léa sourit")
    # 29/09 : objets qui partent seuls, et raccord avec le plan d'avant.
    assert "without something pushing it" in v.consigne_jugement([])
    assert "END OF THE PREVIOUS SHOT" not in v.consigne_jugement(["Léa"], "Léa sourit")
    assert "Frames 1 to 2 are the END OF THE PREVIOUS SHOT, the shot itself starts at frame 3" in \
        v.consigne_jugement(["Léa"], "Léa sourit", raccord=2)


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
        "person in <Picture 3>. summary: [reference generation] The target video is a single shot with "
        "<Subject 1> and <Subject 2>. retention_analysis: <Subject 1> (appears in [Shot 1]): fully_preserved "
        "- the face, hair and clothing of the person in <Picture 1>, <Picture 2> are retained, as one single "
        "person. <Subject 2> (appears in [Shot 1]): fully_preserved - the face, hair and clothing of the "
        "person in <Picture 3> are retained, as one single person. "
        # Chaque personnage n'est placé qu'une fois, par la description elle-même.
        "detailed_description: [Shot 1] <Subject 2> (S1) demande <d>[English] Is this seat taken?</d> "
        "<Subject 1> (S2) répond <d>[French] Oui.</d> non_diegetic_music: N/A")
    assert list(plan["demande"]["images"]) == ["ref_0.png", "ref_1.png", "ref_2.png"]
    assert [f["nom"] for f in plan["resume_public"]["fiches"]] == ["Léa", "James"]
    for mauvais, message in (({"langues": {lea: "Klingon"}}, "inconnue"), ({"fiches": [lea, lea]}, "illisible")):
        with pytest.raises(ValueError, match=message):
            v.preparer(dict(d, **mauvais))


WAV = b"RIFF" + b"\0" * 40 + b"\1\0" * 32000 * 4   # 4 s de faux son, déjà mis au propre


def test_le_profil_voix_part_avec_les_photos_en_audio_de_reference(h3, sans_regles):
    """29/09 : « soit on donne un exemple de voix à cloner, soit on génère un clonage
    dans la langue du locuteur et on l'applique à tous les plans »."""
    v = h3.video_h3
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    v.fiche_poser_image(james, "face", PNG)
    v.fiche_poser_voix(james, WAV, 4.0, "exemple", "English")
    assert {f["nom"]: f["voix"] for f in v.fiches_liste()} == {"Léa": False, "James": True}
    d = demande(mode="references", fiches=[lea, james], langues={lea: "French", james: "English"},
                image_paroles="James demande « Is this seat taken? » Léa répond « Oui. »")
    plan = v.preparer(d)
    invite = plan["resume_public"]["invite"]
    # Le (Sx) de James repris, pas créé (ref-en.txt, 2.4).
    assert "<Subject 2> is the person in <Picture 2>. <Audio 1> is the voice-timbre reference for " \
           "<Subject 2> (S1)." in invite
    assert "<Audio 1>: reference - its vocal timbre guides the spoken voice of <Subject 2> in every line; " \
           "the words of <Audio 1> are never said." in invite
    assert "<Audio 2>" not in invite   # Léa n'a pas de voix : H3 lui en invente une
    assert plan["demande"]["sons"] == {"voix_0.wav": base64.b64encode(WAV).decode()}
    g = plan["demande"]["graphe"]
    assert g["70"] == {"class_type": "LoadAudio", "inputs": {"audio": "voix_0.wav"}}
    assert g["10"]["inputs"]["ref_audios.ref_audio_0"] == ["70", 0]
    # Le script de la machine pose les sons à côté des images.
    assert '**(D.get("sons") or {})' in v._SCRIPT
    # Parc, 30/09 : un plan où James se tait part sans sa voix (H3 le faisait parler).
    for muet in ("James regarde Léa.", "Léa dit « Oui. » James sourit."):
        plan = v.preparer(dict(d, image_paroles=muet))
        assert plan["demande"]["sons"] == {} and "<Audio" not in plan["resume_public"]["invite"]
    # Sans voix, rien ne change.
    v.fiche_retirer_voix(james)
    plan = v.preparer(d)
    assert plan["demande"]["sons"] == {} and "<Audio" not in plan["resume_public"]["invite"]
    assert not any(n["class_type"] == "LoadAudio" for n in plan["demande"]["graphe"].values())
    # Un objet ne parle pas ; une voix trop courte est refusée.
    ballon = v.fiche_creer("ballon", "rond", "objet")["id"]
    with pytest.raises(ValueError, match="ne parle pas"):
        v.fiche_poser_voix(ballon, WAV, 4.0, "exemple", "French")
    with pytest.raises(ValueError, match="trop courte"):
        v.fiche_poser_voix(lea, WAV, 2.5, "exemple", "French")
    # Sa langue est notée (règle 4, 30/09) : sans elle, rien n'est posé.
    with pytest.raises(ValueError, match="langue"):
        v.fiche_poser_voix(lea, WAV, 4.0, "exemple", "")


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_la_page_pose_un_exemple_de_voix_ou_en_genere_une(h3, monkeypatch, tmp_path):
    v = h3.video_h3
    lea = v.fiche_creer("Léa", "x")["id"]
    son = tmp_path / "exemple.mp3"
    # 1 s de silence puis 6 s de son : le silence du début est retiré.
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:r=44100",
                    "-af", "volume='if(lt(t,1),0,1)':eval=frame", "-t", "7", str(son)], check=True)
    exemple = "data:audio/mpeg;base64," + base64.b64encode(son.read_bytes()).decode()
    r = client(h3).post(f"/video-h3/fiches/{lea}/voix", headers=CLE, json={"son": exemple})
    assert r.status_code == 400 and "droit" in r.json()["detail"]
    # La langue de l'exemple est demandée (règle 4, 30/09).
    r = client(h3).post(f"/video-h3/fiches/{lea}/voix", headers=CLE, json={"son": exemple, "droit": True})
    assert r.status_code == 400 and "langue" in r.json()["detail"]
    r = client(h3).post(f"/video-h3/fiches/{lea}/voix", headers=CLE,
                        json={"son": exemple, "droit": True, "langue": "Spanish"})
    assert r.status_code == 200, r.text
    voix = r.json()["voix"]
    assert voix["source"] == "exemple" and 5.5 <= voix["duree_s"] <= 6.5 and voix["langue"] == "Spanish"
    assert voix["son"].startswith("data:audio/wav;base64,")
    # Générée : la voix du Studio lit la phrase de la langue choisie.
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    vu = {}
    lu = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=330:r=22050", "-t", "5",
                         "-f", "wav", "-"], capture_output=True, check=True).stdout

    class Parle(_FauxRouteur):
        async def post(self, url, headers=None, json=None):
            vu.update(url=url, json=json)
            return h3.httpx.Response(200, content=lu, request=h3.httpx.Request("POST", url))
    monkeypatch.setattr(h3.httpx, "AsyncClient", Parle(200, None, {}))
    r = client(h3).post(f"/video-h3/fiches/{lea}/voix", headers=CLE, json={"generer": "French"})
    assert r.status_code == 200, r.text
    assert vu["url"].endswith("/v1/audio/speech") and vu["json"] == {"input": v.PHRASE_VOIX["French"]}
    assert r.json()["voix"]["source"] == "generee" and r.json()["voix"]["langue"] == "French"
    assert client(h3).post(f"/video-h3/fiches/{lea}/voix", headers=CLE, json={"generer": "Klingon"}).status_code == 400
    assert client(h3).delete(f"/video-h3/fiches/{lea}/voix", headers=CLE).json()["voix"] is None
    page = client(h3).get("/video-h3").text
    assert "function dessinerVoix" in page and "j'ai le droit d'utiliser cette voix" in page
    assert "Langue parlée dans l'exemple" in page and "langue: parle.value" in page


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


def _volume_440(chemin, debut, duree):
    """Le niveau de la musique (440 Hz) seule, la « voix » du film (2 000 Hz) filtrée."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(debut), "-t", str(duree), "-i", str(chemin),
                          "-af", "bandpass=f=440:width_type=q:w=6,bandpass=f=440:width_type=q:w=6,volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(err.split("mean_volume:")[1].split("dB")[0])


def _film_qui_parle(chemin):
    """4 s d'images ; silence jusqu'à 2 s, puis une « voix » forte (2 000 Hz)."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x48:r=24",
                    "-f", "lavfi", "-i", "sine=f=2000:r=48000", "-frames:v", "96", "-t", "4",
                    "-af", "volume='if(lt(t,2),0,1)':eval=frame", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(chemin)], check=True)


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_la_musique_part_d_un_passage_de_la_chanson_et_baisse_sous_les_paroles(h3, tmp_path):
    film, musique = tmp_path / "film.mp4", tmp_path / "musique.flac"
    _film_qui_parle(film)
    # La chanson : 3 s d'introduction muette, puis le « chant » (440 Hz).
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "12",
                    "-af", "volume='if(lt(t,3),0,1)':eval=frame", str(musique)], check=True)
    m, sortie = h3.montage, tmp_path / "avec.mp4"
    sortie.write_bytes(m.poser_musique(film.read_bytes(), musique.read_bytes(), 0.0, 0.5))
    assert _volume_440(sortie, 0.4, 1.2) < -60            # prise au début : l'introduction muette
    sortie.write_bytes(m.poser_musique(film.read_bytes(), musique.read_bytes(), 0.0, 0.5, depart_chanson_s=3.0,
                                       fondu_s=0.2))
    assert m.images(sortie) == 96
    assert _volume_440(sortie, 0.4, 1.2) > -30            # prise à 3 s : le chant tout de suite
    libre = _volume_440(sortie, 2.6, 0.8)
    sortie.write_bytes(m.poser_musique(film.read_bytes(), musique.read_bytes(), 0.0, 0.5, depart_chanson_s=3.0,
                                       fondu_s=0.2, sous_paroles=True))
    assert _volume_440(sortie, 0.4, 1.2) > -30            # personne ne parle : la musique reste
    assert _volume_440(sortie, 2.6, 0.8) < libre - 6      # la « voix » parle : la musique baisse
    with pytest.raises(m.MontageImpossible, match="hors bornes"):
        m.poser_musique(film.read_bytes(), musique.read_bytes(), 0.0, depart_chanson_s=-1)


def test_les_passages_parles_se_lisent_dans_le_journal_de_silencedetect(h3):
    journal = ("[silencedetect] silence_start: 0\n[silencedetect] silence_end: 1.3 | silence_duration: 1.3\n"
               "[silencedetect] silence_start: 1.32\n[silencedetect] silence_end: 6.73\n"
               "[silencedetect] silence_start: 7.79\n[silencedetect] silence_end: 8.37\n")
    # Le bruit de 1,30 à 1,32 s est écarté ; le dernier passage court jusqu'à la fin du clip.
    assert h3.montage.lire_silences(journal, 10.1) == [(6.48, 8.04), (8.12, 10.1)]
    assert h3.montage.lire_silences("", 3.0) == [(0.0, 3.0)]


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_les_passages_parles_d_un_vrai_clip(h3, tmp_path):
    film = tmp_path / "film.mp4"
    _film_qui_parle(film)
    passages = h3.montage.passages_parles(film.read_bytes())
    assert len(passages) == 1 and 1.6 <= passages[0][0] <= 2.0 and passages[0][1] == 4.0
    son = h3.montage.son_du_passage(film.read_bytes(), *passages[0])
    assert son[:3] == b"ID3" or son[:2] in (b"\xff\xfb", b"\xff\xf3")


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_les_passages_d_un_son_sans_image(h3, tmp_path):
    # Une chanson n'a pas d'images : le 28/09, l'écoute n'y trouvait aucun passage.
    chanson = tmp_path / "chanson.flac"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "5",
                    "-af", "volume='if(between(t,2,3),0,1)':eval=frame", str(chanson)], check=True)
    passages = h3.montage.passages_parles(chanson.read_bytes())
    assert len(passages) == 2 and passages[0][0] == 0.0 and 2.0 <= passages[0][1] <= 2.4
    assert 2.6 <= passages[1][0] <= 3.0 and passages[1][1] == 5.0
    assert h3.montage.son_du_passage(chanson.read_bytes(), *passages[1])[:3] in (b"ID3", b"\xff\xfb\x90")


def test_l_ecoute_entend_aussi_chaque_passage(h3, monkeypatch):
    """Essai du 28/09 : sur un clip bilingue, Whisper sur le clip entier garde une
    seule langue et perd une réplique ; passage par passage, il entend les deux."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(h3.montage, "passages_parles", lambda video: [(6.48, 8.04), (8.12, 10.1)])
    monkeypatch.setattr(h3.montage, "son_du_passage", lambda video, a, b: ("P%.2f" % a).encode())
    ecoutes, vu = [], {}
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille(
        "", ["Nice to meet you.", "Bonjour, ça va ?", "Nice to meet you."], ecoutes, vu))
    import asyncio
    texte = "Il dit « Bonjour, ça va ? » puis « [anglais] Nice to meet you! »"
    r = asyncio.run(h3._ecouter(b"CLIP", texte))
    assert [e[0] for e in ecoutes] == [b"CLIP", b"P6.48", b"P8.12"]
    assert r["attendu"] == ["Bonjour, ça va ?", "Nice to meet you!"] and r["ok"] is True and r["part"] == 1.0
    assert r["entendu"] == "Nice to meet you." and \
        [p["entendu"] for p in r["passages"]] == ["Bonjour, ça va ?", "Nice to meet you."]
    # Sans les passages, la réplique française manque : 4 mots entendus sur 7.
    monkeypatch.setattr(h3.montage, "passages_parles", lambda video: [])
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille("", ["Nice to meet you."], [], {}))
    sans = asyncio.run(h3._ecouter(b"CLIP", texte))
    assert sans["ok"] is False and abs(sans["part"] - 4 / 7) < 0.01


def test_l_ecoute_ecarte_les_mots_inventes_sur_un_passage_sans_voix(h3, monkeypatch):
    """Gare, 29/09 : un bruit à 0,65 s devenait « Bye. » (Groq, sans parole à 0,74) ;
    le propriétaire n'a entendu aucun « Bye ». Les segments sans parole sont écartés."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(h3.montage, "passages_parles", lambda video: [(0.65, 1.61), (2.94, 5.17)])
    monkeypatch.setattr(h3.montage, "son_du_passage", lambda video, a, b: ("P%.2f" % a).encode())
    ligne = {"text": "Désolé, le bus était en retard.", "no_speech_prob": 0.03, "avg_logprob": -0.21}
    bye = {"text": "Bye.", "no_speech_prob": 0.74, "avg_logprob": -0.80}
    ecoutes = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille("", [
        {"text": "Bye. Désolé, le bus était en retard.", "segments": [bye, ligne]},
        {"text": "Bye.", "segments": [bye]},
        {"text": ligne["text"], "segments": [ligne]}], ecoutes, {}))
    import asyncio
    r = asyncio.run(h3._ecouter(b"CLIP", "Marc dit « Désolé, le bus était en retard. »"))
    assert all(e[1]["details"] == "segments" for e in ecoutes)
    assert r["entendu"] == "Désolé, le bus était en retard." and r["ok"] is True
    assert [p["entendu"] for p in r["passages"]] == ["Désolé, le bus était en retard."]
    assert r["ecartes"] == ["Bye.", "Bye."]
    # Le repli local du routeur ne rend que le texte : il est gardé tel quel.
    monkeypatch.setattr(h3.montage, "passages_parles", lambda video: [])
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille("", ["Bye. Désolé."], [], {}))
    assert asyncio.run(h3._ecouter(b"CLIP", "« Désolé. »"))["entendu"] == "Bye. Désolé."


def test_un_plan_sans_replique_est_ecoute_et_une_voix_y_est_une_faute(h3, monkeypatch):
    """Parc, 30/09, plan 3 : aucune réplique écrite, et H3 fait dire « Bien. Jaffer,
    vous étiez… » ; le juge n'écoutait pas les plans sans réplique."""
    import asyncio
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    # Rejeu du parc : un plan à -57 dB, sans passage parlé, n'est pas envoyé à Whisper
    # (qui y inventait « I'm going to make a », sans parole à 0,25).
    monkeypatch.setattr(h3.montage, "passages_parles", lambda video: [])
    ecoutes = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille(
        "", [{"text": "I'm going to make a", "segments": [{"text": "I'm going to make a", "no_speech_prob": 0.25}]}],
        ecoutes, {}))
    r = asyncio.run(h3._ecouter(b"CLIP", "Marc ramasse le cerf-volant."))
    assert r["ok"] is None and ecoutes == []
    monkeypatch.setattr(h3.montage, "passages_parles", lambda video: [(0.84, 2.08), (2.13, 3.05)])
    parle = {"text": "Bien. Jaffer, vous étiez", "no_speech_prob": 0.26}
    souffle = {"text": "Bye.", "no_speech_prob": 0.74}
    for reponse, ok, doute in (({"text": parle["text"], "segments": [parle]}, False, False),
                               ({"text": "Bye.", "segments": [souffle]}, None, False),
                               ({"text": " ... ", "segments": [{"text": " ... ", "no_speech_prob": 0.1}]}, None, False),
                               ("Bien. Jaffer", None, True)):   # repli local, sans segments
        monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille("", [reponse], [], {}))
        r = asyncio.run(h3._ecouter(b"CLIP", "Leila recule en déroulant la ficelle."))
        assert (r["ok"], r["doute"]) == (ok, doute), reponse
    r = h3.video_h3.comparer_paroles("Leila recule.", "Bien. Jaffer, vous étiez")
    assert h3.video_h3.defaut_de_paroles(r, 10.3)["quoi"] == (
        "Aucune réplique écrite ; le clip dit : « Bien. Jaffer, vous étiez »."
    )
    assert h3.regles.regle_paroles(r)["ok"] is False
    assert h3.regles.regle_paroles(h3.video_h3.comparer_paroles("Leila recule.", ""))["ok"] is None


def test_une_replique_entendue_a_moitie_est_a_verifier_pas_un_defaut():
    import importlib
    v = importlib.import_module("video_h3")
    # Gare, 29/09 : « trempé » dit « trampé », entendu « trompé » ; le propriétaire l'a entendu dit.
    p = v.comparer_paroles("Léa dit « Tu es trempé ! »", "Tu es trompé !")
    assert p["part"] == 0.67 and p["doute"] is True and p["ok"] is None
    assert v.defaut_de_paroles(p, 5.2) is None
    assert v.comparer_paroles("« Tu es trempé ! »", "Tu")["ok"] is False
    assert v.segments_parles([{"text": " Oui ", "no_speech_prob": 0.29}, {"text": "Bye.", "no_speech_prob": 0.3},
                              {"text": "sans indice"}]) == ("Oui sans indice", ["Bye."])


def test_une_replique_dit_sa_langue_et_le_personnage_garde_sa_voix(h3):
    v = h3.video_h3
    texte = "Elle dit « Bonjour ! » puis, en riant, « [anglais] Nice to meet you! »"
    assert v.balises_paroles(texte, "French") == ("Elle dit (S1) <d>[French] Bonjour !</d> puis, en riant, "
                                                  "(S1) <d>[English] Nice to meet you!</d>")
    avec_fiche = v.attribuer_repliques("Léa dit « Bonjour ! » puis « [English] Nice to meet you! »",
                                       [("Léa", "French")], garder_noms=True)
    assert avec_fiche == ("Léa (S1) dit <d>[French] Bonjour !</d> puis Léa (S1) <d>[English] Nice "
                          "to meet you!</d>")
    assert v.repliques(texte) == ["Bonjour !", "Nice to meet you!"]
    # Une marque qui n'est pas une langue reste dans la réplique.
    assert v.balises_paroles("« [soupir] Enfin ! »", "French") == "(S1) <d>[French] [soupir] Enfin !</d>"
    assert v.langue_de_replique("[Japanese] はい", "French") == ("Japanese", "はい")


def test_une_musique_du_studio_se_pose_sous_un_film(h3, monkeypatch, tmp_path):
    _deux_clips(h3, monkeypatch, tmp_path)
    son = tmp_path / "son.flac"
    son.write_bytes(b"SON")
    c_id = "c" * 32
    monkeypatch.setattr(h3, "_chansons_pretes", lambda: [{"id": c_id, "titre": "Jazz", "cree_a": 0}])
    monkeypatch.setattr(h3, "chanson_fichiers", lambda jid: {"son": {"path": str(son)}})
    vus = []
    monkeypatch.setattr(h3.montage, "poser_musique", lambda f, s, d, vol, *reste: vus.append((f, s, d, vol, *reste))
                        or f + s)
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 248)
    c = client(h3)
    assert [x["id"] for x in c.get("/video-h3/clips", headers=CLE).json()["chansons"]] == [c_id]
    r = c.post("/video-h3/musique", headers=CLE, json={"film": "a" * 32, "chanson": c_id, "debut_s": 5.17})
    assert r.status_code == 200, r.text
    assert vus == [(b"A", b"SON", 5.17, 0.3, 0.0, 0.3, False)]
    assert r.json()["video"]["musique"] == {"chanson": c_id, "debut_s": 5.17, "volume": 0.3,
                                            "depart_chanson_s": 0.0, "fondu_s": 0.3, "sous_paroles": False}
    # Essai du 28/09 : la chanson prise à 7,5 s, un fondu d'1 s, baissée sous la parole.
    r = c.post("/video-h3/musique", headers=CLE, json={"film": "a" * 32, "chanson": c_id, "debut_s": 0,
                                                        "depart_chanson_s": 7.5, "fondu_s": 1, "sous_paroles": True})
    assert r.status_code == 200, r.text
    assert vus[-1] == (b"A", b"SON", 0.0, 0.3, 7.5, 1.0, True)
    assert c.post("/video-h3/musique", headers=CLE, json={"film": "a" * 32, "chanson": c_id,
                                                          "fondu_s": "long"}).status_code == 400
    for corps, code in (({"chanson": "e" * 32}, 404), ({"film": "e" * 32}, 404), ({"volume": 2}, 400)):
        base = {"film": "a" * 32, "chanson": c_id, "debut_s": 1}
        assert c.post("/video-h3/musique", headers=CLE, json=dict(base, **corps)).status_code == code


def test_un_scenario_a_deux_pose_la_musique_des_le_plan_voulu(h3, monkeypatch, sans_regles):
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
    png, nombre = m.planche_serree(film.read_bytes(), 1.0, 1.5, 0.125)
    assert png.startswith(b"\x89PNG") and nombre == 12
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


def test_juger_montre_chaque_plan_et_les_fiches_au_chat(h3, monkeypatch, tmp_path, sans_regles):
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    planches = []
    monkeypatch.setattr(h3.montage, "planche", lambda film, debut, duree: planches.append(
        (film, round(debut, 3), round(duree, 3))) or (b"\x89PNG", 11))
    vu, ecoutes = {}, []
    rep = '{"verdict": "defaut", "defauts": [{"image": 9, "quoi": "veste grise"}]}'
    # Chaque plan est aussi écouté, découpé à ses images.
    monkeypatch.setattr(h3.montage, "extraire", lambda film, de, a: b"PLAN %d-%d" % (de, a))
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille(
        rep, ["Excuse me, is this seat taken?", "Oui, bien sûr.", "Thank you!"], ecoutes, vu))
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: pytest.fail("rien ne se loue"))
    # Le juge lit l'histoire du scénario INITIAL, pas le texte corrigé depuis.
    initiaux = [dict(p) for p in plans]
    initiaux[2]["image_paroles"] = "Léa et James marchent, puis James dit « Thank you. »"
    h3.video_h3.scenario_noter(sid, plans_initiaux=initiaux)
    r = client(h3).post(f"/video-h3/scenario/{sid}/juger", headers=CLE)
    assert r.status_code == 200, r.text
    # Le film SANS musique, découpé plan par plan aux images notées.
    # À partir du plan 2, la planche s'ouvre sur la dernière seconde du plan d'avant (raccord, 29/09).
    assert planches == [(b"FILM", 0.0, 5.167), (b"FILM", 4.167, 6.167), (b"FILM", 9.333, 6.167)]
    contenu = vu["chats"][-1]["messages"][0]["content"]
    assert vu["chats"][-1]["model"] == "free-ai-max"   # « Auto » manquait les défauts le 28/09
    assert contenu[0]["type"] == "text" and "Image 1 shows Léa" in contenu[0]["text"]
    # Le texte du plan jugé (le dernier) part aussi : la vidéo doit faire ce qu'il dit, dans l'ordre.
    assert "Léa et James marchent, puis James dit « Thank you. »" in contenu[0]["text"]
    assert plans[2]["image_paroles"] not in contenu[0]["text"]
    assert "not in this order" in contenu[0]["text"]
    assert "Frames 1 to 2 are the END OF THE PREVIOUS SHOT" in contenu[0]["text"]
    assert "END OF THE PREVIOUS SHOT" not in vu["chats"][0]["messages"][0]["content"][0]["text"]
    assert [c["type"] for c in contenu[1:]] == ["image_url"] * 3   # deux fiches, puis la planche
    assert [e[0] for e in ecoutes] == [b"PLAN 0-124", b"PLAN 124-248", b"PLAN 248-372"]
    assert ecoutes[0][1] == {"model": "whisper-1", "details": "segments"}
    j = r.json()["jugement"]
    assert j[0]["paroles"]["ok"] is True and j[0]["defauts"] == [{"t_s": 4.0, "quoi": "veste grise"}]
    # « Non. » n'a pas été dit : un défaut de plus, au début du plan.
    assert j[1]["paroles"] == {"attendu": ["Non."], "entendu": "Oui, bien sûr.", "part": 0.0, "ok": False, "doute": False,
                                "passages": []}   # un faux plan : aucun passage à découper
    assert j[1]["defauts"] == [{"t_s": 8.2, "quoi": "veste grise"},
                               {"t_s": 5.2, "quoi": "Réplique attendue « Non. » ; le clip dit : « Oui, bien sûr. »."}]
    assert j[2]["paroles"]["ok"] is True and len(j[2]["defauts"]) == 1
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


def test_seuls_les_problemes_bloquants_font_corriger(h3):
    """29/09 : « le seuil de déclenchement est trop bas, pour la gare le seul défaut est
    le parapluie ». Un regard ou une main est un détail : montré, jamais réécrit."""
    v = h3.video_h3
    c = v.lire_continuite(json.dumps({"problemes": [
        {"plan": 3, "quoi": "Écrire le geste qui ouvre le parapluie.", "gravite": "bloquant"},
        {"plan": 2, "quoi": "Léa doit regarder Marc.", "gravite": "detail"},
        {"plan": 4, "quoi": "Quelle main prend la valise ?", "gravite": "détail"}]}), 4)
    assert c["ok"] is False and [p["plan"] for p in c["problemes"]] == [3]
    assert [p["plan"] for p in c["details"]] == [2, 4]
    # Que des détails : rien à corriger, le découpage est bon à tourner.
    seuls = v.lire_continuite(json.dumps({"problemes": [
        {"plan": 2, "quoi": "Léa doit regarder Marc.", "gravite": "detail"}]}), 4)
    assert seuls["ok"] is True and seuls["problemes"] == [] and len(seuls["details"]) == 1
    consigne = v.consigne_continuite([{"image_paroles": "x", "ambiance": "", "enchainement": "coupe"}], "y")
    assert '"gravite": "bloquant|detail"' in consigne and "always a detail" in consigne
    assert "Détails, sans correction" in v.PAGE_HTML


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
        {"plan": 2, "quoi": "James est assis avant d'être invité"}], "details": []}


def test_la_continuite_se_lit_et_ne_garde_que_les_plans_du_film(h3):
    v = h3.video_h3
    c = v.lire_continuite('Voici : {"etats": [{"plan": 1, "debut": "a", "fin": "b"}], "problemes": '
                          '[{"plan": 2, "quoi": "  assis   trop tôt "}, {"plan": 9, "quoi": "hors film"}, {"plan": 1}]}', 3)
    assert c == {"ok": False, "etats": [{"plan": 1, "debut": "a", "fin": "b"}],
                 "problemes": [{"plan": 2, "quoi": "assis trop tôt"}], "details": []}
    assert v.lire_continuite('{"problemes": []}', 3)["ok"] is True
    with pytest.raises(ValueError, match="pas pu être lu"):
        v.lire_continuite("tout va bien", 3)
    consigne = v.consigne_continuite([{"image_paroles": "Léa s'assoit.", "ambiance": "x", "enchainement": "coupe"}],
                                     "Léa arrive puis s'assoit.")
    assert "Léa arrive puis s'assoit." in consigne and "after what causes it" in consigne and '"x"' not in consigne
    # Le 28/09, une correction a retiré « James s'assoit » sans que le contrôle le relève.
    assert "none missing" in consigne


def test_rejouer_ne_retourne_que_le_plan_change_et_repose_la_musique(h3, monkeypatch, tmp_path, sans_regles):
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
    # Deux personnes dans la même image : une photo chacune, dans l'ordre, avant le texte.
    r = c.post("/v1/images/generations", headers=entete,
               json={"prompt": "les deux", "image_reference": ["data:image/jpeg;base64," + JPG,
                                                           "data:image/png;base64," + PNG]})
    assert r.status_code == 200
    assert vu["json"]["contents"][0]["parts"] == [
        {"inlineData": {"mimeType": "image/jpeg", "data": JPG}},
        {"inlineData": {"mimeType": "image/png", "data": PNG}}, {"text": "les deux"}]
    r = c.post("/v1/images/generations", headers=entete,
               json={"prompt": "x", "image_reference": ["data:image/png;base64," + PNG] * 15})
    assert r.status_code == 400
    vu.clear()
    c.post("/v1/images/generations", headers=entete, json={"prompt": "sans départ"})
    assert vu["json"]["contents"][0]["parts"] == [{"text": "sans départ"}]


# --- Demande du propriétaire, 28/09 : « fais le 1 et le 2, 3 et 4 » -----------------

def _deux_fiches(v):
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    v.fiche_poser_image(lea, "pied", PNG)
    v.fiche_poser_image(james, "face", PNG)
    return lea, james


def test_1_l_image_du_studio_joint_toutes_les_photos_des_personnages(h3, monkeypatch):
    v = h3.video_h3
    lea, james = _deux_fiches(v)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    vu = {}
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(200, {"data": [{"url": "data:image/png;base64," + PNG}]}, vu))
    r = client(h3).post("/video-h3/image", headers=CLE, json={
        "texte": "Un café bondé", "ameliorations": ["le nom du café lisible"], "fiches": [lea, james]})
    assert r.status_code == 200, r.text
    assert vu["json"]["prompt"].startswith("Léa est la personne des images jointes 1 à 2; James est la "
                                           "personne de l'image jointe 3 (mêmes visage")
    assert len(vu["json"]["image_reference"]) == 3
    # La description rendue (celle qui passe à H3) ne présente pas les photos.
    assert r.json()["texte"].startswith("Un café bondé") and "jointe" not in r.json()["texte"]
    assert "le nom du café lisible" in r.json()["texte"]
    sans_image = v.fiche_creer("Tom", "z")["id"]
    for fiches, message in (([lea, lea], "illisible"), ([sans_image], "aucune image"), (["0" * 12], "inconnue")):
        r = client(h3).post("/video-h3/image", headers=CLE, json={"texte": "x", "fiches": fiches})
        assert r.status_code == 400 and message in r.json()["detail"]
    monkeypatch.setattr(v, "PHOTOS_IMAGE_MAX", 2)
    r = client(h3).post("/video-h3/image", headers=CLE, json={"texte": "x", "fiches": [lea, james]})
    assert r.status_code == 400 and "au plus" in r.json()["detail"]


def test_1_le_clip_garde_son_texte_et_les_personnages_de_son_image(h3, monkeypatch):
    v = h3.video_h3
    lea, james = _deux_fiches(v)
    monkeypatch.setattr(h3, "_h3_peut_louer", lambda: None)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    lances = []
    monkeypatch.setattr(h3, "_lancer_h3", lambda plan, *a, **k: lances.append(plan) or {"id": "x"})
    monkeypatch.setattr(h3, "_garde_licence_h3", lambda: None)
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(
        mode="premiere", images=[PNG], image_paroles="Léa sourit", fiches_image=[james]))
    assert r.status_code == 200, r.text
    assert lances[0]["resume_public"]["texte_client"] == "Léa sourit"
    assert lances[0]["resume_public"]["fiches_image"] == [{"id": james, "nom": "James"}]
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(
        mode="premiere", images=[PNG], fiches_image=["0" * 12]))
    assert r.status_code == 400


def test_2_le_juge_regarde_et_ecoute_un_clip_seul(h3, monkeypatch, tmp_path):
    v = h3.video_h3
    lea, james = _deux_fiches(v)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    film = tmp_path / "clip.mp4"
    film.write_bytes(b"CLIP")
    jid = "a" * 32
    job = {"status": "succeeded", "video": {
        "moteur": "MiniMax H3 (ComfyUI)", "secondes": 5.2, "texte_client": "James demande « Is this seat taken? »",
        "fiches": [], "fiches_image": [{"id": james, "nom": "James"}]}}
    ecrits = {}
    monkeypatch.setattr(h3, "read_job", lambda j: json.loads(json.dumps(job)) if j == jid else None)
    monkeypatch.setattr(h3, "write_job", lambda j, d: ecrits.update({j: d}))
    monkeypatch.setattr(h3, "_video_h3_octets", lambda j: film)
    planches = []
    monkeypatch.setattr(h3.montage, "planche", lambda f, debut, duree: planches.append((f, debut, duree))
                        or (b"\x89PNG", 11))
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: pytest.fail("rien ne se loue"))
    vu, ecoutes = {}, []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurOreille(
        '{"verdict": "ok", "defauts": []}', ["Excusez-moi, cette place est libre ?"], ecoutes, vu))
    r = client(h3).post(f"/video-h3/jobs/{jid}/juger", headers=CLE)
    assert r.status_code == 200, r.text
    assert planches == [(b"CLIP", 0.0, 5.2)] and ecoutes[0][0] == b"CLIP"
    contenu = vu["chats"][0]["messages"][0]["content"]
    assert "Image 1 shows James" in contenu[0]["text"] and "Is this seat taken?" in contenu[0]["text"]
    assert [c["type"] for c in contenu[1:]] == ["image_url"] * 2   # la fiche, puis la planche
    # Les images sont justes, mais la réplique anglaise n'a pas été dite : défaut.
    d = r.json()
    assert d["verdict"] == "defaut" and d["paroles"]["ok"] is False
    assert d["defauts"][0]["t_s"] == 0.0 and "Is this seat taken?" in d["defauts"][0]["quoi"]
    assert ecrits[jid]["jugement"] == d
    assert client(h3).post("/video-h3/jobs/" + "b" * 32 + "/juger", headers=CLE).status_code == 404
    assert client(h3).post("/video-h3/jobs/pas-un-numero/juger", headers=CLE).status_code == 404


def test_3_l_ecoute_compare_les_repliques_attendues():
    import importlib
    v = importlib.import_module("video_h3")
    p = v.comparer_paroles("James demande « Is this seat taken? »", "Excuse me, is this seat seat taken?")
    assert p == {"attendu": ["Is this seat taken?"], "entendu": "Excuse me, is this seat seat taken?",
                 "part": 1.0, "ok": True, "doute": False}
    assert v.defaut_de_paroles(p, 3.0) is None
    # Accents et ponctuation ne comptent pas ; un mot sur deux ne suffit pas, sans faire un défaut.
    assert v.comparer_paroles("Léa dit « Déjà ? »", "deja")["ok"] is True
    moitie = v.comparer_paroles("« Is this seat taken? »", "Is this")
    assert moitie["ok"] is None and moitie["doute"] is True and v.defaut_de_paroles(moitie, 0) is None
    assert v.comparer_paroles("« Is this seat taken? »", "Is")["ok"] is False
    rien = v.comparer_paroles("Ils marchent", "")
    assert rien["ok"] is None and v.defaut_de_paroles(rien, 0) is None
    # Depuis le 30/09, un plan sans réplique qui parle est un défaut (parc, plan 3).
    assert v.comparer_paroles("Ils marchent", "de la musique")["ok"] is False
    manque = v.comparer_paroles("« Non. »", "")
    assert v.defaut_de_paroles(manque, 5.17) == {"t_s": 5.2, "quoi": "Réplique attendue « Non. » ; le clip dit : « rien »."}


def test_4_l_image_de_depart_se_garde_sur_le_studio(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    lea, james = _deux_fiches(h3.video_h3)
    c = client(h3)
    r = c.post("/video-h3/depart", headers=CLE, json={"image": "data:image/png;base64," + PNG})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    assert len(did) == 24 and r.json()["texte"] == ""
    assert c.get("/video-h3/depart/" + did, headers=CLE).json() == {"image": "data:image/png;base64," + PNG}
    assert h3.video_h3.depart_lire(did) == base64.b64decode(PNG)
    vu = {}
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(200, {"data": [{"url": "data:image/png;base64," + PNG}]}, vu))
    r = c.post("/video-h3/depart", headers=CLE, json={"texte": "Un café bondé", "fiches": [lea]})
    # Même image rendue : même numéro ; la description revient sans la présentation des photos.
    assert r.status_code == 200 and r.json()["id"] == did and r.json()["texte"].startswith("Un café bondé")
    assert len(vu["json"]["image_reference"]) == 2
    # L'image du plan d'avant part en dernier, pour garder le même lieu (28/09).
    r = c.post("/video-h3/depart", headers=CLE, json={"texte": "Plan moyen", "fiches": [lea], "decor": did})
    assert r.status_code == 200, r.text
    assert vu["json"]["image_reference"][2] == "data:image/png;base64," + PNG
    assert "L'image jointe 3 est le plan précédent : garder le même univers" in vu["json"]["prompt"]
    assert "l'endroit précis, le cadrage et la place des personnes suivent la description" in vu["json"]["prompt"]
    assert "précédent" not in r.json()["texte"]
    r = c.post("/video-h3/depart", headers=CLE, json={"texte": "x", "decor": "f" * 24})
    assert r.status_code == 400 and "introuvable" in r.json()["detail"]
    assert c.get("/video-h3/depart/" + "f" * 24, headers=CLE).status_code == 404
    assert c.get("/video-h3/depart/nimporte", headers=CLE).status_code == 404
    assert c.post("/video-h3/depart", headers=CLE, json={"image": "pas une image"}).status_code == 400


def test_4_un_plan_coupe_garde_son_image_de_depart():
    import importlib
    v = importlib.import_module("video_h3")
    did = "0123456789abcdef01234567"
    plans = v.verifier_plans([
        {"image_paroles": "Léa attend", "image_depart": did, "description_depart": "  Un café\n bondé "},
        {"image_paroles": "Elle sourit", "enchainement": "suite", "image_depart": did}])
    assert plans[0]["image_depart"] == did and plans[0]["description_depart"] == "Un café bondé"
    assert "image_depart" not in plans[1]   # une suite part de la dernière image du plan d'avant
    with pytest.raises(ValueError, match="image de départ inconnue"):
        v.verifier_plans([{"image_paroles": "x", "image_depart": "../x"}])
    with pytest.raises(ValueError, match="trop longue"):
        v.verifier_plans([{"image_paroles": "x", "image_depart": did, "description_depart": "a" * 2001}])
    # La correction garde l'image ; une image changée fait retourner le plan.
    corriges = v.lire_correction(json.dumps([{"image_paroles": "Léa attend, debout", "ambiance": ""},
                                             {"image_paroles": "Elle sourit", "ambiance": "",
                                              "enchainement": "suite"}]), plans)
    assert corriges[0]["image_depart"] == did
    assert v.plans_a_reprendre(plans, plans) == [0, 1]
    assert v.plans_a_reprendre(plans, [dict(plans[0], image_depart="f" * 24), plans[1]]) == []


def test_4_le_plan_coupe_part_de_son_image_et_les_fiches_donnent_les_voix(h3, monkeypatch):
    v = h3.video_h3
    lea, james = _deux_fiches(v)
    did = v.depart_poser("data:image/png;base64," + PNG)
    recadres = []
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: recadres.append((image, l, h)) or CADRE)
    plans = v.verifier_plans([
        {"image_paroles": "James demande « Is this seat taken? »", "image_depart": did,
         "description_depart": "Un café bondé, une chaise vide"},
        {"image_paroles": "Léa répond « Non. »"}])
    corps = {"fiches": [lea, james], "langues": {james: "English"}, "langue": "French", "longueur": 124}
    commun, musique, a_tourner = h3._scenario_prepare(corps, plans)
    assert recadres == [(base64.b64decode(PNG), *v.DEFINITIONS[v.DEFINITION_PAR_DEFAUT])]
    # 29/09 : les photos des fiches accompagnent l'image de départ (visage réinventé sinon).
    p0 = a_tourner[0]["payload"]
    assert p0["mode"] == "references" and p0["depart_reference"] == base64.b64encode(CADRE).decode()
    plan = v.preparer(dict(p0, depart_reference=PNG))
    assert "detailed_description: [Shot 1] The shot begins from <Picture 4>. " in plan["resume_public"]["invite"]
    assert list(plan["demande"]["images"]) == [f"ref_{i}.png" for i in range(4)]
    # Des fiches sans photo : l'image seule, et les fiches donnent les voix.
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    corps = {"fiches": [lea, james], "langues": {james: "English"}, "langue": "French", "longueur": 124}
    p0 = h3._scenario_prepare(corps, plans[:1])[2][0]["payload"]
    assert p0["mode"] == "premiere" and p0["images"] == [base64.b64encode(CADRE).decode()]
    assert p0["description_premiere"] == "Un café bondé, une chaise vide"
    invite = v.preparer(dict(p0, images=[PNG]))["resume_public"]["invite"]
    # Sans photos de fiche, les noms restent des noms ; James parle anglais.
    assert invite.startswith("First frame: Un café bondé, une chaise vide. ")
    assert "<Subject" not in invite and "James (S1)" in invite and "[English]" in invite
    assert "overall_soundscape" not in invite and "detailed_description" not in invite
    with pytest.raises(ValueError, match="Première image"):
        v.preparer(demande(fiches=[lea]))


def test_la_page_propose_les_quatre_chantiers(h3):
    html = client(h3).get("/video-h3").text
    for morceau in ('id="personnages_premiere"', 'id="personnages_derniere"', "fiches: fichesCochees(nom)",
                    "fiches_image:", 'id="juger_clip"', '"/video-h3/jobs/" + CLIP_COURANT + "/juger"',
                    "function blocDepart(p)", '"/video-h3/depart"', "texteParoles(j.paroles)"):
        assert morceau in html, morceau


# --- Le visage : gros plan pour la fiche, comparaison avec l'image de départ (28/09) ---

def test_la_boite_du_visage_se_lit_et_s_elargit_en_gros_plan(h3):
    v = h3.video_h3
    assert v.lire_visage('Voici : {"x0": 0.4, "y0": 0.1, "x1": 0.6, "y1": 0.3}') == (0.4, 0.1, 0.6, 0.3)
    # La convention du modèle qui voit : 0-1000 (réponse réelle du 28/09).
    assert v.lire_visage('```json\n{"x0": 296, "y0": 72, "x1": 461, "y1": 224}\n```') == (0.296, 0.072, 0.461, 0.224)
    assert v.lire_visage('{"x0": 296, "y0": 72, "x1": 1461, "y1": 224}') is None
    for mauvais in ("{}", "pas de visage", '{"x0": 0.6, "y0": 0.1, "x1": 0.4, "y1": 0.3}',
                    '{"x0": 0.4, "y0": 0.1, "x1": 1.4, "y1": 0.3}', '{"x0": 0.4, "y0": 0.1, "x1": 0.41, "y1": 0.3}',
                    '{"x0": "a", "y0": 0.1, "x1": 0.6, "y1": 0.3}', None):
        assert v.lire_visage(mauvais) is None, mauvais
    # Cheveux au-dessus, cou en dessous, de l'air sur les côtés ; jamais hors de l'image.
    assert v.zone_gros_plan((0.4, 0.2, 0.6, 0.4)) == (0.31, 0.1, 0.69, 0.47)
    assert v.zone_gros_plan((0.0, 0.0, 0.5, 0.9)) == (0.0, 0.0, 0.725, 1.0)


def test_l_avis_sur_la_ressemblance_se_lit(h3):
    v = h3.video_h3
    assert "first 2 image(s)" in v.consigne_ressemblance(2)
    assert v.lire_ressemblance('```json\n{"ressemblance": "moyenne", "ecarts": "nez  plus\\nlarge"}\n```') == \
        {"ressemblance": "moyenne", "ecarts": "nez plus large"}
    for mauvais in ('{"ressemblance": "parfaite"}', "illisible", "[]"):
        assert v.lire_ressemblance(mauvais)["ressemblance"] is None


def _image(chemin, largeur, hauteur):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=%dx%d" % (largeur, hauteur),
                    "-frames:v", "1", str(chemin)], check=True)
    return Path(chemin).read_bytes()


def _taille(octets, tmp_path):
    p = tmp_path / "vue.png"
    p.write_bytes(octets)
    sortie = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=width,height", "-of", "csv=p=0", str(p)],
                            capture_output=True, text=True, check=True).stdout
    return tuple(int(x) for x in sortie.strip().split(","))


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_le_gros_plan_et_la_planche_sont_faits_par_ffmpeg(h3, tmp_path):
    m = h3.montage
    photo = _image(tmp_path / "pied.png", 400, 800)
    gros_plan = m.recadrer_zone(photo, (0.25, 0.1, 0.75, 0.3))
    assert gros_plan.startswith(b"\x89PNG")
    assert _taille(gros_plan, tmp_path) == (512, 410)   # 200 x 160 agrandi à 512 de large
    assert _taille(m.recadrer_zone(_image(tmp_path / "grand.png", 2000, 1000), (0, 0, 0.5, 0.5)), tmp_path) == \
        (1000, 500)   # déjà assez grand : pas réduit
    planche = m.planche_visages([photo, gros_plan, photo], cote=100)
    assert _taille(planche, tmp_path) == (300, 100)
    assert _taille(m.planche_visages([photo], cote=100), tmp_path) == (100, 100)
    with pytest.raises(m.MontageImpossible):
        m.planche_visages([])
    with pytest.raises(m.MontageImpossible):
        m.recadrer_zone(b"pas une image", (0, 0, 1, 1))


def test_une_photo_televersee_se_recadre_sur_le_visage(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    fid = h3.video_h3.fiche_creer("Léa", "une femme")["id"]
    coupes, vus = [], []
    monkeypatch.setattr(h3.montage, "recadrer_zone", lambda image, zone: coupes.append((image, zone)) or CADRE)
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteurSuite(['{"x0": 0.4, "y0": 0.2, "x1": 0.6, "y1": 0.4}', "{}"], vus))
    c = client(h3)
    f = c.post(f"/video-h3/fiches/{fid}/images/face", headers=CLE,
               json={"image": "data:image/jpeg;base64," + JPG, "visage": True}).json()
    assert coupes == [(base64.b64decode(JPG), (0.31, 0.1, 0.69, 0.47))]
    assert f["images"]["face"] == "data:image/png;base64," + base64.b64encode(CADRE).decode()
    image_vue = vus[0]["messages"][-1]["content"][-1]["image_url"]["url"]
    assert image_vue == "data:image/jpeg;base64," + JPG
    # Aucun visage : refus, et la fiche ne change pas.
    r = c.post(f"/video-h3/fiches/{fid}/images/profil", headers=CLE, json={"image": JPG, "visage": True})
    assert r.status_code == 400 and "Aucun visage" in r.json()["detail"]
    assert list(h3.video_h3.fiche_lire(fid)["images"]) == ["face"]
    # Sans la case : la photo est posée telle quelle, sans appel.
    f = c.post(f"/video-h3/fiches/{fid}/images/pied", headers=CLE, json={"image": JPG}).json()
    assert len(vus) == 2 and f["images"]["pied"].startswith("data:image/jpeg;base64,")


def test_l_image_de_depart_se_compare_au_visage_de_la_fiche(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    v = h3.video_h3
    fid = v.fiche_creer("Léa", "une femme")["id"]
    did = v.depart_poser("data:image/png;base64," + PNG)
    c = client(h3)
    r = c.post(f"/video-h3/depart/{did}/comparer", headers=CLE, json={"fiche": fid})
    assert r.status_code == 400 and "aucune photo" in r.json()["detail"]
    v.fiche_poser_image(fid, "face", JPG)
    planches, vus = [], []
    monkeypatch.setattr(h3.montage, "recadrer_zone", lambda image, zone: CADRE)
    monkeypatch.setattr(h3.montage, "planche_visages", lambda images: planches.append(images) or b"\x89PNGplanche")
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        ['{"x0": 0.4, "y0": 0.2, "x1": 0.6, "y1": 0.4}',
         '{"ressemblance": "faible", "ecarts": "nez plus large, nez plus fin"}'], vus))
    d = c.post(f"/video-h3/depart/{did}/comparer", headers=CLE, json={"fiche": fid}).json()
    assert d == {"planche": "data:image/png;base64," + base64.b64encode(b"\x89PNGplanche").decode(),
                 "ressemblance": "faible", "ecarts": "nez plus large, nez plus fin"}
    assert planches == [[base64.b64decode(JPG), CADRE]]   # la fiche, puis le visage généré
    montrees = [p["image_url"]["url"] for p in vus[1]["messages"][-1]["content"] if p.get("type") == "image_url"]
    assert montrees == ["data:image/jpeg;base64," + JPG, "data:image/png;base64," + base64.b64encode(CADRE).decode()]
    assert c.post("/video-h3/depart/" + "b" * 24 + "/comparer", headers=CLE,
                  json={"fiche": fid}).status_code == 404


def test_la_page_propose_le_visage_la_comparaison_et_la_musique_reglable(h3):
    html = client(h3).get("/video-h3").text
    for morceau in ('id="musique_depart"', 'id="musique_fondu"', 'id="musique_sous_paroles"',
                    "depart_chanson_s:", "sous_paroles:", " recadrer sur le visage", "function poserPhoto(",
                    '"/comparer"', "Comparer au visage de", "Avis du Studio — ressemblance", "[anglais] Nice",
                    "function blocComparer(", 'id="comparer_premiere"', 'id="comparer_derniere"',
                    '"/video-h3/visage/comparer", {image: png}'):
        assert morceau in html, morceau


def test_toute_image_se_compare_au_visage_d_une_fiche(h3, monkeypatch):
    # Pas seulement l'image de départ d'un plan : la première ou la dernière image
    # d'un clip, créée ou téléversée, quel que soit le mode.
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    v = h3.video_h3
    fid = v.fiche_creer("Tom", "un homme")["id"]
    v.fiche_poser_image(fid, "face", JPG)
    v.fiche_poser_image(fid, "profil", PNG)
    c = client(h3)
    assert c.post("/video-h3/visage/comparer", headers=CLE, json={"fiche": fid}).status_code == 400
    planches, vus = [], []
    monkeypatch.setattr(h3.montage, "planche_visages", lambda images: planches.append(images) or b"\x89PNGp")
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        ["{}", '{"ressemblance": "forte", "ecarts": ""}'], vus))
    d = c.post("/video-h3/visage/comparer", headers=CLE,
               json={"fiche": fid, "image": "data:image/png;base64," + PNG}).json()
    # Aucun visage trouvé : l'image entière est comparée.
    assert d["ressemblance"] == "forte" and d["ecarts"] == ""
    assert planches == [[base64.b64decode(JPG), base64.b64decode(PNG), base64.b64decode(PNG)]]
    assert "first 2 image(s)" in json.dumps(vus[1])
    r = c.post("/video-h3/visage/comparer", headers=CLE, json={"fiche": "0123456789ab", "image": PNG})
    assert r.status_code in (400, 404)


def test_la_planche_de_personnage_se_cree_sert_aux_images_et_se_supprime(h3, monkeypatch):
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    v, c = h3.video_h3, client(h3)
    fid = v.fiche_creer("Tom", "un homme, veste verte")["id"]
    r = c.post(f"/video-h3/fiches/{fid}/planche", headers=CLE, json={})
    assert r.status_code == 400 and "aucune image" in r.json()["detail"]
    v.fiche_poser_image(fid, "face", JPG)
    v.fiche_poser_image(fid, "pied", PNG)
    vu = {}
    monkeypatch.setattr(h3.httpx, "AsyncClient",
                        _FauxRouteur(200, {"data": [{"url": "data:image/png;base64," + PNG}]}, vu))
    f = c.post(f"/video-h3/fiches/{fid}/planche", headers=CLE, json={}).json()
    # Toutes les photos de la fiche, la consigne générique et la description.
    assert vu["json"]["image_reference"] == ["data:image/jpeg;base64," + JPG, "data:image/png;base64," + PNG]
    assert vu["json"]["prompt"].startswith("Planche de référence d'un personnage")
    assert "de profil strict" in vu["json"]["prompt"] and vu["json"]["prompt"].endswith("veste verte")
    assert f["planche"] == "data:image/png;base64," + PNG and list(f["images"]) == ["face", "pied"]
    # Une planche téléversée remplace l'ancienne, sans appel.
    vu.clear()
    f = c.post(f"/video-h3/fiches/{fid}/planche", headers=CLE, json={"image": JPG}).json()
    assert vu == {} and f["planche"].startswith("data:image/jpeg;base64,")
    assert sorted(p.name for p in (v.DOSSIER_FICHES / fid).iterdir()) == \
        ["face.jpg", "fiche.json", "pied.png", "planche.jpg"]
    # Jointe aux images que le Studio crée avec ce personnage, jamais aux références de H3.
    demande, _ = v.demande_image("Tom dans un parc", fiches=[fid])
    assert len(demande["image_reference"]) == 3 and demande["image_reference"][2].startswith("data:image/jpeg")
    assert demande["prompt"].startswith("Tom est la personne des images jointes 1 à 3")
    assert len(v.fiche_images(fid)) == 2
    f = c.delete(f"/video-h3/fiches/{fid}/planche", headers=CLE).json()
    assert f["planche"] is None and not (v.DOSSIER_FICHES / fid / "planche.jpg").exists()
    assert len(v.demande_image("Tom", fiches=[fid])[0]["image_reference"]) == 2
    html = c.get("/video-h3").text
    for morceau in ('id="fiche_planche"', "function dessinerPlanche(", "Créer la planche de personnage",
                    "Télécharger la planche", '"/planche", {method: "DELETE"'):
        assert morceau in html, morceau


# --- 12. Physique écrite, juge serré, cause d'un défaut, tenues gardées (29/09) ---

def test_la_physique_s_ecrit_en_entier_au_decoupage_a_la_relecture_et_a_la_correction(h3):
    """29/09 : « rebondir AU SOL, sinon il l'a fait en l'air » ; règle générale, pas le ballon."""
    v = h3.video_h3
    plans = [{"image_paroles": "Tom lance la balle.", "ambiance": "", "enchainement": "coupe"}]
    for consigne in (v.consigne_decoupage("Tom lance la balle."), v.consigne_correction(plans, "x")):
        assert "bounces once on the wooden floor" in consigne and "comes to rest" in consigne
    assert "(7) physics" in v.consigne_continuite(plans, "Tom lance la balle.")
    # « ne pas décrire un mouvement de deux façons » (29/09) : même règle, même relecture.
    for consigne in (v.consigne_decoupage("x"), v.consigne_correction(plans, "x")):
        assert "Describe each movement ONCE" in consigne
    assert "(9) is a movement described twice" in v.consigne_continuite(plans, "x")


def test_le_debut_serre_part_du_debut_du_texte_et_pardonne_camera_et_cache(h3):
    """Banc du 29/09 : le tir rejoué vu 4/4 en partant d'où le texte commence ; un
    panoramique et un ballon caché par le corps étaient lus comme des défauts."""
    v = h3.video_h3
    c = v.consigne_debut(["Léa"], "Le ballon tombe sous le panier.")
    assert "where the text says the shot STARTS" in c and "must not be performed again" in c
    assert "the camera panning" in c and "hidden behind a body" in c
    assert "STARTS" not in v.consigne_debut(["Léa"])   # sans texte, rien à comparer


def test_le_juge_regarde_le_debut_serre_et_dit_la_cause(h3, monkeypatch, tmp_path, sans_regles):
    """29/09 : planche à 0,5 s, « ok » ; à 1/8 s, un second ballon dans le filet."""
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(h3.montage, "planche", lambda film, debut, duree: (b"\x89PNG", 11))
    serrees = []
    monkeypatch.setattr(h3.montage, "planche_serree", lambda film, debut, duree, pas: serrees.append(
        (round(debut, 3), duree, pas)) or (b"\x89PNG", 12))
    monkeypatch.setattr(h3.montage, "extraire", lambda film, de, a: b"PLAN")
    vus = []
    ok = '{"verdict": "ok", "defauts": []}'
    ballon = '{"verdict": "defaut", "defauts": [{"image": 5, "quoi": "un second ballon", "cause": "video"}]}'
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([ok, ok, ok, ballon, ok, ok], vus))
    monkeypatch.setattr(h3, "_ecouter", lambda video, texte: asyncio.sleep(0, {}))
    j = client(h3).post(f"/video-h3/scenario/{sid}/juger", headers=CLE).json()["jugement"]
    # Le début serré part au début du PLAN, pas à la seconde de raccord qui ouvre la planche.
    assert serrees == [(0.0, 1.5, 0.125), (pytest.approx(124 / 24, abs=1e-3), 1.5, 0.125),
                       (pytest.approx(248 / 24, abs=1e-3), 1.5, 0.125)]
    assert "one frame every 0.125 s" in vus[1]["messages"][0]["content"][0]["text"]
    assert '"cause": "texte" or "video"' in vus[1]["messages"][0]["content"][0]["text"]
    assert j[0]["verdict"] == "ok"
    assert j[1]["verdict"] == "defaut" and j[1]["defauts"] == [
        {"t_s": round(124 / 24 + 4 * 0.125, 2), "quoi": "un second ballon", "cause": "video"}]


def test_un_defaut_de_la_video_ne_reecrit_pas_le_texte(h3, monkeypatch, tmp_path):
    sid, plans = _scenario_tourne(h3, monkeypatch, tmp_path)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([], []))   # aucun appel au chat
    r = client(h3).post(f"/video-h3/scenario/{sid}/corriger", headers=CLE, json={
        "defauts": [{"plan": 3, "t_s": 11.0, "quoi": "un second ballon", "cause": "video"}]})
    assert r.status_code == 200, r.text
    assert r.json()["plans"] == plans and r.json()["sans_texte"] == [3] and r.json()["retours"] == ""
    vus = []
    corriges = [dict(plans[0]), dict(plans[1], image_paroles="Léa, assise, répond « Non. »"), dict(plans[2])]
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [json.dumps(corriges, ensure_ascii=False), '{"etats": [], "problemes": []}'], vus))
    r = client(h3).post(f"/video-h3/scenario/{sid}/corriger", headers=CLE, json={"defauts": [
        {"plan": 2, "t_s": 6.0, "quoi": "debout", "cause": "texte"},
        {"plan": 3, "t_s": 11.0, "quoi": "un second ballon", "cause": "video"}]})
    assert "debout" in vus[0]["messages"][0]["content"] and "second ballon" not in vus[0]["messages"][0]["content"]
    assert r.json()["sans_texte"] == [3]
    assert v_lire(h3)('{"verdict": "defaut", "defauts": [{"image": 2, "quoi": "x", "cause": "autre"}]}') == \
        {"verdict": "defaut", "defauts": [{"t_s": 0.5, "quoi": "x"}]}


def v_lire(h3):
    return lambda rep: h3.video_h3.lire_jugement(rep, 0.0, 12)


def test_les_tenues_se_relevent_plan_par_plan_et_se_gardent_sur_la_fiche(h3, monkeypatch, sans_regles):
    """29/09 : « le profil dérive de la fiche de base, avec des attributs qui changent »."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    fid = v.fiche_creer("Léa", "femme de 35 ans, manteau rouge")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    PIED = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\2" * 64).decode()
    v.fiche_poser_image(fid, "pied", PIED)   # en manteau rouge : ne part plus avec une autre tenue
    releve = ('{"tenues": [{"nom": "Léa", "plan": 1, "tenue": "maillot de basket bleu"}, '
              '{"nom": "Léa", "plan": 3, "tenue": "robe noire"}, {"nom": "Léa", "plan": 9, "tenue": "x"}]}')
    assert v.lire_tenues(releve, ["Léa"], 3) == {"Léa": {1: "maillot de basket bleu", 3: "robe noire"}}
    assert v.tenues_par_plan({1: "a", 3: "b"}, 4) == ["a", "a", "b", "b"]
    assert v.tenues_par_plan({2: "a"}, 3) == ["a", "a", "a"]
    assert v.tenues_par_plan({0: "a"}, 2) == ["a", "a"]
    faites_images = []

    async def image(demande):
        faites_images.append(demande)
        return "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\n" + bytes([len(faites_images) + 2]) * 64).decode()

    monkeypatch.setattr(h3, "_image_du_studio", image)
    fils = []
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    plans = [{"image_paroles": "Léa, en maillot de basket bleu, dribble.", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Léa tire.", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Léa, en robe noire, entre au café.", "ambiance": "", "enchainement": "coupe"}]
    corps = {"plans": plans, "fiche": fid, "longueur": 124}
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([releve], []))
    sc = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json=corps).json()
    assert [(t["tenue"], t["plans"], t["reprise"]) for t in sc["tenues"]] == [
        ("maillot de basket bleu", [1, 2], False), ("robe noire", [3], False)]
    a_tourner = fils[0][1]
    maillot, robe = (v.fiche_tenue_image(fid, t) for t in ("Maillot de basket  bleu", "robe noire"))
    assert maillot and robe and maillot != robe
    assert [p["payload"]["tenues"][fid] for p in a_tourner] == [maillot, maillot, robe]
    # Le visage de la fiche et la tenue : la photo en pied (ancienne tenue) ne part pas.
    images = v.preparer(a_tourner[0]["payload"])["demande"]["images"]
    assert list(images.values()) == [PNG, maillot]
    # Un second film qui joue la même tenue la reprend de la fiche : aucune image refaite.
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([releve], []))
    sc = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json=corps).json()
    assert len(faites_images) == 2 and all(t["reprise"] for t in sc["tenues"])


def test_la_tenue_de_base_est_lue_sur_la_photo_en_pied_une_seule_fois(h3, monkeypatch):
    """29/09 : de dos, H3 a inventé un sweat gris ; la tenue de la fiche est écrite."""
    v = h3.video_h3
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    fid = v.fiche_creer("Léa", "x")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    vus = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(['{"tenue": "a red  coat"}'], vus))
    assert asyncio.run(h3._tenue_de_base(fid)) == "a red coat"
    # Gardée sur la fiche : aucun second appel au chat.
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([], []))
    assert asyncio.run(h3._tenue_de_base(fid)) == "a red coat"
    # Une photo en pied posée ensuite : c'est elle qu'on lit, la lecture sur la face ne vaut plus.
    AUTRE = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\5" * 64).decode()
    v.fiche_poser_image(fid, "pied", AUTRE)
    assert v.fiche_tenue_de_base(fid) is None
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(['{"tenue": "a blue dress"}'], []))
    assert asyncio.run(h3._tenue_de_base(fid)) == "a blue dress"


def test_l_image_de_depart_prend_la_tenue_de_son_plan(h3, monkeypatch):
    v = h3.video_h3
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    fid = v.fiche_creer("Léa", "x")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    v.fiche_poser_image(fid, "pied", PNG)
    ROBE = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\7" * 64).decode()
    v.fiche_poser_tenue(fid, "robe noire", "data:image/png;base64," + ROBE)
    demandes = []

    async def image(demande):
        demandes.append(demande)
        return "data:image/png;base64," + PNG

    monkeypatch.setattr(h3, "_image_du_studio", image)
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        ['{"tenues": [{"nom": "Léa", "plan": 2, "tenue": "robe noire"}]}'], []))
    r = client(h3).post("/video-h3/depart", headers=CLE, json={
        "texte": "Léa entre", "fiches": [fid], "plans": ["Léa marche.", "Léa, en robe noire, entre."], "plan": 2})
    assert r.status_code == 200, r.text
    refs = demandes[0]["image_reference"]
    assert refs == ["data:image/png;base64," + PNG, "data:image/png;base64," + ROBE]
    assert "vêtue exactement comme sur l'image jointe 2" in demandes[0]["prompt"]


# --- Agrandir (SeedVR2, 30/09) : le devis, les coupes, le script, la route. ------

def test_agrandir_coupe_aux_fins_de_plans_puis_en_parts_egales(sandbox):
    a = sandbox.agrandir
    assert a.bornes(493, [124, 247, 370, 493]) == [0, 124, 247, 370, 493]
    assert a.bornes(300) == [0, 100, 200, 300]
    # Une fin hors du film est ignorée ; un plan trop long est partagé.
    assert a.bornes(130, [124, 999]) == [0, 124, 130]
    assert a.bornes(400, [124]) == [0, 124, 216, 308, 400]
    assert all(y - x <= a.MORCEAU_MAX for x, y in zip(a.bornes(1000), a.bornes(1000)[1:]))


def test_agrandir_le_devis_vient_de_la_mesure_et_refuse_le_trop_long(sandbox):
    a = sandbox.agrandir
    d = a.prix(121, "4k")
    assert d["secondes_estimees"] == round(a.DEMARRAGE_S + 578.9)
    assert 0 < d["estime_usd"] < d["pire_usd"]
    assert d["delai_s"] <= a.DUREE_MAX_S
    assert a.prix(121, "x2")["estime_usd"] < d["estime_usd"]
    with pytest.raises(ValueError, match="choisissez ×2"):
        a.prix(800, "4k")
    with pytest.raises(ValueError):
        a.prix(121, "8k")


def test_agrandir_le_graphe_est_celui_du_modele_officiel(sandbox):
    a = sandbox.agrandir
    for e, decoupe in (("x2", False), ("4k", True)):
        g = a.graphe("morceau_0.mp4", e, "agrandi/m00")
        classes = {n["class_type"] for n in g.values()}
        assert classes <= set(a.CLASSES)
        assert ("SeedVR2TemporalChunk" in classes) is decoupe
        assert g["13"]["inputs"]["color_correction_method"] == "lab"
        assert g["14"]["inputs"]["audio"] == ["2", 1]


def test_agrandir_le_script_est_du_python_et_n_importe_rien_de_comfyui(sandbox):
    a = sandbox.agrandir
    code = a.construire_script(b"mp4", "4k", [0, 124, 248])
    arbre = ast.parse(code)
    importes = {n.names[0].name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import)}
    assert not importes & {"comfy", "nodes", "folder_paths"}
    d = json.loads(base64.b64decode(re.search(r'b64decode\("([^"]+)"\)', code).group(1)))
    assert len(d["graphes"]) == 2 and d["coupes"] == [0, 124, 248]
    assert d["revision"] == a.HF_REVISION and d["base_poids"].startswith(sandbox.video_h3.POINT_DE_MONTAGE)
    with pytest.raises(ValueError):
        a.demande(b"0" * (a.VIDEO_MAX_OCTETS + 1), "x2", [0, 10])


def test_agrandir_phrase_d_echec(sandbox):
    a = sandbox.agrandir
    assert "délai" in a.phrase_d_echec("DELAI au morceau 2")
    assert "nœuds" in a.phrase_d_echec("NOEUD_ABSENT ['SeedVR2Preprocess']")
    assert a.phrase_d_echec("rien de connu") == ""


def _source_agrandir(h3, monkeypatch, tmp_path, images=248):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"mp4")
    h3.write_job("b" * 32, {"id": "b" * 32, "status": "succeeded", "titre": "Le parc"})
    monkeypatch.setattr(h3, "_clips_h3", lambda: [{"id": "b" * 32}])
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: video)
    monkeypatch.setattr(h3.montage, "images", lambda chemin: images)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    lance = []
    monkeypatch.setattr(h3, "run_agrandir", lambda *a: lance.append(a))
    return lance


def test_agrandir_le_prix_avant_la_location(h3, monkeypatch, tmp_path):
    _source_agrandir(h3, monkeypatch, tmp_path)
    assert client(h3).get("/video-h3/agrandir/prix?job=" + "c" * 32, headers=CLE).status_code == 404
    d = client(h3).get("/video-h3/agrandir/prix?job=" + "b" * 32, headers=CLE).json()
    assert d["images"] == 248 and [e["echelle"] for e in d["echelles"]] == ["x2", "4k"]
    assert all("estime_usd" in e for e in d["echelles"])


def test_agrandir_lance_un_travail_neuf_coupe_aux_plans_du_scenario(h3, monkeypatch, tmp_path):
    lance = _source_agrandir(h3, monkeypatch, tmp_path)
    monkeypatch.setattr(h3.video_h3, "scenario_lire", lambda sid: {"fins_images": [124, 248]})
    r = client(h3).post("/video-h3/agrandir", headers=CLE,
                        json={"job": "b" * 32, "echelle": "4k", "scenario": "d" * 32})
    assert r.status_code == 200, r.text
    jid, code, delai = lance[0]
    assert jid != "b" * 32 and delai == h3.agrandir.prix(248, "4k")["delai_s"]
    d = json.loads(base64.b64decode(re.search(r'b64decode\("([^"]+)"\)', code).group(1)))
    assert d["coupes"] == [0, 124, 248]
    v = h3.read_job(jid)["video"]
    # Hors des clips H3 : une vidéo agrandie n'entre pas dans un montage 480p.
    assert not v["moteur"].startswith("MiniMax H3") and v["source"] == "b" * 32
    assert h3.read_job(jid)["titre"] == "Le parc — 4K (2160p)"
    # Un scénario qui ne décrit pas ce film : parts égales.
    monkeypatch.setattr(h3.video_h3, "scenario_lire", lambda sid: {"fins_images": [124, 300]})
    client(h3).post("/video-h3/agrandir", headers=CLE, json={"job": "b" * 32, "echelle": "x2", "scenario": "d" * 32})
    d = json.loads(base64.b64decode(re.search(r'b64decode\("([^"]+)"\)', lance[1][1]).group(1)))
    assert d["coupes"] == [0, 124, 248]  # 248 = 2 morceaux égaux


def test_agrandir_refuse_avant_de_louer(h3, monkeypatch, tmp_path):
    lance = _source_agrandir(h3, monkeypatch, tmp_path)
    assert client(h3).post("/video-h3/agrandir", headers=CLE,
                           json={"job": "b" * 32, "echelle": "8k"}).status_code == 422

    def refus(*a, **k):
        raise h3.budget_modal.BudgetDepasse("Budget Modal du mois atteint.")

    monkeypatch.setattr(h3.budget_modal, "verifier", refus)
    r = client(h3).post("/video-h3/agrandir", headers=CLE, json={"job": "b" * 32, "echelle": "x2"})
    assert r.status_code == 429 and "Budget" in r.json()["detail"]
    monkeypatch.setattr(h3, "modal_configured", lambda: False)
    assert client(h3).post("/video-h3/agrandir", headers=CLE,
                           json={"job": "b" * 32, "echelle": "x2"}).status_code == 503
    assert lance == []


def test_agrandir_encaisse_la_location_meme_en_echec(h3, monkeypatch):
    jid = "e" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: {"exit_code": 8})

    def fini(j, ou, resultat):
        job = h3.read_job(j)
        job.update({"status": "failed", "stderr": "DELAI au morceau 1"})
        h3.write_job(j, job)

    monkeypatch.setattr(h3, "finish_execution", fini)
    vus = []
    monkeypatch.setattr(h3.budget_modal, "consommer", lambda *a, **k: vus.append(a) or {"usd": 1})
    h3.run_agrandir(jid, "code", 600)
    job = h3.read_job(jid)
    assert vus and vus[0][:2] == ("video", h3.agrandir.GPU)
    assert "délai" in job["error"]


def test_la_page_propose_d_agrandir_clips_et_films(h3):
    page = client(h3).get("/video-h3", headers=CLE).text
    assert 'id="clip_agrandir"' in page and 'id="montage_agrandir"' in page
    assert "/video-h3/agrandir/prix?job=" in page and "au pire" in page


def test_l_image_de_depart_part_de_l_etat_debut_des_elements(sandbox, tmp_path):
    """30/09 : depuis le texte entier du plan, 6 images de départ sur 14 dessinaient deux
    fois une personne ou un objet ; depuis l'état « debut » du tableau, 0 sur 14."""
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = sandbox.video_h3.PAGE_HTML
    morceaux = [page[page.index("const PREFIXE = {"):page.index("function majInvitesImages(){")]]
    programme = "\n".join(morceaux) + """
const p = {image_paroles: "Medium shot. Léa enters and puts the red book down. Léa says : « Bonjour. »",
  elements: [{nom: "James", debut: "background, right, holding a book"},
             {nom: "Léa", debut: "off-frame"}, {nom: "le livre rouge", debut: "off-frame"}]};
console.log(JSON.stringify([texteDepart(p), texteDepart({image_paroles: p.image_paroles})]));
"""
    f = tmp_path / "t.js"
    f.write_text(programme, encoding="utf-8")
    avec, sans = json.loads(subprocess.run(["node", str(f)], capture_output=True, text=True, check=True,
                                           encoding="utf-8").stdout)
    assert avec.endswith("Medium shot. James : background, right, holding a book.")
    assert "Léa" not in avec and "enters" not in avec
    # Sans tableau : le texte du plan, répliques retirées, comme avant.
    assert "enters" in sans and "Bonjour" not in sans


# --- Les règles numérotées, côté Studio (30/09) -------------------------------------

def _faux_chat(monkeypatch, h3, reponses: dict, vus: list):
    """Le chat du Studio rend la réponse de `reponses[quoi]` (une liste se dépile)."""
    async def chat(consigne, quoi="la traduction en anglais", images=None, modele="free-ai-auto"):
        vus.append((quoi, consigne, modele, len(images or [])))
        # Les marques des répliques (30/09) : sans réponse prévue, aucune.
        r = reponses.get(quoi, "[]" if quoi == "les marques des répliques" else None)
        if r is None:
            raise KeyError(quoi)
        return r.pop(0) if isinstance(r, list) else r
    monkeypatch.setattr(h3, "_chat_du_studio", chat)


def test_l_histoire_passe_en_anglais_avant_tout_decoupage(h3, monkeypatch):
    """Règle 0 : « the hard code is to do all the post processing from the user initial
    prompt in english ». Répliques intactes, sinon deux essais puis refus."""
    vus = []
    _faux_chat(monkeypatch, h3, {"la traduction de l'histoire en anglais": [
        "Lea says « Hello. »",                           # réplique traduite : refusée
        "Lea puts the book on the table and says « Bonjour. »"]}, vus)
    histoire = "Léa pose le livre sur la table et dit « Bonjour. »"
    assert asyncio.run(h3._histoire_en_anglais(histoire)) == \
        "Lea puts the book on the table and says « Bonjour. »"
    assert len(vus) == 2 and "changé une réplique" in vus[1][1] and "copy it EXACTLY" in vus[0][1]
    _faux_chat(monkeypatch, h3, {"la traduction de l'histoire en anglais": "Léa pose le livre sur la table « Bonjour. »"}, [])
    with pytest.raises(h3.HTTPException) as e:
        asyncio.run(h3._histoire_en_anglais(histoire))
    assert e.value.status_code == 502 and "laissé du français" in e.value.detail


def test_le_decoupage_part_de_l_histoire_en_anglais(h3, monkeypatch):
    async def en_anglais(histoire):
        return "Lea puts the red book down and says « Bonjour. »"
    monkeypatch.setattr(h3, "_histoire_en_anglais", en_anglais)
    vus = []
    decoupe = json.dumps([{"image_paroles": "Lea puts the red book down and says « Bonjour. »", "ambiance": "",
                           "enchainement": "coupe"}], ensure_ascii=False)
    _faux_chat(monkeypatch, h3, {"le découpage en plans": decoupe,
                                 "le contrôle de continuité": '{"etats": [], "problemes": []}'}, vus)
    d = client(h3).post("/video-h3/scenario/decouper", headers=CLE,
                        json={"scenario": "Léa pose le livre rouge et dit « Bonjour. »"}).json()
    assert d["histoire_anglais"] == "Lea puts the red book down and says « Bonjour. »"
    assert "Lea puts the red book down" in vus[0][1] and "pose le livre" not in vus[0][1]


def test_un_plan_a_deux_repliques_est_coupe_en_deux(h3, monkeypatch):
    """Film campus, 30/09 : deux répliques au plan 5, bloqué par la règle 2 et coupé à la
    main. « la découpe doit être hard codée (et proposée) dans le studio dans ce cas »."""
    v = h3.video_h3
    plans = v.verifier_plans([
        {"image_paroles": "Lea stands at the left.", "ambiance": ""},
        {"image_paroles": "Lea yells « [English, joy] I made the team! » Tom replies « [French] C'est génial ! »",
         "ambiance": "Campus", "enchainement": "coupe"}])
    assert v.plans_a_scinder(plans) == [1]
    bonne = json.dumps([{"image_paroles": "Lea yells « [English, joy] I made the team! » Tom smiles.", "ambiance": "Campus"},
                        {"image_paroles": "Tom replies « [French] C'est génial ! »", "ambiance": "Campus"}],
                       ensure_ascii=False)
    perdue = json.dumps([{"image_paroles": "Lea yells « [English, joy] I made the team! »", "ambiance": ""},
                         {"image_paroles": "Tom smiles.", "ambiance": ""}], ensure_ascii=False)
    vus = []
    _faux_chat(monkeypatch, h3, {"la découpe d'un plan à deux répliques": [perdue, bonne]}, vus)
    d = client(h3).post("/video-h3/scenario/scinder", headers=CLE, json={"plans": plans}).json()
    assert d["scissions"] == [{"plan": 2, "en": 2}]
    assert [p["enchainement"] for p in d["plans"]] == ["coupe", "coupe", "suite"]
    assert [len(v.repliques(p["image_paroles"])) for p in d["plans"]] == [0, 1, 1]
    assert "exactly 2 consecutive shots" in vus[0][1] and "could not be used" in vus[1][1]
    # Au-delà des plans d'un scénario : la découpe n'est pas posée, et c'est dit.
    cinq = v.verifier_plans([dict(plans[0]) for _ in range(v.SCENARIO_PLANS_MAX - 1)] + [plans[1]])
    _faux_chat(monkeypatch, h3, {"la découpe d'un plan à deux répliques": [bonne]}, vus)
    d = client(h3).post("/video-h3/scenario/scinder", headers=CLE, json={"plans": cinq}).json()
    assert len(d["plans"]) == v.SCENARIO_PLANS_MAX and "au plus" in d["scissions"][0]["erreur"] and "en" not in d["scissions"][0]
    # Le bouton de la page ne se montre que devant un plan à plusieurs répliques.
    page = v.PAGE_HTML
    assert 'id="scenario_scinder" hidden' in page and '"/video-h3/scenario/scinder"' in page


def _scenario_pret(h3, avec_voix: bool):
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    fid = v.fiche_creer("Léa", "femme de 35 ans")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    if avec_voix:
        v.fiche_poser_voix(fid, WAV, 4.0, "exemple", "French")
    return fid


def _tourner_sans_louer(h3, monkeypatch):
    monkeypatch.setattr(h3, "modal_configured", lambda: True)

    async def rien(*a, **k):
        return []
    monkeypatch.setattr(h3, "_scenario_tenues", rien)
    monkeypatch.setattr(h3, "_scenario_traduire", rien)
    fils = []
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    return fils


def test_le_tournage_est_refuse_quand_une_regle_n_est_pas_suivie(h3, monkeypatch):
    """L'audit du 30/09 : une remarque bloquante vue, puis tournée quand même (parc, plan 2)."""
    fid = _scenario_pret(h3, avec_voix=True)
    fils = _tourner_sans_louer(h3, monkeypatch)
    probleme = {"ok": False, "problemes": [{"plan": 1, "quoi": "deux actions à la fois", "gravite": "bloquant"}]}

    async def continuite(plans, histoire):
        return probleme
    monkeypatch.setattr(h3, "_continuite", continuite)
    plans = [{"image_paroles": "Léa says « Bonjour. »", "ambiance": "", "enchainement": "coupe"}]
    c = client(h3)
    r = c.post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 409 and not fils
    d = r.json()["detail"]
    assert "plan 1, règle 2 : deux actions à la fois" in d["message"] and d["passe_droit"] is True
    assert [x["n"] for x in d["regles"][0]["regles"]] == list(range(9))
    # « Tourner quand même » : parti, et le scénario garde le rapport et le passe-droit.
    r = c.post("/video-h3/scenario/tourner", headers=CLE,
               json={"plans": plans, "fiche": fid, "longueur": 124, "forcer": True})
    assert r.status_code == 200, r.text
    assert r.json()["force"] is True and r.json()["regles"][0]["regles"][2]["ok"] is False and len(fils) == 1
    # La route de vérification dit la même chose, sans rien lancer.
    r = c.post("/video-h3/scenario/verifier", headers=CLE, json={"plans": plans, "fiche": fid})
    assert r.status_code == 200 and r.json()["non_suivies"] == [[1, 2, "deux actions à la fois"]]


def test_la_voix_du_locuteur_n_a_pas_de_passe_droit(h3, monkeypatch):
    """Décision du 30/09 : la voix de chaque locuteur, « to be hard coded in studio »."""
    fid = _scenario_pret(h3, avec_voix=False)
    fils = _tourner_sans_louer(h3, monkeypatch)

    async def continuite(plans, histoire):
        return {"ok": True, "problemes": []}
    monkeypatch.setattr(h3, "_continuite", continuite)
    plans = [{"image_paroles": "Léa says « Bonjour. »", "ambiance": "", "enchainement": "coupe"}]
    for forcer in (False, True):
        r = client(h3).post("/video-h3/scenario/tourner", headers=CLE,
                            json={"plans": plans, "fiche": fid, "longueur": 124, "forcer": forcer})
        assert r.status_code == 409, r.text
        assert "règle 4" in r.json()["detail"]["message"] and r.json()["detail"]["passe_droit"] is False
    assert not fils
    h3.video_h3.fiche_poser_voix(fid, WAV, 4.0, "exemple", "French")
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 200, r.text


def test_l_image_de_depart_se_controle_une_fois(h3, monkeypatch):
    """Règles 6 à 8 : compte des éléments et visage NOMMÉ de chaque personnage."""
    v = h3.video_h3
    fid = v.fiche_creer("Leila", "girl, 10")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    did = v.depart_poser(PNG)
    plan = {"image_paroles": "Leila holds the kite.", "ambiance": "", "enchainement": "coupe", "image_depart": did,
            "elements": [{"nom": "Leila", "debut": "foreground, centre", "mouvement": "none", "fin": "x"},
                         {"nom": "Marc", "debut": "background, left", "mouvement": "none", "fin": "x"}]}
    vus, compares = [], []
    _faux_chat(monkeypatch, h3, {"le contrôle de l'image de départ":
                                 '{"comptes": [1, 0], "texte_ajoute": false, "remarque": "Marc absent"}'}, vus)

    async def comparer(image, f, ou=""):
        compares.append((f, ou))
        return {"ressemblance": "forte"}
    monkeypatch.setattr(h3, "_comparer_visage", comparer)
    fiches = h3._fiches_du_scenario({"fiche": fid})
    r = asyncio.run(h3._regles_depart(plan, fiches))
    assert r[6] == {"ok": False, "pourquoi": "Compté : Marc ×0."} and r[7]["ok"] is True and r[8]["ok"] is True
    assert compares == [(fid, "foreground, centre")] and vus[0][2] == v.MODELE_JUGE
    # Gardé à part des images (depart_lire prend le premier « <id>.* »), et relu sans modèle.
    assert v.depart_lire(did) == base64.b64decode(PNG)
    assert asyncio.run(h3._regles_depart(plan, fiches)) == r and len(vus) == 1 and len(compares) == 1


def test_le_visage_compare_est_celui_de_la_fiche_nommee(h3, monkeypatch):
    """Audit du 30/09 : sur une image à deux personnes, 8 comparaisons sur 9 recadraient l'autre."""
    v = h3.video_h3
    assert "main person" in v.consigne_visage()
    c = v.consigne_visage("Marc (boy, 12, red cap)", "background, left")
    assert "ONE person only: Marc (boy, 12, red cap), expected background, left" in c and "main person" not in c
    fid = v.fiche_creer("Marc", "boy, 12, red cap")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    vus = []
    _faux_chat(monkeypatch, h3, {"la recherche du visage": "{}",
                                 "l'avis sur la ressemblance": '{"ressemblance": "forte", "ecarts": ""}'}, vus)
    monkeypatch.setattr(h3.montage, "planche_visages", lambda images: b"png")
    asyncio.run(h3._comparer_visage(base64.b64decode(PNG), fid, "background, left"))
    assert "ONE person only: Marc (boy, 12, red cap), expected background, left" in vus[0][1]


def test_une_suite_ne_part_pas_d_une_derniere_image_fausse(h3, monkeypatch):
    """Parc, plan 2 : la fin du plan 1 n'avait pas Marc ; la suite l'a recréé autrement.
    Avant chaque suite, la vraie dernière image est contrôlée comme une image de départ."""
    v = h3.video_h3
    fid = v.fiche_creer("Marc", "boy")["id"]
    plans = [{"image_paroles": "a", "ambiance": "", "enchainement": "coupe", "elements": []},
             {"image_paroles": "Marc waves.", "ambiance": "", "enchainement": "suite",
              "elements": [{"nom": "Marc", "debut": "background, left", "mouvement": "waves", "fin": "x"}]}]
    sc = v.scenario_ecrire({"id": "a" * 32, "etat": "en cours", "erreur": "", "plans": plans, "travaux": [],
                            "fiche": fid, "fiches": [], "reglages": {"fiche": fid, "fiches": None}})
    vus = []
    _faux_chat(monkeypatch, h3, {"le contrôle de la dernière image": [
        '{"comptes": [0], "texte_ajoute": false}', '{"comptes": [1], "texte_ajoute": false}',
        "illisible", '{"comptes": [1], "texte_ajoute": true}', "illisible", "illisible"]}, vus)
    arret = h3._controle_derniere_image(sc["id"], 1, base64.b64decode(PNG))
    assert "la dernière image du plan 1 ne montre pas ce que le plan 2 attend (règle 6 : Compté : Marc ×0.)" in arret
    assert h3._controle_derniere_image(sc["id"], 1, base64.b64decode(PNG)) is None
    # Illisible une fois : redemandé ; la bulle ajoutée (règle 8) arrête aussi.
    assert "règle 8 : Texte ou bulle" in h3._controle_derniere_image(sc["id"], 1, base64.b64decode(PNG))
    # Illisible deux fois : on ne tourne pas à l'aveugle (revue du 30/09).
    assert "n'a pas pu être contrôlée" in h3._controle_derniere_image(sc["id"], 1, base64.b64decode(PNG))
    notes = v.scenario_lire(sc["id"])["controles_suite"]
    assert [n["regles"][0]["ok"] for n in notes] == [False, True, True, None] and notes[3]["erreur"]
    # Un élément hors champ au début est compté, et doit être à 0.
    plans[1]["elements"].append({"nom": "Leila", "debut": "off-frame", "mouvement": "walks in", "fin": "left"})
    v.scenario_noter(sc["id"], plans=plans)
    _faux_chat(monkeypatch, h3, {"le contrôle de la dernière image": '{"comptes": [1, 1], "texte_ajoute": false}'}, vus)
    assert "Leila ×1 (doit être hors champ)" in h3._controle_derniere_image(sc["id"], 1, base64.b64decode(PNG))
    assert "must NOT be visible yet" in vus[-1][1]
    plans[1]["elements"].pop()
    v.scenario_noter(sc["id"], plans=plans)
    # « Tourner quand même » : noté, pas arrêté.
    v.scenario_noter(sc["id"], force=True)
    _faux_chat(monkeypatch, h3, {"le contrôle de la dernière image": '{"comptes": [2], "texte_ajoute": false}'}, [])
    assert h3._controle_derniere_image(sc["id"], 1, base64.b64decode(PNG)) is None


def test_le_juge_rend_les_regles_9_a_12_du_plan_tourne(h3, monkeypatch):
    monkeypatch.setattr(h3.montage, "planche", lambda film, debut, duree: (b"png", 4))
    vus = []
    _faux_chat(monkeypatch, h3, {"le contrôle des règles du plan":
                                 '{"regles": [{"n": 10, "ok": false, "pourquoi": "deux Marc"}, '
                                 '{"n": 11, "ok": true}, {"n": 12, "ok": true}]}'}, vus)
    r = asyncio.run(h3._regles_clip(b"film", 0.0, 5.0, ["Marc"], ["data:image/png;base64,AA"],
                                    {"elements": [{"nom": "Marc", "fin": "clapping"}]}))
    assert r[10] == {"ok": False, "pourquoi": "deux Marc"} and r[11]["ok"] is True
    assert vus[0][3] == 2 and "Marc: clapping." in vus[0][1]


def test_la_regle_4_sait_quelles_voix_partent(h3):
    """Revue du 30/09 : la règle 4 disait « suivie » pour une voix qui ne partait pas."""
    v = h3.video_h3
    ids = [v.fiche_creer(n, "x")["id"] for n in ("A", "B", "C", "D")]
    fiches = [{"id": i, "nom": n, "genre": "personne", "voix": {"langue": "French"}} for i, n in zip(ids, "ABCD")]
    tous = "A dit « Un. » B dit « Deux. » C dit « Trois. » D dit « Quatre. »"
    assert h3._voix_envoyees({"enchainement": "suite", "image_paroles": tous}, fiches) == set()
    assert h3._voix_envoyees({"enchainement": "coupe", "image_paroles": tous}, fiches) == set(ids[:3])
    # Parti d'une image sans photo de fiche : mode « première image », aucune voix.
    assert h3._voix_envoyees({"enchainement": "coupe", "image_depart": "x", "image_paroles": tous}, fiches) == set()
    # Parc, 30/09 : seuls ceux qui parlent dans le plan emportent leur voix.
    assert h3._voix_envoyees({"enchainement": "coupe", "image_paroles": "D dit « Oui. » A sourit."},
                             fiches) == {ids[3]}
    assert h3._voix_envoyees({"enchainement": "coupe", "image_paroles": "A et B marchent."}, fiches) == set()


def test_trop_de_photos_avec_l_image_de_depart_garde_les_visages_et_les_voix(h3):
    """Film parc2, 30/09 : 4 + 4 + 1 photos et l'image de départ dépassaient 9 images ;
    le plan partait en « première image », sans fiche ni voix. Le visage de face de
    chaque personne suffit alors, et la voix part."""
    v = h3.video_h3
    ids = [v.fiche_creer(n, "x")["id"] for n in ("A", "B", "C")]
    for fid in ids:
        for angle in ("face", "profil", "trois_quarts", "pied"):
            v.fiche_poser_image(fid, angle, PNG)
    assert v.photos_avec_depart(ids[:1]) == (4, False)
    assert v.photos_avec_depart(ids) == (3, True)
    fiches = [{"id": i, "nom": n, "genre": "personne", "voix": {"langue": "French"}} for i, n in zip(ids, "ABC")]
    assert h3._voix_envoyees({"enchainement": "coupe", "image_depart": "x",
                              "image_paroles": "A dit « Un. » B dit « Deux. » C dit « Trois. »"}, fiches) == set(ids)


# --- Visages (FaceRefine, 30/09) : le graphe, le script, la route. ---------------

def _demande_de(code):
    return json.loads(base64.b64decode(re.search(r'b64decode\("([^"]+)"\)', code).group(1)))


def test_visages_le_graphe_suit_les_sorties_des_noeuds(sandbox):
    vi = sandbox.visages
    g = vi.graphe([("left_most", 2), ("right_most", 1)])
    assert {n["class_type"] for n in g.values()} <= set(vi.CLASSES)
    for b, choix in ((100, "left_most"), (200, "right_most")):
        k = lambda i: str(b + i)  # noqa: E731
        assert g[k(1)]["inputs"]["select"] == choix and g[k(1)]["inputs"]["identity_track"] is False
        ref = g[k(2)]["inputs"]
        # Taille et longueur du recadrage, sorties 4, 5, 6 du suiveur.
        assert (ref["width"], ref["height"], ref["length"]) == ([k(1), 4], [k(1), 5], [k(1), 6])
        # Le modèle patché par PerFrameDenoise (sortie 2), pas celui du chargeur.
        assert g[k(5)]["inputs"]["model"] == g[k(6)]["inputs"]["model"] == [k(4), 2]
        assert g[k(6)]["inputs"]["steps"] == 4 and g[k(6)]["inputs"]["denoise"] == vi.DEBRUITAGE
    # Photos numérotées de suite : 2 pour le premier, 1 pour le second.
    assert [g[i]["inputs"]["image"] for i in ("110", "111", "210")] == ["ref_0.png", "ref_1.png", "ref_2.png"]
    assert "<Picture 1>" in g["102"]["inputs"]["prompt"] and "<Picture 2>" in g["102"]["inputs"]["prompt"]
    # La passe 2 part de la passe 1 ; la sortie porte le son d'origine.
    assert g["201"]["inputs"]["images"] == ["109", 0] and g["209"]["inputs"]["base_images"] == ["109", 0]
    assert g["90"]["inputs"]["images"] == ["209", 0] and g["90"]["inputs"]["audio"] == ["2", 1]


def test_visages_epingle_ses_sources_et_n_installe_ni_insightface_ni_audiolock(sandbox):
    vi = sandbox.visages
    commandes = " ".join(vi.COMMANDES)
    assert vi.FR_COMMIT in commandes and "ultralytics==" in commandes
    assert "insightface" not in commandes.lower() and "AudioLock" not in commandes
    assert len(vi.FR_COMMIT) == 40 and len(vi.DETECTEUR_REVISION) == 40


def test_visages_chaque_passage_part_sur_la_grille_h3_et_revient_a_sa_longueur(sandbox):
    # 30/09 : FaceRefine complète un passage hors grille (17k+5) avec l'image de référence ;
    # passages de 119 images portés à 124, visages des ~11 dernières en bouillie violet et or.
    vi = sandbox.visages
    assert [vi.sur_la_grille(n) for n in (1, 5, 6, 22, 34, 85, 119, 124, 125)] == [5, 5, 22, 22, 39, 90, 124, 124, 141]
    for n in range(1, 200):
        o = vi.ordre_sur_la_grille(n)
        assert len(o) == vi.sur_la_grille(n) and o[:n] == list(range(n)) and set(o) <= set(range(n))
        # Le miroir : jamais un saut de plus d'une image, donc le même plan, sans à-coup.
        assert all(abs(x - y) <= 1 for x, y in zip(o, o[1:]))
    assert vi.ordre_sur_la_grille(3) == [0, 1, 2, 1, 0]
    assert vi.estimation_passages([(119, 1)]) == vi.estimation_passages([(124, 1)])
    s = vi._SCRIPT
    # La source suit l'ordre ; la sortie est recoupée à [de, a), image ET son, avant le bout à bout.
    assert 'P["ordre"]' in s and "trim=end_frame=" in s and "atrim=end=" in s and "apad=whole_dur=" in s


def test_visages_le_devis_refuse_le_trop_long_et_le_trop_nombreux(sandbox):
    vi = sandbox.visages
    d = vi.prix(123, 2)
    assert 0 < d["estime_usd"] < d["pire_usd"] and d["delai_s"] <= vi.DUREE_MAX_S
    assert d["mesure"] is True and d["secondes_estimees"] < 300
    for images, sujets in ((0, 1), (123, 0), (123, 3), (2000, 2)):
        with pytest.raises(ValueError):
            vi.prix(images, sujets)


def test_visages_le_script_prend_les_photos_des_fiches_et_le_delai_de_la_location(h3):
    v, vi = h3.video_h3, h3.visages
    lea, marc = v.fiche_creer("Léa", "femme")["id"], v.fiche_creer("Marc", "homme")["id"]
    ballon = v.fiche_creer("ballon", "ballon orange", genre="objet")["id"]
    for f in (lea, marc, ballon):
        v.fiche_poser_image(f, "face", PNG)
    code = vi.construire_script(b"mp4", [(lea, "left_most"), (marc, "right_most")], 124, 247)
    importes = {n.names[0].name.split(".")[0] for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Import)}
    assert not importes & {"comfy", "nodes", "folder_paths", "ultralytics"}
    d = _demande_de(code)
    assert (d["de"], d["a"]) == (124, 247) and sorted(d["images"]) == ["ref_0.png", "ref_1.png"]
    assert d["delai_s"] == vi.delai_s(123, 2) and d["detecteur"]["revision"] == vi.DETECTEUR_REVISION
    with pytest.raises(ValueError, match="objet"):
        vi.demande(b"mp4", [(ballon, "left_most")], 0, 10)
    with pytest.raises(ValueError, match="Place"):
        vi.demande(b"mp4", [(lea, "au_milieu")], 0, 10)
    assert "nœuds" in vi.phrase_d_echec("NOEUD_ABSENT ['H3FaceTrackCrop']")
    assert vi.phrase_d_echec("rien") == ""


def _source_visages(h3, monkeypatch, tmp_path):
    _source_agrandir(h3, monkeypatch, tmp_path, images=370)
    lance = []
    monkeypatch.setattr(h3, "run_visages", lambda *a: lance.append(a))
    v = h3.video_h3
    fid = v.fiche_creer("Léa", "femme")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    monkeypatch.setattr(v, "scenario_lire", lambda sid: {"fins_images": [124, 247, 370]})
    _autoriser(h3)
    return lance, fid


def test_visages_traite_le_plan_demande_du_scenario(h3, monkeypatch, tmp_path):
    lance, fid = _source_visages(h3, monkeypatch, tmp_path)
    d = client(h3).get("/video-h3/visages/prix?job=" + "b" * 32 + "&scenario=" + "d" * 32 + "&plan=3",
                       headers=CLE).json()
    assert (d["de"], d["a"]) == (247, 370) and d["devis"]["images"] == 123
    r = client(h3).post("/video-h3/visages", headers=CLE, json={
        "job": "b" * 32, "scenario": "d" * 32, "plan": 2, "sujets": [{"fiche": fid, "choix": "left_most"}]})
    assert r.status_code == 200, r.text
    jid, code, delai = lance[0]
    assert (_demande_de(code)["de"], _demande_de(code)["a"]) == (124, 247) and delai == h3.visages.delai_s(123, 1)
    v = h3.read_job(jid)["video"]
    assert not v["moteur"].startswith("MiniMax H3") and v["source"] == "b" * 32
    assert h3.read_job(jid)["titre"] == "Le parc — visages refaits"
    # Sans scénario : tout le clip.
    client(h3).post("/video-h3/visages", headers=CLE, json={"job": "b" * 32, "sujets": [{"fiche": fid}]})
    assert (_demande_de(lance[1][1])["de"], _demande_de(lance[1][1])["a"]) == (0, 370)


def test_visages_refuse_avant_de_louer(h3, monkeypatch, tmp_path):
    lance, fid = _source_visages(h3, monkeypatch, tmp_path)
    corps = {"job": "b" * 32, "sujets": [{"fiche": fid}]}
    assert client(h3).post("/video-h3/visages", headers=CLE, json={**corps, "scenario": "d" * 32,
                                                                     "plan": 4}).status_code == 400
    assert client(h3).post("/video-h3/visages", headers=CLE, json={**corps, "de": 300, "a": 400}).status_code == 400
    assert client(h3).post("/video-h3/visages", headers=CLE, json={**corps, "sujets": []}).status_code == 422
    assert client(h3).post("/video-h3/visages", headers=CLE, json={**corps, "sujets": ["x"]}).status_code == 400

    def refus(*a, **k):
        raise h3.budget_modal.BudgetDepasse("Budget Modal du mois atteint.")

    monkeypatch.setattr(h3.budget_modal, "verifier", refus)
    r = client(h3).post("/video-h3/visages", headers=CLE, json=corps)
    assert r.status_code == 429 and "Budget" in r.json()["detail"]
    monkeypatch.setattr(h3, "modal_configured", lambda: False)
    assert client(h3).post("/video-h3/visages", headers=CLE, json=corps).status_code == 503
    assert lance == []
    # Sans la copie d'autorisation H3 : rien.
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(h3.video_h3, "FICHE_AUTORISATION", tmp_path / "absente.json")
    assert client(h3).post("/video-h3/visages", headers=CLE, json=corps).status_code == 403


def test_visages_encaisse_la_location_meme_en_echec(h3, monkeypatch):
    jid = "f" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: {"exit_code": 4})

    def fini(j, ou, resultat):
        job = h3.read_job(j)
        job.update({"status": "failed", "stderr": "NOEUD_ABSENT ['H3FaceStitch']"})
        h3.write_job(j, job)

    monkeypatch.setattr(h3, "finish_execution", fini)
    vus = []
    monkeypatch.setattr(h3.budget_modal, "consommer", lambda *a, **k: vus.append(a) or {"usd": 1})
    h3.run_visages(jid, "code", 600)
    assert vus and vus[0][:2] == ("video", h3.visages.GPU)
    assert "nœuds" in h3.read_job(jid)["error"]


def test_visages_le_devis_dit_les_personnes_et_les_plans_du_clip(h3, monkeypatch, tmp_path):
    lance, fid = _source_visages(h3, monkeypatch, tmp_path)
    v = h3.video_h3
    marc = v.fiche_creer("Marc", "homme")["id"]
    sans_photo = v.fiche_creer("Zoé", "femme")["id"]
    ballon = v.fiche_creer("ballon", "orange", genre="objet")["id"]
    for f in (marc, ballon):
        v.fiche_poser_image(f, "face", PNG)
    job = h3.read_job("b" * 32)
    job["video"] = {"scenario": "d" * 32, "fiches": [{"id": i} for i in (marc, ballon, sans_photo, fid)]}
    h3.write_job("b" * 32, job)
    d = client(h3).get("/video-h3/visages/prix?job=" + "b" * 32 + "&sujets=2", headers=CLE).json()
    # Les personnes du clip avec photo, dans son ordre ; pas l'objet.
    assert [f["id"] for f in d["fiches"]] == [marc, fid]
    assert d["scenario"] == "d" * 32 and [p["plan"] for p in d["plans"]] == [1, 2, 3]
    assert (d["de"], d["a"]) == (0, 370) and d["devis"]["sujets"] == 2
    # Trop de personnages : le devis le dit, sans erreur.
    assert "refus" in client(h3).get("/video-h3/visages/prix?job=" + "b" * 32 + "&sujets=3",
                                     headers=CLE).json()["devis"]


def test_la_page_propose_de_refaire_les_visages(h3):
    page = client(h3).get("/video-h3", headers=CLE).text
    assert 'id="clip_visages"' in page and 'id="montage_visages"' in page
    assert "/video-h3/visages/prix?job=" in page and "Refaire les visages" in page
    assert page.count("blocVisages(") >= 4


def test_visages_le_2e_plus_grand_et_l_avertissement_du_passant(h3):
    """30/09, parc plans 1 et 4 : « right_most » a suivi un passant de 7 px au lieu de Marc."""
    vi = h3.visages
    g = vi.graphe([("left_most", 1), ("largest_face_2", 1)])
    assert (g["101"]["inputs"]["select"], g["101"]["inputs"]["select_index"]) == ("left_most", 0)
    assert (g["201"]["inputs"]["select"], g["201"]["inputs"]["select_index"]) == ("largest_face", 1)
    rapports = ["[H3FaceRefine] frames=124  face=124 (100%)  body-fallback=0  interpolated=0",
                "[H3FaceRefine] face height  min=30px  mean=34px  max=40px",
                "[H3FaceRefine] frames=124  face=16 (13%)  body-fallback=0  interpolated=108",
                "[H3FaceRefine] face height  min=7px  mean=7px  max=7px"]
    dits = vi.avertissements(rapports, ["Leila", "Marc"])
    assert len(dits) == 1 and dits[0].startswith("Marc") and "7 px" in dits[0]
    assert vi.avertissements(rapports[:2], ["Leila"]) == []
    job = {"stdout": "x\nVISAGES " + json.dumps({"rapports": rapports}), "video": {"sujets": [{"fiche": "?"}] * 2}}
    h3._visages_avertir(job)
    assert "Personnage 2" in job["avertissements"][0]


# --- 30/09 : la langue et l'émotion d'une réplique, la voix par langue --------------
# Demande du propriétaire : « Leila part d'une voix française et la transforme en anglais,
# à l'inverse pour l'américain […] avec aussi l'utilisation des émotions dans H3, menu
# déroulant pour expliquer la syntaxe. le llm qui crée le script connaît cette syntaxe ».

def test_la_marque_donne_la_langue_et_le_ton_que_joue_h3(h3):
    v = h3.video_h3
    assert v.marque_de_replique("[anglais, joie] I made the team!", "French") == ("English", "joie", "I made the team!")
    assert v.marque_de_replique("[sad] Elle n'est pas venue…", "French") == ("French", "tristesse",
                                                                          "Elle n'est pas venue…")
    assert v.marque_de_replique("[French; whisper] Chut.", "English") == ("French", "chuchote", "Chut.")
    # Deux émotions, un mot inconnu : ce n'est pas une marque, elle reste dite.
    for pas_une in ("[joie, colère] Non.", "[soupir] Enfin !"):
        assert v.marque_de_replique(pas_une, "French") == ("French", None, pas_une)
    joie = v.EMOTIONS["joie"][1]
    assert v.balises_paroles("Elle crie « [English, joy] I made it! »", "French") == \
        "Elle crie (S1), %s, <d>[English] I made it!</d>" % joie
    # Le guide de MiniMax : le ton s'écrit à côté de la réplique, la voix vient de l'<Audio>.
    assert v.attribuer_repliques("Léa dit « [tristesse] Il est parti. »", [("Léa", "French")]) == \
        "<Subject 1> (S1) dit %s, <d>[French] Il est parti.</d>" % v.EMOTIONS["tristesse"][1]
    assert v.marques_inconnues("Léa : « [joyeus] Salut ! » puis « [anglais] Hi! »") == ["joyeus"]
    # Chaque émotion que le chat apprend se relit.
    assert all(v.emotion_connue(e) for e in v.EMOTIONS_ANGLAIS)
    assert len({v.emotion_connue(e) for e in v.EMOTIONS_ANGLAIS}) == len(v.EMOTIONS)


def test_le_chat_du_studio_connait_la_marque(h3):
    v = h3.video_h3
    for consigne in (v.consigne_decoupage("Léa dit « Bonjour » à Tyler."),
                     v.consigne_correction([{"image_paroles": "x"}], "trop sombre")):
        assert v.MARQUES in consigne
    assert "[English, joy]" in v.MARQUES and all(e in v.MARQUES for e in v.EMOTIONS_ANGLAIS)


def test_une_marque_illisible_est_refusee_avant_de_louer(h3):
    with pytest.raises(ValueError, match="Marque de réplique inconnue : « \\[joyeus\\] »"):
        h3.video_h3.preparer(demande(image_paroles="Elle dit « [joyeus] Salut ! »"))


def test_la_voix_par_langue_se_pose_se_retire_et_part_avec_la_bonne_replique(h3, sans_regles):
    v = h3.video_h3
    leila = v.fiche_creer("Leila", "x")["id"]
    v.fiche_poser_image(leila, "face", PNG)
    with pytest.raises(ValueError, match="pas encore de voix"):
        v.fiche_poser_voix_langue(leila, "English", WAV, 4.0, {})
    v.fiche_poser_voix(leila, WAV, 4.0, "generee", "French")
    with pytest.raises(ValueError, match="Langue de voix inconnue"):
        v.fiche_poser_voix_langue(leila, "French", WAV, 4.0, {})
    anglais = WAV + b"EN"
    v.fiche_poser_voix_langue(leila, "English", anglais, 4.0, {"source": "clonee"})
    fiche = v.fiche_lire(leila)
    assert v.langues_de_voix(fiche) == ["French", "English"]
    assert fiche["voix_langues"]["English"]["depuis"] == "French"
    assert v.fiche_voix(leila, "English") == anglais and v.fiche_voix(leila, "French") == WAV
    assert v.fiche_voix(leila, "German") is None
    # Une réplique en français, une en anglais : les deux voix partent, chacune pour sa langue.
    d = demande(mode="references", fiches=[leila], langues={leila: "French"},
                image_paroles="Leila dit « [joie] J'ai réussi ! » puis « [English, joy] I made it! »")
    plan = v.preparer(d)
    invite = plan["resume_public"]["invite"]
    assert "<Audio 1> is the voice-timbre reference for <Subject 1> (S1) speaking French." in invite
    assert "<Audio 2> is the voice-timbre reference for <Subject 1> (S1) speaking English." in invite
    assert "summary: [reference generation + audio reference] The target video is a single shot with " \
           "<Subject 1>. It uses <Audio 1> as the voice-timbre reference for <Subject 1> speaking French " \
           "and <Audio 2> as the voice-timbre reference for <Subject 1> speaking English. " in invite
    assert "using the voice timbre referenced from <Audio 2>, overjoyed" in invite
    assert plan["demande"]["sons"] == {"voix_0.wav": base64.b64encode(WAV).decode(),
                                       "voix_1.wav": base64.b64encode(anglais).decode()}
    # Qu'une langue : un seul <Audio>, dans la forme d'avant.
    plan = v.preparer(dict(d, image_paroles="Leila dit « [English] Hi! »"))
    assert plan["demande"]["sons"] == {"voix_0.wav": base64.b64encode(anglais).decode()}
    assert "<Audio 1> is the voice-timbre reference for <Subject 1> (S1)." in plan["resume_public"]["invite"]
    # Sans voix anglaise, l'anglais part avec la voix d'origine (le timbre au moins).
    v.fiche_retirer_voix_langue(leila, "English")
    assert "voix_langues" not in v.fiche_lire(leila)
    plan = v.preparer(dict(d, image_paroles="Leila dit « [English] Hi! »"))
    assert plan["demande"]["sons"] == {"voix_0.wav": base64.b64encode(WAV).decode()}
    with pytest.raises(ValueError, match="pas de voix dans cette langue"):
        v.fiche_retirer_voix_langue(leila, "English")
    # Reposer la voix d'origine efface les voix clonées depuis l'ancienne.
    v.fiche_poser_voix_langue(leila, "English", anglais, 4.0, {})
    v.fiche_poser_voix(leila, WAV, 4.0, "exemple", "French")
    assert "voix_langues" not in v.fiche_lire(leila) and v.fiche_voix(leila, "English") is None


def test_voix_du_plan_une_voix_par_personnage_et_par_langue(h3):
    v = h3.video_h3
    leila = {"voix": {"langue": "French"}, "voix_langues": {"English": {}}}
    tyler = {"voix": {"langue": "English"}}
    dites = [(0, "French"), (1, "French"), (0, "English"), (0, "French")]
    assert v.voix_du_plan(dites, [leila, tyler]) == [(0, "French"), (0, "English"), (1, "English")]
    assert v.voix_du_plan([(1, "French")], [leila, {}]) == []
    assert len(v.voix_du_plan([(k, l) for k in range(2) for l in ("French", "English")],
                              [leila, dict(tyler, voix_langues={"French": {}})])) == v.VOIX_PAR_PLAN


def test_la_regle_4_accepte_la_voix_clonee_et_compte_les_langues(h3):
    r = h3.regles
    leila = {"id": "l1", "nom": "Leila", "genre": "personne", "voix": {"langue": "French"}}
    plan = {"image_paroles": "Leila dit « [anglais, joie] I made it! »"}
    faute = r.regle_voix(plan, [leila], {}, "French")
    assert faute["ok"] is False and "créez-la en anglais" in faute["pourquoi"]
    assert r.regle_voix(plan, [dict(leila, voix_langues={"English": {}})], {}, "French")["ok"] is True
    tyler = {"id": "t1", "nom": "Tyler", "genre": "personne", "voix": {"langue": "English"},
             "voix_langues": {"French": {}}}
    deux = dict(leila, voix_langues={"English": {}})
    quatre = {"image_paroles": "Leila dit « Salut. » puis « [English] Hi. » Tyler dit « Hey. » puis « [French] Salut. »"}
    x = r.regle_voix(quatre, [deux, tyler], {"t1": "English"}, "French")
    assert x["ok"] is False and "4 voix (une par personnage et par langue)" in x["pourquoi"]


def _fiche_qui_parle(h3, source="generee", langue="French"):
    v = h3.video_h3
    fid = v.fiche_creer("Leila", "x")["id"]
    v.fiche_poser_voix(fid, WAV, 4.0, source, langue)
    return fid


def test_la_voix_dans_une_autre_langue_se_demande_et_se_refuse_avant_de_louer(h3, monkeypatch):
    v = h3.video_h3
    c = client(h3)
    sans = v.fiche_creer("Tyler", "x")["id"]
    r = c.post(f"/video-h3/fiches/{sans}/voix/langue", headers=CLE, json={"langue": "English"})
    assert r.status_code == 400 and "Posez d'abord la voix" in r.json()["detail"]
    fid = _fiche_qui_parle(h3)
    for langue, message in (("German", "français et en anglais"), ("French", "déjà dans cette langue")):
        r = c.post(f"/video-h3/fiches/{fid}/voix/langue", headers=CLE, json={"langue": langue})
        assert r.status_code == 400 and message in r.json()["detail"]
    lance = []
    monkeypatch.setattr(h3, "run_voix_langue", lambda *a: lance.append(a))
    r = c.post(f"/video-h3/fiches/{fid}/voix/langue", headers=CLE, json={"langue": "English"})
    assert r.status_code == 503 and lance == []   # Modal pas branché
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    h3.budget_modal.poser("dialogue", 0, h3.budget_modal.plafond_de("dialogue") - 0.01, 1)
    r = c.post(f"/video-h3/fiches/{fid}/voix/langue", headers=CLE, json={"langue": "English"})
    assert r.status_code == 429 and lance == []
    h3.budget_modal.poser("dialogue", 0, 0, 0)
    r = c.post(f"/video-h3/fiches/{fid}/voix/langue", headers=CLE, json={"langue": "English"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued" and job["voix_langue"] == {
        "fiche": fid, "langue": "English", "depuis": "French", "cout_max_usd": job["voix_langue"]["cout_max_usd"]}
    assert len(lance) == 1 and lance[0][:3] == (job["id"], fid, "English")
    # La voix d'origine est générée : son texte est la phrase du Studio, sans écoute.
    d = json.loads(base64.b64decode(re.search(r'"([A-Za-z0-9+/=]{40,})"', lance[0][3]).group(1)))
    assert d["texte_reference"] == v.PHRASE_VOIX["French"] and d["texte"] == v.PHRASE_VOIX["English"]
    # Un exemple téléversé : son texte vient de l'écoute ; sans écoute, rien n'est loué.
    autre = _fiche_qui_parle(h3, "exemple", "English")
    monkeypatch.setattr(h3, "_transcrire_voix", lambda octets: None)
    r = c.post(f"/video-h3/fiches/{autre}/voix/langue", headers=CLE, json={"langue": "French"})
    assert r.status_code == 503 and len(lance) == 1


def test_la_voix_clonee_n_est_posee_que_si_le_studio_l_entend_dire_la_phrase(h3, monkeypatch):
    v = h3.video_h3
    fid = _fiche_qui_parle(h3)
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: {"exit_code": 0, "stdout": "VOIX_OK {}",
                                                              "stderr": "", "artifacts": []})
    monkeypatch.setattr(h3, "_artefact", lambda job, nom: b"WAV-CLONE" if nom == "voix.wav" else None)
    monkeypatch.setattr(h3.montage, "voix_de_reference", lambda wav, maxi: (wav + b"-propre", 5.2))
    entendu = {"texte": "Hello, my name is on my card. The weather is nice today, and I am calmly telling you "
                        "about my day, without rushing."}
    monkeypatch.setattr(h3, "_transcrire_voix", lambda octets: entendu["texte"])
    jid = "e" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    avant = h3.budget_modal.vue("dialogue")["appels"].get("dialogue", 0)
    h3.run_voix_langue(jid, fid, "English", "print(1)")
    job = h3.read_job(jid)
    assert job["status"] == "succeeded" and job["voix_posee"] == {"fiche": fid, "langue": "English"}
    assert v.fiche_voix(fid, "English") == b"WAV-CLONE-propre"
    assert v.fiche_lire(fid)["voix_langues"]["English"]["ecoute"]["part"] >= h3.VOIX_LANGUE_SEUIL
    assert h3.budget_modal.vue("dialogue")["appels"]["dialogue"] == avant + 1
    # Une voix qui dit autre chose n'est pas posée ; la location est comptée quand même.
    v.fiche_retirer_voix_langue(fid, "English")
    entendu["texte"] = "Ah, abelmi."
    jid = "f" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    h3.run_voix_langue(jid, fid, "English", "print(1)")
    job = h3.read_job(jid)
    assert job["status"] == "failed" and "ne dit pas la phrase" in job["error"]
    assert v.fiche_voix(fid, "English") is None
    assert h3.budget_modal.vue("dialogue")["appels"]["dialogue"] == avant + 2


def test_la_page_explique_la_marque_et_cree_la_voix_dans_l_autre_langue(h3):
    html = client(h3).get("/video-h3").text
    assert "__AIDE_MARQUES" not in html
    assert html.count("<summary>Langue et émotion d'une réplique</summary>") == 2
    assert 'data-cible="scenario"' in html and 'data-cible="image_paroles"' in html
    assert "Insérer la marque" in html and "marque_inserer" in html
    for nom, ton in h3.video_h3.EMOTIONS.values():
        assert "<td>[%s]</td>" % nom in html
    assert "async function voixLangue(" in html and "/voix/langue" in html
    assert "Créer sa voix en " in html
    fid = _fiche_qui_parle(h3)
    h3.video_h3.fiche_poser_voix_langue(fid, "English", WAV, 4.0, {"source": "clonee"})
    fiche = client(h3).get(f"/video-h3/fiches/{fid}", headers=CLE).json()
    assert list(fiche["voix_langues"]) == ["English"]
    assert fiche["voix_langues"]["English"]["son"].startswith("data:audio/wav;base64,")
    r = client(h3).delete(f"/video-h3/fiches/{fid}/voix/langue/English", headers=CLE)
    assert r.status_code == 200 and r.json()["voix_langues"] == {}


def test_une_marque_inventee_par_le_chat_est_ramenee_a_ce_qui_se_lit(h3):
    """Découpage réel du 30/09 : « [English, amused] Hey, are you lost? » faisait refuser
    tout le découpage comme réplique inventée."""
    v = h3.video_h3
    scenario = "Tyler dit, amusé : « Hey, are you lost? » Léa soupire : « [soupir] Enfin. »"
    reponse = json.dumps([
        {"image_paroles": "Tyler says « [English, amused] Hey, are you lost? »", "ambiance": "", "enchainement": "coupe",
         "elements": []},
        {"image_paroles": "Léa says « [French, sarcastic] [soupir] Enfin. »", "ambiance": "", "enchainement": "suite",
         "elements": []}], ensure_ascii=False)
    plans = v.lire_decoupage(reponse, scenario)
    assert "« [English, amused] Hey, are you lost? »" in plans[0]["image_paroles"]   # « amused » se lit
    assert v.marque_de_replique("[English, amused] Hey!", "French") == ("English", "amusement", "Hey!")
    plans = v.lire_decoupage(reponse.replace("amused", "smug"), scenario)
    assert "« [English] Hey, are you lost? »" in plans[0]["image_paroles"]
    # Le mot inconnu tombe ; ce que l'auteur a écrit entre crochets reste à lui.
    assert "« [French] [soupir] Enfin. »" in plans[1]["image_paroles"]
    assert v.marque_de_replique("[English, amusement] Hey!", "French") == ("English", "amusement", "Hey!")
    with pytest.raises(ValueError, match="inventé ou changé"):
        v.lire_decoupage(reponse.replace("Hey, are you lost?", "Hi, lost?"), scenario)


def test_le_studio_marque_les_repliques_d_apres_le_chat(h3, monkeypatch):
    """Découpage réel du 30/09 : le chat n'a posé aucune marque manquante ; « I made the
    team! » de Leila serait parti en français, avec sa voix française."""
    v = h3.video_h3
    plans = [
        {"image_paroles": "Tyler says, amused: « Hey, are you lost? » Leila replies: « [English] Yes! »",
         "ambiance": "", "enchainement": "coupe"},
        {"image_paroles": "Tyler, embarrassed: « Je… parle un peu français. » Leila: « [French, laughing] Trop "
                          "mignon ! » Wild with joy, Leila shouts: « I made the team! »",
         "ambiance": "", "enchainement": "suite"}]
    consigne = v.consigne_marquer(plans)
    # Les répliques sans marque complète, chacune avec sa phrase ; la marque entière n'est pas redemandée.
    assert "1. Tyler says, amused: « Hey, are you lost? »" in consigne
    assert "2. Leila replies: « [English] Yes! »" in consigne and "Trop mignon" not in consigne
    assert "4. Wild with joy, Leila shouts: « I made the team! »" in consigne
    reponse = ('Voici : [{"n": 1, "language": "English", "emotion": "amusement"}, '
               '{"n": 2, "language": "French", "emotion": "joy"}, '
               '{"n": 3, "language": "French", "emotion": "awkwardness"}, '
               '{"n": 4, "language": "English", "emotion": "joy"}]')
    marques = v.poser_marques(plans, reponse)
    assert "« [English, amusement] Hey, are you lost? »" in marques[0]["image_paroles"]
    assert "« [English, joie] Yes! »" in marques[0]["image_paroles"]   # la langue de l'auteur l'emporte
    assert "« [French, gêne] Je… parle un peu français. »" in marques[1]["image_paroles"]
    assert "« [French, laughing] Trop mignon ! »" in marques[1]["image_paroles"]
    assert "« [English, joie] I made the team! »" in marques[1]["image_paroles"]
    assert plans[1]["image_paroles"].endswith("« I made the team! »")   # l'original n'est pas touché
    assert v._repliques_a_marquer(marques) == []
    # Une valeur illisible est ignorée ; une réponse illisible est dite.
    assert "« [English] Hey" in v.poser_marques(plans, '[{"n": 1, "language": "English", "emotion": "smug"}]')[0][
        "image_paroles"]
    with pytest.raises(ValueError, match="ne se lit pas"):
        v.poser_marques(plans, "Je ne sais pas.")
    assert v.consigne_marquer([{"image_paroles": "« [English, joy] Hi! »", "ambiance": ""}]) == ""
    # Par la route : un chat qui ne répond pas ne perd pas le découpage.
    _faux_chat(monkeypatch, h3, {"les marques des répliques": "rien"}, [])
    assert asyncio.run(h3._marquer_repliques(plans)) == (plans, {"erreur": "La réponse du chat sur les marques "
                                                                          "ne se lit pas."})


def test_un_scenario_a_six_plans_mais_pas_cinq_raccords_d_affilee(h3):
    """30/09 : 5 plans, puis 6 le soir (décisions du propriétaire ; une réplique par plan,
    et le film campus en a six) ; la limite mesurée des raccords reste."""
    v = h3.video_h3
    assert v.SCENARIO_PLANS_MAX == 6 and v.PLANS_MAX == 4
    plan = lambda e: {"image_paroles": "x", "ambiance": "", "enchainement": e}
    assert len(v.verifier_plans([plan("coupe")] + [plan("suite")] * 3 + [plan("coupe"), plan("suite")])) == 6
    with pytest.raises(ValueError, match="4 plans au plus d'affilée sans « coupe »"):
        v.verifier_plans([plan("coupe")] + [plan("suite")] * 4)
    assert "never more than 4 shots in a row" in v.consigne_decoupage("Un film.")
    assert client(h3).get("/video-h3/etat", headers=CLE).json()["scenario"] == {"plans_max": 6}


def test_le_ton_n_est_pas_redit_quand_la_phrase_le_dit_deja(h3):
    """Vérification à blanc du film campus, 30/09 : « says, amused: amused, a playful smile
    in the voice, » partait à H3. Les cinq phrases du découpage réel."""
    v = h3.video_h3
    sujets = [("Leila", "French"), ("Tyler", "English")]
    for texte in ("Tyler stops and says, amused: « [English, amusement] Hey, are you lost? »",
                  "Tyler tries in French, embarrassed: « [French, awkwardness] Je… parle un peu français. »",
                  "Leila bursts out laughing, saying: « [French, laughing] Ton accent est trop mignon ! »",
                  "Leila faces the board, overjoyed, and yells: « [English, joy] I made the team! »",
                  "Tyler, enthusiastic, replies to her: « [French, enthusiasm] C'est génial, Leila ! »"):
        emotion = v.marque_de_replique(texte[texte.index("«") + 2:texte.rindex("»") - 1], "French")[1]
        assert emotion
        sortie = v.attribuer_repliques(texte, sujets)
        assert v.EMOTIONS[emotion][1] not in sortie, sortie
    # Dit nulle part avant la réplique : le ton est écrit, une fois.
    sortie = v.attribuer_repliques("Leila replies with relief: « [English, calm] Yes! »", sujets)
    assert sortie.count("calmly and gently") == 1
    # La phrase d'avant ne compte pas : le « amused » de Tyler ne tait pas le ton de Leila.
    sortie = v.attribuer_repliques("Tyler says, amused: « Hi. » Leila answers: « [English, amusement] Hi! »", sujets)
    assert sortie.count(v.EMOTIONS["amusement"][1]) == 1


def test_la_regle_1_lit_the_only_comme_un_article(h3):
    """Film campus, 30/09 : « the only bulletin board » (consigne du découpage) était dit
    absent d'un texte qui disait « towards the bulletin board »."""
    r = h3.regles
    assert r.nomme_dans("the only bulletin board", "Leila faces right towards the bulletin board.")
    assert not r.nomme_dans("the only bulletin board", "Leila faces right towards the board.")


def test_retention_nomme_les_images_de_chaque_sujet_comme_le_guide(h3):
    """30/09, remarque du propriétaire : « of the reference pictures » ne disait pas
    lesquelles. Guide de MiniMax (ref_en, 4.1) : « <Subject 1>: fully_preserved - … »."""
    v = h3.video_h3
    t = v.sujets_des_fiches([4, 4, 1, 1], objets={2: "objet", 3: "pose"})
    assert ("<Subject 1> (appears in [Shot 1]): fully_preserved - the face, hair and clothing of the person in <Picture 1>, "
            "<Picture 2>, <Picture 3>, <Picture 4> are retained") in t
    assert "<Subject 2> (appears in [Shot 1]): fully_preserved - the face, hair and clothing of the person in <Picture 5>, " in t
    assert "<Subject 3> (appears in [Shot 1]): fully_preserved - the shape, colour and size of the object in <Picture 9> " in t
    assert "<Subject 4> (appears in [Shot 1]): fully_preserved - a hand pose only: the hands and fingers take exactly the " \
           "position of <Picture 10>" in t
    assert "reference pictures" not in t


def test_summary_et_appears_in_comme_le_guide(h3):
    """30/09, demande du propriétaire : « ajoute summary et appears in ». Syntaxe relue
    le même jour dans skills/h3-prompt-writing/references/ref-en.txt (3 et 4.1)."""
    v = h3.video_h3
    # Seuls les sujets que le plan nomme « appear » ; le summary vient entre les deux sections.
    t = v.sujets_des_fiches([1, 1, 1], presents={0, 2}, voix={0: 1}, parleurs={0: 2})
    assert t.index("subject_definitions:") < t.index(" summary: ") < t.index(" retention_analysis: ")
    assert "<Subject 1> (appears in [Shot 1]): fully_preserved" in t
    assert "<Subject 2>: fully_preserved" in t and "<Subject 2> (appears" not in t
    assert "<Subject 3> (appears in [Shot 1]): fully_preserved" in t
    assert "summary: [reference generation + audio reference] The target video is a single shot with " \
           "<Subject 1> and <Subject 3>. It uses <Audio 1> as the voice-timbre reference for <Subject 1>. " in t
    assert "<Audio 1> is the voice-timbre reference for <Subject 1> (S2)." in t
    # Pas de (Sx) dans retention_analysis (ref-en.txt, 5.4).
    assert "(S" not in t.split(" retention_analysis: ")[1]
    # Le summary n'introduit aucune étiquette nouvelle.
    resume = t.split(" summary: ")[1].split(" retention_analysis: ")[0]
    definies = set(re.findall(r"<(?:Subject|Picture|Audio) \d+>", t.split(" summary: ")[0]))
    assert set(re.findall(r"<(?:Subject|Picture|Audio) \d+>", resume)) <= definies


def _finaliser_monte(h3, monkeypatch, tmp_path):
    """Un film de 370 images en trois plans ; les locations réussissent tout de suite."""
    lance, fid = _source_visages(h3, monkeypatch, tmp_path)
    loues = []

    def reussir(quoi):
        def run(jid, code, delai):
            loues.append((quoi, jid, _demande_de(code)))
            job = h3.read_job(jid)
            job["status"] = "succeeded"
            h3.write_job(jid, job)
        return run

    monkeypatch.setattr(h3, "run_visages", reussir("visages"))
    monkeypatch.setattr(h3, "run_agrandir", reussir("agrandir"))
    monkeypatch.setattr(h3, "_recoller_tous", lambda videos: b"".join(videos))
    monkeypatch.setattr(h3.montage, "extraire", lambda video, de, a: b"plan-%d-%d" % (de, a))
    # Le fil tourne ici, pour lire son résultat.
    monkeypatch.setattr(h3, "_finaliser_lancer", h3.run_finaliser)
    plans = [{"de": 0, "a": 124, "sujets": [{"fiche": fid, "choix": "left_most"}]},
             {"de": 124, "a": 247, "sujets": []},
             {"de": 247, "a": 370, "sujets": [{"fiche": fid, "choix": "right_most"}]}]
    return loues, plans


def test_finaliser_fait_les_visages_puis_la_4k_en_une_location_chacun(h3, monkeypatch, tmp_path):
    loues, plans = _finaliser_monte(h3, monkeypatch, tmp_path)
    r = client(h3).post("/video-h3/finaliser", headers=CLE, json={"job": "b" * 32, "plans": plans, "echelle": "4k"})
    assert r.status_code == 200, r.text
    job = h3.read_job(r.json()["id"])
    assert job["status"] == "succeeded", job.get("error")
    # 30/09 : une location par étape, un seul chargement des modèles, les passages en série
    # (sept locations en parallèle avaient lu ensemble les 26 Go du modèle de texte).
    assert [q for q, _, _ in loues] == ["visages", "agrandir"]
    v = loues[0][2]
    # Visages des plans 1 et 3 seulement : le plan 2 n'a personne.
    assert [(x["de"], x["a"], x["source"]) for x in v["passages"]] == [(0, 124, "source_0.mp4"),
                                                                      (247, 370, "source_1.mp4")]
    assert v["delai_s"] == h3.visages.delai_passages([(124, 1), (123, 1)])
    # Envoyés sur la grille H3 : 124 déjà dessus, 123 porté à 124 par son miroir.
    assert [len(x["ordre"]) for x in v["passages"]] == [124, 124] and v["passages"][1]["ordre"][-2:] == [122, 121]
    # Les photos de chaque passage sont les siennes : la 2e passe lit la photo suivante.
    photos = [[n["inputs"]["image"] for n in x["graphe"].values() if n["class_type"] == "LoadImage"]
              for x in v["passages"]]
    assert photos == [["ref_0.png"], ["ref_1.png"]] and sorted(v["images"]) == ["ref_0.png", "ref_1.png"]
    # La 4K des trois plans, coupée à leurs fins, en une location.
    assert loues[1][2]["coupes"] == [0, 124, 247, 370]
    f = job["finalisation"]
    assert h3.read_job(f["film_visages"])["video"]["moteur"] == "MiniMax H3 (montage)"
    # Le film final est en 4K : il n'entre pas dans un montage de clips 480p.
    assert h3.read_job(f["film"])["video"]["moteur"] == "SeedVR2 (agrandissement)"
    assert not job["video"]["moteur"].startswith("MiniMax H3")
    assert job["video"]["devis"]["pire_usd"] > job["video"]["devis"]["estime_usd"] > 0


def test_finaliser_attend_le_budget_puis_reprend_sans_relouer(h3, monkeypatch, tmp_path):
    loues, plans = _finaliser_monte(h3, monkeypatch, tmp_path)
    vrai = h3.budget_modal.verifier
    permis = [1]

    def compte(*a, **k):
        if permis[0] <= 0:
            raise h3.budget_modal.BudgetDepasse("Budget Modal du mois atteint.")
        permis[0] -= 1
        return vrai(*a, **k)

    monkeypatch.setattr(h3.budget_modal, "verifier", compte)
    fid = client(h3).post("/video-h3/finaliser", headers=CLE,
                          json={"job": "b" * 32, "plans": plans, "echelle": "4k"}).json()["id"]
    job = h3.read_job(fid)
    assert job["status"] == "attente" and "budget" in job["error"]
    assert [q for q, _, _ in loues] == ["visages"]
    assert job["finalisation"]["film_visages"]   # les visages sont visibles avant la 4K
    permis[0] = 9
    r = client(h3).post("/video-h3/finaliser/%s/reprendre" % fid, headers=CLE)
    assert r.status_code == 200, r.text
    assert h3.read_job(fid)["status"] == "succeeded"
    assert [q for q, _, _ in loues] == ["visages", "agrandir"]
    assert client(h3).post("/video-h3/finaliser/%s/reprendre" % fid, headers=CLE).status_code == 409


def test_finaliser_refuse_des_plans_qui_ne_couvrent_pas_le_film(h3, monkeypatch, tmp_path):
    loues, plans = _finaliser_monte(h3, monkeypatch, tmp_path)
    for mauvais in (plans[:2], [plans[0], plans[2]], [dict(plans[0], sujets=[{"fiche": "x", "choix": "au_fond"}])]
                    + plans[1:], [dict(p, sujets=[]) for p in plans]):
        r = client(h3).post("/video-h3/finaliser", headers=CLE,
                            json={"job": "b" * 32, "plans": mauvais, "echelle": ""})
        assert r.status_code == 422, mauvais
    assert client(h3).post("/video-h3/finaliser", headers=CLE,
                           json={"job": "b" * 32, "plans": plans, "echelle": "8k"}).status_code == 422
    assert loues == []


def test_finaliser_reprend_les_passages_deja_faits_et_loue_le_reste_ensemble(h3, monkeypatch, tmp_path):
    """Une finalisation d'avant le 30/09 au soir (un travail par passage) : les passages
    réussis sont repris tels quels, ceux qui restent partent en UNE location."""
    loues, plans = _finaliser_monte(h3, monkeypatch, tmp_path)
    plans[1]["sujets"] = plans[0]["sujets"]
    fait = "9" * 32
    h3.write_job(fait, {"id": fait, "status": "succeeded", "video": {"de": 0, "a": 124}})
    fid = "8" * 32
    h3.write_job(fid, {"id": fid, "status": "failed", "titre": "Le parc — finalisée",
                       "video": {"moteur": "Finalisation (visages, agrandissement)", "source": "b" * 32,
                                 "echelle": ""},
                       "finalisation": {"plans": [dict(plans[0], visages=fait, agrandi=None),
                                                  dict(plans[1], visages=None, agrandi=None),
                                                  dict(plans[2], visages=None, agrandi=None)],
                                        "film_visages": None, "film": None, "etape": ""}})
    assert client(h3).post("/video-h3/finaliser/%s/reprendre" % fid, headers=CLE).status_code == 200
    job = h3.read_job(fid)
    assert job["status"] == "succeeded", job.get("error")
    assert [q for q, _, _ in loues] == ["visages"]
    assert [(x["de"], x["a"]) for x in loues[0][2]["passages"]] == [(124, 247), (247, 370)]
    assert job["finalisation"]["plans"][0]["visages"] == fait


def test_trop_de_passages_pour_une_location_en_font_plusieurs_en_serie(h3):
    g = h3._groupes([(k, 124, 2) for k in range(10)], h3._tient_visages)
    assert [len(x) for x in g] == [5, 5] and all(h3._tient_visages(x) for x in g)
    assert not h3._tient_visages(g[0] + g[1][:1])
    g = h3._groupes([(k, 124, 0) for k in range(6)], h3._tient_4k("4k"))
    assert [len(x) for x in g] == [4, 2]


def test_un_fondu_et_une_coupe_se_trouvent_dans_l_image(sandbox, tmp_path):
    """Film campus, 30/09 : le fondu de fin du plan 6 ne se voit pas d'une image à l'autre
    (score de scène 0,006) ; il se voit sur une demi-seconde."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg absent")
    film = tmp_path / "f.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=s=160x90:r=24:d=3",
                    "-f", "lavfi", "-i", "color=c=0x2060c0:s=160x90:r=24:d=3",
                    "-f", "lavfi", "-i", "color=c=0xe0c020:s=160x90:r=24:d=2",
                    "-filter_complex", "[0][1]xfade=transition=fade:duration=0.5:offset=2.5[a];[a][2]concat=n=2[v]",
                    "-map", "[v]", "-pix_fmt", "yuv420p", str(film)], check=True)
    # Fondu de 2,5 à 3 s (images 60 à 72), coupe franche à 5,5 s (image 132).
    vues = sandbox.montage.transitions(film.read_bytes())
    assert len(vues) == 2 and abs(vues[0] - 66) <= 4 and abs(vues[1] - 132) <= 2, vues
    v = sandbox.montage.vignettes(film.read_bytes(), [100, 10])
    assert len(v) == 2 and all(x[:2] == b"\xff\xd8" for x in v)


def test_finaliser_propose_des_passages_coupes_aux_fondus(h3, monkeypatch, tmp_path):
    loues, plans = _finaliser_monte(h3, monkeypatch, tmp_path)
    h3.write_job("b" * 32, {"id": "b" * 32, "status": "succeeded", "titre": "Le parc",
                            "video": {"scenario": "d" * 32}})
    # Scénario 124/247/370 ; un fondu vu à 300, un autre collé à la fin d'un plan (écarté).
    monkeypatch.setattr(h3.montage, "transitions", lambda film: [250, 300])
    monkeypatch.setattr(h3.montage, "vignettes", lambda film, n: [b"jpg"] * len(n))
    d = client(h3).post("/video-h3/finaliser/prix", headers=CLE, json={"job": "b" * 32}).json()
    assert [(p["de"], p["a"], p["transition"]) for p in d["plans"]] == [
        (0, 124, False), (124, 247, False), (247, 300, False), (300, 370, True)]
    assert d["plans"][0]["vignette"].startswith("data:image/jpeg;base64,") and d["fiches"]
    # Avec des plans : le devis, ou le refus dit.
    d = client(h3).post("/video-h3/finaliser/prix", headers=CLE,
                        json={"job": "b" * 32, "plans": plans, "echelle": "4k"}).json()
    assert d["devis"]["pire_usd"] > d["devis"]["estime_usd"] > 0
    d = client(h3).post("/video-h3/finaliser/prix", headers=CLE,
                        json={"job": "b" * 32, "plans": plans[:2], "echelle": "4k"}).json()
    assert "refus" in d["devis"] and loues == []



def test_la_page_propose_de_finaliser_le_film(h3):
    page = client(h3).get("/video-h3", headers=CLE).text
    assert 'id="montage_finaliser"' in page and 'blocFinaliser("montage_finaliser"' in page
    assert "/video-h3/finaliser/prix" in page and "/reprendre" in page and "au pire" in page
