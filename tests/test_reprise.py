"""Reprendre les travaux qu'un redemarrage a laisses sans personne derriere eux.

Decision du proprietaire, 22/09/2026 : **readopter**. Retrouver la machine par
son etiquette et la suivre de nouveau, plutot que couper la depense -- le
fichier est sauve.

Ce que ces tests protegent, et qui a ete MESURE avant d'etre ecrit :

- Un travail Modal cree a 13:22:25 a survecu a la recreation du gestionnaire de
  13:26. Le compteur reel est monte 5,1979 -> 5,3268 -> 5,4417 $, soit quatre
  minutes de facturation apres que plus personne ne suivait.
- Un travail Kaggle est a `running` depuis le 09/09/2026 09:46, soit **318 h**.
  Il a pourtant DEUX delais : le `-t` remis a Kaggle, qui arrete le notebook
  lui-meme, et `deadline = pousse + limite + marge` dans la boucle d'attente.
  Aucun des deux n'a pu jouer, parce que les deux vivent dans le fil de suivi.
  **Un delai qui vit dans un fil ne se declenche que si quelqu'un regarde
  encore.** C'est pour cela que la reprise reapplique l'echeance d'ORIGINE et
  ne repart jamais d'une horloge neuve.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "sandbox-manager"))

import reprise  # noqa: E402


def fiche(**champs) -> dict:
    """Une fiche de travail minimale, que chaque test complete."""
    base = {"id": "a" * 32, "status": "running", "provider": "modal",
            "provider_effective": "modal", "created_at": 1_000_000.0,
            "started_at": 1_000_000.0}
    base.update(champs)
    return base


# --- Ce qu'on fait d'une fiche, selon qui la tenait -------------------------

def test_un_travail_reste_running_n_est_pas_laisse_tel_quel():
    """Le defaut, dans sa forme la plus simple : rien ne regardait."""
    assert reprise.que_faire(fiche()) == reprise.REPRENDRE_MODAL


def test_un_travail_modal_se_retrouve_par_son_ETIQUETTE_pas_par_remote_ref():
    """`remote_ref` n'est ecrit qu'a la FIN (app.py:677).

    Une reprise qui s'appuierait dessus ne retrouverait donc QUE les travaux
    qui n'ont pas besoin d'elle. L'etiquette `free-ai-studio-job`, elle, est
    posee des la creation de la machine (app.py:584) -- c'est deja le
    raisonnement de `arreter_modal()`, ecrit le 17/09, et il a tenu ce soir sur
    un travail qui n'avait aucun `remote_ref`.
    """
    sans = fiche()
    assert "remote_ref" not in sans
    assert reprise.que_faire(sans) == reprise.REPRENDRE_MODAL


@pytest.mark.parametrize("statut", ["queued", "routing", "preparing",
                                    "submitting", "running"])
def test_tous_les_statuts_vivants_sont_repris(statut):
    """Un travail coupe entre l'envoi et le lancement est orphelin aussi."""
    assert reprise.que_faire(fiche(status=statut)) != reprise.RIEN


@pytest.mark.parametrize("statut", ["succeeded", "failed", "cancelled"])
def test_un_travail_deja_fini_n_est_PAS_repris(statut):
    """Reprendre un travail fini le relancerait, ou ecraserait son resultat."""
    assert reprise.que_faire(fiche(status=statut)) == reprise.RIEN


def test_un_travail_LOCAL_ne_peut_pas_etre_repris_et_le_DIT():
    """Le calcul local est mort avec le conteneur. On ne fait pas semblant.

    Il n'y a rien a retrouver : le processus vivait dans l'image qu'on vient de
    remplacer. La fiche doit le dire avec un motif nomme, et surtout pas rester
    a `running` -- c'est ce mensonge-la qui dure depuis treize jours.
    """
    assert reprise.que_faire(fiche(provider="local",
                                   provider_effective="local")) == reprise.ORPHELIN


def test_un_travail_kaggle_SANS_reference_est_orphelin():
    """Sans `remote_ref`, personne ne sait quel notebook interroger."""
    assert reprise.que_faire(fiche(provider="kaggle",
                                   provider_effective="kaggle")) == reprise.ORPHELIN


def test_un_travail_kaggle_AVEC_sa_reference_se_reprend():
    """`remote_ref` est ecrit AVANT la poussee (app.py:953), donc il est la."""
    k = fiche(provider="kaggle", provider_effective="kaggle",
              remote_ref="moi/free-ai-studio-abc")
    assert reprise.que_faire(k) == reprise.REPRENDRE_KAGGLE


# --- La question du proprietaire, devenue un test --------------------------

def test_un_travail_kaggle_garde_son_echeance_D_ORIGINE():
    """<< Pourquoi pas de timeout pour Kaggle ? >> -- il y en a deux.

    Le `-t` remis a Kaggle et la boucle d'attente du Studio. Les deux vivent
    dans le fil de suivi, et le fil meurt avec le conteneur. La reprise doit
    donc recalculer l'echeance depuis `started_at`, jamais depuis maintenant :
    une horloge neuve offrirait une heure de plus a un travail vieux de treize
    jours, et le ferait patienter pour rien.
    """
    vieux = fiche(provider="kaggle", provider_effective="kaggle",
                  remote_ref="moi/free-ai-studio-816909b63c78",
                  started_at=1_000_000.0)
    # 3 600 s de limite, 300 s de marge : l'echeance est a started_at + 3 900.
    assert reprise.echeance_kaggle(vieux, limite=3600, marge=300) == 1_003_900.0
    # Et elle est DEPASSEE des que l'horloge est plus loin -- ici, treize jours.
    assert reprise.echeance_depassee(vieux, limite=3600, marge=300,
                                     maintenant=1_000_000.0 + 318 * 3600)
    # Elle ne l'est pas pour un travail qui vient de partir.
    assert not reprise.echeance_depassee(vieux, limite=3600, marge=300,
                                         maintenant=1_000_060.0)


def test_une_fiche_sans_heure_de_depart_ne_se_voit_pas_offrir_une_horloge_neuve():
    """Pas d'heure de depart : on prend celle de creation, jamais maintenant."""
    sans = {"id": "b" * 32, "status": "running", "provider": "kaggle",
            "provider_effective": "kaggle", "remote_ref": "moi/x",
            "created_at": 500.0}
    assert reprise.echeance_kaggle(sans, limite=10, marge=1) == 511.0

    # Et une fiche qui n'a NI l'une NI l'autre -- le cas que le rituel de
    # mutation du 22/09 a trouve muet : le test portait ce nom mais donnait
    # quand meme un `created_at`. Sans aucune heure, le depart vaut zero,
    # donc l'echeance est deja passee et le travail est ramasse tout de
    # suite. C'est le bon sens du penchant : une heure inconnue ne vaut
    # jamais maintenant, sinon un travail sans heure serait immortel.
    rien = {"id": "c" * 32, "status": "running", "provider": "kaggle",
            "provider_effective": "kaggle", "remote_ref": "moi/x"}
    assert reprise.depart(rien) == 0.0
    assert reprise.echeance_kaggle(rien, limite=10, marge=1) == 11.0
    assert reprise.echeance_depassee(rien, limite=10, marge=1,
                                     maintenant=1_000_000.0)
    # Une heure a zero, negative ou booleenne n'est pas une heure.
    for fausse in (0, -5.0, True, "hier", None):
        assert reprise.depart({"started_at": fausse}) == 0.0, fausse


# --- Ce que la boite dit d'elle-meme ---------------------------------------

def test_le_travail_encore_en_cours_dans_la_boite_est_ATTENDU_pas_ramasse():
    """La machine Modal est un `sleep` : elle vit APRES la fin du calcul.

    `Sandbox.create("sleep", duree)` (app.py:572) veut dire que `poll()` rend
    None tant que la duree n'est pas ecoulee, MEME si le python du client est
    fini depuis longtemps. Demander a la machine si elle tourne ne repond donc
    pas a la question posee. La seule reponse est de chercher le processus.
    """
    assert not reprise.travail_fini_dans_la_boite("4127\n")
    assert reprise.travail_fini_dans_la_boite("")
    assert reprise.travail_fini_dans_la_boite("   \n")


def test_une_sortie_de_sonde_illisible_ne_vaut_PAS_termine():
    """Un sondeur separe << pas ENCORE >> de << JAMAIS >>.

    Si la sonde ne repond pas, on ne conclut pas que le calcul est fini : on le
    dirait fini et on ramasserait un dossier a moitie ecrit.
    """
    assert not reprise.travail_fini_dans_la_boite(None)


# --- La reprise ne fabrique jamais un succes -------------------------------

def test_la_machine_disparue_ne_devient_JAMAIS_un_succes(sandbox, monkeypatch):
    """Elle a fini pendant notre absence, et on ne sait pas comment.

    Le seul resultat honnete est un echec nomme. Ecrire << succeeded >> parce
    qu'on ne trouve plus la machine, ce serait fabriquer un resultat.
    """
    jid = "c" * 32
    sandbox.write_job(jid, {"id": jid, "status": "running", "provider": "modal",
                            "provider_effective": "modal",
                            "created_at": 1.0, "started_at": 1.0})

    # Modal ne connait plus cette etiquette : la machine est partie.
    monkeypatch.setattr(sandbox, "boites_du_travail", lambda _jid: [])

    constat = sandbox.reprendre_les_travaux()

    apres = sandbox.read_job(jid)
    assert apres["status"] != "succeeded", apres
    assert apres["status"] == "failed", apres
    assert "reprise" in (apres.get("error") or "").lower(), apres.get("error")
    assert constat["repris"] >= 0 and constat["orphelins"] >= 1, constat


def test_un_travail_fini_pendant_l_absence_rend_son_FICHIER(sandbox, monkeypatch):
    """Le point de la decision << readopter >> : le fichier est sauve.

    La machine est encore la, le calcul est fini, ses fichiers sont dedans. La
    reprise les descend et la fiche passe a `succeeded` -- pas parce qu'on l'a
    decide, mais parce qu'on a ramasse quelque chose.
    """
    jid = "d" * 32
    sandbox.write_job(jid, {"id": jid, "status": "running", "provider": "modal",
                            "provider_effective": "modal",
                            "created_at": 1.0, "started_at": 1.0})

    class BoiteFinie:
        object_id = "sb-essai"

        def poll(self):
            return None  # le `sleep` tourne encore : ca ne dit RIEN du calcul

    ramasses = []

    monkeypatch.setattr(sandbox, "boites_du_travail", lambda _jid: [BoiteFinie()])
    monkeypatch.setattr(sandbox, "processus_du_travail", lambda _b: "")  # fini
    monkeypatch.setattr(sandbox, "ramasser_la_boite",
                        lambda _b, _jid: ramasses.append(_jid) or
                        [{"name": "0000-video.mp4", "source": "modal"}])

    constat = sandbox.reprendre_les_travaux()

    apres = sandbox.read_job(jid)
    assert ramasses == [jid], ramasses
    assert apres["status"] == "succeeded", apres
    assert apres["artifacts"] and apres["artifacts"][0]["name"] == "0000-video.mp4"
    assert constat["repris"] == 1, constat


def test_la_reprise_ne_touche_pas_un_travail_deja_clos(sandbox, monkeypatch):
    """Un cliquet : elle ne doit pas relancer ce qui est fini."""
    jid = "e" * 32
    sandbox.write_job(jid, {"id": jid, "status": "succeeded", "provider": "modal",
                            "provider_effective": "modal", "created_at": 1.0,
                            "artifacts": [{"name": "deja.mp4", "source": "modal"}]})

    appels = []
    monkeypatch.setattr(sandbox, "boites_du_travail",
                        lambda _jid: appels.append(_jid) or [])

    sandbox.reprendre_les_travaux()

    assert appels == [], appels
    assert sandbox.read_job(jid)["status"] == "succeeded"
def test_une_boite_retrouvee_mais_VIDE_ne_devient_PAS_un_succes(sandbox, monkeypatch):
    """Retrouver la machine n'est pas ramasser un fichier.

    Le statut se DEDUIT de ce qu'on a ramasse. Une machine vide veut dire qu'on
    ne sait pas ce qui s'y est passe pendant l'absence du Studio : l'ecrire
    << succeeded >> parce qu'on a retrouve la boite serait fabriquer un
    resultat, et le client ouvrirait un travail reussi sans fichier.
    """
    jid = "f" * 32
    sandbox.write_job(jid, {"id": jid, "status": "running", "provider": "modal",
                            "provider_effective": "modal",
                            "created_at": 1.0, "started_at": 1.0})

    class Boite:
        object_id = "sb-vide"

    monkeypatch.setattr(sandbox, "boites_du_travail", lambda _jid: [Boite()])
    monkeypatch.setattr(sandbox, "processus_du_travail", lambda _b: "")
    monkeypatch.setattr(sandbox, "ramasser_la_boite", lambda _b, _jid: [])

    constat = sandbox.reprendre_les_travaux()

    apres = sandbox.read_job(jid)
    assert apres["status"] == "failed", apres
    assert "aucun fichier" in (apres.get("error") or "").lower(), apres.get("error")
    assert constat["repris"] == 0 and constat["orphelins"] == 1, constat


def test_un_travail_qu_on_n_a_pas_su_JOINDRE_reste_INTACT(sandbox, monkeypatch):
    """Un sondeur separe << pas ENCORE >> de << JAMAIS >>.

    Modal injoignable -- reseau coupe, jeton absent, service en panne -- n'est
    PAS la meme chose que << plus aucune machine ne porte cette etiquette >>.
    Confondre les deux ferait fermer en echec, au premier redemarrage hors
    ligne, tous les travaux en cours. La fiche doit rester exactement comme
    elle etait, et le constat doit le compter a part.
    """
    jid = "g" * 32
    sandbox.write_job(jid, {"id": jid, "status": "running", "provider": "modal",
                            "provider_effective": "modal",
                            "created_at": 1.0, "started_at": 1.0})

    monkeypatch.setattr(sandbox, "boites_du_travail", lambda _jid: None)

    constat = sandbox.reprendre_les_travaux()

    apres = sandbox.read_job(jid)
    assert apres["status"] == "running", apres
    assert "error" not in apres, apres
    assert constat["non_mesures"] == 1, constat
    assert constat["orphelins"] == 0, constat


# --- La vraie sonde, pas un leurre -----------------------------------------

class _ModalQuiTombe:
    """Un Modal dont la recherche echoue -- reseau coupe, service en panne."""

    class App:
        @staticmethod
        def lookup(nom, create_if_missing=False):
            raise ConnectionError("modal injoignable")


class _ModalQuiRepondVide:
    """Un Modal qui repond, et ne connait aucune machine pour ce travail."""

    class App:
        @staticmethod
        def lookup(nom, create_if_missing=False):
            return type("A", (), {"app_id": "ap-1"})()

    class Sandbox:
        @staticmethod
        def list(app_id=None, tags=None):
            return iter(())


@pytest.mark.parametrize("faux, attendu, ce_que_ca_veut_dire", [
    (_ModalQuiTombe, None, "on n'a pas pu demander"),
    (_ModalQuiRepondVide, [], "on a demande, il n'y a plus rien"),
])
def test_la_sonde_MODAL_separe_pas_su_demander_de_plus_rien(
        sandbox, monkeypatch, faux, attendu, ce_que_ca_veut_dire):
    """Le meme bras que ci-dessus, mais sur la VRAIE fonction.

    Le test voisin remplace `boites_du_travail` par un leurre : il verifie ce
    que la reprise fait d'un None, pas que la sonde en rende un. Le rituel de
    mutation du 22/09 l'a montre en changeant `return None` en `return []`
    dans la vraie fonction -- les 22 tests sont restes verts. Un leurre teste
    le test.
    """
    monkeypatch.setitem(sys.modules, "modal", faux)
    monkeypatch.setattr(sandbox, "apply_stored_secrets", lambda: None)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)

    assert sandbox.boites_du_travail("d" * 32) == attendu, ce_que_ca_veut_dire


def test_modal_NON_CONFIGURE_ne_vaut_pas_machine_partie(sandbox, monkeypatch):
    """Pas de jeton : on n'a pas pu demander. La fiche reste intacte.

    C'est le cas du redemarrage de 13:26 : le conteneur est remonte sans la
    carte, et un gestionnaire qui lirait cela comme << plus aucune machine >>
    fermerait en echec un travail qui, lui, facturait encore.
    """
    monkeypatch.setitem(sys.modules, "modal", _ModalQuiRepondVide)
    monkeypatch.setattr(sandbox, "apply_stored_secrets", lambda: None)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: False)

    assert sandbox.boites_du_travail("e" * 32) is None


# --- Une reprise silencieuse ne se distingue pas d'une reprise absente ------

def test_la_reprise_DIT_ce_qu_elle_a_fait_MEME_quand_il_n_y_a_rien(
        sandbox, monkeypatch, tmp_path, caplog):
    """Le silence de << rien a faire >> et celui de << ca n'a pas tourne >>.

    Mesure du 22/09/2026 : redeploiement reel, le temoin Kaggle de 318 h s'est
    bien ferme -- statut `failed`, motif nomme dans sa fiche -- et le journal
    du gestionnaire ne portait AUCUNE ligne de reprise. Le constat chiffre
    etait calcule, rendu, puis jete par le fil qui l'appelait. C'est le defaut
    que je reproche au code depuis ce soir, dans mon propre code : un sondeur
    separe << pas ENCORE >> de << JAMAIS >>, et un journal muet ne separe
    rien.

    Le dossier des fiches est POSE VIDE, et ce n'est pas un detail : l'espace
    de travail est partage par toute la suite, si bien que `laisses` n'y est
    jamais a zero. Ecrit sans cela, ce test portait son nom sans jouer son
    cas -- la mutation << ne parler que s'il s'est passe quelque chose >> le
    laissait vert. Meme faute que le matin meme, et trouvee de la meme facon :
    un test nomme d'apres un cas qu'il n'atteint pas.
    """
    vide = tmp_path / "aucune-fiche"
    vide.mkdir()
    monkeypatch.setattr(sandbox, "JOBS", vide)

    with caplog.at_level(logging.INFO, logger="sandbox-manager"):
        constat = sandbox.reprise_au_demarrage()

    # Les CINQ a zero : il n'y a vraiment rien, et c'est le cas qu'on teste.
    assert constat == {"repris": 0, "attendus": 0, "orphelins": 0,
                       "non_mesures": 0, "laisses": 0}, constat
    dit = "\n".join(r.getMessage() for r in caplog.records)
    assert "eprise" in dit, dit
    # Les CINQ compteurs, pas seulement ceux qui ne sont pas a zero : un zero
    # est une reponse, et c'est meme la seule qu'on lise les bons jours.
    for mot in ("repris", "attendus", "orphelins", "non mesures", "laisses"):
        assert mot in dit, (mot, dit)


def test_une_reprise_qui_TOMBE_le_dit_au_lieu_de_se_taire(sandbox, monkeypatch, caplog):
    """Un fil daemon qui leve meurt sans un mot. C'est le pire des silences.

    Il ressemble trait pour trait a << il n'y avait rien a faire >>, et c'est
    exactement l'inverse : rien n'a ete regarde.
    """
    def tombe():
        raise RuntimeError("le disque des fiches est illisible")

    monkeypatch.setattr(sandbox, "reprendre_les_travaux", tombe)

    with caplog.at_level(logging.INFO, logger="sandbox-manager"):
        constat = sandbox.reprise_au_demarrage()

    assert constat.get("echec") == "RuntimeError", constat
    dit = "\n".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in dit or "illisible" in dit, dit


def test_aucun_module_charge_sous_test_ne_lance_la_reprise_tout_seul():
    """Charge SANS la fixture, comme test_kaggle : aucun fil de reprise.

    24/09/2026 : un tel fil, parti d'un module voisin, lisait la fiche d'un
    test en cours, la declarait orpheline et la reecrivait apres coup -- la
    fiche finie chez Modal redevenait << local >>. C'etait l'echec
    intermittent de test_local_d_abord. La regle vit dans conftest.py.
    """
    import threading

    from conftest import charger
    avant = {id(t) for t in threading.enumerate()}
    module = charger("sandbox-manager")
    nouveaux = [t.name for t in threading.enumerate() if id(t) not in avant]
    assert module.REPRISE_AU_DEMARRAGE is False
    assert "reprise-travaux" not in nouveaux, nouveaux
