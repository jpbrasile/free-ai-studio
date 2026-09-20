"""La fonction de vidage : ce que le Studio occupe, et ce qu'on peut rendre.

Trois choses se gardent ici, dans cet ordre de degat.

1. **Le travail du client n'est jamais propose a la suppression.** Ses fichiers
   et ses conversations sont dans des volumes voisins de ceux qu'on vide ; un
   `docker volume rm` de trop et six mois de travail partent sans confirmation
   possible. Les deux scripts les AFFICHENT et refusent de les toucher.
2. **Une seule route efface les 34 Go** : `supprimer-modele-video`, qui porte
   ses propres gardes. Sans cette regle, le jour ou l'une des deux routes
   apprend quelque chose, l'autre l'ignore.
3. **Les deux jumeaux proposent les memes lignes.** Un client sous Linux et un
   client sous Windows doivent pouvoir rendre la meme place.

Ces tests lisent les fichiers ; ils ne lancent pas docker. Ce que lire ne peut
pas dire a ete joue en vrai le 20/09 (les six chemins, et la mesure sur cette
machine : 49,70 Go telecharges contre 1,81 Go de travail).

UNE EXCEPTION, ajoutee le 20/09/2026 : la ligne du budget Modal choisit entre
deux nombres, et lire le texte du script ne prouve pas qu'elle choisit bien. Ce
test-la LANCE le script, sur une copie et avec un compteur fabrique, pour ne
jamais toucher le vrai. Il a besoin de docker (le script s'arrete sans lui) et
se saute proprement quand il n'y en a pas.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

SH = (RACINE / "scripts" / "ressources.sh").read_text(encoding="utf-8")
PS1 = (RACINE / "scripts" / "ressources.ps1").read_text(encoding="utf-8")

# Les cles que le client tape. Elles sont affichees entre crochets dans le
# tableau : si l'une disparait d'un cote, le tableau ment de ce cote-la.
CLES = ("video-poids", "video-image", "chat", "whisper", "studio", "tout")

# Les deux volumes qui contiennent le travail de la personne, et rien d'autre.
TRAVAIL = ("sandbox-data", "open-webui-data")


def lignes_de_code(source: str, commentaire: str) -> list[str]:
    return [l.strip() for l in source.splitlines()
            if l.strip() and not l.strip().startswith(commentaire)]


def test_les_deux_jumeaux_proposent_les_memes_lignes():
    for cle in CLES:
        assert cle in SH, cle
        assert cle in PS1, cle


def test_le_travail_du_client_est_montre_mais_jamais_supprime():
    """LE test qui compte : un `docker volume rm` de trop, et six mois partent.

    Les deux volumes du travail sont voisins de ceux qu'on vide. Ils doivent
    apparaitre dans le tableau -- le client a le droit de savoir ce qu'ils
    pesent -- et n'apparaitre dans AUCUNE ligne qui efface."""
    # Les appels passent par des fonctions -- `vider_volume`, `ViderImage` --,
    # pas par `docker volume rm` en direct. Une garde qui ne regarde que les
    # commandes brutes laisse passer la faute : verifie par mutation le 20/09,
    # elle passait. Ce sont donc les DEUX qu'on regarde.
    for source, commentaire, efface in (
            (SH, "#", ("rm -rf", "docker volume rm", "docker image rm",
                       "vider_volume", "vider_image", "vider_poids")),
            (PS1, "#", ("Remove-Item", "docker volume rm", "docker image rm",
                        "ViderVolume", "ViderImage", "ViderPoids"))):
        code = lignes_de_code(source, commentaire)
        # Ils sont mesures : le client voit ce qu'ils pesent.
        assert any("sandbox-data" in l for l in code)
        assert any("open-webui-data" in l for l in code)
        # Mais jamais dans une ligne qui efface pour de bon. La seule mention
        # autorisee a cote d'un `rm` est celle qu'on ECRIT a l'ecran, pour que
        # la personne puisse le faire elle-meme en connaissance de cause.
        for l in code:
            if not any(e in l for e in efface):
                continue
            if l.startswith("echo") or l.startswith("Write-Host") or '"    docker volume rm' in l:
                continue
            if l.startswith("vider_") or l.startswith("function Vider"):
                continue          # la definition de la fonction, pas un appel
            for v in TRAVAIL:
                assert v not in l, l


def test_une_seule_route_efface_les_34_go():
    """Le vidage appelle le script dedie : ses gardes valent pour les deux."""
    assert "./scripts/supprimer-modele-video.sh --oui" in SH
    assert "supprimer-modele-video.ps1" in PS1
    # Et surtout : pas de suppression du modele en direct, qui contournerait
    # les gardes du script dedie (dossier du modele seulement, jamais la racine
    # du cache Hugging Face, qui contient les modeles des autres outils).
    for source, commentaire, efface in ((SH, "#", "rm -rf"), (PS1, "#", "Remove-Item")):
        for l in lignes_de_code(source, commentaire):
            if efface in l:
                assert "models--Wan-AI" not in l, l


def test_rien_ne_s_efface_sans_que_la_question_soit_posee():
    assert "read -r reponse" in SH
    assert "Read-Host" in PS1
    # Sans terminal, le .sh refuse au lieu de supposer.
    assert "[ ! -t 0 ]" in SH
    # Et sans argument, les deux se contentent de mesurer.
    assert 'if [ -z "$cle" ]' in SH
    assert "if (-not $Vider)" in PS1


def test_le_prix_du_retour_est_dit_avant_la_question():
    """Un vidage qui ne dit pas son prix n'est pas un choix."""
    for source in (SH, PS1):
        assert "Pour revenir" in source or "retour" in source
    # Et pour les 34 Go, le prix du retour est devenu << rien a faire >> :
    # c'est la regle du proprietaire du 20/09, et elle doit etre ECRITE la ou
    # le client decide, pas seulement tenue par le service.
    assert "le Studio les retélécharge" in SH
    assert "le Studio les retelecharge" in PS1


def test_le_total_ne_se_fait_pas_passer_pour_exact():
    """Les images Docker partagent des couches : additionner majore."""
    assert "borne haute" in SH
    assert "borne haute" in PS1


# --- Les dates : celle du depot, et celle du credit ---------------------------

def test_chaque_ligne_dit_depuis_quand_elle_dort_la():
    """Demande du proprietaire, 20/09/2026 : noter la date de renouvellement.

    Une taille seule ne dit pas s'il faut s'en occuper. 34 Go arrives hier et
    34 Go qui dorment depuis six mois, ce n'est pas la meme decision."""
    assert "RENOUVELÉ LE" in SH
    assert "RENOUVELE LE" in PS1
    # La date d'une IMAGE est celle ou elle a atterri ici (`LastTagTime`), pas
    # celle ou son auteur l'a publiee (`.Created`, qui n'est que le repli).
    for source in (SH, PS1):
        assert "LastTagTime" in source
        assert ".Created" in source
    # Celle des POIDS est le fichier le plus recemment ecrit : un
    # telechargement repris ajoute des fichiers sans toucher au dossier.
    assert "LastWriteTime" in PS1
    assert "-printf '%T@" in SH


def test_le_credit_modal_est_dit_avec_sa_date_de_remise_a_zero():
    """Un credit mensuel sans sa date fait attendre pour rien, ou lancer un
    calcul qui sera refuse. Modal en particulier : c'est le seul qui coute."""
    for source in (SH, PS1):
        assert "Modal" in source
        assert "modal-budget.json" in source
        # La cadence des routes gratuites est le jour, pas le mois : les
        # confondre, c'est promettre un quota qui ne reviendra pas ce soir.
        assert "JOUR" in source


def test_le_premier_du_mois_est_le_notre_et_jamais_celui_de_modal():
    """LA correction du 20/09/2026, demandee par le proprietaire : << web search
    pour retrouver les jours exacts >>.

    Le bloc annoncait << remis a zero le 01/10/2026, et tous les 1ers du mois >>
    a cote du nom de Modal. Verification faite sur leurs pages : ils publient
    << $30 / month free compute >> et << All Workspaces are billed monthly >>,
    et le JOUR n'est ecrit NULLE PART -- ni tarifs, ni facturation, ni budgets.
    Le << 1er >> venait d'un resume de moteur de recherche. Il est vrai de
    NOTRE compteur, dont la cle est `%Y-%m` ; il ne l'est pas du credit du
    client. Un client qui compte sur une date inventee lance un calcul qui sera
    refuse.

    SUITE DU MEME JOUR, sur << mesure Modal pour moi >> : la source manquante
    n'etait pas absente, elle etait AILLEURS. Le tableau de bord de l'espace de
    travail ecrit << Billing Cycle: Sep 1 - Oct 1, 2026 >>. Le cycle est donc
    le mois civil ici -- et le bloc doit maintenant citer cette source au lieu
    de s'arreter a << ils ne le disent pas >>, tout en gardant que la page
    publique, elle, ne le dit toujours pas, et que le cycle qui fait foi est
    celui de VOTRE tableau de bord.
    """
    for source in (SH, PS1):
        # Toute ligne qui parle du 1er doit dire de QUI il est.
        for ligne in source.splitlines():
            if "1ers" in ligne and not ligne.strip().startswith("#"):
                assert "NOTRE" in ligne, ligne
        # Ce que la page publique ne donne pas...
        assert "ne publie PAS le jour" in source
        # ...et ce que le tableau de bord donne, cite mot pour mot.
        assert "Billing Cycle: Sep 1 - Oct 1" in source
        assert "tableau de bord" in source
        # Et la date qui fait foi est nommee : celle du client, chez eux.
        assert "VOTRE cycle" in source
        assert "modal.com" in source


def test_la_ligne_modal_avoue_qu_elle_compte_moins_que_la_facture():
    """Le defaut trouve en mesurant, le 20/09/2026 -- et le pire des deux.

    Le proprietaire a remarque que les 30 $ etaient intacts juste avant le
    premier usage de Modal par le Studio. C'est ce qui rend la comparaison
    exacte : meme fenetre (a partir du 09/09/2026 11 h), meme travail, les six
    jours factures du mois portant tous le nom `free-ai-studio-sandbox`. Notre
    compteur disait 1,39 $, Modal facturait 3,80 $, et le credit restant reel
    etait 26,20 $ et non 28,61 $.

    Une ligne qui affiche un budget SANS dire qu'elle sous-compte est pire
    qu'une ligne absente : elle donne une confiance que le chiffre ne merite
    pas. Ce test garde l'aveu, ses deux nombres et l'adresse du vrai chiffre.
    """
    for source in (SH, PS1):
        assert "MOINS que la vraie" in source
        assert "1,39" in source and "3,80" in source
        assert "Usage & billing" in source


def test_chaque_fournisseur_dit_ce_qui_est_publie_et_ce_qui_ne_l_est_pas():
    """Trois fournisseurs, trois reponses differentes -- et aucune inventee.

    Google ECRIT sa date (<< RPD quotas reset at midnight Pacific time >>).
    OpenRouter donne les comptes par jour mais pas l'heure. Groq ne publie
    aucune heure fixe : son API rend un compte a rebours. Ecrire << remis a
    zero chaque jour >> pour les trois, comme on le faisait, donnait le meme
    niveau de certitude a une mesure et a deux suppositions.
    """
    for source in (SH, PS1):
        assert "Pacifique" in source
        assert "Google" in source
        assert "OpenRouter" in source and "Groq" in source
        assert "n'est pas publi" in source          # publiee / publiée
        assert "compte a rebours" in source or "compte à rebours" in source
        # La date du releve : une limite vieille d'un an se relit autrement.
        assert "20/09/2026" in source


def test_la_date_de_remise_a_zero_est_calculee_et_jamais_ecrite_en_dur():
    """Une date ecrite en clair est juste une fois, puis fausse pour toujours."""
    for source, calcul in ((SH, "premier_du_mois_suivant"), (PS1, "PremierDuMoisSuivant")):
        assert calcul in source
        for ligne in source.splitlines():
            # Les deux langages commentent avec `#`. On coupe a la premiere :
            # cela laisse passer un `#` dans une chaine, il n'y en a pas ici,
            # et le jour ou il y en aura ce test le dira.
            code = ligne.split("#")[0]
            if not any(m in code for m in ("repart", "remis a zero", "remis à zéro")):
                # Une date de RELEVE s'ecrit en dur, et doit l'etre : elle dit
                # quand les pages des fournisseurs ont ete lues. Seule une date
                # de REMISE A ZERO ne doit jamais etre figee.
                continue
            assert "/2026" not in code, ligne
            assert "/2027" not in code, ligne


def test_le_compteur_d_un_mois_clos_n_est_jamais_affiche_comme_a_jour():
    """Le fichier garde le mois qu'il compte. Un mois plus ancien est deja
    reparti de zero cote service : afficher son total serait un chiffre faux
    presente comme courant."""
    assert '"$(json_texte "$BUDGET_MODAL" mois)" = "$MOIS"' in SH
    assert '$b.mois -eq $moisCourant' in PS1


def test_l_estimation_ne_se_fait_jamais_passer_pour_une_facture():
    """Le chiffre affiche dit toujours D'OU il vient.

    Depuis le 20/09/2026 il y a deux provenances possibles : le releve pris
    chez Modal, ou notre estimation locale quand Modal n'a pas repondu. Les
    deux s'affichent avec leur nom ; ce qui reste interdit, c'est de montrer la
    seconde en laissant croire que c'est la premiere.
    """
    for source in (SH, PS1):
        assert "facture" in source
        assert "fait foi" in source


def test_la_ligne_modal_montre_le_releve_de_modal_quand_il_existe():
    """Le defaut trouve le 20/09/2026 en lancant le script, le jour meme ou le
    compteur avait appris a relever le vrai chiffre.

    Les pages du Studio disaient 3,80 $ et 26,20 $ de reste ; ce script, lui,
    disait encore 1,39 $ et 28,61 $, parce qu'il ne lisait que `usd`. Deux
    tableaux de bord de la meme maison qui donnent deux budgets differents, et
    celui qu'on lit dans un terminal est le plus rassurant des deux : c'est
    exactement l'ordre dans lequel il ne faut pas se tromper.

    Il lit donc `usd_reel`, et quand ce chiffre existe il le montre AVEC son
    jour de releve -- une valeur sans sa date ne se compare a rien.
    """
    assert "usd_reel" in SH and "usd_reel_le" in SH
    assert "usd_reel" in PS1 and "usd_reel_le" in PS1
    for source in (SH, PS1):
        haut = source.upper()
        assert "RELEV" in haut and "CHEZ MODAL" in haut
    # Et le jour vient de la variable, jamais d'une date ecrite en clair.
    assert "$reel_le" in SH
    assert "$releveLe" in PS1


def test_des_deux_minorants_c_est_le_plus_grand_qui_s_affiche():
    """Les deux nombres comptent MOINS que la verite, chacun a sa facon.

    Le notre ignore la memoire et le processeur. Celui de Modal ignore le
    calcul qui vient de finir -- leur page previent que le total arrive
    << within minutes >>. Prendre le plus grand des deux est la seule regle qui
    ne fasse jamais afficher un budget plus confortable que la realite ; le
    garde `budget_modal.lire()` applique deja la meme, et ce script doit dire
    la meme chose que lui.

    Et l'autre nombre ne disparait pas : le releve s'affiche avec l'estimation
    a cote, sinon on ne verrait plus de combien elle sous-compte.
    """
    # SH : la comparaison passe par awk, faute de flottants en shell.
    assert "r >= e" in SH
    assert "$estime" in SH
    # PS1 : comparaison native, meme sens.
    assert "-ge $estime" in PS1
    for source in (SH, PS1):
        assert "sous-compte" in source


def _ligne_modal(tmp_path: Path, budget: dict) -> str:
    """Lance le script sur une COPIE, avec le compteur qu'on lui donne.

    Le script fait `cd "$(dirname "$0")/.."` : depose dans `<tmp>/scripts/`, il
    lit donc `<tmp>/config/modal-budget.json` et jamais celui du depot, qui est
    le vrai compteur et qu'un conteneur en marche reecrit a chaque depense.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    shutil.copy2(RACINE / "scripts" / "ressources.sh", tmp_path / "scripts")
    (tmp_path / "config" / "modal-budget.json").write_text(
        json.dumps(budget), encoding="utf-8")
    fait = subprocess.run(["bash", "scripts/ressources.sh"], cwd=tmp_path,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    if fait.returncode == 2 and "Docker" in (fait.stdout or ""):
        pytest.skip("pas de docker sur cette machine")
    debut = fait.stdout.index("Modal (machines")
    return fait.stdout[debut:fait.stdout.index("Gemini", debut)]


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker absent")
def test_en_vrai_le_releve_de_modal_l_emporte_sur_notre_estimation(tmp_path):
    """Le seul test qui aurait attrape le defaut du 20/09/2026.

    Ce jour-la le script affichait 1,39 $ quand Modal facturait 3,80 $. Lire le
    fichier ne le dit pas : il faut deux nombres differents dans le compteur et
    regarder lequel sort. Ici le releve est le plus grand, c'est donc lui qui
    doit s'afficher, avec son jour.
    """
    mois = time.strftime("%Y-%m")
    texte = _ligne_modal(tmp_path, {"mois": mois, "usd": 1.3878, "usd_reel": 3.797,
                                    "usd_reel_le": "2026-09-20 10:03:08"})
    assert "3.80 $ dépensés" in texte
    assert "reste 26.20 $" in texte
    assert "RELEVÉ CHEZ MODAL (le 2026-09-20 10:03:08)" in texte
    # L'estimation reste visible a cote : c'est elle qui dit de combien on
    # sous-compte quand Modal ne repond pas.
    assert "1.39 $" in texte


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker absent")
def test_en_vrai_un_releve_en_retard_ne_fait_pas_baisser_le_budget(tmp_path):
    """L'autre sens, celui qu'on oublie : le releve de Modal est en retard.

    Leur total arrive << within minutes >> ; entre-temps notre estimation est
    le plus grand des deux, et c'est elle qui protege. Un script qui ferait
    confiance au releve en toutes circonstances afficherait ici 3,00 $ au lieu
    de 7,00 $ -- un budget plus confortable que la realite, exactement ce que
    la regle du plus grand interdit.
    """
    mois = time.strftime("%Y-%m")
    texte = _ligne_modal(tmp_path, {"mois": mois, "usd": 7.0, "usd_reel": 3.0,
                                    "usd_reel_le": "2026-09-20 10:03:08"})
    assert "7.00 $ dépensés" in texte
    assert "reste 23.00 $" in texte
    assert "Modal n'a pas répondu" in texte
