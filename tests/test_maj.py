"""Bouton « Mettre a jour » : sans veilleur, le message renvoie au geste du debutant."""
from __future__ import annotations

import asyncio
import os
import time

import pytest
from fastapi import HTTPException


def test_sans_veilleur_renvoie_vers_demarrer(routeur):
    with pytest.raises(HTTPException) as refus:
        asyncio.run(routeur.maj_lancer())
    assert refus.value.status_code == 503
    assert "demarrer.cmd" in refus.value.detail
    # start.ps1 n'est pas le chemin du debutant (README, geste 5). Jusqu'au
    # 14/09/2026, le message y renvoyait.
    assert "start.ps1" not in refus.value.detail
    assert not routeur.MAJ_DEMANDE.exists()


def test_veilleur_vivant_recoit_la_demande(routeur):
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    reponse = asyncio.run(routeur.maj_lancer())
    assert reponse["demande"] is True
    assert routeur.MAJ_DEMANDE.exists()


def test_veilleur_muet_depuis_une_minute(routeur):
    # Un signe de vie trop vieux vaut un veilleur absent : la demande resterait
    # sur la table, et la page attendrait pour rien.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    vieux = time.time() - 60
    os.utime(routeur.MAJ_VEILLEUSE, (vieux, vieux))
    with pytest.raises(HTTPException):
        asyncio.run(routeur.maj_lancer())
    assert not routeur.MAJ_DEMANDE.exists()
