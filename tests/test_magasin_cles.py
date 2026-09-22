"""Qui a le droit d'activer un backend : le magasin, et AUSSI le .env (22/09/2026).

`modal_enabled()` acceptait deux sources d'activation : l'interrupteur
`MODAL_ENABLED=true`, ou la presence des deux jetons **dans le magasin**. Il ne
regardait jamais le .env. Consequence mesuree ce jour-la, sur l'installation du
proprietaire : des jetons Modal valides poses a la main dans `.env`, avec
`MODAL_ENABLED=false` comme le livre le depot, donnaient un Studio qui repond
<< Modal non configure >> en ayant les bons identifiants dans son environnement.

Le defaut s'est montre au pire moment : le Studio tournait, mais parce que les
ANCIENS jetons -- revoques depuis -- dormaient encore dans le magasin. C'est une
activation tenue par des identifiants morts. Vider le magasin, ce qu'il fallait
faire, debranchait Modal du meme coup.

Le motif du code d'origine s'applique tel quel au .env : << coller un jeton dans
l'interface est tout sauf accidentel >>. L'ecrire a la main dans `.env` ne l'est
pas davantage.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import charger  # noqa: E402


def studio_avec_env(monkeypatch, **variables):
    """Recharge le gestionnaire avec ces variables posees AVANT l'import.

    Passer par un vrai chargement, et non par un `ENV_SECRETS` bricole apres
    coup, est ce qui distingue ce test d'un leurre : `ENV_SECRETS` est la
    photographie de l'environnement prise a l'import, et c'est precisement
    cette photographie qui doit compter.
    """
    for nom, valeur in variables.items():
        monkeypatch.setenv(nom, valeur)
    return charger("sandbox-manager")


# --- Le .env active, comme le magasin -----------------------------------------


def test_des_jetons_modal_poses_dans_le_env_ACTIVENT_modal(sandbox, monkeypatch):
    studio = studio_avec_env(monkeypatch,
                             MODAL_TOKEN_ID="ak-du-test",
                             MODAL_TOKEN_SECRET="as-du-test")
    assert studio.stored_keys() == {}, "le magasin doit etre vide : c'est tout l'enjeu"
    assert studio.modal_enabled() is True
    assert studio.modal_configured() is True


def test_des_identifiants_kaggle_poses_dans_le_env_ACTIVENT_kaggle(sandbox, monkeypatch):
    """Meme forme, meme defaut : les deux fonctions sont jumelles."""
    studio = studio_avec_env(monkeypatch,
                             KAGGLE_USERNAME="quelquun",
                             KAGGLE_KEY="cle-du-test")
    assert studio.stored_keys() == {}
    assert studio.kaggle_enabled() is True
    assert studio.kaggle_configured() is True


# --- Le cas qui a mordu -------------------------------------------------------


def test_vider_le_magasin_ne_DEBRANCHE_pas_un_backend_tenu_par_le_env(
        sandbox, monkeypatch):
    """Le geste exact du 22/09 : des jetons neufs dans .env, des vieux au magasin.

    Le bouton << Oublier >> doit retirer les vieux sans eteindre le backend,
    puisque les neufs sont ailleurs. La route rendait `configure: false`.
    """
    studio = studio_avec_env(monkeypatch,
                             MODAL_TOKEN_ID="ak-neuf",
                             MODAL_TOKEN_SECRET="as-neuf")
    studio.store_key("MODAL_TOKEN_ID", "ak-vieux-et-revoque")
    studio.store_key("MODAL_TOKEN_SECRET", "as-vieux-et-revoque")

    studio.forget_secrets([c["nom"] for c in studio.SANDBOX_HELP["modal"]["champs"]])

    assert studio.stored_keys() == {}, "les vieux doivent avoir quitte le magasin"
    assert studio.os.environ["MODAL_TOKEN_ID"] == "ak-neuf", \
        "la valeur du .env est restauree, pas effacee"
    assert studio.modal_configured() is True, \
        "des jetons valides dans .env : le backend reste configure"


# --- Et le controle peut encore echouer ---------------------------------------


def test_sans_jeton_NULLE_PART_modal_reste_eteint(sandbox, monkeypatch):
    """Sans ce bras, `modal_enabled` pourrait rendre True en toutes circonstances.

    `MODAL_ENABLED=false` protege une installation fraiche d'un usage cloud
    accidentel : cette protection-la ne bouge pas.
    """
    studio = studio_avec_env(monkeypatch, MODAL_ENABLED="false")
    assert studio.stored_keys() == {}
    assert studio.modal_enabled() is False
    assert studio.modal_configured() is False


def test_un_jeton_SEUL_dans_le_env_n_active_rien(sandbox, monkeypatch):
    """Un identifiant sans son secret n'authentifie personne : ce n'est pas
    une activation, c'est une saisie a moitie faite."""
    studio = studio_avec_env(monkeypatch, MODAL_TOKEN_ID="ak-tout-seul")
    assert studio.modal_enabled() is False
