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
import re
import subprocess
import time
import unicodedata

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
    # Le montant attendu est FABRIQUE par le formateur, pas recopie : le jour ou
    # la reserve change, la phrase et le test bougent ensemble.
    assert _format_fr().en_dollars(budget.RESERVE_AUTONOME_USD) in texte, (
        "le refus doit chiffrer la reserve qu'il protege")

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


def test_la_cause_de_l_ecart_est_celle_qui_a_ete_mesuree(budget):
    """Question du proprietaire : << mauvaise lecture de notre part ou latence ? >>

    Les deux branches ont ete verifiees le 20/09/2026 plutot que departagees au
    raisonnement, et la premiere explication que j'avais ecrite -- le stockage --
    etait FAUSSE. Ce test grave les trois reponses mesurees :

    1. Pas la latence : Modal ecrit dans son API que les donnees arrivent
       << within minutes >>, et un retard ferait afficher MOINS, alors que c'est
       notre chiffre qui est le plus petit.
    2. Pas le stockage : le tableau de bord dit << Deployed Apps: $3.80 >>,
       stockage zero, egress non facture.
    3. C'est le prix a la seconde : Modal facture GPU 1,97 $ / memoire 1,37 $ /
       processeur 0,46 $ quand notre modele suppose 82 / 13 / 5 %. Nous traitons
       comme marginal ce que Modal facture presque a moitie.

    Et la precaution qui va avec : le 2,74 porte sur tout septembre, alors que ce
    compteur n'existe que depuis le 19/09 -- sur la seule fenetre qui lui
    appartient, le rapport mesure est 1,44 sur UN evenement.
    """
    doc = budget.__doc__
    assert "within minutes" in doc                   # la latence, ecartee par leur API
    assert "Deployed Apps: $3.80" in doc             # le stockage, ecarte par le releve
    assert "FAUSSE" in doc                           # l'erreur precedente, gardee visible
    for part in ("1,97", "1,37", "0,46"):            # la decomposition mesuree
        assert part in doc, part
    assert "1,44" in doc and "19/09" in doc          # la fenetre qui appartient a ce compteur


# --- 7. Le releve chez Modal, pris juste avant d'ecrire -----------------------

def _faux_depenses(monkeypatch, montants, disponible=True):
    """Remplace le module `depenses` par une reponse figee.

    Aucun reseau, aucun jeton : ces tests verifient le CABLAGE, pas Modal. Le
    module est importe a l'interieur de _releve_reel(), donc il suffit de le
    poser dans sys.modules.
    """
    import sys
    import types
    faux = types.ModuleType("depenses")
    faux.etat = lambda cycle="this month", forcer=False: {
        "disponible": disponible, "montants": montants,
    }
    monkeypatch.setitem(sys.modules, "depenses", faux)
    return faux


def test_le_releve_de_modal_remplace_l_estimation_quand_il_est_plus_grand(budget, monkeypatch):
    """L'ordre du proprietaire, 20/09/2026 : << il suffit de relever le compteur
    juste avant de l'ecrire >>.

    C'est la reparation du defaut mesure le meme jour -- le compteur voyait 37 %
    de la facture. Elle tient en un endroit, celui qui ECRIT, et non dans les 67
    qui lisent : le contrat de lire() ne bouge pas, seul le nombre devient vrai.
    """
    _faux_depenses(monkeypatch, {"calcul": 3.79706491, "mesure": 4.66502664})
    budget.consommer("video", "L4", 10.0, 16384)
    etat = budget.lire()
    # Le releve est ecrit, date, et c'est lui que le garde voit.
    assert etat["usd_reel"] == pytest.approx(3.7971, abs=1e-4)
    assert etat["usd_reel_le"]
    assert etat["usd"] == pytest.approx(3.7971, abs=1e-4)
    # L'estimation locale reste visible sous son nom, et elle est bien plus basse.
    assert etat["usd_estime"] < 0.1
    assert etat["reste_usd"] == pytest.approx(30.0 - 3.7971, abs=1e-4)


def test_le_releve_prend_le_calcul_et_jamais_le_cout_mesure(budget, monkeypatch):
    """`metered_cost` ajoute le stockage, que `free_storage` annule aussitot.

    Mesure du 20/09/2026 : metered_cost 4,66502664 = deployed_apps 3,79706491 +
    volumes 0,86502664, avec free_storage -0,86502664 et credits -3,80. Prendre
    `mesure` gonflerait le compteur de 0,87 $ qui ne mangent aucun credit --
    c'est-a-dire refuser des calculs pour une depense qui n'existe pas.
    """
    _faux_depenses(monkeypatch, {"calcul": 3.79706491, "mesure": 4.66502664,
                                 "stockage": 0.86502664, "credits": -3.8})
    budget.consommer("chanson", "L4", 10.0, 24576)
    assert budget.lire()["usd_reel"] == pytest.approx(3.7971, abs=1e-4)


def test_sans_reponse_de_modal_le_compteur_reste_sur_son_estimation(budget, monkeypatch):
    """Une page ne depend jamais d'un service distant.

    Sans jeton, sans reseau, ou si la commande manque : le releve rend None, et
    tout se passe comme avant -- le garde refuse sur l'estimation locale, qui
    est un plancher. C'est le comportement qu'avaient les 352 tests d'avant,
    et il ne doit pas avoir change.
    """
    _faux_depenses(monkeypatch, {}, disponible=False)
    budget.consommer("video", "L4", 10.0, 16384)
    etat = budget.lire()
    assert etat["usd_reel"] is None
    assert etat["usd"] == pytest.approx(etat["usd_estime"])
    assert etat["usd"] > 0


def test_le_releve_ne_fait_jamais_baisser_le_compteur(budget, monkeypatch):
    """Les deux nombres sont des MINORANTS, et on garde le plus grand.

    Modal previent que ses donnees arrivent << within minutes >> : juste apres
    un gros calcul, son chiffre ignore encore ce calcul-la. Si on le prenait tel
    quel, le compteur RECULERAIT, et un client pourrait relancer en boucle un
    travail que le garde vient d'accepter. Le maximum des deux l'interdit.
    """
    budget.poser("video", secondes=1000.0, usd=12.0, appels=3)
    _faux_depenses(monkeypatch, {"calcul": 0.5})     # Modal est en retard
    budget.consommer("video", "L4", 1.0, 16384)
    etat = budget.lire()
    assert etat["usd_reel"] == pytest.approx(0.5)    # le releve est garde tel quel...
    assert etat["usd"] > 12.0                        # ...mais il ne fait pas reculer le total
    assert etat["usd"] == pytest.approx(etat["usd_estime"])


# --- 8. L'amorce : le premier refus d'apres redemarrage --------------------

def test_l_amorce_pose_le_chiffre_de_modal_des_le_demarrage(budget, monkeypatch):
    """LE defaut mesure le 20/09/2026, une fois l'image reconstruite.

    Le code neuf etait en place et `lire()` rendait pourtant encore 1,3878 $ :
    `usd_reel` n'apparait qu'au premier `consommer()`. Entre le redemarrage et
    la premiere depense, le garde decidait donc sur l'estimation locale -- une
    fenetre etroite, mais qui contient UN travail, celui qu'il aurait fallu
    refuser.
    """
    budget.poser("video", secondes=4996.2, usd=1.3878, appels=29)
    assert budget.lire()["usd"] == pytest.approx(1.3878)     # le defaut, avant
    _faux_depenses(monkeypatch, {"calcul": 3.79706491})
    assert budget.amorcer() == pytest.approx(3.79706491)
    etat = budget.lire()
    assert etat["usd"] == pytest.approx(3.7971, abs=1e-4)    # repare, sans depense
    assert etat["usd_estime"] == pytest.approx(1.3878)       # l'estimation reste lisible
    assert etat["usd_reel_le"]


def test_l_amorce_ne_touche_ni_au_temps_ni_aux_usages(budget, monkeypatch):
    """Elle range un releve, elle n'encaisse rien.

    Si elle ajoutait au total local, chaque redemarrage du conteneur ferait
    monter le compteur sans qu'aucune carte ait ete louee -- un compteur qui
    grossit tout seul finirait par refuser tout.
    """
    budget.poser("chanson", secondes=100.0, usd=0.5, appels=2)
    avant = budget.lire()
    _faux_depenses(monkeypatch, {"calcul": 3.79706491})
    budget.amorcer()
    apres = budget.lire()
    assert apres["secondes"] == avant["secondes"]
    assert apres["appels"] == avant["appels"]
    assert apres["usd_par_usage"] == avant["usd_par_usage"]
    assert apres["usd_estime"] == pytest.approx(avant["usd_estime"])


def test_sans_reponse_l_amorce_n_ecrit_rien(budget, monkeypatch):
    """Modal injoignable : le demarrage se passe comme avant, sur le plancher local."""
    budget.poser("video", secondes=100.0, usd=0.5, appels=1)
    _faux_depenses(monkeypatch, {}, disponible=False)
    assert budget.amorcer() is None
    etat = budget.lire()
    assert etat["usd_reel"] is None
    assert etat["usd"] == pytest.approx(etat["usd_estime"])


def test_le_demarrage_lance_l_amorce_dans_un_fil(sandbox):
    """Le releve dure 0,85 s quand Modal repond -- et jusqu'au delai d'attente
    quand il ne repond pas. Appele tel quel, il ferait attendre le demarrage du
    conteneur sur un service distant, et un Modal muet retarderait la page de
    vingt-cinq secondes. Le fil est donc la moitie de la reparation, pas un
    detail de style.
    """
    from conftest import RACINE
    source = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    assert "budget_modal.amorcer" in source, "l'amorce n'est plus appelee au demarrage"
    debut = source.index("budget_modal.amorcer")
    autour = source[debut - 200:debut + 200]
    assert "threading.Thread" in autour, "l'amorce bloquerait le demarrage"
    assert "daemon=True" in autour, "un fil non daemon retiendrait l'arret du conteneur"


# --- 9. Ce que la banniere dit au client, joue dans un vrai moteur JS --------

PAGES = [("chanson", "chansons"), ("video", "clips"), ("dialogue", "dialogues")]


def _format_fr():
    """Les formateurs francais, charges depuis leur source, une seule fois.

    On ne recopie pas ici la virgule decimale ni la date a la francaise : un test
    qui porte sa propre copie de la regle ne teste plus que lui-meme.
    """
    global _FORMAT_FR
    if _FORMAT_FR is None:
        import importlib.util

        from conftest import RACINE
        chemin = RACINE / "sandbox-manager" / "format_fr.py"
        spec = importlib.util.spec_from_file_location("format_fr_du_test", chemin)
        _FORMAT_FR = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_FORMAT_FR)
    return _FORMAT_FR


_FORMAT_FR = None


def _budget_texte_js(nom_module: str) -> str:
    """Sort `budgetTexte` de la page, telle qu'elle part dans le navigateur."""
    from conftest import RACINE
    source = (RACINE / "sandbox-manager" / (nom_module + ".py")).read_text(encoding="utf-8")
    debut = source.index("function budgetTexte(b){")
    profondeur = 0
    for fin in range(source.index("{", debut), len(source)):
        if source[fin] == "{":
            profondeur += 1
        elif source[fin] == "}":
            profondeur -= 1
            if profondeur == 0:
                return source[debut:fin + 1]
    raise AssertionError("budgetTexte n'est pas refermee dans " + nom_module)


def _rendu(tmp_path, nom_module, etat):
    """Execute la fonction dans node et rend la phrase vue par le client.

    Un test de texte dirait seulement que les deux branches sont ECRITES ; on
    veut savoir laquelle SORT, et qu'aucune des deux ne casse la page -- une
    faute de JS ici efface la banniere entiere, sans un mot dans les journaux
    du serveur.
    """
    # Les formateurs francais arrivent dans la page par `avec_formateurs` : la
    # MEME source ici, sinon `fr` n'existe pas et node s'arrete sur
    # << fr is not defined >> -- ce qui est exactement ce que verrait le client
    # si un rendu oubliait l'appel (la garde `verifier-francais.py` le surveille).
    programme = (_format_fr().JS_FORMATEURS
                 + _budget_texte_js(nom_module)
                 + "\nconsole.log(budgetTexte(" + json.dumps(etat) + "));\n")
    fichier = tmp_path / ("banniere_" + nom_module + ".js")
    fichier.write_text(programme, encoding="utf-8")
    # encoding= explicite : node ecrit de l'UTF-8, et sur cette machine Python
    # decoderait en cp1252. Sans cette ligne, << releve >> devient << relevÃ© >>
    # et le test cherche un mot qui n'existe nulle part -- mesure le 20/09/2026.
    fait = subprocess.run(["node", str(fichier)], capture_output=True,
                          text=True, encoding="utf-8")
    assert fait.returncode == 0, fait.stderr
    return fait.stdout


@pytest.mark.parametrize("nom_module,champ", PAGES)
def test_la_banniere_dit_selon_modal_quand_le_chiffre_vient_de_modal(
        budget, monkeypatch, tmp_path, nom_module, champ):
    """<< Estimation locale, pas une facture >> etait vrai jusqu'au 20/09/2026.

    Le compteur porte maintenant le releve de Modal quand il l'a. Laisser la
    vieille phrase sous un chiffre qui EST la facture, c'est dire au client
    quelque chose de faux sur le seul nombre qui l'engage.
    """
    budget.poser(nom_module if nom_module != "video" else "video",
                 secondes=4996.2, usd=1.3878, appels=29)
    _faux_depenses(monkeypatch, {"calcul": 3.79706491})
    budget.amorcer()
    etat = budget.vue(nom_module)
    etat[champ] = 2
    texte = _rendu(tmp_path, nom_module, etat)
    assert "selon Modal" in texte
    assert "relevé chez Modal" in texte
    assert "1,39" in texte, "l'estimation locale doit rester lisible a cote"
    assert "3,80" in texte
    assert "pas une facture" not in texte


@pytest.mark.parametrize("nom_module,champ", PAGES)
def test_la_banniere_avoue_sous_compter_quand_modal_se_tait(
        budget, monkeypatch, tmp_path, nom_module, champ):
    """Hors ligne, le client doit savoir que le nombre est un PLANCHER.

    C'est la moitie qui protege : un chiffre trop petit presente sans reserve
    laisserait croire qu'il reste du credit la ou il n'y en a plus.
    """
    budget.poser(nom_module if nom_module != "video" else "video",
                 secondes=4996.2, usd=1.3878, appels=29)
    _faux_depenses(monkeypatch, {}, disponible=False)
    budget.amorcer()
    etat = budget.vue(nom_module)
    etat[champ] = 2
    texte = _rendu(tmp_path, nom_module, etat)
    assert "selon le Studio" in texte
    assert "sous-compte" in texte
    assert "relevé chez Modal" not in texte


# --- 10. La page d'essai : elle depense, elle doit le dire -------------------

def test_la_page_d_essai_montre_le_budget_et_dit_d_ou_il_vient(budget, monkeypatch, tmp_path):
    """Trouve le 20/09/2026 en validant les trois autres pages dans un navigateur.

    Le code envoye depuis /essai part sur Modal avec usage=<<autonome>> : il
    depense, et sur la part reservee, celle que personne d'autre ne peut
    entamer. La page n'affichait aucun montant. Les trois pages creatives en
    montrent un depuis le 19/09.
    """
    budget.poser("autonome", secondes=4996.2, usd=1.3878, appels=29)
    _faux_depenses(monkeypatch, {"calcul": 3.79706491})
    budget.amorcer()
    texte = _rendu(tmp_path, "app", budget.lire())
    assert "selon Modal" in texte
    assert "releve chez Modal" in texte
    assert "3,80" in texte and "1,39" in texte
    assert "part du Sandbox" in texte
    assert (_format_fr().en_dollars(budget.RESERVE_AUTONOME_USD) + " que les pages") in texte, (
        "la part reservee doit etre nommee, en dollars")


def test_la_page_d_essai_previent_quand_modal_se_tait(budget, monkeypatch, tmp_path):
    """Hors ligne, le montant affiche est un PLANCHER, et la page le dit."""
    budget.poser("autonome", secondes=4996.2, usd=1.3878, appels=29)
    _faux_depenses(monkeypatch, {}, disponible=False)
    budget.amorcer()
    texte = _rendu(tmp_path, "app", budget.lire())
    assert "selon le Studio" in texte
    assert "sous-compte" in texte
    assert "releve chez Modal" not in texte


def test_la_page_d_essai_sert_bien_ce_budget(sandbox):
    """La fonction ne sert a rien si la page ne l'appelle pas, ni si la boite
    ou elle ecrit n'existe pas. Les deux ont deja manque ailleurs.
    """
    from conftest import RACINE
    source = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    debut = source.index("ESSAI_HTML")
    fin = source.index("@app.get(\"/essai\"")
    page = source[debut:fin]
    assert 'id="budget"' in page, "la boite ou ecrire le montant a disparu"
    assert 'fetch("/budget/modal"' in page, "la page ne demande plus le compteur"
    assert "budgetTexte(d)" in page, "le montant n'est plus mis dans la page"


# --- 11. Les prix : ceux de Modal, et la bonne des deux grilles ---------------
#
# Le defaut du 20/09/2026. Notre estimation disait 1,39 $ la ou Modal facturait
# 3,80 $, et l'explication ecrite dans le module accusait les QUANTITES : trop
# peu de coeurs, memoire mal comptee. Les deux etaient fausses. La cause est que
# Modal publie deux grilles de prix -- la normale et celle des bacs a sable --
# et que le Studio, qui ne lance que des bacs a sable, comptait avec la normale.
# Le processeur et la memoire y valent exactement trois fois plus.
#
# Personne ne l'avait vu parce que personne n'avait jamais lance
# `modal billing rates`. Ces trois tests-la sont la pour que la prochaine
# difference de grille se voie sans facture.

TARIFS_HORAIRES_RELEVES = {
    # Releves le 20/09/2026 par `modal billing rates --json`, tels quels.
    "cpu_hour_cost": 0.04730,
    "cpu_hour_cost_sandbox": 0.141900,
    "mem_gib_hour_cost": 0.00800,
    "mem_gib_hour_cost_sandbox": 0.024000,
    "gpu_hour_cost_t4": 0.59,
    "gpu_hour_cost_l4": 0.80,
    "gpu_hour_cost_a10g": 1.10,
    "gpu_hour_cost_l40s": 1.95,
    "gpu_hour_cost_a100_40gb": 2.10,
    "gpu_hour_cost_a100_80gb": 2.50,
    "gpu_hour_cost_rtx6000": 3.03,
    "gpu_hour_cost_h100": 3.95,
    "gpu_hour_cost_h200": 4.54,
    "gpu_hour_cost_b200": 6.25,
    "gpu_hour_cost_b300": 7.10,
}

CARTES = {
    "T4": "gpu_hour_cost_t4", "L4": "gpu_hour_cost_l4",
    "A10": "gpu_hour_cost_a10g", "A10G": "gpu_hour_cost_a10g",
    "L40S": "gpu_hour_cost_l40s", "A100": "gpu_hour_cost_a100_40gb",
    "A100-80GB": "gpu_hour_cost_a100_80gb", "RTX6000": "gpu_hour_cost_rtx6000",
    "H100": "gpu_hour_cost_h100", "H200": "gpu_hour_cost_h200",
    "B200": "gpu_hour_cost_b200", "B300": "gpu_hour_cost_b300",
}


def test_le_processeur_et_la_memoire_sont_au_tarif_du_bac_a_sable(budget):
    """LE defaut du 20/09/2026, en un test.

    Le Studio ne cree que des bacs a sable (`modal.Sandbox.create`). Modal
    facture leur processeur et leur memoire trois fois le tarif d'un conteneur
    ordinaire. Compter avec la grille normale, c'est sous-compter de deux tiers
    sur 48 % de la facture -- la part memoire + processeur mesuree en
    septembre 2026.
    """
    attendu_cpu = TARIFS_HORAIRES_RELEVES["cpu_hour_cost_sandbox"] / 3600
    attendu_mem = TARIFS_HORAIRES_RELEVES["mem_gib_hour_cost_sandbox"] / 3600
    assert budget.PRIX_CPU_USD_S == pytest.approx(attendu_cpu, rel=0.01)
    assert budget.PRIX_MEMOIRE_USD_S == pytest.approx(attendu_mem, rel=0.01)
    # Et surtout : PAS la grille normale, celle qui etait utilisee avant.
    assert budget.PRIX_CPU_USD_S > TARIFS_HORAIRES_RELEVES["cpu_hour_cost"] / 3600 * 2
    assert budget.PRIX_MEMOIRE_USD_S > TARIFS_HORAIRES_RELEVES["mem_gib_hour_cost"] / 3600 * 2


def test_aucune_carte_publiee_par_modal_ne_manque_a_la_table(budget):
    """Une carte absente est comptee au prix de la plus chere CONNUE.

    Cette garde ne protege que si la table suit le catalogue : le 20/09/2026 il
    manquait RTX6000, H200, B200 et B300, et une B300 etait donc estimee au
    tarif H100 -- 0,001097 au lieu de 0,001972, 44 % de moins. Le refus serait
    arrive bien trop tard.
    """
    for carte, cle in CARTES.items():
        assert carte in budget.PRIX_GPU_USD_S, carte
        assert budget.PRIX_GPU_USD_S[carte] == pytest.approx(
            TARIFS_HORAIRES_RELEVES[cle] / 3600, rel=0.01), carte


def test_l_estimation_corrigee_retombe_sur_la_facture_du_20_09(budget):
    """La preuve chiffree, sur la seule journee ou ce compteur couvrait tout.

    Modal a facture 0,157 9 $ le 20/09/2026, decompose par sa propre CLI :
    0,087 6 $ de carte L4, 0,042 3 $ de memoire, 0,028 0 $ de processeur. En
    divisant par les tarifs de Modal, cela fait 394 s de L4, 16,1 Gio de
    memoire -- exactement `VIDEO_MEMORY_MB` -- et 1,8 coeur.

    Avec les prix corriges, les memes 394 s et le coeur que l'on RESERVE,
    l'estimation vaut 0,145 $. Avant, 0,110 $. Le reste (les coeurs reellement
    utilises au-dela du coeur reserve) ne se sait pas avant de lancer, et c'est
    ecrit tel quel dans le module.
    """
    secondes, memoire_mb = 394, 16384
    estime = budget.prix_seconde("L4", memoire_mb) * secondes
    assert 0.14 < estime < 0.15, estime
    facture = 0.1579
    assert estime / facture > 0.90, "l'estimation retombe a moins de 90 % de la facture"
    assert estime <= facture, "une estimation au-dessus de la facture refuserait trop tot"


# --- 12. Les 8 % qualifient la METHODE, jamais le total affiche --------------
#
# Defaut trouve le 20/09/2026 en relisant les quatre bannieres validees la
# veille. La phrase disait : le total est de 3,80 $, et << elle sous-compte
# d'environ 8 % >>. Le lecteur comprend << le vrai chiffre est 3,80 x 1,08 >>.
# C'est faux. Les 8 % mesurent l'ecart entre le coeur RESERVE et le processeur
# reellement utilise, sur un travail donne. Le total, lui, court sur tout le
# mois et contient des travaux comptes AVANT la correction des tarifs du
# 20/09/2026. Mesure du jour meme, sur ce meme compteur : 1,39 $ estime contre
# 3,80 $ factures, soit 37 % d'ecart -- annoncer 8 % sur CE nombre-la est faux
# de loin, et faux dans le sens qui rassure.


def _texte_nu(texte: str) -> str:
    """Le mot tel qu'on le compare : sans balises, sans accents, sans typographie.

    Les trois pages creatives ecrivent en francais accentue et coupent parfois
    le mot par un <b> ; app.py ecrit en ASCII. Une regle ecrite quatre fois
    n'est gardee qu'une fois sur quatre le jour ou quelqu'un en oublie une.
    """
    sans_balises = re.sub(r"</?[a-zA-Z][^>]*>", "", texte)
    decompose = unicodedata.normalize("NFKD", sans_balises)
    return "".join(c for c in decompose if not unicodedata.combining(c))


TOUTES_LES_BANNIERES = PAGES + [("app", None)]


def _etat_de_banniere(budget, monkeypatch, nom_module, champ, modal_repond):
    """L'etat que le serveur enverrait a CETTE page, Modal repondant ou non."""
    budget.poser("autonome" if nom_module == "app" else nom_module,
                 secondes=4996.2, usd=1.3878, appels=29)
    if modal_repond:
        _faux_depenses(monkeypatch, {"calcul": 3.79706491})
    else:
        _faux_depenses(monkeypatch, {}, disponible=False)
    budget.amorcer()
    if nom_module == "app":
        return budget.lire()
    etat = budget.vue(nom_module)
    etat[champ] = 2
    return etat


@pytest.mark.parametrize("modal_repond", [True, False], ids=["modal_repond", "modal_muet"])
@pytest.mark.parametrize("nom_module,champ", TOUTES_LES_BANNIERES)
def test_les_8_pourcent_ne_qualifient_jamais_le_total_affiche(
        budget, monkeypatch, tmp_path, nom_module, champ, modal_repond):
    """CHAQUE mention de << sous-compte >> est precedee de << la methode >>.

    La regle porte sur les occurrences et non sur une phrase entiere : c'est la
    seule forme qui tombe encore si quelqu'un ajoute demain une cinquieme
    banniere, ou une seconde mention dans une banniere existante.
    """
    etat = _etat_de_banniere(budget, monkeypatch, nom_module, champ, modal_repond)
    texte = _texte_nu(_rendu(tmp_path, nom_module, etat))
    mentions = [trouve.start() for trouve in re.finditer("sous-compte", texte)]
    assert mentions, "la banniere n'avoue plus sous-compter"
    for debut in mentions:
        avant = texte[max(0, debut - 12):debut]
        assert avant.endswith("methode "), (
            "les 8 % sont accroches a << " + avant.strip() + " >> et non a la methode")


@pytest.mark.parametrize("modal_repond", [True, False], ids=["modal_repond", "modal_muet"])
@pytest.mark.parametrize("nom_module,champ", TOUTES_LES_BANNIERES)
def test_le_total_affiche_dit_qu_il_contient_des_travaux_aux_anciens_tarifs(
        budget, monkeypatch, tmp_path, nom_module, champ, modal_repond):
    """Sans cette reserve, le total passe pour homogene alors qu'il ne l'est pas.

    La date n'est pas ecrite en dur ici : elle vient de PRIX_RELEVE_LE, de sorte
    qu'un releve de prix refait demain deplace la phrase et le test ensemble.
    """
    etat = _etat_de_banniere(budget, monkeypatch, nom_module, champ, modal_repond)
    texte = _texte_nu(_rendu(tmp_path, nom_module, etat))
    # La date est RANGEE en clair (`2026-09-20`) et AFFICHEE a la francaise. Le
    # test attend la forme affichee, obtenue par le meme formateur que la page.
    date = _format_fr().en_date(budget.PRIX_RELEVE_LE)
    assert "tarifs plus bas" in texte, "le total passe pour homogene"
    assert ("avant le " + date) in texte or ("avant cette date" in texte and date in texte), (
        "la reserve ne nomme pas la date du releve de prix")
