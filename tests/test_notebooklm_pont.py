"""NotebookLM par notebooklm-py (PLAN.md 17.6), sans Google.

Une FAUSSE bibliotheque `notebooklm` prend la place de la vraie dans
sys.modules : memes noms (NotebookLMClient.from_storage, notebooks, sources,
artifacts, chat, AudioFormat, AudioLength), memes attributs de statut que la
0.8.2 relue le 24/09/2026. Ce qui est verifie ici : le coffre (la session n'est
jamais en clair sur le disque), la traduction des erreurs, le parcours du
resume audio y compris le faux << removed >> du ticket #2432, les routes et
leurs refus. Ce qui ne l'est pas : le vrai NotebookLM -- voir PLAN.md 17.6.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ENTETE = {"Authorization": "Bearer cle-sandbox-de-test"}
AUTRE_SITE = {"origin": "https://exemple.com", "sec-fetch-site": "cross-site"}

ETAT = {"cookies": [{"name": "SID", "value": "valeur-sid-secrete", "domain": ".google.com", "path": "/"},
                    {"name": "__Secure-1PSIDTS", "value": "valeur-psidts-secrete",
                     "domain": ".google.com", "path": "/"}],
        "origins": [], "notebooklm": {"account": {"email": "personne@exemple.com"}}}


# --- La fausse bibliotheque ------------------------------------------------------

class Statut(types.SimpleNamespace):
    task_id = "tache-1"
    status = ""
    error = None
    is_complete = False
    is_failed = False
    is_rate_limited = False


class Scenario:
    def __init__(self):
        self.ouverture: Exception | None = None   # leve a l'ouverture du client
        self.tourner = False                      # la bibliotheque fait tourner les cookies
        self.depart = Statut(status="in_progress")
        self.fin = Statut(status="completed", is_complete=True)
        self.audios: list = []
        self.erreur_source: Exception | None = None
        self.appels: list = []
        self.chemins: list = []                   # fichiers de session vus par le client
        self.plein = False                        # create leve NotebookLimitError
        self.supprimes: list = []
        # La recherche web rapide : statut final et pages trouvees.
        self.recherche_statut = "completed"
        self.recherche_pages = [("https://fr.wikipedia.org/wiki/Phare", "Phare — Wikipédia"),
                                ("javascript:alert(1)", "Piège")]
        self.carnets = [carnet("a", "Mes notes", 2024, 3), carnet("b", "Studio · Phares · 01/09/2026 10:00", 2026, 9),
                        carnet("c", "Cours", 2025, 1)]


def carnet(ident, titre, annee, mois, proprio=True, date=True):
    import datetime as dt
    return types.SimpleNamespace(
        id=ident, title=titre, sources_count=2, is_owner=proprio,
        created_at=dt.datetime(annee, mois, 1, tzinfo=dt.timezone.utc) if date else None)


def faux_module(sc: Scenario) -> types.ModuleType:
    m = types.ModuleType("notebooklm")
    m.AudioFormat = types.SimpleNamespace(DEEP_DIVE="deep_dive", BRIEF="brief",
                                          CRITIQUE="critique", DEBATE="debate")
    m.AudioLength = types.SimpleNamespace(SHORT="short", DEFAULT="default", LONG="long")

    class Client:
        def __init__(self, path):
            self.path = Path(path)

        async def __aenter__(self):
            sc.chemins.append(self.path)
            sc.appels.append(("ouvrir", json.loads(self.path.read_text(encoding="utf-8"))))
            if sc.ouverture is not None:
                raise sc.ouverture
            if sc.tourner:
                neuf = json.loads(self.path.read_text(encoding="utf-8"))
                neuf["cookies"][1]["value"] = "valeur-psidts-tournee"
                self.path.write_text(json.dumps(neuf), encoding="utf-8")
            c = types.SimpleNamespace()

            async def lister():
                sc.appels.append(("lister",))
                return list(sc.carnets)

            async def effacer(ident):
                sc.appels.append(("supprimer", ident))
                sc.supprimes.append(ident)
                sc.carnets = [n for n in sc.carnets if n.id != ident]

            async def creer(titre):
                sc.appels.append(("creer", titre))
                if sc.plein:
                    raise erreur("NotebookLimitError", texte="Notebook quota appears to be exhausted")
                return types.SimpleNamespace(id="carnet-42")

            async def ajouter_texte(carnet, titre, contenu, wait=False, wait_timeout=None):
                sc.appels.append(("texte", carnet, titre, contenu, wait))
                if sc.erreur_source:
                    raise sc.erreur_source
                return types.SimpleNamespace(id="src-texte")

            async def ajouter_fichier(carnet, chemin, wait=False, wait_timeout=None, title=None):
                sc.appels.append(("fichier", carnet, Path(chemin).read_bytes(), title, wait))
                return types.SimpleNamespace(id="src-fichier")

            async def generer(carnet, source_ids=None, language="en", instructions=None,
                              audio_format=None, audio_length=None):
                sc.appels.append(("generer", carnet, list(source_ids), language, instructions,
                                  audio_format, audio_length))
                return sc.depart

            async def attendre(carnet, tache, timeout=None):
                sc.appels.append(("attendre", tache, timeout))
                return sc.fin

            async def lister_audio(carnet):
                sc.appels.append(("lister_audio",))
                return sc.audios

            async def rapatrier(carnet, chemin, artifact_id=None):
                sc.appels.append(("rapatrier", artifact_id))
                Path(chemin).write_bytes(b"\x00\x00\x00\x20ftypM4A  faux-audio")
                return chemin

            async def demander(carnet, question):
                sc.appels.append(("demander", carnet, question))
                return types.SimpleNamespace(answer="Il parle des phares.", references=[
                    types.SimpleNamespace(citation_number=1, cited_text="Le phare de Cordouan…")])

            async def chercher(carnet, question, source="web", mode="fast"):
                sc.appels.append(("chercher", carnet, question, source, mode))
                return types.SimpleNamespace(task_id="recherche-1")

            async def attendre_recherche(carnet, tache, timeout=None):
                sc.appels.append(("attendre_recherche", tache, timeout))
                return types.SimpleNamespace(
                    status=types.SimpleNamespace(value=sc.recherche_statut),
                    sources=tuple(types.SimpleNamespace(url=u, title=t) for u, t in sc.recherche_pages))

            async def importer(carnet, tache, pages):
                sc.appels.append(("importer", tache, [p.url for p in pages]))
                return [{"id": "web-%d" % i, "title": p.title} for i, p in enumerate(pages)]

            async def pret(carnet, ident, timeout=None):
                sc.appels.append(("pret", ident))
                if ident == "web-1":
                    raise erreur("SourceProcessingError")

            c.notebooks = types.SimpleNamespace(list=lister, create=creer, delete=effacer)
            c.sources = types.SimpleNamespace(add_text=ajouter_texte, add_file=ajouter_fichier,
                                              wait_until_ready=pret)
            c.research = types.SimpleNamespace(start=chercher, wait_for_completion=attendre_recherche,
                                               import_sources=importer)
            c.artifacts = types.SimpleNamespace(generate_audio=generer, wait_for_completion=attendre,
                                                list_audio=lister_audio, download_audio=rapatrier)
            c.chat = types.SimpleNamespace(ask=demander)
            return c

        async def __aexit__(self, *exc):
            return False

    def ouvrir(path, keepalive=None):
        sc.keepalive = keepalive
        return Client(path)

    m.NotebookLMClient = types.SimpleNamespace(from_storage=ouvrir)
    return m


def erreur(nom: str, base=Exception, texte="rien"):
    """Une erreur de la bibliotheque, reconnue par son NOM comme dans `traduire`."""
    return type(nom, (base,), {})(texte)


@pytest.fixture
def nlm(sandbox, monkeypatch, tmp_path):
    """Le pont, sur un dossier de configuration neuf et la fausse bibliotheque."""
    pont = sandbox.notebooklm_pont
    monkeypatch.setattr(pont, "DOSSIER", tmp_path / "config" / "notebooklm")
    monkeypatch.setattr(pont, "FICHIER", tmp_path / "config" / "notebooklm" / "session.coffre")
    sc = Scenario()
    monkeypatch.setitem(sys.modules, "notebooklm", faux_module(sc))
    return pont, sc


def brancher(pont):
    pont._sceller(json.dumps(ETAT))


def lancer(pont, fabrique):
    return pont.executer(fabrique)


# --- 1. La session : dans le coffre, jamais en clair ------------------------------

def test_la_session_est_fermee_dans_le_coffre_et_jamais_en_clair(nlm):
    pont, _ = nlm
    assert pont.compte() == {"branchee": False}
    brancher(pont)
    brut = pont.FICHIER.read_text(encoding="utf-8")
    assert "valeur-sid-secrete" not in brut and "SID" not in brut
    assert json.loads(pont._lire()) == ETAT
    info = pont.compte()
    assert info["branchee"] and info["cookies"] == 2 and info["compte"] == "personne@exemple.com"
    assert "valeur-sid-secrete" not in json.dumps(info)
    assert pont.oublier() is True and not pont.branchee() and pont.oublier() is False


def faux_import(sortie=0, message="", garder=lambda c: c["domain"].endswith("google.com")):
    """`notebooklm auth import-cookies` : lit l'export, ecrit le storage_state
    sous NOTEBOOKLM_HOME. Rend aussi ce qu'il a vu."""
    vu = {}

    def run(argv, capture_output, text, env, timeout):
        vu.update(argv=list(argv), home=env["NOTEBOOKLM_HOME"], export=Path(argv[3]))
        if not sortie:
            cookies = [c for c in json.loads(Path(argv[3]).read_text(encoding="utf-8")) if garder(c)]
            cible = Path(env["NOTEBOOKLM_HOME"]) / "profiles" / "default" / "storage_state.json"
            cible.parent.mkdir(parents=True)
            cible.write_text(json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8")
        return types.SimpleNamespace(returncode=sortie, stdout="", stderr=message)
    return run, vu


EXPORT = json.dumps([
    {"domain": ".google.com", "name": "SID", "value": "valeur-sid-secrete", "path": "/"},
    {"domain": ".google.com", "name": "__Secure-1PSIDTS", "value": "valeur-psidts-secrete", "path": "/"},
    {"domain": ".exemple.com", "name": "PISTEUR", "value": "x", "path": "/"},
])


def test_l_export_passe_par_la_commande_de_la_bibliotheque_puis_le_dossier_part(nlm, monkeypatch):
    pont, _ = nlm
    run, vu = faux_import()
    monkeypatch.setattr(pont.subprocess, "run", run)
    assert pont.enregistrer(EXPORT) == {"cookies": 2}
    assert vu["argv"][:3] == ["notebooklm", "auth", "import-cookies"]
    # Le dossier temporaire -- export en clair compris -- n'existe plus.
    assert not vu["export"].exists() and not Path(vu["home"]).exists()
    assert "PISTEUR" not in pont._lire() and "valeur-sid-secrete" in pont._lire()
    assert "valeur-sid-secrete" not in pont.FICHIER.read_text(encoding="utf-8")


# --- 1 bis. L'entretien : la session reste vivante sans reconnexion ---------------

def faux_refresh(sortie=0, message="", tourner=True):
    """`notebooklm --storage F auth refresh --verify --quiet` : fait tourner
    __Secure-1PSIDTS dans F, comme la bibliotheque. Rend ce qu'il a vu."""
    vu = {}

    def run(argv, capture_output, text, env, timeout):
        vu.update(argv=list(argv), fichier=Path(argv[2]), clair=Path(argv[2]).read_text(encoding="utf-8"))
        if tourner:
            neuf = json.loads(vu["clair"])
            neuf["cookies"][1]["value"] = "valeur-psidts-entretenue"
            Path(argv[2]).write_text(json.dumps(neuf), encoding="utf-8")
        return types.SimpleNamespace(returncode=sortie, stdout="", stderr=message)
    return run, vu


def test_l_entretien_fait_tourner_la_session_et_la_referme_dans_le_coffre(nlm, monkeypatch, caplog):
    pont, _ = nlm
    brancher(pont)
    run, vu = faux_refresh()
    monkeypatch.setattr(pont.subprocess, "run", run)
    with caplog.at_level("INFO", logger="sandbox-manager.notebooklm"):
        r = pont.entretenir()
    assert r["fait"] and r["ok"]
    assert vu["argv"] == ["notebooklm", "--storage", str(vu["fichier"]), "auth", "refresh",
                          "--verify", "--quiet"]
    # La copie en clair n'a vecu que le temps de l'appel ; le coffre a la neuve.
    assert not vu["fichier"].exists() and not vu["fichier"].parent.exists()
    assert "valeur-psidts-entretenue" in pont._lire()
    # Le journal dit QUEL cookie a tourne, jamais sa valeur.
    assert "tournes : __Secure-1PSIDTS" in caplog.text
    assert "valeur-" not in caplog.text


def test_un_entretien_echoue_se_journalise_et_garde_quand_meme_la_rotation(nlm, monkeypatch, caplog):
    pont, _ = nlm
    brancher(pont)
    run, _vu = faux_refresh(sortie=1, message="Error: Authentication expired")
    monkeypatch.setattr(pont.subprocess, "run", run)
    with caplog.at_level("INFO", logger="sandbox-manager.notebooklm"):
        r = pont.entretenir()
    assert r["fait"] and not r["ok"]
    assert "valeur-psidts-entretenue" in pont._lire()
    assert "ECHEC (code 1) Error: Authentication expired" in caplog.text and "valeur-" not in caplog.text


def test_sans_session_l_entretien_ne_lance_rien(nlm, monkeypatch):
    pont, _ = nlm
    monkeypatch.setattr(pont.subprocess, "run", lambda *a, **k: pytest.fail("rien a entretenir"))
    assert pont.entretenir() == {"fait": False}


def test_le_fil_d_entretien_survit_a_une_erreur_et_attend_entre_deux(nlm, monkeypatch):
    pont, _ = nlm
    tours, attentes = [], []

    def entretenir():
        tours.append(1)
        if len(tours) == 1:
            raise RuntimeError("panne")

    class Fin(Exception):
        pass

    def attente(s):
        attentes.append(s)
        if len(attentes) == 2:
            raise Fin
    monkeypatch.setattr(pont, "entretenir", entretenir)
    with pytest.raises(Fin):
        pont.entretenir_sans_fin(attente)
    assert len(tours) == 2 and attentes == [pont.ENTRETIEN_S] * 2
    assert 900 <= pont.ENTRETIEN_S <= 1200   # 15 a 20 min, conseil de la bibliotheque


def test_les_changements_disent_des_noms_et_les_doublons_jamais_une_valeur(nlm):
    pont, _ = nlm
    apres = json.loads(json.dumps(ETAT))
    apres["cookies"][1]["value"] = "valeur-neuve"
    apres["cookies"].append({"name": "__Secure-1PSIDTS", "value": "valeur-vieille",
                             "domain": "accounts.google.com", "path": "/"})
    d = pont.changements(json.dumps(ETAT), json.dumps(apres))
    assert d.startswith("2 -> 3 cookies ; tournes : __Secure-1PSIDTS ;")
    assert "ajoutes : __Secure-1PSIDTS@accounts.google.com" in d
    assert d.endswith("doublons : __Secure-1PSIDTS") and "valeur" not in d
    assert pont.changements("pas du json", "{}") == "session illisible"


def test_le_client_tourne_seul_pendant_un_appel_long_et_le_journalise(nlm, caplog):
    pont, sc = nlm
    brancher(pont)
    sc.tourner = True
    with caplog.at_level("INFO", logger="sandbox-manager.notebooklm"):
        lancer(pont, pont.verifier)
    assert sc.keepalive == pont.ENTRETIEN_CLIENT_S
    assert "NotebookLM appel : 2 -> 2 cookies ; tournes : __Secure-1PSIDTS" in caplog.text
    assert "valeur-" not in caplog.text


@pytest.mark.parametrize("export, attendu", [
    ("", "Collez l’export"),
    ("pas du json", "pas un export JSON"),
])
def test_un_export_vide_ou_illisible_est_refuse_sans_rien_lancer(nlm, monkeypatch, export, attendu):
    pont, _ = nlm
    monkeypatch.setattr(pont.subprocess, "run", lambda *a, **k: pytest.fail("lance a tort"))
    with pytest.raises(ValueError, match=attendu):
        pont.enregistrer(export)
    assert not pont.branchee()


def test_un_export_refuse_par_la_bibliotheque_dit_pourquoi_et_ne_ferme_rien(nlm, monkeypatch):
    pont, _ = nlm
    run, vu = faux_import(sortie=1, message="Error: Missing required cookies: SID\n")
    monkeypatch.setattr(pont.subprocess, "run", run)
    with pytest.raises(ValueError, match="Export refusé : Error: Missing required cookies: SID"):
        pont.enregistrer(EXPORT)
    assert not pont.branchee() and not vu["export"].exists()


def _commande_reelle():
    return os.getenv("NOTEBOOKLM_CLI") or shutil.which("notebooklm")


@pytest.mark.skipif(not _commande_reelle(), reason="notebooklm-py absent de cet environnement")
def test_la_vraie_commande_d_import_garde_les_cookies_google_seulement(nlm):
    """La commande PUBLIE de la bibliotheque, hors reseau, sur des cookies faux."""
    pont, _ = nlm
    export = json.dumps([
        {"domain": ".google.com", "name": "SID", "value": "faux-sid", "path": "/",
         "expirationDate": 1893456000, "secure": False, "httpOnly": False},
        {"domain": ".google.com", "name": "__Secure-1PSIDTS", "value": "faux-psidts", "path": "/",
         "expirationDate": 1893456000, "secure": True, "httpOnly": True},
        {"domain": ".exemple.com", "name": "PISTEUR", "value": "x", "path": "/"},
    ])
    assert pont.enregistrer(export, commande=_commande_reelle()) == {"cookies": 2}
    assert "PISTEUR" not in pont._lire()


# --- 2. Les erreurs, dites a la personne ---------------------------------------

@pytest.mark.parametrize("exc, classe, morceau", [
    (erreur("AuthError"), "SessionExpiree", "a expiré"),
    (erreur("_LoginRedirectError", ValueError,
            "Authentication expired or invalid. Redirected to: https://accounts.google.com/"),
     "SessionExpiree", "a expiré"),
    (erreur("RateLimitError"), "QuotaAtteint", "3 résumés audio par jour"),
    (erreur("NotebookLimitError"), "CarnetsPleins", "Votre NotebookLM est plein"),
    (erreur("SourceProcessingError", texte="PDF chiffre"), "NotebookLMEchec", "PDF chiffre"),
    (erreur("WaitTimeoutError"), "NotebookLMEchec", "pas fini à temps"),
    (erreur("UnknownRPCMethodError"), "NotebookLMEchec", "mettre le Studio à jour"),
    (RuntimeError("boum"), "NotebookLMEchec", "RuntimeError: boum"),
])
def test_chaque_erreur_de_la_bibliotheque_a_sa_phrase(nlm, exc, classe, morceau):
    pont, _ = nlm
    dite = pont.traduire(exc)
    assert type(dite).__name__ == classe and morceau in str(dite)


def test_une_ValueError_ordinaire_n_est_pas_une_session_expiree(nlm):
    pont, _ = nlm
    assert isinstance(pont.traduire(ValueError("mauvais argument")), pont.NotebookLMEchec)


def test_sans_session_rien_ne_part_chez_google(nlm):
    pont, sc = nlm
    with pytest.raises(pont.SessionAbsente):
        lancer(pont, pont.verifier)
    assert sc.appels == []


def test_une_session_morte_se_dit_expiree(nlm):
    pont, sc = nlm
    brancher(pont)
    sc.ouverture = erreur("_LoginRedirectError", ValueError, "Authentication expired or invalid.")
    with pytest.raises(pont.SessionExpiree):
        lancer(pont, pont.verifier)
    assert pont.branchee(), "une session refusee reste la ; la personne choisit d'oublier"


def test_sans_la_bibliotheque_le_studio_dit_de_reconstruire(nlm, monkeypatch):
    pont, _ = nlm
    brancher(pont)
    monkeypatch.setitem(sys.modules, "notebooklm", None)   # import -> ImportError
    with pytest.raises(pont.NotebookLMEchec, match="demarrer.cmd"):
        lancer(pont, pont.verifier)


# --- 3. Le client : fichier temporaire, cookies tournes refermes -------------------

def test_le_fichier_de_session_en_clair_ne_survit_pas_a_l_appel(nlm):
    pont, sc = nlm
    brancher(pont)
    assert lancer(pont, pont.verifier) == {"ok": True, "carnets": 3}
    assert sc.chemins and not sc.chemins[0].exists() and not sc.chemins[0].parent.exists()


def test_les_cookies_tournes_par_la_bibliotheque_sont_refermes_dans_le_coffre(nlm):
    pont, sc = nlm
    brancher(pont)
    sc.tourner = True
    lancer(pont, pont.verifier)
    assert "valeur-psidts-tournee" in pont._lire()
    assert "valeur-psidts-tournee" not in pont.FICHIER.read_text(encoding="utf-8")


# --- 4. Le resume audio ------------------------------------------------------------

def _resume(pont, tmp_path, sources=None, **reglages):
    etapes = []
    r = lancer(pont, lambda: pont.resume_audio(
        sources if sources is not None else [{"titre": "Notes", "texte": "Les phares de France."}],
        tmp_path / "sortie", progres=etapes.append, **reglages))
    return r, etapes


def test_le_resume_fabrique_un_carnet_en_francais_et_rapporte_l_audio(nlm, tmp_path):
    pont, sc = nlm
    brancher(pont)
    doc = tmp_path / "cours.pdf"
    doc.write_bytes(b"%PDF-1.4 faux")
    r, etapes = _resume(pont, tmp_path, [{"chemin": str(doc), "titre": "cours.pdf"},
                                         {"titre": "Notes", "texte": "Les phares."}],
                        titre="Phares", consigne="pour des lyceens", format_="debat", longueur="court")
    assert r["carnet_id"] == "carnet-42" and r["sources"] == 2
    assert r["carnet_url"] == "https://notebook.google.com/notebook/carnet-42"
    assert r["audio"].read_bytes().startswith(b"\x00\x00\x00\x20ftyp")
    noms = [a[0] for a in sc.appels]
    assert noms == ["ouvrir", "creer", "fichier", "texte", "generer", "attendre", "rapatrier"]
    creer, fichier, _, generer, attendre = (sc.appels[i] for i in range(1, 6))
    assert creer[1] == "Studio · Phares"
    assert fichier[2] == b"%PDF-1.4 faux" and fichier[3] == "cours.pdf" and fichier[4] is True
    assert generer[2:] == (["src-fichier", "src-texte"], "fr", "pour des lyceens", "debate", "short")
    assert attendre[2] == pont.AUDIO_DELAI_S == 1200
    assert etapes[0].startswith("Création du carnet") and any("5 à 10 minutes" in e for e in etapes)


def test_une_forme_inconnue_retombe_sur_la_discussion_approfondie(nlm, tmp_path):
    pont, sc = nlm
    brancher(pont)
    _resume(pont, tmp_path, format_="n-importe", longueur="??")
    generer = next(a for a in sc.appels if a[0] == "generer")
    assert generer[5:] == ("deep_dive", "default") and generer[4] is None


def test_un_resume_fini_mais_dit_removed_est_rapatrie_ticket_2432(nlm, tmp_path):
    pont, sc = nlm
    brancher(pont)
    sc.fin = Statut(status="removed")
    sc.audios = [types.SimpleNamespace(id="audio-ancien", is_completed=True),
                 types.SimpleNamespace(id="audio-9", is_completed=True)]
    r, _ = _resume(pont, tmp_path)
    assert r["audio"].exists()
    assert ("rapatrier", "audio-9") in sc.appels


def test_removed_sans_audio_pret_est_un_echec_dit(nlm, tmp_path):
    pont, sc = nlm
    brancher(pont)
    sc.fin = Statut(status="failed", error="Generation failed")
    sc.audios = [types.SimpleNamespace(id="x", is_completed=False)]
    with pytest.raises(pont.NotebookLMEchec, match="Generation failed"):
        _resume(pont, tmp_path)
    assert not any(a[0] == "rapatrier" for a in sc.appels)


def test_le_quota_au_depart_se_dit_et_rien_n_est_attendu(nlm, tmp_path):
    pont, sc = nlm
    brancher(pont)
    sc.depart = Statut(is_rate_limited=True, is_failed=True)
    with pytest.raises(pont.QuotaAtteint, match="Réessayez demain"):
        _resume(pont, tmp_path)
    assert not any(a[0] == "attendre" for a in sc.appels)


def test_un_document_illisible_pour_notebooklm_se_dit(nlm, tmp_path):
    pont, sc = nlm
    brancher(pont)
    sc.erreur_source = erreur("SourceProcessingError", texte="source en echec")
    with pytest.raises(pont.NotebookLMEchec, match="n’a pas su lire un des documents"):
        _resume(pont, tmp_path)


def test_une_question_rend_la_reponse_et_ses_citations(nlm):
    pont, sc = nlm
    brancher(pont)
    r = lancer(pont, lambda: pont.demander("carnet-42", "De quoi parle-t-il ?"))
    assert r == {"reponse": "Il parle des phares.",
                 "citations": [{"numero": 1, "extrait": "Le phare de Cordouan…"}],
                 "web": [], "note": ""}
    assert not [a for a in sc.appels if a[0] in ("chercher", "importer")]


def test_avec_le_web_la_recherche_rapide_ajoute_les_pages_avant_la_question(nlm):
    pont, sc = nlm
    brancher(pont)
    r = lancer(pont, lambda: pont.demander("carnet-42", "Quand fut-il allumé ?", web=True))
    noms = [a[0] for a in sc.appels]
    # Chercher, attendre, importer, attendre chaque page, PUIS demander.
    assert noms[1:] == ["chercher", "attendre_recherche", "importer", "pret", "pret", "demander"]
    assert sc.appels[1] == ("chercher", "carnet-42", "Quand fut-il allumé ?", "web", "fast")
    assert sc.appels[2][2] == pont.RECHERCHE_DELAI_S
    # Une page illisible (web-1) n'empeche pas la reponse.
    assert r["reponse"] == "Il parle des phares." and r["note"] == ""
    assert r["web"][0] == {"titre": "Phare — Wikipédia", "url": "https://fr.wikipedia.org/wiki/Phare"}


def test_avec_le_web_au_plus_dix_pages_et_rien_trouve_se_dit(nlm):
    pont, sc = nlm
    brancher(pont)
    sc.recherche_pages = [("https://exemple.org/%d" % i, "Page %d" % i) for i in range(14)] + [("", "Sans adresse")]
    r = lancer(pont, lambda: pont.demander("carnet-42", "Q", web=True))
    assert len(r["web"]) == pont.RECHERCHE_MAX == 10
    importe = [a for a in sc.appels if a[0] == "importer"][0][2]
    assert len(importe) == 10 and "" not in importe
    sc.appels.clear()
    sc.recherche_statut = "failed"
    r = lancer(pont, lambda: pont.demander("carnet-42", "Q", web=True))
    assert r["web"] == [] and "rien trouvé" in r["note"] and r["reponse"]
    assert "importer" not in [a[0] for a in sc.appels]


def test_une_recherche_web_en_panne_est_dite(nlm):
    pont, _ = nlm
    e = pont.traduire(erreur("ResearchTimeoutError"))
    assert isinstance(e, pont.NotebookLMEchec) and "décochez" in str(e)


# --- 5. Les routes ---------------------------------------------------------------

@pytest.fixture
def client(sandbox, nlm):
    from fastapi.testclient import TestClient
    return TestClient(sandbox.app, base_url="http://localhost"), nlm[0], nlm[1]


def test_l_etat_contre_la_cle_seulement_puis_la_verification(client):
    c, pont, sc = client
    assert c.get("/notebooklm/etat").status_code == 401
    assert c.get("/notebooklm/etat?verifier=1", headers=ENTETE).json() == {"branchee": False, "coupe": None}
    brancher(pont)
    e = c.get("/notebooklm/etat?verifier=1", headers=ENTETE).json()
    assert e["branchee"] and e["ok"] and e["carnets"] == 3 and e["compte"] == "personne@exemple.com"
    sc.ouverture = erreur("AuthError")
    e = c.get("/notebooklm/etat?verifier=1", headers=ENTETE).json()
    assert e["ok"] is False and "a expiré" in e["message"]
    assert "valeur-sid-secrete" not in json.dumps(e)


def test_brancher_ferme_l_export_l_essaie_et_ne_le_renvoie_pas(client, monkeypatch):
    c, pont, _ = client
    run, _ = faux_import()
    monkeypatch.setattr(pont.subprocess, "run", run)
    r = c.post("/notebooklm/session", headers=ENTETE, json={"export": EXPORT})
    assert r.status_code == 200
    assert r.json() == {"enregistree": True, "cookies": 2, "ok": True, "carnets": 3}
    assert "valeur" not in r.text
    r = c.post("/notebooklm/session", headers=ENTETE, json={"export": "pas du json"})
    assert r.status_code == 400 and "pas un export JSON" in r.json()["detail"]


def test_brancher_une_session_que_google_refuse_la_garde_et_le_dit(client, monkeypatch):
    c, pont, sc = client
    run, _ = faux_import()
    monkeypatch.setattr(pont.subprocess, "run", run)
    sc.ouverture = erreur("_LoginRedirectError", ValueError, "Authentication expired or invalid.")
    d = c.post("/notebooklm/session", headers=ENTETE, json={"export": EXPORT}).json()
    assert d["enregistree"] and d["ok"] is False and "a expiré" in d["message"]


def test_un_autre_site_ne_peut_ni_brancher_ni_lancer_ni_oublier(client):
    c, pont, _ = client
    brancher(pont)
    h = dict(ENTETE, **AUTRE_SITE)
    assert c.post("/notebooklm/session", headers=h, json={"export": EXPORT}).status_code == 403
    assert c.post("/notebooklm/resume", headers=h, data={"texte": "x"}).status_code == 403
    assert c.post("/notebooklm/demander", headers=h,
                  json={"carnet_id": "c", "question": "q"}).status_code == 403
    assert c.post("/notebooklm/oublier", headers=h).status_code == 403
    assert pont.branchee()


def test_en_studio_partage_tout_est_coupe(sandbox, nlm):
    from fastapi.testclient import TestClient
    pont, _ = nlm
    brancher(pont)
    c = TestClient(sandbox.app, base_url="http://192.168.1.20")
    assert c.get("/notebooklm/etat", headers=ENTETE).json()["coupe"]
    r = c.post("/notebooklm/resume", headers=ENTETE, data={"texte": "x"})
    assert r.status_code == 403 and "une seule personne" in r.json()["detail"]
    assert c.post("/notebooklm/demander", headers=ENTETE,
                  json={"carnet_id": "c", "question": "q"}).status_code == 403


def test_resumer_sans_session_ou_sans_document_ou_avec_un_mauvais_fichier(client):
    c, pont, _ = client
    r = c.post("/notebooklm/resume", headers=ENTETE, data={"texte": "x"})
    assert r.status_code == 409 and "pas encore branché" in r.json()["detail"]
    brancher(pont)
    assert c.post("/notebooklm/resume", headers=ENTETE, data={"texte": "  "}).status_code == 400
    r = c.post("/notebooklm/resume", headers=ENTETE,
               files={"fichiers": ("virus.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400 and "PDF, .txt, .md ou .docx" in r.json()["detail"]


def _attendre_fin(c, jid, delai=20.0):
    fin = time.time() + delai
    while time.time() < fin:
        j = c.get("/notebooklm/jobs/" + jid, headers=ENTETE).json()
        if j["status"] in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    pytest.fail("le travail NotebookLM ne finit pas")


def test_un_resume_complet_par_la_page_puis_l_audio_par_son_jeton(client):
    c, pont, sc = client
    brancher(pont)
    r = c.post("/notebooklm/resume", headers=ENTETE,
               data={"texte": "Les phares de France.", "format": "bref", "longueur": "long"},
               files={"fichiers": ("cours.md", b"# Cours", "text/markdown")})
    assert r.status_code == 200, r.text
    j = _attendre_fin(c, r.json()["id"])
    assert j["status"] == "succeeded", j
    assert j["carnet_id"] == "carnet-42" and j["carnet_url"].endswith("/notebook/carnet-42")
    generer = next(a for a in sc.appels if a[0] == "generer")
    assert generer[3] == "fr" and generer[5:] == ("brief", "long")
    son = c.get(j["audio_url"])
    assert son.status_code == 200 and son.headers["content-type"] == "audio/mp4"
    assert son.content.startswith(b"\x00\x00\x00\x20ftyp")
    assert "cle-sandbox-de-test" not in j["audio_url"]
    faux = j["audio_url"].split("cle=")[0] + "cle=faux"
    assert c.get(faux).status_code == 401
    assert c.get(j["audio_url"] + "&telecharger=1").headers["content-disposition"].startswith("attachment")


def test_la_version_opus_de_repli_passe_par_le_meme_jeton(client, monkeypatch, tmp_path):
    """Repli pour un navigateur sans AAC (la piste VS Code du 25/09 a ete
    dementie : « Go Live »). La route rend la meme chose en Opus, meme jeton."""
    c, pont, _ = client
    brancher(pont)
    j = _attendre_fin(c, c.post("/notebooklm/resume", headers=ENTETE, data={"texte": "x"}).json()["id"])
    vus = []

    def faux_opus(m4a):
        vus.append(m4a)
        o = tmp_path / "resume.opus"
        o.write_bytes(b"OggS" + b"\x00" * 60)
        return o
    monkeypatch.setattr(pont, "version_opus", faux_opus)
    son = c.get(j["audio_url"] + "&format=opus")
    assert son.status_code == 200 and son.headers["content-type"] == "audio/ogg"
    assert son.content.startswith(b"OggS") and vus[0].name.endswith("resume-notebooklm.m4a")
    assert c.get(j["audio_url"].split("cle=")[0] + "cle=faux&format=opus").status_code == 401
    monkeypatch.setattr(pont, "version_opus", lambda m4a: None)
    assert c.get(j["audio_url"] + "&format=opus").status_code == 404
    # Sans le paramètre, rien ne change : l'AAC d'origine.
    assert c.get(j["audio_url"]).headers["content-type"] == "audio/mp4"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_version_opus_vraie_conversion_gardee_ensuite(nlm, tmp_path):
    import subprocess
    pont, _ = nlm
    m4a = tmp_path / "resume-notebooklm.m4a"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-c:a", "aac", str(m4a)], check=True)
    opus = pont.version_opus(m4a)
    assert opus == m4a.with_suffix(".opus")
    tete = opus.read_bytes()[:64]
    assert tete.startswith(b"OggS") and b"OpusHead" in tete
    avant = opus.stat().st_mtime_ns
    assert pont.version_opus(m4a) == opus and opus.stat().st_mtime_ns == avant
    assert not list(tmp_path.glob("*.partiel"))


def test_version_opus_sans_ffmpeg_ou_sur_un_faux_fichier_rend_none(nlm, tmp_path):
    pont, _ = nlm
    m4a = tmp_path / "resume-notebooklm.m4a"
    m4a.write_bytes(b"pas de l'audio")
    assert pont.version_opus(m4a, commande="ffmpeg-introuvable-xyz") is None
    if shutil.which("ffmpeg"):
        assert pont.version_opus(m4a) is None
    assert not list(tmp_path.glob("*.opus*"))


def test_les_resumes_faits_restent_ecoutables_apres_un_rechargement(client, sandbox):
    """25/09 : « toujours pas de son ». Un resume lance hors de la page, ou
    avant un rechargement, doit s'y retrouver avec son lecteur."""
    c, pont, _ = client
    brancher(pont)
    assert c.get("/notebooklm/resumes").status_code == 401
    sandbox.write_job("pas-nlm", {"id": "pas-nlm", "provider": "modal", "status": "succeeded", "artifacts": []})
    j = _attendre_fin(c, c.post("/notebooklm/resume", headers=ENTETE,
                                data={"texte": "Les phares.", "titre": "Phares"}).json()["id"])
    liste = c.get("/notebooklm/resumes", headers=ENTETE).json()["resumes"]
    # Le dossier des travaux est commun a la suite : les resumes des tests
    # d'avant y sont aussi. Le plus recent passe devant, et aucun autre travail.
    assert liste[0]["id"] == j["id"] and "pas-nlm" not in [r["id"] for r in liste]
    assert liste[0]["titre"] == "Phares" and liste[0]["carnet_url"].endswith("carnet-42")
    son = c.get(liste[0]["audio_url"])
    assert son.status_code == 200 and son.content.startswith(b"\x00\x00\x00\x20ftyp")


def test_un_resume_qui_echoue_chez_google_finit_en_echec_dit(client):
    c, pont, sc = client
    brancher(pont)
    sc.depart = Statut(is_rate_limited=True)
    r = c.post("/notebooklm/resume", headers=ENTETE, data={"texte": "x"})
    j = _attendre_fin(c, r.json()["id"])
    assert j["status"] == "failed" and "Réessayez demain" in j["message"]
    assert "audio_url" not in j


def test_la_fiche_d_un_autre_travail_n_est_pas_lue_ici(client, sandbox):
    c, _, _ = client
    jid = "autre-travail"
    sandbox.write_job(jid, {"id": jid, "provider": "modal", "status": "succeeded", "artifacts": []})
    assert c.get("/notebooklm/jobs/" + jid, headers=ENTETE).status_code == 404


def test_poser_une_question_et_la_refuser_vide(client):
    c, pont, _ = client
    brancher(pont)
    r = c.post("/notebooklm/demander", headers=ENTETE, json={"carnet_id": "carnet-42", "question": "Quoi ?"})
    assert r.status_code == 200 and r.json()["reponse"] == "Il parle des phares."
    assert r.json()["web"] == []
    r = c.post("/notebooklm/demander", headers=ENTETE,
               json={"carnet_id": "carnet-42", "question": "Quoi ?", "web": True})
    assert r.status_code == 200 and r.json()["web"][0]["url"].startswith("https://")
    # La page : la case, et seules les adresses http(s) deviennent des liens.
    html = c.get("/notebooklm").text
    assert 'id="web"' in html and "elles y restent" in html
    assert "web: web" in html and "/^https?:\\/\\//i.test(s.url)" in html
    assert c.post("/notebooklm/demander", headers=ENTETE,
                  json={"carnet_id": "carnet-42", "question": " "}).status_code == 400


def test_reparer_depuis_le_coffre_sans_reconnexion(client, monkeypatch):
    c, pont, _ = client
    r = c.post("/notebooklm/reparer", headers=ENTETE)
    assert r.status_code == 409 and "pas encore branché" in r.json()["detail"]
    brancher(pont)
    run, vu = faux_refresh()
    monkeypatch.setattr(pont.subprocess, "run", run)
    assert c.post("/notebooklm/reparer", headers=ENTETE).json() == {"ok": True}
    assert vu["argv"][3:5] == ["auth", "refresh"] and "valeur-psidts-entretenue" in pont._lire()
    run, _vu = faux_refresh(sortie=1, tourner=False)
    monkeypatch.setattr(pont.subprocess, "run", run)
    d = c.post("/notebooklm/reparer", headers=ENTETE).json()
    assert d["ok"] is False and "brancher-notebooklm.cmd" in d["message"]
    assert c.post("/notebooklm/reparer", headers=dict(ENTETE, **AUTRE_SITE)).status_code == 403
    assert c.post("/notebooklm/reparer").status_code == 401


def test_la_page_montre_reparer_seulement_si_le_coffre_a_une_session_refusee(client):
    c, _pont, _ = client
    html = c.get("/notebooklm").text
    assert '<div id="reparer" class="carte" hidden>' in html
    assert 'el("reparer").hidden = !(e.branchee && !e.ok);' in html
    assert 'fetch("/notebooklm/reparer", {method: "POST", headers: H})' in html


def _rendre_markdown(pont, texte: str, tmp_path) -> str:
    """markdown() de la page, sous node, sur un faux DOM qui se relit en HTML."""
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = pont.PAGE_HTML
    code = page[page.index("const SYMBOLES = "):page.index("// Après brancher-notebooklm.cmd")]
    programme = r"""
function esc(t){ return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function noeud(tag){ return {tagName: tag.toUpperCase(), enfants: [], _t: "",
  set textContent(v){ this._t = String(v); this.enfants = []; },
  appendChild(n){ this.enfants.push(n); return n; },
  html(){ if(this.tagName === "BR") return "<br>";
    const t = this.tagName.toLowerCase();
    return "<" + t + ">" + esc(this._t) + this.enfants.map(e => e.html()).join("") + "</" + t + ">"; }}; }
const document = {createElement: noeud,
  createTextNode: t => ({html: () => esc(String(t))})};
""" + code + """
const div = noeud("div");
markdown(div, %s);
console.log(div.enfants.map(e => e.html()).join(""));
""" % json.dumps(texte)
    fichier = tmp_path / "markdown.js"
    fichier.write_text(programme, encoding="utf-8")
    fait = subprocess.run(["node", str(fichier)], capture_output=True, text=True,
                          encoding="utf-8", timeout=20)
    assert fait.returncode == 0, fait.stderr
    return fait.stdout.strip()


def test_la_reponse_markdown_devient_titres_listes_et_gras(nlm, tmp_path):
    pont, _ = nlm
    html = _rendre_markdown(pont, "## Le phare\n\nIl fut **allumé** en *1611* [1].\nSuite.\n\n"
                                  "* premier\n* second `code`\n\n1. un\n2. deux", tmp_path)
    assert html == ("<h4>Le phare</h4><p>Il fut <strong>allumé</strong> en <em>1611</em> [1]."
                    "<br>Suite.</p><ul><li>premier</li><li>second <code>code</code></li></ul>"
                    "<ol><li>un</li><li>deux</li></ol>")


def test_les_formules_latex_deviennent_indices_exposants_et_symboles(nlm, tmp_path):
    pont, _ = nlm
    # Vu en reel le 25/09 : « \(H_2S\) » affiche brut dans une reponse.
    html = _rendre_markdown(pont, r"Le \(H_2S\;\) se dissocie : \(H_{2}S \rightarrow H_2 + S\), "
                                  r"à \(10^{-3}\,\text{mbar}\) et \[\Delta H \approx 20\]", tmp_path)
    assert html == ("<p>Le <span>H<sub>2</sub>S </span> se dissocie : "
                    "<span>H<sub>2</sub>S → H<sub>2</sub> + S</span>, à "
                    "<span>10<sup>-3</sup> mbar</span> et <span>Δ H ≈ 20</span></p>")
    # Double barre oblique (reponse echappee une fois de trop) : meme rendu.
    assert _rendre_markdown(pont, r"\\(H_2S\\)", tmp_path) == "<p><span>H<sub>2</sub>S</span></p>"
    # Une formule ne laisse pas passer de HTML non plus.
    assert "<img" not in _rendre_markdown(pont, r"\(<img src=x onerror=alert(1)>_2\)", tmp_path)


def test_la_reponse_markdown_n_injecte_jamais_de_html(nlm, tmp_path):
    pont, _ = nlm
    html = _rendre_markdown(pont, '<img src=x onerror=alert(1)> **<b>gras</b>**', tmp_path)
    assert "<img" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<strong>&lt;b&gt;gras&lt;/b&gt;</strong>" in html
    # Et la page n'utilise innerHTML nulle part.
    assert "innerHTML" not in pont.PAGE_HTML


def test_oublier_efface_la_session(client):
    c, pont, _ = client
    brancher(pont)
    assert c.post("/notebooklm/oublier", headers=ENTETE).json() == {"oubliee": True}
    assert not pont.branchee()


def test_la_page_avertit_avant_de_brancher_et_porte_la_cle(client):
    c, pont, _ = client
    html = c.get("/notebooklm").text
    assert "__CLE__" not in html and '"cle-sandbox-de-test"' in html
    for morceau in ("ouvre votre compte Google entier", "navigation privée",
                    "sans vous déconnecter", "Vos documents partent chez Google (NotebookLM)",
                    "notebooklm-py 0.8.2", "Oublier la session NotebookLM"):
        assert morceau in html, morceau
    # Un message venu de Google ne s'ecrit jamais en HTML dans la page.
    assert "innerHTML" not in html
    for morceau in ("Faire de la place dans NotebookLM", "La suppression est <b>définitive</b>",
                    "Je comprends que c’est définitif.", "commence par « Studio · »"):
        assert morceau in html, morceau
    # « Vos résumés » : la durée s'affiche d'emblée ; avec preload « none » le
    # lecteur montrait 0:00 et le propriétaire a lu le résumé comme vide (25/09).
    assert 'a.preload = "metadata"' in html and 'preload = "none"' not in html
    # Repli : chaque lecteur porte aussi la source Opus.
    assert '"&format=opus", \'audio/ogg; codecs="opus"\'' in html
    assert html.count("brancherSon(") == 3
    # 25/09 : « on devrait pouvoir supprimer les résumés audio ». Deux clics ;
    # le carnet chez Google reste, « Faire de la place » le supprime.
    # Session expirée en réel le 25/09 : la page cachait alors les résumés, que
    # le Studio garde sur son disque. Ils sont hors du bloc « travail ».
    travail = html.split('<div id="travail"')[1].split('<div id="historique">')[0]
    assert 'id="resumes"' not in travail and 'id="resumes"' in html.split('<div id="historique">')[1]
    assert "if(e.branchee && e.ok){ listerResumes(); }" not in html
    assert "brancher-notebooklm.cmd" in pont.PHRASE_EXPIREE
    for morceau in ("🗑️ Supprimer du Studio", "Confirmer : effacer pour de bon",
                    '"/notebooklm/jobs/" + encodeURIComponent(j.id), {method: "DELETE"'):
        assert morceau in html, morceau
    # « pas clair » (25/09) : le chemin premier est un double-clic, l'extension
    # de cookies passe en repli replié.
    assert "brancher-notebooklm.cmd" in html and "J’ai fini, vérifier" in html
    assert html.index("brancher-notebooklm.cmd") < html.index("<details>") < html.index("Cookie-Editor")


def test_le_brancheur_suit_l_epingle_ne_montre_pas_la_cle_et_efface_tout():
    racine = Path(__file__).resolve().parents[1]
    ps1 = (racine / "scripts" / "brancher-notebooklm.ps1").read_text(encoding="utf-8")
    cmd = (racine / "brancher-notebooklm.cmd").read_text(encoding="utf-8")
    assert r"scripts\brancher-notebooklm.ps1" in cmd
    # Une seule vérité pour la version : l'épingle du Studio, relue par le script.
    epingle = re.search(r"^notebooklm-py==(\S+)", (racine / "sandbox-manager" / "requirements.txt")
                        .read_text(encoding="utf-8"), re.M)
    assert epingle and '"^notebooklm-py==(\\S+)"' in ps1
    assert not re.search(r"notebooklm-py\S*==\d", ps1) and epingle.group(1) not in ps1
    # La clé ne s'écrit nulle part, la session non plus.
    for ligne in ps1.splitlines():
        if "Write-Host" in ligne:
            assert "$cle" not in ligne and "$corps" not in ligne and "$entetes" not in ligne, ligne
    # 25/09, en réel : Google n'a pas donné __Secure-1PSIDTS à la connexion et
    # l'import du Studio a refusé. La réparation de la bibliothèque passe AVANT
    # l'envoi, tant que le profil du navigateur existe encore.
    reparation = ps1.index("auth refresh --verify --allow-headless")
    assert ps1.index("login --browser") < reparation < ps1.index("/notebooklm/session")
    # Le dossier de travail (session + profil du navigateur) part dans un finally.
    fin = ps1.split("} finally {")[1]
    assert "Remove-Item -Recurse -Force -LiteralPath $travail" in fin
    # PowerShell 5.1 lit un .ps1 sans BOM en ANSI : le script reste en ASCII.
    assert ps1.isascii() and cmd.isascii()


# --- 6. Carnets : noms clairs, et la place faite par la personne (25/09/2026) -----

@pytest.mark.parametrize("titre, quand, attendu", [
    ("Phares", "25/09/2026 08:40", "Studio · Phares · 25/09/2026 08:40"),
    ("", "", "Studio · Résumé"),
    ("  cours   de\nmaths ", "2026-09-25", "Studio · cours de maths"),   # heure pas francaise : ecartee
])
def test_le_nom_d_un_carnet_du_studio_se_lit(nlm, titre, quand, attendu):
    pont, _ = nlm
    assert pont.nom_du_carnet(titre, quand) == attendu


def test_la_liste_va_du_plus_ancien_au_plus_recent_sans_les_carnets_des_autres(nlm):
    pont, sc = nlm
    brancher(pont)
    sc.carnets += [carnet("d", "Partagé par un collègue", 2020, 1, proprio=False),
                   carnet("e", "Sans date", 2020, 1, date=False)]
    liste = lancer(pont, pont.carnets)
    assert [n["id"] for n in liste] == ["a", "c", "b", "e"]
    assert liste[0]["cree"] < liste[1]["cree"] < liste[2]["cree"] and liste[3]["cree"] is None
    assert [n["du_studio"] for n in liste] == [False, False, True, False]


def test_supprimer_ne_touche_que_les_carnets_possedes_et_encore_la(nlm):
    pont, sc = nlm
    brancher(pont)
    sc.carnets.append(carnet("d", "Partagé", 2020, 1, proprio=False))
    r = lancer(pont, lambda: pont.supprimer(["a", "d", "inconnu", "c"]))
    assert r == {"supprimes": ["a", "c"], "refuses": ["d", "inconnu"]}
    assert sc.supprimes == ["a", "c"]


def test_un_compte_plein_se_dit_et_rien_n_est_envoye(nlm, tmp_path):
    pont, sc = nlm
    brancher(pont)
    sc.plein = True
    with pytest.raises(pont.CarnetsPleins, match="Votre NotebookLM est plein"):
        _resume(pont, tmp_path)
    assert not any(a[0] in ("texte", "fichier", "generer") for a in sc.appels)
    assert sc.supprimes == [], "plein ne supprime JAMAIS rien tout seul"


def test_un_resume_refuse_pour_compte_plein_ouvre_la_boite_des_carnets(client):
    c, pont, sc = client
    brancher(pont)
    sc.plein = True
    r = c.post("/notebooklm/resume", headers=ENTETE,
               data={"texte": "x", "titre": "Phares", "quand": "25/09/2026 08:40"})
    j = _attendre_fin(c, r.json()["id"])
    assert j["status"] == "failed" and j["plein"] is True and "plein" in j["message"]
    assert ("creer", "Studio · Phares · 25/09/2026 08:40") in sc.appels
    assert sc.supprimes == []


def test_les_routes_des_carnets_lisent_puis_suppriment_sur_confirmation(client):
    c, pont, sc = client
    brancher(pont)
    assert c.get("/notebooklm/carnets").status_code == 401
    liste = c.get("/notebooklm/carnets", headers=ENTETE).json()["carnets"]
    assert [n["id"] for n in liste] == ["a", "c", "b"]
    chemin = "/notebooklm/carnets/supprimer"
    assert c.post(chemin, headers=ENTETE, json={"ids": ["a"]}).status_code == 400
    assert c.post(chemin, headers=ENTETE, json={"ids": ["a"], "confirme": "oui"}).status_code == 400
    assert c.post(chemin, headers=ENTETE, json={"ids": [], "confirme": True}).status_code == 400
    assert c.post(chemin, headers=dict(ENTETE, **AUTRE_SITE),
                  json={"ids": ["a"], "confirme": True}).status_code == 403
    assert sc.supprimes == []
    r = c.post(chemin, headers=ENTETE, json={"ids": ["a", "c"], "confirme": True})
    assert r.json() == {"supprimes": ["a", "c"], "refuses": []}
    assert [n["id"] for n in c.get("/notebooklm/carnets", headers=ENTETE).json()["carnets"]] == ["b"]


def test_en_studio_partage_les_carnets_ne_se_lisent_ni_ne_se_suppriment(sandbox, nlm):
    from fastapi.testclient import TestClient
    pont, sc = nlm
    brancher(pont)
    c = TestClient(sandbox.app, base_url="http://192.168.1.20")
    assert c.get("/notebooklm/carnets", headers=ENTETE).status_code == 403
    assert c.post("/notebooklm/carnets/supprimer", headers=ENTETE,
                  json={"ids": ["a"], "confirme": True}).status_code == 403
    assert sc.supprimes == []
