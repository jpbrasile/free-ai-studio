"""Composer deux briques : ce que le registre ne permet pas encore.

Un *composite* est une chaine de briques designees par leur FONCTION et non par
un nom de modele -- << la voix >>, pas << Piper 1.8.0 >>. C'est le cap que le
depot s'est donne (docs/PLAN-PLATEFORME.md:43-45), et la case est restee vide :
le mot << composite >> apparait deux fois dans les deux fichiers de plan reunis,
les deux dans ce seul paragraphe.

Ce que ces tests gardent :

1. les briques declarent ce qu'elles consomment et ce qu'elles rendent, sinon
   IL N'Y A PAS DE GRAPHE A TRAVERSER et le controle deterministe n'a rien a
   comparer ;
2. la chaine temoin -- dictee -> resume -> lecture a voix haute -- s'enchaine
   vraiment, brique par brique, au lieu de s'enchainer dans une phrase de plan.

Le meme champ manque dans le depot voisin (plasma) : sur 96 composites, 2
declarent leurs entrees et 2 leurs sorties. C'est le meilleur argument pour le
poser avant d'aller chercher des briques ailleurs.

Aucun appel reseau.
"""
from __future__ import annotations

import json

import pytest

from conftest import RACINE

REGISTRE = RACINE / "registry" / "apps.json"

# Les types qui traversent une frontiere entre deux briques. Des VALEURS NUES,
# jamais un objet de service : la regle vient du depot voisin, ou 5 828
# declarations de type tiennent sur 15 types de base et zero objet solveur. Un
# type que rien ne peut contredire est un controle qui ne peut pas sonner.
TYPES_CONNUS = {"texte", "audio", "image", "video", "fichier"}

# La chaine temoin du lot 1. Trois briques qui existent deja, trois types
# differents traverses, et elle finit sur un fichier : << resume-moi cet
# enregistrement et lis-le-moi >>.
TEMOIN = ("dictee_locale", "chat_auto", "voix_fr")


@pytest.fixture
def registre():
    return json.loads(REGISTRE.read_text(encoding="utf-8"))


@pytest.fixture
def par_id(registre):
    return {a["id"]: a for a in registre["applications"]}


# --- SP-BRIQUES-SANS-TYPES : la preuve de cloture ---------------------------

def test_chaque_brique_declare_ce_qu_elle_prend_et_ce_qu_elle_rend(registre):
    """Sans ces deux champs, le controle deterministe n'a rien a comparer.

    Il rougit aujourd'hui sur les seize : c'est le defaut, pas une regression.
    """
    muettes = [a["id"] for a in registre["applications"]
               if "entrees" not in a or "sorties" not in a]
    assert not muettes, (
        "SP-BRIQUES-SANS-TYPES -- %d brique(s) sur %d ne declarent ni ce "
        "qu'elles consomment ni ce qu'elles rendent, donc il n'y a pas de "
        "graphe a traverser : %s"
        % (len(muettes), len(registre["applications"]), muettes))


def test_les_types_declares_sont_des_types_connus(registre):
    """Un type invente par une entree est un controle qui ne sonnera jamais."""
    for app in registre["applications"]:
        for champ in ("entrees", "sorties"):
            valeurs = app.get(champ)
            assert isinstance(valeurs, list) and valeurs, \
                "%s : %s doit etre une liste non vide" % (app["id"], champ)
            inconnus = set(valeurs) - TYPES_CONNUS
            assert not inconnus, \
                "%s : %s inconnu(s) %s" % (app["id"], champ, sorted(inconnus))


def test_la_chaine_temoin_s_enchaine_vraiment(par_id):
    """La sortie du noeud n doit couvrir l'entree du noeud n+1.

    C'est l'affirmation la plus risquee du lot 1 : les trois routes existent et
    leurs types s'enchainent dans le code (transcriptions rend {"text": ...},
    le chat prend du texte, speech prend {"input": texte} et rend du WAV), mais
    le REGISTRE ne le dit nulle part. Tant qu'il ne le dit pas, la chaine tient
    dans une phrase de plan et non dans une donnee verifiable.
    """
    for brique in TEMOIN:
        assert brique in par_id, "la chaine temoin nomme une brique absente : %s" % brique

    for amont, aval in zip(TEMOIN, TEMOIN[1:]):
        sorties = set(par_id[amont].get("sorties") or ())
        entrees = set(par_id[aval].get("entrees") or ())
        assert sorties & entrees, (
            "la chaine temoin casse entre %s et %s : sorties %s, entrees %s"
            % (amont, aval, sorted(sorties) or "(non declarees)",
               sorted(entrees) or "(non declarees)"))


def test_au_moins_une_paire_de_briques_se_chaine(registre):
    """Le seuil le plus bas qui soit : deux briques, dans tout le registre.

    S'il rougit, le mot << composite >> ne designe rien d'executable.
    """
    apps = registre["applications"]
    paires = [(a["id"], b["id"])
              for a in apps for b in apps
              if a["id"] != b["id"]
              and set(a.get("sorties") or ()) & set(b.get("entrees") or ())]
    assert paires, (
        "aucune des %d briques ne peut en alimenter une autre : le registre est "
        "un catalogue a LIRE, pas un catalogue a COMPOSER" % len(apps))


# --- Le module composite.py -------------------------------------------------

import sys  # noqa: E402

sys.path.insert(0, str(RACINE / "sandbox-manager"))
import composite  # noqa: E402


@pytest.fixture
def apps(registre):
    return registre["applications"]


def repondre(noeuds):
    """Un lecteur de demande qui rend une suite fixe : aucun appel reseau."""
    return lambda _consigne: '{"noeuds": %s}' % json.dumps(noeuds)


# --- D2 : une promesse de verdict est une promesse de LANCEMENT -------------
#
# Relecture adverse du 22/09 (GLM-5.3, outils en lecture seule) : << la
# promesse de la page -- vous dit AVANT de lancer si c'est possible -- est
# fausse pour 14 briques sur 16 : le client lit "Oui, cette chaine tient",
# clique, et se casse au controle >>. Verifie contre le code : `verifier()` ne
# consulte nulle part `ROUTES` (6 briques sur 16) ni `BUDGET_PAR_BRIQUE`.

def test_une_brique_sans_route_ne_peut_pas_etre_PROMISE(apps):
    """Dix briques sur seize n'ont aucune route dans une chaine.

    Avant ce test, `[fabrication_image]` rendait un verdict favorable ; le
    client cliquait, le noeud partait vraiment chez le fournisseur pour les
    etapes precedentes, et la chaine se cassait sur `brique_sans_route`.
    """
    chaine = composite.chaine_depuis_briques(["image_fabrication"], apps)
    verdict = composite.verifier(chaine)
    assert verdict["atteignable"] == composite.NON, verdict["pourquoi"]
    assert "brique_sans_route" in verdict["motifs"], verdict["motifs"]
    assert "Fabrication d'image" in verdict["pourquoi"], verdict["pourquoi"]


def test_une_brique_au_budget_ferme_ne_peut_pas_etre_PROMISE(apps):
    """La garde de budget est fermee par defaut et RIEN ne la branche.

    `budget_modal.verifier()` n'est appelee par aucun chemin composite (grep
    sur le depot : aucun appelant ne passe `garde_budget`). Un noeud qui peut
    partir chez le loueur refuse donc a tous les coups -- le verdict doit le
    dire AVANT, pas le laisser decouvrir au clic.
    """
    chaine = composite.chaine_depuis_briques(["video_soignee"], apps)
    verdict = composite.verifier(chaine)
    assert verdict["atteignable"] == composite.NON, verdict["pourquoi"]
    assert "budget_non_verifie" in verdict["motifs"], verdict["motifs"]


def test_la_chaine_temoin_reste_PROMISE(apps):
    """L'autre bras : la garde se retourne, elle ne refuse pas tout.

    Sans ce bras, une garde qui dirait << non >> a tout aurait l'air de
    marcher.
    """
    chaine = composite.chaine_depuis_briques(list(TEMOIN), apps)
    verdict = composite.verifier(chaine)
    assert verdict["atteignable"] != composite.NON, verdict["pourquoi"]
    assert "brique_sans_route" not in verdict["motifs"], verdict["motifs"]
    assert "budget_non_verifie" not in verdict["motifs"], verdict["motifs"]


@pytest.mark.parametrize("brique", [
    "chat_auto", "chat_max", "chat_secours_openrouter", "chat_secours_groq",
    "image_lecture", "image_fabrication", "recherche_web", "voix_fr", "voix_en",
    "dictee_locale", "dictee_groq", "video_rapide", "video_soignee",
    "video_maison", "chanson", "dialogue"])
def test_un_verdict_qui_ne_dit_pas_NON_tient_sa_promesse(apps, brique):
    """L'invariant, sur les SEIZE : promis ⇒ lancable.

    C'est la propriete que D2 violait, et elle se verifie sans reseau : une
    brique promise doit avoir une route, et la garde de budget ne doit pas la
    refuser au premier pas.
    """
    chaine = composite.chaine_depuis_briques([brique], apps)
    verdict = composite.verifier(chaine)
    if verdict["atteignable"] == composite.NON:
        return  # rien n'est promis : rien a tenir
    assert brique in composite.ROUTES, (
        "%s est promise et n'a aucune route" % brique)
    trace = composite.executer(chaine, lambda _e, _x: "rendu", entree=b"son",
                               verdict=verdict)
    assert trace["ou"] != composite.CONTROLE, trace


# --- D6 : la demande du client atteint le noeud -----------------------------

def test_la_demande_du_client_atteint_chaque_noeud(apps):
    """Elle etait portee par le graphe et par la chaine, et jamais lue.

    Mesure de la relecture : << Quel temps fera-t-il demain ? >> partait au
    modele sous la forme << Resume ce texte en quelques phrases :\n\nNone >>,
    et le Studio rendait << C'est fait >>.
    """
    chaine = composite.chaine_depuis_briques(["chat_auto"], apps)
    chaine["phrase"] = "Quel temps fera-t-il demain ?"
    vues = []
    composite.executer(chaine, lambda e, _x: vues.append(e.get("demande")) or "ok")
    assert vues == ["Quel temps fera-t-il demain ?"], vues


def test_le_chat_porte_la_demande_du_client_pas_un_resume_fige():
    """La consigne se fabrique a part, pour etre lisible sans reseau."""
    etape = {"brique": "chat_auto", "fonction": "Chat",
             "demande": "Traduis ce texte en anglais"}
    consigne = composite._consigne_du_chat(etape, "Bonjour tout le monde")
    assert "Traduis ce texte en anglais" in consigne
    assert "Bonjour tout le monde" in consigne


def test_un_noeud_seul_ne_recoit_jamais_le_mot_None():
    """Sans entree, la demande EST le message. `str(None)` n'en est pas un."""
    etape = {"brique": "chat_auto", "fonction": "Chat",
             "demande": "Quel temps fera-t-il demain ?"}
    consigne = composite._consigne_du_chat(etape, None)
    assert "None" not in consigne, consigne
    assert "Quel temps fera-t-il demain ?" in consigne


# --- D7 et D8 : la brique servie est celle qui est nommee -------------------

def test_deux_briques_a_la_MEME_adresse_sont_distinguees():
    """Sinon le routeur tranche seul, et l'etiquette ment.

    Exception nommee et mesuree : les deux voix partagent `/v1/audio/speech`
    parce que le routeur lit CHAQUE segment dans sa propre langue
    (`decouper_par_langue`) et n'accepte aucun champ de langue. Ce n'est pas
    une brique servie pour une autre : c'est une seule route, et deux fiches.
    """
    import json as _json
    par_chemin = {}
    for brique, (_genre, chemin) in composite.ROUTES.items():
        par_chemin.setdefault(chemin, []).append(brique)
    for chemin, briques in sorted(par_chemin.items()):
        if len(briques) < 2 or chemin == "/v1/audio/speech":
            continue
        precisions = [composite.PRECISION.get(b) for b in briques]
        assert all(precisions), (chemin, briques, precisions)
        empreintes = {_json.dumps(p, sort_keys=True) for p in precisions}
        assert len(empreintes) == len(briques), (chemin, precisions)


def test_la_dictee_locale_EXIGE_de_rester_sur_la_machine(par_id):
    """Le registre promet << la voix ne quitte pas la machine >>.

    Releve du 22/09 : les deux dictees partaient a la meme adresse sans dire
    laquelle, et la route choisit Groq d'abord des qu'une cle est branchee. La
    voix partait donc chez Groq sous l'etiquette de la brique locale. Ce test
    lie le code a la promesse du registre : si la promesse change, il sonne.
    """
    assert "ne quitte pas la machine" in par_id["dictee_locale"]["nature"]
    assert composite.PRECISION["dictee_locale"] == {"moteur": "local"}
    assert composite.PRECISION["dictee_groq"] == {"moteur": "groq"}


def test_chaque_chat_part_sur_SON_modele(par_id):
    """`chat_max` tournait sur Flash-Lite sous l'etiquette de Flash."""
    assert par_id["chat_max"]["modele"] != par_id["chat_auto"]["modele"]
    assert composite.PRECISION["chat_auto"] == {"model": "free-ai-auto"}
    assert composite.PRECISION["chat_max"] == {"model": "free-ai-max"}


def _routeur_simule(monkeypatch, reponse):
    """Remplace le transport d'httpx : on lit ce qui PART, rien ne sort."""
    import httpx

    vues = []

    def transport(requete):
        vues.append(requete)
        return reponse

    vrai = httpx.Client
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: vrai(transport=httpx.MockTransport(transport), **kw))
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-interne-de-test")
    return vues


def test_le_noeud_de_dictee_ENVOIE_le_moteur_au_routeur(apps, monkeypatch):
    """Le maillon. Sans lui, la table et la route sont justes et la voix part.

    Trouve MUET par le rituel de mutation : retirer l'envoi ne cassait rien.
    """
    import httpx

    vues = _routeur_simule(monkeypatch, httpx.Response(200, json={"text": "bonjour"}))
    etape = composite.chaine_depuis_briques(["dictee_locale"], apps)["etapes"][0]
    assert composite.lancer_par_le_routeur(etape, b"RIFF....WAVE") == "bonjour"
    assert b'name="moteur"\r\n\r\nlocal\r\n' in vues[0].content, vues[0].content[:400]


def test_le_noeud_de_chat_ENVOIE_son_modele_ET_la_demande(apps, monkeypatch):
    """Meme maillon, cote chat : `chat_max` tournait sous le modele d'Auto."""
    import httpx

    vues = _routeur_simule(monkeypatch, httpx.Response(
        200, json={"choices": [{"message": {"content": "Hello"}}]}))
    etape = dict(composite.chaine_depuis_briques(["chat_max"], apps)["etapes"][0],
                 demande="Traduis ce texte en anglais")
    assert composite.lancer_par_le_routeur(etape, "Bonjour") == "Hello"
    envoi = json.loads(vues[0].content)
    assert envoi["model"] == "free-ai-max", envoi
    assert "Traduis ce texte en anglais" in envoi["messages"][0]["content"]
    assert "Bonjour" in envoi["messages"][0]["content"]


# --- D4 : ce qui est lance est ce qui a ete montre --------------------------

def test_une_chaine_se_rebatit_des_BRIQUES_sans_rappeler_le_modele(apps):
    """<< Lancer >> recompilait : un second appel au modele, non deterministe.

    La page tient deja les briques qu'elle a montrees. Les rebatir est
    deterministe, gratuit, et rend impossible l'ecart entre la chaine vue et
    la chaine lancee.
    """
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    liee = composite.lier(graphe, apps)
    rebatie = composite.chaine_depuis_briques(
        [e["brique"] for e in liee["etapes"]], apps, phrase=liee["phrase"])
    assert rebatie == liee


def test_une_brique_inconnue_se_refuse_avec_son_motif(apps):
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.chaine_depuis_briques(["brique_qui_nexiste_pas"], apps)
    assert refus.value.motif == "brique_inconnue"
    assert "brique_qui_nexiste_pas" in refus.value.phrase


# --- SP-LICENCE-DUNE-CHAINE : la preuve de cloture --------------------------

def test_une_chaine_qui_contient_la_chanson_est_refusee(apps):
    """L'usage non commercial est contagieux : il se propage a la chaine.

    C'est la preuve de cloture de SP-LICENCE-DUNE-CHAINE, et elle est bornee
    sur la SEULE brique reellement non commerciale des seize.
    """
    graphe = composite.compiler("une chanson", repondre(["chanson"]), apps)
    chaine = composite.lier(graphe, apps)
    verdict = composite.verifier(chaine)
    assert verdict["atteignable"] == composite.NON, verdict
    assert "chaine_non_commerciale" in verdict["motifs"], verdict
    assert "commercial" in verdict["pourquoi"]


def test_la_garde_de_licence_ne_mord_PAS_sur_la_chaine_temoin(apps):
    """Le defaut que la relecture adverse a trouve dans le plan, devenu test.

    La preuve de SP-LICENCE exigeait d'abord qu'une chaine contenant `voix_fr`
    soit refusee -- et le temoin du lot se TERMINE par `voix_fr`. Ecrit ainsi,
    le lot echouait apres coup : soit la garde refusait et le temoin mourait
    dans son propre controle, soit elle ne refusait pas et la preuve etait
    incurable.

    La cause : deux licences sans rapport. GPL contraint la DIFFUSION ;
    << CC BY-NC >> interdit l'USAGE commercial. La fiche de `voix_fr` dit
    << usage commercial permis >>. Ce test garde la distinction, dans les deux
    sens, pour que personne ne la reperde.
    """
    assert composite.est_non_commercial(
        "poids : CC BY-NC 4.0, USAGE NON COMMERCIAL ; code `yue2_infer` : Apache 2.0")
    assert not composite.est_non_commercial(
        "Piper : GPL-3.0-or-later. Voix : CC BY 4.0 (base SIWIS) \u2014 usage "
        "commercial permis en citant la source")
    assert not composite.est_non_commercial(
        "Apache 2.0 \u2014 la licence elle-m\u00eame n'interdit rien, usage "
        "commercial compris")


def test_une_seule_des_seize_briques_est_non_commerciale(apps):
    """La garde se retourne : si la prose d'une licence change, ceci sonne."""
    trouvees = {a["id"] for a in apps if composite.est_non_commercial(a["licence"])}
    assert trouvees == {"chanson"}, trouvees


# --- lier : l'abstention est une reponse, pas un trou -----------------------

def test_lier_s_abstient_quand_deux_briques_se_valent(apps):
    """`conversation_secours` est portee par les DEUX secours du routeur.

    Rien dans le code ne les departage pour un composite -- le routeur les
    choisit lui-meme quand le premier tombe. S'abstenir est donc juste, et
    c'est le seul endroit du registre ou le cas se presente : le controle peut
    echouer, donc il a le droit d'exister.
    """
    graphe = {"phrase": "", "noeuds": [{"capacite": "conversation_secours"}]}
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.lier(graphe, apps)
    assert refus.value.motif == "plusieurs_briques_se_valent"
    assert "chat_secours_groq" in refus.value.phrase
    assert "chat_secours_openrouter" in refus.value.phrase


def test_lier_nomme_la_brique_de_chaque_noeud_du_temoin(apps):
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    chaine = composite.lier(graphe, apps)
    assert [e["brique"] for e in chaine["etapes"]] == list(TEMOIN)


# --- verifier : le verdict avant toute depense ------------------------------

def test_le_temoin_est_atteignable_et_gratuit(apps):
    """Le critere chiffre d'avance du lot : la chaine tient, et elle coute 0."""
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    verdict = composite.verifier(composite.lier(graphe, apps))
    assert verdict["atteignable"] == composite.OUI, verdict
    assert verdict["cout_max_usd"] == 0
    # La somme d'argent sort en francais, comme partout ailleurs dans le Studio.
    assert "0,00" in verdict["pourquoi"], verdict["pourquoi"]


def test_le_temoin_dit_que_le_chat_exige_une_cle(apps):
    """<< Gratuit >> n'est pas << sans cle >>, et le registre distingue.

    Defaut trouve le 22/09 EN FAISANT TOURNER la chaine contre le service :
    le verdict annoncait << gratuite : 0,00 $ >> pour une chaine dont deux
    noeuds sur trois reclamaient un compte branche. Vrai au comptoir, faux a
    l'usage -- sur une installation neuve elle s'arrete au premier de ces
    noeuds. Le prix reste 0 ; c'est l'annonce qui etait incomplete.
    """
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    verdict = composite.verifier(composite.lier(graphe, apps))
    assert "cle_requise" in verdict["motifs"], verdict
    assert "Chat" in verdict["pourquoi"], verdict["pourquoi"]
    # Les deux autres noeuds du temoin n'en demandent pas : la phrase ne doit
    # pas les accuser.
    assert "Dict\u00e9e" not in verdict["pourquoi"], verdict["pourquoi"]
    assert "haute voix" not in verdict["pourquoi"], verdict["pourquoi"]


def _verdict_temoin(apps):
    """Le verdict de la chaine temoin : gratuite, et une cle reclamee."""
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    return composite.verifier(composite.lier(graphe, apps))


def test_le_verdict_porte_des_faits_pas_seulement_une_phrase(apps):
    """Ce qui est vrai est structure ; la phrase se redige a partir de lui.

    Le partage demande le 22/09 : le calcul etablit les faits, le modele les met
    en francais. Les tests portent donc sur les faits -- un mot qui change dans
    une phrase ne doit pas casser une suite de tests, et un montant qui change
    doit la casser.
    """
    verdict = _verdict_temoin(apps)
    quoi = [f["quoi"] for f in verdict["faits"]]
    assert "gratuite" in quoi, verdict["faits"]
    assert "cle_requise" in quoi, verdict["faits"]
    gratuite = next(f for f in verdict["faits"] if f["quoi"] == "gratuite")
    assert gratuite["montant"] == "0,00 $", gratuite
    cle = next(f for f in verdict["faits"] if f["quoi"] == "cle_requise")
    assert "Chat, Free AI Auto" in cle["applications"], cle
    # Le remede fait partie du fait : un refus sans son remede n'apprend rien.
    assert "/cles" in cle["ou_la_configurer"], cle


def test_le_modele_redige_et_sa_phrase_est_gardee(apps):
    """Quand le modele rend du bon francais avec le bon montant, on le garde."""
    verdict = _verdict_temoin(apps)
    # Elle NOMME l'application, comme le modele le fait en service reel : le
    # fait porte ce nom, et depuis le 22/09 une phrase qui le perd ou le
    # deforme retombe sur la phrase ecrite.
    bonne = ("Cette cha\u00eene ne vous co\u00fbtera rien : 0,00 $. Chat, Free AI "
             "Auto a besoin d'un service d\u00e9j\u00e0 branch\u00e9 dans la page Cl\u00e9s.")
    rendu = composite.rediger(verdict, lambda _c: bonne)
    # L'etat est ecrit d'avance par le calcul ; l'explication vient du modele.
    assert rendu.startswith("Oui, cette chaîne tient."), rendu
    assert bonne in rendu, rendu


def test_sans_AUCUN_fait_la_phrase_ecrite_reste(apps):
    """Rien a mettre en francais : le modele n'est meme pas consulte.

    Trouve MUET par le rituel de mutation du 22/09 au soir : tous mes tests
    passaient par un verdict portant un montant, et une autre garde attrapait
    le cas avant celle-ci. Ici l'etat est << oui >> et la phrase du modele est
    inoffensive -- si la garde tombe, cette phrase arrive a l'ecran.
    """
    verdict = {"atteignable": composite.OUI,
               "pourquoi": "Cette cha\u00eene tient.",
               "faits": []}
    appele = []

    def modele(_consigne):
        appele.append(1)
        return "Tout va bien."

    assert composite.rediger(verdict, modele) == "Cette cha\u00eene tient."
    assert appele == [], "le modele ne doit pas etre appele sans faits"


def test_une_phrase_INTERMINABLE_est_refusee(apps):
    """Un modele qui part en roue libre ne remplit pas l'ecran du debutant.

    L'autre moitie de la mutation muette. Le verdict porte des faits SANS
    montant -- la garde des sommes n'a donc rien a exiger, la garde des nombres
    ne trouve aucun nombre invente, et l'etat est << oui >> : cette garde-ci est
    la SEULE qui puisse encore refuser. Elle est donc joue seule, ce qui est
    tout l'objet.
    """
    verdict = {"atteignable": composite.OUI,
               "pourquoi": "Cette cha\u00eene tient.",
               "faits": [{"quoi": "cle_requise",
                          "applications": ["Chat"],
                          "ou_la_configurer": "la page des identifiants"}]}
    courte = "Il faut brancher une cl\u00e9 pour Chat."
    longue = courte + (" C'est la m\u00eame chose, redite." * 40)
    assert len(longue) > 700, len(longue)

    # la courte passe : la garde se retourne, elle ne refuse pas tout
    assert composite.rediger(verdict, lambda _c: courte) != verdict["pourquoi"]
    # l'interminable retombe sur la phrase ecrite
    assert composite.rediger(verdict, lambda _c: longue) == verdict["pourquoi"]


def test_une_phrase_qui_PERD_le_montant_est_refusee(apps):
    """Le verdict porte un chiffre. Une phrase qui le laisse tomber ne le dit plus."""
    verdict = _verdict_temoin(apps)
    # Elle NOMME l'application : sans cela, la garde des noms attraperait
    # cette phrase avant celle du montant, et ce test cesserait de mesurer
    # ce qu'il annonce (mesure du rituel de mutation, 22/09 au soir).
    sans = ("Cette cha\u00eene est gratuite et tr\u00e8s simple \u00e0 utiliser "
            "avec Chat, Free AI Auto.")
    assert composite.rediger(verdict, lambda _c: sans) == verdict["pourquoi"]
    assert "0,00" in verdict["pourquoi"], verdict["pourquoi"]


def test_une_phrase_qui_INVENTE_un_montant_est_refusee(apps):
    """Le verrou qui compte : un nombre fabrique est ce que ce depot refuse partout.

    La somme calculee est bien presente -- c'est la SECONDE, celle que personne
    n'a calculee, qui fait refuser la phrase.
    """
    verdict = _verdict_temoin(apps)
    inventee = ("Cette cha\u00eene est gratuite : 0,00 $ avec Chat, Free AI "
                "Auto, mais comptez environ 3,50 $ par mois.")
    assert composite.rediger(verdict, lambda _c: inventee) == verdict["pourquoi"]


# Six facons d'ecrire un montant, dont CINQ echappaient a la garde du 22/09.
# Mesure de ce jour-la, avant correction : 1 attrape sur 6. Le trou venait d'un
# motif ecrit contre un seul format -- deux decimales et un dollar -- alors que
# `format_fr.en_dollars(valeur, decimales)` prend ses decimales en parametre et
# que le compteur Modal du Studio s'affiche a quatre. La garde compte desormais
# les NOMBRES, pas les sommes bien formees.
SIX_FORMATS = [
    "12,50 $",       # deux decimales : le seul que l'ancienne garde voyait
    "5,1979 $",      # quatre decimales : le format du compteur Modal d'ici
    "10 $",          # aucune decimale
    "$12.50",        # ecriture americaine
    "3,5 $",         # une decimale
    "11,40 EUR",     # une autre monnaie
]


@pytest.mark.parametrize("somme", SIX_FORMATS)
def test_un_montant_invente_est_refuse_QUEL_QUE_SOIT_son_format(apps, somme):
    """Une garde ecrite contre un format ne garde que ce format.

    Chaque phrase porte la somme CALCULEE -- elle passe donc la premiere garde,
    celle qui exige que le montant soit dit. C'est la seconde somme, que
    personne n'a calculee, qui doit faire retomber sur la phrase ecrite.
    """
    verdict = _verdict_temoin(apps)
    inventee = ("Cette cha\u00eene est gratuite : 0,00 $ avec Chat, Free AI "
                "Auto. Comptez %s en plus." % somme)
    assert composite.rediger(verdict, lambda _c: inventee) == verdict["pourquoi"]


def test_quand_aucun_modele_ne_repond_la_phrase_ecrite_reste(apps):
    """La circularite : << aucun service de chat ne repond >> ne peut pas etre
    ecrit par un service de chat. C'est pourquoi la phrase ecrite existe."""
    verdict = _verdict_temoin(apps)

    def muet(_consigne):
        raise composite.CompositeRefuse(
            "chat_indisponible", "Aucun service de chat gratuit ne repond.")

    assert composite.rediger(verdict, muet) == verdict["pourquoi"]
    assert composite.rediger(verdict, lambda _c: "") == verdict["pourquoi"]
    assert composite.rediger(verdict, lambda _c: "x" * 900) == verdict["pourquoi"]


def test_une_reponse_vide_du_modele_ne_devient_jamais_la_phrase():
    """Le controle de longueur, mis a l'epreuve la ou il est SEUL.

    Trouve par le rituel de mutation (plan §3.7) : la garde etait silencieuse,
    parce que tous mes essais portaient un montant a retrouver. Sur une chaine
    vide il n'y en a aucun, et une reponse vide du modele deviendrait une page
    sans un mot -- un << rien >> que le client lirait comme une panne.
    """
    vide = composite.verifier({"etapes": []})
    assert vide["atteignable"] == composite.NON
    assert vide["faits"] == [{"quoi": "chaine_vide"}], vide["faits"]
    assert vide["pourquoi"], "le repli doit exister avant qu'on s'appuie dessus"

    for reponse in ("", "   ", "\n", "x" * 900):
        assert composite.rediger(vide, lambda _c, r=reponse: r) == vide["pourquoi"], reponse


def _verdict_refuse(apps):
    """Le verdict d'une chaine refusee : la chanson, seule brique non commerciale."""
    graphe = composite.compiler("une chanson", repondre(["chanson"]), apps)
    return composite.verifier(composite.lier(graphe, apps))


def test_l_etat_du_verdict_ne_passe_jamais_par_le_modele(apps):
    """Quoi que le modele reponde, le << non >> est ecrit par le calcul.

    C'est le verrou principal, et il tient meme si l'explication est mauvaise :
    l'etat n'a jamais quitte le code.
    """
    verdict = _verdict_refuse(apps)
    assert verdict["atteignable"] == composite.NON
    assert verdict["pourquoi"].startswith("Non :"), verdict["pourquoi"]

    honnete = ("Cette cha\u00eene ne peut pas \u00eatre utilis\u00e9e : la licence de "
               "Chanson l'interdit pour un usage commercial. Le co\u00fbt maximum "
               "serait de 0,52 $.")
    assert composite.rediger(verdict, lambda _c: honnete).startswith("Non :")


def _verdict_inconnu(apps):
    """Un verdict `inconnu`, bati sur les FAITS REELS de `dialogue`.

    L'etat est pose a la main, et il faut dire pourquoi plutot que de le
    laisser croire mesure : depuis le 22/09, aucune chaine reelle ne vaut
    `inconnu` -- les six briques lancables sont toutes gratuites, licenciees et
    sans carte, et tout le reste est refuse avant (cliquet ci-dessus). Les
    FAITS, eux, ne sont pas inventes : ils sortent de `verifier` sur
    `[dialogue]`, et le test du cout les epingle separement. Le jour ou une
    route s'ajoute, le cliquet rougit et cette construction redevient inutile.
    """
    reel = composite.verifier(
        composite.chaine_depuis_briques(["dialogue"], apps))
    assert any(f["quoi"] == "cout_sans_nombre" for f in reel["faits"]), reel
    return dict(reel, atteignable=composite.INCONNU,
                pourquoi=composite.ENTETE[composite.INCONNU]
                + " Le co\u00fbt de Dialogue n'a pas de nombre par travail "
                  "mesur\u00e9.")


def test_un_plancher_n_est_pas_un_PRIX(apps):
    """Le fait doit nommer les trois choses, sinon le modele en fait un prix.

    Mesure du 22/09 : avec une cle nommee `montant_minimum`, le modele ecrivait
    << ne coute que 0,00 $ >> sur deux tirages sur trois -- une certitude sur de
    l'argent, la ou le calcul dit qu'il ne sait pas. Les noms des faits SONT le
    vocabulaire montre : le fait porte le plancher, le maximum inconnu, et ce
    que ca change.
    """
    fait = [f for f in _verdict_inconnu(apps)["faits"]
            if f["quoi"] == "cout_sans_nombre"]
    assert len(fait) == 1, fait
    assert "plancher" in fait[0], fait[0]
    assert "inconnu" in fait[0]["maximum"], fait[0]
    assert "n'est pas un prix" in fait[0]["consequence"], fait[0]
    # et la somme reste EXIGEE dans la phrase : un renommage qui viderait
    # l'ensemble des sommes attendues ferait taire la garde sans rien casser.
    assert "plancher" in composite.CLES_DE_SOMME, composite.CLES_DE_SOMME


def test_un_INCONNU_ecrit_comme_une_certitude_est_refuse(apps):
    """La jumelle de la garde du refus, pour l'etat qui dit << je ne sais pas >>.

    Une phrase sans aucun mot de doute fait retomber sur la phrase ecrite. La
    somme est presente et vient bien des faits : c'est l'ASSURANCE qui est
    fausse, pas le nombre -- donc ni la garde des nombres ni l'entete
    deterministe ne peuvent l'attraper.
    """
    verdict = _verdict_inconnu(apps)
    trop_sure = ("Cette cha\u00eene ne co\u00fbte que 0,00 $ avec Dialogue "
                 "\u00e0 plusieurs voix.")
    assert composite.rediger(verdict, lambda _c: trop_sure) == verdict["pourquoi"]


def test_un_INCONNU_qui_DIT_le_doute_passe(apps):
    """Et la garde se retourne : elle laisse passer ce qui dit vrai.

    Sans ce second bras, une garde qui refuse tout aurait l'air de marcher.
    """
    verdict = _verdict_inconnu(apps)
    juste = ("Le plancher de cette cha\u00eene est 0,00 $, mais son maximum "
             "reste inconnu : le co\u00fbt de Dialogue \u00e0 plusieurs voix n'a "
             "pas de nombre par travail mesur\u00e9.")
    rendu = composite.rediger(verdict, lambda _c: juste)
    assert rendu != verdict["pourquoi"], rendu
    assert rendu.startswith(composite.ENTETE[composite.INCONNU]), rendu


def _verdict_a_deux_noms(apps):
    """La chaine temoin dans sa variante distante : DEUX noms a rendre."""
    verdict = composite.verifier(composite.chaine_depuis_briques(
        ["dictee_groq", "chat_auto", "voix_fr"], apps))
    noms = {n for f in verdict["faits"]
            for n in f.get(composite.CLE_DES_NOMS, ())}
    assert len(noms) == 2, noms
    return verdict


def test_un_nom_d_application_DEFORME_est_refuse(apps):
    """Mesure du 22/09 : << Dictee « Groq si posible » >>, deux fois sur sept.

    La phrase ci-dessous porte la bonne somme et n'invente aucun nombre : les
    deux gardes precedentes la laissent passer. Seule celle des noms peut la
    refuser, ce qui est tout l'objet.
    """
    verdict = _verdict_a_deux_noms(apps)
    deforme = ("Cette cha\u00eene est gratuite : 0,00 $. Les applications "
               "Dict\u00e9e \u00ab Groq si posible \u00bb et Chat, Free AI Auto "
               "exigent une cl\u00e9.")
    assert composite.rediger(verdict, lambda _c: deforme) == verdict["pourquoi"]


def test_un_nom_d_application_INTACT_passe(apps):
    """L'autre bras : la garde se retourne, elle ne refuse pas tout."""
    verdict = _verdict_a_deux_noms(apps)
    juste = ("Cette cha\u00eene est gratuite : 0,00 $. Les applications "
             "Dict\u00e9e \u00ab Groq si possible \u00bb et Chat, Free AI Auto "
             "exigent une cl\u00e9.")
    rendu = composite.rediger(verdict, lambda _c: juste)
    assert rendu != verdict["pourquoi"], rendu
    assert rendu.startswith(composite.ENTETE[composite.OUI]), rendu


def test_la_cle_des_noms_est_celle_que_les_faits_portent(apps):
    """Un renommage qui viderait l'ensemble ferait taire la garde en silence.

    Meme panne que celle du 22/09 au matin sur `montant_minimum` : le nom
    change d'un cote, le lecteur reste de l'autre, l'ensemble devient vide, et
    un ensemble vide ne rougit jamais.
    """
    verdict = _verdict_a_deux_noms(apps)
    assert any(composite.CLE_DES_NOMS in f for f in verdict["faits"]), verdict["faits"]


def test_un_refus_ne_devient_jamais_un_mode_d_emploi(apps):
    """Le defaut du 22/09, mesure sur la sortie reelle du service.

    Le modele avait rendu, pour une chaine REFUSEE : << Pour utiliser
    l'application Chanson a des fins non commerciales, le cout maximum s'eleve a
    0,52 $ >>. Les montants etaient justes, la licence citee, et le sens
    inverse : un refus presente comme une facon de s'en servir. Le mot du refus
    n'y etait pas.
    """
    verdict = _verdict_refuse(apps)
    mode_d_emploi = ("Pour utiliser l'application Chanson \u00e0 des fins non "
                     "commerciales, le co\u00fbt maximum s'\u00e9l\u00e8ve \u00e0 0,52 $ "
                     "et la licence impose le respect des r\u00e8gles CC BY-NC 4.0.")
    # Le montant est bon, la licence est bonne -- et la phrase est refusee
    # quand meme, parce qu'elle ne dit pas le refus.
    assert composite.rediger(verdict, lambda _c: mode_d_emploi) == verdict["pourquoi"]


def test_la_phrase_de_la_cle_s_accorde_en_nombre(apps):
    """Une phrase francaise ne s'accorde pas en remplacant son sujet.

    Defaut trouve le 22/09 en lisant la sortie du verdict de la chaine reelle :
    << Plusieurs etapes A BESOIN d'un service deja branche >>. Le sujet variait,
    le verbe non -- et l'article et le pronom de reprise non plus. Les deux
    nombres sont joues ici, parce qu'un gabarit a trou n'est faux que dans un
    des deux.
    """
    # UN seul noeud reclame une cle : le chat.
    un = composite.verifier(composite.lier(
        composite.compiler("reponds-moi", repondre(["conversation"]), apps), apps))
    assert "cle_requise" in un["motifs"], un
    assert "Une étape a besoin" in un["pourquoi"], un["pourquoi"]
    assert "Sans lui," in un["pourquoi"], un["pourquoi"]

    # DEUX noeuds en reclament une : la dictee distante, puis le chat.
    deux = composite.verifier(composite.lier(
        composite.compiler(
            "transcris puis resume",
            repondre(["transcription_distante", "conversation"]), apps), apps))
    assert "cle_requise" in deux["motifs"], deux
    assert "Plusieurs étapes ont besoin" in deux["pourquoi"], deux["pourquoi"]
    assert "Sans eux," in deux["pourquoi"], deux["pourquoi"]
    # Et le mot faux ne doit revenir par aucun chemin.
    assert "étapes a besoin" not in deux["pourquoi"], deux["pourquoi"]


def test_les_briques_sans_cle_sont_exactement_celles_que_le_registre_dit(apps):
    """La garde se retourne : si la prose de `cout` change, ceci sonne."""
    sans_cle = {a["id"] for a in apps if not composite.exige_une_cle(a["cout"])}
    assert sans_cle == {"recherche_web", "voix_fr", "voix_en", "dictee_locale",
                        "video_maison"}, sans_cle


def test_une_chaine_dont_les_types_ne_s_enchainent_pas_est_refusee(apps):
    """Le controle deterministe a enfin quelque chose a comparer."""
    graphe = {"phrase": "", "noeuds": [{"capacite": "synthese_vocale_fr"},
                                       {"capacite": "fabrication_image"}]}
    verdict = composite.verifier(composite.lier(graphe, apps))
    assert verdict["atteignable"] == composite.NON, verdict
    assert "types_incompatibles" in verdict["motifs"]
    assert "audio" in verdict["pourquoi"] and "texte" in verdict["pourquoi"]


def test_un_cout_sans_nombre_mesure_est_DIT_et_jamais_arrondi_a_zero(apps):
    """`dialogue` n'a qu'un plafond mensuel, aucun nombre par travail.

    Un plafond partage n'est pas le cout d'un travail. Repondre << gratuit >>
    serait un faux-vert.

    Ce test exigeait l'etat << inconnu >>. Il ne l'exige plus depuis le 22/09,
    et ce n'est pas un relachement : `dialogue` n'a aucune route dans une
    chaine ET sa garde de budget refuse a tous les coups, donc l'etat vaut
    << non >>, qui est un refus plus fort et vrai. Le bras du cout n'est pas
    mort pour autant -- il ecrit toujours son motif et son fait, et la mesure
    porte desormais sur eux. Le refus qui masque l'etat est NOMME ici, pour que
    le prochain lecteur ne croie pas a une garde desserree.
    """
    verdict = composite.verifier(
        composite.chaine_depuis_briques(["dialogue"], apps))
    assert "cout_sans_nombre" in verdict["motifs"], verdict["motifs"]
    assert verdict["cout_max_usd"] == 0
    fait = [f for f in verdict["faits"] if f["quoi"] == "cout_sans_nombre"]
    assert len(fait) == 1, verdict["faits"]
    assert fait[0]["plancher"] == "0,00 $", fait[0]
    assert "inconnu" in fait[0]["maximum"], fait[0]
    assert verdict["atteignable"] == composite.NON
    assert "brique_sans_route" in verdict["motifs"], verdict["motifs"]


def test_aucune_chaine_reelle_n_atteint_PARTIEL_ni_INCONNU_aujourd_hui(apps):
    """Le cliquet du masquage. Ce n'est pas une garde : c'est un signal.

    Mesure du 22/09, apres le bras de la route : sur les seize briques, six
    sont lancables en chaine, et toutes les six sont gratuites, de licence
    nommee et sans carte. Les etats `partiel` et `inconnu` ne sont donc
    atteignables par AUCUNE chaine reelle -- non parce que leurs bras seraient
    morts, mais parce qu'un refus plus fort arrive avant.

    Le jour ou une route s'ajoute, ce test rougit. C'est voulu : il dit au
    prochain lecteur que les deux etats redeviennent montrables au client, et
    que la garde du doute de `rediger` redevient atteignable en production.
    """
    etats = {composite.verifier(
        composite.chaine_depuis_briques([a["id"]], apps))["atteignable"]
        for a in apps}
    assert etats <= {composite.OUI, composite.NON}, etats
    assert len(composite.ROUTES) == 6, sorted(composite.ROUTES)


def test_une_licence_qu_on_ne_peut_pas_nommer_rend_inconnu(apps):
    """Le premier secours sert un modele qui change d'une requete a l'autre.

    Sa fiche dit << celle du modele route, variable >>. On ne peut donc pas
    dire la licence de la chaine entiere : c'est << inconnu >>, pas << oui >>.
    """
    assert composite.licence_indeterminee("celle du mod\u00e8le rout\u00e9, variable")
    assert not composite.licence_indeterminee("Apache 2.0")


def test_le_cout_dune_chaine_payante_est_la_somme_des_pires_cas(apps):
    """Chaque nombre vient de la prose mesuree, aucun n'est estime."""
    graphe = {"phrase": "", "noeuds": [{"capacite": "video_soignee"}]}
    verdict = composite.verifier(composite.lier(graphe, apps))
    assert verdict["cout_max_usd"] == 0.558
    assert "0,56" in verdict["pourquoi"], verdict["pourquoi"]


# --- compiler : ce qu'il refuse, et pourquoi --------------------------------

def test_compiler_refuse_une_fonction_inventee(apps):
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.compiler("fais-moi un cafe", repondre(["cafe_serre"]), apps)
    assert refus.value.motif == "capacite_inventee"
    assert refus.value.ou == composite.COMPILATION


def test_compiler_refuse_une_reponse_illisible(apps):
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.compiler("n'importe quoi", lambda _c: "je ne sais pas", apps)
    assert refus.value.motif == "reponse_illisible"


def test_compiler_dit_ce_qu_il_sait_faire_quand_il_ne_trouve_rien(apps):
    """Une liste vide est une reponse permise : mieux que choisir au hasard."""
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.compiler("pilote ma voiture", repondre([]), apps)
    assert refus.value.motif == "aucune_suite"
    assert "conversation" in refus.value.phrase


# --- executer : la trace dit OU ca a casse, pas SI --------------------------

def test_la_trace_nomme_l_etape_ou_la_chaine_a_casse(apps):
    """Un booleen ne fait pas tourner le volant."""
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    chaine = composite.lier(graphe, apps)

    def lancer(etape, entree):
        if etape["brique"] == "chat_auto":
            raise composite.CompositeRefuse(
                "sans_cle", "Aucun service gratuit branche.", ou=composite.EXECUTION)
        return "quelque chose"

    trace = composite.executer(chaine, lancer, entree="un enregistrement")
    assert trace["resultat"] == "refus"
    assert trace["ou"] == composite.EXECUTION
    assert trace["motif"] == "sans_cle"
    # Le premier noeud a bien rendu : la trace le dit, au lieu d'un << faux >>.
    assert trace["etapes"][0] == {"brique": "dictee_locale", "resultat": "rendu",
                                  "motif": None}
    assert trace["etapes"][1]["brique"] == "chat_auto"


def test_la_trace_dune_chaine_entiere_nomme_chaque_brique(apps):
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    chaine = composite.lier(graphe, apps)
    trace = composite.executer(chaine, lambda _e, _x: "rendu", entree="son")
    assert trace["resultat"] == "rendu"
    assert [e["brique"] for e in trace["etapes"]] == list(TEMOIN)
    assert all(e["resultat"] == "rendu" for e in trace["etapes"])
# --- la garde de budget, par noeud et fermee par defaut ---------------------

def test_un_noeud_qui_peut_partir_chez_le_loueur_ne_part_pas_sans_budget(apps):
    """Le seul defaut qui coute de l'argent est celui qui lance sans demander.

    `budget_modal.verifier()` est taille pour UN travail : un usage parmi
    quatre, une carte, une duree. Un total de chaine n'y entre pas. La chaine
    delegue donc au module de la brique, qui porte deja SON `budget_verifier`,
    et tant que l'appelant ne l'a pas passe, le noeud NE PART PAS.
    """
    graphe = {"phrase": "", "noeuds": [{"capacite": "video_rapide"}]}
    chaine = composite.lier(graphe, apps)
    lancee = []
    trace = composite.executer(chaine, lambda e, x: lancee.append(e) or "clip",
                               entree="un chat qui dort")
    assert trace["resultat"] == "refus"
    assert trace["motif"] == "budget_non_verifie"
    assert trace["ou"] == composite.CONTROLE
    assert lancee == [], "le noeud a ete lance malgre le refus"


def test_la_garde_de_budget_est_appelee_pour_chaque_noeud(apps):
    """Par noeud, JUSTE AVANT le lancement -- pas une fois pour la chaine."""
    graphe = composite.compiler(
        "resume cet enregistrement et lis-le-moi",
        repondre(["transcription_locale", "conversation", "synthese_vocale_fr"]),
        apps)
    chaine = composite.lier(graphe, apps)
    vus = []
    composite.executer(chaine, lambda _e, _x: "rendu", entree="son",
                       garde_budget=lambda e: vus.append(e["brique"]))
    assert vus == list(TEMOIN)


def test_la_chaine_temoin_ne_touche_modal_nulle_part(apps):
    """Mesure, pas affirmation : aucune de ses trois briques n'est louable.

    C'est ce qui rend le critere << 0,00 $ >> verifiable sans depenser.
    """
    chaine = composite.lier(
        {"phrase": "", "noeuds": [{"capacite": c} for c in
                                  ("transcription_locale", "conversation",
                                   "synthese_vocale_fr")]}, apps)
    for etape in chaine["etapes"]:
        assert etape["brique"] not in composite.BUDGET_PAR_BRIQUE, etape["brique"]
        assert "modal" not in etape["modes"], etape["brique"]
