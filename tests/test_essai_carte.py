"""La page d'essai VERIFIE si l'ordinateur a une carte, au lieu de l'affirmer.

Defaut releve par le proprietaire le 20/09/2026, sur sa propre machine :
<< affirmation fausse sur ce pc >>, a propos de la phrase

    La carte graphique n'existe pas sur le backend local.

Elle etait vraie le jour ou elle a ete ecrite. Depuis le 19/09/2026, la
surcouche `docker-compose.gpu.yml` donne la carte au gestionnaire ET un
deuxieme bac a sable qui sait s'en servir : sur ce PC, la page Video fabrique
des clips sur une RTX 4090. Un debutant muni d'une carte lisait donc, sur sa
propre page, que sa carte n'existe pas.

Ordre suivant du proprietaire : << fais en sorte que le test soit fait, le
client a ou pas de gpu >>. La page MESURE donc la machine par `/essai/carte`,
qui lance un vrai `nvidia-smi`. Elle ne pose la question a personne : un
debutant ne sait pas si son PC a une carte graphique, et c'est justement pour
lui que ce Studio existe.

Ce que ces tests gardent :

1. la route rend le releve REEL, et ne pretend pas que cette page s'en sert ;
2. la phrase montree suit le releve, dans les deux cas -- carte vue, carte
   absente -- et n'affirme JAMAIS qu'il n'y a pas de carte quand il y en a une ;
3. quand la carte existe, la page dit aussi que cette page-ci ne s'en sert pas.
   Remplacer une phrase fausse par une autre serait le meme defaut a l'envers ;
4. la case << carte graphique >> fait ce qu'elle dit. Elle a ete grisee du 20
   au 21/09/2026 parce qu'elle etait IGNOREE en silence -- `run_local` ne
   recevait meme pas le drapeau. Depuis REG-1, tranche par le proprietaire le
   21/09, le code part sur la carte SI elle est libre a cet instant, sinon sur
   le processeur, et la fiche du travail dit LAQUELLE a servi. Un repli
   silencieux serait la meme faute que la case grisee sans raison.

Aucun appel reseau, aucun nvidia-smi : la sonde est remplacee par un faux.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from conftest import RACINE

VUE = {"vue": True, "nom": "NVIDIA GeForce RTX 4090", "totale_mo": 24564,
       "libre_mo": 24138, "marge_mo": 1024, "motif": ""}
ABSENTE = {"vue": False, "nom": None, "totale_mo": None, "libre_mo": None,
           "marge_mo": 1024,
           "motif": "nvidia-smi absent du conteneur : la carte n'y est pas passee"}


def _client(sandbox):
    return TestClient(sandbox.app)


def _entetes(sandbox):
    return {"Authorization": "Bearer " + sandbox.KEY}


def _fonction_js(nom: str) -> str:
    """Sort une fonction de la page, telle qu'elle part dans le navigateur."""
    source = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    debut = source.index("function %s(" % nom)
    profondeur = 0
    for fin in range(source.index("{", debut), len(source)):
        if source[fin] == "{":
            profondeur += 1
        elif source[fin] == "}":
            profondeur -= 1
            if profondeur == 0:
                return source[debut:fin + 1]
    raise AssertionError("%s n'est pas refermee" % nom)


def _rendu(tmp_path, etat):
    """Execute carteTexte dans node : on veut la phrase qui SORT, pas le code.

    Le texte lu ici est celui que le client voit. Un test qui se contenterait de
    chercher des mots dans la source dirait seulement que les deux branches sont
    ECRITES, pas laquelle parle.
    """
    # MODAL_PLUS_VITE est declare hors de la fonction : sans lui, node leve.
    programme = ('const MODAL_PLUS_VITE = "Sur Modal, la carte consomme l\'offre '
                 'gratuite beaucoup plus vite qu\'un calcul sur processeur.";\n'
                 + _fonction_js("carteTexte")
                 + "\nconsole.log(carteTexte(" + json.dumps(etat) + "));\n")
    fichier = tmp_path / "carte.js"
    fichier.write_text(programme, encoding="utf-8")
    # encoding= explicite : node ecrit de l'UTF-8 et Python decoderait en cp1252.
    fait = subprocess.run(["node", str(fichier)], capture_output=True,
                          text=True, encoding="utf-8")
    assert fait.returncode == 0, fait.stderr
    return fait.stdout


# --- 1. La route mesure, et n'exagere pas ce qu'elle mesure ------------------

def test_la_route_rend_le_releve_reel_de_la_sonde(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.gpu_local, "releve", lambda *a, **k: VUE)
    corps = _client(sandbox).get("/essai/carte", headers=_entetes(sandbox)).json()
    assert corps["carte"] == VUE
    assert corps["carte"]["nom"] == "NVIDIA GeForce RTX 4090"


def test_la_route_n_affirme_pas_que_cette_page_utilise_la_carte(sandbox, monkeypatch):
    """La carte existe, et cette page ne s'en sert pas : les deux sont vrais.

    Dire le premier sans le second remplacerait une phrase fausse par une
    autre, dans le sens qui fait perdre du temps au lieu d'en faire perdre.
    """
    monkeypatch.setattr(sandbox.gpu_local, "releve", lambda *a, **k: VUE)
    corps = _client(sandbox).get("/essai/carte", headers=_entetes(sandbox)).json()
    assert corps["utilisee_par_cette_page"] is False


def test_la_route_dit_pourquoi_quand_il_n_y_a_pas_de_carte(sandbox, monkeypatch):
    """Un `vue: false` sans motif se lirait comme une panne du Studio."""
    monkeypatch.setattr(sandbox.gpu_local, "releve", lambda *a, **k: ABSENTE)
    corps = _client(sandbox).get("/essai/carte", headers=_entetes(sandbox)).json()
    assert corps["carte"]["vue"] is False
    assert corps["carte"]["motif"].strip()


def test_la_route_demande_la_cle(sandbox):
    assert _client(sandbox).get("/essai/carte").status_code in (401, 403)


# --- 2. La phrase montree suit le releve ------------------------------------

def test_avec_une_carte_la_page_la_nomme_et_ne_la_nie_pas(tmp_path):
    texte = _rendu(tmp_path, {"carte": VUE, "bac_a_sable_gpu": True,
                              "utilisee_par_cette_page": False})
    assert "NVIDIA GeForce RTX 4090" in texte
    assert "24138" in texte, "la memoire libre mesuree doit rester lisible"
    assert "n'a pas de carte" not in texte
    assert "n'existe pas" not in texte


def test_avec_une_carte_la_page_dit_LA_CONDITION_et_pas_seulement_oui(tmp_path):
    """Une case qui marche << parfois >> sans dire quand trompe autant qu'une
    case grisee sans raison.

    La phrase disait, du 20 au 21/09 : << Ici, le code tourne quand meme sur le
    processeur [...] le Studio ne lance pas un travail sur un chiffre suppose >>.
    Elle est devenue fausse a la minute ou la carte a ete branchee. Ce test
    garde la meme exigence qu'avant -- la page dit la REGLE, pas seulement le
    resultat -- de l'autre cote.
    """
    texte = _rendu(tmp_path, {"carte": VUE, "bac_a_sable_gpu": True,
                              "utilisee_par_cette_page": True})
    assert "chiffre suppose" not in texte, \
        "la vieille raison est devenue fausse : la page s'en sert desormais"
    assert "que personne d'autre ne la tienne" in texte, \
        "la condition doit etre ecrite, sinon la case marche << parfois >>"
    assert "processeur" in texte, "le repli doit etre annonce avant, pas subi"
    assert "jamais arrete" in texte, \
        "un client doit savoir qu'on n'interrompt pas le calcul d'un autre"


def test_sans_carte_la_page_le_dit_avec_son_motif(tmp_path):
    texte = _rendu(tmp_path, {"carte": ABSENTE, "bac_a_sable_gpu": False,
                              "utilisee_par_cette_page": False})
    assert "n'a pas de carte graphique" in texte
    assert "nvidia-smi" in texte, "le motif mesure doit accompagner le constat"


@pytest.mark.parametrize("releve", [VUE, ABSENTE], ids=["carte_vue", "carte_absente"])
def test_l_avertissement_sur_modal_reste_dans_les_deux_cas(tmp_path, releve):
    """Vrai avec ou sans carte : c'est la moitie de la phrase qui etait juste."""
    texte = _rendu(tmp_path, {"carte": releve, "bac_a_sable_gpu": bool(releve["vue"]),
                              "utilisee_par_cette_page": False})
    assert "offre gratuite beaucoup plus vite" in texte


# --- 3. La page elle-meme ----------------------------------------------------

def test_la_vieille_affirmation_a_disparu_de_la_page(sandbox):
    """Elle etait ecrite en dur, hors de toute condition."""
    page = _client(sandbox).get("/essai").text
    assert "La carte graphique n'existe pas sur le backend local" not in page


def test_la_page_interroge_vraiment_la_route(sandbox):
    """Une fonction que personne n'appelle ne repare rien."""
    page = _client(sandbox).get("/essai").text
    assert 'id="carte"' in page, "la boite ou ecrire la reponse a disparu"
    assert 'fetch("/essai/carte"' in page, "la page ne verifie plus l'etat de la carte"
    assert "carteTexte(d)" in page, "la reponse n'est plus mise dans la page"


def test_la_case_carte_est_redevenue_cochable_et_la_page_le_justifie(sandbox):
    """Elle a ete grisee un jour, le temps qu'elle serve a quelque chose.

    Une case sans effet qui se laisse cocher fait croire a un calcul sur la
    carte qui n'a jamais eu lieu ; une case grisee alors que le Studio SAIT
    utiliser la carte est la meme faute a l'envers.
    """
    page = _client(sandbox).get("/essai").text
    assert "function accorderLaCase()" in page
    assert "case_.disabled = false" in page, "la case doit etre rendue au client"
    assert "case_.disabled = local" not in page, "le grisage du 20/09 doit avoir disparu"
    assert 'addEventListener("change", accorderLaCase)' in page
    assert "si elle est libre au moment du lancement" in page, \
        "l'infobulle doit dire la condition"


def test_le_drapeau_gpu_passe_enfin_la_porte(sandbox):
    """REG-1 referme. Le test qui figeait l'ancien etat a fait son travail : il
    est tombe le jour du branchement, comme annonce dans PLAN.md.
    """
    source = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    assert "threading.Thread(target=run_local, args=(jid, req.code, req.gpu), daemon=True)" in source
    assert "def run_local(jid: str, code: str, gpu: bool = False)" in source


def _job(sandbox, gpu):
    jid = "essai-" + os.urandom(6).hex()
    sandbox.write_job(jid, {"id": jid, "provider": "local", "gpu": gpu,
                            "status": "queued", "artifacts": []})
    return jid


def test_sans_drapeau_la_carte_n_est_meme_pas_sondee(sandbox, monkeypatch):
    """Le chemin de tous les jours ne paie pas une sonde inutile -- et surtout,
    rien ne part sur la carte quand personne ne l'a demandee."""
    sondes = []
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://faux:8000")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda *a, **k: sondes.append(1) or (True, "", VUE))
    monkeypatch.setattr(sandbox, "local_execute",
                        lambda jid, code: {"exit_code": 0, "stdout": "ok", "stderr": ""})
    monkeypatch.setattr(sandbox, "maison_execute", lambda *a, **k: pytest.fail(
        "parti sur la carte alors que personne ne l'a demandee"))
    jid = _job(sandbox, gpu=False)
    sandbox.run_local(jid, "print(1)", False)
    fiche = sandbox.read_job(jid)
    assert fiche["provider_effective"] == "local"
    assert "placement" not in fiche, "rien a expliquer quand rien n'a ete demande"
    assert sondes == []


def test_avec_le_drapeau_et_la_carte_libre_le_travail_part_SUR_LA_CARTE(sandbox, monkeypatch):
    """Bout en bout, et la duree courte est verifiee au passage.

    Sans ce dernier point, /essai heriterait des 2 400 s de la video et un code
    qui ne s'arrete pas tiendrait la carte quarante minutes.
    """
    recues = []
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://faux:8000")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda *a, **k: (True, "RTX 4090 : 24138 Mo libres sur 24564,"
                                               " personne d'autre ne la tient.", VUE))
    monkeypatch.setattr(sandbox, "local_execute", lambda *a, **k: pytest.fail(
        "reste sur le processeur alors que la carte est libre"))
    monkeypatch.setattr(sandbox, "maison_execute",
                        lambda jid, code, secondes=None: recues.append(secondes) or
                        {"exit_code": 0, "stdout": "ok", "stderr": ""})
    jid = _job(sandbox, gpu=True)
    sandbox.run_local(jid, "print(1)", True)
    fiche = sandbox.read_job(jid)
    assert fiche["provider_effective"] == "maison"
    assert "tourne sur la carte" in fiche["placement"]
    assert recues == [sandbox.ESSAI_MAISON_S]
    assert sandbox.ESSAI_MAISON_S < 2400, "la duree de la video n'a rien a faire ici"


def test_avec_le_drapeau_mais_la_carte_prise_le_travail_RESTE_sur_le_processeur(
        sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://faux:8000")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda *a, **k: (False, "RTX 4090 : 15500 Mo deja pris sur 24564."
                                                " Un autre calcul tient la carte, et on"
                                                " ne l'arrete jamais.", VUE))
    monkeypatch.setattr(sandbox, "local_execute",
                        lambda jid, code: {"exit_code": 0, "stdout": "ok", "stderr": ""})
    monkeypatch.setattr(sandbox, "maison_execute", lambda *a, **k: pytest.fail(
        "a pris une carte que quelqu'un d'autre tenait"))
    jid = _job(sandbox, gpu=True)
    sandbox.run_local(jid, "print(1)", True)
    fiche = sandbox.read_job(jid)
    assert fiche["provider_effective"] == "local"
    assert "ne l'arrete jamais" in fiche["placement"],         "le client doit lire POURQUOI sa carte n'a pas servi"


def test_carte_libre_le_code_part_sur_la_carte(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://faux:8000")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda *a, **k: (True, "RTX 4090 : 24138 Mo libres sur 24564,"
                                               " personne d'autre ne la tient.", VUE))
    ou, phrase = sandbox.ou_lancer_essai()
    assert ou == "maison"
    assert "tourne sur la carte" in phrase


def test_carte_prise_le_code_part_sur_le_processeur_et_on_n_arrete_personne(
        sandbox, monkeypatch):
    """LE cas qui protege le voisin.

    Sur la machine de developpement, `llama-server` tient 15,5 Go en
    permanence. Un Studio qui prendrait la carte de force ferait perdre le
    travail de quelqu'un d'autre -- ici, il s'efface et il le dit.
    """
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://faux:8000")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda *a, **k: (False, "RTX 4090 : 15500 Mo deja pris sur 24564."
                                                " Un autre calcul tient la carte, et on"
                                                " ne l'arrete jamais.", VUE))
    ou, phrase = sandbox.ou_lancer_essai()
    assert ou == "local"
    assert "ne l'arrete jamais" in phrase
    assert "tourne sur le processeur" in phrase


def test_sans_bac_a_sable_gpu_le_repli_est_dit_et_la_sonde_n_est_pas_appelee(
        sandbox, monkeypatch):
    """Une carte vue par le gestionnaire ne veut pas dire un bac a sable pour
    s'en servir : la surcouche peut ne pas etre appliquee."""
    appels = []
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda *a, **k: appels.append(1) or (True, "", VUE))
    ou, phrase = sandbox.ou_lancer_essai()
    assert ou == "local"
    assert "docker-compose.gpu.yml" in phrase
    assert appels == [], "inutile de sonder la carte : aucun bac a sable pour s'en servir"


def test_une_duree_demandee_ne_peut_que_RACCOURCIR_l_attente(sandbox):
    """Le bac a sable GPU est regle a 2 400 s pour la video.

    Un code tape dans /essai n'a pas a pouvoir tenir la carte quarante minutes.
    Mais le champ qui raccourcit ne doit jamais pouvoir rallonger, sinon il
    devient une porte.
    """
    source = (RACINE / "sandbox-worker" / "app.py").read_text(encoding="utf-8")
    assert "min(TIMEOUT, int(req.secondes))" in source, \
        "la duree demandee doit etre plafonnee par le reglage"
    gestionnaire = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    assert "min(plafond, int(secondes))" in gestionnaire
    assert "ESSAI_MAISON_S = int(os.getenv(" in gestionnaire


# --- 9. le repli dit ce qui manque sur le processeur -------------------------
# Trouve le 21/09 en PROUVANT le repli sur la vraie carte : le routage etait
# juste, le voisin intact, et le travail mourait sur
# `ModuleNotFoundError: No module named 'torch'`. Le client lisait << le code
# tourne sur le processeur >> et une trace qui ne s'y rapporte pas.

def test_le_repli_carte_prise_previent_que_torch_n_y_est_pas(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://bac-gpu:8000")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda: (False, "La carte est prise.", {}))
    ou, phrase = sandbox.ou_lancer_essai()
    assert ou == "local"
    assert "torch" in phrase and "CUDA" in phrase, phrase
    assert "s'arretera" in phrase, phrase


def test_le_repli_sans_bac_a_sable_gpu_previent_aussi(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "")
    ou, phrase = sandbox.ou_lancer_essai()
    assert ou == "local"
    assert "torch" in phrase, phrase


def test_partir_SUR_LA_CARTE_ne_previent_de_rien(sandbox, monkeypatch):
    """La mise en garde ne vaut que pour le processeur -- sur la carte, torch est la."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://bac-gpu:8000")
    monkeypatch.setattr(sandbox.gpu_local, "libre_pour_un_code_inconnu",
                        lambda: (True, "Personne ne la tient.", {}))
    ou, phrase = sandbox.ou_lancer_essai()
    assert ou == "maison"
    assert "torch" not in phrase, phrase


def test_la_phrase_et_les_DEUX_IMAGES_sont_tenues_ensemble(sandbox):
    """Le jour ou torch arrive sur le bac a sable du processeur, ce test tombe.

    Une phrase sur l'etat d'une image se perime en silence. Celle-ci est donc
    verifiee contre les deux fichiers qui construisent les images, et non
    recopiee depuis une mesure d'un jour.
    """
    cpu = (RACINE / "sandbox-worker" / "requirements.txt").read_text(
        encoding="utf-8")
    assert "torch" not in cpu.lower(), (
        "torch est arrive sur le bac a sable du processeur : la mise en garde "
        "de ou_lancer_essai() est devenue fausse, il faut la retirer")

    gpu = (RACINE / "sandbox-worker-gpu" / "Dockerfile").read_text(
        encoding="utf-8")
    assert "FROM pytorch/pytorch:" in gpu, (
        "le bac a sable de la carte ne part plus d'une image pytorch : verifier "
        "que torch y est toujours avant de promettre le contraire du processeur")

    assert "torch" in sandbox.SANS_TORCH
