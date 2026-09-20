"""Vider une ressource ne doit pas fermer une porte.

REGLE DU PROPRIETAIRE, 20/09/2026 : << si on supprime, l'usage de la ressource
demandee demarre par son telechargement >>.

Sans elle, `scripts/ressources.sh --vider video-poids` etait un piege : le
client rendait 32 Go, redemandait un clip << a la maison >>, et le Studio le
faisait payer chez le loueur en lui disant d'ouvrir un terminal. Ces tests
gardent le comportement qui repare ca, cas par cas :

1. l'etat des poids se MESURE sur le disque, jamais dans un compteur -- un
   compteur ment des qu'un telechargement a ete repris ;
2. demander un clip sans les poids DEMARRE le telechargement et rend la
   question au client, avec ses trois sorties et le prix de chacune ;
3. consulter l'etat ne demarre rien ;
4. et quand le decideur ne voit pas le cache (pas de surcouche GPU), rien ne
   change : le clip part chez le loueur, comme avant.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
GPU_URL = "http://sandbox-worker-gpu:8000"


@pytest.fixture
def poids(sandbox, tmp_path, monkeypatch):
    """Le module, branche sur un faux cache jetable."""
    m = sandbox.poids_video
    monkeypatch.setattr(m, "DOSSIER", str(tmp_path))
    monkeypatch.setattr(m, "_etat", {"en_cours": False, "fini": False,
                                     "erreur": None, "debut": None})
    return m


# --- 1. L'etat se mesure sur le disque ---------------------------------------

def test_sans_cache_monte_le_module_reste_muet(sandbox, monkeypatch):
    """Pas de surcouche GPU = pas de carte = rien a telecharger."""
    monkeypatch.setattr(sandbox.poids_video, "DOSSIER", "")
    e = sandbox.poids_video.etat()
    assert e["possible"] is False and e["present"] is False
    assert "pas de carte" in sandbox.poids_video.phrase(e).lower()


def test_les_octets_sont_comptes_sur_le_disque(poids, tmp_path):
    """Un pourcentage qui vient d'un compteur ment apres une reprise."""
    d = tmp_path / "hub" / "models--Wan-AI--Wan2.2-TI2V-5B-Diffusers" / "blobs"
    d.mkdir(parents=True)
    (d / "morceau").write_bytes(b"x" * 1024)
    e = poids.etat()
    assert e["octets"] == 1024
    # Le total mesure le 20/09 : 34 203 034 754 octets en 1 310,9 s.
    assert e["total_octets"] == 34203034754


def test_un_dossier_a_moitie_plein_ne_compte_pas_pour_des_poids_presents(poids, tmp_path, monkeypatch):
    """LE defaut trouve le 20/09 en ecrivant ces tests, et il etait deja livre.

    `poids_presents` valait << le dossier existe >>. Or le Studio telecharge
    maintenant lui-meme : le dossier existe pendant les vingt-deux minutes ou
    il se remplit. Un clip route << maison >> a la troisieme minute serait
    perdu -- exactement la panne de dix minutes que le detour par /health
    devait supprimer. Et un telechargement interrompu a la main produisait
    deja le meme mensonge avant ce chantier.
    """
    d = tmp_path / "hub" / "models--Wan-AI--Wan2.2-TI2V-5B-Diffusers" / "blobs"
    d.mkdir(parents=True)
    (d / "morceau").write_bytes(b"x" * 4096)
    assert poids.etat()["present"] is False

    # Complet : 98 % des octets attendus, et plus un seul `.incomplete`.
    monkeypatch.setattr(poids, "TOTAL_OCTETS", 4096)
    assert poids.etat()["present"] is True
    (d / "reste.incomplete").write_bytes(b"")
    assert poids.etat()["present"] is False


def test_le_pourcentage_ne_dit_jamais_100_avant_la_fin(poids, tmp_path):
    """Un dossier a moitie rempli ne doit pas afficher << pret >>."""
    d = tmp_path / "hub" / "models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
    d.mkdir(parents=True)
    (d / "a").write_bytes(b"y" * 4096)
    poids._etat.update(en_cours=True, debut=0.0)
    e = poids.etat()
    assert e["pourcent"] < 1.0
    assert "se telecharge" in poids.phrase(e)


def test_demarrer_ne_relance_pas_ce_qui_tourne_deja(poids, monkeypatch):
    """Deux clics coup sur coup ne font pas deux telechargements de 34 Go."""
    lances = []
    monkeypatch.setattr(poids.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: lances.append(1)})())
    poids.demarrer()
    poids.demarrer()
    assert len(lances) == 1
    assert poids.etat()["en_cours"] is True


def test_demarrer_ne_fait_rien_quand_les_poids_sont_la(poids, tmp_path, monkeypatch):
    d = tmp_path / "hub" / "models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
    d.mkdir(parents=True)
    (d / "poids").write_bytes(b"z" * 4096)
    monkeypatch.setattr(poids, "TOTAL_OCTETS", 4096)
    monkeypatch.setattr(poids.threading, "Thread",
                        lambda *a, **k: pytest.fail("rien ne doit se relancer"))
    assert poids.demarrer()["present"] is True


def test_le_telechargement_ecrit_la_ou_le_studio_regarde(poids, monkeypatch):
    """LE defaut du 20/09, trouve en jouant le chemin en vrai et pas en le lisant.

    `snapshot_download(DEPOT)` sans `cache_dir` ecrit dans le dossier par
    defaut de Hugging Face -- dans le conteneur `/root/.cache/huggingface`,
    qui n'est pas monte et disparait au redemarrage. Mesure du jour, depuis un
    dossier vide : **0 octet apres 30 s** la ou le Studio regarde, pendant que
    la page annoncait << se telecharge : 0 % faits >>. Trente-quatre Go perdus
    au premier `docker compose up`, et une phrase rassurante posee sur rien.

    La garde tient en une phrase : l'endroit ou l'on ECRIT doit etre
    exactement celui ou l'on MESURE."""
    recu: dict = {}
    faux = types.ModuleType("huggingface_hub")
    faux.snapshot_download = lambda depot, **kw: recu.update(depot=depot, **kw)
    monkeypatch.setitem(sys.modules, "huggingface_hub", faux)

    poids._travail()

    assert recu["depot"] == poids.DEPOT
    assert Path(recu["cache_dir"]) == poids.cache_hub()
    assert poids.chemin().parent == Path(recu["cache_dir"])
    # Et c'est bien le `hub/` que le bac a sable exige (`SANDBOX_POIDS_REQUIS`),
    # pas le dossier au-dessus : un etage de trop et les poids sont invisibles.
    assert Path(recu["cache_dir"]).name == "hub"
    assert poids.etat()["erreur"] is None


# --- 2. Demander un clip sans les poids demarre le telechargement ------------

def creer(service, **payload):
    corps = {"description": "un phare dans la tempete", "duree": "3", "ou": "modal"}
    corps.update(payload)
    return TestClient(service.app, base_url=LOCAL).post("/video/creer", headers=CLE, json=corps)


@pytest.fixture
def studio_sans_poids(sandbox, monkeypatch):
    """Une carte branchee, les 34 Go absents, et le decideur qui PEUT les descendre."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", GPU_URL)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: None)
    monkeypatch.setattr(sandbox, "maison_prete", lambda: (
        False,
        "Le modele video (34 Go) se telecharge maintenant : 12 % faits. Encore environ 19 minutes.",
        True))
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "utilisable",
                        lambda *a, **k: pytest.fail("la carte ne doit pas etre sondee"))
    return sandbox


def test_sans_les_poids_la_question_est_rendue_au_client_avec_ses_trois_sorties(studio_sans_poids):
    """409, et non un clip paye sans qu'on demande.

    Le 409 est le meme que pour une carte prise : rien n'est en panne, il y a
    une attente dont le client connait le prix."""
    r = creer(studio_sans_poids)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["ou"] == "on-demande"
    assert d["sorties"] == ["attente", "modal", "annuler"]
    # Les chiffres du telechargement sont DANS la phrase montree.
    assert "12 %" in d["pourquoi"] and "19 minutes" in d["pourquoi"]
    # Et le prix de l'autre sortie, avant de cliquer.
    assert d["prix_estime_usd"] is not None
    # Le titre dit ce qui bloque : sans lui, la page annoncerait une carte prise.
    assert "télécharge" in d["titre"]


def test_j_attends_devient_une_attente_et_non_une_depense(studio_sans_poids):
    """La page relance toutes les 30 s ; quand les 34 Go sont la, le clip part ici."""
    r = creer(studio_sans_poids, attendre=True)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["ou"] == "attente"
    assert d["reglage"] == "toujours-maison"


def test_consulter_l_etat_ne_demarre_rien(sandbox, monkeypatch):
    """Ouvrir la page ne doit pas declencher 34 Go de telechargement."""
    monkeypatch.setattr(sandbox.poids_video, "demarrer",
                        lambda: pytest.fail("consulter n'est pas demander"))
    r = TestClient(sandbox.app, base_url=LOCAL).get("/video/poids/etat", headers=CLE)
    assert r.status_code == 200
    assert "phrase" in r.json()


# --- 3. Celui qui n'a pas la surcouche ne voit aucun changement ---------------

def test_sans_cache_dans_le_decideur_le_clip_part_chez_le_loueur_comme_avant(sandbox, monkeypatch):
    """Le cas du Studio installe sans surcouche GPU : on rend la commande."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", GPU_URL)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: None)
    monkeypatch.setattr(sandbox.poids_video, "DOSSIER", "")

    class FausseReponse:
        def json(self): return {"ok": True, "poids_presents": False}

    class FauxClient:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return FausseReponse()

    monkeypatch.setattr(sandbox.httpx, "Client", lambda **k: FauxClient())
    r = creer(sandbox)
    assert r.status_code == 200
    fiche = r.json()
    assert fiche["provider"] == "modal"
    assert "telecharger-modele-video" in fiche["ou_calculer"]["pourquoi"]


# --- 4. La page sait afficher autre chose que << la carte est prise >> -------

def test_la_page_utilise_le_titre_quand_ce_n_est_pas_la_carte_qui_bloque(sandbox):
    """Sans ce branchement, la boite dirait << la carte est prise >> pendant que
    le Studio descend 34 Go -- faux, et inquietant."""
    page = sandbox.video.PAGE_HTML
    assert "d.titre" in page
    # Les deux boites, celle qui attend et celle qui demande, le prennent.
    assert page.count("d.titre ?") >= 2
