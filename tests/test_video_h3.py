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
import sys
import threading
import time
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
    async def aucune_garde(plans, commun, forcer, tournes=None, rapport=None, refus=None, fins_vues=None):
        return []

    async def aucune_regle_clip(*a, **k):
        return {}

    async def aucun_rapport(*a, **k):
        return []
    monkeypatch.setattr(h3, "_garde_des_regles", aucune_garde)
    monkeypatch.setattr(h3, "_verifier_scenario", aucun_rapport)
    monkeypatch.setattr(h3, "_controle_derniere_image", lambda sid, i, image: None)
    monkeypatch.setattr(h3, "_regles_clip", aucune_regle_clip)
    # Le jugement de chaque plan tourné (chez Modal aussi depuis le 02/10) a ses tests.
    monkeypatch.setattr(h3, "_juger_plan_tourne",
                        lambda sid, i, jid, premiere: {"plan": i + 1, "travail": jid, "fautes": []})


@pytest.fixture
def sans_depart_auto(h3, monkeypatch):
    """Les tests du tournage écrits avant l'image de départ automatique du plan 1 (01/10) :
    le plan 1 part comme écrit ; elle a ses propres tests."""
    async def rien(plans, commun):
        return False
    monkeypatch.setattr(h3, "_departs_des_coupes", rien)


@pytest.fixture
def sans_objets_clefs(h3, monkeypatch):
    """Les tests du tournage écrits avant les fiches d'objets clefs (02/10) : leur chat
    simulé n'attend pas la question des objets ; elle a ses propres tests."""
    async def aucun(plans, corps):
        return {"ajoutes": [], "sans_fiche": []}
    monkeypatch.setattr(h3, "_avec_objets_clefs", aucun)


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
    # Le 4e : celui des films en haute définition (30/09, « 4k dans studio »).
    assert page.count("<video") == 4 and "<video" not in replies
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
        "Elle dit : (S1) <d>[French] Enfin.</d> " + v.SEULES_REPLIQUES + " Sound: pluie. non_diegetic_music: N/A"
    assert v.invite("  un phare  ", "", "piano doux") == \
        "un phare. " + v.SILENCE_IMAGE + " Sound: " + v.SILENCE_SON + " non_diegetic_music: piano doux."
    assert v.invite("", "", "") == ""


def test_sans_musique_demandee_la_musique_est_refusee(h3):
    # Sans rien dire, H3 ajoute une musique : le champ du guide MiniMax vaut N/A.
    v = h3.video_h3
    assert v.invite("un phare", "vent", "  ").endswith("Sound: vent. " + v.SILENCE_SON + " non_diegetic_music: N/A")
    assert "N/A" not in v.invite("un phare", "", "violoncelle lent")
    assert v.invite("", "", "") == ""


def test_sans_replique_ecrite_le_silence_se_dit(h3):
    """01/10, plan 4 de « Leila et un martien » : aucune réplique, et les deux prises
    ont parlé ; chaque voie de parole se ferme (guides de dialogue H3)."""
    v = h3.video_h3
    assert v.invite("Zib prend le biscuit", "grillons", "") == (
        "Zib prend le biscuit. Nobody speaks: every person keeps their lips closed. "
        "Sound: grillons. No dialogue, no voiceover, no singing, no individual voices. non_diegetic_music: N/A")
    # Une réplique écrite : rien de tel.
    parle = v.invite("Elle dit « Bonjour. »", "grillons", "")
    assert v.SILENCE_IMAGE not in parle and v.SILENCE_SON not in parle


def test_le_clip_maitre_date_ses_coupes_sans_paroles_et_garde_sa_camera(h3):
    """03/10, « Le jardin de verre » : toute l'histoire en un clip de 15 s, un [Shot N] par coupe,
    une caméra par plan, sans paroles (propriétaire : « on évite de mettre des paroles »)."""
    v = h3.video_h3
    assert v.sans_repliques("Mila waters the pot and murmurs : « Pousse, petite graine. »") == "Mila waters the pot."
    assert v.sans_repliques("She smiles. She says « Bonjour. » Then she sits.") == "She smiles. Then she sits."
    plans = [{"image_paroles": "Mila kneels by the pot and murmurs « Pousse. »", "enchainement": "coupe",
              "camera": {"mouvement": "avance", "amplitude": "petite", "vitesse": "lente"}, "ambiance": "Birds."},
             {"image_paroles": "Close-up of the pot: a shoot grows.", "enchainement": "coupe",
              "camera": v.lire_camera(None), "ambiance": "Birds"},
             {"image_paroles": "The shoot becomes a shrub.", "enchainement": "suite", "longueur": 248,
              "ambiance": "Crystal chimes."}]
    m = v.texte_maitre(plans)
    assert m["debuts_s"] == [0.0, 3.771, 7.542]
    assert m["texte"] == (v.MAITRE_TETE + " [Shot 1] Mila kneels by the pot. The camera pushes in with small "
                          "amplitude at slow speed. [Shot 2] At 00:03.771, the camera cuts to a new shot. Close-up "
                          "of the pot: a shoot grows. The camera holds a static shot. From 00:07.542, without a "
                          "cut: The shoot becomes a shrub. The camera holds a static shot.")
    assert m["ambiance"] == "Birds; Crystal chimes" and "girl" not in m["texte"]
    # Le texte en plans part sans la caméra fixe par défaut, qui le contredisait.
    plan = v.preparer({"mode": "texte", "image_paroles": m["texte"], "longueur": v.LONGUEUR_MAITRE})
    assert "static shot throughout" not in plan["resume_public"]["invite"]
    assert "static shot throughout" in v.preparer({"mode": "texte", "image_paroles": "Mila smiles."}
                                                  )["resume_public"]["invite"]
    # Les clés : la coupe vue (à 0,13 s près), plus une image ; la suite partage son image.
    assert v.cles_du_maitre(plans, m["debuts_s"], [3.65, 9.9], 362) == [(0, 87), (89, 181), (181, 361)]
    with pytest.raises(ValueError, match="coupe du plan 2"):
        v.cles_du_maitre(plans, m["debuts_s"], [9.9], 362)
    # Propriétaire, 04/10 : « si une coupe n'est pas faite, fais le clip en mode continu » — la coupe
    # manquée devient une suite à sa date prévue (le plan 1 finit sur l'image d'où part le plan 2).
    continus = []
    assert v.cles_du_maitre(plans, m["debuts_s"], [9.9], 362, (), continus) == [(0, 91), (91, 181), (181, 361)]
    assert continus == [2]
    # Le maître part de son image en « Première image » (coupes franches) ; sans image, rien ne change.
    p = v.payload_maitre({"mode": "references", "depart_reference": "QUJD", "fiches": ["f1"]}, "Oscar.")
    assert p["mode"] == "premiere" and p["images"] == ["QUJD"] and p["depart_reference"] is None
    assert p["fiches"] == ["f1"] and p["description_premiere"] == "Oscar."
    assert v.payload_maitre({"mode": "references", "fiches": ["f1"]})["mode"] == "references"
    # « Le phare », 03/10 : une suite qui change de valeur de plan devient une coupe ; sinon elle reste.
    phare = [{"image_paroles": "At dusk, wide shot, Oscar stands left.", "enchainement": "coupe"},
             {"image_paroles": "At dusk, medium shot, Oscar stands at the top.", "enchainement": "suite"},
             {"image_paroles": "Medium shot, Oscar presses the switch.", "enchainement": "suite"},
             {"image_paroles": "Oscar smiles.", "enchainement": "suite"}]
    assert [p["enchainement"] for p in v.suites_du_maitre(phare)] == ["coupe", "coupe", "suite", "suite"]
    assert phare[1]["enchainement"] == "suite"   # les plans reçus ne changent pas
    # Une suite où H3 a coupé quand même (« Le phare », 03/10) se traite en coupe.
    assert v.cles_du_maitre(plans, m["debuts_s"], [3.65, 7.6], 362) == [(0, 87), (89, 181), (183, 361)]


def test_sans_replique_un_rire_demande_reste_permis_sans_mots(h3):
    """03/10, « Le jardin de verre », clip 4 : « she laughs », « gentle laughter » ET « lips closed »,
    « no individual voices » ; la consigne se contredisait et H3 a fait dire « I'll be done! »."""
    v = h3.video_h3
    assert v.sons_de_voix("Mila touches a leaf and she laughs.", "shimmer, gentle laughter, a sigh") == [
        "laughs", "laughter", "sigh"]
    assert v.sons_de_voix("A humming fridge? no: a hummingbird.", "") == []   # pas un mot dans un autre
    i = v.invite("Mila touches a crystal leaf, and she laughs.", "soft shimmer, gentle laughter", "")
    assert v.SILENCE_IMAGE not in i and "lips closed" not in i and "no individual voices" not in i
    assert v.SILENCE_SANS_MOTS_IMAGE % "laughs / laughter" in i
    assert "Sound: soft shimmer, gentle laughter. " + v.SILENCE_SANS_MOTS_SON % "laughs / laughter" in i
    # Sans son de voix, le silence complet reste.
    assert v.SILENCE_IMAGE in v.invite("Zib prend le biscuit", "grillons", "")


def test_les_paroles_sont_balisees_au_format_du_modele(h3):
    # Fiche MiniMaxAI/MiniMax-H3 : `<d>[Language] …</d>`, le locuteur (S1) juste avant.
    v = h3.video_h3
    assert v.invite("Elle dit doucement : « Enfin au sec. »") == \
        "Elle dit doucement : (S1) <d>[French] Enfin au sec.</d> " + v.SEULES_REPLIQUES + " non_diegetic_music: N/A"
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
    # Syntaxe de H3 (guide de MiniMax, base, 2.1 et cas 2) : consigne d'alignement, ligne vide, champs.
    assert invite.startswith(v.CONSIGNE_I2VA + "\n\nintegrated_multimodal_description: [Shot 1] "
                             "<Picture 1>: Un café bondé. ") and "ignorée" not in invite
    assert "\n\noverall_soundscape: " in invite and invite.endswith("\n\nnon_diegetic_music: N/A")
    assert "Sound: " not in invite and "First frame" not in invite
    p = v.preparer(demande(mode="premiere_derniere", images=[PNG, PNG],
                           description_premiere="Début.", description_derniere="Fin."))
    i = p["resume_public"]["invite"]
    assert i.startswith("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns "
                        "with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the "
                        "5.17-second mark of the target video.\n\nintegrated_multimodal_description: [Shot 1] "
                        "<Picture 1>: Début. ")
    assert "The shot ends on the composition established by Picture 2: Fin." in i
    # Image téléversée (sans description) : l'ancre n'est pas écrite, la consigne si.
    i = v.preparer(demande(mode="premiere", images=[PNG]))["resume_public"]["invite"]
    assert "<Picture 1>:" not in i and i.startswith(v.CONSIGNE_I2VA + "\n\nintegrated_multimodal_description: [Shot 1] ")
    # La tête d'un maître, avant son [Shot 1], passe dedans, après l'ancre de l'image.
    assert v.description_aux_images("The same place. [Shot 1] Wide shot. [Shot 2] At 00:01.885, close-up.",
                                    "Un jardin") == (
        "[Shot 1] <Picture 1>: Un jardin. The same place. Wide shot. [Shot 2] At 00:01.885, close-up.")
    # Ce qui ne s'adressait qu'au modèle d'image ne part pas à H3 (maître f970b321 : « First frame: Photo
    # réaliste, cadrage paysage 16:9, image nette, début de la scène : Wide shot… »).
    assert v.description_aux_images("Leila walks.", v.PREFIXE_DEPART + "Wide shot, night garden. "
                                    "Améliorations demandées : plus sombre.") == (
        "[Shot 1] <Picture 1>: Wide shot, night garden. Leila walks.")
    # Les noms deviennent l'étiquette de la fiche, ancrée une fois sur <Picture 1> ; une réplique garde
    # ses mots (choix du propriétaire, 04/10 : « courte description »).
    leila = v.fiche_creer("Leila", "x")["id"]
    v.fiche_poser_image(leila, "face", PNG)
    assert v.fiches_sans_etiquette([leila]) == [leila]
    v.fiche_poser_etiquette(leila, '"The girl with dark brown hair."')
    assert v.fiche_lire(leila)["etiquette_h3"] == "the girl with dark brown hair"
    assert v.fiches_sans_etiquette([leila]) == []
    i = v.preparer(demande(mode="premiere", images=[PNG], fiches=[leila],
                           image_paroles="Leila walks to the capsule. Leila says « Leila, wake up! »"))[
        "resume_public"]["invite"]
    assert i.count("The girl with dark brown hair shown in <Picture 1> walks to the capsule.") == 1, i
    assert "The girl with dark brown hair (S1)" in i and "Leila, wake up!" in i and "Leila walks" not in i, i
    # Film 5 relancé, 04/10 : Pixel, absent du premier plan (donc de l'image de départ), n'est pas ancré.
    pixel = v.fiche_creer("Pixel", "x")["id"]
    v.fiche_poser_image(pixel, "face", PNG)
    v.fiche_poser_etiquette(pixel, "the silver robot with blue eyes")
    i = v.preparer(demande(mode="premiere", images=[PNG], fiches=[leila, pixel],
                           image_paroles="[Shot 1] Leila walks. [Shot 2] Wide shot. Pixel wakes up."))[
        "resume_public"]["invite"]
    assert "The silver robot with blue eyes wakes up." in i and i.count("shown in <Picture 1>") == 1, i
    for mauvais in ("Leila", "the girl, who is twelve years old and has very long dark brown hair"):
        with pytest.raises(ValueError):
            v.etiquette_lire(mauvais)
    v.fiche_poser_image(leila, "face", PNG)   # une photo change : l'étiquette est à refaire
    assert v.fiches_sans_etiquette([leila]) == [leila]
    # Texte seul (T2VA) : pas de consigne d'image, les champs quand même.
    i = v.preparer(demande(mode="texte", images=[]))["resume_public"]["invite"]
    assert i.startswith("integrated_multimodal_description: [Shot 1] ")
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


def test_la_limite_de_la_chaine_compte_depuis_la_derniere_coupe(h3, monkeypatch):
    """01/10, « Leila et un martien » : plan 6 refusé (« déjà 4 plans ») juste après la
    coupe du plan 5 ; le scénario avait écrit le rang dans le film à la place de la chaîne."""
    v = h3.video_h3
    monkeypatch.delenv("H3_MOTION_CONTEXT", raising=False)
    plan = v.preparer_prolonger(demande(), _clip_reussi(h3, plans=5, chaine=1), PNG)
    assert plan["resume_public"]["plans"] == 2
    with pytest.raises(ValueError, match="déjà %d plans" % v.PLANS_MAX):
        v.preparer_prolonger(demande(), _clip_reussi(h3, plans=5, chaine=v.PLANS_MAX), PNG)
    with pytest.raises(ValueError, match="déjà"):   # hors scénario, `plans` compte toujours
        v.preparer_prolonger(demande(), _clip_reussi(h3, plans=v.PLANS_MAX), PNG)


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
    # Sans fin fournie : la dernière image, épinglée à l'image 0 (01/10), 1 image retirée.
    plan = v.preparer_prolonger(d, _clip_reussi(h3), PNG)
    g = plan["demande"]["graphe"]
    assert g["11"]["class_type"] == "MiniMaxH3AddGuide" and "audio" not in g["11"]["inputs"]
    assert "80" not in g and v.images_a_retirer(plan) == 1


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
    assert ("<Subject 2> is the person in <Picture 2>. <Picture 3> is the first frame of [Shot 1], "
            "showing <Subject 1> and <Subject 2>. ") in invite
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
    jid, _code, precedent, retirer, ou = lance[0]
    assert ou == "modal"
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
                             "detailed_description: [Shot 1] The camera holds a static shot throughout. Elle sourit")
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


def test_la_planche_part_avec_chaque_plan_tourne_par_h3(h3):
    """01/10, « Leila et un martien » : de profil dans six plans, H3 n'avait que quatre
    photos sans profil ; « la multi vue aurait dû être envoyée » (le propriétaire)."""
    v = h3.video_h3
    fid = v.fiche_creer("Léa", "une femme")["id"]
    for angle, image in (("face", PNG), ("trois_quarts", JPG), ("profil", PNG), ("pied", JPG)):
        v.fiche_poser_image(fid, angle, image)
    v.fiche_poser_planche(fid, JPG)
    assert v.fiche_images_h3(fid) == [PNG, JPG] and len(v.fiche_images(fid)) == 4
    plan = v.preparer(demande(mode="references", fiche=fid, image_paroles="Elle sourit."))
    invite = plan["resume_public"]["invite"]
    assert invite.startswith("subject_definitions: <Subject 1> is the person in <Picture 1>, <Picture 2>; "
                             "<Picture 2> shows this same person from every angle: front, three-quarter, "
                             "profile and back. ")
    assert list(plan["demande"]["images"]) == ["ref_0.png", "ref_1.png"]
    assert v.photos_avec_depart([fid]) == (2, False)
    # Une autre tenue jouée : le portrait seul, la planche montre l'ancienne.
    assert v.fiche_images_h3(fid, visage_seul=True) == [PNG]
    plan = v.preparer(demande(mode="references", fiche=fid, image_paroles="Elle sourit.", visages_seuls=True))
    assert "every angle" not in plan["resume_public"]["invite"]


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
    assert v["invite"].startswith("The camera holds a static shot throughout. In a café she says (S1) <d>[French] Bonjour.</d> " + h3.video_h3.SEULES_REPLIQUES + " Sound: Café chatter.")
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
    # « Le robot perdu », 04/10 : le son d'un clip où le juge a entendu des paroles est coupé au montage.
    monkeypatch.setattr(h3.montage, "couper_son", lambda video: b"m")
    r = c.post("/video-h3/montage", headers=CLE, json={"clips": ["b" * 32, "a" * 32], "muets": ["a" * 32]})
    assert r.status_code == 200, r.text
    assert c.get(c.get("/video/jobs/" + r.json()["id"], headers=CLE).json()["video_url"]).content == b"Bm"
    assert r.json()["video"]["muets"] == ["a" * 32]
    r = c.post("/video-h3/montage", headers=CLE, json={"clips": ["b" * 32, "a" * 32], "muets": ["c" * 32]})
    assert r.status_code == 400


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
    # 01/10 : « suite » par défaut, le chat en a enchaîné cinq ; le Studio met la coupe lui-même.
    six = json.dumps([{"image_paroles": "Plan %d." % k, "ambiance": "", "enchainement": "suite"} for k in range(6)])
    chaine = [p["enchainement"] for p in v.lire_decoupage(six, "Un film.")]
    assert chaine == ["coupe"] + ["suite"] * (v.PLANS_MAX - 1) + ["coupe", "suite"]
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


def test_le_relecteur_d_avant_tournage_voit_les_images_de_depart(h3, monkeypatch):
    """03/10, « Le jardin de verre » : refus « l'arrosoir doit être visible dès le début », alors
    qu'il l'était sur l'image de départ ; le relecteur ne lisait que le texte."""
    v = h3.video_h3
    fid = v.fiche_creer("Mila", "x")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    d1, d3 = v.depart_poser(PNG), v.depart_poser(PNG)
    plans = [{"image_paroles": "Mila waters the pot.", "ambiance": "", "enchainement": "coupe", "image_depart": d1},
             {"image_paroles": "The sprout grows.", "ambiance": "", "enchainement": "suite"},
             {"image_paroles": "Mila steps back.", "ambiance": "", "enchainement": "coupe", "image_depart": d3}]
    vus = []

    async def continuite(plans, histoire, deja_filmes=None, fins_vues=None, departs_vus=None):
        vus.append(departs_vus)
        return {"ok": True, "problemes": [], "details": [], "etats": []}

    async def rien(plan, fiches):
        return {}
    monkeypatch.setattr(h3, "_continuite", continuite)
    monkeypatch.setattr(h3, "_regles_depart", rien)
    asyncio.run(h3._verifier_scenario(plans, {"fiche": fid, "fiches": None}))
    assert sorted(vus[0]) == [1, 3] and vus[0][1] == base64.b64decode(PNG)
    # Un plan déjà filmé (rejeu) garde sa vraie dernière image, pas son image de départ.
    asyncio.run(h3._verifier_scenario(plans, {"fiche": fid, "fiches": None}, deja_filmes=[1]))
    assert sorted(vus[1]) == [3]
    consigne = v.consigne_continuite(plans, "x", vues=[], departs=[1, 3])
    assert "The attached images 1 to 2 are the START images of shots 1, 3" in consigne
    assert "START images" not in v.consigne_continuite(plans, "x")


def test_le_film_se_simule_en_images_debut_et_fin_sans_rien_tourner(h3, monkeypatch, sans_regles):
    """03/10, propriétaire : « simule tous les clips sans les lancer, seulement en images » et
    « image de début + script = image de fin »."""
    v = h3.video_h3
    _autoriser(h3)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    fid = v.fiche_creer("Mila", "x")["id"]
    v.fiche_poser_image(fid, "face", PNG)

    async def tenues(ids, plans):
        return {}
    monkeypatch.setattr(h3, "_tenues_des_plans", tenues)
    demandes, juges = [], []

    async def image(demande):
        if not demande["prompt"].startswith("Planche de référence"):   # la fiche de l'objet clef
            demandes.append(demande["prompt"])
            photos.append(len(demande.get("image_reference") or []))
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)
    photos = []

    async def chat(consigne, quoi="", images=None, modele=""):
        juges.append((quoi, len(images or [])))
        if quoi == "le contrôle de la fin":   # la première fin change de salon, les autres tiennent
            if sum(q == quoi for q, _n in juges) == 1:
                return '{"ok": false, "fautes": ["une autre bibliothèque"]}'
            return '{"ok": true, "fautes": []}'
        if sum(q == quoi for q, _n in juges) == 2:   # le redessin de la coupe est pire
            return '{"ok": false, "fautes": ["le pot a changé de forme", "un autre canapé"]}'
        return '{"ok": false, "fautes": ["le pot a changé de forme"]}'
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    tournes = []
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: tournes.append(a))
    el = lambda nom, debut, fin, mvt="none": {"nom": nom, "debut": debut, "fin": fin, "mouvement": mvt}
    plans = [{"image_paroles": "Medium shot. Mila waters the pot and says « Pousse. »", "ambiance": "",
              "enchainement": "coupe", "elements": [el("Mila", "on the left", "on the left", "waters the pot"),
                                                    el("the pot", "at the centre", "at the centre")]},
             {"image_paroles": "Close-up. A crystal sprout grows from the pot.", "ambiance": "", "enchainement": "suite",
              "elements": [el("the pot", "at the centre", "at the centre"),
                           el("a crystal sprout", "off-frame", "at the centre, grown", "grows from the pot")]},
             {"image_paroles": "Wide shot. Mila looks at the shrub.", "ambiance": "", "enchainement": "coupe",
              "elements": [el("Mila", "on the right", "on the right", "looks at the shrub")]}]
    r = client(h3).post("/video-h3/scenario/simuler", headers=CLE,
                        json={"plans": plans, "fiche": fid, "longueur": 124, "decor_auto": False})
    assert r.status_code == 200, r.text
    lignes = r.json()["plans"]
    assert [x["plan"] for x in lignes] == [1, 2, 3] and all(x["depart"] and x["fin"] for x in lignes)
    # La suite reprend l'image de fin du plan d'avant ; la coupe en part, autre cadrage, raccord jugé.
    assert lignes[1]["depart"] == lignes[0]["fin"]
    assert lignes[2]["raccord"] == ["le pot a changé de forme"] and ("le contrôle du raccord", 2) in juges
    # Le faux raccord se redessine une fois, comme au tournage ; le redessin, pire (deux fautes),
    # est écarté : le premier essai reste, avec ses fautes (03/10, propriétaire : « le meilleur »).
    assert lignes[2]["raccord_essais"] == v.RACCORD_ESSAIS == 2 and lignes[2]["raccord_garde"] == 1
    assert [x.get("fin_garde") for x in lignes] == [2, 1, 1]
    assert sum(q == "le contrôle du raccord" for q, _n in juges) == 2
    # L'image de fin se juge contre le début du plan : la fin 1, refusée, est redessinée une fois.
    assert [x["fin_essais"] for x in lignes] == [2, 1, 1] and all(x["controle_fin"] == [] for x in lignes)
    assert [n for q, n in juges if q == "le contrôle de la fin"] == [2, 2, 2, 2]
    # 7 images : début 1, fin 1 deux fois, fin 2, début 3 (coupe) deux fois, fin 3 ; jamais la réplique.
    assert len(demandes) == 7 and not any("Pousse" in d for d in demandes)
    assert sum(v.CONSIGNE_FIN.split("%d")[1][:40] in d for d in demandes) == 4
    assert v.CONSIGNE_COUPE % 2 in demandes[4] and v.CONSIGNE_COUPE % 2 in demandes[5]
    assert "fin de la scène" in demandes[3] and "a crystal sprout : at the centre, grown." in demandes[3]
    # 03/10, propriétaire : l'image de fin a aussi les photos des fiches présentes à la fin
    # (Mila, l'objet clef), jamais celles des absents (Mila n'est pas au plan 2).
    assert "Mila est la personne" in demandes[1] and "the pot est l'objet" in demandes[1]
    assert "Mila" not in demandes[3].split(".")[0] and "the pot est l'objet" in demandes[3]
    assert photos[1] >= 3 and photos[1] > photos[3]
    # 03/10, quatrième story-board : le redessin reçoit les fautes du juge, pas le premier dessin ;
    # la description de l'image (celle qui passe à H3 et au juge) n'en garde rien.
    assert v.CONSIGNE_A_EVITER % "une autre bibliothèque" in demandes[2]
    assert v.CONSIGNE_A_EVITER % "le pot a changé de forme" in demandes[5]
    assert not any("à ne pas refaire" in demandes[k] for k in (0, 1, 3, 4, 6))
    assert not any("à ne pas refaire" in (x.get("description_fin", "") + x.get("description_depart", ""))
                   for x in lignes)
    # Le juge de la fin compare au décor quand il y en a un ; un gros plan n'est pas un manque.
    assert "Image 3 is the empty set" in v.consigne_controle_fin("x", avec_decor=True)
    assert "Image 3" not in v.consigne_controle_fin("x") and "they are NOT missing" in v.consigne_raccord("x")
    assert tournes == []   # rien n'est tourné


def test_la_correction_n_invente_pas_de_tenue(h3):
    """03/10, « Le jardin de verre » : le relecteur a noté « la tenue de Mila n'est décrite dans
    aucun plan », et la correction l'a habillée d'un pull crème, loin du pull rayé de sa fiche."""
    v = h3.video_h3
    assert "Clothing that the text does not give is NEVER a fault" in v.consigne_continuite(
        [{"image_paroles": "x", "enchainement": "coupe"}], "x")
    plans = [{"image_paroles": "Close-up. Mila kneels near the pot.", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Wide shot. Mila stands up.", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Mila, in her red coat, waves.", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Mila looks at the tree.", "ambiance": "", "enchainement": "coupe"}]
    nouveaux = [dict(plans[0], image_paroles="Close-up. Mila, wearing a cream sweater and dark trousers, kneels "
                                             "on the left near the pot."),
                dict(plans[1], image_paroles="Wide shot. Mila stands up on the right, wearing a cream sweater."),
                dict(plans[2], image_paroles="Mila, in her red coat, waves from the right."),
                dict(plans[3], image_paroles="Mila in a blue dress looks at the tree.")]
    sortie, touches = v.sans_tenue_inventee(nouveaux, plans, "Mila plants a seed.")
    # La tenue ajoutée part, le reste de la correction reste.
    assert sortie[0]["image_paroles"] == "Close-up. Mila kneels on the left near the pot."
    assert sortie[1]["image_paroles"] == "Wide shot. Mila stands up on the right."
    # Une tenue déjà dans le plan d'origine (ou l'histoire) reste.
    assert sortie[2]["image_paroles"] == "Mila, in her red coat, waves from the right."
    # Un vêtement ajouté que le code ne sait pas couper : le plan garde son texte d'origine.
    assert sortie[3]["image_paroles"] == "Mila looks at the tree." and touches == [1, 2, 4]


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


def test_un_scenario_se_tourne_plan_par_plan_et_se_recolle(h3, monkeypatch, tmp_path, sans_regles, sans_depart_auto, sans_objets_clefs):
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    # Chaque plan part traduit, la suite aussi (28/09) : deux réponses du chat.
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite([
        '{"tenues": [{"nom": "Léa", "tenue": ""}]}',   # le relevé des tenues : celle de la fiche
        # 03/10 : la tenue de la fiche n'est plus lue sur sa photo pour être écrite (« jamais en texte »).
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

    def tourner(jid, code, precedent, retirer, ou="modal"):
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
    # Propriétaire, 03/10 : « les attributs sont toujours avec des images, jamais en texte ».
    assert " wears " not in v1["invite"] and v.fiche_tenue_de_base(fid) is None
    # Suite avec fiche : le raccord natif (30/09), 22 images reprises puis retirées au recollage.
    assert (p2, r2) == (j1, 22) and v2["mode"] == "prolonger" and v2["plans"] == 2
    assert v2["voie"] == "raccord" and v2["images"] == 141
    assert (v1["chaine"], v2["chaine"]) == (1, 2)
    assert "(S1) <d>[French] Bonjour.</d>" in v2["invite"]
    assert sc["film"] == j2 and sc["travaux"] == [j1, j2] and "video_url" in sc


def test_chaque_coupe_part_d_une_image_que_le_studio_cree_sinon_rien_ne_part(h3, monkeypatch, sans_regles):
    """01/10, propriétaire : « le premier clip doit démarrer à partir d'une image », puis
    « une coupure démarre par une image créée par un text to image »."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    fid = v.fiche_creer("Zib", "un martien")["id"]
    v.fiche_poser_image(fid, "face", PNG)

    async def tenues(commun, plans, a_tourner):
        return []
    monkeypatch.setattr(h3, "_scenario_tenues", tenues)
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: image)
    demandes = []

    async def image(demande):
        demandes.append(demande)
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)
    fils = []
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    plans = [{"image_paroles": "Zib atterrit dans le jardin", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Zib salue", "ambiance": "", "enchainement": "suite"},
             {"image_paroles": "Le lendemain, Zib repart", "ambiance": "", "enchainement": "coupe"}]
    vus = []
    vraie = h3._creer_depart

    async def creer(corps):
        vus.append(dict(corps))
        return await vraie(corps)
    monkeypatch.setattr(h3, "_creer_depart", creer)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 200, r.text
    sc = r.json()
    # Une image par « coupe » (plans 1 et 3), pas pour la suite, qui part du plan d'avant.
    assert len(demandes) == 2 and "Zib atterrit" in json.dumps(demandes[0], ensure_ascii=False)
    assert sc["plans"][0]["image_depart"] and "image_depart" not in sc["plans"][1] and sc["plans"][2]["image_depart"]
    # Comme la page : l'image de la coupe d'avant est jointe (même lieu, même lumière).
    assert [x["decor"] for x in vus] == [None, sc["plans"][0]["image_depart"]] and vus[1]["plan"] == 3
    for k in (0, 2):
        p = fils[0][1][k]["payload"]
        assert p.get("depart_reference") or p["mode"] == "premiere"
    # L'image du Studio en panne : rien ne part, et on le dit.

    async def panne(demande):
        raise h3.HTTPException(502, "L'image du Studio n'a rendu aucune image.")
    monkeypatch.setattr(h3, "_image_du_studio", panne)
    monkeypatch.setattr(h3, "COUPE_PAUSE_S", 0)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 502 and len(fils) == 1
    # 03/10, « Le jardin de verre » : le refus nomme le plan.
    assert "plan 1" in r.json()["detail"] and "aucune image" in r.json()["detail"], r.text


def test_un_refus_d_image_de_depart_est_redemande_puis_la_description_redite(h3, monkeypatch, sans_regles):
    """03/10, « Le jardin de verre » : « Google n'a renvoyé aucune image » sur le plan 3, et le
    film s'arrêtait avant le premier plan, sans dire lequel."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    monkeypatch.setattr(h3, "COUPE_PAUSE_S", 0)
    fid = v.fiche_creer("Mila", "une fillette")["id"]
    v.fiche_poser_image(fid, "face", PNG)

    async def tenues(commun, plans, a_tourner):
        return []
    monkeypatch.setattr(h3, "_scenario_tenues", tenues)
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: image)
    fils = []
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    plans = [{"image_paroles": "Mila arrose le pot", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Des troncs de cristal jaillissent du parquet", "ambiance": "", "enchainement": "coupe"}]
    demandes, refus = [], {"n": 2}

    async def image(demande):
        demandes.append(demande["prompt"])
        if "jaillissent" in demande["prompt"] and refus["n"]:
            refus["n"] -= 1
            raise h3.HTTPException(502, "L'image du Studio a refusé : Google n'a renvoye aucune image : "
                                        "la description a probablement ete refusee.")
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)
    chats = []

    async def chat(consigne, quoi="", images=None, modele=""):
        if consigne.startswith("An image generator returned no image"):
            chats.append(consigne)
            return "Des troncs de verre s'élèvent lentement au milieu du salon"
        return ""
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE,
                        json={"plans": plans, "fiche": fid, "longueur": 124, "decor_auto": False})
    assert r.status_code == 200, r.text
    # Plan 1 ; plan 2 refusé deux fois (la description redite après le 1er refus), puis dessiné.
    assert len(demandes) == 1 + h3.COUPE_ESSAIS and len(chats) == 1 and "jaillissent" in chats[0]
    assert "s'élèvent lentement" in demandes[-1] and demandes[-1].count(v.PREFIXE_DEPART) == 1
    assert r.json()["plans"][1]["description_depart"].startswith(v.PREFIXE_DEPART)
    # Le chat hors sujet ou vide : la même description.
    assert v.reformuler_depart(v.PREFIXE_DEPART + "x", "") == v.PREFIXE_DEPART + "x"
    assert v.reformuler_depart(v.PREFIXE_DEPART + "x", v.PREFIXE_DEPART + "y") == v.PREFIXE_DEPART + "y"
    # Un refus qui n'est pas une panne passagère (400) : pas redemandé, le plan nommé.
    demandes.clear()

    async def interdit(demande):
        demandes.append(1)
        raise h3.HTTPException(400, "Description vide.")
    monkeypatch.setattr(h3, "_image_du_studio", interdit)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE,
                        json={"plans": plans, "fiche": fid, "longueur": 124, "decor_auto": False})
    assert r.status_code == 400 and "plan 1" in r.json()["detail"] and len(demandes) == 1 and len(fils) == 1


def test_la_description_de_depart_suit_le_tableau_sans_les_repliques(h3):
    """02/10 : depuis le texte entier, Gemini a écrit « Delicious! » sur l'image."""
    v = h3.video_h3
    plan = {"image_paroles": "Medium shot in a garden at night. Zib bites the cookie. Zib dit : « Delicious! »",
            "elements": [{"nom": "the saucer", "debut": "in the background, right of the frame"},
                         {"nom": "Zib", "debut": "in the foreground, centre"},
                         {"nom": "Tom", "debut": "off-frame"}]}
    assert v.texte_depart(plan) == (v.PREFIXE_DEPART + "Medium shot in a garden at night. "
                                    "the saucer : in the background, right of the frame. Zib : in the foreground, centre.")
    assert v.texte_depart({"image_paroles": "Il dit : « Bonjour. » puis sourit"}) == v.PREFIXE_DEPART + "Il puis sourit"
    # 03/10, « Le jardin de verre » : l'effet tenait dans la première phrase, après « : ».
    jardin = {"image_paroles": "At twilight, close-up on the pot of soil: a transparent crystal sprout pierces the "
                               "soil and branches out into a glass shrub.",
              "elements": [{"nom": "pot of soil", "debut": "in the centre, with wet soil"},
                           {"nom": "transparent crystal sprout", "debut": "off-frame"}]}
    assert v.texte_depart(jardin) == (v.PREFIXE_DEPART + "At twilight, close-up on the pot of soil. "
                                      "pot of soil : in the centre, with wet soil.")
    # Film 5 relancé, 04/10 : le lieu dans la deuxième phrase ; sans lui, une rue de ville.
    capsule = {"image_paroles": "Wide shot, night. In the garden, Leila stands center foreground, facing camera. "
                                "A silver capsule falls from sky. Leila looks up.",
               "elements": [{"nom": "Leila", "debut": "in the center foreground, standing, facing the camera"},
                            {"nom": "silver capsule", "debut": "off-frame"}]}
    assert v.texte_depart(capsule) == (v.PREFIXE_DEPART + "Wide shot, night. In the garden. "
                                       "Leila : in the center foreground, standing, facing the camera.")
    demande, _ = v.demande_image("x", decor=v.depart_poser(PNG), coupe=True)
    assert v.CONSIGNE_COUPE % 1 in demande["prompt"] and "dernière image du plan précédent" in demande["prompt"]


def test_une_coupe_apres_un_plan_tourne_part_de_sa_derniere_image(h3, monkeypatch, tmp_path, sans_regles):
    """02/10, propriétaire : « code le 1 ». Plan 5 de « Leila et un martien » : l'image de
    la coupe partait de celle du plan 1, et le décor a sauté. Au tournage, la coupe est
    refaite depuis la dernière image du plan d'avant ; en panne, celle du découpage part."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    fid = v.fiche_creer("Zib", "un martien")["id"]
    v.fiche_poser_image(fid, "face", PNG)

    async def tenues(commun, plans, a_tourner):
        return []
    monkeypatch.setattr(h3, "_scenario_tenues", tenues)
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: image)
    demandes = []

    async def image(demande):
        demandes.append(demande)
        return "data:image/jpeg;base64," + JPG if len(demandes) > 2 else "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)
    fils, vrai = [], h3.run_scenario_h3
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    plans = [{"image_paroles": "Zib atterrit dans le jardin", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Zib mange un biscuit et dit « Délicieux. »", "ambiance": "", "enchainement": "coupe",
              "elements": [{"nom": "the saucer", "debut": "in the background, right of the frame"}]}]
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 200, r.text
    sid, decoupage = r.json()["id"], r.json()["plans"][1]["image_depart"]
    video = tmp_path / "plan.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: video)
    monkeypatch.setattr(h3.montage, "derniere_image", lambda octets: base64.b64decode(PNG) + b"FIN-DU-PLAN-1")
    monkeypatch.setattr(h3.montage, "recoller_son", lambda a, b, retirer: a + b)
    controles = []
    monkeypatch.setattr(h3, "_controle_derniere_image", lambda s, i, img: controles.append((i, img)) or None)
    tournes = []

    def tourner(jid, code, precedent, retirer, ou="modal"):
        tournes.append(h3.read_job(jid)["video"])
        job = h3.read_job(jid)
        job["status"] = "succeeded"
        h3.write_job(jid, job)
    monkeypatch.setattr(h3, "run_video_h3", tourner)
    poses = []
    vrai_poser = v.depart_poser
    monkeypatch.setattr(v, "depart_poser", lambda img: poses.append(img) or vrai_poser(img))
    vrai(*fils[0])   # le fil, joué ici pour attendre sa fin
    sc = v.scenario_lire(sid)
    assert sc["etat"] == "réussi", sc["erreur"]
    assert sc.get("departs_de_coupe") and sc["departs_de_coupe"][0]["note"] == "", sc.get("departs_de_coupe")
    # La dernière image du plan 1 jointe à Gemini, avec la consigne de coupe, sans la réplique.
    assert base64.b64decode(poses[-2]).endswith(b"FIN-DU-PLAN-1")
    assert v.CONSIGNE_COUPE % 2 in demandes[-1]["prompt"] and "Délicieux" not in demandes[-1]["prompt"]
    assert "the saucer : in the background, right of the frame" in demandes[-1]["prompt"]
    neuve = sc["plans"][1]["image_depart"]
    assert neuve != decoupage and sc["departs_de_coupe"] == [{"plan": 2, "depart": neuve, "garde": neuve, "decoupage": decoupage, "note": ""}]
    assert controles and controles[-1][0] == 1
    assert len(tournes) == 2 and fils[0][1][1]["payload"]["depart_reference"] == JPG   # l'image neuve part
    # L'image du Studio en panne au tournage (02/10, film 4, plan 5 : HTTP 503) : redemandée,
    # puis le film s'arrête, au lieu de partir de l'image du découpage, faite avant le tournage.
    pannes = []

    async def panne(demande):
        pannes.append(1)
        raise h3.HTTPException(502, "L'image du Studio n'a rendu aucune image.")
    monkeypatch.setattr(h3, "COUPE_PAUSE_S", 0)
    demandes.clear()
    monkeypatch.setattr(h3, "_image_du_studio", image)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    sid2, decoupage2 = r.json()["id"], r.json()["plans"][1]["image_depart"]
    monkeypatch.setattr(h3, "_image_du_studio", panne)
    tournes.clear()
    vrai(*fils[1])
    sc = v.scenario_lire(sid2)
    assert sc["etat"] == "échoué" and "Plan 2" in sc["erreur"] and "rejouez" in sc["erreur"], sc.get("erreur")
    assert len(pannes) == h3.COUPE_ESSAIS and len(tournes) == 1   # redemandée ; le plan 2 n'est pas tourné
    (note,) = sc["departs_de_coupe"]
    assert note["garde"] == decoupage2 and note["depart"] is None and "aucune image" in note["note"]
    # Une panne passagère, puis l'image : elle part.
    reponses = [panne, image]

    async def puis(demande):
        return await reponses.pop(0)(demande)
    monkeypatch.setattr(h3, "_image_du_studio", image)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    monkeypatch.setattr(h3, "_image_du_studio", puis)
    vrai(*fils[2])
    sc = v.scenario_lire(r.json()["id"])
    assert sc["etat"] == "réussi" and sc["departs_de_coupe"][0]["note"] == "", sc.get("erreur")
    # « Tourner quand même » : celle du découpage part, et c'est écrit.
    monkeypatch.setattr(h3, "_image_du_studio", image)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE,
                        json={"plans": plans, "fiche": fid, "longueur": 124, "forcer": True})
    sid4, decoupage4 = r.json()["id"], r.json()["plans"][1]["image_depart"]
    monkeypatch.setattr(h3, "_image_du_studio", panne)
    vrai(*fils[3])
    sc = v.scenario_lire(sid4)
    assert sc["etat"] == "réussi" and sc["plans"][1]["image_depart"] == decoupage4, sc.get("erreur")


def test_une_tenue_changee_par_le_scenario_ajoute_sa_photo_a_tous_les_plans(h3, monkeypatch, sans_regles, sans_depart_auto, sans_objets_clefs):
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


def _tournage_juge(h3, monkeypatch, tmp_path, ou, fautifs, muets=()):
    """Deux plans tournés par le fil ; `fautifs` : les appels du juge (1, 2…) qui voient un
    double ; `muets` : ceux où le chat ne répond pas."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(h3, "_h3_peut", lambda ou, demande=None: None)
    fid = v.fiche_creer("Zib", "x")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    tournes, juges = [], []

    def tourner(jid, code, precedent, retirer, lieu):
        tournes.append((jid, precedent, h3.read_job(jid)["video"]["graine"]))
        job = h3.read_job(jid)
        job.update(status="succeeded")
        job["video"]["secondes"] = 5.17 * (2 if precedent else 1)   # la chaîne recollée
        h3.write_job(jid, job)

    async def regles_clip(film, debut, duree, noms, refs, plan):
        juges.append((round(debut * 24), round(duree * 24), plan["image_paroles"]))
        if len(juges) in muets:
            return {10: h3.regles.resultat(None, "Le chat du Studio ne répond pas (ReadTimeout)")}
        double = len(juges) in fautifs
        return {10: h3.regles.resultat(not double, "deux Zib" if double else "")}

    async def ecouter(video, texte):
        return {"attendu": [], "ok": True}
    film = tmp_path / "film.mp4"
    film.write_bytes(b"MP4")
    monkeypatch.setattr(h3, "run_video_h3", tourner)
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: film)
    monkeypatch.setattr(h3.montage, "extraire", lambda f, de, a: b"PLAN")
    monkeypatch.setattr(h3, "_regles_clip", regles_clip)
    monkeypatch.setattr(h3, "_ecouter", ecouter)
    sid = "f" * 32
    plans = [{"image_paroles": "Zib atterrit"}, {"image_paroles": "Zib salue"}]
    v.scenario_ecrire({"id": sid, "etat": "en cours", "erreur": "", "plans": plans, "travaux": [], "film": None,
                       "fiches": [fid], "ou": ou})
    p = {"mode": "references", "fiche": fid, "image_paroles": "Zib", "longueur": 124, "images": [], "graine": 7}
    h3.run_scenario_h3(sid, [{"enchainement": "coupe", "payload": p}, {"enchainement": "coupe", "payload": p}])
    return v.scenario_lire(sid), tournes, juges


def test_ici_un_plan_fautif_est_repris_avant_le_plan_suivant(h3, monkeypatch, tmp_path):
    """01/10 : le double fantôme de Zib (plan 2) n'a été vu qu'après les six plans ;
    « le rerun plan2 aurait dû être fait avant plan 3 par studio »."""
    sc, tournes, juges = _tournage_juge(h3, monkeypatch, tmp_path, "maison", fautifs={1})
    (a, pa, ga), (b, pb, gb), (c, pc, gc) = tournes
    # La reprise part du même départ, avec une autre graine, AVANT le plan 2, qui part d'elle.
    assert pa is None and pb is None and pc == b
    assert ga == 7 and gb != 7 and gc == 7
    # Chaque prise est jugée seule : le plan 2 commence où la prise gardée finit.
    assert juges == [(0, 124, "Zib atterrit"), (0, 124, "Zib atterrit"), (124, 124, "Zib salue")]
    assert sc["etat"] == "réussi" and sc["travaux"] == [b, c] and sc["film"] == c
    assert sc["reprises_auto"] == [{"plan": 1, "prises": [a, b], "garde": b}]
    assert [x["fautes"] for x in sc["controles_plans"]] == [["règle 10 : deux Zib"], [], []]


def test_ici_une_seule_reprise_et_la_moins_fautive_reste(h3, monkeypatch, tmp_path):
    sc, tournes, juges = _tournage_juge(h3, monkeypatch, tmp_path, "maison", fautifs={1, 2})
    (a, _, _), (b, _, _), (c, pc, _) = tournes
    # À égalité, la première prise reste, et le plan 2 part d'elle.
    assert len(tournes) == 3 and pc == a and sc["travaux"] == [a, c]
    assert sc["reprises_auto"] == [{"plan": 1, "prises": [a, b], "garde": a}]


def test_un_juge_muet_est_redemande_puis_dit_non_juge(h3, monkeypatch, tmp_path):
    """01/10, plan 2 rejoué : la reprise, jugée par un chat en ReadTimeout, a passé pour propre."""
    sc, tournes, juges = _tournage_juge(h3, monkeypatch, tmp_path, "maison", fautifs={1}, muets={2})
    # La reprise est rejugée (appels 2 et 3) : propre, rien n'est noté « non jugé ».
    assert len(tournes) == 3 and len(juges) == 4 and "non_juge" not in sc["controles_plans"][1]
    sc, tournes, juges = _tournage_juge(h3, monkeypatch, tmp_path, "maison", fautifs={1}, muets={2, 3})
    # Muet deux fois : la reprise reste (la première est fautive), et le dit.
    assert sc["travaux"][0] == tournes[1][0] and "ReadTimeout" in sc["controles_plans"][1]["non_juge"]


def test_chez_modal_aucune_reprise_payee_sans_accord(h3, monkeypatch, tmp_path):
    # 02/10, film 4 : chez Modal, les plans n'étaient pas jugés. Jugés maintenant (gratuit) ; un plan
    # fautif n'est pas repris (une reprise se paie) : le film s'arrête et dit pourquoi.
    sc, tournes, juges = _tournage_juge(h3, monkeypatch, tmp_path, "modal", fautifs={1})
    assert len(tournes) == 1 and len(juges) == 1 and "reprises_auto" not in sc and sc["etat"] == "arrêté"
    assert sc["erreur"] == "Plan 1 à revoir : règle 10 : deux Zib"
    assert [x["fautes"] for x in sc["controles_plans"]] == [["règle 10 : deux Zib"]]


def test_chez_modal_un_plan_propre_continue_et_le_dernier_plan_n_arrete_rien(h3, monkeypatch, tmp_path):
    sc, tournes, juges = _tournage_juge(h3, monkeypatch, tmp_path, "modal", fautifs={2})
    assert len(tournes) == 2 and sc["etat"] == "réussi"
    assert [x["fautes"] for x in sc["controles_plans"]] == [[], ["règle 10 : deux Zib"]]


def test_plan_par_plan_arrete_le_film_apres_chaque_plan_neuf(h3, monkeypatch, tmp_path):
    # Propriétaire, 02/10 : « tu valides (ou pas) chaque plan avant de passer au suivant ».
    vrai = h3.video_h3.scenario_ecrire

    def avec_reglage(sc):
        vrai(dict(sc, reglages={"plan_par_plan": True}) if "reglages" not in sc else sc)
    monkeypatch.setattr(h3.video_h3, "scenario_ecrire", avec_reglage)
    sc, tournes, juges = _tournage_juge(h3, monkeypatch, tmp_path, "modal", fautifs=set())
    assert len(tournes) == 1 and sc["etat"] == "arrêté"
    assert sc["erreur"] == "Plan 1 tourné : à valider avant le suivant (plan par plan)."


# --- 10. Deux personnages, deux langues, une musique posée après coup (28/09) ---

def test_chaque_replique_va_au_personnage_nomme_dans_sa_phrase(h3):
    v = h3.video_h3
    texte = ("Léa sourit à James. James dit « Hello Léa, is this seat taken? » Lea répond "
             "« Non, asseyez-vous. » Puis « Bon café. »")
    assert v.attribuer_repliques(texte, [("Léa", "French"), ("James", "English")]) == (
        # Forme du guide (5.4) : (Sx) suit le nom du locuteur dans sa phrase, jamais un second nom.
        # 02/10 : (Sx) est le rang de la PERSONNE dans les fiches, pas l'ordre de parole du
        # plan — le même numéro d'un plan à l'autre (« la voix change », le propriétaire).
        "<Subject 1> sourit à <Subject 2>. <Subject 2> (S2) dit <d>[English] Hello Léa, is this "
        "seat taken?</d> <Subject 1> (S1) répond <d>[French] Non, asseyez-vous.</d> "
        "Puis <Subject 1> (S1) <d>[French] Bon café.</d>")
    # Un objet ne prend pas de numéro : Tom, après le ballon, reste (S2).
    assert v.attribuer_repliques("Tom dit « Hi. »", [("Léa", "French"), ("ballon", "English"), ("Tom", "English")],
                                 objets={1: "objet"}) == "<Subject 3> (S2) dit <d>[English] Hi.</d>"
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
    # 01/10 : « raccord par défaut sauf si le scénario veut un coupé ».
    assert "\"suite\" BY DEFAULT" in v.consigne_decoupage("Un film.")
    assert "not a reason for a cut" in v.consigne_decoupage("Un film.")
    # Essai du 29/09 : geste étalé sur trois plans, élément du lieu absent au départ, caméra qui avance.
    for regle in ("never spread one gesture over several shots", "already visible from the start",
                  "never write a camera movement", "fix the STAGING of each place",
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
        # La caméra en tête quand aucune phrase n'est finie hors réplique (01/10).
        "detailed_description: [Shot 1] The camera holds a static shot throughout. "
        "<Subject 2> (S2) demande <d>[English] Is this seat taken?</d> "
        "<Subject 1> (S1) répond <d>[French] Oui.</d> " + v.SEULES_REPLIQUES + "\n\nnon_diegetic_music: N/A")
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
           "<Subject 2> (S2)." in invite
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


def test_aucune_fonction_du_studio_n_en_cache_une_autre():
    # 30/09 : un second « _ecouter » (sous-titres) a été écrasé par celui du juge, défini
    # plus bas ; le test des sous-titres remplaçait la fonction par un faux et n'a rien vu.
    import ast
    import collections
    for nom in ("app.py", "montage.py", "video_h3.py", "visages.py", "agrandir.py", "chanson.py"):
        arbre = ast.parse((Path(__file__).parents[1] / "sandbox-manager" / nom).read_text(encoding="utf-8"))
        noms = collections.Counter(n.name for n in arbre.body
                                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        assert not [k for k, v in noms.items() if v > 1], nom


def test_les_repliques_se_recoupent_aux_pauses_seulement_si_plusieurs_phrases(h3):
    m = h3.montage
    # Film campus, 30/09 : 0,54 s AU MILIEU d'une réplique, 0,59 s ENTRE deux personnages.
    assert m.repartir([(3.28, 3.67), (4.21, 5.03)], "Hey, are you lost?") == [(3.28, 5.03, "Hey, are you lost?")]
    assert m.repartir([(13.76, 16.39), (16.98, 20.06)], "Je parle un peu français. Ton accent est trop mignon !") \
        == [(13.76, 16.39, "Je parle un peu français."), (16.98, 20.06, "Ton accent est trop mignon !")]
    # Une pause courte (0,37 s) ne coupe pas, même si Whisper met un point.
    assert m.repartir([(6.61, 10.01), (10.38, 11.25)], "Yes! I can't find the science building.") \
        == [(6.61, 11.25, "Yes! I can't find the science building.")]
    assert m.repartir([(1.0, 2.0)], "  ") == []
    cales = m.calage([(3.28, 5.03, "Hé, tu es perdue ?"), (5.2, 5.4, "Oui !"), (9.0, 9.5, "Bon.")])
    assert cales[0] == (3.13, 5.03, "Hé, tu es perdue ?")          # pas au-delà de la voix : la suivante suit
    assert all(x[1] < y[0] for x, y in zip(cales, cales[1:]))      # jamais deux à la fois
    assert cales[1][1] - cales[1][0] >= m.SOUS_TITRE_MIN_S
    assert m.srt(cales[:1]) == "1\n00:00:03,130 --> 00:00:05,030\nHé, tu es perdue ?\n\n"


def test_un_film_4k_se_sous_titre_en_francais_puis_prend_sa_musique(h3, monkeypatch, tmp_path):
    fichiers = _deux_clips(h3, monkeypatch, tmp_path)
    hd = "e" * 32
    _clip_reussi(h3, hd, moteur="SeedVR2 (agrandissement)")
    job = h3.read_job(hd)
    job["video"]["echelle"] = "4k"
    h3.write_job(hd, job)
    fichiers[hd] = tmp_path / "hd.mp4"
    fichiers[hd].write_bytes(b"FILM4K")
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "k")
    monkeypatch.setattr(h3.montage, "passages_de_voix", lambda v: [(3.28, 5.03, [(3.28, 3.67), (4.21, 5.03)]),
                                                                    (13.76, 20.06, [(13.76, 16.39), (16.98, 20.06)])])
    monkeypatch.setattr(h3.montage, "son_du_passage", lambda v, de, a: b"%.2f" % de)
    entendus = {b"3.08": "Hey, are you lost?", b"13.56": "Je parle un peu français. Ton accent est trop mignon !"}
    monkeypatch.setattr(h3, "_ecouter_replique", lambda son: entendus[son])
    consignes = []

    async def chat(consigne, quoi="", **_):
        consignes.append(consigne)
        return '```json\n["Hé, tu es perdue ?", "Je parle un peu français.", "Ton accent est trop mignon !"]\n```'
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    incruste = []
    monkeypatch.setattr(h3.montage, "incruster_sous_titres", lambda f, s: incruste.append((f, s)) or f + b"+ST")
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 724)
    c = client(h3)
    r = c.post("/video-h3/sous-titres", headers=CLE, json={"film": hd})
    assert r.status_code == 200, r.text
    for _ in range(150):   # le vrai fil : l'écoute et la traduction y tournent
        time.sleep(0.2)
        try:
            st = h3.read_job(r.json()["id"])
        except OSError:    # Windows : le fichier est en train d'être remplacé
            continue
        if st["status"] in ("succeeded", "failed"):
            break
    assert st["status"] == "succeeded", st.get("error")
    assert '"Hey, are you lost?"' in consignes[0] and "français" in consignes[0]
    assert [x["texte"] for x in st["video"]["sous_titres"]] == ["Hé, tu es perdue ?", "Je parle un peu français.",
                                                                "Ton accent est trop mignon !"]
    assert incruste[0][0] == b"FILM4K" and "00:00:16,830 --> " in incruste[0][1]
    # Il reste un film 4K : dans la liste HD, pas parmi les clips 480p à monter.
    assert st["video"]["moteur"] == "SeedVR2 (agrandissement)" and st["video"]["echelle"] == "4k"
    listes = c.get("/video-h3/clips", headers=CLE).json()
    assert st["id"] in [f["id"] for f in listes["films_hd"]] and st["id"] not in [x["id"] for x in listes["clips"]]
    # Puis la musique sur le film sous-titré, qui reste 4K.
    son = tmp_path / "son.flac"
    son.write_bytes(b"SON")
    monkeypatch.setattr(h3, "_chansons_pretes", lambda: [{"id": "c" * 32, "titre": "Campus", "cree_a": 0}])
    monkeypatch.setattr(h3, "chanson_fichiers", lambda jid: {"son": {"path": str(son)}})
    monkeypatch.setattr(h3.montage, "poser_musique", lambda f, s, *reste: f + s)
    r = c.post("/video-h3/musique", headers=CLE, json={"film": st["id"], "chanson": "c" * 32, "sous_paroles": True})
    assert r.status_code == 200, r.text
    assert r.json()["video"]["moteur"] == "SeedVR2 (agrandissement)" and r.json()["video"]["echelle"] == "4k"
    # Une voix entendue dans le morceau dès 27 s (30/09) : posé dès 0 s, il irait à
    # 30,2 s -- refusé, avec le début qui passe ; posé à 3,5 s, accepté.
    monkeypatch.setattr(h3, "_chansons_pretes",
                        lambda: [{"id": "c" * 32, "titre": "Campus", "cree_a": 0, "voix_des_s": 27.0}])
    r = c.post("/video-h3/musique", headers=CLE, json={"film": st["id"], "chanson": "c" * 32})
    assert r.status_code == 400 and "27.0 s" in r.json()["detail"] and "3.2 s" in r.json()["detail"]
    r = c.post("/video-h3/musique", headers=CLE, json={"film": st["id"], "chanson": "c" * 32, "debut_s": 3.5})
    assert r.status_code == 200, r.text
    # L'écoute absente : refus avant tout travail.
    monkeypatch.delenv("FREE_TIER_MANAGER_KEY")
    assert c.post("/video-h3/sous-titres", headers=CLE, json={"film": hd}).status_code == 503
    assert c.post("/video-h3/sous-titres", headers=CLE, json={"film": "z" * 32}).status_code == 404


def test_un_scenario_a_deux_pose_la_musique_des_le_plan_voulu(h3, monkeypatch, sans_regles, sans_depart_auto):
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
    assert "<Subject 2> (S2) demande <d>[English] Is this seat taken?</d>" in tournes[0]["invite"]
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

    def tourner(jid, code, precedent, retirer, ou="modal"):
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
    # Le plan au texte changé est jugé sur son NOUVEAU texte (bug du 02/10, plan 6a) ; les autres, sur l'origine.
    initiaux = r.json()["plans_initiaux"]
    assert initiaux[0] == plans[0] and initiaux[2] == plans[2]
    assert initiaux[1]["image_paroles"] == "Léa, en manteau rouge, répond « Non. »"
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


def test_un_scenario_echoue_en_route_se_reprend_sans_retourner_ses_plans_faits(h3, monkeypatch, tmp_path,
                                                                               sans_regles):
    """01/10, « Leila et un martien » : arrêt au plan 6 (suite d'une coupe), cinq plans
    tournés que seul un scénario réussi savait reprendre. Le plan 6 part seul, recollé
    aux cinq, et sa chaîne compte depuis la coupe du plan 5."""
    v = h3.video_h3
    sid, _ = _scenario_tourne(h3, monkeypatch, tmp_path)
    sc = v.scenario_lire(sid)
    plans = [{"image_paroles": "Plan %d" % (k + 1), "ambiance": "", "enchainement": e}
             for k, e in enumerate(["coupe", "suite", "suite", "suite", "coupe", "suite"])]
    v.scenario_ecrire(dict(sc, etat="échoué", erreur="Plan 6 : déjà 4 plans", plans=plans, film=None,
                           film_sans_musique=None, musique=None, travaux=[str(k) * 32 for k in range(1, 6)],
                           fins_images=[124, 248, 372, 496, 620]))
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    extraits = []
    monkeypatch.setattr(h3.montage, "extraire", lambda f, a, b: extraits.append((a, b)) or b"X")
    monkeypatch.setattr(h3.montage, "recoller_son", lambda a, b, retirer: a + b)
    monkeypatch.setattr(h3.montage, "derniere_image", lambda octets: base64.b64decode(PNG))
    monkeypatch.setattr(h3.montage, "fin", lambda octets, n: b"raccord")
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 620)
    monkeypatch.setattr(h3, "_controle_derniere_image", lambda *a: None)
    tournes = []

    def tourner(jid, code, precedent, retirer, ou="modal"):
        job = h3.read_job(jid)
        tournes.append((precedent, job["video"]))
        job["video"]["secondes"] = round(744 / 24, 2)
        job["status"] = "succeeded"
        h3.write_job(jid, job)

    monkeypatch.setattr(h3, "run_video_h3", tourner)
    fils, vrai = [], h3.run_scenario_h3
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    r = client(h3).post(f"/video-h3/scenario/{sid}/rejouer", headers=CLE, json={"plans": plans})
    assert r.status_code == 200, r.text
    assert r.json()["repris"] == [1, 2, 3, 4, 5]
    vrai(*fils[0])
    nouveau = v.scenario_lire(r.json()["id"])
    assert nouveau["etat"] == "réussi", nouveau["erreur"]
    # Les cinq plans découpés dans le travail du plan 5, qui porte tout le film d'avant.
    assert extraits == [(0, 124), (124, 248), (248, 372), (372, 496), (496, 620)]
    (precedent, video), = tournes
    pose = h3.read_job(precedent)["video"]
    assert pose["mode"] == "reprise" and pose["chaine"] == 1
    assert video["mode"] == "prolonger" and video["chaine"] == 2 and video["plans"] == 6
    # Un scénario en cours ou sans aucun plan fait ne se reprend pas.
    v.scenario_ecrire(dict(v.scenario_lire(sid), etat="en cours"))
    assert client(h3).post(f"/video-h3/scenario/{sid}/rejouer", headers=CLE,
                           json={"plans": plans}).status_code == 409


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


def test_le_maitre_se_deplie_apres_le_juge_plan_par_plan(h3, monkeypatch, tmp_path):
    """03/10 : chaque plan du maître tourné seul entre ses deux images du maître ; pas avant le juge."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    film = tmp_path / "maitre.mp4"
    film.write_bytes(b"MAITRE")
    plans = [{"image_paroles": "Oscar climbs the stairs.", "enchainement": "coupe", "camera": v.lire_camera(None)},
             {"image_paroles": "Oscar lights the lantern and says « Voilà. »", "enchainement": "coupe",
              "camera": v.lire_camera({"mouvement": "avance"})}]
    jid = "c" * 32
    job = {"id": jid, "status": "succeeded", "video": {"moteur": "MiniMax H3 (ComfyUI)", "maitre": {
        "plans": plans, "debuts_s": [0.0, 2.583], "longueur": 124, "commun": {"fiche": None, "definition": "480p"}}}}
    h3.write_job(jid, job)
    monkeypatch.setattr(h3, "_video_h3_octets", lambda j: film if j == jid else None)
    c = client(h3)
    r = c.post("/video-h3/maitre/%s/deplier" % jid, headers=CLE, json={})
    assert r.status_code == 409 and "Jugez d'abord" in r.json()["detail"]
    # Le juge dit la coupe que le maître n'a pas faite (« Le phare », 03/10).
    monkeypatch.setattr(h3, "_photos_des_fiches", lambda ids: ([], []))
    monkeypatch.setattr(h3, "_juger_passage", lambda *a: asyncio.sleep(0, {"verdict": "ok", "defauts": []}))
    monkeypatch.setattr(h3, "_ecouter", lambda *a: asyncio.sleep(0, {"attendu": [], "ok": None}))
    monkeypatch.setattr(h3.montage, "coupes_vues", lambda f, seuil=0.3: [] if isinstance(f, bytes) else 1 / 0)
    r = c.post("/video-h3/jobs/%s/juger" % jid, headers=CLE)
    assert r.status_code == 200 and r.json()["verdict"] == "defaut", r.text
    assert "coupe du plan 2" in r.json()["defauts"][-1]["quoi"]

    job["jugement"] = {"verdict": "ok", "defauts": []}
    h3.write_job(jid, job)
    monkeypatch.setattr(h3.montage, "coupes_vues", lambda f, seuil=0.3: [2.5])
    pris = []
    monkeypatch.setattr(h3.montage, "image_numero", lambda f, n: pris.append(n) or base64.b64decode(PNG))
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: base64.b64decode(PNG))
    tournes = []
    monkeypatch.setattr(h3, "run_video_h3", lambda j, *a: tournes.append(h3.read_job(j)["video"]))
    r = c.post("/video-h3/maitre/%s/deplier" % jid, headers=CLE, json={"definition": "768p"})
    assert r.status_code == 200, r.text
    # Deux plans séparés par une coupe : chacun part de sa première image seule (« Le phare » n° 4, 04/10).
    assert r.json()["cles"] == [[0, 59], [61, 123]] and pris == [0, 61]
    for _ in range(50):
        if len(tournes) == 2:
            break
        time.sleep(0.05)
    assert [t["mode"] for t in tournes] == ["premiere"] * 2
    # Le plan déplié garde sa réplique et sa caméra ; il sait d'où il vient.
    assert "Voilà." in tournes[1]["invite"] and "pushes in" in tournes[1]["invite"]
    # Personne d'autre que les personnages nommés (« Le robot perdu », 04/10 : un homme inventé) ;
    # le texte montré au client reste le sien.
    assert all(v.PERSONNE_D_AUTRE in t["invite"] for t in tournes)
    assert tournes[0]["texte_client"] == "Oscar climbs the stairs."
    # L'image de départ de chaque clip est gardée dès le dépliage, lisible par sa route (04/10).
    departs = r.json()["departs"]
    assert tournes[1]["deplie_de"] == {"maitre": jid, "plan": 2, "images": [61], "depart": departs["2"]}
    assert c.get("/video-h3/depart/%s" % departs["1"], headers=CLE).json()["image"].endswith(PNG)
    assert h3.read_job(jid)["deplie"] == r.json()["clips"]
    # Une suite : le plan d'avant finit sur l'image dont elle repart (première et dernière).
    job["video"]["maitre"]["plans"][1]["enchainement"] = "suite"
    h3.write_job(jid, job)
    monkeypatch.setattr(h3.montage, "coupes_vues", lambda f, seuil=0.3: [])
    pris.clear()
    tournes.clear()
    r = c.post("/video-h3/maitre/%s/deplier" % jid, headers=CLE, json={"definition": "768p"})
    assert r.status_code == 200, r.text
    assert r.json()["cles"] == [[0, 62], [62, 123]] and pris == [0, 62, 62]
    for _ in range(50):
        if len(tournes) == 2:
            break
        time.sleep(0.05)
    assert [t["mode"] for t in tournes] == ["premiere_derniere", "premiere"]


def test_pres_d_une_coupe_demandee_un_changement_plus_faible_suffit(h3):
    """« Le robot perdu », film 5 : trois maîtres refusés ; les coupes des plans 2 et 3 y étaient,
    entre deux plans de nuit (scene 0,27 et 0,29 à 1,83 et 3,63 s, sous le seuil de 0,3)."""
    v = h3.video_h3
    plans = [{"enchainement": "coupe"}] * 3
    with pytest.raises(ValueError, match="coupe du plan 2, 3"):
        v.cles_du_maitre(plans, [0.0, 1.885, 3.771], [], 124)
    assert v.cles_du_maitre(plans, [0.0, 1.885, 3.771], [], 124, [1.833, 3.625]) == [(0, 43), (45, 86), (88, 123)]
    # Loin d'une coupe demandée, ou pour une suite, le changement faible ne compte pas.
    suite = [{"enchainement": "coupe"}, {"enchainement": "suite"}]
    assert v.cles_du_maitre(suite, [0.0, 2.6], [], 124, [2.5]) == [(0, 62), (62, 123)]
    assert v.cles_du_maitre(plans[:2], [0.0, 2.6], [1.0], 124, [1.0, 2.4])[1][0] == round(2.4 * 24) + 1


def test_le_depliage_retouche_l_image_du_maitre_d_apres_les_fiches(h3, monkeypatch, tmp_path):
    """« Le robot perdu », film 5, 04/10 : le maître part de la seule image du plan 1, sans Pixel ;
    H3 l'a fait cube blanc au lieu de la sphère de sa fiche. Au dépliage, l'image du maître d'où
    part chaque plan est redessinée d'après les fiches des personnages qu'il nomme."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    leila = v.fiche_creer("Leila", "x")["id"]
    pixel = v.fiche_creer("Pixel", "x")["id"]
    for f in (leila, pixel):
        v.fiche_poser_image(f, "face", PNG)
    film = tmp_path / "maitre.mp4"
    film.write_bytes(b"MAITRE")
    plans = [{"image_paroles": "Leila looks at the sky.", "enchainement": "coupe", "camera": v.lire_camera(None)},
             {"image_paroles": "Pixel floats beside Leila.", "enchainement": "coupe", "camera": v.lire_camera(None)},
             {"image_paroles": "A spaceship descends.", "enchainement": "coupe", "camera": v.lire_camera(None)}]
    jid = "d" * 32
    job = {"id": jid, "status": "succeeded", "jugement": {"verdict": "defaut", "defauts": [{"quoi": "Leila en double"}]},
           "video": {"moteur": "MiniMax H3 (ComfyUI)", "maitre": {
               "plans": plans, "debuts_s": [0.0, 1.7, 3.4], "longueur": 124,
               "commun": {"fiches": [leila, pixel], "definition": "480p"}}}}
    h3.write_job(jid, job)
    monkeypatch.setattr(h3, "_video_h3_octets", lambda j: film if j == jid else None)
    monkeypatch.setattr(h3.montage, "coupes_vues", lambda f, seuil=0.3: [1.68, 3.38] if seuil < 0.3 else [1.68])
    monkeypatch.setattr(h3.montage, "image_numero", lambda f, n: base64.b64decode(PNG))
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: base64.b64decode(PNG))
    monkeypatch.setattr(h3, "run_video_h3", lambda j, *a: None)
    demandes = []

    async def image(demande):
        demandes.append(demande)
        if len(demandes) == 2:
            raise h3.HTTPException(502, "aucune image")
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)
    # Qwen, deuxième dessin : il réussit au plan 1, échoue au plan 2.
    qwen = []
    construire = h3.retouche_qwen.construire_script
    monkeypatch.setattr(h3.retouche_qwen, "construire_script",
                        lambda image, refs, texte: qwen.append((refs, texte)) or construire(image, refs, texte))

    def modal(j, code, gpu, internet, **kw):
        assert j == jid and kw["gpu_type"] == "L40S" and kw["usage"] is None and kw["volume"] == v.VOLUME
        if len(qwen) > 1:
            return {"exit_code": 1, "stderr": "CALCUL_ECHOUE", "artifacts": []}
        sortie = h3.JOBS / j / "modal-output"
        sortie.mkdir(parents=True, exist_ok=True)
        (sortie / "0000-retouche.png").write_bytes(base64.b64decode(PNG))
        return {"exit_code": 0, "stderr": "", "artifacts": [{"name": "0000-retouche.png"}]}
    monkeypatch.setattr(h3, "modal_execute", modal)
    controles = []

    async def juge(consigne, quoi="", images=None, modele=""):
        if quoi == "l'étiquette d'un personnage":   # écrite une fois par fiche, avant les clips
            return "the girl with dark brown hair"
        controles.append((quoi, len(images or [])))
        return ('{"ok": false, "fautes": ["Pixel est cubique"]}' if len(controles) == 1
                else '{"ok": true, "fautes": []}')
    monkeypatch.setattr(h3, "_chat_du_studio", juge)
    r = client(h3).post("/video-h3/maitre/%s/deplier" % jid, headers=CLE, json={"retoucher": True, "forcer": True})
    assert r.status_code == 200, r.text
    ret = r.json()["retouches"]
    assert ret["1"] == "retouchée par Qwen (1 fiches), contrôle ok au dessin 2"
    # Google refuse, puis Qwen : un refus ne bloque rien, Google n'est pas redemandé au troisième dessin.
    assert ret["2"].startswith("image du maître gardée") and "google" in ret["2"] and "Qwen" in ret["2"]
    assert len(demandes) == 2 and len(qwen) == 2
    assert ret["3"].startswith("aucun personnage")
    # La remarque du juge du maître est à éviter dès le premier dessin ; celle du contrôle, au suivant.
    assert "image à reprendre" in demandes[0]["prompt"] and "Leila en double" in demandes[0]["prompt"]
    refs, texte = qwen[0]
    assert "Pixel est cubique" in texte and "Leila en double" not in texte
    assert texte.startswith("Leila is the character of <image2>.") and len(refs) == 1   # sa photo, pas de planche
    # Les noms, pas l'action : « looks at the sky » se dessinerait (04/10, la capsule déjà au sol au plan 1).
    assert "Leila" in demandes[0]["prompt"] and "looks at the sky" not in demandes[0]["prompt"]
    assert len(demandes[0]["image_reference"]) == 2   # la fiche de Leila, puis l'image du maître
    assert controles[0] == ("le contrôle de la retouche", 3)   # maître, retouche, photo de Leila
    assert len(demandes[1]["image_reference"]) == 3   # Pixel et Leila, puis l'image du maître
    # Sans la demande, rien n'est retouché.
    demandes.clear()
    r = client(h3).post("/video-h3/maitre/%s/deplier" % jid, headers=CLE, json={"forcer": True})
    assert r.status_code == 200 and "retouches" not in r.json() and not demandes


def test_la_retouche_redemande_un_refus_passager(h3, monkeypatch):
    """« Le robot perdu », 04/10 : deux plans ont gardé le Pixel cube du maître sur un 503 de Google."""
    v = h3.video_h3
    pixel = v.fiche_creer("Pixel", "x")["id"]
    v.fiche_poser_image(pixel, "face", PNG)
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: base64.b64decode(PNG))
    attentes, appels = [], []

    async def dormir(s):
        attentes.append(s)
    monkeypatch.setattr(h3.asyncio, "sleep", dormir)

    async def image(demande):
        appels.append(1)
        if len(appels) <= 2:
            raise h3.HTTPException(502, "Google a refuse la demande d'image (HTTP 503).")
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)

    async def juge(consigne, quoi="", images=None, modele=""):
        return '{"ok": true, "fautes": []}'
    monkeypatch.setattr(h3, "_chat_du_studio", juge)
    plan = {"image_paroles": "Pixel floats."}
    _, note = asyncio.run(h3._retoucher_depart(base64.b64decode(PNG), {"fiches": [pixel]}, plan, "480p"))
    assert note == "retouchée par l'image du Studio (1 fiches), contrôle ok au dessin 1"
    assert attentes == list(h3.RETOUCHE_REDEMANDES_S)
    # Toujours refusée : l'image du maître est gardée, et le dit.
    appels.clear()
    attentes.clear()
    monkeypatch.setattr(h3, "_image_du_studio", lambda d: (_ for _ in ()).throw(
        h3.HTTPException(502, "Google a refuse la demande d'image (HTTP 503).")))
    _, note = asyncio.run(h3._retoucher_depart(base64.b64decode(PNG), {"fiches": [pixel]}, plan, "480p"))
    assert note.startswith("image du maître gardée") and len(attentes) == 2


def test_l_image_de_depart_est_controlee_et_redessinee_avec_les_fautes_du_juge(h3, monkeypatch):
    """Film 5 relancé, 04/10 : une rue de ville pour « in the garden ». Propriétaire : « autant le faire
    bosser lui s'il sait mieux le faire »."""
    v = h3.video_h3
    demandes = []

    async def depart(corps):
        demandes.append(corps)
        return {"id": v.depart_poser(PNG), "image": PNG, "texte": "d%d" % len(demandes)}
    monkeypatch.setattr(h3, "_depart_redemande", depart)
    reponses = iter(['{"ok": false, "fautes": ["une rue de ville, pas un jardin", "jour au lieu de nuit"]}',
                     '{"ok": false, "fautes": ["pas d\'étoiles"]}', '{"ok": true, "fautes": []}'])
    vus = []

    async def juge(consigne, quoi="", images=None, modele=""):
        vus.append((consigne, quoi, len(images or [])))
        return next(reponses)
    monkeypatch.setattr(h3, "_chat_du_studio", juge)
    plan = {"image_paroles": "Wide shot, night. In the garden, Leila stands. A capsule falls. Leila dit : « Oh ! »"}
    d = asyncio.run(h3._depart_controle(plan, {"texte": "x", "fiches": []}))
    assert d["texte"] == "d3" and len(demandes) == 3
    assert "a_eviter" not in demandes[0] and demandes[1]["a_eviter"] == ["une rue de ville, pas un jardin",
                                                                       "jour au lieu de nuit"]
    assert vus[0][1] == "le contrôle de l'image de départ" and vus[0][2] == 1
    assert "In the garden" in vus[0][0] and "Oh !" not in vus[0][0] and "FIRST frame" in vus[0][0]
    # Toujours fautive : la moins fautive est gardée (le 2e dessin, une faute).
    demandes.clear()
    reponses = iter(['{"ok": false, "fautes": ["a", "b"]}', '{"ok": false, "fautes": ["c"]}',
                     '{"ok": false, "fautes": ["d", "e", "f"]}'])
    assert asyncio.run(h3._depart_controle(plan, {"texte": "x"}))["texte"] == "d2"


def test_la_retouche_garde_le_dessin_le_moins_fautif_et_saute_qwen_sans_modal(h3, monkeypatch):
    v = h3.video_h3
    pixel = v.fiche_creer("Pixel", "x")["id"]
    v.fiche_poser_image(pixel, "face", PNG)
    monkeypatch.setattr(h3, "modal_configured", lambda: False)
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: pytest.fail("Modal n'est pas branché"))
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: base64.b64decode(PNG))
    appels = []

    async def image(demande):
        appels.append(1)
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)
    fautes = iter(['{"ok": false, "fautes": ["a"]}', '{"ok": false, "fautes": ["b", "c"]}'])

    async def juge(consigne, quoi="", images=None, modele=""):
        return next(fautes)
    monkeypatch.setattr(h3, "_chat_du_studio", juge)
    _, note = asyncio.run(h3._retoucher_depart(base64.b64decode(PNG), {"fiches": [pixel]},
                                               {"image_paroles": "Pixel floats."}, "480p", jid="e" * 32))
    assert len(appels) == 2   # dessins 1 et 3 ; Qwen sauté
    assert note == "retouchée par l'image du Studio (1 fiches, dessin 1), fautes restantes : a"


def test_un_film_coupe_par_un_redemarrage_se_reprend(h3, monkeypatch, tmp_path):
    """« Le robot perdu », 04/10 : la reconstruction a coupé le film, resté « en cours » dans son
    fichier ; « Ce film est déjà en cours » refusait sa reprise sans fin."""
    monkeypatch.setattr(h3, "DOSSIER_FILMS_AUTO", tmp_path / "films")
    monkeypatch.setattr(h3, "_FILMS_AUTO_FILS", {})
    fin = threading.Event()

    class Film:
        def __init__(self, etat, dossier, *a):
            self.etat, self.dossier = etat, dossier

        def ecrire(self):
            self.dossier.mkdir(parents=True, exist_ok=True)
            (self.dossier / (self.etat["id"] + ".json")).write_text(json.dumps(self.etat), encoding="utf-8")

        def derouler(self):
            fin.wait(5)
    monkeypatch.setattr(h3.film_auto, "Film", Film)
    fid = "e" * 32
    Film({"id": fid, "statut": "en cours"}, tmp_path / "films").ecrire()   # coupé : aucun fil ici
    c = client(h3)
    assert c.post("/video-h3/film/auto/%s/reprendre" % fid, headers=CLE).status_code == 200
    r = c.post("/video-h3/film/auto/%s/reprendre" % fid, headers=CLE)   # son fil tourne : refus
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"]
    fin.set()


def test_un_film_se_refait_depuis_une_etape_en_gardant_les_precedentes(h3, monkeypatch, tmp_path):
    """« Le robot perdu », 04/10 : le montage refait (son coupé des clips parlants), les plans gardés."""
    monkeypatch.setattr(h3, "DOSSIER_FILMS_AUTO", tmp_path / "films")
    monkeypatch.setattr(h3, "_FILMS_AUTO_FILS", {})
    lances = []
    monkeypatch.setattr(h3, "_film_auto_lancer", lambda etat: lances.append(dict(etat)) or etat)
    fid = "e" * 32
    etat = h3.film_auto.nouvel_etat("Oscar allume le phare.")
    etat.update(id=fid, statut="fini", faites=list(h3.film_auto.Film.ETAPES))
    (tmp_path / "films").mkdir()
    (tmp_path / "films" / (fid + ".json")).write_text(json.dumps(etat), encoding="utf-8")
    c = client(h3)
    r = c.post("/video-h3/film/auto/%s/reprendre" % fid, headers=CLE, json={"depuis": "montage"})
    assert r.status_code == 200, r.text
    assert lances[-1]["faites"] == ["personnages", "decoupage", "musique_lancee", "maitre", "deplier"]
    assert lances[-1]["statut"] == "en cours"
    assert c.post("/video-h3/film/auto/%s/reprendre" % fid, headers=CLE,
                  json={"depuis": "rien"}).status_code == 400


def test_le_proprietaire_choisit_l_essai_garde_pour_un_plan(h3, monkeypatch, tmp_path):
    """« Le robot perdu », 04/10 : « prends l'essai 2 du plan 4 » (l'essai 1 avait un double de Leila)."""
    monkeypatch.setattr(h3, "DOSSIER_FILMS_AUTO", tmp_path / "films")
    monkeypatch.setattr(h3, "_FILMS_AUTO_FILS", {})
    fid = "e" * 32
    etat = h3.film_auto.nouvel_etat("Oscar allume le phare.")
    etat.update(id=fid, statut="fini", clips=[{"job": "a" * 32, "verdict": "defaut", "defauts": ["double"]}],
                journal=[{"etape": "clip", "plan": 1, "job": "a" * 32, "verdict": "defaut", "defauts": ["double"]},
                         {"etape": "clip_rejoue", "plan": 1, "job": "b" * 32, "verdict": "defaut",
                          "defauts": ["antenne"]}])
    (tmp_path / "films").mkdir()
    (tmp_path / "films" / (fid + ".json")).write_text(json.dumps(etat), encoding="utf-8")
    c = client(h3)
    r = c.post("/video-h3/film/auto/%s/clip" % fid, headers=CLE, json={"plan": 1, "job": "b" * 32})
    assert r.status_code == 200, r.text
    lu = json.loads((tmp_path / "films" / (fid + ".json")).read_text(encoding="utf-8"))
    assert lu["clips"][0] == {"job": "b" * 32, "verdict": "defaut", "defauts": ["antenne"], "choisi": True}
    for corps in ({"plan": 1, "job": "c" * 32}, {"plan": 2, "job": "b" * 32}):
        assert c.post("/video-h3/film/auto/%s/clip" % fid, headers=CLE, json=corps).status_code == 400


def test_le_juge_voit_tout_un_clip_long_et_cherche_les_doubles(h3, monkeypatch):
    """03/10, clip maître de 15 s : la planche 4 x 3 n'en montrait que 6 s, et le juge a dit « ok »
    à une fillette dédoublée à 12,5 s. Tout le clip est vu, en planches de 18 s au plus."""
    v = h3.video_h3
    lances = []
    monkeypatch.setattr(h3.montage, "_lancer", lambda args, quoi: lances.append(args))
    for duree in (15.08, 5.2):
        with pytest.raises(h3.montage.MontageImpossible):   # le faux ffmpeg n'écrit rien
            h3.montage.planche(b"mp4", 0.0, duree)
    assert "fps=2,scale=416:-1,tile=6x6" in lances[0]
    assert "fps=2,scale=416:-1,tile=4x3" in lances[1]   # un plan de 5 s : la planche d'avant

    planches = []
    monkeypatch.setattr(h3.montage, "planche", lambda f, debut, duree: planches.append((debut, round(duree, 2)))
                        or (b"\x89PNG", int(duree * 2 + 0.999)))
    monkeypatch.setattr(h3.montage, "planche_serree", lambda *a: (b"\x89PNG", 12))
    consignes = []

    async def chat(consigne, quoi="", images=None, modele=""):
        consignes.append(consigne)
        return ('{"verdict": "defaut", "defauts": [{"image": 2, "quoi": "deux fillettes"}]}'
                if len(consignes) == 2 else '{"verdict": "ok", "defauts": []}')
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    texte = "[Shot 1] Mila waters the pot. [Shot 2] At 00:12.500, the camera cuts to a new shot. Mila smiles."
    verdict = asyncio.run(h3._juger_passage(b"mp4", 0.0, 20.0, [], [], texte))
    assert planches == [(0.0, 18.0), (18.0, 2.0)]
    assert verdict["verdict"] == "defaut" and verdict["defauts"] == [{"t_s": 18.5, "quoi": "deux fillettes"}]
    assert "shown twice at the same time" in consignes[0] and "planned cuts" in consignes[0]
    assert "Frame 1 of this sheet" not in consignes[0] and "Frame 1 of this sheet is at 18 s" in consignes[1]
    assert "ONE video shot:" in v.consigne_jugement([], "Mila waters the pot.")
    # « Le robot perdu », 04/10 : la coupe voulue est dite par son numéro d'image, sur sa planche seulement.
    assert "12.5 s, about frame 26" in consignes[0] and "about frame" not in consignes[1]


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


def test_le_ton_prononce_par_h3_est_un_defaut_et_l_adverbe_le_dit_deja():
    """01/10, « Leila et un martien », plan 6, tourné ici : « shouts, joyfully: overjoyed,
    bursting with happiness, <d>[French] Reviens quand tu veux !</d> » ; H3 a prononcé le
    ton, et l'écoute disait « ok » (segments du routeur, tels quels)."""
    import importlib
    v = importlib.import_module("video_h3")
    entendu = "Les 47 nœuds bannances, Overjoyed, Brusting with Happiness, reviens quand tu veux."
    p = v.comparer_paroles("Leila shouts, joyfully: « [French, joy] Reviens quand tu veux ! »", entendu)
    assert p["ok"] is False and p["ton_dit"] == ["overjoyed, bursting with happiness"]
    assert "overjoyed" in v.defaut_de_paroles(p, 25.8)["quoi"]
    # La réplique seule, ou un mot du ton qui est DANS la réplique : pas de défaut.
    assert v.comparer_paroles("« Reviens quand tu veux ! »", "Reviens quand tu veux !")["ok"] is True
    assert v.comparer_paroles("« I am bursting with happiness! »", "I am bursting with happiness!")["ok"] is True
    # Et à la source : l'adverbe dit déjà l'émotion, le ton ne s'ajoute plus.
    assert v._ton("joie", "waves her right arm and shouts, joyfully:") == ""
    assert v._ton("joie", "waves her right arm and shouts:") == ", overjoyed, bursting with happiness,"


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
    # 01/10 : l'image de départ est aussi ÉPINGLÉE à l'image 0 (deux Leila sinon).
    g = plan["demande"]["graphe"]
    assert g["11"]["class_type"] == "MiniMaxH3AddGuide"
    assert g["11"]["inputs"]["image"] == ["63", 0] and g["11"]["inputs"]["frame_idx"] == 0
    assert "audio" not in g["11"]["inputs"] and g["13"]["inputs"]["conditioning"] == ["11", 0]
    assert "MiniMaxH3AddGuide" in plan["demande"]["classes"]
    # Sans image de départ, rien n'est épinglé.
    assert "11" not in v.preparer(dict(p0, depart_reference=None))["demande"]["graphe"]
    # Des fiches sans photo : l'image seule, et les fiches donnent les voix.
    lea, james = v.fiche_creer("Léa", "x")["id"], v.fiche_creer("James", "y")["id"]
    corps = {"fiches": [lea, james], "langues": {james: "English"}, "langue": "French", "longueur": 124}
    p0 = h3._scenario_prepare(corps, plans[:1])[2][0]["payload"]
    assert p0["mode"] == "premiere" and p0["images"] == [base64.b64encode(CADRE).decode()]
    assert p0["description_premiere"] == "Un café bondé, une chaise vide"
    invite = v.preparer(dict(p0, images=[PNG]))["resume_public"]["invite"]
    # Sans photos de fiche, les noms restent des noms ; James parle anglais.
    assert invite.startswith(v.CONSIGNE_I2VA + "\n\nintegrated_multimodal_description: [Shot 1] "
                             "<Picture 1>: Un café bondé, une chaise vide. ")
    assert "<Subject" not in invite and "James (S2)" in invite and "[English]" in invite
    assert "detailed_description" not in invite
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
    monkeypatch.setattr(h3.montage, "largeur_image", lambda image: 1344)   # visage de 269 px : il se juge
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


def test_un_visage_trop_petit_ne_se_juge_pas(h3, monkeypatch):
    # 02/10, film 4 : fin du plan 2 en plan large (1344 px), visage de 0,07 de large (≈ 94 px) ;
    # « faible » 3 fois sur 3 pour la Leila du plan 1. Le modèle n'est plus consulté.
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    v = h3.video_h3
    fid = v.fiche_creer("Leila", "une fille")["id"]
    v.fiche_poser_image(fid, "face", JPG)
    vus = []
    monkeypatch.setattr(h3.montage, "recadrer_zone", lambda image, zone: CADRE)
    monkeypatch.setattr(h3.montage, "planche_visages", lambda images: b"\x89PNGplanche")
    monkeypatch.setattr(h3.montage, "largeur_image", lambda image: 1344)
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        ['{"x0": 0.51, "y0": 0.35, "x1": 0.58, "y1": 0.46}', '{"ressemblance": "faible", "ecarts": "profil"}'], vus))
    d = asyncio.run(h3._comparer_visage(base64.b64decode(PNG), fid))
    assert d["ressemblance"] == v.TROP_PETIT and "94 px" in d["ecarts"] and len(vus) == 1
    assert h3.regles.regles_depart([], {"comptes": [], "texte_ajoute": False}, {"Leila": d["ressemblance"]})[7]["ok"] is None


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


def test_les_tenues_se_relevent_plan_par_plan_et_se_gardent_sur_la_fiche(h3, monkeypatch, sans_regles, sans_depart_auto, sans_objets_clefs):
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


def test_un_personnage_hors_champ_au_debut_n_est_pas_joint_a_l_image(h3, monkeypatch):
    # Film campus, 01/10 : Tyler entre au plan 1 ; joint à l'image, il y était dessiné.
    v = h3.video_h3
    leila = v.fiche_creer("Leila", "x")["id"]
    tyler = v.fiche_creer("Tyler", "y")["id"]
    for fid in (leila, tyler):
        v.fiche_poser_image(fid, "face", PNG)
    demandes = []

    async def image(demande):
        demandes.append(demande)
        return "data:image/png;base64," + PNG

    monkeypatch.setattr(h3, "_image_du_studio", image)
    elements = [{"nom": "Leila", "debut": "In the foreground at the centre"},
                {"nom": "Tyler", "debut": "off-frame", "mouvement": "walks in from the left"}]
    r = client(h3).post("/video-h3/depart", headers=CLE, json={
        "texte": "Leila lit une carte", "fiches": [leila, tyler], "elements": elements})
    assert r.status_code == 200, r.text
    assert "Leila est la personne" in demandes[0]["prompt"] and "Tyler" not in demandes[0]["prompt"]
    assert len(demandes[0]["image_reference"]) == 1
    # Sans tableau, rien ne change : les deux fiches partent.
    assert v.fiches_au_depart([leila, tyler], None) == [leila, tyler]
    assert v.fiches_au_depart([leila, tyler], [{"nom": "tyler", "debut": "Out of frame"}],
                              "Leila lit une carte") == [leila]
    # « Leila et un martien », 01/10 : Zib, absent du plan 1 (ni tableau ni texte), y était dessiné.
    zib = v.fiche_creer("Zib", "z")["id"]
    plan1 = [{"nom": "Leila", "debut": "in the foreground"}, {"nom": "the saucer", "debut": "off-frame"}]
    assert v.fiches_au_depart([leila, zib], plan1, "Leila looks into the telescope.") == [leila]
    assert v.fiches_au_depart([leila, zib], plan1, "Leila looks at Zib.") == [leila, zib]


def test_l_image_de_depart_nomme_qui_elle_montre_et_pas_le_hors_champ(h3):
    # 01/10 : « <Picture 9> is the first frame of [Shot 1]. » ne liait la Leila de l'image à
    # aucune fiche ; le guide de MiniMax écrit « …, showing a woman… » (ref-en.txt, 2.2).
    v = h3.video_h3
    leila, tyler = v.fiche_creer("Leila", "x")["id"], v.fiche_creer("Tyler", "y")["id"]
    for fid in (leila, tyler):
        v.fiche_poser_image(fid, "face", PNG)
    d = demande(mode="references", fiches=[leila, tyler], depart_reference=PNG,
                image_paroles="Leila lit une carte ; Tyler entre par la gauche.",
                elements=[{"nom": "Leila", "debut": "centre"}, {"nom": "Tyler", "debut": "off-frame"}])
    invite = v.preparer(d)["resume_public"]["invite"]
    assert "<Picture 3> is the first frame of [Shot 1], showing <Subject 1>. " in invite
    # Sans tableau : tous ceux que le plan nomme (l'image a été faite avec leurs fiches).
    d.pop("elements")
    invite = v.preparer(d)["resume_public"]["invite"]
    assert "<Picture 3> is the first frame of [Shot 1], showing <Subject 1> and <Subject 2>. " in invite


def test_la_camera_au_format_du_guide_fixe_par_defaut(h3):
    """01/10 : sans phrase de caméra, H3 a reculé pendant tout le plan 1 (Modal). Le guide
    de MiniMax (4.3) : type + amplitude + vitesse, en phrase dans le plan."""
    v = h3.video_h3
    assert v.phrase_camera(None) == "The camera holds a static shot throughout."
    assert v.phrase_camera({"mouvement": "avance", "amplitude": "petite", "vitesse": "lente"}) == \
        "The camera pushes in with small amplitude at slow speed."
    assert v.phrase_camera({"mouvement": "pano_droite", "vitesse": "rapide"}) == "The camera pans right at fast speed."
    assert v.phrase_camera({"mouvement": "auto"}) == ""
    # Fixe : ni amplitude ni vitesse, même envoyées.
    assert v.lire_camera({"mouvement": "fixe", "amplitude": "grande"}) == v.CAMERA_DEFAUT
    for mauvais in ({"mouvement": "vol"}, {"mouvement": "avance", "vitesse": "folle"}, "fixe"):
        with pytest.raises(ValueError):
            v.lire_camera(mauvais)
    # Après la première phrase finie hors réplique ; en tête s'il n'y en a pas.
    assert v.avec_camera("In a medium shot, Leila stands. Tyler says « Hi. Lost? » and smiles.", "C.") == \
        "In a medium shot, Leila stands. C. Tyler says « Hi. Lost? » and smiles."
    assert v.avec_camera("Tyler says « Hi. »", "C.") == "C. Tyler says « Hi. »"
    d = demande(image_paroles="In a medium shot, Leila reads a map. She smiles.",
                camera={"mouvement": "recule", "amplitude": "petite"})
    assert "Leila reads a map. The camera pulls out with small amplitude. She smiles." in \
        v.preparer(d)["resume_public"]["invite"]
    assert "camera" not in v.preparer(dict(d, camera={"mouvement": "auto"}))["resume_public"]["invite"]


def test_la_camera_du_plan_suit_le_plan(h3):
    """Le menu de chaque plan : gardé par verifier_plans, la correction et la découpe ;
    changé, le plan se retourne ; absent (ancien scénario), il vaut « fixe »."""
    v = h3.video_h3
    avance = {"mouvement": "avance", "amplitude": "", "vitesse": "lente"}
    plans = v.verifier_plans([{"image_paroles": "Leila reads.", "ambiance": "", "enchainement": "coupe",
                               "camera": avance}])
    assert plans[0]["camera"] == avance
    assert v.verifier_plans([{"image_paroles": "Leila reads.", "ambiance": ""}])[0]["camera"] == v.CAMERA_DEFAUT
    with pytest.raises(ValueError, match="Plan 1"):
        v.verifier_plans([{"image_paroles": "x", "ambiance": "", "camera": {"mouvement": "vol"}}])
    corrige = v.lire_correction('[{"image_paroles": "Leila reads the map.", "ambiance": ""}]', plans)
    assert corrige[0]["camera"] == avance
    ancien = [{"image_paroles": "Leila reads.", "ambiance": "", "enchainement": "coupe"}]
    assert v.plans_a_reprendre(ancien, [dict(ancien[0], camera=v.CAMERA_DEFAUT)]) == [0]
    assert v.plans_a_reprendre(ancien, plans) == []


def test_la_duree_du_plan_suit_le_plan(h3):
    """01/10, « mets 10 s pour le plan 6 » : une durée par plan, dans la grille du modèle,
    gardée par la correction et la découpe ; changée, le plan se retourne ; absente, celle du scénario."""
    v = h3.video_h3
    plans = v.verifier_plans([{"image_paroles": "Leila waves.", "ambiance": "", "longueur": 243}])
    assert plans[0]["longueur"] == 243
    assert "longueur" not in v.verifier_plans([{"image_paroles": "Leila waves.", "ambiance": ""}])[0]
    for mauvais in (240, "dix"):
        with pytest.raises(ValueError, match="Plan 1"):
            v.verifier_plans([{"image_paroles": "x", "ambiance": "", "longueur": mauvais}])
    assert v.lire_correction('[{"image_paroles": "Leila waves goodbye.", "ambiance": ""}]', plans)[0]["longueur"] == 243
    ancien = [{"image_paroles": "Leila waves.", "ambiance": "", "enchainement": "coupe"}]
    assert v.plans_a_reprendre(ancien, plans) == []
    assert v.plans_a_reprendre(plans, plans) == [0]


def test_le_scenario_tourne_chaque_plan_a_sa_duree(sandbox):
    app = sandbox
    lea = app.video_h3.fiche_creer("Léa", "x")["id"]
    app.video_h3.fiche_poser_image(lea, "face", PNG)
    plans = app.video_h3.verifier_plans([{"image_paroles": "Léa marche.", "ambiance": ""},
                                         {"image_paroles": "Léa salue.", "ambiance": "", "longueur": 243}])
    _, _, a_tourner = app._scenario_prepare({"fiche": lea, "longueur": 124}, plans)
    assert [t["payload"]["longueur"] for t in a_tourner] == [124, 243]


def test_le_mode_references_charge_ref2va_et_sa_lora(h3):
    # 01/10 : le modèle Comfy-Org r2v charge ref2va ; sur fl2va, même graine, une seconde Leila.
    v = h3.video_h3
    leila = v.fiche_creer("Leila", "x")["id"]
    v.fiche_poser_image(leila, "face", PNG)
    refs = v.preparer(demande(mode="references", fiches=[leila], image_paroles="Leila marche."))["demande"]
    assert refs["graphe"]["1"]["inputs"]["unet_name"] == "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    assert refs["graphe"]["2"]["inputs"]["lora_name"] == "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    assert refs["fichiers"] == list(v.fichiers_du_mode("references"))
    assert set(v.FICHIERS_REFERENCES) <= set(refs["fichiers"]) and v.FICHIERS[0] not in refs["fichiers"]
    # Les autres modes gardent fl2va et sa LoRA.
    texte = v.preparer(demande(mode="texte"))["demande"]
    assert texte["graphe"]["1"]["inputs"]["unet_name"] == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    assert texte["fichiers"] == list(v.FICHIERS)
    # Le téléchargement des poids prend les deux jeux.
    script = v.construire_script_poids()
    d = json.loads(base64.b64decode(re.search(r'b64decode\("([A-Za-z0-9+/=]+)"\)', script).group(1)))
    assert d["fichiers"] == list(v.FICHIERS + v.FICHIERS_REFERENCES)


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
const j = {image_paroles: "Close-up on the pot: a crystal sprout grows into a glass shrub.",
  elements: [{nom: "the pot", debut: "centre"}, {nom: "crystal sprout", debut: "off-frame"}]};
console.log(JSON.stringify([texteDepart(p), texteDepart({image_paroles: p.image_paroles}), texteDepart(j)]));
"""
    f = tmp_path / "t.js"
    f.write_text(programme, encoding="utf-8")
    avec, sans, jardin = json.loads(subprocess.run(["node", str(f)], capture_output=True, text=True, check=True,
                                                   encoding="utf-8").stdout)
    assert jardin.endswith("Close-up on the pot. the pot : centre.")   # 03/10 : l'action après « : » reste dehors
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
    # 02/10 : le chat avait mis « fixe » (le mot de la caméra) dans l'enchaînement ; la découpe était refusée.
    camera_mal_placee = json.dumps([dict(m, enchainement="fixe") for m in json.loads(bonne)], ensure_ascii=False)
    morceaux = v.lire_scission(camera_mal_placee, plans[1])
    assert [m["enchainement"] for m in morceaux] == ["coupe", "suite"]
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


def test_le_tournage_est_refuse_quand_une_regle_n_est_pas_suivie(h3, monkeypatch, sans_depart_auto):
    """L'audit du 30/09 : une remarque bloquante vue, puis tournée quand même (parc, plan 2)."""
    fid = _scenario_pret(h3, avec_voix=True)
    fils = _tourner_sans_louer(h3, monkeypatch)
    probleme = {"ok": False, "problemes": [{"plan": 1, "quoi": "deux actions à la fois", "gravite": "bloquant"}]}

    async def continuite(plans, histoire, deja_filmes=None, fins_vues=None, departs_vus=None):
        return probleme
    monkeypatch.setattr(h3, "_continuite", continuite)
    plans = [{"image_paroles": "Léa says « Bonjour. »", "ambiance": "", "enchainement": "coupe"}]
    c = client(h3)
    r = c.post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 409 and not fils
    d = r.json()["detail"]
    assert "plan 1, règle 2 : deux actions à la fois" in d["message"] and d["passe_droit"] is True
    assert [x["n"] for x in d["regles"][0]["regles"]] == list(range(9)) + [13, 14, 16, 18]
    # « Tourner quand même » : parti, et le scénario garde le rapport et le passe-droit.
    r = c.post("/video-h3/scenario/tourner", headers=CLE,
               json={"plans": plans, "fiche": fid, "longueur": 124, "forcer": True})
    assert r.status_code == 200, r.text
    assert r.json()["force"] is True and r.json()["regles"][0]["regles"][2]["ok"] is False and len(fils) == 1
    # La route de vérification dit la même chose, sans rien lancer.
    r = c.post("/video-h3/scenario/verifier", headers=CLE, json={"plans": plans, "fiche": fid})
    assert r.status_code == 200 and r.json()["non_suivies"] == [[1, 2, "deux actions à la fois"]]


def test_avant_de_refuser_le_studio_corrige_une_fois_le_texte(h3, monkeypatch, sans_depart_auto, sans_objets_clefs):
    """« Leila et un martien », 01/10 : sept règles de texte non suivies au moment de
    tourner, corrigées à la main en trois passages. Le correcteur du découpage les reçoit
    une fois ; gardé s'il fait mieux, la réplique intacte ; sinon le texte d'origine."""
    fid = _scenario_pret(h3, avec_voix=True)
    fils = _tourner_sans_louer(h3, monkeypatch)

    async def continuite(plans, histoire, deja_filmes=None, fins_vues=None, departs_vus=None):
        if "telescope" in plans[0]["image_paroles"]:
            return {"ok": True, "problemes": []}
        return {"ok": False, "problemes": [{"plan": 1, "quoi": "le télescope disparaît", "gravite": "bloquant"}]}
    monkeypatch.setattr(h3, "_continuite", continuite)
    plans = [{"image_paroles": "Léa says « Bonjour. »", "ambiance": "", "enchainement": "coupe",
              "camera": {"mouvement": "arc", "amplitude": "petite", "vitesse": "lente"}}]
    corrige = '[{"image_paroles": "The telescope stands left. Léa says « Bonjour. »", "ambiance": ""}]'
    vus = []
    _faux_chat(monkeypatch, h3, {"la correction avant le tournage": [corrige]}, vus)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["correction"] == {"trouvees": 1, "corrige": True, "restent": 0} and len(fils) == 1
    assert d["plans"][0]["image_paroles"].startswith("The telescope") and d["plans"][0]["camera"]["mouvement"] == "arc"
    assert "BEFORE shooting" in vus[0][1] and "rule 2: le télescope disparaît" in vus[0][1]
    # Une correction qui ne fait pas mieux : le texte d'origine, et le refus le dit.
    _faux_chat(monkeypatch, h3, {"la correction avant le tournage": ['[{"image_paroles": "Léa says « Bonjour. »", '
                                                                     '"ambiance": "wind"}]']}, vus)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid, "longueur": 124})
    assert r.status_code == 409 and len(fils) == 1
    d = r.json()["detail"]
    assert d["correction"]["corrige"] is False and "pas fait mieux" in d["correction"]["erreur"]
    assert d["plans"][0]["image_paroles"] == "Léa says « Bonjour. »" and d["passe_droit"] is True
    # « Tourner quand même » ne demande aucune correction.
    n = len(vus)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE,
                        json={"plans": plans, "fiche": fid, "longueur": 124, "forcer": True})
    assert r.status_code == 200 and len(vus) == n and "correction" not in r.json() or r.json()["correction"] is None
    page = h3.video_h3.PAGE_HTML
    assert "Le Studio a corrigé" in page and "d.detail.plans" in page


def test_la_voix_du_locuteur_n_a_pas_de_passe_droit(h3, monkeypatch, sans_depart_auto):
    """Décision du 30/09 : la voix de chaque locuteur, « to be hard coded in studio »."""
    fid = _scenario_pret(h3, avec_voix=False)
    fils = _tourner_sans_louer(h3, monkeypatch)

    async def continuite(plans, histoire, deja_filmes=None, fins_vues=None, departs_vus=None):
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
    assert r[16]["ok"] is None   # le tableau ne dit aucune main : sans objet, et gardé quand même


def test_regle_16_la_main_qui_tient_l_objet(h3, monkeypatch):
    """02/10, film 4, plan 5 : la photo dans la main gauche de Leila, le tableau la donnait à la
    droite. Les mains sont décrites SANS le texte (sur le personnage recadré), puis comparées au
    tableau sans l'image ; la faute arrête le tournage avec ce qui a été vu."""
    v = h3.video_h3
    fid = v.fiche_creer("Leila", "adolescente de 15 ans, sweat jaune")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    did = v.depart_poser(PNG)
    ou = "foreground, centre, holding the photo in her right hand"
    plan = {"image_paroles": "Leila shows the photo.", "ambiance": "", "enchainement": "coupe", "image_depart": did,
            "elements": [{"nom": "Leila", "debut": ou, "mouvement": "none", "fin": "x"}]}
    vus, recadres = [], []
    _faux_chat(monkeypatch, h3, {
        "le contrôle de l'image de départ": '{"comptes": [1], "texte_ajoute": false, "remarque": ""}',
        "la recherche des mains": '{"x0": 300, "y0": 100, "x1": 700, "y1": 900}',
        "la lecture des mains": '{"main_droite": "nothing", "main_gauche": "a printed photo"}',
        "la comparaison des mains": '{"contradiction": true, "pourquoi": "la photo est dans la main gauche"}'}, vus)

    async def comparer(image, f, ou=""):
        return {"ressemblance": "forte"}
    monkeypatch.setattr(h3, "_comparer_visage", comparer)
    monkeypatch.setattr(h3.montage, "recadrer_zone", lambda image, zone, cote: recadres.append((zone, cote)) or base64.b64decode(PNG))
    assert v.attend_des_mains(ou) and not v.attend_des_mains("foreground, centre, holding the photo")
    # Le cadrage en tête allonge le départ : il ne coupe plus « right » avant « hand ».
    long = "wide shot, seen from further back and slightly low, " * 5 + "holding the photo with her right hand"
    assert v.attend_des_mains(v.lire_tableau([{"nom": "Leila", "debut": long}])[0]["debut"])
    r = asyncio.run(h3._regles_depart(plan, h3._fiches_du_scenario({"fiche": fid})))
    assert r[16]["ok"] is False and "Leila : la photo est dans la main gauche" in r[16]["pourquoi"]
    assert "main gauche a printed photo" in r[16]["pourquoi"] and r[7]["ok"] is True
    assert recadres == [((0.24, 0.036, 0.76, 0.964), 768)]
    quoi = {q: c for q, c, _, n in vus}
    # La lecture ne voit pas le texte attendu ; la comparaison ne voit pas l'image ; aucun âge ne part.
    assert "photo" not in quoi["la lecture des mains"]
    assert [n for q, _, _, n in vus if q == "la comparaison des mains"] == [0]
    assert "15" not in quoi["la recherche des mains"] and ou in quoi["la comparaison des mains"]
    # Un tableau tenu : rien à redire, et le verdict est gardé.
    _faux_chat(monkeypatch, h3, {
        "le contrôle de l'image de départ": '{"comptes": [1], "texte_ajoute": false, "remarque": ""}',
        "la recherche des mains": '{"x0": 300, "y0": 100, "x1": 700, "y1": 900}',
        "la lecture des mains": '{"main_droite": "a photo", "main_gauche": "hidden"}',
        "la comparaison des mains": '{"contradiction": false, "pourquoi": ""}'}, vus)
    plan["elements"][0]["debut"] = ou + ", smiling"
    assert asyncio.run(h3._regles_depart(plan, h3._fiches_du_scenario({"fiche": fid})))[16] == \
        {"ok": True, "pourquoi": ""}
    # Une réponse illisible : non jugé, jamais une faute.
    _faux_chat(monkeypatch, h3, {
        "le contrôle de l'image de départ": '{"comptes": [1], "texte_ajoute": false, "remarque": ""}',
        "la recherche des mains": "je ne vois personne"}, vus)
    plan["elements"][0]["debut"] = ou + ", sad"
    x = asyncio.run(h3._regles_depart(plan, h3._fiches_du_scenario({"fiche": fid})))[16]
    assert x["ok"] is None and "introuvable" in x["pourquoi"]


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
    # La source suit l'ordre ; la sortie est recoupée à [de, a) avant le bout à bout, et le son
    # vient du film (30/09 : un passage rendu sans son a fait échouer le bout à bout).
    assert 'P["ordre"]' in s and "trim=end_frame=" in s and "apad=whole_dur=" in s
    assert '["-i", str(film)]' in s and "asplit=" in s and "[%d:a]atrim" not in s


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


def test_un_scenario_a_huit_plans_mais_pas_cinq_raccords_d_affilee(h3):
    """30/09 : 5 plans, puis 6 le soir (décisions du propriétaire ; une réplique par plan,
    et le film campus en a six), 8 le 02/10 (film 4, plan 6 en deux) ; la limite mesurée des raccords reste."""
    v = h3.video_h3
    assert v.SCENARIO_PLANS_MAX == 8 and v.PLANS_MAX == 4
    plan = lambda e: {"image_paroles": "x", "ambiance": "", "enchainement": e}
    assert len(v.verifier_plans([plan("coupe")] + [plan("suite")] * 3 + [plan("coupe"), plan("suite")])) == 6
    with pytest.raises(ValueError, match="4 plans au plus d'affilée sans « coupe »"):
        v.verifier_plans([plan("coupe")] + [plan("suite")] * 4)
    assert "never more than 4 shots in a row" in v.consigne_decoupage("Un film.")
    assert client(h3).get("/video-h3/etat", headers=CLE).json()["scenario"] == {"plans_max": 8}
    # Film 4 : plan 5 coupe, 6a et 6b en suite ; huit plans passent, neuf non.
    huit = [plan("coupe"), plan("suite"), plan("suite"), plan("coupe"), plan("coupe"), plan("suite"),
            plan("suite"), plan("coupe")]
    assert len(v.verifier_plans(huit)) == 8
    with pytest.raises(ValueError, match="8 plans au plus"):
        v.verifier_plans(huit + [plan("coupe")])


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


def test_l_invite_legere_dit_chaque_chose_une_fois(h3):
    """02/10, plan 6 : 4 015 caractères, dont la scène 685 ; les voix dites trois fois, le raccord
    quatre. Propriétaire : « trop d'infos tue l'info ». Même plan, chaque consigne une fois."""
    v = h3.video_h3
    args = dict(tenues=(), ecrites={0: "a purple jacket over a yellow hoodie", 1: "a varsity jacket"},
                objets={2: "objet", 3: "objet"}, voix={0: 1, 1: 2}, presents={0, 1, 2, 3},
                parleurs={0: 1, 1: 2}, suite=True, planches={0}, vues={2, 3})
    plein = v.sujets_des_fiches([2, 4, 1, 1], **args)
    leger = v.sujets_des_fiches([2, 4, 1, 1], legere=True, **args)
    assert len(leger) < len(plein) * 0.55
    # Les étiquettes, les voix et les tenues restent ; chacune une fois.
    assert leger.count("<Audio 1>") == 1 and leger.count("<Audio 2>") == 1
    assert leger.count("a purple jacket over a yellow hoodie") == 1 and "same face and hair" in leger
    assert "<Subject 1> (appears in [Shot 1]): fully_preserved - one single person" in leger
    assert "<Subject 3> (appears in [Shot 1]): fully_preserved - same shape and colour; exactly one." in leger
    assert v.SUITE_GARDE_LEGERE in leger and v.SUITE_GARDE not in leger
    assert "summary: [video continuation + reference generation + audio reference] One single shot." in leger
    assert "Each <Audio> gives only a voice timbre; its words are never said." in leger
    assert "clothing" not in leger.split("retention_analysis:")[1].replace("same clothing", "")
    assert v.sujets_des_fiches([1, 1], legere=False) == v.sujets_des_fiches([1, 1])


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
    monkeypatch.setattr(h3.montage, "coller_sans_reencoder", lambda videos, **k: b"".join(videos))
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
    # La page le retrouve (« 4k dans studio ») ; les morceaux de l'agrandissement, non.
    hd = client(h3).get("/video-h3/clips", headers=CLE).json()["films_hd"]
    film = next(x for x in hd if x["id"] == f["film"])
    assert film["echelle"] == "4k" and "cle=" in film["video_url"]
    assert not {p["agrandi"] for p in f["plans"]} & {x["id"] for x in hd}
    assert not job["video"]["moteur"].startswith("MiniMax H3")
    assert job["video"]["devis"]["pire_usd"] > job["video"]["devis"]["estime_usd"] > 0


def test_finaliser_la_4k_ici_en_morceaux_courts_sans_rien_louer(h3, monkeypatch, tmp_path):
    """01/10, « 4k compressé en local » : la 4K sur la carte d'ici, mesurée sur la 4090 ;
    FlashVSR depuis le 03/10. Morceaux de 32 images au plus (mémoire vive), une fois par
    plafond de la machine, ni Modal ni budget."""
    loues, plans = _finaliser_monte(h3, monkeypatch, tmp_path)
    plans = [dict(p, sujets=[]) for p in plans]
    _ici(h3, monkeypatch, fichiers={f: 1 for f in h3.agrandir.FICHIERS_MAISON})
    monkeypatch.setattr(h3, "modal_configured", lambda: False)
    monkeypatch.setattr(h3.budget_modal, "verifier", lambda *a, **k: pytest.fail("budget demandé"))
    ici = []

    def run(jid, code):
        ici.append((jid, _demande_de(code)))
        job = h3.read_job(jid)
        job["status"] = "succeeded"
        h3.write_job(jid, job)

    monkeypatch.setattr(h3, "run_agrandir_maison", run)
    monkeypatch.setattr(h3.montage, "coller_sans_reencoder", lambda videos, **k: b"".join(videos))
    monkeypatch.setattr(h3, "_extrait", lambda jid, p: b"x")
    monkeypatch.setattr(h3, "_film_h3", lambda *a, **k: "f" * 32)
    monkeypatch.setattr(h3.montage, "taille", lambda video: (1344, 768))
    p = client(h3).post("/video-h3/finaliser/prix", headers=CLE,
                        json={"job": "b" * 32, "plans": plans, "echelle": "4k", "ou": "maison"}).json()
    assert p["ici"]["possible"] and p["devis"]["ici"] and p["devis"]["locations"] == 1 and p["devis"]["pire_usd"] == 0
    r = client(h3).post("/video-h3/finaliser", headers=CLE,
                        json={"job": "b" * 32, "plans": plans, "echelle": "4k", "ou": "maison"})
    assert r.status_code == 200, r.text
    job = h3.read_job(r.json()["id"])
    assert job["status"] == "succeeded", job.get("error")
    assert loues == [] and job["video"]["devis"]["pire_usd"] == 0 and job["video"]["ou"] == "maison"
    # SeedVR2 (6,4 s l'image) faisait trois fois ; FlashVSR (~1,5 s) fait les trois plans en une.
    # Coupes aux fins de plans (124, 247), sans amorce là, 8 images d'amorce ailleurs ; le
    # script est celui de FlashVSR.
    assert [d["coupes"] for _, d in ici] == [[0, 31, 62, 93, 124, 155, 186, 216, 247, 278, 309, 339, 370]]
    for jid, d in ici:
        c = d["coupes"]
        assert max(b - a for a, b in zip(c, c[1:])) <= h3.agrandir.MORCEAU_MAX_MAISON
        assert d["delai_s"] == h3.video_h3.MAISON_DUREE_MAX_S
        assert d["amorces"] == [0 if x in (0, 124, 247) else 8 for x in c[:-1]]
        assert d["fichiers"] == list(h3.agrandir.FICHIERS_MAISON) and "graphes" not in d
        assert d["entree"] == [960, 550] and d["canevas"] == [3840, 2176] and d["finale"] == [3780, 2160]
        etape = h3.read_job(jid)
        assert etape["provider"] == "maison" and etape["machine"] == "comfy"
        assert etape["video"]["modele"] == h3.agrandir.MOTEUR_MAISON


def test_ici_un_plan_trop_long_est_partage_au_lieu_d_etre_refuse(h3):
    """01/10 : le plan 6 (243 images) faisait refuser la 4K ici ; coupé à la main. Depuis
    FlashVSR (03/10) il passe d'une fois ; un plan de 1 200 images (50 s) ne passe pas."""
    assert h3.agrandir.tient_maison(243) and not h3.agrandir.tient_maison(1200)
    plans = [{"de": 0, "a": 124, "sujets": []}, {"de": 124, "a": 1324, "sujets": []}]
    coupes = h3._couper_pour_ici(plans)
    assert coupes[0] == plans[0] and coupes[1]["de"] == 124 and coupes[-1]["a"] == 1324 and len(coupes) == 3
    assert all(x["a"] == y["de"] for x, y in zip(coupes, coupes[1:]))
    assert all(h3.agrandir.tient_maison(p["a"] - p["de"]) for p in coupes)
    # Un plan avec visages n'est pas touché (ici, il est refusé plus loin, avec sa phrase).
    avec = [{"de": 0, "a": 243, "sujets": [{"fiche": "x", "choix": "largest_face"}]}]
    assert h3._couper_pour_ici(avec) == avec


def test_finaliser_ici_refuse_les_visages_le_x2_et_les_poids_absents(h3, monkeypatch, tmp_path):
    loues, plans = _finaliser_monte(h3, monkeypatch, tmp_path)
    _ici(h3, monkeypatch, fichiers={f: 1 for f in h3.agrandir.FICHIERS_MAISON})
    c = client(h3)
    r = c.post("/video-h3/finaliser", headers=CLE, json={"job": "b" * 32, "plans": plans, "echelle": "4k", "ou": "maison"})
    assert r.status_code == 422 and "chez Modal" in r.json()["detail"]
    sans = [dict(p, sujets=[]) for p in plans]
    r = c.post("/video-h3/finaliser", headers=CLE, json={"job": "b" * 32, "plans": sans, "echelle": "x2", "ou": "maison"})
    assert r.status_code == 422
    _ici(h3, monkeypatch)   # les poids de H3, pas ceux de FlashVSR
    r = c.post("/video-h3/finaliser", headers=CLE, json={"job": "b" * 32, "plans": sans, "echelle": "4k", "ou": "maison"})
    assert r.status_code == 409 and "FlashVSR" in r.json()["detail"]
    assert loues == []


def test_agrandir_complete_chaque_morceau_au_multiple_de_4_puis_le_retire(sandbox):
    """01/10 : 31 images rendues 30 par SeedVR2, et le film passé à 24,8 images/s."""
    s = sandbox.agrandir.construire_script(b"v", "4k", [0, 31, 62])
    assert "tpad=stop_mode=clone:stop=%d" in s and '-(c[k + 1] - c[k]) % D["multiple"]' in s
    assert '"-frames:v", str(c[k + 1] - c[k])' in s
    assert sandbox.agrandir.bornes(124, None, 32) == [0, 31, 62, 93, 124]
    assert sandbox.agrandir.tient_maison(124) and not sandbox.agrandir.tient_maison(1200)


def test_agrandir_ici_flashvsr_amorce_dans_un_plan_jamais_a_travers_une_coupe(sandbox):
    """03/10 : FlashVSR lit le film en flux. Un morceau qui continue un plan reçoit les
    8 images d'avant (jetées ensuite) ; un morceau qui ouvre un plan n'en reçoit pas."""
    ag = sandbox.agrandir
    coupes = ag.bornes(370, [243, 370], 128)   # morceaux de 128 : la règle, pas le réglage (32 depuis le 03/10)
    assert coupes == [0, 122, 243, 370]
    d = ag.demande_maison(b"v", coupes, [243, 370], 1344, 768, 1800)
    assert d["amorces"] == [0, ag.AMORCE_MAISON, 0]
    # Les dimensions de l'essai du 03/10 : 3840x2176 rendu, 3780x2160 rendu au film.
    assert ag.dimensions_maison(1344, 768) == {"entree": [960, 550], "canevas": [3840, 2176],
                                               "finale": [3780, 2160]}
    x = ag.dimensions_maison(832, 480)
    assert x["finale"] == [3744, 2160] and x["canevas"][0] % 128 == 0
    # Le canevas ramené à 2160 de haut couvre la largeur du film ; l'entrée x4 couvre le canevas.
    assert x["canevas"][0] * 2160 / 2176 >= 3744 and 4 * x["entree"][0] >= x["canevas"][0]
    s = ag.construire_script_maison(b"v", coupes, [243, 370], 1344, 768, 1800)
    assert "expandable_segments" in s and "render_tiled" in s and "__DEMANDE_B64__" not in s


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
    # 01/10 : « la remise en état des visages est inutile en mode automatique » : rien coché d'office.
    bloc = page.split("function dessinerFinaliser")[1].split("function ")[0]
    assert "c.checked = false;" in bloc and "c.checked = j <" not in bloc


def _video_grise(chemin, images, n=48, l=112, h=64):
    """Une vidéo dont chaque image est `images(i)` (octets gris l x h)."""
    brut = b"".join(images(i) for i in range(n))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "%dx%d" % (l, h),
                    "-r", "24", "-i", "-", "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(chemin)],
                   input=brut, check=True)
    return chemin.read_bytes()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_un_visage_refait_qui_saute_est_signale(h3, tmp_path):
    """Film campus, 30/09 : des visages refaits changeaient d'un coup en fin de passage.
    Un carré qui glisse d'un pixel par image (le visage refait) passe ; le même qui
    bondit de 30 pixels à l'image 40 est signalé, là et seulement là."""
    fond = bytes((x * 2) % 256 for x in range(112)) * 64

    def avec_carre(position):
        def image(i):
            ligne = bytearray(fond)
            x0 = position(i)
            for y in range(20, 40):
                ligne[y * 112 + x0:y * 112 + x0 + 20] = b"\xff" * 20
            return bytes(ligne)
        return image

    m = h3.montage
    origine = _video_grise(tmp_path / "o.mp4", lambda i: fond)
    doux = _video_grise(tmp_path / "d.mp4", avec_carre(lambda i: 10 + i))
    saute = _video_grise(tmp_path / "s.mp4", avec_carre(lambda i: 10 + i + (30 if i >= 40 else 0)))
    assert m.sauts_de_visages(origine, doux, [(0, 24), (24, 48)]) == []
    trouves = m.sauts_de_visages(origine, saute, [(0, 24), (24, 48)])
    assert [(t["de"], t["a"], t["image"]) for t in trouves] == [(24, 48, 40)]
    assert trouves[0]["fois"] > m.SAUT_VISAGE_FOIS


def test_un_film_trop_lourd_pour_la_reserve_finit_en_echec(h3, monkeypatch):
    """Film campus 4K sous-titré, 30/09 : 147 Mo, mis de côté sans fichier, et « réussi ».
    02/10, propriétaire : « on peut dépasser » la réserve des envois ; un film fait ici a la
    sienne (MAX_FILM), et seul ce plafond-là le refuse."""
    monkeypatch.setattr(h3, "MAX_UPLOAD", 3)
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 24)
    garde = h3._film_h3(b"FILM-AU-DELA-DES-ENVOIS", {"mode": "musique", "mode_titre": "Film et musique"}, "Gros film")
    assert h3.read_job(garde)["status"] == "succeeded"
    monkeypatch.setattr(h3, "MAX_FILM", 3)
    with pytest.raises(h3.montage.MontageImpossible, match="réserve"):
        h3._film_h3(b"FILM-TROP-LOURD", {"mode": "musique", "mode_titre": "Film et musique"}, "Film trop lourd 30-09")
    fiches = [json.loads(p.read_text(encoding="utf-8")) for p in h3.JOBS.glob("*/job.json")]
    rates = [j for j in fiches if j.get("titre") == "Film trop lourd 30-09"]
    assert rates and all(j["status"] == "failed" and "réserve" in j["error"] for j in rates)


def test_une_video_de_la_machine_d_ici_a_la_reserve_des_films(h3, monkeypatch):
    """03/10, film « Le phare » : la 4K de 15,5 s (106 Mo) dépassait les 100 Mo des envois."""
    monkeypatch.setattr(h3, "MAX_UPLOAD", 3)
    jid = "d" * 32
    sortie = h3.JOBS / jid / "output"
    sortie.mkdir(parents=True)
    (sortie / "video.mp4").write_bytes(b"VIDEO-4K-LOURDE")
    (sortie / "journal.txt").write_bytes(b"TROP-LONG")
    arts = {a["name"]: a for a in h3.collect_local_artifacts(jid, "maison")}
    assert not arts["video.mp4"].get("skipped") and arts["journal.txt"]["reason"] == "artifact_too_large"
    monkeypatch.setattr(h3, "MAX_FILM", 3)
    assert h3.collect_local_artifacts(jid, "maison")[0]["skipped"]


def _encodeur(nom):
    if not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return nom in (r.stdout or "")


@pytest.mark.skipif(not (_encodeur("libx264") and shutil.which("ffprobe")), reason="ffmpeg avec libx264 absent")
def test_le_recollage_repose_la_cadence_et_reprend_le_son_de_l_original(h3, tmp_path):
    """02/10, 4K de « Leila et un martien » : morceaux à 24,77 et 24,83 images/s, en deux
    échelles de temps ; collés tels quels, 843 images duraient 43,6 s pour 34 s de son."""
    m = h3.montage

    def clip(nom, cadence, n, son=False):
        c = tmp_path / nom
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=%s" % cadence]
        if son:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440"]
        cmd += ["-frames:v", str(n), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-video_track_timescale",
                str(int(float(cadence) * 500))]
        cmd += (["-c:a", "aac", "-t", "%.3f" % (n / 24)] if son else [])
        subprocess.run(cmd + [str(c)], check=True)
        return c.read_bytes()
    morceaux = [clip("a.mp4", "24.774", 30), clip("b.mp4", "24.8333", 28)]
    original = clip("o.mp4", "24", 58, son=True)
    film = tmp_path / "film.mp4"
    film.write_bytes(m.coller_sans_reencoder(morceaux, ips=24, son=original))
    assert m.images(film) == 58
    duree = float(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                  "stream=duration", "-of", "csv=p=0", str(film)],
                                 capture_output=True, text=True).stdout)
    assert abs(duree - 58 / 24) < 0.1, duree
    pistes = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                             str(film)], capture_output=True, text=True).stdout.split()
    assert pistes.count("audio") == 1


@pytest.mark.skipif(not (_encodeur("libsvtav1") and shutil.which("ffprobe")), reason="SVT-AV1 absent (il est dans le conteneur)")
def test_un_film_hd_passe_en_av1_si_la_qualite_mesuree_tient(h3, tmp_path):
    """30/09 : « un compresseur qui garde la qualité », en 4K, sans copie H.264."""
    m = h3.montage
    film = tmp_path / "film.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-crf", "10",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(film)], check=True)
    octets, fiche = m.compacter_av1(film.read_bytes())
    sortie = tmp_path / "av1.mp4"
    sortie.write_bytes(octets)
    assert fiche["codec"] == "av1" and fiche["crf"] == m.AV1_CRFS[0], fiche
    assert m.codec_video(sortie) == "av1" and m.images(sortie) == m.images(film) and len(octets) < film.stat().st_size
    assert fiche["psnr_y"] >= m.AV1_PSNR_Y_MOYEN_MIN and fiche["psnr_pire"] >= m.AV1_PSNR_PIRE_MIN
    # Déjà en AV1 : rien n'est refait.
    assert m.compacter_av1(octets) == (octets, {"codec": "av1", "deja": True})
    # Une garde impossible à tenir : les deux réglages essayés, le film rendu tel quel.
    m_seuil = m.AV1_PSNR_Y_MOYEN_MIN
    try:
        m.AV1_PSNR_Y_MOYEN_MIN = 200
        rendu, fiche = m.compacter_av1(film.read_bytes())
    finally:
        m.AV1_PSNR_Y_MOYEN_MIN = m_seuil
    assert rendu == film.read_bytes() and fiche["codec"] == "h264"
    assert [e["crf"] for e in fiche["essais"]] == list(m.AV1_CRFS) and "qualité" in fiche["raison"]
    # 02/10 : 102 Mo pour 100 Mo de réserve, film jeté. Au-dessus du plafond, un cran de
    # plus jusqu'à tenir, PSNR noté ; sous le plafond, rien ne change.
    assert m.compacter_av1(film.read_bytes(), plafond=10**9)[1]["crf"] == m.AV1_CRFS[0]
    premier = m.compacter_av1(film.read_bytes())[0]
    rendu, fiche = m.compacter_av1(film.read_bytes(), plafond=len(premier) - 1)
    assert fiche["sous_plafond"] and fiche["crf"] in m.AV1_CRFS_PLAFOND and len(rendu) < len(premier), fiche
    rendu, fiche = m.compacter_av1(film.read_bytes(), plafond=1)
    assert rendu == premier and "plafond" in fiche
    assert [e["crf"] for e in fiche["essais"]][-len(m.AV1_CRFS_PLAFOND):] == list(m.AV1_CRFS_PLAFOND)


def test_seuls_les_films_hd_sont_compresses_et_un_echec_les_laisse_tels_quels(h3, monkeypatch):
    appels = []
    monkeypatch.setattr(h3.montage, "compacter_av1", lambda f, plafond=0: appels.append(f) or (b"AV1", {"codec": "av1", "mo": 1}))
    assert h3._compacter_hd(b"CLIP", "MiniMax H3 (montage)") == (b"CLIP", None) and appels == []
    assert h3._compacter_hd(b"HD", "SeedVR2 (agrandissement)") == (b"AV1", {"codec": "av1", "mo": 1})

    def casse(f, plafond=0):
        raise h3.montage.MontageImpossible("La mesure de qualité (PSNR) a échoué.")
    monkeypatch.setattr(h3.montage, "compacter_av1", casse)
    assert h3._compacter_hd(b"HD", "SeedVR2 (agrandissement)") == (
        b"HD", {"raison": "La mesure de qualité (PSNR) a échoué."})


def test_le_traducteur_des_sous_titres_sait_qui_parle_a_qui(h3, monkeypatch):
    """30/09 : « Hey, are you lost? », dit à Leila (15 ans), était devenu « tu es perdu ».
    Le contexte vient de la filiation du film : film 4K -> montage -> clip -> scénario et fiches."""
    v = h3.video_h3
    leila = v.fiche_creer("Leila", "adolescente de 15 ans, veste violette")["id"]
    tyler = v.fiche_creer("Tyler", "adolescent américain de 16 ans")["id"]
    sid, sid2 = "5" * 32, "6" * 32
    scenarios = {sid: {"plans": [{"image_paroles": "Tyler arrive et demande à Leila « Hey, are you lost? »"},
                                 {"image_paroles": "Leila répond « Yes! »"}]},
                 sid2: {"plans": [{"image_paroles": "Leila crie « I made the team! »"}]}}

    def lire(s):
        if s not in scenarios:
            raise ValueError("Scénario inconnu.")
        return scenarios[s]
    monkeypatch.setattr(v, "scenario_lire", lire)
    clip, montage_, film, avant = "1" * 32, "2" * 32, "3" * 32, "7" * 32
    fiches = [{"id": leila, "nom": "Leila"}, {"id": tyler, "nom": "Tyler"}]
    # Le second clip est une prolongation : son scénario n'est connu que par `precedent` (01/10).
    for jid, video in ((avant, {"fiches": fiches, "scenario": sid2}),
                       (clip, {"fiches": fiches, "scenario": sid}),
                       ("8" * 32, {"precedent": avant}),
                       (montage_, {"clips": [clip, "8" * 32, "9" * 32]}),
                       (film, {"source": montage_, "moteur": "SeedVR2 (agrandissement)"})):
        h3.write_job(jid, {"id": jid, "status": "succeeded", "created_at": time.time(), "artifacts": [], "video": video})
    contexte = h3._contexte_du_film(film)
    assert "- Leila : adolescente de 15 ans, veste violette" in contexte
    assert "- Tyler : adolescent américain de 16 ans" in contexte
    assert "Plan 1 : Tyler arrive et demande à Leila « Hey, are you lost? »" in contexte
    assert "Plan 3 : Leila crie « I made the team! »" in contexte   # numérotés à la suite
    assert h3._contexte_du_film("4" * 32) == ""   # rien de connu : la consigne reste sans contexte
    # Réponse numérotée ; un numéro manquant est refusé (le Studio redemande).
    assert h3.lire_liste_json('{"1": "Hé, tu es perdue ?", "2": "Oui !"}', 2) == ["Hé, tu es perdue ?", "Oui !"]
    with pytest.raises(ValueError):
        h3.lire_liste_json('{"1": "Hé, tu es perdue ?"}', 2)


def test_une_traduction_incomplete_est_redemandee(h3, monkeypatch, tmp_path):
    """01/10, avec le contexte : 4 répliques rendues sur 6, deux fois sur trois."""
    fichiers = _deux_clips(h3, monkeypatch, tmp_path)
    hd = "e" * 32
    _clip_reussi(h3, hd, moteur="SeedVR2 (agrandissement)")
    fichiers[hd] = tmp_path / "hd.mp4"
    fichiers[hd].write_bytes(b"FILM4K")
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "k")
    monkeypatch.setattr(h3.montage, "passages_de_voix", lambda v: [(1.0, 2.0, [(1.0, 2.0)]), (3.0, 4.0, [(3.0, 4.0)])])
    monkeypatch.setattr(h3.montage, "son_du_passage", lambda v, de, a: b"%.1f" % de)
    monkeypatch.setattr(h3, "_ecouter_replique", lambda son: {b"0.8": "Hey, are you lost?", b"2.8": "Yes!"}[son])
    reponses = ['{"1": "Hé, tu es perdue ?"}', '{"1": "Hé, tu es perdue ?", "2": "Oui !"}']
    consignes = []

    async def chat(consigne, quoi="", **_):
        consignes.append(consigne)
        return reponses[len(consignes) - 1]
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    monkeypatch.setattr(h3.montage, "incruster_sous_titres", lambda f, s: f + b"+ST")
    monkeypatch.setattr(h3, "_compacter_hd", lambda f, m: (f, None))
    monkeypatch.setattr(h3.montage, "images", lambda chemin: 120)
    jid = "f" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "created_at": time.time(), "artifacts": [],
                       "video": {"moteur": "SeedVR2 (agrandissement)"}})
    h3.run_sous_titres(jid, hd)
    job = h3.read_job(jid)
    assert job["status"] == "succeeded", job.get("error")
    assert len(consignes) == 2 and '{"1": "Hey, are you lost?", "2": "Yes!"}' in consignes[0]
    assert [x["texte"] for x in job["video"]["sous_titres"]] == ["Hé, tu es perdue ?", "Oui !"]


# --- « Ici, sans urgence » ou Modal (01/10) ----------------------------------------
# « Le client débutant n'aura peut-être pas une carte GPU et en tout cas aucun hook
# installé. Studio doit gérer les deux configs. »

CARTE_24 = {"vue": True, "nom": "RTX 4090", "totale_mo": 24564, "libre_mo": 24100, "marge_mo": 1024, "motif": ""}


def _ici(h3, monkeypatch, carte=CARTE_24, fichiers="tous"):
    """Une machine H3 d'ici qui répond, une carte, des poids."""
    monkeypatch.setattr(h3, "WORKER_COMFY_URL", "http://sandbox-worker-comfy:8000")
    monkeypatch.setattr(h3.gpu_local, "releve", lambda *a, **k: dict(carte))
    v = h3.video_h3
    tous = {f: 1 for f in list(v.FICHIERS) + list(v.FICHIERS_REFERENCES)}
    sante = {"ok": True, "fichiers": tous if fichiers == "tous" else fichiers}
    monkeypatch.setattr(h3, "_h3_ici_sante", lambda: sante)


def test_sans_carte_seul_modal_est_offert_avec_sa_raison(h3, monkeypatch):
    monkeypatch.setattr(h3, "WORKER_COMFY_URL", "")
    ici = h3.h3_ici()
    assert ici["possible"] is False and "chez Modal" in ici["motif"]
    r = client(h3).get("/video-h3/ou", headers=CLE).json()
    assert r["ici"]["possible"] is False and r["ici"]["file"] == 0


def test_une_carte_plus_petite_que_la_seule_mesuree_n_est_pas_offerte(h3, monkeypatch):
    _ici(h3, monkeypatch, carte=dict(CARTE_24, nom="RTX 4070", totale_mo=12282))
    ici = h3.h3_ici()
    assert ici["possible"] is False and "RTX 4070" in ici["motif"] and "Modal" in ici["motif"]


def test_les_poids_du_mode_sont_verifies_un_par_un(h3, monkeypatch):
    v = h3.video_h3
    _ici(h3, monkeypatch, fichiers={f: 1 for f in v.FICHIERS})
    assert h3.h3_ici()["possible"] is True
    ref = {"fichiers": list(v.fichiers_du_mode("references"))}
    ici = h3.h3_ici(ref)
    assert ici["possible"] is False and "manque" in ici["motif"]
    _ici(h3, monkeypatch, fichiers={})
    assert "pas sur cet ordinateur" in h3.h3_ici()["motif"]


def test_ici_impossible_rien_ne_part_et_modal_n_est_pas_exige(h3, monkeypatch):
    _autoriser(h3)
    monkeypatch.setattr(h3, "WORKER_COMFY_URL", "")
    lance = []
    monkeypatch.setattr(h3, "run_video_h3", lambda *a: lance.append(a))
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(ou="maison"))
    assert r.status_code == 409 and "Modal" in r.json()["detail"]
    assert lance == []
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(ou="ailleurs"))
    assert r.status_code == 400


def test_ici_part_sans_modal_ni_poids_modal_et_attend_la_carte(h3, monkeypatch):
    """Ni Modal branché, ni poids sur le disque Modal : le cas du client avec une carte."""
    _autoriser(h3)
    _ici(h3, monkeypatch)
    monkeypatch.setattr(h3.video_h3, "a_traduire", lambda p: False)
    lance = []
    monkeypatch.setattr(h3, "run_video_h3", lambda *a: lance.append(a))
    r = client(h3).post("/video-h3/creer", headers=CLE, json=demande(ou="maison"))
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    assert len(lance) == 1 and lance[0][0] == jid and lance[0][4] == "maison"
    j = client(h3).get("/video/jobs/" + jid, headers=CLE).json()
    assert j["status"] == "queued" and j["attente_carte"] is True and j["fournisseur"] == "maison"
    # Vu le 01/10 : la fiche d'un plan fait ici disait « A100 » et 0,955 $ au pire.
    v = h3.read_job(jid)["video"]
    assert v["carte"] == "ici" and v["cout_max_usd"] == 0 and v["prix_estime_usd"] == 0
    d = h3.video_h3
    code = lance[0][1]
    assert "__DEMANDE_B64__" not in code
    demande_envoyee = json.loads(base64.b64decode(re.search(r'b64decode\("([^"]+)"\)', code).group(1)))
    assert demande_envoyee["delai_s"] == d.MAISON_DUREE_MAX_S - 120


def test_la_file_attend_la_carte_puis_calcule_ici_sans_rien_encaisser(h3, monkeypatch):
    _ici(h3, monkeypatch)
    libre = iter([(False, "RTX 4090 : 15,4 Go déjà pris sur 24 Go.", {}), (True, "libre", {})])
    monkeypatch.setattr(h3.file_carte.gpu_local, "libre_pour_un_code_inconnu", lambda *a: next(libre))
    monkeypatch.setattr(h3.file_carte, "SONDE_S", 0.01)
    vus = []

    def maison(jid, code, secondes=None, url=None):
        vus.append((url, secondes, h3.read_job(jid).get("attente_carte")))
        return {"exit_code": 0, "timed_out": False, "stdout": "", "stderr": "", "artifacts": []}

    monkeypatch.setattr(h3, "maison_execute", maison)
    monkeypatch.setattr(h3, "modal_execute", lambda *a, **k: pytest.fail("Modal appelé"))
    monkeypatch.setattr(h3.budget_modal, "consommer", lambda *a, **k: pytest.fail("encaissé"))
    jid = "e" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": [], "provider": "maison",
                       "machine": "comfy", "attente_carte": True})
    motifs = []
    attendre = h3.file_carte.attendre_son_tour

    def espion(j, annule, noter, **k):
        return attendre(j, annule, lambda rang, m: (motifs.append(m), noter(rang, m)), sonde_s=0.01)

    monkeypatch.setattr(h3.file_carte, "attendre_son_tour", espion)
    h3.run_video_h3(jid, "print(1)", None, 0, "maison")
    job = h3.read_job(jid)
    assert job["status"] == "succeeded" and job["provider_effective"] == "maison"
    assert vus == [("http://sandbox-worker-comfy:8000", h3.video_h3.MAISON_DUREE_MAX_S, False)]
    assert motifs and "15,4 Go" in motifs[0]
    assert h3.file_carte.etat() == {"en_cours": None, "en_attente": []}


def test_un_arret_pendant_l_attente_ne_laisse_rien_partir(h3, monkeypatch):
    _ici(h3, monkeypatch)
    monkeypatch.setattr(h3.file_carte.gpu_local, "libre_pour_un_code_inconnu",
                        lambda *a: (False, "occupée", {}))
    monkeypatch.setattr(h3, "maison_execute", lambda *a, **k: pytest.fail("parti"))
    monkeypatch.setattr(h3, "arreter_maison", lambda *a, **k: pytest.fail("rien à tuer"))
    jid = "f" * 32
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": [], "provider": "maison",
                       "provider_effective": "maison", "machine": "comfy", "attente_carte": True})
    fil = threading.Thread(target=h3.run_video_h3_maison, args=(jid, "print(1)"))
    fil.start()
    for _ in range(100):
        if h3.file_carte.position(jid) == 1:
            break
        time.sleep(0.01)
    r = client(h3).post("/jobs/" + jid + "/arreter", headers=CLE).json()
    assert r["status"] == "cancelled" and "ne partira pas" in r["detail"]
    fil.join(5)
    assert not fil.is_alive()
    assert h3.read_job(jid)["status"] == "cancelled"
    assert h3.file_carte.etat() == {"en_cours": None, "en_attente": []}


def test_un_arret_signale_juste_avant_l_attente_n_est_pas_perdu(h3):
    """02/10, les deux tests « instables » : l'arrêt était lu hors du verrou, puis l'attente
    entrait dans wait() ; un reveiller() tombé entre les deux se perdait, et le fil dormait
    toute la sonde. Ici l'arrêt arrive exactement dans cette fenêtre."""
    f = h3.file_carte
    arret = []

    def annule():
        if not arret:          # première lecture : pas encore arrêté… puis l'arrêt et son signal
            arret.append(1)
            f.reveiller()
            return False
        return True

    debut = time.monotonic()
    assert f.attendre_son_tour("z", annule, lambda r, m: None, libre=lambda: (False, "occupée", {}),
                               sonde_s=5) is False
    assert time.monotonic() - debut < 1 and f.etat() == {"en_cours": None, "en_attente": []}


def test_l_arret_n_est_pas_recouvert_par_la_place_dans_la_file(h3, monkeypatch):
    """02/10 : `noter` lisait la fiche « queued », l'arrêt écrivait « cancelled », puis `noter`
    réécrivait sa copie : l'arrêt disparaissait et l'attente ne finissait jamais. L'arrêt
    arrive ici pendant `noter`, entre sa lecture et son écriture."""
    _ici(h3, monkeypatch)
    monkeypatch.setattr(h3.file_carte.gpu_local, "libre_pour_un_code_inconnu", lambda *a: (False, "occupée", {}))
    monkeypatch.setattr(h3.file_carte, "SONDE_S", 0.05)
    jid = "a1" * 16
    h3.write_job(jid, {"id": jid, "status": "queued", "artifacts": [], "provider": "maison",
                       "provider_effective": "maison", "machine": "comfy", "attente_carte": True})
    lire, arrets = h3.read_job, []

    def lecture(j):
        job = lire(j)
        if sys._getframe(1).f_code.co_name == "noter" and not arrets:
            fil = threading.Thread(target=lambda: arrets.append(
                client(h3).post("/jobs/" + jid + "/arreter", headers=CLE).json()))
            arrets.append(fil)
            fil.start()
            fil.join(0.5)      # sans verrou, l'arrêt s'écrit ici, avant la réécriture de noter
        return job
    monkeypatch.setattr(h3, "read_job", lecture)
    assert h3.attendre_la_carte(jid) is False
    arrets[0].join(5)
    assert arrets[1]["status"] == "cancelled" and lire(jid)["status"] == "cancelled"


def test_deux_fils_ecrivent_la_meme_fiche_sans_se_gener(h3):
    """02/10 : un seul « job.json.tmp » pour tous ; sous Windows, deux écritures en même temps
    levaient PermissionError (mémoire, bug n°11)."""
    jid = "b2" * 16
    pannes = []

    def ecrire(k):
        for i in range(60):
            try:
                h3.write_job(jid, {"id": jid, "status": "queued", "k": k, "i": i})
            except OSError as exc:
                pannes.append(exc)
    fils = [threading.Thread(target=ecrire, args=(k,)) for k in range(4)]
    for t in fils:
        t.start()
    for t in fils:
        t.join(30)
    assert not pannes and h3.read_job(jid)["i"] == 59
    assert not list((h3.JOBS / jid).glob("*.tmp"))


def test_la_file_garde_l_ordre_d_arrivee(h3, monkeypatch):
    f = h3.file_carte
    ordre, tenu = [], threading.Event()

    def travail(jid):
        if f.attendre_son_tour(jid, lambda: False, lambda r, m: None,
                               libre=lambda: (True, "", {}), sonde_s=0.01):
            ordre.append(jid)
            tenu.wait(0.05)
            f.rendre(jid)

    fils = []
    for jid in ("un", "deux", "trois"):
        fils.append(threading.Thread(target=travail, args=(jid,)))
        fils[-1].start()
        time.sleep(0.02)
    for t in fils:
        t.join(5)
    assert ordre == ["un", "deux", "trois"]


def test_la_page_offre_ici_ou_modal_et_l_envoie(h3):
    page = client(h3).get("/video-h3", headers=CLE).text
    assert 'id="ou_choix"' in page and "Ici, sans urgence" in page
    assert page.count("ou: OU") == 5


def test_une_personne_sans_mouvement_ecrit_reste_vivante(h3):
    """02/10, plan 1 : « mouvement : none » pour Leila, figée tout le plan (« il manque une
    indication d'action »). Un objet immobile, lui, ne reçoit rien."""
    v = h3.video_h3
    elements = [{"nom": "Leila", "debut": "in the foreground, left", "mouvement": "none", "fin": "same"},
                {"nom": "the small telescope", "debut": "left", "mouvement": "none", "fin": "left"},
                {"nom": "Zib", "debut": "off-frame", "mouvement": "none", "fin": "off-frame"},
                {"nom": "Tom", "debut": "right", "mouvement": "waves", "fin": "right"}]
    assert v.phrases_vivants(elements, ["Leila", "Zib", "Tom"]) == v.VIVANT.format(nom="Leila")
    assert v.phrases_vivants(elements, []) == ""
    assert "none\" for an object only" in v.TABLEAU


def test_une_suite_ne_redit_ni_le_cadrage_ni_les_places_de_depart(h3):
    """02/10, « Leila et un martien », plans 3 → 4 : le plan 3 finit sur un zoom avant, le
    plan 4 redisait « Medium shot » et d'où chacun part ; H3 a recadré et rejoué le salut.
    Remarque du propriétaire : une suite part du bout de vidéo d'avant."""
    v = h3.video_h3
    elements = [
        {"nom": "the small telescope", "debut": "in the foreground, left of the frame, mounted on a tripod",
         "mouvement": "none", "fin": "in the foreground, left of the frame, mounted on a tripod"},
        {"nom": "Zib", "debut": "in the middle ground, centre of the frame, facing left, holding his hand up",
         "mouvement": "lowers his hand", "fin": "in the foreground, centre of the frame"},
        {"nom": "Leila", "debut": "in the foreground, left of the frame, facing right, standing, looking at Zib",
         "mouvement": "smiles", "fin": "in the foreground, left of the frame"}]
    texte = ("Medium shot in a quiet garden at night. The small telescope stands in the foreground, left of the "
             "frame, mounted on a tripod. Zib, starting in the middle ground, centre of the frame, facing left, "
             "holding his hand up, lowers his hand. In the foreground, left of the frame, facing right, standing, "
             "looking at Zib, Leila smiles. Leila dit : « Bonjour. Ça va ? »")
    assert v.texte_de_suite(texte, elements) == (
        "Zib lowers his hand. Leila smiles. Leila dit : « Bonjour. Ça va ? »")
    # Sans tableau, seul le cadrage part ; un texte sans cadrage reste tel quel.
    assert v.texte_de_suite("Wide shot of the park. Tom runs.", None) == "Tom runs."
    assert v.texte_de_suite("Tom runs.", elements) == "Tom runs."
    # Le son de <Video 1> n'est qu'ambiance : un plan d'avant muet ne donne pas sa voix.
    assert "no voice heard in <Video 1> is a voice reference" in v.SUITE_GARDE


def test_les_objets_clefs_ont_leur_fiche_aux_vues_multiples(h3):
    """02/10 : la soucoupe vire à la voiture, « le biscuit … change entre plan ». Un objet
    qui revient a sa fiche ; d'abord ceux qui bougent, dans la place qui reste."""
    v = h3.video_h3
    t = lambda nom, bouge: {"nom": nom, "debut": "in the background", "mouvement": bouge,   # noqa: E731
                            "fin": "in the background"}
    plans = [{"image_paroles": "The saucer lands. Zib eats the only cookie.",
              "elements": [t("the telescope", "none"), t("the saucer", "lands"), t("Zib", "walks")]},
             {"image_paroles": "The telescope stands. The saucer rises. Zib holds the only cookie.",
              "elements": [t("the telescope", "none"), t("the saucer", "rises"), t("Zib", "waves")]},
             {"image_paroles": "A bird flies.", "elements": [t("the bird", "flies")]}]
    assert v.objets_clefs(plans, ["Zib"], 2) == ["the saucer", "the telescope"]
    assert v.objets_clefs(plans, ["Zib"], 0) == []
    reponse = ('Voici : [{"nom": "the only cookie", "plans": [1, 2], "bouge": [1, 2]}, '
               '{"nom": "the moon", "plans": [1, 2], "bouge": []}, {"nom": "the bird", "plans": [3], "bouge": [3]}]')
    lus = v.lire_objets(reponse, plans)
    assert [o["nom"] for o in lus] == ["the only cookie"]   # la lune n'est écrite nulle part, l'oiseau une fois
    assert v.objets_clefs(plans, ["Zib"], 2, lus) == ["the only cookie", "the saucer"]
    assert v.lire_objets("pas de JSON", plans) == []
    f = v.fiche_objet_clef("the saucer")
    assert f["genre"] == "objet" and f["vues"] and v.fiche_objet_clef("The Saucer")["id"] == f["id"]
    assert v.CONSIGNE_OBJET_VUES in v.fiche_demande_image(f, v.ANGLE_DEPART)["prompt"]
    sujets = v.sujets_des_fiches([2, 1], objets={1: "objet"}, vues={1})
    assert "<Subject 2> is the object in <Picture 3>; it shows this one same object from several angles." in sujets


def test_le_tournage_ajoute_les_objets_clefs_tant_qu_il_y_a_place(h3, monkeypatch):
    """Les fiches d'objets rejoignent celles du scénario sans faire passer les personnes
    au seul visage (neuf images au plus, l'image de départ comprise)."""
    v = h3.video_h3
    leila = v.fiche_creer("Leila", "une fille")["id"]
    for angle in ("face", "trois_quarts", "profil", "pied"):
        v.fiche_poser_image(leila, angle, "data:image/png;base64," + PNG)
    vus = []

    async def chat(consigne, quoi="", **k):
        vus.append(quoi)
        return ('[{"nom": "the cookie", "plans": [1, 2], "bouge": [1, 2]}, '
                '{"nom": "the saucer", "plans": [1, 2], "bouge": [2]}, '
                '{"nom": "the lamp", "plans": [1, 2], "bouge": []}, '
                '{"nom": "the car", "plans": [1, 2], "bouge": []}, '
                '{"nom": "the hat", "plans": [1, 2], "bouge": []}]')

    async def image(demande):
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    monkeypatch.setattr(h3, "_image_du_studio", image)
    plans = [{"image_paroles": "Leila holds the cookie near the saucer, the lamp, the car and the hat."},
             {"image_paroles": "Leila eats the cookie; the saucer rises; the lamp, the car and the hat stay."}]
    corps = {"fiches": [leila]}
    note = asyncio.run(h3._avec_objets_clefs(plans, corps))
    # 9 images : 4 photos de Leila + l'image de départ ; 4 places, prises par ordre.
    assert [o["nom"] for o in note["ajoutes"]] == ["the cookie", "the saucer", "the lamp", "the car"]
    assert corps["fiches"][0] == leila and len(corps["fiches"]) == 5
    assert v.photos_avec_depart(corps["fiches"]) == (8, False) and vus == ["la liste des objets clefs"]
    # Un second tournage reprend les mêmes fiches, sans refaire leurs images.
    monkeypatch.setattr(h3, "_image_du_studio", None)
    corps2 = {"fiches": [leila]}
    asyncio.run(h3._avec_objets_clefs(plans, corps2))
    assert corps2["fiches"] == corps["fiches"]
    # Sans place, rien n'est demandé.
    plein = {"fiches": corps["fiches"]}
    assert asyncio.run(h3._avec_objets_clefs(plans, plein)) == {"ajoutes": [], "sans_fiche": []}


def test_avant_le_tournage_l_image_d_une_coupe_refaite_ne_se_juge_pas(h3):
    """02/10 : rejeu refusé, « plan 5, règle 6 », sur l'image du découpage d'une coupe
    qui allait être refaite depuis la fin du plan 4. Le plan 1 et le texte se jugent."""
    plans = [{"enchainement": "coupe"}, {"enchainement": "suite"}, {"enchainement": "coupe"}]
    assert h3._departs_refaits(plans) == {3}
    faute = lambda n: {"n": n, "regle": "", "ok": False, "pourquoi": "x"}   # noqa: E731
    rapport = [{"plan": 1, "regles": [faute(6)]}, {"plan": 3, "regles": [faute(6), faute(7)]}]
    with pytest.raises(h3.HTTPException) as refus:
        asyncio.run(h3._garde_des_regles(plans, {}, False, rapport=rapport))
    assert "plan 1, règle 6" in refus.value.detail["message"] and "plan 3" not in refus.value.detail["message"]
    rapport = [{"plan": 3, "regles": [faute(6), faute(1)]}]
    with pytest.raises(h3.HTTPException) as refus:
        asyncio.run(h3._garde_des_regles(plans, {}, False, rapport=rapport))
    assert refus.value.detail["message"] == "Règles non suivies : plan 3, règle 1 : x"
    assert asyncio.run(h3._garde_des_regles(plans, {}, False, rapport=[{"plan": 3, "regles": [faute(8)]}]))


def test_le_decor_a_sa_fiche_et_ne_part_pas_a_h3(h3):
    """02/10, propriétaire : « le décor doit avoir son id image pour la consistance ». Une fiche
    « décor » : une vue d'ensemble du lieu seul, jointe aux images de départ, jamais à H3."""
    v = h3.video_h3
    lieu = v.fiche_creer("la place", "petite place pavée, fontaine de pierre, façades beiges", genre="decor")
    assert v.fiche_est_objet(lieu)
    demande = v.fiche_demande_image(lieu, "face")
    assert v.CADRE_DECOR in demande["prompt"] and demande["size"] == v.TAILLE_IMAGE_DEMANDEE
    with pytest.raises(ValueError):
        v.fiche_demande_image(lieu, "profil")
    with pytest.raises(ValueError, match="pas encore d'image"):
        v.demande_image("x", lieu=lieu["id"])
    v.fiche_poser_image(lieu["id"], "face", PNG)
    image = v.fiche_lieu_image(lieu["id"])
    demande, _ = v.demande_image("Wide shot. Leila sits.", lieu=lieu["id"], coupe=True)
    assert demande["image_reference"] == [image]
    assert v.CONSIGNE_LIEU % 1 in demande["prompt"] and v.CONSIGNE_COUPE_LIEU in demande["prompt"]
    assert v.CONSIGNE_COUPE % 1 not in demande["prompt"]   # pas la dernière image : le lieu vient de la fiche
    # 03/10, « le fauteuil se balade » : les meubles du décor sont nommés et ne bougent pas.
    assert "MEUBLES (canapé, fauteuil" in v.CONSIGNE_LIEU and "déplacé ni remplacé" in v.CONSIGNE_LIEU
    # Une image antérieure du film tient aussi les meubles, sans imposer ses objets.
    avant = v.depart_poser(PNG)
    avec, _ = v.demande_image("Wide shot. Leila sits.", lieu=lieu["id"], coupe=True, meubles=avant)
    assert len(avec["image_reference"]) == 2 and v.CONSIGNE_MEUBLES % 2 in avec["prompt"]
    assert v.CONSIGNE_ETAT_COUPE % 2 not in avec["prompt"]
    seule, _ = v.demande_image("x", lieu=lieu["id"])
    assert v.CONSIGNE_COUPE_LIEU not in seule["prompt"]
    personne = v.fiche_creer("Leila", "une adolescente")["id"]
    v.fiche_poser_image(personne, "face", PNG)
    with pytest.raises(ValueError, match="pas une fiche de décor"):
        v.fiche_lieu_image(personne)
    with pytest.raises(ValueError, match="est un décor"):
        v.preparer({"mode": "references", "image_paroles": "x", "fiches": [personne, lieu["id"]]})


def test_une_coupe_tournee_prend_le_lieu_de_la_fiche_decor_et_l_instant_de_la_derniere_image(
        h3, monkeypatch, tmp_path, sans_regles):
    """02/10, film 4, plan 2 : refaite depuis la dernière image du plan 1 (un gros plan), la coupe
    a inventé un autre lieu. Avec la fiche du décor, l'image d'une coupe part de la fiche et
    change de cadrage. 03/10, « Le jardin de verre » : sans la dernière image, le pot a changé de
    forme et de place ; propriétaire : « des fiches et du plan final, mais avec un autre angle de
    vue ». Au tournage, la dernière image est jointe aussi, comme l'état de l'instant."""
    v = h3.video_h3
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    monkeypatch.setattr(v, "a_traduire", lambda p: False)
    fid = v.fiche_creer("Zib", "un martien")["id"]
    v.fiche_poser_image(fid, "face", PNG)
    lieu = v.fiche_creer("le jardin", "un jardin la nuit", genre="decor")["id"]

    async def tenues(commun, plans, a_tourner):
        return []
    monkeypatch.setattr(h3, "_scenario_tenues", tenues)
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: image)
    demandes = []

    async def image(demande):
        demandes.append(demande)
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_image_du_studio", image)
    fils = []
    vrai = h3.run_scenario_h3
    monkeypatch.setattr(h3, "run_scenario_h3", lambda *a: fils.append(a))
    plans = [{"image_paroles": "Zib atterrit dans le jardin", "ambiance": "", "enchainement": "coupe"},
             {"image_paroles": "Wide shot. Zib mange un biscuit", "ambiance": "", "enchainement": "coupe"}]
    corps = {"plans": plans, "fiche": fid, "longueur": 124, "decor": lieu}
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json=corps)
    assert r.status_code == 400 and "pas encore d'image" in r.text   # un décor sans image : rien ne part
    v.fiche_poser_image(lieu, "face", PNG)
    r = client(h3).post("/video-h3/scenario/tourner", headers=CLE, json=corps)
    assert r.status_code == 200, r.text
    image_lieu = v.fiche_lieu_image(lieu)
    assert all(image_lieu in d["image_reference"] for d in demandes)   # avant le tournage aussi
    assert v.CONSIGNE_COUPE_LIEU not in demandes[0]["prompt"] and v.CONSIGNE_COUPE_LIEU in demandes[1]["prompt"]
    sid = r.json()["id"]
    assert v.scenario_lire(sid)["reglages"]["decor"] == lieu
    video = tmp_path / "plan.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: video)
    monkeypatch.setattr(h3.montage, "derniere_image", lambda octets: base64.b64decode(PNG) + b"FIN-DU-PLAN-1")
    monkeypatch.setattr(h3, "_controle_derniere_image", lambda s, i, img: None)

    def tourner(jid, code, precedent, retirer, ou="modal"):
        job = h3.read_job(jid)
        job["status"] = "succeeded"
        h3.write_job(jid, job)
    monkeypatch.setattr(h3, "run_video_h3", tourner)
    poses = []
    vrai_poser = v.depart_poser
    monkeypatch.setattr(v, "depart_poser", lambda img: poses.append(img) or vrai_poser(img))
    avant = len(demandes)
    vrai(*fils[0])
    sc = v.scenario_lire(sid)
    assert sc["etat"] == "réussi", sc["erreur"]
    au_tournage = demandes[avant:]
    assert au_tournage and image_lieu in au_tournage[-1]["image_reference"]
    assert v.CONSIGNE_COUPE_LIEU in au_tournage[-1]["prompt"] and v.CONSIGNE_COUPE % 1 not in au_tournage[-1]["prompt"]
    fin = base64.b64encode(base64.b64decode(PNG) + b"FIN-DU-PLAN-1").decode()
    assert any(fin in p for p in poses)   # la dernière image sert : l'instant
    assert v.CONSIGNE_ETAT_COUPE % len(au_tournage[-1]["image_reference"]) in au_tournage[-1]["prompt"]
    assert au_tournage[-1]["image_reference"][-1].endswith(fin)


def test_un_rejeu_de_rejeu_prend_le_dernier_travail_reussi(h3):
    # 02/10, film 4 : un rejeu arrêté après un plan neuf n'a qu'un travail pour deux plans (le
    # plan repris n'en ajoute pas) ; le rejouer plantait en 500 (travaux[1] inexistant).
    fait, rate = "a" * 32, "b" * 32
    h3.write_job(fait, {"id": fait, "status": "succeeded", "artifacts": []})
    h3.write_job(rate, {"id": rate, "status": "failed", "artifacts": []})
    sc = {"etat": "arrêté", "fins_images": [243, 362], "travaux": [fait, rate]}
    assert h3._film_du_scenario(sc) == fait
    assert h3._film_du_scenario({"etat": "arrêté", "fins_images": [243], "travaux": []}) is None


def test_au_rejeu_le_relecteur_voit_la_vraie_fin_du_plan_repris(h3, monkeypatch):
    # 02/10, film 4 : au rejeu du plan 2, « le plan 1 s'achevait en plan moyen » (son texte) ;
    # le plan 1 filmé finit en gros plan. Le relecteur reçoit la marque et la vraie image.
    v = h3.video_h3
    plans = [{"image_paroles": "Medium shot. Leila.", "enchainement": "coupe"},
             {"image_paroles": "The camera pulls back.", "enchainement": "suite"}]
    neuf = v.consigne_continuite(plans, "x")
    assert "deja_filme" not in neuf and "REAL last images" not in neuf
    rejeu = v.consigne_continuite(plans, "x", {1}, [1])
    assert '"deja_filme": true' in rejeu and "REAL last images of shots 1" in rejeu
    assert rejeu.count("deja_filme") == 2   # la consigne, puis le seul plan 1
    # Une remarque sur un plan déjà filmé est écartée : son texte ne se corrige plus.
    reponse = json.dumps({"problemes": [{"plan": 1, "quoi": "cadre", "gravite": "bloquant"},
                                        {"plan": 2, "quoi": "geste", "gravite": "bloquant"}]})
    assert [p["plan"] for p in v.lire_continuite(reponse, 2, deja_filmes={1})["problemes"]] == [2]
    assert len(v.lire_continuite(reponse, 2)["problemes"]) == 2
    # Seuls les plans repris suivis d'un plan retourné ont leur image, lue à leur dernière image.
    lues = []
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: Path(__file__))
    monkeypatch.setattr(h3.montage, "vignettes", lambda video, numeros, largeur: lues.extend(numeros) or
                        [b"jpg%d" % n for n in numeros])
    assert h3._fins_vues("f" * 32, [243, 481, 700], [0, 1]) == {2: b"jpg480"}
    assert lues == [480]
    assert h3._fins_vues(None, [243], [0]) == {}


def test_la_suite_a_tourner_part_de_la_vraie_fin_du_plan_filme(h3, monkeypatch):
    # 02/10, film 4, propriétaire : « faire relire la vidéo précédente pour améliorer si besoin
    # le prompt du clip suivant ». Tyler finit le plan 2 à cheval, deux mains au guidon.
    v = h3.video_h3
    ligne = "Leila says: « [French] Regarde ! »"
    p3 = "Tyler stands beside the bicycle, one hand on it. " + ligne
    a_cheval = "Tyler is astride the bicycle, both hands on the handlebar. " + ligne
    r = v.lire_depart_reel('{"texte": "%s", "changements": "Tyler est à cheval."}' % a_cheval.replace('"', '\\"'), p3)
    assert r == {"texte": a_cheval, "changements": "Tyler est à cheval."}
    # Le « Shot 3: » de la consigne recopié en tête (02/10, plan 5) : retiré.
    assert v.lire_depart_reel(json.dumps({"texte": "Shot 3: " + a_cheval}), p3)["texte"] == a_cheval
    with pytest.raises(ValueError, match="réplique"):
        v.lire_depart_reel(json.dumps({"texte": "Tyler is astride. Leila says: « [French] Regarde ça ! »"}), p3)
    with pytest.raises(ValueError):
        v.lire_depart_reel("rien", p3)
    assert "last second of shot 2" in v.consigne_depart_reel(2, p3) and "Shot 3: " + p3 in v.consigne_depart_reel(2, p3)
    # Seule la suite qui suit un plan repris est adaptée, sur les images de la dernière seconde.
    lues, reponses = [], [json.dumps({"texte": a_cheval, "changements": "à cheval"})]
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: Path(__file__))
    monkeypatch.setattr(h3.montage, "vignettes", lambda video, numeros, largeur: lues.append(numeros) or
                        [b"jpg"] * len(numeros))

    async def chat(consigne, quoi, images=None, modele=None):
        assert len(images) == 3 and "Shot 3: " in consigne
        return reponses.pop(0)
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    plans = [{"image_paroles": "a", "enchainement": "coupe"}, {"image_paroles": "b", "enchainement": "suite"},
             {"image_paroles": p3, "enchainement": "suite"}, {"image_paroles": "d", "enchainement": "suite"}]
    notes = asyncio.run(h3._adapter_departs(plans, "f" * 32, [243, 481], {0, 1}))
    assert lues == [[456, 468, 480]] and plans[2]["image_paroles"] == a_cheval
    assert notes == [{"plan": 3, "avant": p3, "apres": a_cheval, "changements": "à cheval"}]
    assert plans[3]["image_paroles"] == "d"   # le plan d'avant n'est pas filmé : rien à lire
    # Une réplique touchée : le texte écrit est gardé, et la note le dit.
    plans[2]["image_paroles"] = p3
    reponses.append(json.dumps({"texte": "Tyler is astride. Leila says: « [French] Regarde ça ! »"}))
    notes = asyncio.run(h3._adapter_departs(plans, "f" * 32, [243, 481], {0, 1}))
    assert plans[2]["image_paroles"] == p3 and "réplique" in notes[0]["erreur"]
    assert asyncio.run(h3._adapter_departs(plans, None, [243, 481], {0, 1})) == []
    # Rien à changer : la lecture est notée quand même.
    reponses.append(json.dumps({"texte": p3, "changements": ""}))
    notes = asyncio.run(h3._adapter_departs(plans, "f" * 32, [243, 481], {0, 1}))
    assert plans[2]["image_paroles"] == p3 and notes == [{"plan": 3, "changements":
                                                          "Le départ écrit correspond déjà à la fin filmée."}]
    assert "when unsure" in v.consigne_depart_reel(2, p3)
    # 02/10, plan 5 : une COUPE après un plan filmé est recalée aussi, son cadrage écrit gardé.
    coupe = v.consigne_depart_reel(4, "Wide shot. Tyler holds the camera to his eye.", coupe=True)
    assert "it is a CUT" in coupe and "Keep its framing exactly" in coupe
    assert "last second of shot 4" in coupe and "Shot 5: Wide shot." in coupe and "shot 5\"" in coupe
    assert "CUT" not in v.consigne_depart_reel(2, p3)
    plans[2] = {"image_paroles": p3, "enchainement": "coupe"}
    vues = []

    async def chat_coupe(consigne, quoi, images=None, modele=None):
        vues.append(consigne)
        return json.dumps({"texte": a_cheval, "changements": "à cheval"})
    monkeypatch.setattr(h3, "_chat_du_studio", chat_coupe)
    notes = asyncio.run(h3._adapter_departs(plans, "f" * 32, [243, 481], {0, 1}))
    assert "it is a CUT" in vues[0] and plans[2]["image_paroles"] == a_cheval and notes[0]["plan"] == 3


def test_la_fiche_du_decor_se_fait_d_apres_le_film(h3, monkeypatch):
    # 02/10, film 4 : la fiche faite d'après l'image de départ du plan 1 montrait une colonne,
    # le film une vasque à deux étages ; la coupe du plan 5 a recopié la fiche. Propriétaire :
    # « la planche décor détaillée aussi dans studio, on l'utilise pour le plan 5 ».
    v = h3.video_h3
    _autoriser(h3)
    assert v.images_pour_decor([243, 481, 600]) == [242, 480, 599]
    assert v.images_pour_decor([100, 200, 300, 400, 500, 600, 700]) == [99, 299, 499, 699]
    with pytest.raises(ValueError, match="rien n'est créé"):
        v.lire_decor_du_film('{"nom": "square", "description": "a fountain"}')
    assert "never invent" in v.consigne_decor_du_film(3) and "The 3 attached" in v.consigne_decor_du_film(3)
    description = ("A small cobbled square: in the middle a round stone fountain with a high basin wall at seat "
                   "height and a two-tier bowl on a central column, beige stone buildings behind.")
    lues, vues, demandes = [], [], []
    monkeypatch.setattr(v, "scenario_lire", lambda sid: {"etat": "arrêté", "plans": [{}, {}, {}]})
    monkeypatch.setattr(h3, "_fins_images", lambda sc: [243, 481, 600])
    monkeypatch.setattr(h3, "_film_du_scenario", lambda sc: "f" * 32)
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: Path(__file__))
    monkeypatch.setattr(h3.montage, "vignettes", lambda video, numeros, largeur: lues.append(numeros) or
                        [base64.b64decode(PNG)] * len(numeros))

    async def chat(consigne, quoi, images=None, modele=None):
        vues.append(len(images))
        return json.dumps({"nom": "the cobbled square", "description": description})

    async def image(demande):
        demandes.append(demande)
        if len(demandes) == 1:   # une panne passagère : redemandée
            raise h3.HTTPException(503, "Google a refuse la demande d'image (HTTP 503).")
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    monkeypatch.setattr(h3, "_image_du_studio", image)
    monkeypatch.setattr(h3, "COUPE_PAUSE_S", 0)
    r = client(h3).post("/video-h3/scenario/" + "a" * 32 + "/decor", headers=CLE, json={})
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["nom"] == "the cobbled square" and f["genre"] == "decor" and f["description"] == description
    # 03/10, « la multiview est fausse » puis « on construira un décor 3d plus tard » : la vue
    # d'ensemble seule, plus de planche à vues d'autres côtés.
    assert f["images"] and not f.get("planche") and lues == [[242, 480, 599]] and vues == [3]
    assert len(demandes) == 2 and [len(d["image_reference"]) for d in demandes] == [3, 3]
    assert "two-tier bowl" in demandes[1]["prompt"]
    # Les coupes reçoivent la vue d'ensemble seule, même d'une fiche ancienne qui a une planche ;
    # la caméra reste du côté du décor (règle des 180°).
    v.fiche_poser_planche(f["id"], PNG)
    demande, _ = v.demande_image("Wide shot of the square.", lieu=f["id"], coupe=True)
    assert len(demande["image_reference"]) == 1 and "règle des 180°" in demande["prompt"]
    assert "un autre angle du même côté" in v.CONSIGNE_COUPE_LIEU
    # Rien de tourné : refus.
    monkeypatch.setattr(h3, "_fins_images", lambda sc: [])
    assert client(h3).post("/video-h3/scenario/" + "a" * 32 + "/decor", headers=CLE, json={}).status_code == 409


def test_un_texte_change_fait_reecrire_son_tableau(h3, monkeypatch):
    # 02/10, film 4 : le plan 4 réécrit (Tyler à cheval, deux mains au guidon), son tableau disait
    # encore « debout, une main » ; la règle 7 cherchait Tyler à cette place-là.
    v = h3.video_h3
    debout = [{"nom": "Tyler", "debut": "standing left, one hand on the bicycle", "mouvement": "smiles",
               "fin": "standing left"}]
    a_cheval = [{"nom": "Tyler", "debut": "astride the bicycle, left, both hands on the handlebar",
                 "mouvement": "smiles", "fin": "astride the bicycle, left"}]
    assert v.lire_tableau_a_jour(json.dumps({"elements": a_cheval})) == a_cheval
    for illisible in ("rien", json.dumps({"elements": []})):
        with pytest.raises(ValueError, match="ancien est gardé"):
            v.lire_tableau_a_jour(illisible)
    consigne = v.consigne_tableau_a_jour("Tyler is astride.", debout)
    assert "Shot text: Tyler is astride." in consigne and "one hand on the bicycle" in consigne
    reponses, demandes = [json.dumps({"elements": a_cheval})], []

    async def chat(consigne, quoi, images=None, modele=None):
        demandes.append(consigne)
        return reponses.pop(0)
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    anciens = [{"image_paroles": "a", "elements": debout}, {"image_paroles": "Tyler stands.", "elements": debout},
               {"image_paroles": "c", "elements": debout}]
    plans = [dict(anciens[0], image_paroles="a changé"),            # repris : pas touché
             dict(anciens[1], image_paroles="Tyler is astride."),   # changé, à tourner : réécrit
             dict(anciens[2])]                                      # inchangé : pas touché
    notes = asyncio.run(h3._tableaux_a_jour(plans, anciens, {0}))
    assert len(demandes) == 1 and plans[1]["elements"] == a_cheval
    assert plans[0]["elements"] == debout and plans[2]["elements"] == debout
    assert notes == [{"plan": 2, "tableau": "Tableau des éléments réécrit d'après le texte changé."}]
    # Illisible : l'ancien tableau reste, et la note le dit.
    plans[1]["elements"] = debout
    reponses.append("rien")
    notes = asyncio.run(h3._tableaux_a_jour(plans, anciens, {0}))
    assert plans[1]["elements"] == debout and "ancien est gardé" in notes[0]["erreur"]


def test_une_parole_non_ecrite_est_une_faute_meme_si_la_replique_est_dite(h3):
    # 02/10, film 4, plan 2 (prise 4) : ce que l'écoute a entendu, passage par passage.
    v = h3.video_h3
    morceaux = [{"de_s": 0.0, "a_s": 4.3, "entendu": "and all my postplasticity mark, and all of the pravies"},
                {"de_s": 7.1, "a_s": 9.9, "entendu": "Hey Leila, is that a real instant camera?"}]
    attendues = ["Hey Leila! Is that a real instant camera?"]
    trop = v.passages_en_trop(attendues, morceaux)
    assert trop == morceaux[:1]
    assert v.passages_en_trop(attendues, morceaux[1:]) == []
    assert v.passages_en_trop(attendues, [{"de_s": 0, "a_s": 1, "entendu": "Oh."}]) == []   # trop court
    paroles = {"attendu": attendues, "ok": False, "entendu": "", "en_trop": trop}
    r = h3.regles.regle_paroles(paroles)
    assert r["ok"] is False and "postplasticity" in r["pourquoi"] and "0.0-4.3" in r["pourquoi"]
    assert "Paroles non écrites" in v.defaut_de_paroles(paroles, 10.0)["quoi"]


def test_une_coupe_franche_dans_un_plan_se_voit_pas_un_mouvement(h3):
    m = h3.montage
    # Plan 2, prise 3 : un pic seul (48,2) sur une médiane de 3,3.
    coupe = [3.3] * 19 + [48.2] + [3.3] * 20
    assert m.sauts_d_image(coupe) == [(19, 48.2)]
    # Pigeons qui s'envolent (prise 2) : 8 à 10 sur plusieurs paires de suite, pas une coupe.
    mouvement = [2.0] * 27 + [10.4, 9.0, 8.0, 9.5, 8.5, 9.0, 8.3, 8.4] + [2.0] * 20
    assert m.sauts_d_image(mouvement) == []
    assert h3.regles.regle_sans_coupe(coupe, 24)["ok"] is False
    assert h3.regles.regle_sans_coupe(mouvement, 24)["ok"] is True
    assert h3.regles.regle_sans_coupe(None, 24)["ok"] is None


def test_une_coupe_au_raccord_d_une_suite_se_voit(h3):
    # 02/10, film 4, plan 6 prise 2, mesuré : plan large du plan 5 → gros plan de la photo
    # (62,7), puis un recul rapide (17 à 30), médiane du plan 7,3.
    ecarts = [62.7, 17.5, 30.1, 28.9, 28.1, 22.3, 17.4] + [7.3] * 200
    r = h3.regles.regle_sans_coupe(ecarts, 24, raccord=True)
    assert r["ok"] is False and "raccord" in r["pourquoi"]
    # Dedans, l'instant reste celui du plan, pas décalé de l'image du plan d'avant.
    dedans = [3.0] * 25 + [48.2] + [3.0] * 20
    assert "à 1.0 s (images 24 → 25" in h3.regles.regle_sans_coupe(dedans, 24, raccord=True)["pourquoi"]
    assert "à 1.0 s (images 24 → 25" in h3.regles.regle_sans_coupe(dedans[1:], 24)["pourquoi"]


@pytest.mark.parametrize("enchainement, depuis", [("suite", 99), ("coupe", 100)])
def test_le_juge_mesure_une_suite_depuis_la_fin_du_plan_d_avant(h3, monkeypatch, tmp_path, enchainement, depuis):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"FILM")
    plans = [{"image_paroles": "a", "enchainement": "suite"}, {"image_paroles": "b", "enchainement": enchainement}]
    monkeypatch.setattr(h3.video_h3, "scenario_lire", lambda sid: {"plans": plans, "fiches": []})
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: film)
    monkeypatch.setattr(h3, "read_job", lambda jid: {"video": {"secondes": 200 / 24}})
    monkeypatch.setattr(h3, "_photos_des_fiches", lambda fiches: ([], []))

    async def regles_clip(*a):
        return {10: {"ok": True, "pourquoi": ""}}

    async def ecouter(*a):
        return {"attendu": ["b"], "ok": True}
    monkeypatch.setattr(h3, "_regles_clip", regles_clip)
    monkeypatch.setattr(h3, "_ecouter", ecouter)
    extraits = []
    monkeypatch.setattr(h3.montage, "extraire", lambda video, a, b: extraits.append((a, b)) or b"M%d" % a)
    monkeypatch.setattr(h3.montage, "ecarts_d_images", lambda m: [3.0] * 50 if m == b"M100" else [62.7] + [3.0] * 50)
    note = h3._juger_plan_tourne("s", 1, "j", 100)
    assert (depuis, 200) in extraits
    r15 = next(x for x in note["regles"] if x["n"] == 15)
    assert r15["ok"] is (enchainement == "coupe")


def test_une_voix_dans_le_raccord_est_tue_avant_la_suite(h3, monkeypatch):
    # 02/10 : « Parfaite ! » à la fin du plan 1, dans le raccord ; H3 faisait parler Leila 4 à 5 s.
    monkeypatch.setattr(h3.montage, "fin", lambda video, n: b"RACCORD")
    monkeypatch.setattr(h3.montage, "passages_de_voix", lambda video: [(0.0, 0.92, [(0.0, 0.92)])])
    monkeypatch.setattr(h3.montage, "taire", lambda video: b"MUET")
    _, raccord = h3._derniere_et_raccord(b"FILM", b"IMAGE")
    assert base64.b64decode(raccord) == b"MUET"
    monkeypatch.setattr(h3.montage, "passages_de_voix", lambda video: [])
    assert base64.b64decode(h3._derniere_et_raccord(b"FILM", b"IMAGE")[1]) == b"RACCORD"


# --- Ambiance égale d'un plan à l'autre (02/10, film 4 : « tu mets ces réglages en automatique ») ---

def _trois_plans():
    # Trois plans : eau forte (-26 dB, 3 s), silence (-73 dB, 5 s, une réplique au milieu), eau (-38 dB, 5 s).
    amb = [-26.0] * 30 + [-73.0] * 50 + [-38.0] * 50
    voix = [-60.0] * 130
    for k in range(50, 61):
        voix[k] = -20.0
    return amb, voix, [30, 80, 130]


def test_l_ambiance_trop_forte_est_baissee_et_la_muette_completee_hors_paroles(h3):
    m = h3.montage
    amb, voix, bornes = _trois_plans()
    d = m.regler_ambiance(amb, voix, bornes)
    # Référence : le plan le plus fort, AMB_RETRAIT_DB en retrait (12 dB, choix du propriétaire) ;
    # le plan au-dessus est baissé (borné à AMB_BAISSE_MAX_DB), les autres ne bougent pas.
    ref = -26.0 - m.AMB_RETRAIT_DB
    assert m.AMB_RETRAIT_DB == 12.0 and d["reference_db"] == ref
    assert [p["gain_db"] for p in d["plans"]] == [max(-m.AMB_BAISSE_MAX_DB, ref + 26.0), 0.0, 0.0]
    assert d["parole"][55] and d["parole"][48] and not d["parole"][45] and not d["parole"][10]
    # La nappe vient du plus long passage sans paroles au niveau visé : le plan 3.
    k0, k1 = d["source"]
    assert (k0, k1) == (80, 130) and not any(d["parole"][k0:k1])
    # Elle comble le plan muet, baissée sous la réplique, et rien là où le fond est déjà au niveau.
    assert d["nappe"][70] == pytest.approx(1.0, abs=0.02)
    assert d["nappe"][55] == pytest.approx(m.AMB_SOUS_VOIX, abs=0.02)
    assert d["nappe"][10] == pytest.approx(0.0, abs=0.01)
    assert d["nappe"][110] == pytest.approx(0.0, abs=0.01)


def test_le_fond_de_chaque_plan_se_regle_a_la_main(h3):
    """Propriétaire, 02/10 : « un bouton d'ajustement manuel pour chaque clip si besoin »."""
    m = h3.montage
    amb, voix, bornes = _trois_plans()
    d = m.regler_ambiance(amb, voix, bornes, [0, 6, -6])
    ref = d["reference_db"]
    assert [p["vise_db"] for p in d["plans"]] == [ref, ref + 6, ref - 6]
    # Plan 2 monté de 6 dB : la nappe double ; plan 3 baissé de 6 dB.
    assert d["nappe"][70] == pytest.approx(10 ** (6 / 20), abs=0.05)
    assert d["plans"][2]["gain_db"] == -6.0
    # Un réglage manquant vaut 0 ; hors bornes ou illisible : refusé.
    assert m.ajustements_valides([3], 3) == [3.0, 0.0, 0.0]
    for faux in ([0, 0, 0, 0], [99], ["fort"], [float("nan")]):
        with pytest.raises(ValueError):
            m.ajustements_valides(faux, 3)


def test_la_nappe_ne_se_prend_jamais_sur_une_replique(h3):
    m = h3.montage
    amb = [-30.0] * 100
    voix = [-60.0] * 100
    for k in list(range(5, 15)) + list(range(60, 70)):   # deux répliques dans l'unique plan
        voix[k] = -10.0
    d = m.regler_ambiance(amb, voix, [100])
    k0, k1 = d["source"]
    assert not any(d["parole"][k0:k1]) and (k0, k1) == (18, 57)


def test_sans_ambiance_rien_n_est_touche(h3):
    m = h3.montage
    d = m.regler_ambiance([-80.0] * 100, [-60.0] * 100, [50, 100])
    assert d["reference_db"] is None and d["source"] is None
    assert [p["gain_db"] for p in d["plans"]] == [0.0, 0.0] and not any(d["nappe"])


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_l_ambiance_egalisee_garde_les_images_et_rapproche_les_plans(h3, tmp_path):
    m = h3.montage
    film = tmp_path / "film.mp4"
    # Deux plans de 3 s : un bruit d'eau fort, puis presque rien.
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=6",
                    "-f", "lavfi", "-i", "anoisesrc=a=0.2:d=3:seed=1", "-f", "lavfi",
                    "-i", "anoisesrc=a=0.002:d=3:seed=2", "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    str(film)], check=True)
    egal, rapport = m.egaliser_ambiance(film.read_bytes(), [3.0, 6.0])
    sortie = tmp_path / "egal.mp4"
    sortie.write_bytes(egal)
    assert m.images(sortie) == m.images(film)
    baisse = -min(m.AMB_RETRAIT_DB, m.AMB_BAISSE_MAX_DB)
    assert rapport["plans"][0]["gain_db"] == baisse and rapport["plans"][1]["gain_db"] == 0.0
    assert rapport["nappe_depuis_s"] is not None
    avant = m._niveaux(m._pcm(film, m.AMB_BANDE, 1, m.AMB_TAUX), m.AMB_PAS)
    apres = m._niveaux(m._pcm(sortie, m.AMB_BANDE, 1, m.AMB_TAUX), m.AMB_PAS)
    ecart_avant = m._mediane(avant[5:25]) - m._mediane(avant[35:55])
    ecart_apres = m._mediane(apres[5:25]) - m._mediane(apres[35:55])
    assert ecart_avant > 30 and abs(ecart_apres) < 3


def test_le_scenario_fini_egalise_son_ambiance_et_garde_le_film_brut(h3, monkeypatch, tmp_path):
    v = h3.video_h3
    sid = "a" * 32
    v.scenario_ecrire({"id": sid, "etat": "en cours", "erreur": "", "plans": [], "travaux": ["b" * 32]})
    brut = tmp_path / "brut.mp4"
    brut.write_bytes(b"BRUT")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: brut)
    monkeypatch.setattr(h3, "read_job", lambda jid: {"titre": "Leila", "video": {"plans": 2}})
    vus, faits = [], []
    rapport = {"reference_db": -33.9, "plans": []}
    monkeypatch.setattr(h3.montage, "egaliser_ambiance", lambda f, b, aj=None, piste=None: vus.append((f, b)) or (b"EGAL", rapport))
    monkeypatch.setattr(h3, "_film_h3", lambda film, video, titre, moteur="": faits.append((film, video)) or "c" * 32)
    assert h3._egaliser_scenario(sid, "b" * 32, [124, 248], 24.0) == "c" * 32
    assert vus == [(b"BRUT", [124 / 24, 248 / 24])]
    assert faits[0][0] == b"EGAL" and faits[0][1]["mode"] == "ambiance" and faits[0][1]["clips"] == ["b" * 32]
    sc = v.scenario_lire(sid)
    assert sc["ambiance"] == rapport and sc["film_sans_ambiance"] == "b" * 32
    # Un rejeu reprend ses plans sur le film brut : l'ambiance ne s'égalise qu'une fois.
    assert h3._film_du_scenario(dict(sc, film="c" * 32, film_sans_musique="c" * 32)) == "b" * 32
    # Un échec n'arrête pas le film : le brut reste, l'erreur est notée.
    def rate(f, b, aj=None, piste=None):
        raise h3.montage.MontageImpossible("La lecture du son du film a échoué.")
    monkeypatch.setattr(h3.montage, "egaliser_ambiance", rate)
    assert h3._egaliser_scenario(sid, "b" * 32, [124], 24.0) == "b" * 32
    assert v.scenario_lire(sid)["ambiance"] == {"erreur": "La lecture du son du film a échoué."}


def test_le_fond_se_refait_a_la_main_depuis_le_film_brut_et_la_musique_revient(h3, monkeypatch, tmp_path):
    """Propriétaire, 02/10 : « un bouton d'ajustement manuel pour chaque clip si besoin »."""
    v = h3.video_h3
    sid, _ = _scenario_tourne(h3, monkeypatch, tmp_path)
    v.scenario_noter(sid, film_sans_ambiance="b" * 32, film_sans_musique="e" * 32)
    film = tmp_path / "brut.mp4"
    film.write_bytes(b"BRUT")
    lus, egalises, musiques = [], [], []
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: lus.append(jid) or film)
    monkeypatch.setattr(h3, "read_job", lambda jid: {"titre": "Film", "video": {}})
    rapport = {"reference_db": -40.0, "plans": []}
    monkeypatch.setattr(h3.montage, "egaliser_ambiance",
                        lambda f, b, aj=None, piste=None: egalises.append(aj) or (b"EGAL", rapport))
    monkeypatch.setattr(h3, "_film_h3", lambda *a, **k: "a" * 32)
    monkeypatch.setattr(h3, "_mettre_musique", lambda jid, *a: musiques.append(jid) or "m" * 32)
    c = client(h3)
    for _ in range(2):
        r = c.post(f"/video-h3/scenario/{sid}/ambiance", headers=CLE, json={"plans_db": [0, -3]})
        assert r.status_code == 200, r.text
    # Chaque fois depuis le film BRUT (rien ne s'accumule), le réglage complété à un par plan.
    assert set(lus) == {"b" * 32}
    assert egalises == [[0.0, -3.0, 0.0]] * 2
    assert musiques == ["a" * 32] * 2
    sc = v.scenario_lire(sid)
    assert sc["film"] == "m" * 32 and sc["film_sans_ambiance"] == "b" * 32 and sc["film_sans_musique"] == "a" * 32
    assert sc["ambiance_plans_db"] == [0.0, -3.0, 0.0] and r.json()["film"] == "m" * 32
    r = c.post(f"/video-h3/scenario/{sid}/ambiance", headers=CLE, json={"plans_db": [40]})
    assert r.status_code == 400 and "dB" in r.json()["detail"]
    page = c.get("/video-h3").text
    assert 'value="fond"' in page and "function actionFond" in page and 'id="fond_plans"' in page


def test_un_plan_au_texte_change_est_juge_sur_son_nouveau_texte_et_son_tableau_vide_se_refait(h3, monkeypatch):
    """Bug du 02/10, film 4, plan 6a : réécrit au rejeu, il était jugé sur le texte du plan 6
    d'origine (`plans_initiaux` hérité) ; son tableau, vidé, n'était pas réécrit."""
    v = h3.video_h3
    initiaux = [{"image_paroles": "Plan 1 tel qu'écrit"}, {"image_paroles": "Tyler part, Leila salue."}]
    anciens = [{"image_paroles": "Plan 1 adapté par le Studio"}, {"image_paroles": "Tyler part, Leila salue."}]
    ecrits = [{"image_paroles": "Plan 1 adapté par le Studio"},
              {"image_paroles": "Leila regarde la photo et dit « Merci ! »"},
              {"image_paroles": "Un plan de plus"}]
    sortie = v.plans_initiaux_du_rejeu(initiaux, anciens, ecrits)
    # Même texte : l'origine héritée ; texte changé ou plan neuf : le texte écrit.
    assert [p["image_paroles"] for p in sortie] == ["Plan 1 tel qu'écrit", "Leila regarde la photo et dit « Merci ! »",
                                                    "Un plan de plus"]
    tableau = [{"nom": "Leila", "debut": "sitting", "mouvement": "looks", "fin": "sitting"}]
    demandes = []

    async def chat(consigne, quoi, images=None, modele=None):
        demandes.append(consigne)
        return json.dumps({"elements": tableau})
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    ancien_tableau = [{"nom": "Tyler", "debut": "astride", "mouvement": "rides away", "fin": "gone"}]
    plans = [dict(ecrits[1], elements=[])]
    notes = asyncio.run(h3._tableaux_a_jour(plans, [dict(anciens[1], elements=ancien_tableau)], set()))
    assert plans[0]["elements"] == tableau and "rides away" in demandes[0] and notes[0]["plan"] == 1


def test_une_reaction_a_l_action_principale_n_est_pas_une_seconde_action(h3):
    """02/10, film 4, plan 6b : « Tyler part à vélo, Leila le salue et lui lance sa réplique »,
    refusé trois fois (« deux actions »), tourné forcé et réussi. Propriétaire : « on changera
    la règle si ça passe à nouveau ». Deux actions indépendantes restent deux plans."""
    v = h3.video_h3
    plans = [{"image_paroles": "Tyler rides away; Leila waves and calls « À demain ! »", "ambiance": "",
              "enchainement": "coupe"}]
    for texte in (v.TABLEAU, v.consigne_continuite(plans, "Histoire")):
        assert "she waves and calls goodbye: ONE main action" in texte
        assert "umbrella" in texte


def test_un_rejeu_qui_renvoie_l_image_du_decoupage_ne_retourne_pas_la_coupe(h3):
    """Bug 18 du 02/10, film 4 : le plan 5 repartait chez Modal parce que le client renvoyait
    l'image du découpage, que le tournage avait remplacée par une image refaite d'après le film."""
    v = h3.video_h3
    anciens = [{"image_paroles": "A", "ambiance": "", "enchainement": "coupe", "image_depart": "refaite",
                "description_depart": "d'après le film"}]
    notes = [{"plan": 1, "depart": "refaite", "garde": "refaite", "decoupage": "decoupe", "note": ""}]
    client = [{"image_paroles": "A", "ambiance": "", "enchainement": "coupe", "image_depart": "decoupe",
               "description_depart": "du découpage"}]
    assert v.plans_a_reprendre(anciens, client) == []          # avant : retourné pour rien
    remis = v.plans_avec_coupes_refaites(client, anciens, notes)
    assert remis[0]["image_depart"] == "refaite" and v.plans_a_reprendre(anciens, remis) == [0]
    assert client[0]["image_depart"] == "decoupe"              # la liste du client n'est pas touchée
    # Une autre image choisie par le client, ou une coupe non refaite : rien ne change.
    autre = [dict(client[0], image_depart="neuve")]
    assert v.plans_avec_coupes_refaites(autre, anciens, notes)[0]["image_depart"] == "neuve"
    rate = [dict(notes[0], depart=None, garde="decoupe")]
    assert v.plans_avec_coupes_refaites(client, anciens, rate)[0]["image_depart"] == "decoupe"


def test_une_suite_trop_longue_est_refusee_avant_le_premier_sou(h3):
    """Bug 20 du 02/10, film 4, plan 6 : le contrôle mesurait l'invite d'une suite SANS l'en-tête
    de suite ni les lignes <Video 1> ; acceptée, puis refusée au tournage à 4 015 caractères."""
    v = h3.video_h3
    lea = v.fiche_creer("Léa", "x")["id"]
    v.fiche_poser_image(lea, "face", PNG)
    base = {"mode": "references", "fiches": [lea], "langues": {lea: "French"}, "ambiance": "", "coupe_s": 0,
            "images": [], "longueur": 124, "visages_seuls": False}
    court = dict(base, image_paroles="Léa sourit.")
    nu = len(v.preparer(dict(court, depart_reference=JPG))["resume_public"]["invite"])
    vrai = len(v.controler_suite(court)["resume_public"]["invite"])
    assert v.SUITE_DEBUT[:40] in v.controler_suite(court)["resume_public"]["invite"] and vrai > nu
    # Un texte qui tient nu, mais pas en suite : refusé dès le contrôle, avec sa longueur.
    long = dict(base, image_paroles="Léa sourit. " + "x" * (4000 - nu - (vrai - nu) // 2))
    v.preparer(dict(long, depart_reference=JPG))
    with pytest.raises(ValueError, match=r"Invite trop longue : \d+ caractères, 4 000 au plus"):
        v.controler_suite(long)


# --- Le décor tenu d'un plan à l'autre (03/10) --------------------------------------
# Propriétaire, 03/10 : « corrige la fontaine qui change entre les plans de façon générique,
# probablement avec une id card meilleure et un son track id along the clip » ; « oui, pour tout ».

def _decor_et_leila(v):
    lieu = v.fiche_creer("la place", "petite place pavée, fontaine de pierre à deux vasques", genre="decor")["id"]
    v.fiche_poser_image(lieu, "face", PNG)
    leila = v.fiche_creer("Leila", "une adolescente")["id"]
    v.fiche_poser_image(leila, "face", PNG)
    return lieu, leila


def test_le_decor_part_a_h3_avant_l_image_de_depart_quand_on_le_demande(h3):
    v = h3.video_h3
    lieu, leila = _decor_et_leila(v)
    base = {"mode": "references", "image_paroles": "Leila sits on the fountain.", "fiches": [leila],
            "decor": lieu, "depart_reference": PNG}
    sans = v.preparer(dict(base))
    assert not sans["resume_public"]["decor_video"] and "setting" not in sans["resume_public"]["invite"]
    avec = v.preparer(dict(base, decor_video=True))
    invite = avec["resume_public"]["invite"]
    assert avec["resume_public"]["decor_video"]
    # Leila en <Picture 1>, le décor en <Picture 2>, l'image de départ en dernier, épinglée.
    assert "<Picture 2> is the setting of [Shot 1]" in invite and "<Picture 2> (setting): fully_preserved" in invite
    assert "<Picture 3> is the first frame of [Shot 1]" in invite and "begins from <Picture 3>" in invite
    assert len(avec["demande"]["images"]) == len(sans["demande"]["images"]) + 1
    legere = v.preparer(dict(base, decor_video=True, invite_legere=True))["resume_public"]["invite"]
    assert "<Picture 2>: fully_preserved - same place and fixed elements" in legere


def test_le_decor_ne_prend_pas_une_place_qui_manque(h3, monkeypatch):
    v = h3.video_h3
    lieu, leila = _decor_et_leila(v)
    monkeypatch.setitem(v.MODES["references"], "images_max", 2)   # Leila + le départ : complet
    r = v.preparer({"mode": "references", "image_paroles": "Leila sits.", "fiches": [leila], "decor": lieu,
                    "depart_reference": PNG, "decor_video": True})
    assert not r["resume_public"]["decor_video"] and len(r["demande"]["images"]) == 2


def test_la_fiche_du_decor_se_fait_d_apres_le_texte_si_le_film_reste_au_meme_endroit(h3, monkeypatch):
    v = h3.video_h3
    consigne = v.consigne_decor_du_texte(["Leila sits on the fountain.", "Tyler rides up."])
    assert "[Shot 2] Tyler rides up." in consigne and "un_seul_lieu" in consigne and "water jets" in consigne
    # 03/10, « Le jardin de verre » : la pousse que le plan 2 fait naître était déjà dans le pot du décor.
    assert "at the START of the film" in consigne and "an empty pot stays empty" in consigne
    assert "aucun objet ni plante en plus" in v.CADRE_DECOR
    # 03/10, « le canapé aurait dû faire partie du décor id » : les meubles y sont décrits, pas les accessoires.
    assert "EVERY piece of furniture" in consigne and "say there is no other furniture" in consigne
    assert "nor the props the characters use" in consigne
    assert "every piece of furniture" in v.consigne_decor_du_film(3)
    # Les quatre côtés du lieu sont décrits : chaque vue de la planche montre ce que la description y met.
    assert v.COTES_DU_LIEU in consigne and v.COTES_DU_LIEU in v.consigne_decor_du_film(3)
    assert "the camera never goes behind it" in v.COTES_DU_LIEU and "NEAR side" not in v.COTES_DU_LIEU
    # La lumière fait partie du décor (03/10 : un décor en plein jour pour un film au coucher du soleil).
    assert "the time of day and the light" in v.COTES_DU_LIEU and "l'heure et la lumière" in v.CADRE_DECOR
    assert "the camera never crosses to the side behind it, 180-degree rule" in v.consigne_decoupage("x")
    assert "%d characters" not in consigne and str(v.DECOR_DESCRIPTION_MAX - 50) in consigne
    assert v.lire_decor_du_texte('{"un_seul_lieu": false}') is None
    with pytest.raises(ValueError):
        v.lire_decor_du_texte("pas de JSON")
    description = ("A small cobbled square with a round stone fountain: a basin at seat height, two tiers, "
                   "four water jets, beige stone buildings behind it.")
    reponse = json.dumps({"un_seul_lieu": True, "nom": "the cobbled square", "description": description})
    assert v.lire_decor_du_texte(reponse)["nom"] == "the cobbled square"
    demandes = []

    async def chat(consigne, quoi, images=None, modele=None):
        return reponse

    async def image(demande):
        demandes.append(demande)
        return "data:image/png;base64," + PNG
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    monkeypatch.setattr(h3, "_image_du_studio", image)
    plans = [{"image_paroles": "Leila sits on the fountain."}, {"image_paroles": "Tyler rides up."}]
    d = asyncio.run(h3._decor_du_texte(plans))
    fiche = v.fiche_lire(d["fiche"])
    assert fiche["genre"] == "decor" and fiche["description"] == description and not fiche.get("planche")
    # La vue vide seule, d'après le texte (03/10 : plus de planche, règle des 180°).
    assert len(demandes) == 1 and "image_reference" not in demandes[0] and v.CADRE_DECOR in demandes[0]["prompt"]

    async def ailleurs(consigne, quoi, images=None, modele=None):
        return '{"un_seul_lieu": false}'
    monkeypatch.setattr(h3, "_chat_du_studio", ailleurs)
    assert asyncio.run(h3._decor_du_texte(plans)) == {"fiche": None, "pourquoi": "le scénario change de lieu"}

    async def panne(consigne, quoi, images=None, modele=None):
        raise h3.HTTPException(503, "Le chat du Studio ne répond pas.")
    monkeypatch.setattr(h3, "_chat_du_studio", panne)
    assert asyncio.run(h3._decor_du_texte(plans))["fiche"] is None   # rien ne bloque : le film part sans


def test_le_tournage_fait_la_fiche_du_decor_quand_le_scenario_n_en_a_pas(h3, monkeypatch, tmp_path, sans_regles,
                                                                         sans_objets_clefs):
    """Avant la première image, une seule fois : chaque coupe en garde le lieu."""
    v = h3.video_h3
    lieu, leila = _decor_et_leila(v)
    vus = []

    async def decor(plans):
        vus.append(len(plans))
        return {"fiche": lieu, "nom": "la place"}
    monkeypatch.setattr(h3, "_decor_du_texte", decor)
    monkeypatch.setenv("STUDIO_DECOR_AUTO", "true")
    poses = []

    async def departs(plans, commun):
        poses.append(commun.get("decor"))
        raise h3.HTTPException(418, "arrêt du test")
    monkeypatch.setattr(h3, "_departs_des_coupes", departs)
    _autoriser(h3)
    v.poids_noter(True)
    monkeypatch.setattr(h3, "modal_configured", lambda: True)
    fid = leila
    plans = [{"image_paroles": "Leila sits.", "ambiance": "", "enchainement": "coupe"}]
    c = client(h3)
    r = c.post("/video-h3/scenario/tourner", headers=CLE, json={"plans": plans, "fiche": fid})
    assert r.status_code == 418 and vus == [1] and poses == [lieu]
    # Un décor déjà choisi, ou `decor_auto: false` : rien n'est refait.
    for corps in ({"decor": lieu}, {"decor_auto": False}):
        c.post("/video-h3/scenario/tourner", headers=CLE, json=dict({"plans": plans, "fiche": fid}, **corps))
    assert vus == [1] and poses == [lieu, lieu, None]


def test_la_regle_17_lit_le_decor_du_plan_contre_sa_fiche(h3):
    r = h3.regles
    assert 17 in r.NUMEROS["clip"] and 17 not in h3.REGLES_QUI_REPRENNENT   # notée, pas encore reprise
    assert "Images 2 to 4" in r.consigne_decor_constant(3) and "water jets" in r.consigne_decor_constant(3)
    assert r.lire_decor_constant('{"ok": true, "differences": []}')["ok"] is True
    faux = r.lire_decor_constant('{"ok": false, "differences": ["fontaine : trois jets au lieu de quatre"]}')
    assert faux["ok"] is False and "trois jets" in faux["pourquoi"]
    assert r.lire_decor_constant('{"ok": false, "differences": []}')["ok"] is None
    assert r.lire_decor_constant("illisible")["ok"] is None


def test_le_decor_du_plan_tourne_se_juge_sur_trois_images(h3, monkeypatch):
    v = h3.video_h3
    lieu, _ = _decor_et_leila(v)
    lues, vues = [], []
    monkeypatch.setattr(h3.montage, "vignettes", lambda film, numeros, largeur: lues.append(numeros) or
                        [base64.b64decode(PNG)] * len(numeros))

    async def chat(consigne, quoi, images=None, modele=None):
        vues.append(images)
        return '{"ok": false, "differences": ["fontaine : une seule vasque"]}'
    monkeypatch.setattr(h3, "_chat_du_studio", chat)
    assert asyncio.run(h3._decor_constant(b"film", 0, 121, None)) is None   # sans fiche : rien
    r = asyncio.run(h3._decor_constant(b"film", 121, 241, lieu))
    assert r["ok"] is False and "une seule vasque" in r["pourquoi"]
    assert lues == [[121, 180, 239]] and vues[0][0] == v.fiche_lieu_image(lieu) and len(vues[0]) == 4


def test_la_piste_son_du_lieu_sert_de_nappe(h3):
    m = h3.montage
    amb, voix, bornes = _trois_plans()
    d = m.regler_ambiance(amb, voix, bornes, nappe_db=-50.0)
    assert d["source"] == "fiche"
    # Le plan muet est comblé ; la nappe, 12 dB plus bas que sa piste, est relevée d'autant.
    assert d["nappe"][70] == pytest.approx(min(10 ** ((d["reference_db"] + 50.0) / 20), m.AMB_NAPPE_MAX), abs=0.05)
    # Une piste sans son ne compte pas : la nappe se reprend dans le film.
    assert m.regler_ambiance(amb, voix, bornes, nappe_db=-90.0)["source"] == (80, 130)


def test_la_piste_son_du_lieu_se_garde_sur_la_fiche_puis_resert(h3, monkeypatch, tmp_path):
    v = h3.video_h3
    lieu, _ = _decor_et_leila(v)
    sid = "a" * 32
    v.scenario_ecrire({"id": sid, "etat": "en cours", "erreur": "", "plans": [], "travaux": ["b" * 32],
                       "reglages": {"decor": lieu}})
    brut = tmp_path / "brut.mp4"
    brut.write_bytes(b"BRUT")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: brut)
    monkeypatch.setattr(h3, "read_job", lambda jid: {"titre": "Leila", "video": {"plans": 1}})
    monkeypatch.setattr(h3, "_film_h3", lambda *a, **k: "c" * 32)
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64
    pistes, coupes = [], []
    monkeypatch.setattr(h3.montage, "egaliser_ambiance", lambda f, b, aj=None, piste=None: pistes.append(piste) or
                        (b"EGAL", {"reference_db": -38.0, "plans": [], "nappe_depuis_s": [8.0, 13.0]}))
    monkeypatch.setattr(h3.montage, "piste_du_lieu", lambda film, depuis: coupes.append(depuis) or wav)
    h3._egaliser_scenario(sid, "b" * 32, [124], 24.0)
    assert pistes == [None] and coupes == [[8.0, 13.0]] and v.fiche_son_lieu(lieu) == wav
    assert v.scenario_lire(sid)["ambiance"]["piste_gardee_sur_la_fiche"] == lieu
    h3._egaliser_scenario(sid, "b" * 32, [124], 24.0)   # le film suivant au même endroit
    assert pistes == [None, wav] and coupes == [[8.0, 13.0]]
    with pytest.raises(ValueError, match="WAV"):
        v.fiche_poser_son_lieu(lieu, b"pas un son")


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_l_ambiance_se_fait_de_la_piste_du_lieu(h3, tmp_path):
    m = h3.montage
    film = tmp_path / "film.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=6",
                    "-f", "lavfi", "-i", "anoisesrc=a=0.2:d=3:seed=1", "-f", "lavfi",
                    "-i", "anoisesrc=a=0.002:d=3:seed=2", "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    str(film)], check=True)
    piste = m.piste_du_lieu(film.read_bytes(), [0.5, 2.8])
    assert piste[:4] == b"RIFF" and piste[8:12] == b"WAVE"
    egal, rapport = m.egaliser_ambiance(film.read_bytes(), [3.0, 6.0], None, piste)
    sortie = tmp_path / "egal.mp4"
    sortie.write_bytes(egal)
    assert m.images(sortie) == m.images(film) and rapport["nappe_de"] == "fiche du décor"
    assert rapport["nappe_depuis_s"] is None
    apres = m._niveaux(m._pcm(sortie, m.AMB_BANDE, 1, m.AMB_TAUX), m.AMB_PAS)
    assert abs(m._mediane(apres[5:25]) - m._mediane(apres[35:55])) < 3


def test_le_decoupage_recoit_les_fiches_et_ne_change_pas_la_tenue(h3, monkeypatch, sans_traduction):
    """03/10, « Le jardin de verre » : le découpage, sans les fiches, a habillé Mila d'un
    pull crème et d'un jean ; sa fiche dit pull rayé et salopette jaune. Propriétaire :
    « corrige le découpage pour qu'il reçoive les fiches »."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-routeur-de-test")
    c = client(h3)
    mila = c.post("/video-h3/fiches", headers=CLE, json={
        "nom": "Mila", "description": "Fillette de 9 ans, pull à rayures blanches et bleu marine, "
                                     "salopette en velours jaune moutarde"}).json()["id"]
    decoupe = '[{"image_paroles": "Mila arrose le pot.", "ambiance": "", "enchainement": "coupe"}]'
    vus = []
    monkeypatch.setattr(h3.httpx, "AsyncClient", _FauxRouteurSuite(
        [decoupe, '{"etats": [], "problemes": []}', "[]", "[]"], vus))
    r = c.post("/video-h3/scenario/decouper", headers=CLE,
               json={"scenario": "Mila arrose le pot.", "fiches": [mila, ""]})
    assert r.status_code == 200, r.text
    consigne = vus[0]["messages"][0]["content"]
    consigne = consigne if isinstance(consigne, str) else consigne[0]["text"]
    # 03/10, propriétaire : « les attributs sont toujours avec des images, jamais en texte » :
    # le nom seul part, la photo porte l'apparence.
    # Le nom seul, sans genre : « Mila (personne) » a été recopié dans les plans.
    assert "Call them exactly: Mila." in consigne and "(personne)" not in consigne
    assert "rayures" not in consigne and "9 ans" not in consigne
    assert "Never write their looks: no clothing" in consigne
    # Une tenue écrite quand même par le découpage, que l'histoire ne donne pas, est retirée.
    v = h3.video_h3
    sortie, touches = v.sans_tenue_du_texte(
        [{"image_paroles": "Mila, wearing a cream sweater, waters the pot.", "ambiance": ""},
         {"image_paroles": "Mila waters the pot, in her red coat.", "ambiance": ""}], "Mila, in her red coat, waters.")
    assert [s["image_paroles"] for s in sortie] == ["Mila waters the pot.", "Mila waters the pot, in her red coat."]
    assert touches == [1]
    # Une fiche inconnue est refusée avant tout appel au chat ; sans fiche, rien n'est ajouté.
    assert c.post("/video-h3/scenario/decouper", headers=CLE,
                  json={"scenario": "x", "fiche": "inconnue"}).status_code == 400
    assert h3.video_h3.distribution([]) == "" and "reference sheets" not in h3.video_h3.consigne_decoupage("x")
    assert "fiches: fichesDuScenario()})});" in h3.video_h3.PAGE_HTML


def test_un_plan_de_scenario_ne_joint_pas_la_personne_qu_il_ne_nomme_pas(h3):
    """03/10, « Le jardin de verre », plan 2 (gros plan sur le pot) : la photo de Mila partait
    à H3 avec « wears … in every frame », et Mila a traversé le champ."""
    v = h3.video_h3
    mila, pot = v.fiche_creer("Mila", "x")["id"], v.fiche_creer("pot of soil", "y", "objet")["id"]
    v.fiche_poser_image(mila, "face", PNG)
    v.fiche_poser_image(pot, "face", PNG)
    elements = [{"nom": "pot of soil", "debut": "centre"}, {"nom": "crystal sprout", "debut": "off-frame"}]
    d = demande(mode="references", fiches=[mila, pot], elements=elements,
                image_paroles="Close-up on the pot of soil: a crystal sprout grows.")
    invite = v.preparer(d)["resume_public"]["invite"]
    assert "is the person in" not in invite and "<Subject 1> is the object in <Picture 1>" in invite
    # Nommée par le texte ou le tableau, elle reste ; un clip sans tableau garde toutes ses fiches.
    assert v.personnes_du_plan([mila, pot], dict(d, image_paroles="Mila waters the pot of soil.")) == [mila, pot]
    assert v.personnes_du_plan([mila, pot], {"image_paroles": "She waters it."}) == [mila, pot]
    # Personne de nommé et aucun objet : la fiche reste, plutôt qu'un plan sans fiche.
    assert v.personnes_du_plan([mila], d) == [mila]


def test_un_objet_clef_avec_ou_sans_article_n_a_qu_une_fiche(h3):
    """03/10, « Le jardin de verre » : « pot of soil » et « the pot of soil », deux fiches."""
    v = h3.video_h3
    plans = [{"image_paroles": "x", "elements": [{"nom": "pot of soil", "debut": "centre", "mouvement": "none"}]},
             {"image_paroles": "y", "elements": [{"nom": "the pot of soil", "debut": "left", "mouvement": "none"}]}]
    assert v.objets_clefs(plans, place=3) == ["the pot of soil"]
    du_chat = [{"nom": "pot of soil", "plans": {0}, "bouge": set()},
               {"nom": "the pot of soil", "plans": {1}, "bouge": set()}]
    assert v.objets_clefs([{}, {}], place=3, du_chat=du_chat) == ["the pot of soil"]
    assert v.objets_clefs(plans, exclus=["Pot of soil"], place=3) == []
    assert v.fiche_objet_clef("pot of soil")["id"] == v.fiche_objet_clef("the pot of soil")["id"]


def test_le_raccord_d_une_coupe_est_controle_redessine_une_fois_puis_arrete(h3, monkeypatch, tmp_path):
    """03/10, « Le jardin de verre », plan 2 : le pot haut et cylindrique de la fin du plan 1 est
    revenu en coupe basse, devant un autre canapé ; rien ne comparait les deux images."""
    v = h3.video_h3
    assert v.lire_raccord('{"ok": true, "fautes": []}') == []
    assert v.lire_raccord('x {"ok": false, "fautes": ["the pot is now a low bowl"]} y') == ["the pot is now a low bowl"]
    assert v.lire_raccord('{"ok": false}') == ["faux raccord (sans détail)"]
    with pytest.raises(ValueError):
        v.lire_raccord("pas de JSON")
    c = v.consigne_raccord("Close-up on the pot of soil.")
    assert "SUPPOSED to change" in c and "same shape, size, colour and content" in c and "Close-up on the pot" in c
    fid = v.fiche_creer("Mila", "girl")["id"]
    plans = [{"image_paroles": "a", "ambiance": "", "enchainement": "coupe", "elements": []},
             {"image_paroles": "Close-up on the pot of soil.", "ambiance": "", "enchainement": "coupe",
              "elements": [{"nom": "pot of soil", "debut": "centre", "mouvement": "none", "fin": "centre"}]}]

    def scenario(sid, force=False):
        return v.scenario_ecrire({"id": sid, "etat": "en cours", "erreur": "", "plans": plans, "travaux": [],
                                  "fiche": fid, "fiches": [], "force": force,
                                  "reglages": {"fiche": fid, "fiches": None}})
    video = tmp_path / "plan.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(h3, "_video_h3_octets", lambda jid: video)
    monkeypatch.setattr(h3.montage, "derniere_image", lambda octets: base64.b64decode(PNG))
    monkeypatch.setattr(h3.montage, "recadrer_image", lambda image, l, h: image)
    monkeypatch.setattr(h3, "_controle_derniere_image", lambda s, i, img: None)
    dessins = []

    async def creer(corps):
        dessins.append(corps)
        return {"id": v.depart_poser(PNG), "texte": "Close-up on the pot of soil."}
    monkeypatch.setattr(h3, "_creer_depart", creer)
    vus = []
    # Faux raccord, puis bon : redessinée une fois, l'image neuve part.
    _faux_chat(monkeypatch, h3, {"le contrôle du raccord": [
        '{"ok": false, "fautes": ["the pot is now a low bowl"]}', '{"ok": true, "fautes": []}']}, vus)
    sc = scenario("b" * 32)
    payload = {}
    assert h3._depart_de_coupe(sc["id"], 1, "j" * 32, payload) is True
    assert len(dessins) == 2 and payload.get("depart_reference")
    # Le redessin sait ce que le juge a vu (03/10) ; le premier dessin n'a rien à éviter.
    assert not dessins[0].get("a_eviter") and dessins[1]["a_eviter"] == ["the pot is now a low bowl"]
    assert [x for x in vus if x[0] == "le contrôle du raccord"][0][3] == 2   # deux images au juge
    assert v.scenario_lire(sc["id"])["raccords"][0]["fautes"] == ["the pot is now a low bowl"]
    # Faux raccord deux fois : le film s'arrête, sans partir d'une image au faux raccord.
    dessins.clear()
    _faux_chat(monkeypatch, h3, {"le contrôle du raccord": ['{"ok": false, "fautes": ["sofa moved"]}'] * 2}, vus)
    sc = scenario("c" * 32)
    with pytest.raises(ValueError, match="contrôle du raccord.*sofa moved"):
        h3._depart_de_coupe(sc["id"], 1, "j" * 32, {})
    assert len(dessins) == 2
    # « Tourner quand même » : noté, pas bloquant ; un juge illisible n'arrête rien non plus.
    _faux_chat(monkeypatch, h3, {"le contrôle du raccord": ['{"ok": false, "fautes": ["sofa moved"]}']}, vus)
    assert h3._depart_de_coupe(scenario("d" * 32, force=True)["id"], 1, "j" * 32, {}) is True
    _faux_chat(monkeypatch, h3, {"le contrôle du raccord": ["illisible"]}, vus)
    assert h3._depart_de_coupe(scenario("e" * 32)["id"], 1, "j" * 32, {}) is True
    assert v.scenario_lire("e" * 32)["raccords"][0]["erreur"]


def test_avec_la_fiche_du_decor_une_coupe_d_avant_tournage_tient_les_meubles_de_la_precedente(h3, monkeypatch):
    """03/10, « Le jardin de verre » : « le fauteuil se balade » d'une image de départ à l'autre ;
    avec la fiche du décor, la coupe ne recevait plus l'image de la coupe d'avant."""
    vus = []

    async def depart(corps):
        vus.append(corps)
        return {"id": "d%d" % len(vus), "texte": "x"}
    monkeypatch.setattr(h3, "_depart_redemande", depart)
    plans = [{"image_paroles": "Wide shot. Mila kneels.", "enchainement": "coupe"},
             {"image_paroles": "Close-up. The pot.", "enchainement": "suite"},
             {"image_paroles": "Wide shot. Mila stands.", "enchainement": "coupe"}]
    assert asyncio.run(h3._departs_des_coupes(plans, {"fiches": ["f"], "decor": "lieu1"}))
    assert [(x["decor"], x["meubles"], x["coupe"]) for x in vus] == [(None, None, False), (None, "d1", True)]
    vus.clear()
    plans = [dict(p) for p in plans]
    for p in plans:
        p.pop("image_depart", None)
    asyncio.run(h3._departs_des_coupes(plans, {"fiches": ["f"]}))   # sans décor : comme avant
    assert [(x["decor"], x["meubles"]) for x in vus] == [(None, None), ("d1", None)]
