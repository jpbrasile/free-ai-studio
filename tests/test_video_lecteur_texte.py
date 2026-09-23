"""Vidéo : la table des mots du lecteur de texte est rattachée à la main.

Échec Kaggle du 23/09/2026 (travail ef554b3c, T4 de 14,6 Go) : le journal dit
« encoder.embed_tokens.weight | MISSING ... newly initialized ». La table des
mots est recréée au hasard (environ 2 Go de trop), la description est lue avec
des mots quelconques et cuBLAS n'a plus de place (CUBLAS_STATUS_ALLOC_FAILED).

Le bloc du script envoyé à la carte est exécuté ici sur de faux objets : aucun
modèle n'est chargé. Qu'il suffise sur un vrai T4 n'est PAS prouvé par ce test.
"""
from __future__ import annotations

import ast
import types


def bloc(video) -> str:
    source = video._SCRIPT
    debut = source.index("lecteur = getattr(pipe, \"text_encoder\", None)")
    fin = source.index("# MESURE DU 09/09", debut)
    return source[debut:fin]


def executer(video, pipe) -> list[str]:
    dits: list[str] = []
    exec(bloc(video), {"pipe": pipe, "print": lambda *a, **k: dits.append(" ".join(map(str, a)))})
    return dits


def faux_pipe(relie: bool):
    partagee = object()
    pile = types.SimpleNamespace(embed_tokens=partagee if relie else object())
    lecteur = types.SimpleNamespace(shared=partagee, encoder=pile)
    return types.SimpleNamespace(text_encoder=lecteur)


def test_une_table_recreee_au_hasard_est_rattachee_et_dite(sandbox):
    pipe = faux_pipe(relie=False)
    dits = executer(sandbox.video, pipe)
    assert pipe.text_encoder.encoder.embed_tokens is pipe.text_encoder.shared
    assert len(dits) == 1 and "rattachee" in dits[0], (
        "le rattachement se fait en silence : le journal ne dit plus pourquoi."
    )


def test_une_table_deja_reliee_ne_change_rien(sandbox):
    pipe = faux_pipe(relie=True)
    avant = pipe.text_encoder.encoder.embed_tokens
    assert executer(sandbox.video, pipe) == []
    assert pipe.text_encoder.encoder.embed_tokens is avant


def test_un_modele_sans_lecteur_de_ce_type_passe(sandbox):
    assert executer(sandbox.video, types.SimpleNamespace(text_encoder=None)) == []


def test_le_script_complet_reste_du_python_valide_et_dit_sa_memoire(sandbox):
    video = sandbox.video
    script = video.construire_script(video.preparer({"description": "un chat"})["demande"])
    ast.parse(script)
    assert "mem_get_info()" in script, (
        "le journal ne dit pas la memoire libre avant le calcul : le prochain echec "
        "de memoire se lira encore a l'aveugle."
    )
