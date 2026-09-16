"""Bouton « Mettre a jour » : sans veilleur, le message renvoie au geste du debutant."""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def demande_de_la_page():
    """Ce que le navigateur envoie depuis la page du Studio."""
    return SimpleNamespace(headers={"sec-fetch-site": "same-origin",
                                    "content-type": "application/json"})


def test_sans_veilleur_renvoie_vers_demarrer(routeur):
    with pytest.raises(HTTPException) as refus:
        asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert refus.value.status_code == 503
    assert "demarrer.cmd" in refus.value.detail
    # start.ps1 n'est pas le chemin du debutant (README, geste 5). Jusqu'au
    # 14/09/2026, le message y renvoyait.
    assert "start.ps1" not in refus.value.detail
    assert not routeur.MAJ_DEMANDE.exists()


def test_veilleur_vivant_recoit_la_demande(routeur):
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    reponse = asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert reponse["demande"] is True
    assert routeur.MAJ_DEMANDE.exists()


def test_signe_de_vie_date_du_futur_compte(routeur):
    # Horloge du conteneur en retard sur celle de Windows : le fichier porte une
    # date a venir. Jusqu'au 16/09/2026, le Studio tenait ce veilleur pour mort
    # et renvoyait vers demarrer.cmd.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    futur = time.time() + 20
    os.utime(routeur.MAJ_VEILLEUSE, (futur, futur))
    reponse = asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert reponse["demande"] is True


def test_signe_de_vie_tres_en_avance_refuse(routeur):
    # Deux heures d'avance : ce n'est plus un ecart d'horloge, c'est un fichier
    # laisse la. Le veilleur est tenu pour absent.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    futur = time.time() + 7200
    os.utime(routeur.MAJ_VEILLEUSE, (futur, futur))
    with pytest.raises(HTTPException):
        asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert not routeur.MAJ_DEMANDE.exists()


def test_veilleur_muet_depuis_une_minute(routeur):
    # Un signe de vie trop vieux vaut un veilleur absent : la demande resterait
    # sur la table, et la page attendrait pour rien.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    vieux = time.time() - 60
    os.utime(routeur.MAJ_VEILLEUSE, (vieux, vieux))
    with pytest.raises(HTTPException):
        asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert not routeur.MAJ_DEMANDE.exists()
