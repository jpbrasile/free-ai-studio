"""Le resume audio NotebookLM dans une chaine (PLAN.md 17.6b, 26/09/2026),
et la ligne << ou calcule chaque etape, au pire combien >> (PLAN.md 16.2).

Sans Google : la fausse bibliotheque de `test_notebooklm_pont.py` tient la
place de `notebooklm-py`, et le VRAI gestionnaire repond derriere le transport
de httpx -- la route `/notebooklm/resume`, son fil, sa fiche et son jeton audio
sont les siens, pas des reponses ecrites d'avance. Ce qui n'est PAS verifie :
le vrai NotebookLM (la session du proprietaire est morte le 26/09), la marque
`ftyp` reelle du .m4a de Google, et la page /composite vue dans un navigateur.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from test_notebooklm_pont import brancher, erreur, nlm  # noqa: F401 -- fixture reprise

BRIQUE = "notebooklm_resume"
LOCAL = "http://127.0.0.1:8020"
CLE = {"Authorization": "Bearer cle-sandbox-de-test"}


@pytest.fixture
def composite(sandbox):
    return sandbox.composite


@pytest.fixture
def apps(composite):
    return composite.charger_registre()


def _etat(branchee=True, coupe=None, routeur=None):
    return {"routeur": routeur, "sandbox": {"modal": False, "kaggle": False},
            "notebooklm": {"branchee": branchee, "coupe": coupe}}


# --- 1. La brique existe partout ou une brique doit exister ---------------------

def test_la_brique_a_sa_route_son_registre_ses_donnees_et_sa_page(composite, apps):
    par_id = {a["id"]: a for a in apps}
    assert composite.ROUTES[BRIQUE] == ("notebooklm", "/notebooklm/resume")
    fiche = par_id[BRIQUE]
    assert fiche["entrees"] == ["texte", "fichier"] and fiche["sorties"] == ["audio"]
    assert composite.exige_une_cle(fiche["cout"])
    d = composite.donnees_de(BRIQUE)
    assert d["sort"] == "oui" and d["vers"] == ["Google"]
    assert "Vos documents partent chez Google (NotebookLM)" in d["phrase"]
    page = composite.PAGE_DES_CLES[composite.CLE_DE_LA_BRIQUE[BRIQUE][0]]
    assert "Me reconnecter à Google" in page and "brancher-notebooklm.cmd" in page
    assert "localhost:8020/notebooklm" in page


def test_le_verdict_annonce_que_les_documents_partent_chez_google(composite, apps):
    chaine = composite.chaine_depuis_briques(["document_lecture", BRIQUE], apps)
    v = composite.verifier(chaine, etat_cles=_etat(), entree="fichier")
    assert v["atteignable"] == composite.OUI, v["pourquoi"]
    assert "chez Google (NotebookLM)" in v["etapes"][1]["donnees"]["phrase"]
    assert "chez Google" in v["resume"]


def test_sans_session_le_verdict_refuse_et_dit_de_se_reconnecter(composite, apps):
    chaine = composite.chaine_depuis_briques([BRIQUE], apps)
    v = composite.verifier(chaine, etat_cles=_etat(branchee=False))
    assert v["atteignable"] == composite.NON and "cle_manquante" in v["motifs"]
    assert "Me reconnecter à Google" in v["pourquoi"]
    assert "brancher-notebooklm.cmd" in v["pourquoi"]


def test_en_studio_partage_le_verdict_refuse_sans_parler_de_reconnexion(composite, apps):
    chaine = composite.chaine_depuis_briques([BRIQUE], apps)
    v = composite.verifier(chaine, etat_cles=_etat(branchee=False,
                                                    coupe="requete relayee par un proxy"))
    assert v["atteignable"] == composite.NON
    assert "notebooklm_coupe" in v["motifs"] and "cle_manquante" not in v["motifs"]
    assert "une seule personne" in v["pourquoi"] and "reconnecter" not in v["pourquoi"]


def test_en_studio_partage_la_route_de_lancement_ne_lance_rien(sandbox, nlm, monkeypatch):  # noqa: F811
    """Le refus est lu sur la requete DU CLIENT, pas sur l'appel interne."""
    pont, _ = nlm
    brancher(pont)
    partis = []
    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur",
                        lambda e, x: partis.append(e) or b"")
    r = TestClient(sandbox.app, base_url="http://192.168.1.20").post(
        "/composite/lancer", headers=CLE, data={"phrase": "résume", "briques": BRIQUE})
    assert r.status_code == 409 and "une seule personne" in r.json()["detail"], r.text
    assert partis == []


# --- 2. Le lancement, par la vraie route de la page NotebookLM ------------------

@pytest.fixture
def studio(sandbox, nlm, monkeypatch):  # noqa: F811
    """Le composite parle au VRAI gestionnaire, et ce qui part se lit."""
    import httpx

    pont, sc = nlm
    client = TestClient(sandbox.app, base_url=LOCAL)
    vues = []

    def transport(requete):
        requete.read()
        vues.append(requete)
        r = client.request(requete.method, requete.url.raw_path.decode("ascii"),
                           content=requete.content,
                           headers={k: v for k, v in requete.headers.items()
                                    if k.lower() in ("authorization", "content-type")})
        return httpx.Response(r.status_code, content=r.content, headers=r.headers)

    vrai = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kw: vrai(transport=httpx.MockTransport(transport), **kw))
    monkeypatch.setattr(sandbox.composite, "ATTENTE_S", 0.05)
    monkeypatch.setattr(sandbox.composite, "NOTEBOOKLM_DELAI_S", 20)
    return sandbox.composite, pont, sc, vues


def _etape(composite, **plus):
    etape = composite.chaine_depuis_briques([BRIQUE])["etapes"][0]
    return dict(etape, demande="résume", **plus)


def test_un_texte_part_en_plusieurs_parties_et_revient_en_m4a(studio):
    composite, pont, sc, vues = studio
    brancher(pont)
    son = composite.lancer_par_le_routeur(_etape(composite), "Les phares de France.")
    assert son.startswith(b"\x00\x00\x00\x20ftypM4A ")
    envoi = vues[0]
    assert envoi.url.path == "/notebooklm/resume"
    assert envoi.headers["content-type"].startswith("multipart/form-data")
    assert any(a[0] == "texte" and a[3] == "Les phares de France." for a in sc.appels)
    assert any("/notebooklm/jobs/" in v.url.path for v in vues)
    assert composite.type_de_sortie(son, ["audio"]) == ("audio/mp4", "sortie.m4a")


def test_un_pdf_joint_part_comme_fichier(studio):
    composite, pont, sc, _ = studio
    brancher(pont)
    composite.lancer_par_le_routeur(_etape(composite), b"%PDF-1.4 faux")
    fichier = next(a for a in sc.appels if a[0] == "fichier")
    assert fichier[2] == b"%PDF-1.4 faux" and fichier[3] == "document.pdf"


def test_sans_session_au_lancement_la_phrase_nomme_la_page_et_le_cmd(studio):
    composite, _, _, _ = studio
    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(_etape(composite), "x")
    assert pris.value.motif == "notebooklm_non_branche"
    assert "Me reconnecter à Google" in pris.value.phrase
    assert "brancher-notebooklm.cmd" in pris.value.phrase
    assert "sur cette page" not in pris.value.phrase


def test_une_session_expiree_se_dit_avec_la_reconnexion(studio):
    composite, pont, sc, _ = studio
    brancher(pont)
    sc.ouverture = erreur("AuthError")
    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(_etape(composite), "x")
    phrase = pris.value.phrase
    assert pris.value.motif == "travail_echoue"
    assert "a expiré" in phrase and "Me reconnecter à Google" in phrase
    assert "http://localhost:8020/notebooklm" in phrase and "ci-dessous" not in phrase


def test_l_arret_du_client_arrete_la_chaine_et_dit_que_google_continue(studio, monkeypatch):
    import asyncio
    import threading

    composite, pont, _, _ = studio
    brancher(pont)
    arret = threading.Event()
    arret.set()

    async def long(*a, **k):  # un resume qui tourne encore chez Google
        await asyncio.sleep(2)
        raise pont.NotebookLMEchec("fin du faux résumé")
    monkeypatch.setattr(pont, "resume_audio", long)

    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(_etape(composite, arret=arret), "x")
    assert pris.value.motif == composite.ARRETE_PAR_LE_CLIENT
    assert "Google ne sait pas interrompre" in pris.value.phrase


# --- 3. Ce qui part : le type se LIT ---------------------------------------------

def _docx() -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    return tampon.getvalue()


def test_l_envoi_lit_le_type_du_fichier(composite):
    etape = _etape(composite)
    assert composite._envoi_notebooklm(etape, _docx())["files"]["fichiers"][0] == "document.docx"
    assert composite._envoi_notebooklm(etape, "  texte  ") == {"files": {"texte": (None, "texte")}}
    assert composite._envoi_notebooklm(etape, None) == {"files": {"texte": (None, "résume")}}
    assert composite._envoi_notebooklm(etape, "é".encode()) == {"files": {"texte": (None, "é")}}
    for mauvais in (b"\xff\xfe\x00binaire", b"PK\x03\x04pas une archive\xff"):
        with pytest.raises(composite.CompositeRefuse) as pris:
            composite._envoi_notebooklm(etape, mauvais)
        assert pris.value.motif == "entree_du_mauvais_type"


def test_un_mp4_audio_n_est_plus_annonce_video(composite):
    m4a = b"\x00\x00\x00\x20ftypM4A \x00"
    isom = b"\x00\x00\x00\x20ftypisom\x00"
    assert composite.type_de_sortie(m4a) == ("audio/mp4", "sortie.m4a")
    assert composite.type_de_sortie(isom, ["audio"]) == ("audio/mp4", "sortie.m4a")
    assert composite.type_de_sortie(isom, ["video"]) == ("video/mp4", "sortie.mp4")


# --- 4. PLAN 16.2 : les fournisseurs branches, et la ligne resumee ---------------

def test_seuls_les_fournisseurs_branches_sont_nommes(composite):
    d = composite.donnees_branchees(composite.donnees_de("chat_auto"),
                                    {"gemini": False, "openrouter": True, "groq": True})
    assert d["vers"] == ["OpenRouter", "Groq"]
    assert "Google" not in d["phrase"] and "OpenRouter" in d["phrase"] and "Groq" in d["phrase"]
    un = composite.donnees_branchees(composite.donnees_de("image_lecture"),
                                     {"gemini": True, "openrouter": False, "groq": False})
    assert un["vers"] == ["Google"] and "s’il ne répond pas" not in un["phrase"]
    assert un["phrase"].startswith("Votre image part chez Google (Gemini)")


def test_etat_inconnu_ou_rien_de_branche_garde_les_trois(composite):
    entier = composite.donnees_de("chat_auto")
    assert composite.donnees_branchees(entier, None) == entier
    assert composite.donnees_branchees(entier, {"gemini": False, "openrouter": False,
                                                "groq": False}) == entier
    # Une fiche qui n'est pas une chaine de chat n'est jamais touchee.
    video = composite.donnees_de("video_rapide")
    assert composite.donnees_branchees(video, {"gemini": True}) == video


def test_le_verdict_nomme_les_branches_et_resume_en_une_ligne(composite, apps):
    chaine = composite.chaine_depuis_briques(["chat_auto", "voix_fr"], apps)
    v = composite.verifier(chaine, etat_cles=_etat(
        routeur={"gemini": False, "openrouter": True, "groq": False}))
    assert v["etapes"][0]["donnees"]["vers"] == ["OpenRouter"]
    assert v["resume"] == ("En bref : %s chez OpenRouter → %s sur votre ordinateur. "
                           "Au pire : 0,00 $." % (v["etapes"][0]["fonction"],
                                                  v["etapes"][1]["fonction"]))


def test_la_ligne_resumee_dit_l_inconnu_au_lieu_d_un_prix(composite, apps):
    chaine = composite.chaine_depuis_briques(["dialogue"], apps)
    v = composite.verifier(chaine, sonde_budget=lambda _e: None)
    assert "cout_sans_nombre" in v["motifs"], v["motifs"]
    assert "Au pire : inconnu" in v["resume"]
    assert "chez Modal" in v["resume"]


def test_la_page_montre_la_ligne_resumee(composite):
    assert "v.resume" in composite.PAGE_HTML and "echapper(v.resume)" in composite.PAGE_HTML


def test_le_verdict_du_routeur_porte_la_ligne(sandbox, monkeypatch):
    async def etat(request=None):
        return _etat(routeur={"gemini": True, "openrouter": False, "groq": False})
    monkeypatch.setattr(sandbox, "etat_des_cles", etat)
    monkeypatch.setattr(sandbox.composite, "rediger", lambda v: v["pourquoi"])
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/composite/verdict", headers=CLE, data={"phrase": "x", "briques": "chat_auto"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["resume"].startswith("En bref : ") and "chez Google" in v["resume"]
    assert v["etapes"][0]["donnees"]["vers"] == ["Google"]
    assert json.dumps(v)  # rendu tel quel a la page
