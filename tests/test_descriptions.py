"""Les documents qu'un agent lit EN PREMIER ne doivent pas contredire le code.

Position du proprietaire, 19/09/2026 : << c'est un risque inacceptable pour un
fonctionnement automatique, sinon on ne sait pas l'utiliser >>. Elle reclasse
ces controles : ce n'est pas de la proprete, c'est un prealable dur. Un agent
qui lit `modal/profiles.json` ne se trompe pas par hasard -- le depot le lui a
dit.

Le defaut mesure le 19/09 : la section `policy` annoncait
`fallback_manual: ["colab", "kaggle"]`, manuel et dans cet ordre, quand
`run_auto` pose `["modal", "local", "kaggle", "colab"]` et enchaine tout seul.
Trois documents disaient la meme regle, tous les trois faux dans le meme sens.
Deux ont ete corriges a la main les 19 et 20/09 ; celui-ci est desormais
EPINGLE au code, ce qui est different : une correction vieillit, une epingle
non.

Aucun appel reseau : on lit un JSON et une source Python.
"""
from __future__ import annotations

import json
import re

from conftest import RACINE

PROFILS = RACINE / "modal" / "profiles.json"
SOURCE = RACINE / "sandbox-manager" / "app.py"


def _ordre_du_code(nom: str = "ORDRE_AUTO") -> list[str]:
    """Un ordre de `run_auto`, lu dans la source.

    Lu dans le texte et non importe : `app.py` ne s'importe pas sans son
    environnement. Jusqu'au 23/09, l'ordre etait une liste litterale dans un
    `job.update(...)` ; il y en a deux depuis (local d'abord pour un job sans
    carte ni Internet), devenues des constantes -- et ce test, comme annonce,
    est tombe et a ete rebranche dessus.
    """
    trouve = re.search(r"^%s = (\[[^\]]*\])" % nom,
                       SOURCE.read_text(encoding="utf-8"), re.M)
    assert trouve, "%s introuvable dans sandbox-manager/app.py" % nom
    return json.loads(trouve.group(1))


def _profils() -> dict:
    return json.loads(PROFILS.read_text(encoding="utf-8"))


def test_l_ordre_de_repli_du_catalogue_est_celui_du_code():
    """LE controle qui aurait attrape le defaut du 19/09."""
    policy = _profils()["policy"]
    assert policy["fallback_order"] == _ordre_du_code("ORDRE_AUTO")
    assert policy["fallback_order_sans_carte_ni_internet"] == \
        _ordre_du_code("ORDRE_AUTO_LOCAL_D_ABORD")
    assert policy["fallback_order_carte_sans_internet"] == \
        _ordre_du_code("ORDRE_AUTO_CARTE_D_ICI")
    assert policy["automatic_backend"] == "local"


def test_le_catalogue_ne_dit_plus_que_le_repli_est_manuel():
    """`fallback_manual` etait faux deux fois : l'ordre ET le mot << manuel >>.

    Un secours annonce manuel laisse croire qu'on garde la main ; en verite le
    Studio part tout seul sur Kaggle puis Colab.
    """
    policy = _profils()["policy"]
    assert "fallback_manual" not in policy, \
        "le champ qui portait la regle fausse est revenu"
    assert policy["fallback_is_automatic"] is True


def test_le_catalogue_dit_qu_aucun_code_ne_le_lit():
    """La phrase qui protege du contresens, et le fait qu'elle affirme.

    Si quelqu'un branche un jour du code sur ce fichier, la phrase devient
    fausse et ce test tombe : c'est le seul moment ou il doit parler.
    """
    entete = _profils()["_lisez_moi"]
    assert "Aucun code ne lit ce fichier" in entete["ce_que_ce_fichier_n_est_pas"]

    lecteurs = []
    for chemin in RACINE.rglob("*"):
        if chemin.suffix not in {".py", ".sh", ".ps1", ".yml", ".yaml", ".cmd"}:
            continue
        if ".git" in chemin.parts or "node_modules" in chemin.parts:
            continue
        if chemin.name == "test_descriptions.py":
            continue
        if "profiles.json" in chemin.read_text(encoding="utf-8", errors="ignore"):
            lecteurs.append(str(chemin.relative_to(RACINE)))
    assert not lecteurs, (
        "l'en-tete affirme que personne ne lit ce fichier, or : %s" % lecteurs)


def test_la_date_de_verification_ne_couvre_que_les_liens():
    """Une date qui grossit son perimetre est pire qu'une date absente.

    `verified` ne dit rien de la section `policy`, qui est epinglee au code et
    n'a donc pas de date : elle est vraie ou le test est rouge.
    """
    profils = _profils()
    assert re.fullmatch(r"20\d\d-\d\d-\d\d", profils["verified"])
    assert "LIENS" in profils["_lisez_moi"]["verified_couvre"]
