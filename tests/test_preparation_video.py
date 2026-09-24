"""La description d'une video, preparee avant de partir (24/09/2026).

« un phare » en francais : une cote, puis un homme barbu, sur Kaggle ;
« a lighthouse » : un phare, sur le meme modele. Demande du proprietaire :
« la transformer en anglais, l'enrichir […] transparent dans le rendu du flow,
en grisé si obligatoire […] ou modifiable enrichissement ».
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"


@pytest.fixture
def composite(sandbox):
    return sandbox.composite


def chaine(composite, briques, proprietes=None):
    c = composite.chaine_depuis_briques(briques, composite.charger_registre())
    c["phrase"] = "un phare"
    c["proprietes"] = proprietes or {}
    return c


def par_id(montrees):
    return {p["id"]: p for p in montrees}


# --- Les reglages : la traduction grisee, l'enrichissement modifiable ---------

def test_une_video_montre_la_traduction_grisee_et_l_enrichissement_au_choix(composite):
    ids = par_id(composite.proprietes_montrees(chaine(composite, ["chat_auto", "video_rapide"])))
    traduire, enrichir = ids["traduire@1"], ids["enrichir@1"]
    # UN seul choix : la page dessine le menu desactive (choix.length < 2).
    assert [c["valeur"] for c in traduire["choix"]] == ["oui"]
    assert "obligatoire" in traduire["choix"][0]["nom"]
    assert [c["valeur"] for c in enrichir["choix"]] == ["oui", "non"]
    assert enrichir["defaut"] == "oui" and enrichir["note"]
    # Le chat qui precede n'a rien a preparer.
    assert "traduire@0" not in ids and "enrichir@0" not in ids


def test_seul_l_enrichissement_se_decoche(composite):
    c = chaine(composite, ["video_rapide"])
    assert composite.proprietes_lues('{"enrichir@0": "non"}', c) == {"enrichir@0": "non"}
    assert composite.proprietes_lues('{"traduire@0": "oui"}', c) == {}
    with pytest.raises(composite.CompositeRefuse):
        composite.proprietes_lues('{"traduire@0": "non"}', c)


def test_rien_a_preparer_hors_video(composite):
    ids = par_id(composite.proprietes_montrees(chaine(composite, ["chat_auto", "voix_fr"])))
    assert not [i for i in ids if i.startswith(("traduire@", "enrichir@"))]
    etape = dict(chaine(composite, ["chat_auto"])["etapes"][0], demande="un phare")
    assert composite.pretraiter_par_le_chat(etape, "un phare") is None


# --- Le pretraitement lui-meme ------------------------------------------------

def etape_video(composite, **reglages):
    etape = chaine(composite, ["video_rapide"])["etapes"][0]
    return dict(etape, demande="un phare", reglages=reglages)


def test_par_defaut_traduit_et_enrichit(composite, monkeypatch):
    vus = []
    monkeypatch.setattr(composite, "appeler_le_modele", lambda c: vus.append(c) or
                        "**Prompt:** A white lighthouse on a rock in the rain, waves crashing.")
    pret = composite.pretraiter_par_le_chat(etape_video(composite), None)
    assert pret == {"avant": "un phare", "enrichie": True,
                    "apres": "A white lighthouse on a rock in the rain, waves crashing."}
    assert "60 to 100 words" in vus[0] and "un phare" in vus[0]


def test_decoche_traduit_seulement_et_garde_deux_mots(composite, monkeypatch):
    vus = []
    monkeypatch.setattr(composite, "appeler_le_modele", lambda c: vus.append(c) or '"a lighthouse"')
    pret = composite.pretraiter_par_le_chat(etape_video(composite, enrichir="non"), "un phare")
    assert pret == {"avant": "un phare", "apres": "a lighthouse", "enrichie": False}
    assert "Translate" in vus[0] and "60 to 100 words" not in vus[0]


def test_chat_muet_rien_ne_part(composite, monkeypatch):
    def refuse(_c):
        raise composite.CompositeRefuse("chat_indisponible", "Aucun chat.")
    monkeypatch.setattr(composite, "appeler_le_modele", refuse)
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.pretraiter_par_le_chat(etape_video(composite), None)
    assert refus.value.motif == "preparation_impossible"
    assert "rien n'est parti" in refus.value.phrase
    monkeypatch.setattr(composite, "appeler_le_modele", lambda _c: "")
    with pytest.raises(composite.CompositeRefuse):
        composite.pretraiter_par_le_chat(etape_video(composite), None)


# --- Dans la course : ce qui part est ce qui est montre ------------------------

def test_executer_lance_le_texte_prepare_et_le_montre(composite):
    c = chaine(composite, ["video_rapide"])
    recus, suivis = [], []

    def lancer(etape, entree):
        recus.append(entree)
        return b"\x00\x00\x00\x18ftypmp42"

    def pretraiter(etape, entree):
        return {"avant": etape["demande"], "apres": "a lighthouse", "enrichie": False}

    trace = composite.executer(c, lancer, None, garde_budget=lambda _e: None,
                               suivi=lambda r, s, rendu, _s: suivis.append((s, rendu)),
                               pretraiter=pretraiter)
    assert trace["resultat"] == "rendu", trace
    assert recus == ["a lighthouse"]
    attendu = {"avant": "un phare", "apres": "a lighthouse", "enrichie": False}
    assert trace["etapes"][0]["pretraitement"] == attendu
    # Montre DES le debut du calcul, pas seulement a la fin : un clip Kaggle dure 10 min.
    assert suivis[0] == ("en_cours", {"pretraitement": attendu})


def test_executer_sans_pretraitement_ne_change_rien(composite):
    c = chaine(composite, ["video_rapide"])
    recus = []
    composite.executer(c, lambda e, x: recus.append(x) or b"x", "un phare",
                       garde_budget=lambda _e: None)
    assert recus == ["un phare"]


def test_un_echec_du_pretraitement_arrete_la_chaine_avec_sa_phrase(composite):
    c = chaine(composite, ["video_rapide"])
    lances = []

    def pretraiter(etape, entree):
        raise composite.CompositeRefuse("preparation_impossible", "Pas traduite.",
                                        ou=composite.EXECUTION)

    trace = composite.executer(c, lambda e, x: lances.append(x), None,
                               garde_budget=lambda _e: None, pretraiter=pretraiter)
    assert lances == [] and trace["resultat"] == "refus"
    assert trace["phrase"] == "Pas traduite."


def test_les_routes_de_la_chaine_branchent_le_vrai_pretraitement(sandbox):
    """Les deux appels a `executer` d'app.py : sans lui, la page montrerait des
    reglages que l'execution ignore."""
    import inspect

    source = inspect.getsource(sandbox)
    assert source.count("pretraiter=composite.pretraiter_par_le_chat") == 2
    assert '("texte", "ecoute", "phrase", "pretraitement")' in source


def test_la_page_de_la_chaine_montre_la_preparation(sandbox):
    page = TestClient(sandbox.app, base_url=LOCAL).get("/composite", headers=CLE).text
    assert "function preparation(p)" in page
    assert "if (e.pretraitement) html += preparation(e.pretraitement);" in page


# --- La page /video -----------------------------------------------------------

def test_video_la_route_traduit_seulement_si_on_decoche(sandbox, monkeypatch):
    vus = []
    monkeypatch.setattr(sandbox.composite, "appeler_le_modele",
                        lambda c: vus.append(c) or "a lighthouse")
    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/video/enrichir", headers=CLE,
                    json={"description": "un phare", "enrichir": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"originale": "un phare", "enrichie": "a lighthouse", "enrichir": False}
    assert vus[0] == sandbox.video.CONSIGNE_TRADUIRE % "un phare"


def test_video_la_traduction_est_grisee_l_enrichissement_coche(sandbox):
    page = TestClient(sandbox.app, base_url=LOCAL).get("/video").text
    assert '<input type="checkbox" id="traduire" checked disabled>' in page
    assert '<input type="checkbox" id="enrichirCase" checked>' in page
    assert "enrichir: detailler" in page
