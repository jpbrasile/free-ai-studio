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
import format_fr  # noqa: E402


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
    """Des briques du registre n'ont aucune route dans une chaine.

    Avant ce test, une telle brique rendait un verdict favorable ; le client
    cliquait, les noeuds precedents partaient vraiment chez le fournisseur, et
    la chaine se cassait sur `brique_sans_route`.

    Le vehicule a change le 22/09 au soir, et le motif merite d'etre ecrit.
    C'etait `image_fabrication`, qui a maintenant une route ; c'est desormais
    `recherche_web`, qui n'en aura pas : le Studio ne sert aucune adresse de
    recherche. `WEB_SEARCH_ENGINE` est un REGLAGE passe au frontal de chat
    (`docker-compose.yml:220`), et le registre le dit deja lui-meme en portant
    `code: null` la ou les quinze autres briques pointent une ligne de code.
    Un test dont le vehicule guerit se repointe, il ne se desserre pas.
    """
    chaine = composite.chaine_depuis_briques(["recherche_web"], apps)
    verdict = composite.verifier(chaine)
    assert verdict["atteignable"] == composite.NON, verdict["pourquoi"]
    assert "brique_sans_route" in verdict["motifs"], verdict["motifs"]
    assert "Recherche Web" in verdict["pourquoi"], verdict["pourquoi"]


def test_une_brique_sans_ligne_de_code_n_a_pas_de_route(par_id):
    """Le registre porte deja la reponse : `code` dit la ligne qui fait foi.

    Une brique dont AUCUNE ligne ne fait foi n'a rien a brancher. Ce test lie
    les deux affirmations pour qu'elles ne puissent plus diverger en silence :
    le jour ou quelqu'un ecrit la route de la recherche Web, il devra d'abord
    ecrire le code qu'elle appelle.
    """
    assert par_id["recherche_web"]["code"] is None, par_id["recherche_web"]
    assert "recherche_web" not in composite.ROUTES


def test_un_budget_DEPASSE_se_dit_avant_le_clic(apps):
    """Ce qui reste interdit, c'est de DEPASSER -- et c'est le module qui le dit.

    Ce test remplace `test_une_brique_au_budget_ferme_ne_peut_pas_etre_PROMISE`,
    dont la premisse est tombee le 22/09/2026 sur un ordre du proprietaire :
    << les depenses sont de fausses depenses tant que l'on reste dans le budget
    free >>. L'ancien refusait TOUTE brique pouvant partir chez un loueur, sans
    rien mesurer ; il s'interdisait un credit qu'on a. Mesure du jour : les
    quatre briques louables tiennent toutes dans le credit offert.

    Ce n'est pas un desserrage : le refus est plus etroit ET plus dur. Il porte
    maintenant sur un depassement DIT par `budget_verifier()` du module, avec
    sa phrase, et il est ici joue sur ses quatre bras.
    """
    verdict = composite.verifier(
        composite.chaine_depuis_briques(["dialogue"], apps),
        sonde_budget=lambda _e: "Le budget du mois est épuisé.")
    assert verdict["atteignable"] == composite.NON, verdict["pourquoi"]
    assert "budget_depasse" in verdict["motifs"], verdict["motifs"]
    # La phrase du module est relayee telle quelle : la chaine n'en ecrit pas
    # une plus vague par-dessus.
    assert "Le budget du mois est épuisé." in verdict["pourquoi"]


def test_un_clip_ne_meurt_PAS_d_un_loueur_ferme_il_reste_la_carte_d_ici(apps):
    """Le loueur ferme n'est pas la fin du monde pour un clip -- et le code le dit.

    Mesure du 22/09 dans `app.py` : `/video/creer` consulte
    `ou_calculer.decider()` AVANT (l. 2309) et ne verifie le budget que si la
    decision dit << modal >> (l. 2333) ; un clip part alors sur la carte d'ici,
    gratuitement. `/chanson/creer` (l. 2541) et `/dialogue/creer` (l. 2923),
    eux, appellent `budget_verifier` sans jamais consulter la decision.

    Donc : meme sonde, meme depassement, DEUX verdicts differents. Repondre
    << non >> au clip serait un faux-rouge, aussi faux que le faux-vert.
    """
    verdict = composite.verifier(
        composite.chaine_depuis_briques(["video_rapide"], apps),
        sonde_budget=lambda _e: "Le budget du mois est épuisé.")
    assert verdict["atteignable"] == composite.PARTIEL, verdict["pourquoi"]
    assert "loueur_ferme" in verdict["motifs"], verdict["motifs"]
    assert "budget_depasse" not in verdict["motifs"], verdict["motifs"]
    assert "carte de votre ordinateur" in verdict["pourquoi"]


def test_un_budget_qui_TIENT_ne_refuse_RIEN(apps):
    """L'autre bras, et c'est celui que l'ordre du proprietaire a ouvert.

    Sans lui, une garde qui dirait << non >> a tout aurait de nouveau l'air de
    marcher -- c'est exactement ce qui s'etait installe.
    """
    verdict = composite.verifier(
        composite.chaine_depuis_briques(["video_rapide"], apps),
        sonde_budget=lambda _e: None)
    assert verdict["atteignable"] != composite.NON, verdict["pourquoi"]
    assert "budget_depasse" not in verdict["motifs"], verdict["motifs"]
    assert "loueur_ferme" not in verdict["motifs"], verdict["motifs"]


def test_un_budget_qu_on_ne_peut_pas_RELEVER_n_autorise_pas(apps):
    """Pas de mesure n'est pas une autorisation -- ni un refus : c'est INCONNU.

    Le module peut manquer sur une installation partielle, ou sa garde peut
    lever autre chose que `BudgetDepasse`. Le silence ne doit jamais valoir
    autorisation : c'est la regle qui gouverne toutes les gardes de ce fichier.
    """
    def casse(_e):
        raise RuntimeError("pas de module ici")

    verdict = composite.verifier(
        composite.chaine_depuis_briques(["video_rapide"], apps),
        sonde_budget=casse)
    assert verdict["atteignable"] == composite.INCONNU, verdict["pourquoi"]
    assert "budget_non_mesure" in verdict["motifs"], verdict["motifs"]


def test_la_chaine_temoin_reste_PROMISE(apps):
    """L'autre bras : la garde se retourne, elle ne refuse pas tout.

    Sans ce bras, une garde qui dirait << non >> a tout aurait l'air de
    marcher.
    """
    chaine = composite.chaine_depuis_briques(list(TEMOIN), apps)
    verdict = composite.verifier(chaine)
    assert verdict["atteignable"] != composite.NON, verdict["pourquoi"]
    assert "brique_sans_route" not in verdict["motifs"], verdict["motifs"]
    # `budget_non_verifie` n'existe plus : il refusait sans mesurer. Les deux
    # motifs qui l'ont remplace sont nommes ici, sinon cette ligne deviendrait
    # vraie parce qu'elle ne regarde plus rien.
    assert "budget_depasse" not in verdict["motifs"], verdict["motifs"]
    assert "loueur_ferme" not in verdict["motifs"], verdict["motifs"]


@pytest.mark.parametrize("brique", [
    "chat_auto", "chat_max", "chat_secours_openrouter", "chat_secours_groq",
    "image_lecture", "image_fabrication", "recherche_web", "voix_fr", "voix_en",
    "dictee_locale", "dictee_groq", "video_rapide",
    "video_maison", "chanson", "dialogue"])
def test_un_verdict_qui_ne_dit_pas_NON_tient_sa_promesse(apps, brique):
    """L'invariant, sur les QUINZE (le clip soigne retire le 23/09) : promis ⇒ lancable.

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
    for brique, (genre, chemin) in composite.ROUTES.items():
        # Le groupe est (genre, adresse) et non l'adresse seule : `image_lecture`
        # partage `/v1/chat/completions` avec les deux chats mais n'y envoie pas
        # la meme requete -- elle porte une image la ou ils portent du texte.
        # C'est l'enonce VRAI de l'invariant : deux briques qui batiraient la
        # MEME requete doivent se distinguer.
        par_chemin.setdefault((genre, chemin), []).append(brique)
    for (_genre, chemin), briques in sorted(par_chemin.items()):
        if len(briques) < 2 or chemin == "/v1/audio/speech":
            continue
        # Un travail ne se distingue pas par `PRECISION`, qui vise le
        # routeur du palier gratuit : les trois briques video partagent
        # l'adresse `(<< travail >>, << video >>)` et se distinguent par ce que
        # `TRAVAUX` fixe dans la demande -- la qualite pour les deux clips
        # loues, le reglage << toujours-maison >> pour le troisieme.
        precisions = [composite.TRAVAUX[b][1] if _genre == "travail"
                      else composite.PRECISION.get(b) for b in briques]
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


# --- Le type de ce qui SORT : mesure d'abord, declaration ensuite -----------

PNG = b"\x89PNG\r\n\x1a\n" + b"corps"
WAV = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"corps"


def test_une_image_en_sortie_n_est_PAS_annoncee_comme_un_son():
    """Le defaut du 22/09 au soir, trouve en branchant la fabrication d'image.

    La route de lancement annoncait `audio/wav` pour toute sortie binaire. Les
    octets etaient bons, le statut etait 200, et le navigateur montrait un
    lecteur audio muet. Aucun test existant ne pouvait le dire, parce qu'aucune
    chaine ne pouvait finir autrement que par une voix.
    """
    mime, nom = composite.type_de_sortie(PNG, ["image"])
    assert mime == "image/png", mime
    assert nom == "sortie.png", nom


def test_un_son_reste_un_son():
    """L'autre bras : la correction ne casse pas ce qui marchait."""
    mime, nom = composite.type_de_sortie(WAV, ["audio"])
    assert mime == "audio/wav", mime
    assert nom == "sortie.wav", nom


def test_les_octets_l_emportent_sur_le_type_DECLARE():
    """Une signature est une mesure, un champ declare est une promesse.

    Si une brique declare rendre du son et rend une image, c'est l'image qui
    part : le navigateur recevrait autrement un fichier etiquete faux, et le
    defaut ne se verrait qu'a l'ouverture.
    """
    assert composite.type_de_sortie(PNG, ["audio"])[0] == "image/png"


def test_une_sortie_que_RIEN_ne_reconnait_suit_le_type_declare():
    """A defaut de mesure, la promesse -- jamais une supposition."""
    assert composite.type_de_sortie(b"xyz", ["video"])[0] == "video/mp4"
    assert composite.type_de_sortie(b"xyz", [])[0] == "application/octet-stream"


def test_la_page_accepte_CHAQUE_type_d_entree_qu_une_brique_lancable_declare(apps):
    """Une route ouverte sans champ pour la nourrir ne sert a rien.

    Ecrit d'abord sur la seule chaine `accept="audio/*,image/*"`, ce test
    demandait d'etre recopie a chaque brique -- et un controle qu'on recopie est
    un controle qu'on finit par ajuster au lieu de le lire. Il DERIVE maintenant
    du registre : toute brique qui a une route et qui attend autre chose que du
    texte doit trouver son type dans le champ de fichier. La brique suivante est
    couverte sans que personne y pense.

    Le cas paye : `document_lecture` est arrivee le 22/09/2026 avec
    `entrees: ["fichier"]`, et le champ n'acceptait que `audio/*,image/*`. Le
    verdict aurait dit oui et le client n'aurait rien pu deposer -- exactement la
    faute que la version d'avant avait ete ecrite pour attraper, sur le type
    qu'elle ne connaissait pas.
    """
    import re as _re

    champ = _re.search(r'<input type=file[^>]*accept="([^"]+)"',
                       composite.PAGE_HTML)
    assert champ, "le champ de fichier n'a plus d'attribut accept"
    accepte = champ.group(1)

    # Le type nu -> ce qui doit apparaitre dans `accept` pour lui.
    ATTENDU = {"audio": "audio/*", "image": "image/*",
               "fichier": "application/pdf", "video": "video/*"}
    for app in apps:
        if app["id"] not in composite.ROUTES:
            continue
        for type_nu in app["entrees"]:
            if type_nu == "texte":
                continue  # la demande elle-meme, pas un fichier a deposer
            assert ATTENDU[type_nu] in accepte, (
                "%s attend %r et le champ ne l'accepte pas : %s"
                % (app["id"], type_nu, accepte))

    assert composite.ROUTES["image_lecture"][0] == "vision"
    assert composite.ROUTES["document_lecture"][0] == "document"


def test_le_noeud_qui_LIT_une_image_envoie_l_image_et_son_type(apps, monkeypatch):
    """Le maillon de la lecture d'image, et le type qui ne se devine pas.

    Deux choses partent ensemble et une seule ne suffirait pas : l'image, et
    l'etiquette de son format. Une image envoyee sous une etiquette au hasard
    est acceptee par certains fournisseurs et refusee par d'autres -- le defaut
    n'apparaitrait qu'une fois sur deux.
    """
    import base64
    import httpx

    vues = _routeur_simule(monkeypatch, httpx.Response(
        200, json={"choices": [{"message": {"content": "Un chat roux."}}]}))
    png = b"\x89PNG\r\n\x1a\n" + b"des octets d'image"
    etape = dict(composite.chaine_depuis_briques(["image_lecture"], apps)["etapes"][0],
                 demande="Qu'y a-t-il sur cette photo ?")
    assert composite.lancer_par_le_routeur(etape, png) == "Un chat roux."
    envoi = json.loads(vues[0].content)
    parties = envoi["messages"][0]["content"]
    assert parties[0]["type"] == "text", parties
    assert "Qu'y a-t-il sur cette photo ?" in parties[0]["text"], parties
    url = parties[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,"), url[:60]
    assert base64.b64decode(url.split(",", 1)[1]) == png


def test_une_image_de_format_inconnu_se_REFUSE_au_lieu_d_etre_etiquetee(apps):
    """L'autre bras. Deviner marcherait parfois, et c'est le pire des cas."""
    etape = composite.chaine_depuis_briques(["image_lecture"], apps)["etapes"][0]
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.lancer_par_le_routeur(etape, b"ceci n'est pas une image")
    assert refus.value.motif == "image_de_format_inconnu", refus.value.motif


def test_le_noeud_qui_FABRIQUE_une_image_rend_des_octets(apps, monkeypatch):
    """La sortie declaree est `image` : ce qui sort doit etre l'image, pas son
    encodage en base64. Une chaine qui rendrait le texte du base64 passerait le
    controle de types et livrerait au client un fichier illisible."""
    import base64
    import httpx

    png = b"\x89PNG\r\n\x1a\n" + b"fabriquee"
    vues = _routeur_simule(monkeypatch, httpx.Response(
        200, json={"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]}))
    etape = dict(composite.chaine_depuis_briques(["image_fabrication"], apps)["etapes"][0],
                 demande="Dessine un chat roux")
    assert composite.lancer_par_le_routeur(etape, None) == png
    envoi = json.loads(vues[0].content)
    assert "Dessine un chat roux" in envoi["prompt"], envoi
    assert "size" not in envoi, "sans format choisi, le modele choisit, comme avant"


@pytest.mark.parametrize("format_, taille", [("1:1", "1024x1024"), ("16:9", "1344x768"),
                                              ("9:16", "768x1344")])
def test_le_format_choisi_part_avec_la_demande_d_image(apps, monkeypatch, format_, taille):
    """23/09 : << les tailles x, y de l'image de sortie [sont] figes >>. Le
    format choisi part en << LxH >>, que le routeur ramene a la proportion
    comprise par Google."""
    import base64
    import httpx

    vues = _routeur_simule(monkeypatch, httpx.Response(
        200, json={"data": [{"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")}]}))
    etape = dict(composite.chaine_depuis_briques(["image_fabrication"], apps)["etapes"][0],
                 demande="Dessine un phare", reglages={"format": format_})
    composite.lancer_par_le_routeur(etape, None)
    envoi = json.loads(vues[0].content)
    assert envoi["size"] == taille
    largeur, hauteur = (int(x) for x in taille.split("x"))
    # la meme regle que aspect_ratio() du routeur : la proportion arrive intacte
    assert format_ == ("1:1" if largeur == hauteur else "16:9" if largeur > hauteur else "9:16")


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

    Depuis le 23/09, la garde du module donne un maximum a `dialogue` : le cout
    << sans nombre >> ne se voit plus que quand elle ne rend rien -- d'ou la
    sonde muette.
    """
    reel = composite.verifier(
        composite.chaine_depuis_briques(["dialogue"], apps),
        sonde_mesure=lambda _e: None)
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
                        "video_maison", "document_lecture"}, sans_cle


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

    Ce test a exige l'etat << inconnu >>, l'a perdu le 22/09 au matin sous DEUX
    refus qui arrivaient avant (aucune route, budget ferme d'avance), et le
    retrouve le 22/09 au soir : `dialogue` a maintenant sa route de travail, et
    le budget ne refuse plus sans mesurer. Les deux masques sont tombes le meme
    jour, et l'etat qu'ils cachaient etait bien celui-ci.

    C'est le cliquet du masquage qui a rendu ce retour visible, et son texte
    annoncait le jour ou : << le jour ou une route de loueur s'ouvrira, il
    rougira de nouveau, et cette fois les deux etats redeviendront montrables
    au client >>. Il a rougi, et l'etat est montrable.

    Depuis le 23/09, la garde du module donne un maximum a `dialogue` (test
    suivant) : ce cas-ci ne vaut plus que quand elle ne rend rien.
    """
    verdict = composite.verifier(
        composite.chaine_depuis_briques(["dialogue"], apps),
        sonde_mesure=lambda _e: None)
    assert "cout_sans_nombre" in verdict["motifs"], verdict["motifs"]
    assert verdict["cout_max_usd"] == 0
    fait = [f for f in verdict["faits"] if f["quoi"] == "cout_sans_nombre"]
    assert len(fait) == 1, verdict["faits"]
    assert fait[0]["plancher"] == "0,00 $", fait[0]
    assert "inconnu" in fait[0]["maximum"], fait[0]
    assert verdict["atteignable"] == composite.INCONNU, verdict["motifs"]
    assert "brique_sans_route" not in verdict["motifs"], verdict["motifs"]


def test_le_dialogue_a_un_MAXIMUM_celui_de_sa_garde(apps, tmp_path, monkeypatch):
    """Le registre n'a pas de cout par dialogue ; la garde du module, si.

    Avant le 23/09, le verdict disait << on ne peut pas dire son maximum >>
    alors que `dialogue.budget_verifier` refuse deja au pire cas, chiffre en
    main (0,759 $). Ce nombre-la est le maximum : on le dit, et on avoue que le
    cout HABITUEL reste inconnu. Vraie garde, compteur jetable.
    """
    import budget_modal
    monkeypatch.setattr(budget_modal, "FICHIER", tmp_path / "modal-budget.json")
    chaine = composite.chaine_depuis_briques(["dialogue"], apps)
    pire = composite.mesure_du_noeud(chaine["etapes"][0])["cout_max_usd"]
    assert pire > 0, pire
    verdict = composite.verifier(chaine)
    assert "cout_sans_nombre" not in verdict["motifs"], verdict["motifs"]
    fait = [f for f in verdict["faits"] if f["quoi"] == "cout_maximum"]
    assert len(fait) == 1, verdict["faits"]
    assert fait[0]["montant"] == format_fr.en_dollars(pire), fait[0]
    assert fait[0]["sans_mesure_par_travail"] == [chaine["etapes"][0]["fonction"]], fait[0]
    assert format_fr.en_dollars(pire) in verdict["pourquoi"], verdict["pourquoi"]
    assert "coût habituel" in verdict["pourquoi"], verdict["pourquoi"]
    assert verdict["atteignable"] != composite.INCONNU, verdict["motifs"]


def test_dialogue_plus_clip_additionne_la_garde_et_le_registre(apps):
    """Le maximum d'une chaine mixte : garde pour le pas sans nombre, garde
    aussi pour le clip (son pire cas passe le cout mesure du registre)."""
    mesures = {"dialogue": 0.759, "video_rapide": 0.883}
    chaine = composite.chaine_depuis_briques(["dialogue"], apps)
    chaine["etapes"] += composite.chaine_depuis_briques(["video_rapide"], apps)["etapes"]
    verdict = composite.verifier(
        chaine, sonde_budget=lambda _e: None,
        sonde_mesure=lambda e: {"refus": None, "cout_max_usd": mesures[e["brique"]],
                                "reste_usd": 15.0})
    fait = [f for f in verdict["faits"] if f["quoi"] == "cout_maximum"]
    assert len(fait) == 1 and fait[0]["montant"] == format_fr.en_dollars(0.759 + 0.883), fait


# Deux cartes POSEES. Elles rendent la forme de `gpu_local.utilisable` : le
# troisieme element est le releve, et c'est son `vue` qui separe une carte
# absente d'une carte prise par quelqu'un d'autre.
CARTE_LIBRE = lambda mo: (  # noqa: E731
    True, "Carte posee par le test : libre pour %d Mo." % mo,
    {"vue": True, "nom": "carte du test", "libre_mo": mo + 4096})
CARTE_ABSENTE = lambda mo: (  # noqa: E731
    False, "Carte posee par le test : aucune carte sur cette machine.",
    {"vue": False, "nom": None, "libre_mo": None})
CARTE_OCCUPEE = lambda mo: (  # noqa: E731
    False, "Carte posee par le test : prise par un autre calcul.",
    {"vue": True, "nom": "carte du test", "libre_mo": 512})


def test_le_masquage_des_etats_est_REMESURE_a_chaque_route_ouverte(apps):
    """Le cliquet du masquage. Ce n'est pas une garde : c'est un signal.

    Il a rougi trois fois en un jour, et les trois fois il disait vrai :
      - six briques lancables, `partiel` et `inconnu` atteignables par AUCUNE
        chaine reelle -- non que leurs bras fussent morts, mais qu'un refus
        plus fort arrivait avant ;
      - huit, apres les deux routes d'image : rien ne bouge, les huit etant
        gratuites, de licence nommee et sans carte ;
      - TREIZE, le 22/09 au soir, apres les cinq routes de travail et le budget
        mesure. `inconnu` est revenu, porte par `dialogue` et son plafond mensuel
        sans nombre par travail. Le texte d'hier annoncait ce jour-la ; il est
        venu ;
      - QUATORZE, avec `document_lecture`. Les trois etats ne bougent pas : elle
        est gratuite, de licence nommee (BSD-3) et sans carte, donc elle rejoint
        le groupe `oui` sans rien y changer.

    LES DEUX sondes sont POSEES, et la seconde l'a ete apres coup : le
    22/09/2026 ce cliquet a rougi sur le runner et pas ici. La ligne
    d'hier -- << `partiel` reste hors d'atteinte d'une chaine reelle >> --
    etait FAUSSE, et seule une machine sans carte pouvait le montrer : ma
    4090 repondait << 24138 Mo libres >>, le runner n'a aucune carte, et
    `video_maison` seul y rend `partiel`. Le budget etait pose, la carte ne
    l'etait pas -- aucun test du fichier ne posait `sonde_carte`. Un cliquet
    qui change avec la machine ne dit plus rien du code, qu'il s'agisse du
    compteur d'un loueur ou de la carte d'ici.

    Les deux bras que ce cliquet ne joue donc PAS, et qui ont chacun le
    leur : `partiel` par
    `test_un_clip_ne_meurt_PAS_d_un_loueur_ferme_il_reste_la_carte_d_ici` et
    `test_sans_carte_du_tout_le_clip_maison_rend_partiel_et_le_DIT`.
    """
    etats = {composite.verifier(
        composite.chaine_depuis_briques([a["id"]], apps),
        sonde_budget=lambda _e: None,
        sonde_carte=CARTE_LIBRE)["atteignable"]
        for a in apps}
    assert etats == {composite.OUI, composite.NON, composite.INCONNU}, etats
    assert len(composite.ROUTES) == 13, sorted(composite.ROUTES)  # 14 avant le retrait du clip soigne, 23/09


def test_une_licence_qu_on_ne_peut_pas_nommer_rend_inconnu(apps):
    """Le premier secours sert un modele qui change d'une requete a l'autre.

    Sa fiche dit << celle du modele route, variable >>. On ne peut donc pas
    dire la licence de la chaine entiere : c'est << inconnu >>, pas << oui >>.
    """
    assert composite.licence_indeterminee("celle du mod\u00e8le rout\u00e9, variable")
    assert not composite.licence_indeterminee("Apache 2.0")


def test_le_cout_dune_chaine_payante_est_la_somme_des_pires_cas(apps):
    """Chaque nombre vient de la prose mesuree, aucun n'est estime."""
    graphe = {"phrase": "", "noeuds": [{"capacite": "video_rapide"}]}
    verdict = composite.verifier(composite.lier(graphe, apps))
    assert verdict["cout_max_usd"] == 0.277
    assert "0,28" in verdict["pourquoi"], verdict["pourquoi"]


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
    # Depuis le 23/09, l'etape rendue porte aussi sa fonction et son texte.
    premiere = trace["etapes"][0]
    assert {k: premiere[k] for k in ("brique", "resultat", "motif")} == {
        "brique": "dictee_locale", "resultat": "rendu", "motif": None}
    assert premiere["texte"] == "quelque chose"
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

def test_un_noeud_qui_DEPASSE_ne_part_pas__sans_qu_on_ait_a_brancher_la_garde(apps):
    """Le seul defaut qui coute de l'argent est celui qui lance sans demander.

    Deux choses d'un coup, et c'est voulu : la garde est posee PAR DEFAUT (nul
    besoin de passer `garde_budget` pour qu'elle morde), et elle mord sur un
    depassement MESURE par le module, plus sur l'absence de mesure.

    L'ancienne version de ce test exigeait qu'un noeud louable ne parte jamais
    sans garde branchee. Sa premisse est tombee le 22/09/2026 : la garde est
    branchee, et ce qu'elle refuse est le depassement, pas la location.
    """
    graphe = {"phrase": "", "noeuds": [{"capacite": "video_rapide"}]}
    chaine = composite.lier(graphe, apps)
    lancee = []
    # On remplace la SONDE, pas la garde : c'est le chemin par defaut qui est
    # sous mesure ici.
    avant = composite.budget_du_noeud
    composite.budget_du_noeud = lambda _e: "Le budget du mois est épuisé."
    try:
        trace = composite.executer(chaine, lambda e, x: lancee.append(e) or "clip",
                                   entree="un chat qui dort")
    finally:
        composite.budget_du_noeud = avant
    assert trace["resultat"] == "refus"
    assert trace["motif"] == "budget_depasse"
    assert trace["ou"] == composite.CONTROLE
    assert lancee == [], "le noeud a ete lance malgre le refus"


def test_un_noeud_qui_TIENT_dans_le_credit_part_pour_de_bon(apps):
    """Le bras que le refus d'avance rendait injouable.

    Tant que la garde refusait par principe, aucun test ne POUVAIT montrer un
    noeud louable qui part. Celui-ci le montre, et c'est la moitie du travail
    demande le 22/09.
    """
    graphe = {"phrase": "", "noeuds": [{"capacite": "video_rapide"}]}
    chaine = composite.lier(graphe, apps)
    lancee = []
    avant = composite.budget_du_noeud
    composite.budget_du_noeud = lambda _e: None
    try:
        trace = composite.executer(chaine, lambda e, x: lancee.append(e) or "clip",
                                   entree="un chat qui dort")
    finally:
        composite.budget_du_noeud = avant
    assert trace["resultat"] == "rendu", trace
    assert [e["brique"] for e in lancee] == ["video_rapide"], lancee


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
# --- Les cinq routes de TRAVAIL : creer, attendre, recuperer ----------------
# Elles ne passent pas par le routeur du palier gratuit : elles s'adressent au
# Studio lui-meme, aux adresses de ses propres pages. Les trois decisions du
# proprietaire du 22/09 viennent de la, sans etre reecrites : `/video/creer`
# consulte deja `ou_calculer.decider()`, rend 409 avec sa decision quand la
# carte est prise, et chaque module porte son `budget_verifier`.

def _studio_simule(monkeypatch, repondre):
    """Le Studio repond comme `app.py` repond, et on lit ce qui part."""
    import httpx

    vues = []

    def transport(requete):
        vues.append(requete)
        return repondre(requete)

    vrai = httpx.Client
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: vrai(transport=httpx.MockTransport(transport), **kw))
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-interne-de-test")
    # Le sondeur ne dort pas pendant un test, et il ne tourne pas non plus un
    # quart d'heure. Deux reglages, aucun chemin de decision touche.
    #
    # `DELAI_S` vaut 900 s en service. Un sondeur qui cesserait de separer
    # << pas ENCORE >> de << JAMAIS >> tournerait donc quinze minutes sur une
    # adresse morte -- et le banc PENDRAIT au lieu de rougir. C'est arrive ce
    # soir, au rituel de mutation : deux commandes perdues, et le `finally` du
    # rituel jamais joue parce que le processus avait ete tue, laissant la
    # mutation dans le fichier. Un test qui pend ne rapporte rien ; celui-ci
    # rougit.
    monkeypatch.setattr(composite, "ATTENTE_S", 0)
    monkeypatch.setattr(composite, "DELAI_S", 2)
    return vues


def _studio_video(etats, adresse="/video/jobs/j1/fichier?cle=jeton-du-travail"):
    """Un Studio qui accepte un clip, le fait attendre, puis rend son fichier.

    `etats` est la suite de statuts que l'etat renvoie, un par interrogation.
    Le fichier n'est servi QU'A l'adresse portant son jeton -- comme
    `app.py:2395`, qui compare `hmac.compare_digest(cle, attendu)` et repond
    401 sans lui. Un composite qui fabriquerait l'adresse recevrait donc 401,
    et ce transport-ci le lui rendrait.
    """
    import httpx

    restants = list(etats)

    def repondre(requete):
        chemin = requete.url.path
        if chemin == "/video/creer":
            return httpx.Response(200, json={"id": "j1", "status": "queued"})
        if chemin == "/video/jobs/j1":
            statut = restants.pop(0) if restants else "succeeded"
            corps = {"id": "j1", "status": statut}
            if statut == "succeeded":
                corps["video_url"] = adresse
            return httpx.Response(200, json=corps)
        if chemin == "/video/jobs/j1/fichier":
            if requete.url.params.get("cle") != "jeton-du-travail":
                return httpx.Response(401, json={"detail": "Unauthorized"})
            return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42")
        return httpx.Response(404, json={"detail": "inconnu"})

    return repondre


def test_un_travail_se_cree_attend_puis_rend_son_fichier(apps, monkeypatch):
    """Le chemin entier d'un noeud qui fabrique un TRAVAIL, sans reseau.

    C'est ce qui fait passer le Studio de huit briques chainables a treize :
    les cinq briques qui creent un travail ne repondent pas sur le coup, elles
    rendent un identifiant et se font attendre.
    """
    vues = _studio_simule(monkeypatch, _studio_video(["queued", "running"]))
    etape = composite.chaine_depuis_briques(["video_rapide"], apps)["etapes"][0]
    sortie = composite.lancer_par_le_routeur(
        dict(etape, demande="un chat qui dort"), "un chat qui dort")
    assert sortie[4:8] == b"ftyp", sortie[:16]
    # La qualite part avec la demande : c'est ce qui distingue les deux clips
    # loues l'un de l'autre, et le routeur ne la devine pas.
    import json as _json
    envoye = _json.loads(vues[0].content)
    assert envoye["qualite"] == "rapide", envoye
    assert envoye["description"] == "un chat qui dort", envoye
    # Trois interrogations d'etat : queued, running, succeeded.
    assert [v.url.path for v in vues].count("/video/jobs/j1") == 3, [
        v.url.path for v in vues]


def test_le_fichier_se_prend_a_l_adresse_que_l_ETAT_donne(apps, monkeypatch):
    """Le defaut du 22/09 au soir, trouve en LISANT `app.py` et non en testant.

    Le composite allait chercher `/video/jobs/<id>/fichier` avec la cle du
    Studio dans l'entete. Cette route-la ne lit pas l'entete : elle compare un
    jeton par travail passe en parametre (`hmac.compare_digest`, app.py:2395)
    et repond 401 sans lui. Le nom du champ qui porte l'adresse change en plus
    avec l'usage -- `video_url` pour la video (l. 2379), `son_url` pour la
    chanson (l. 2599) et le dialogue (l. 2975).

    Ce test fixe la regle : l'adresse se LIT dans la reponse d'etat, elle ne se
    fabrique pas. Le transport rend 401 a toute adresse sans jeton, exactement
    comme le service.
    """
    vues = _studio_simule(monkeypatch, _studio_video([]))
    etape = composite.chaine_depuis_briques(["video_rapide"], apps)["etapes"][0]
    composite.lancer_par_le_routeur(dict(etape, demande="un chat"), "un chat")
    dernier = vues[-1]
    assert dernier.url.path == "/video/jobs/j1/fichier", dernier.url
    assert dernier.url.params.get("cle") == "jeton-du-travail", dernier.url


def test_un_travail_fini_SANS_fichier_le_dit_au_lieu_de_rendre_du_vide(apps, monkeypatch):
    """Un travail reussi qui ne depose rien n'est pas une sortie vide.

    Sans ce bras, le pas suivant recevrait `None` et casserait plus loin, sur
    un motif qui ne designerait plus le vrai coupable.
    """
    import httpx

    def repondre(requete):
        if requete.url.path == "/video/creer":
            return httpx.Response(200, json={"id": "j1"})
        return httpx.Response(200, json={"id": "j1", "status": "succeeded"})

    _studio_simule(monkeypatch, repondre)
    etape = composite.chaine_depuis_briques(["video_rapide"], apps)["etapes"][0]
    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(dict(etape, demande="un chat"), "un chat")
    assert pris.value.motif == "travail_sans_fichier", pris.value.motif


def test_un_409_de_creer_devient_une_QUESTION_au_client(apps, monkeypatch):
    """La carte est prise : ce n'est pas une panne, c'est une question.

    `/video/creer` rend 409 avec la decision d'`ou_calculer.decider()` en
    detail (app.py:2317), parce qu'aucune regle ecrite d'avance ne sait si le
    client est presse. Le composite relaie la phrase francaise du module au
    lieu d'en ecrire une plus vague -- c'est la troisieme decision du
    proprietaire, et elle ne coute pas une ligne de logique nouvelle.
    """
    import httpx

    decision = {"ou": "on-demande",
                "pourquoi": "La carte de votre ordinateur est occupée. "
                            "Attendre ne coûte rien ; louer coûte 0,12 $."}

    _studio_simule(monkeypatch,
                   lambda _r: httpx.Response(409, json={"detail": decision}))
    etape = composite.chaine_depuis_briques(["video_rapide"], apps)["etapes"][0]
    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(dict(etape, demande="un chat"), "un chat")
    assert pris.value.motif == "arbitrage_du_client", pris.value.motif
    assert "Attendre ne coûte rien" in pris.value.phrase, pris.value.phrase


def test_carte_libre_au_controle_PRISE_au_depart_d_un_seul_tenant(apps, sandbox, monkeypatch):
    """Le cas du point 15.5, joue d'un bout a l'autre et non en deux moities.

    La carte est libre quand le flow est verifie ; un julia la prend avant que
    l'etape parte. Le composite ne sonde pas lui-meme au depart : il rappelle
    `/video/creer`, qui redecide a la seconde du depart. Ici, le VRAI
    gestionnaire repond (TestClient derriere le transport de httpx) : la
    decision, le 409 et la question sont les siens, pas une reponse ecrite
    d'avance. Et rien n'est parti."""
    import httpx
    from fastapi.testclient import TestClient

    releve = {"vue": True, "nom": "NVIDIA GeForce RTX 4090", "totale_mo": 24564,
              "libre_mo": 24138, "marge_mo": 1024, "motif": ""}
    etat = {"libre": True}

    def sonde(besoin_mo, delai_s=None):
        if etat["libre"]:
            return True, "24138 Mo libres.", releve
        return False, "3200 Mo libres, il en faut %d." % (besoin_mo + 1024), dict(releve, libre_mo=3200)

    # Le gestionnaire avec une carte declaree, et rien qui parte vraiment.
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "http://sandbox-worker-gpu:8000")
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "maison_prete", lambda: (True, "", False))
    partis = []
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: partis.append(a))
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "utilisable", sonde)

    client = TestClient(sandbox.app, base_url="http://127.0.0.1:8020")

    def vers_le_vrai_gestionnaire(requete):
        r = client.request(requete.method, requete.url.path, content=requete.content,
                           headers={k: v for k, v in requete.headers.items()
                                    if k.lower() in ("authorization", "content-type")})
        return httpx.Response(r.status_code, content=r.content, headers=r.headers)

    _studio_simule(monkeypatch, vers_le_vrai_gestionnaire)
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-sandbox-de-test")

    chaine = composite.chaine_depuis_briques(["video_rapide"], apps)
    verdict = composite.verifier(chaine, sonde_carte=sonde, sonde_budget=lambda _e: None)
    assert "carte_occupee" not in verdict["motifs"], verdict["motifs"]

    etat["libre"] = False  # le julia arrive entre le controle et le depart
    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(dict(chaine["etapes"][0], demande="un phare"),
                                        "un phare")
    assert pris.value.motif == "arbitrage_du_client", pris.value.motif
    assert "3200" in pris.value.phrase, pris.value.phrase
    assert partis == []


def test_un_404_pendant_l_attente_ne_devient_PAS_pas_encore_pret(apps, monkeypatch):
    """Un sondeur separe << pas ENCORE >> de << JAMAIS >>.

    Une boucle d'attente est le seul endroit ou une faute ne produit aucun
    signal. Le 21/09/2026, un 404 traduit en << pas encore pret >> a coute
    cinquante minutes sur une adresse morte. Ici tout statut >= 400 leve
    immediatement, et seuls les etats que `app.py` ecrit vraiment font
    attendre.
    """
    import httpx

    def repondre(requete):
        if requete.url.path == "/video/creer":
            return httpx.Response(200, json={"id": "j1"})
        return httpx.Response(404, json={"detail": "Travail inconnu"})

    vues = _studio_simule(monkeypatch, repondre)
    etape = composite.chaine_depuis_briques(["video_rapide"], apps)["etapes"][0]
    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(dict(etape, demande="un chat"), "un chat")
    assert pris.value.motif == "noeud_refuse", pris.value.motif
    assert "Travail inconnu" in pris.value.phrase, pris.value.phrase
    # DEUX requetes en tout -- la creation, puis une seule interrogation. Il
    # n'a pas attendu une adresse morte, et c'est le nombre qui le prouve :
    # sans le refus, ce compteur monterait jusqu'a l'epuisement du delai.
    assert len(vues) == 2, [v.url.path for v in vues]


def test_un_travail_PERDU_ne_fait_pas_attendre_non_plus(apps, monkeypatch):
    """Les etats d'echec que `app.py` ecrit vraiment sont nommes, pas devines."""
    import httpx

    def repondre(requete):
        if requete.url.path == "/video/creer":
            return httpx.Response(200, json={"id": "j1"})
        return httpx.Response(200, json={"id": "j1", "status": "failed",
                                         "message": "le modèle a manqué de mémoire"})

    _studio_simule(monkeypatch, repondre)
    etape = composite.chaine_depuis_briques(["video_rapide"], apps)["etapes"][0]
    with pytest.raises(composite.CompositeRefuse) as pris:
        composite.lancer_par_le_routeur(dict(etape, demande="un chat"), "un chat")
    assert pris.value.motif == "travail_echoue", pris.value.motif
    assert "manqué de mémoire" in pris.value.phrase, pris.value.phrase


def test_la_chanson_prend_son_style_de_la_DEMANDE_et_ses_paroles_du_pas_davant():
    """Une chanson reclame DEUX choses, et elles ne viennent pas du meme endroit.

    Le style est ce que le client a demande ; les paroles sont ce que le noeud
    precedent a ecrit. Les confondre donnerait une chanson qui chante sa propre
    consigne -- c'est le defaut que le noeud de chat avait deja eu.
    """
    usage, demande = composite.demande_du_travail(
        {"brique": "chanson", "demande": "une berceuse douce"},
        "dors mon petit, la nuit est longue")
    assert usage == "chanson"
    assert demande["style"] == "une berceuse douce", demande
    assert demande["paroles"] == "dors mon petit, la nuit est longue", demande


def test_le_clip_MAISON_porte_son_reglage_et_ne_demande_aucune_qualite():
    """<< toujours-maison >> est un reglage, pas une qualite.

    C'est ce qui distingue `video_maison` des deux clips loues a la meme
    adresse, et c'est la premiere decision du proprietaire ecrite dans une
    table plutot que dans du code : le local passe devant parce que la demande
    le dit, et `ou_calculer.decider()` fait le reste.
    """
    _, demande = composite.demande_du_travail(
        {"brique": "video_maison", "demande": "un chat qui dort"}, "")
    assert demande["ou_calculer"] == "toujours-maison", demande
    assert "qualite" not in demande, demande
    assert "duree" not in demande, "sans reglage, le defaut de preparer(), comme avant"


def test_la_duree_reglee_part_avec_le_travail():
    """24/09 : << il manque des champs pour la duree >>. La duree part dans
    l'unite de la page du travail, et `preparer()` la lit telle quelle."""
    import chanson
    import video

    _, demande = composite.demande_du_travail(
        {"brique": "video_maison", "demande": "un phare", "reglages": {"duree": "3"}}, "")
    assert demande["duree"] == "3"
    plan = video.preparer(demande, pour_modal=False, maison=True)
    assert plan["demande"]["images"] == video.DUREES_MAISON["3"]["images"]
    _, demande = composite.demande_du_travail(
        {"brique": "chanson", "demande": "douce", "reglages": {"duree": "2"}}, "la la")
    assert demande["duree"] == "2" and "2" in chanson.DUREES


# --- 12. Les trois briques qui n'ont AUCUNE adresse, et pourquoi ------------

def test_les_deux_secours_sont_des_POSITIONS_pas_des_adresses(par_id):
    """On ne fabrique pas une route a une brique qui n'est pas une destination.

    Mesure du 22/09, verifiee contre le code et non de memoire :
    `free-tier-manager/app.py::chaine_de(modele)` ne prend QUE le modele et
    rend un ORDRE d'essai de fournisseurs. Rien dans la requete ne permet de
    demander OpenRouter ou Groq : le routeur y tombe quand les precedents
    tombent. Les deux fiches le disent elles-memes -- leur champ `code` pointe
    une entree de la table `PROVIDERS`, pas une adresse.

    Leur donner une route serait donc inventer un champ que le service n'a pas,
    et la brique servie ne serait pas celle qui est nommee. C'est la faute D7,
    deja payee une fois sur les deux dictees.
    """
    source = (RACINE / "free-tier-manager" / "app.py").read_text(encoding="utf-8")
    assert "def chaine_de(modele: str) -> List[str]:" in source, (
        "la signature a change : si un fournisseur peut desormais etre nomme, "
        "les deux secours deviennent des destinations et meritent une route")
    for brique in ("chat_secours_openrouter", "chat_secours_groq"):
        assert brique not in composite.ROUTES, brique
        assert "PROVIDERS[" in par_id[brique]["code"], par_id[brique]["code"]
    # Et elles partagent une capacite : c'est ce qui fait que `lier` s'abstient
    # au lieu d'en choisir une pour avoir l'air decide.
    assert (par_id["chat_secours_openrouter"]["capacite"]
            == par_id["chat_secours_groq"]["capacite"] == "conversation_secours")


def test_les_briques_sans_route_sont_EXACTEMENT_celles_qu_on_a_nommees(registre):
    """Le cliquet de la liste : trois, et on sait dire pourquoi chacune.

    Mesure du 22/09 au soir : quatorze briques sur dix-sept ont une route. Les
    trois qui n'en ont pas ne sont pas un reste -- chacune a son motif ecrit et
    verifie contre le code. Le jour ou une quatrieme apparait, ou ou l'une de
    ces trois trouve une adresse, ce test sonne et le motif se reecrit.

    La dix-septieme brique, `document_lecture`, est arrivee AVEC sa route : elle
    n'a donc pas fait bouger cette liste-ci, seulement le compte.
    """
    dehors = {a["id"] for a in registre["applications"]
              if a["id"] not in composite.ROUTES}
    assert dehors == {"chat_secours_openrouter", "chat_secours_groq",
                      "recherche_web"}, dehors
    assert len(composite.ROUTES) == 13, sorted(composite.ROUTES)  # 14 avant le retrait du clip soigne, 23/09


# --- 10. Preferer le local : y a-t-il seulement un choix a faire ? ----------

def test_aucune_capacite_n_oppose_aujourd_hui_une_brique_LOCALE_a_une_DISTANTE(apps):
    """Le cliquet de la preference locale. Pas une garde : un signal.

    L'ordre du proprietaire du 22/09 dit << privilegier le local si gpu existe
    et est libre >>. Pour les clips, c'est deja obtenu SANS ecrire une ligne :
    `/video/creer` consulte `ou_calculer.decider()`, dont le reglage par defaut
    est `maison-si-libre`, et la chaine passe par cette route-la.

    Ce qui n'est PAS obtenu, c'est l'arbitrage entre CANDIDATS dans `lier()` --
    et la mesure dit pourquoi : une seule capacite porte plusieurs briques,
    `conversation_secours`, et ses deux candidates sont distantes toutes les
    deux. Ecrire une preference locale serait donc un controle qui ne peut pas
    sonner, et un controle qui ne peut pas echouer se supprime au lieu de se
    reporter. On le remplace par ce signal : le jour ou une capacite opposera
    une brique locale a une distante, il rougit, et c'est ce jour-la qu'il
    faudra ecrire la preference.
    """
    par_capacite = {}
    for a in apps:
        par_capacite.setdefault(a["capacite"], []).append(a)

    a_choix = {c: b for c, b in par_capacite.items() if len(b) > 1}
    assert set(a_choix) == {"conversation_secours"}, sorted(a_choix)

    for capacite, briques in a_choix.items():
        locales = [b["id"] for b in briques if "local" in b["modes"]]
        assert not locales, (
            "%s oppose desormais une brique locale a une distante (%s) : la "
            "preference locale a maintenant un sujet, elle doit s'ecrire dans "
            "lier()" % (capacite, locales))


# --- 11. La question du client arrive JUSQU'A lui ---------------------------

def test_un_refus_porte_sa_PHRASE_dans_la_trace_et_pas_seulement_son_motif(apps):
    """Le defaut du 22/09 au soir, trouve en relisant le chemin complet.

    `executer` gardait `refus.motif` et jetait `refus.phrase`. La route levait
    ensuite 409 avec le motif. Quand la carte etait prise, le client lisait
    donc << arbitrage_du_client >> -- un slug -- au lieu de la question
    francaise que `ou_calculer.decider()` avait ecrite pour lui.

    La decision etait prise, relayee, et jamais montree. Un motif nomme est
    fait pour le journal ; une phrase est faite pour un debutant.
    """
    chaine = composite.chaine_depuis_briques(["chat_auto"], apps)

    def refuser(_etape, _entree):
        raise composite.CompositeRefuse(
            "arbitrage_du_client",
            "La carte de votre ordinateur est occupée. Attendre ne coûte "
            "rien ; louer coûte 0,12 $.", ou=composite.EXECUTION)

    trace = composite.executer(chaine, refuser, entree="bonjour",
                               garde_budget=lambda _e: None)
    assert trace["resultat"] == "refus"
    assert trace["motif"] == "arbitrage_du_client"
    assert "Attendre ne coûte rien" in (trace["phrase"] or ""), trace
    # Au pas aussi : la trace dit OU ca a casse, et avec quels mots.
    assert "Attendre ne coûte rien" in (trace["etapes"][-1]["phrase"] or "")


def test_un_echec_NON_nomme_met_son_texte_dans_la_phrase_et_un_NOM_dans_le_motif(apps):
    """Un meme champ ne peut pas avoir deux sens selon le chemin emprunte.

    Le motif portait `str(erreur)` sur ce bras-la et un slug partout ailleurs.
    Un journal qui compte les motifs comptait donc une categorie par message
    d'erreur.
    """
    chaine = composite.chaine_depuis_briques(["chat_auto"], apps)

    def casser(_etape, _entree):
        raise ValueError("le service n'a pas repondu")

    trace = composite.executer(chaine, casser, entree="bonjour",
                               garde_budget=lambda _e: None)
    assert trace["resultat"] == "echec"
    assert trace["motif"] == "ValueError", trace["motif"]
    assert trace["phrase"] == "le service n'a pas repondu", trace["phrase"]


def test_la_route_montre_la_QUESTION_au_client_et_journalise_le_motif(sandbox, apps,
                                                                     monkeypatch):
    """Le dernier metre : ce que le navigateur recoit vraiment.

    Sans ce test, la phrase pouvait arriver jusqu'a la trace et mourir dans la
    route -- c'est exactement ou elle mourait. Le motif reste, dans l'en-tete,
    parce qu'un journal en a besoin ; le corps de la reponse est en francais.

    LA RUSTINE PASSE PAR `monkeypatch`, et ce n'est pas un detail de style.
    `sandbox` est un module neuf a chaque test, mais `sandbox.composite` est le
    module `composite` charge UNE fois pour toute la suite : une affectation
    directe y survivait a son test. Tout ce qui appelait ensuite
    `lancer_par_le_routeur` recevait << arbitrage_du_client >>. Invisible
    jusqu'au 22/09/2026, parce que personne ne l'appelait apres ; les trois
    premiers tests a le faire -- ceux de la brique document -- echouaient en
    suite complete et passaient tout seuls.
    """
    from fastapi.testclient import TestClient

    def refuser(_etape, _entree):
        raise sandbox.composite.CompositeRefuse(
            "arbitrage_du_client",
            "La carte de votre ordinateur est occupée. Attendre ne coûte "
            "rien ; louer coûte 0,12 $.",
            ou=sandbox.composite.EXECUTION)

    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur", refuser)
    client = TestClient(sandbox.app)
    reponse = client.post(
        "/composite/lancer",
        headers={"Authorization": "Bearer " + sandbox.KEY},
        data={"briques": "chat_auto", "phrase": "bonjour"})
    assert reponse.status_code == 409, reponse.text
    assert "Attendre ne coûte rien" in reponse.json()["detail"], reponse.text
    assert reponse.headers["X-Composite-Motif"] == "arbitrage_du_client"


def test_sans_carte_du_tout_le_clip_maison_rend_partiel_et_le_DIT(apps):
    """Le bras que la CI a revele le 22/09/2026, et que rien ne jouait.

    `video_maison` est la seule des seize briques qui demande la carte
    (`vram_min_go` = 14,4 ; les quinze autres sont a `null` parce que ce sont
    des API). Sur une machine sans carte -- le runner, l'ordinateur d'un
    debutant -- elle ne rend pas `oui` : elle rend `partiel`, parce que la
    chaine tient mais qu'un pas ne partira pas d'ici. Ce n'est pas une panne,
    c'est le verdict juste, et il doit etre le meme partout.
    """
    chaine = composite.chaine_depuis_briques(["video_maison"], apps)
    verdict = composite.verifier(chaine, sonde_budget=lambda _e: None,
                                 sonde_carte=CARTE_ABSENTE)
    assert verdict["atteignable"] == composite.PARTIEL, verdict["motifs"]
    assert "carte_absente" in verdict["motifs"], verdict["motifs"]

    # Et avec la carte, la meme chaine passe. Sans ce second bras, le controle
    # ne pourrait pas echouer : il dirait << partiel >> quoi qu'il arrive.
    avec = composite.verifier(chaine, sonde_budget=lambda _e: None,
                              sonde_carte=CARTE_LIBRE)
    assert avec["atteignable"] == composite.OUI, avec["motifs"]


def test_une_carte_ABSENTE_et_une_carte_OCCUPEE_ne_disent_pas_la_meme_chose(apps):
    """Deux refus, deux nouvelles differentes pour celui qui lit.

    << Occupee >> dit d'attendre ; << absente >> dit que cet ordinateur ne fera
    jamais ce pas. Le releve de `gpu_local` portait deja la difference (`vue`)
    et le motif l'ecrasait : les deux sortaient en `carte_occupee`. Le verdict
    reste `partiel` dans les deux cas -- c'est le motif qui change, et c'est
    lui que la page lira pour choisir quoi proposer.
    """
    chaine = composite.chaine_depuis_briques(["video_maison"], apps)
    absente = composite.verifier(chaine, sonde_budget=lambda _e: None,
                                 sonde_carte=CARTE_ABSENTE)
    occupee = composite.verifier(chaine, sonde_budget=lambda _e: None,
                                 sonde_carte=CARTE_OCCUPEE)

    assert "carte_absente" in absente["motifs"] and \
        "carte_occupee" not in absente["motifs"], absente["motifs"]
    assert "carte_occupee" in occupee["motifs"] and \
        "carte_absente" not in occupee["motifs"], occupee["motifs"]
    assert absente["atteignable"] == occupee["atteignable"] == composite.PARTIEL

    # Le fait porte la meme distinction, pour qui lit les faits et non la phrase.
    fait_a = [f for f in absente["faits"] if f["quoi"] == "carte"][0]
    fait_o = [f for f in occupee["faits"] if f["quoi"] == "carte"][0]
    assert fait_a["presente"] is False and fait_o["presente"] is True
    assert fait_a["libre"] is False and fait_o["libre"] is False


def test_une_sonde_SANS_releve_n_invente_pas_une_carte_absente(apps):
    """Ne pas savoir n'est pas savoir que non.

    Une sonde qui ne rend pas de releve -- un tiers, un bouchon plus vieux --
    laisse le motif le moins affirmatif. Inventer << absente >> ferait dire au
    Studio qu'il n'y a pas de carte sur une machine qui en a peut-etre une.
    """
    chaine = composite.chaine_depuis_briques(["video_maison"], apps)
    verdict = composite.verifier(
        chaine, sonde_budget=lambda _e: None,
        sonde_carte=lambda mo: (False, "prise, et je ne dis rien de plus.", None))
    assert "carte_occupee" in verdict["motifs"], verdict["motifs"]
    assert "carte_absente" not in verdict["motifs"], verdict["motifs"]


# --- SP-FLOW-BUDGET-CUMULE : chaque pas passe seul, mais tous ensemble ? ------
# Point 15.5 (proprietaire, 23/09/2026 ; gel leve le meme jour). Sans ce
# controle, trois pas qui passent chacun la garde partaient l'un apres l'autre,
# et le troisieme etait refuse -- apres avoir paye les deux premiers.

def _mesures(couts, reste, refus=None):
    """Une sonde de mesure : le pire cas de chaque brique, le meme reste."""
    def mesure(etape):
        if etape["brique"] not in composite.BUDGET_PAR_BRIQUE:
            return None
        if refus and etape["brique"] in refus:
            return {"refus": "Refusé seul.", "cout_max_usd": None, "reste_usd": None}
        return {"refus": None, "cout_max_usd": couts[etape["brique"]], "reste_usd": reste}
    return mesure


def test_deux_pas_qui_passent_seuls_mais_pas_ensemble_sont_refuses_d_avance(apps):
    chaine = composite.chaine_depuis_briques(["chanson", "dialogue"], apps)
    verdict = composite.verifier(
        chaine, sonde_mesure=_mesures({"chanson": 3.0, "dialogue": 2.0}, reste=4.0))
    assert verdict["atteignable"] == composite.NON, verdict["pourquoi"]
    assert "budget_cumule_depasse" in verdict["motifs"], verdict["motifs"]
    assert "5,00 $" in verdict["pourquoi"] and "4,00 $" in verdict["pourquoi"]
    fait = next(f for f in verdict["faits"] if f["quoi"] == "budget_cumule")
    assert fait["reste_du_mois"] == "4,00 $"


def test_deux_pas_qui_tiennent_ENSEMBLE_passent(apps):
    """L'autre bras : le controle additionne, il ne refuse pas tout."""
    chaine = composite.chaine_depuis_briques(["chanson", "dialogue"], apps)
    verdict = composite.verifier(
        chaine, sonde_mesure=_mesures({"chanson": 3.0, "dialogue": 2.0}, reste=5.5))
    assert "budget_cumule_depasse" not in verdict["motifs"], verdict["motifs"]
    assert "budget_cumule_serre" not in verdict["motifs"], verdict["motifs"]
    fait = next(f for f in verdict["faits"] if f["quoi"] == "budget_cumule")
    assert fait["pire_cas"] == "5,00 $"


def test_un_clip_de_trop_ne_refuse_pas_il_reste_la_carte_d_ici(apps):
    """Chanson seule tient ; avec le clip loue, plus. Le clip peut encore se
    faire ici : PARTIEL, comme `loueur_ferme`, jamais NON."""
    chaine = composite.chaine_depuis_briques(["chanson", "video_rapide"], apps)
    verdict = composite.verifier(
        chaine, sonde_carte=lambda mo: (True, "libre.", {"vue": True}),
        sonde_mesure=_mesures({"chanson": 3.0, "video_rapide": 2.0}, reste=4.0))
    assert "budget_cumule_serre" in verdict["motifs"], verdict["motifs"]
    assert "budget_cumule_depasse" not in verdict["motifs"], verdict["motifs"]
    # Cette chaine est refusee pour d'autres raisons (types, licence de la
    # chanson) : on ne juge ici que ce que le cumul en dit.
    fait = next(f for f in verdict["faits"] if f["quoi"] == "budget_cumule")
    assert fait["consequence"] == "un clip ne part que sur la carte d'ici"
    assert "carte de votre ordinateur" in verdict["pourquoi"]


def test_un_seul_pas_loue_ou_un_refus_seul_ne_sont_pas_additionnes(apps):
    # Un seul pas : la garde par noeud suffit, aucun total.
    seul = composite.chaine_depuis_briques(["chanson"], apps)
    verdict = composite.verifier(seul, sonde_mesure=_mesures({"chanson": 9.0}, reste=1.0))
    assert not any(f["quoi"] == "budget_cumule" for f in verdict["faits"])
    # Un pas deja refuse seul : le verdict le dit deja, pas deux fois.
    assert composite.cumul_de_chaine(
        composite.chaine_depuis_briques(["chanson", "dialogue"], apps)["etapes"],
        _mesures({"chanson": 3.0, "dialogue": 2.0}, reste=4.0, refus={"dialogue"})) is None


def test_executer_refuse_AVANT_le_premier_pas_rien_ne_part(apps, monkeypatch):
    """Le budget a pu bouger depuis le verdict : la garde se repose au depart."""
    monkeypatch.setattr(composite, "mesure_du_noeud",
                        _mesures({"chanson": 3.0, "dialogue": 2.0}, reste=4.0))
    partis = []
    trace = composite.executer(
        composite.chaine_depuis_briques(["chanson", "dialogue"], apps),
        lambda e, _x: partis.append(e["brique"]) or "son")
    assert trace["resultat"] == "refus", trace
    assert trace["motif"] == "budget_cumule_depasse"
    assert "ne pas payer le début" in trace["phrase"]
    assert partis == []


def test_le_cumul_additionne_les_VRAIS_pires_cas_des_modules(apps, monkeypatch, tmp_path):
    """Avec les vraies gardes de chanson et dialogue et le vrai compteur : le
    mois est rempli juste assez pour que chacun passe seul, pas les deux."""
    import json as _json

    import budget_modal

    monkeypatch.setattr(budget_modal, "FICHIER", tmp_path / "modal-budget.json")
    chaine = composite.chaine_depuis_briques(["chanson", "dialogue"], apps)
    couts = {e["brique"]: composite.mesure_du_noeud(e)["cout_max_usd"]
             for e in chaine["etapes"]}
    assert min(couts.values()) > 0.02, couts
    plafond = budget_modal.plafond_de("chanson")
    depense = plafond - max(couts.values()) - 0.01
    (tmp_path / "modal-budget.json").write_text(_json.dumps(
        {"mois": budget_modal._mois_courant(), "secondes": 0, "usd": depense}),
        encoding="utf-8")
    for e in chaine["etapes"]:
        assert composite.mesure_du_noeud(e)["refus"] is None, e["brique"]
    verdict = composite.verifier(chaine)
    assert "budget_cumule_depasse" in verdict["motifs"], verdict["pourquoi"]
    assert verdict["atteignable"] == composite.NON


def test_la_consigne_orale_dit_de_garder_accents_et_ponctuation(sandbox):
    """24/09 : « pas de symbole » tout court faisait tomber apostrophes et
    ponctuation (« L ecume danse ... l horizon ») ; la voix lisait mal. Mesure :
    6 reponses fautives sur 24 avant, 0 sur 24 avec la phrase qui dit quoi garder."""
    c = sandbox.composite
    orale = c._consigne_orale("voix_fr")
    assert "accents, apostrophes, virgules et points" in orale
    assert "pas de symbole," not in orale and "symbole de mise en forme" in orale
    assert "en anglais" in c._consigne_orale("voix_en")
    assert c._consigne_orale(None) == "" and c._consigne_orale("image_fabrication") == ""
