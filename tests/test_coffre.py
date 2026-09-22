"""Une lecture large de la configuration ne doit plus rendre une VALEUR de secret.

Le 22/09/2026 le defaut a mordu pour de vrai : un filtre de lecture cherchant
<< modal >> dans la configuration a fait sortir `MODAL_TOKEN_ID` et
`MODAL_TOKEN_SECRET` dans un transcript, et les deux jetons ont du etre revoques
puis regeneres. Ce n'etait pas une inattention isolee : tant que les valeurs sont
en clair, TOUTE lecture large les emporte -- un grep, un journal, une sauvegarde,
une capture d'ecran.

Ce fichier reproduit exactement ce geste : ouvrir les fichiers du dossier de
configuration et y chercher un mot. Il exige que la VALEUR n'en sorte pas, et que
les NOMS, eux, restent lisibles -- savoir quels services sont branches n'est pas
un secret, et un magasin illisible en entier serait un magasin qu'on ne sait plus
reparer a la main.

IL NE LIT JAMAIS LE DOSSIER DE LA MACHINE. Il fait ecrire le code dans un dossier
jetable, puis relit ce dossier-la. Un cliquet qui lit la machine rend un verdict
different sur le runner : defaut paye le 22/09/2026, CI rouge
(SP-CLIQUET-QUI-LIT-LA-MACHINE).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import charger  # noqa: E402,F401  (charger sert aux tests d'identite)

# Une valeur qui ne ressemble a rien d'autre dans le depot : si elle sort quelque
# part, c'est par le magasin et par lui seul.
SECRET = "sk-valeur-temoin-qui-ne-doit-jamais-sortir-0123456789"


def fichiers_qui_portent(dossier: Path, valeur: str) -> list[Path]:
    """Tout fichier du dossier dont les octets contiennent cette valeur.

    La barre la plus dure, et la seule qui tienne : peu importe le filtre
    qu'emploie celui qui lit, la valeur ne doit etre nulle part."""
    porteurs = []
    for chemin in sorted(dossier.rglob("*")):
        if not chemin.is_file():
            continue
        try:
            octets = chemin.read_bytes()
        except OSError:
            continue
        if valeur.encode("utf-8") in octets:
            porteurs.append(chemin)
    return porteurs


def lecture_large(dossier: Path, motif: str) -> list[str]:
    """LE GESTE QUI A FUI, reproduit : chercher un mot dans la configuration.

    Rend le texte de chaque fichier ou le mot apparait -- c'est-a-dire ce qui
    atterrit sous les yeux de celui qui lance le filtre."""
    sortie = []
    for chemin in sorted(dossier.rglob("*")):
        if not chemin.is_file():
            continue
        try:
            texte = chemin.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if motif.lower() in texte.lower():
            sortie.append(texte)
    return sortie


# --- 1. Le geste qui a fui, sur les deux magasins -----------------------------


def test_une_lecture_large_ne_rend_PAS_le_jeton_du_bac_a_sable(sandbox):
    """Le cas exact du 22/09 : un filtre << modal >> sur la configuration."""
    sandbox.store_key("MODAL_TOKEN_SECRET", SECRET)
    dossier = Path(sandbox.CONFIG_DIR)

    vus = lecture_large(dossier, "modal")
    assert vus, "aucun fichier trouve : le test ne prouverait rien"
    for texte in vus:
        assert SECRET not in texte, "le filtre << modal >> ramene encore la valeur"


def test_une_lecture_large_ne_rend_PAS_la_cle_du_routeur(routeur):
    """L'autre magasin, celui que le sous-plan ne nommait pas -- et c'est LUI qui
    porte de vraies cles sur l'installation du proprietaire (mesure le 22/09)."""
    routeur.store_key("GEMINI_API_KEY", SECRET)
    dossier = Path(routeur.CONFIG_DIR)

    vus = lecture_large(dossier, "gemini")
    assert vus, "aucun fichier trouve : le test ne prouverait rien"
    for texte in vus:
        assert SECRET not in texte, "le filtre << gemini >> ramene encore la valeur"


# --- 2. La barre dure : quel que soit le filtre --------------------------------


def test_la_valeur_n_est_nulle_part_dans_le_dossier_du_bac_a_sable(sandbox):
    sandbox.store_key("MODAL_TOKEN_SECRET", SECRET)
    porteurs = fichiers_qui_portent(Path(sandbox.CONFIG_DIR), SECRET)
    assert porteurs == [], "la valeur est en clair dans %s" % [p.name for p in porteurs]


def test_la_valeur_n_est_nulle_part_dans_le_dossier_du_routeur(routeur):
    routeur.store_key("GEMINI_API_KEY", SECRET)
    porteurs = fichiers_qui_portent(Path(routeur.CONFIG_DIR), SECRET)
    assert porteurs == [], "la valeur est en clair dans %s" % [p.name for p in porteurs]


# --- 3. Les deux bras qui empechent la garde d'etre satisfaite par la perte ----
#
# Sans eux, effacer le magasin ferait passer tout ce qui precede. Une garde qui
# se satisfait d'une perte de donnee n'est pas une garde.


def test_le_secret_reste_LISIBLE_par_le_code_qui_en_a_besoin(sandbox):
    sandbox.store_key("MODAL_TOKEN_SECRET", SECRET)
    assert sandbox.stored_keys().get("MODAL_TOKEN_SECRET") == SECRET


def test_la_cle_reste_LISIBLE_cote_routeur(routeur):
    routeur.store_key("GEMINI_API_KEY", SECRET)
    assert routeur.stored_keys().get("GEMINI_API_KEY") == SECRET


def test_les_NOMS_restent_lisibles_en_clair(sandbox):
    """Savoir quels services sont branches n'est pas un secret, et le lire sans
    outil est ce qui permet de reparer une installation a la main."""
    sandbox.store_key("MODAL_TOKEN_ID", SECRET)
    brut = (Path(sandbox.CONFIG_DIR) / "sandbox-keys.json").read_text(encoding="utf-8")
    assert "MODAL_TOKEN_ID" in brut


def test_effacer_un_secret_l_efface_vraiment(sandbox):
    sandbox.store_key("MODAL_TOKEN_SECRET", SECRET)
    sandbox.store_key("MODAL_TOKEN_SECRET", "")
    assert "MODAL_TOKEN_SECRET" not in sandbox.stored_keys()
    assert fichiers_qui_portent(Path(sandbox.CONFIG_DIR), SECRET) == []


# --- 4. Le mode de perte, trouve par relecture adverse le 22/09/2026 ----------
#
# Le scenario : la cle du coffre disparait (dossier efface, ligne de .env
# changee) -> les valeurs ne s'ouvrent plus -> l'utilisateur colle UNE cle sur
# /cles -> si l'ecriture repartait des valeurs LUES, le fichier serait reecrit
# avec cette seule cle et les autres seraient detruites en silence, sous un
# message << enregistree >>. `docs/SAUVEGARDES.md` atteste qu'il n'existe aucune
# autre copie.
#
# La parade est dans la forme : `store_key` repart du fichier BRUT, jamais des
# valeurs ouvertes. Illisible se repare, efface non.


def test_une_cle_de_coffre_PERDUE_n_efface_pas_les_autres_secrets(sandbox, monkeypatch,
                                                                  tmp_path):
    import json

    sandbox.store_key("MODAL_TOKEN_ID", SECRET)
    sandbox.store_key("MODAL_TOKEN_SECRET", "second-secret-temoin")

    # La cle s'en va : le coffre en engendrera une neuve, qui n'ouvre pas l'ancien.
    monkeypatch.setenv("STUDIO_COFFRE_FICHIER", str(tmp_path / "coffre-neuf.cle"))

    # L'utilisateur, voyant << non configure >>, recolle quelque chose.
    sandbox.store_key("KAGGLE_KEY", "cle-kaggle-neuve")

    brut = json.loads((Path(sandbox.CONFIG_DIR) / "sandbox-keys.json")
                      .read_text(encoding="utf-8"))
    assert set(brut) == {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "KAGGLE_KEY"}, (
        "une cle perdue a fait disparaitre les secrets qu'elle n'ouvrait plus")


def test_une_valeur_illisible_est_ECARTEE_et_non_devinee(sandbox, monkeypatch, tmp_path):
    """Ecartee, pas rendue fausse : mieux vaut << non configure >> qu'une
    authentification avec une valeur inventee."""
    sandbox.store_key("MODAL_TOKEN_ID", SECRET)
    monkeypatch.setenv("STUDIO_COFFRE_FICHIER", str(tmp_path / "autre.cle"))
    assert "MODAL_TOKEN_ID" not in sandbox.stored_keys()


# --- 5. La migration d'un magasin d'avant le coffre ---------------------------


def test_un_magasin_EN_CLAIR_se_ferme_au_demarrage(sandbox):
    import json

    fichier = Path(sandbox.CONFIG_DIR) / "sandbox-keys.json"
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(json.dumps({"MODAL_TOKEN_ID": SECRET}), encoding="utf-8")

    assert sandbox.migrer_le_magasin() is True
    assert fichiers_qui_portent(Path(sandbox.CONFIG_DIR), SECRET) == []
    assert sandbox.stored_keys()["MODAL_TOKEN_ID"] == SECRET
    # Deux fois de suite ne refait rien : le prefixe rend la question decidable.
    assert sandbox.migrer_le_magasin() is False


def test_la_migration_NE_TOUCHE_PAS_une_valeur_deja_fermee(sandbox, monkeypatch, tmp_path):
    """Rechiffrer en passant par la lecture effacerait ce que la cle n'ouvre
    pas. Une valeur deja fermee est recopiee octet pour octet."""
    import json

    sandbox.store_key("MODAL_TOKEN_ID", SECRET)
    fichier = Path(sandbox.CONFIG_DIR) / "sandbox-keys.json"
    ferme_avant = json.loads(fichier.read_text(encoding="utf-8"))["MODAL_TOKEN_ID"]

    monkeypatch.setenv("STUDIO_COFFRE_FICHIER", str(tmp_path / "autre.cle"))
    donnees = json.loads(fichier.read_text(encoding="utf-8"))
    donnees["GROQ_API_KEY"] = "encore-en-clair"
    fichier.write_text(json.dumps(donnees), encoding="utf-8")

    assert sandbox.migrer_le_magasin() is True
    apres = json.loads(fichier.read_text(encoding="utf-8"))
    assert apres["MODAL_TOKEN_ID"] == ferme_avant, "une valeur fermee a ete touchee"
    assert apres["GROQ_API_KEY"].startswith(sandbox.coffre.PREFIXE)


# --- 6. Refuser plutot que parier ---------------------------------------------


def test_sans_endroit_ou_poser_une_cle_on_REFUSE_au_lieu_d_ecrire_en_clair(
        sandbox, monkeypatch, tmp_path):
    """Retomber en clair << juste cette fois >> serait le defaut du 22/09 refait
    en silence. Un fichier ordinaire tient lieu de dossier impossible."""
    import pytest

    barrage = tmp_path / "pas-un-dossier"
    barrage.write_text("", encoding="utf-8")
    monkeypatch.setenv("STUDIO_COFFRE_FICHIER", str(barrage / "coffre.cle"))

    with pytest.raises(sandbox.coffre.CoffreSansCle):
        sandbox.store_key("MODAL_TOKEN_ID", SECRET)
    assert fichiers_qui_portent(Path(sandbox.CONFIG_DIR), SECRET) == []


# --- 7. Ce que les deux gloses affirment, et que rien ne verifiait ------------


def test_les_deux_exemplaires_du_coffre_sont_identiques():
    """Meme remede que pour garde_exposition.py : deux images, deux contextes de
    construction, et le contexte ne peut pas etre la racine du depot."""
    racine = Path(__file__).resolve().parents[1]
    copies = [racine / "free-tier-manager" / "coffre.py",
              racine / "sandbox-manager" / "coffre.py"]
    octets = {c.read_bytes() for c in copies}
    assert len(octets) == 1, "les deux exemplaires de coffre.py divergent"


def test_le_fichier_de_cle_ne_porte_AUCUN_nom_de_service(sandbox):
    """La glose affirme qu'un filtre par nom ne ramene jamais la cle. Sans ce
    test, c'est une affirmation."""
    sandbox.store_key("MODAL_TOKEN_ID", SECRET)
    contenu = sandbox.coffre.chemin_de_la_cle().read_bytes().decode("ascii", "replace")
    for mot in ("modal", "kaggle", "gemini", "groq", "openrouter", "token", "key"):
        assert mot not in contenu.lower(), "la cle porte le mot << %s >>" % mot


def test_deux_services_qui_demarrent_ENSEMBLE_ne_se_volent_pas_la_cle(sandbox,
                                                                      tmp_path):
    """Sans O_EXCL, chacun engendrerait la sienne, la derniere ecrite gagnerait,
    et le magasin de l'autre deviendrait illisible -- au PREMIER demarrage.

    Il faut appeler `_engendrer` DIRECTEMENT. Passer par `cle()` ne prouve rien :
    elle lit le fichier avant d'engendrer, donc le second appel rend la cle lue
    sans jamais atteindre le code eprouve ici. Ecrit d'abord comme cela, le test
    ne pouvait pas echouer -- c'est le rituel de mutation qui l'a montre, en
    attribuant la faute a un autre test que lui."""
    chemin = tmp_path / "partagee.cle"

    premiere = sandbox.coffre._engendrer(chemin)
    seconde = sandbox.coffre._engendrer(chemin)

    assert premiere == seconde, "le second service a ecrase la cle du premier"
    assert chemin.read_bytes().strip() == premiere


# --- 8. L'appel au demarrage, et non la seule fonction -----------------------
#
# `migrer_le_magasin()` peut etre parfaite et n'etre appelee nulle part. Les
# tests du paragraphe 5 l'appellent a la main ; ceux-ci chargent le service comme
# le conteneur le charge, et regardent le fichier apres.


def _service_demarre_sur(dossier, monkeypatch, quoi):
    """Plante un magasin EN CLAIR, puis charge le service par-dessus."""
    import json
    import os

    dossier.mkdir(parents=True, exist_ok=True)
    for nom, contenu in quoi.items():
        (dossier / nom).write_text(json.dumps(contenu), encoding="utf-8")
    monkeypatch.setenv("FREE_AI_CONFIG_DIR", str(dossier))
    for nom in ("STUDIO_HEBERGE", "STUDIO_ADRESSE_PUBLIEE"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("SANDBOX_REPRISE_AU_DEMARRAGE", "false")
    monkeypatch.setattr(os, "chown", lambda *args: None, raising=False)


def test_le_bac_a_sable_FERME_son_magasin_en_demarrant(monkeypatch, tmp_path):
    dossier = tmp_path / "config"
    _service_demarre_sur(dossier, monkeypatch,
                         {"sandbox-keys.json": {"MODAL_TOKEN_ID": SECRET}})
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-sandbox-de-test")

    studio = charger("sandbox-manager")

    assert fichiers_qui_portent(dossier, SECRET) == [], (
        "le magasin est encore en clair apres un demarrage")
    assert studio.stored_keys()["MODAL_TOKEN_ID"] == SECRET


def test_le_routeur_FERME_son_magasin_en_demarrant(monkeypatch, tmp_path):
    dossier = tmp_path / "config"
    _service_demarre_sur(dossier, monkeypatch,
                         {"keys.json": {"GEMINI_API_KEY": SECRET}})
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-interne-de-test")

    routeur = charger("free-tier-manager")

    assert fichiers_qui_portent(dossier, SECRET) == [], (
        "le magasin est encore en clair apres un demarrage")
    assert routeur.stored_keys()["GEMINI_API_KEY"] == SECRET
