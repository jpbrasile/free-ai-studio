"""Le budget Modal unique, et la part reservee au bac a sable.

Decision de l'utilisateur du 19/09/2026 (docs/PLAN-PLATEFORME.md, paragraphe 8,
decision 2). Ce que ces tests gardent, defaut par defaut :

1. que les quatre usages tirent sur LE MEME total -- c'est la reparation ;
2. que la part reservee au bac a sable refuse AVANT de depenser, comme la
   reserve protegee du Boost, et non apres coup ;
3. que le bac a sable, QUATRIEME depensier, est compte -- il ne l'etait pas ;
4. que le mois en cours n'est pas perdu au passage aux trois anciens fichiers ;
5. qu'un travail SANS carte ne se voit pas facturer une carte.

Aucun appel reseau : Modal n'est jamais touche.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def budget(sandbox, monkeypatch, tmp_path):
    """Le compteur unique, dans un repertoire jetable."""
    module = sandbox.budget_modal
    monkeypatch.setattr(module, "FICHIER", tmp_path / "modal-budget.json")
    monkeypatch.setattr(module, "PLAFOND_USD", 30.0)
    monkeypatch.setattr(module, "RESERVE_AUTONOME_USD", 15.0)
    monkeypatch.setattr(module, "PART_RESERVEE_AUTONOME", 0.5)
    return module


# --- 1. Un seul total ---------------------------------------------------------

def test_les_quatre_usages_tirent_sur_le_meme_total(budget):
    """LE defaut repare : 5 + 20 + 5 = 30, trois compteurs aveugles l'un a l'autre.

    Chacun pouvait atteindre son plafond le meme mois, et le depot l'avait ecrit
    dans son propre docker-compose.yml sans le corriger.
    """
    for usage in ("video", "chanson", "dialogue", "autonome"):
        budget.consommer(usage, "L4", 100, 1024)
    etat = budget.lire()
    assert etat["appels"] == {"video": 1, "chanson": 1, "dialogue": 1, "autonome": 1}
    assert etat["usd"] == pytest.approx(sum(etat["usd_par_usage"].values()))
    # abs= : le fichier arrondit a quatre decimales a chaque ecriture, quatre
    # fois ici. Un approx serre mesurerait l'arrondi, pas le compteur.
    assert etat["usd"] == pytest.approx(
        4 * budget.prix_seconde("L4", 1024) * 100, abs=1e-3)


def test_une_depense_video_reduit_ce_qui_reste_a_la_chanson(sandbox, budget):
    """Le renversement le plus visible : les pages se voient les unes les autres."""
    avant = sandbox.chanson.budget_lire()["reste_usd"]
    budget.consommer("video", "A100", 600, 16384)
    apres = sandbox.chanson.budget_lire()["reste_usd"]
    assert apres < avant, "la chanson ne voit toujours pas ce que la video a depense"


# --- 2. La part reservee ------------------------------------------------------

def test_la_demande_humaine_s_arrete_avant_la_reserve(budget):
    """Refuser AVANT de depenser, la forme de la reserve protegee du Boost.

    A 14,90 $ depenses sur 30, il reste 15,10 $ au total mais seulement 0,10 $
    aux demandes : les 15 $ reserves ne sont pas a elles.
    """
    budget.poser("video", 0, 14.90, 1)
    with pytest.raises(budget.BudgetDepasse) as leve:
        budget.verifier("chanson", "L4", 1800, 24576, quoi="Une chanson")
    texte = str(leve.value)
    assert "réservés au mode autonome" in texte
    assert "15.00 $" in texte, "le refus doit chiffrer la reserve qu'il protege"

    # Le bac a sable, lui, peut encore travailler : c'est a cela qu'elle sert.
    budget.verifier("autonome", "L4", 1800, 24576)


def test_le_plafond_du_bac_a_sable_est_le_plafond_entier(budget):
    assert budget.plafond_de("autonome") == 30.0
    for humain in budget.USAGES_HUMAINS:
        assert budget.plafond_de(humain) == 15.0


def test_la_part_reservee_se_regle(sandbox, monkeypatch, tmp_path):
    """<< 50 %, ajustable >> : la decision dit ajustable, donc elle doit l'etre."""
    module = sandbox.budget_modal
    monkeypatch.setattr(module, "FICHIER", tmp_path / "modal-budget.json")
    monkeypatch.setattr(module, "PLAFOND_USD", 30.0)
    monkeypatch.setattr(module, "RESERVE_AUTONOME_USD", 0.0)
    assert module.plafond_de("video") == 30.0
    module.poser("video", 0, 29.0, 1)
    module.verifier("video", "T4", 60, 1024)  # ne leve pas : rien n'est reserve


def test_le_refus_de_la_chanson_dit_toujours_que_kaggle_reste_ouvert(sandbox, budget):
    """Une sortie de secours gratuite existe : un refus qui la tait se lit comme
    une panne. C'est la seule phrase propre a un usage dans le message commun."""
    budget.poser("chanson", 0, 29.99, 1)
    with pytest.raises(sandbox.chanson.BudgetDepasse) as leve:
        sandbox.chanson.budget_verifier("L4", sandbox.chanson.DUREE_MAX_S)
    assert "Kaggle reste possible, gratuitement." in str(leve.value)


def test_la_meme_exception_pour_les_quatre(sandbox, budget):
    """Il y avait trois classes BudgetDepasse distinctes : un piege arme.

    `except video.BudgetDepasse` n'attrapait pas ce que chanson.py levait.
    """
    assert sandbox.video.BudgetDepasse is budget.BudgetDepasse
    assert sandbox.chanson.BudgetDepasse is budget.BudgetDepasse
    assert sandbox.dialogue.BudgetDepasse is budget.BudgetDepasse


# --- 3. Le quatrieme depensier ------------------------------------------------

def test_le_bac_a_sable_refuse_de_louer_quand_le_plafond_est_atteint(sandbox, budget,
                                                                    monkeypatch):
    """run_auto() envoyait du code sur Modal sans passer par aucun budget.

    Le controle est pose dans modal_execute(), donc il tombe avant tout appel au
    SDK Modal -- ici absent, ce qui suffit a prouver que rien n'a ete loue.
    """
    budget.poser("autonome", 0, 29.99, 1)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    with pytest.raises(budget.BudgetDepasse):
        sandbox.modal_execute("a" * 32, "print(1)", True, False)


def test_un_refus_de_budget_ne_tue_pas_le_mode_auto(sandbox, budget, monkeypatch):
    """Le plafond atteint n'est pas une panne : le mode auto a trois suites
    gratuites. Laisser l'exception remonter laisserait le travail en
    << routing >> pour toujours, puisque run_auto() tourne dans un fil."""
    budget.poser("autonome", 0, 29.99, 1)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "local_execute",
                        lambda jid, code: {"exit_code": 0, "stdout": "", "stderr": "",
                                           "artifacts": []})
    jid = "b" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_auto(jid, "print(1)", True, False)
    job = sandbox.read_job(jid)
    assert job["status"] == "succeeded"
    assert job["provider_effective"] == "local"
    essais = {a["provider"]: a["result"] for a in job["fallback_attempts"]}
    assert essais["modal"] == "budget_exhausted"


def test_la_route_du_compteur_rend_la_repartition(sandbox, budget):
    """Les trois pages ne montrent qu'une tranche ; le quatrieme usage n'a pas de
    page. Sans cette route, il resterait invisible."""
    budget.consommer("autonome", "T4", 50, 2048)
    reponse = TestClient(sandbox.app, base_url="http://127.0.0.1:8020").get(
        "/budget/modal", headers={"Authorization": "Bearer cle-sandbox-de-test"})
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["appels"]["autonome"] == 1
    assert corps["reserve_autonome_usd"] == 15.0
    assert corps["plafond_usd"] == 30.0


# --- 4. Le mois en cours n'est pas perdu --------------------------------------

def test_les_trois_anciens_compteurs_sont_repris_une_fois(budget, tmp_path):
    """Un compteur qui oublie est un compteur qui ment.

    Et le report doit etre ECRIT : sinon il se referait a chaque lecture et
    doublerait des la premiere depense.
    """
    mois = time.strftime("%Y-%m")
    for nom, cle, usd in (("video-budget.json", "clips", 3.0),
                          ("chanson-budget.json", "chansons", 1.0),
                          ("dialogue-budget.json", "dialogues", 0.5)):
        (tmp_path / nom).write_text(json.dumps(
            {"mois": mois, "secondes": 10, "usd": usd, cle: 2}), encoding="utf-8")

    etat = budget.lire()
    assert etat["usd"] == pytest.approx(4.5)
    assert etat["appels"] == {"video": 2, "chanson": 2, "dialogue": 2, "autonome": 0}
    assert sorted(etat["repris_des_anciens"]) == [
        "chanson-budget.json", "dialogue-budget.json", "video-budget.json"]
    assert budget.FICHIER.exists(), "le report doit etre ecrit, pas refait a chaque lecture"

    budget.consommer("video", "T4", 10, 1024)
    assert budget.lire()["usd"] > 4.5
    assert budget.lire()["usd"] < 9.0, "le report a ete refait une seconde fois"
    # On n'efface rien : les anciens fichiers restent, et servent de preuve.
    assert (tmp_path / "video-budget.json").exists()


def test_un_mois_clos_n_est_pas_repris(budget, tmp_path):
    (tmp_path / "video-budget.json").write_text(json.dumps(
        {"mois": "2000-01", "secondes": 10, "usd": 99.0, "clips": 2}), encoding="utf-8")
    assert budget.lire()["usd"] == 0.0


# --- 5. Un travail sans carte ne paie pas de carte ----------------------------

def test_sans_carte_on_ne_facture_pas_de_carte(budget):
    """Le mode autonome est le seul a lancer des travaux SANS GPU.

    Les compter au prix de la carte la plus chere -- le repli prevu pour une
    carte INCONNUE -- refuserait les travaux les moins chers du service.
    """
    sans = budget.prix_seconde(None, 2048, coeurs=1.0)
    assert sans == pytest.approx(budget.PRIX_CPU_USD_S + budget.PRIX_MEMOIRE_USD_S * 2)
    assert budget.prix_seconde("", 2048, coeurs=1.0) == pytest.approx(sans)
    # Une carte INCONNUE, elle, reste comptee au prix de la plus chere connue.
    assert budget.prix_seconde("X9", 2048, coeurs=1.0) > budget.prix_seconde(
        "H100", 2048, coeurs=1.0) - 1e-12


def test_le_temps_passe_est_encaisse_meme_en_cas_d_echec(budget):
    """Une machine qui plante a quand meme ete louee."""
    budget.consommer("autonome", "T4", 120, 2048)
    assert budget.lire()["usd"] > 0
    assert budget.lire()["appels"]["autonome"] == 1


def test_un_usage_inconnu_est_refuse(budget):
    for appel in (lambda: budget.verifier("mystere", "T4", 60, 1024),
                  lambda: budget.consommer("mystere", "T4", 60, 1024),
                  lambda: budget.vue("mystere"),
                  lambda: budget.poser("mystere", 0, 1, 1)):
        with pytest.raises(ValueError):
            appel()


def test_la_date_de_remise_a_zero_est_dite_et_franchit_l_annee(budget):
    """Demande du proprietaire, 20/09/2026 : noter la date de renouvellement.

    Un credit mensuel sans sa date, c'est soit attendre pour rien alors qu'il
    est deja revenu, soit lancer un calcul qui sera refuse. La date est rendue
    par le module et non recalculee par chaque page : deux dates differentes
    sur le meme compteur seraient pires que pas de date du tout.
    """
    assert budget.premier_du_mois_suivant("2026-09") == "2026-10-01"
    # Decembre franchit l'annee : la faute que tout calcul de date oublie.
    assert budget.premier_du_mois_suivant("2026-12") == "2027-01-01"
    assert budget.premier_du_mois_suivant("2026-01") == "2026-02-01"

    etat = budget.lire()
    assert etat["compteur_remis_a_zero_le"] == budget.premier_du_mois_suivant(etat["mois"])
    # Et c'est bien une date posterieure au mois compte.
    assert etat["compteur_remis_a_zero_le"] > etat["mois"]


def test_le_champ_ne_se_fait_pas_passer_pour_la_date_de_modal(budget):
    """Le 1er du mois est a NOUS -- et le 20/09/2026 on a su d'ou vient le sien.

    Premier temps (correction du 20/09) : un << 1er du mois >> etait affiche a
    cote du nom de Modal sur la foi d'un resume de moteur de recherche. Leurs
    pages publiques disent << $30 / month free compute >> et << All Workspaces
    are billed monthly >>, sans jamais nommer un jour. Il a ete retire.

    Second temps, le meme jour, sur << mesure Modal pour moi >> : le tableau de
    bord de l'espace de travail, lui, l'ecrit -- << Billing Cycle: Sep 1 -
    Oct 1, 2026 >>. Le cycle est donc bien le mois civil ICI. Le champ garde
    pourtant son nom, parce qu'il mesure NOTRE compteur et que le cycle
    s'affiche par espace de travail : celui d'un autre client peut tomber
    ailleurs. Ce test empeche de le renommer en quelque chose qui promet plus
    qu'on ne sait, et empeche aussi d'effacer la source maintenant qu'on l'a.
    """
    etat = budget.lire()
    assert "renouvele_le" not in etat
    assert "compteur_remis_a_zero_le" in etat
    # Et la raison est ecrite la ou on la cherchera : dans le module.
    doc = budget.premier_du_mois_suivant.__doc__
    assert "Billing Cycle: Sep 1 - Oct 1, 2026" in doc     # la source, citee
    assert "20/09/2026" in doc                             # la date du releve
    assert "SON tableau de bord" in doc                    # qui fait foi


def test_le_module_dit_de_combien_il_sous_compte(budget):
    """Mesure du 20/09/2026 : le compteur voit moins de la moitie de la facture.

    La comparaison est possible parce que le proprietaire l'a remarque : les
    30 $ etaient intacts juste avant le premier usage de Modal par le Studio,
    le 09/09/2026 a 11 h. Rien d'autre n'avait tourne depuis le 1er, et les six
    jours factures du mois portent tous le nom `free-ai-studio-sandbox`. Meme
    fenetre, meme travail, deux chiffres : 1,3878 $ ici, 3,7971 $ chez Modal.

    Pourquoi un test et pas une note : un compteur qui se trompe VERS LE BAS
    laisse passer ce qu'il devrait refuser. Le module l'affirme deja pour les
    prix GPU (<< Se tromper vers le bas est exactement ce qu'un compteur de
    refus ne doit jamais faire >>) ; il le mesure maintenant sur lui-meme. Si
    quelqu'un efface l'aveu, ce test tombe.
    """
    doc = budget.__doc__
    assert "1,3878" in doc and "3,7971" in doc       # les deux chiffres compares
    assert "26,20" in doc                            # le reste reellement annonce
    assert "09/09/2026" in doc                       # le t0 qui rend l'egalite vraie
    # Et l'interdiction de << corriger >> en multipliant par le rapport mesure.
    assert "2,74" in doc and "pas un coefficient" in doc
