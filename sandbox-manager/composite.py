"""Composer plusieurs briques en une chaine, et dire AVANT de lancer si elle tient.

Un *composite* est une chaine de briques designees par leur FONCTION et non par
un nom de modele -- << la voix >>, pas << Piper 1.8.0 >>. C'est le cap que le
depot s'est donne (docs/PLAN-PLATEFORME.md:43-45) et la case est restee vide
jusqu'ici.

QUATRE PAS, ET UN SEUL APPELLE UN MODELE :

  compiler(phrase)          la phrase du client -> un graphe de CAPACITES.
                            Le seul pas qui appelle un modele, par la passerelle
                            qui existe deja : aucun fournisseur neuf, aucune cle
                            neuve, aucun cout.
  lier(graphe, registre)    capacite -> brique, par correspondance EXACTE.
                            Deterministe. Deux briques qui se valent vraiment
                            font une ABSTENTION, pas un choix pour avoir l'air
                            decide.
  verifier(chaine)          types, cout, carte, licence -- AVANT toute depense.
  executer(chaine)          et la trace dit OU ca a casse, pas si.

CE QUI N'EST PAS ICI, ET POURQUOI :

  - aucune estimation. `cout_max_usd` ne porte que des nombres deja mesures ;
    `null` veut dire << pas de nombre par travail >> et rend le verdict
    << inconnu >>, jamais un zero optimiste ;
  - aucun plafond invente. La seule barriere reelle du depot est
    `budget_modal.verifier()`, qui refuse au PIRE CAS avant de lancer. Elle est
    taillee pour UN travail -- un usage, un gpu, une duree -- donc une chaine
    l'appelle PAR NOEUD, juste avant chaque lancement, et ne lui fabrique pas un
    total. `ALLOW_PAID_GPU` et `MAX_DAILY_COST` sont declares dans `.env.example`
    et greppes par la CI, mais lus par AUCUN code Python : ce sont des valeurs
    par defaut documentees, pas des barrieres, et rien ici ne s'appuie dessus ;
  - aucune sortie reseau dans un bac a sable : `docker-compose.yml` pose
    `internal: true` sur `sandbox-internal`, donc tout telechargement se fait
    dans une phase de preparation HORS bac a sable.

LA LICENCE D'UNE CHAINE, ET LA DISTINCTION QUI A FAILLI ME COUTER LE LOT :
deux licences sans rapport se ressemblent de loin. L'USAGE non commercial se
propage le long d'une chaine -- une chaine qui contient `chanson` (CC BY-NC 4.0)
est non commerciale. La DISTRIBUTION est une autre question : `voix_fr` embarque
Piper en GPL-3.0-or-later dans un depot MIT, mais sa fiche dit << usage
commercial permis >>. Les confondre produit une garde fausse, qui refuserait la
chaine temoin de ce lot-ci. Ce module ne controle QUE l'usage ; la question
GPL-du-composite n'est tranchee par aucun fichier du depot et attend son
proprietaire.

Aucun appel reseau a l'import.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

import format_fr

# --- Les types qui traversent une frontiere entre deux briques ---------------
# Des VALEURS NUES, jamais un objet de service. La regle vient du depot voisin,
# ou 5 828 declarations de type tiennent sur 15 types de base et zero objet
# solveur : un type que rien ne peut contredire est un controle qui ne peut pas
# sonner.
TYPES = ("texte", "audio", "image", "video", "fichier")

# --- Ce que le verdict peut valoir ------------------------------------------
OUI = "oui"            # la chaine tient, et le cout est connu
PARTIEL = "partiel"    # elle tient, mais une contrainte du client tombe
INCONNU = "inconnu"    # il manque un nombre ou une licence pour trancher
NON = "non"            # elle ne tient pas, et on dit pourquoi

# --- Ou ca a casse. Un booleen n'apprend rien. -------------------------------
COMPILATION = "compilation"
LIAISON = "liaison"
CONTROLE = "controle"
EXECUTION = "execution"
SORTIE = "sortie"

# --- Le registre -------------------------------------------------------------
# Le conteneur du sandbox-manager ne copie que `*.py` (son Dockerfile), donc le
# registre y arrive par un montage en LECTURE SEULE declare dans le compose. Un
# module Python engendre depuis le registre serait une SECONDE VERITE : le depot
# refuse cela partout ailleurs, et c'est le defaut repare le 20/09 (la meme
# verite recopiee a six endroits, quatre avaient diverge).
REGISTRE = Path(os.getenv(
    "REGISTRE_APPS",
    str(Path(__file__).resolve().parents[1] / "registry" / "apps.json")))


class CompositeRefuse(Exception):
    """Un refus qui porte son motif NOMME et sa phrase de remede.

    Jamais un booleen : un refus qui ne dit pas ce qui reste ouvert se lit
    comme une panne.
    """

    def __init__(self, motif: str, phrase: str, ou: str = CONTROLE):
        super().__init__(phrase)
        self.motif = motif
        self.phrase = phrase
        self.ou = ou


def charger_registre(chemin: Path | None = None) -> list[dict]:
    """Les briques, telles que le registre les declare. Aucun defaut invente."""
    chemin = Path(chemin) if chemin else REGISTRE
    if not chemin.is_file():
        raise CompositeRefuse(
            "registre_absent",
            "Le registre des applications est introuvable (%s). Le service ne "
            "peut composer que ce qu'il sait decrire." % chemin,
            ou=LIAISON)
    return json.loads(chemin.read_text(encoding="utf-8"))["applications"]


def par_capacite(apps: list[dict]) -> dict[str, list[dict]]:
    """capacite -> les briques qui la portent. Plusieurs = une egalite reelle."""
    table: dict[str, list[dict]] = {}
    for app in apps:
        table.setdefault(app["capacite"], []).append(app)
    return table


# ---------------------------------------------------------------------------
# 1. compiler : la phrase du client devient un graphe de CAPACITES
# ---------------------------------------------------------------------------

CONSIGNE = """Tu traduis la demande d'une personne en une suite de FONCTIONS.

Les fonctions disponibles, et rien d'autre :
%s

Reponds UNIQUEMENT par un objet JSON de cette forme, sans texte autour :
{"noeuds": ["fonction_1", "fonction_2"]}

Regles :
- l'ordre compte : la sortie de chaque fonction alimente la suivante ;
- n'invente aucune fonction qui ne soit pas dans la liste ;
- si la demande ne correspond a aucune suite de ces fonctions, reponds
  {"noeuds": []} plutot que de choisir au hasard.

La demande : %s
"""


def compiler(phrase: str, appeler_modele, apps: list[dict] | None = None) -> dict:
    """La phrase -> un graphe de noeuds `{capacite, entrees, sorties}`.

    `appeler_modele(consigne) -> texte` est injecte : en production c'est la
    passerelle `free-ai-auto` qui existe deja, dans les tests c'est une
    fonction qui rend une reponse fixe. Aucun fournisseur neuf, aucune cle
    neuve, aucun cout.

    AUCUN MODELE LIE ICI. Le graphe ne nomme que des capacites : c'est la
    definition meme du composite, et c'est ce qui permet a la decouverte
    d'arriver plus tard comme un fournisseur de candidats de plus.
    """
    apps = apps if apps is not None else charger_registre()
    connues = sorted({a["capacite"] for a in apps})
    if not (phrase or "").strip():
        raise CompositeRefuse(
            "phrase_vide",
            "Dites en une phrase ce que vous voulez obtenir.", ou=COMPILATION)

    catalogue = "\n".join(
        "- %s : %s" % (a["capacite"], a["fonction"]) for a in apps)
    brut = appeler_modele(CONSIGNE % (catalogue, phrase.strip()))

    noeuds = _lire_json(brut)
    if noeuds is None:
        raise CompositeRefuse(
            "reponse_illisible",
            "Le lecteur de la demande n'a pas rendu une suite de fonctions "
            "lisible. Reformulez en une phrase, ou dites la fonction voulue.",
            ou=COMPILATION)
    if not noeuds:
        raise CompositeRefuse(
            "aucune_suite",
            "Cette demande ne correspond a aucune suite des fonctions que ce "
            "Studio sait faire. Les fonctions disponibles : %s."
            % ", ".join(connues), ou=COMPILATION)

    inventees = [n for n in noeuds if n not in connues]
    if inventees:
        raise CompositeRefuse(
            "capacite_inventee",
            "Fonction(s) inconnue(s) de ce Studio : %s. Rien n'est lance."
            % ", ".join(inventees), ou=COMPILATION)

    return {"phrase": phrase.strip(), "noeuds": [{"capacite": n} for n in noeuds]}


def _lire_json(brut: str):
    """La liste de capacites, ou None si la reponse n'est pas lisible.

    Un modele encadre volontiers son JSON de ```json ... ``` ou d'une phrase de
    politesse. On accepte cela ; on n'accepte PAS d'inventer ce qu'il a voulu
    dire.
    """
    if not isinstance(brut, str):
        return None
    m = re.search(r"\{.*\}", brut, re.S)
    if not m:
        return None
    try:
        objet = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    noeuds = objet.get("noeuds")
    if not isinstance(noeuds, list) or any(not isinstance(n, str) for n in noeuds):
        return None
    return [n.strip() for n in noeuds if n.strip()]


# ---------------------------------------------------------------------------
# 2. lier : capacite -> brique, et l'abstention quand deux briques se valent
# ---------------------------------------------------------------------------

def lier(graphe: dict, apps: list[dict] | None = None) -> dict:
    """Le graphe de capacites devient une chaine de briques nommees.

    Deterministe : correspondance EXACTE de `capacite`, aucun classement, aucun
    modele. Quand plusieurs briques portent la meme capacite et que rien dans le
    code ne les departage, on S'ABSTIENT et on le dit -- choisir pour avoir
    l'air decide est la faute que le depot voisin nomme en toutes lettres.

    Aujourd'hui une seule capacite est dans ce cas : `conversation_secours`,
    portee par les deux secours du routeur. Un composite ne doit jamais viser
    le secours directement -- le routeur le choisit lui-meme quand le premier
    tombe. L'abstention est donc la bonne reponse, et ce n'est pas un trou.
    """
    apps = apps if apps is not None else charger_registre()
    table = par_capacite(apps)

    chaine = []
    for noeud in graphe["noeuds"]:
        capacite = noeud["capacite"]
        candidates = table.get(capacite, [])
        if not candidates:
            raise CompositeRefuse(
                "capacite_absente",
                "Aucune application de ce Studio ne fait << %s >>." % capacite,
                ou=LIAISON)
        if len(candidates) > 1:
            raise CompositeRefuse(
                "plusieurs_briques_se_valent",
                "Deux applications font << %s >> (%s) et rien ne les departage. "
                "Je prefere m'abstenir plutot que d'en choisir une au hasard : "
                "dites laquelle."
                % (capacite, ", ".join(sorted(c["id"] for c in candidates))),
                ou=LIAISON)
        chaine.append(_etape(candidates[0]))
    return {"phrase": graphe.get("phrase", ""), "etapes": chaine}


def _etape(brique: dict) -> dict:
    """La forme d'un pas de chaine, ecrite a UN seul endroit.

    `lier` la fabrique depuis une capacite, `chaine_depuis_briques` depuis un
    identifiant : deux entrees, une seule forme. Deux copies de cette forme
    divergeraient le jour ou un champ s'ajoute, et le controle deterministe
    lirait alors un champ absent sur la moitie des chaines.
    """
    return {
        "capacite": brique["capacite"],
        "brique": brique["id"],
        "fonction": brique["fonction"],
        "entrees": list(brique["entrees"]),
        "sorties": list(brique["sorties"]),
        "modes": list(brique["modes"]),
        "licence": brique["licence"],
        "cout": brique["cout"],
        "cout_max_usd": brique["cout_max_usd"],
        "vram_min_go": brique["vram_min_go"],
    }


def chaine_depuis_briques(ids, apps: list[dict] | None = None,
                          phrase: str = "") -> dict:
    """La chaine que la page a DEJA montree, rebatie sans appeler le modele.

    << Lancer >> recompilait la phrase : un second appel au modele, qui n'est
    pas deterministe. La chaine lancee pouvait donc differer de celle dont le
    verdict venait d'etre lu -- autre profil de cles, autres briques, ou meme
    un JSON illisible au moment de lancer une demande deja validee. La page
    tient les briques qu'elle a montrees : on les rebatit, c'est gratuit et
    c'est le meme resultat a chaque fois.
    """
    apps = apps if apps is not None else charger_registre()
    par_id = {a["id"]: a for a in apps}
    etapes = []
    for ident in ids:
        brique = par_id.get(ident)
        if brique is None:
            raise CompositeRefuse(
                "brique_inconnue",
                "<< %s >> n'est pas une application de ce Studio." % ident,
                ou=LIAISON)
        etapes.append(_etape(brique))
    return {"phrase": phrase, "etapes": etapes}


# ---------------------------------------------------------------------------
# 3. verifier : types, licence, cout, carte -- AVANT toute depense
# ---------------------------------------------------------------------------

# L'USAGE non commercial, et lui seul. Les marqueurs sont ecrits pour ne PAS
# mordre sur << CC BY 4.0 ... usage commercial permis >> (voix_fr) ni sur
# << Apache 2.0 -- ... usage commercial compris >> (dialogue) : c'est
# exactement la confusion qui aurait fait echouer ce lot apres coup.
_NON_COMMERCIAL = (
    re.compile(r"\bBY-NC\b", re.I),
    re.compile(r"\bnon[\s-]commercial", re.I),
)
# Une licence qu'on ne peut pas nommer n'est pas une licence permissive : le
# modele servi par le premier secours change d'une requete a l'autre.
_INDETERMINEE = re.compile(r"\bvariable\b", re.I)

# << GRATUIT >> N'EST PAS << SANS CLE >>, et le registre distingue les deux dans
# sa prose depuis toujours : `dictee_locale` et `voix_fr` portent
# << gratuit, sans cle >>, `chat_auto` porte << gratuit >> tout court, et
# `dictee_groq` porte << gratuit avec une cle Groq >>. Une chaine qui annonce
# << gratuite >> sans dire de quelles cles elle depend est vraie au comptoir et
# fausse a l'usage : sur une installation neuve elle s'arrete au premier noeud
# qui en reclame une. Mesure du 22/09 : le verdict disait << gratuite : 0,00 $ >>
# pour une chaine dont DEUX noeuds sur trois exigeaient une cle.
_SANS_CLE = re.compile(r"sans\s+clé|sans\s+compte|sans\s+carte", re.I)


def exige_une_cle(cout: str) -> bool:
    """La brique a-t-elle besoin d'un compte deja branche pour servir ?

    Lue dans la prose de `cout`, qui est la seule chose que le registre dise a
    ce sujet -- et elle le dit exactement. Un test epingle l'ensemble trouve :
    si la prose change, il sonne.
    """
    return not _SANS_CLE.search(cout or "")


def est_non_commercial(licence: str) -> bool:
    """La brique interdit-elle l'usage commercial ? Sur l'USAGE, pas la diffusion."""
    return any(m.search(licence or "") for m in _NON_COMMERCIAL)


def licence_indeterminee(licence: str) -> bool:
    """La licence est-elle impossible a nommer aujourd'hui ?"""
    return bool(_INDETERMINEE.search(licence or ""))


def verifier(chaine: dict, *, besoin_mo: int = 0, sonde_carte=None,
             sonde_budget=None) -> dict:
    """Le verdict, rendu dans la MEME forme que `ou_calculer.decider()` :
    un etat, plus un `pourquoi` en francais affichable tel quel.

    << Non >> est un resultat, pas une panne. Pour quelqu'un dont la regle est
    `MAX_DAILY_COST=0`, s'entendre dire << non, pas gratuitement, et voila ce
    qui s'en approche >> vaut mieux qu'une chaine qui casse au sixieme noeud.
    """
    etapes = chaine["etapes"]
    motifs: list[str] = []
    pourquoi: list[str] = []
    # Les FAITS, a cote des phrases : c'est eux qui sont vrais, et c'est sur eux
    # que portent les tests. La phrase ecrite en face reste le repli.
    faits: list[dict] = []
    etat = OUI

    if not etapes:
        return _verdict(NON, ["chaine_vide"], ["La chaîne ne contient aucune étape."],
                        chaine, 0.0, [{"quoi": "chaine_vide"}])

    # --- les types : la sortie du noeud n couvre-t-elle l'entree du noeud n+1 ?
    for amont, aval in zip(etapes, etapes[1:]):
        if not set(amont["sorties"]) & set(aval["entrees"]):
            motifs.append("types_incompatibles")
            pourquoi.append(
                "%s rend %s, et %s attend %s : les deux ne s'enchaînent pas."
                % (amont["fonction"], " ou ".join(amont["sorties"]),
                   aval["fonction"], " ou ".join(aval["entrees"])))
            faits.append({"quoi": "types_incompatibles", "amont": amont["fonction"],
                          "rend": amont["sorties"], "aval": aval["fonction"],
                          "attend": aval["entrees"]})
            etat = NON

    # --- la route : cette brique peut-elle seulement PARTIR d'une chaine ? ---
    # `ROUTES` et `BUDGET_PAR_BRIQUE` vivent au paragraphe 5 : on les LIT, on
    # ne les recopie pas ici -- deux tables divergeraient le jour ou une route
    # s'ajoute, et le verdict promettrait de nouveau ce qui ne part pas.
    #
    # Releve du 22/09, relecture adverse : dix briques sur seize n'avaient
    # aucune route, et le verdict les promettait. Le client lisait << Oui,
    # cette chaine tient >>, cliquait, et la chaine cassait au controle APRES
    # avoir vraiment lance les noeuds precedents. La page promet de dire
    # << avant de lancer >> : elle le disait pour deux briques sur seize.
    sans_route = [e for e in etapes if e["brique"] not in ROUTES]
    if sans_route:
        motifs.append("brique_sans_route")
        pourquoi.append(
            ("%s n'a pas encore de route dans une chaîne : le Studio sait la "
             "lancer depuis sa propre page, pas depuis un enchaînement."
             if len(sans_route) == 1 else
             "%s n'ont pas encore de route dans une chaîne : le Studio sait "
             "les lancer depuis leur propre page, pas depuis un enchaînement.")
            % ", ".join(e["fonction"] for e in sans_route))
        faits.append({"quoi": "brique_sans_route",
                      "applications": [e["fonction"] for e in sans_route],
                      "consequence": "cette chaîne ne peut pas être lancée : "
                                     "ces applications ne se branchent pas "
                                     "encore dans un enchaînement"})
        etat = NON

    # --- le budget : MESURE, au lieu d'etre refuse d'avance -------------------
    # Ordre du proprietaire, 22/09/2026 : << les depenses sont de fausses
    # depenses tant que l'on reste dans le budget free >>. Le bras precedent
    # refusait toute brique pouvant partir chez un loueur SANS RIEN MESURER --
    # il s'interdisait un credit qu'on a. Il interroge maintenant la garde du
    # module, la meme que `executer` posera juste avant le lancement, et ne
    # refuse que sur un depassement dit par elle, avec sa phrase.
    #
    # Deux cas, et c'est le CODE qui les separe, pas une regle qu'on s'invente :
    #   - `/chanson/creer` (app.py:2541) et `/dialogue/creer` (app.py:2923)
    #     appellent `budget_verifier` sans jamais consulter
    #     `ou_calculer.decider()` : le loueur est leur seule route ;
    #   - `/video/creer` consulte la decision AVANT (app.py:2309) et ne verifie
    #     le budget que si elle dit << modal >> (app.py:2333) : un clip peut
    #     encore se fabriquer sur la carte d'ici, credit de location epuise.
    # Donc : chanson et dialogue ⇒ NON, clip ⇒ PARTIEL, et la phrase dit lequel.
    sonde = sonde_budget or budget_du_noeud
    ferme, prive_du_loueur = [], []
    for e in etapes:
        if not BUDGET_PAR_BRIQUE.get(e["brique"]):
            continue
        try:
            refus = sonde(e)
        except Exception as exc:  # noqa: BLE001
            # Pas de mesure n'est pas une autorisation -- ni un refus. C'est
            # INCONNU, et on le dit : `MAX_DAILY_COST=0` merite mieux qu'un
            # silence qui laisse partir.
            if etat == OUI:
                etat = INCONNU
            motifs.append("budget_non_mesure")
            pourquoi.append(
                "Le budget de %s n'a pas pu être relevé d'ici (%s) : la "
                "chaîne ne promet pas ce qu'elle n'a pas mesuré."
                % (e["fonction"], exc.__class__.__name__))
            faits.append({"quoi": "budget_non_mesure", "application": e["fonction"]})
            continue
        if not refus:
            continue
        (ferme if e["brique"] in LOUEUR_SEUL else prive_du_loueur).append((e, refus))

    if ferme:
        motifs.append("budget_depasse")
        pourquoi.append(
            "%s ne peut partir que chez un loueur, et le crédit offert n'y "
            "suffit plus aujourd'hui. %s"
            % (", ".join(e["fonction"] for e, _ in ferme), ferme[0][1]))
        faits.append({"quoi": "budget_depasse",
                      "applications": [e["fonction"] for e, _ in ferme],
                      "dit_par_le_module": ferme[0][1],
                      "consequence": "cette chaîne ne peut pas être lancée "
                                     "aujourd'hui sans dépenser"})
        etat = NON

    if prive_du_loueur:
        if etat == OUI:
            etat = PARTIEL
        motifs.append("loueur_ferme")
        pourquoi.append(
            "Le crédit offert chez le loueur ne suffit plus pour %s : ce pas "
            "ne partira que sur la carte de votre ordinateur, si elle est "
            "libre. %s"
            % (", ".join(e["fonction"] for e, _ in prive_du_loueur),
               prive_du_loueur[0][1]))
        faits.append({"quoi": "loueur_ferme",
                      "applications": [e["fonction"] for e, _ in prive_du_loueur],
                      "dit_par_le_module": prive_du_loueur[0][1],
                      "consequence": "ce pas ne part que sur la carte d'ici"})

    # --- la licence d'USAGE : non commercial est contagieux -------------------
    nc = [e for e in etapes if est_non_commercial(e["licence"])]
    if nc:
        motifs.append("chaine_non_commerciale")
        pourquoi.append(
            "Cette chaîne ne peut pas servir un usage commercial : %s "
            "l'interdit (%s), et la contrainte se propage à tout ce qui en sort."
            % (", ".join(e["fonction"] for e in nc), nc[0]["licence"]))
        faits.append({"quoi": "usage_non_commercial",
                      "applications": [e["fonction"] for e in nc],
                      "licence": nc[0]["licence"],
                      "consequence": "cette chaîne est refusée : elle ne "
                                     "peut pas servir un usage commercial, et la "
                                     "contrainte se propage à tout ce qui en sort"})
        etat = NON

    floues = [e for e in etapes if licence_indeterminee(e["licence"])]
    if floues and etat != NON:
        motifs.append("licence_indeterminee")
        pourquoi.append(
            "La licence de %s ne peut pas être nommée aujourd'hui (%s) : "
            "on ne peut donc pas dire celle de la chaîne entière."
            % (", ".join(e["fonction"] for e in floues), floues[0]["licence"]))
        faits.append({"quoi": "licence_indeterminee",
                      "applications": [e["fonction"] for e in floues],
                      "licence": floues[0]["licence"]})
        etat = INCONNU

    # --- le cout : des nombres mesures, ou rien -------------------------------
    sans_nombre = [e for e in etapes if e["cout_max_usd"] is None]
    total = sum(e["cout_max_usd"] or 0 for e in etapes)
    if sans_nombre:
        if etat == OUI:
            etat = INCONNU
        motifs.append("cout_sans_nombre")
        pourquoi.append(
            "Le coût de %s n'a pas de nombre par travail mesuré : la "
            "chaîne coûte au moins %s, et on ne peut pas dire son maximum."
            % (", ".join(e["fonction"] for e in sans_nombre),
               format_fr.en_dollars(total)))
        # << montant_minimum >> se lit comme un prix, et le 22/09 le modele l'a
        # ecrit << ne coute que 0,00 $ >> sur deux tirages sur trois. Un
        # plancher n'est pas un prix : le fait le dit en toutes lettres.
        faits.append({"quoi": "cout_sans_nombre",
                      "applications": [e["fonction"] for e in sans_nombre],
                      "plancher": format_fr.en_dollars(total),
                      "maximum": "inconnu, faute de mesure par travail",
                      "consequence": "le plancher n'est pas un prix : on ne "
                                     "peut pas dire ce que cette cha\u00eene "
                                     "co\u00fbtera au pire"})
    elif total > 0:
        pourquoi.append(
            "Cette chaîne peut coûter jusqu'à %s au pire."
            % format_fr.en_dollars(total))
        faits.append({"quoi": "cout_maximum", "montant": format_fr.en_dollars(total)})
    else:
        pourquoi.append(
            "Cette chaîne est gratuite : %s." % format_fr.en_dollars(0))
        faits.append({"quoi": "gratuite", "montant": format_fr.en_dollars(0)})

    # Gratuit, oui -- mais avec quoi de deja branche ? La phrase le dit, parce
    # qu'une installation neuve s'arreterait au premier noeud qui reclame une
    # cle, et que << gratuit >> l'aurait laisse croire le contraire.
    avec_cle = [e for e in etapes if exige_une_cle(e["cout"])]
    if avec_cle:
        motifs.append("cle_requise")
        # Les DEUX phrases sont ecrites en entier. Un gabarit a trou ne peut pas
        # etre juste ici : le verbe, l'article du complement et le pronom de
        # reprise s'accordent tous avec le sujet, et remplacer le seul sujet les
        # laisse au singulier. Defaut du 22/09, lu dans la sortie du verdict :
        # << Plusieurs etapes A BESOIN d'un service deja branche >>.
        pourquoi.append(
            ("Une étape a besoin d'un service déjà branché dans "
             "la page « vos identifiants » (/cles) : %s. Sans lui, la "
             "chaîne s'arrêtera là, et le dira."
             if len(avec_cle) == 1 else
             "Plusieurs étapes ont besoin de services déjà "
             "branchés dans la page « vos identifiants » (/cles) : %s. "
             "Sans eux, la chaîne s'arrêtera au premier qui manque, et "
             "le dira.")
            % ", ".join(e["fonction"] for e in avec_cle))
        faits.append({"quoi": "cle_requise",
                      "applications": [e["fonction"] for e in avec_cle],
                      "ou_la_configurer": "la page « vos identifiants » du "
                                          "Studio, à l'adresse /cles",
                      "si_elle_manque": "la chaîne s'arrête à cette "
                                        "étape et le dit"})

    # --- la carte : seulement si un noeud la demande --------------------------
    besoin = max([e["vram_min_go"] or 0 for e in etapes] or [0])
    if besoin or besoin_mo:
        besoin_mo = int(besoin_mo or besoin * 1024)
        sonde = sonde_carte or _sonde_defaut()
        if sonde is None:
            if etat == OUI:
                etat = INCONNU
            motifs.append("carte_non_sondee")
            pourquoi.append(
                "Un pas de cette chaîne demande la carte, et elle n'a pas "
                "pu être sondée d'ici.")
            faits.append({"quoi": "carte_non_sondee"})
        else:
            libre, phrase, releve = sonde(besoin_mo)
            # << Occupee >> et << absente >> ne sont pas la meme nouvelle pour
            # le client : l'une lui dit d'attendre, l'autre lui dit que cet
            # ordinateur ne fera jamais ce pas. Le releve le sait (`vue`), le
            # motif l'ignorait. Sans releve on ne sait pas : on garde alors le
            # motif le moins affirmatif, jamais une absence inventee.
            vue = releve.get("vue", True) if isinstance(releve, dict) else True
            pourquoi.append(phrase)
            faits.append({"quoi": "carte", "libre": bool(libre),
                          "presente": bool(vue), "releve": phrase})
            if not libre:
                if etat == OUI:
                    etat = PARTIEL
                motifs.append("carte_occupee" if vue else "carte_absente")

    return _verdict(etat, motifs, pourquoi, chaine, total, faits)


# L'ETAT s'ecrit d'avance et ne passe JAMAIS par le modele. C'est le verrou qui
# compte : le 22/09, sur une chaine refusee, le modele a rendu << Pour utiliser
# l'application Chanson a des fins non commerciales, le cout maximum s'eleve a
# 0,52 $ >>. Un refus devenu mode d'emploi, sans le mot << non >>.
ENTETE = {
    OUI: "Oui, cette chaîne tient.",
    PARTIEL: "En partie seulement.",
    INCONNU: "On ne peut pas encore le dire avec certitude.",
    NON: "Non : cette chaîne ne peut pas être lancée telle quelle.",
}

# Second verrou : une explication qui accompagne un << non >> doit dire le refus.
_REFUS_DIT = re.compile(
    r"ne peut pas|ne peuvent pas|impossible|interdit|interdis|refus|"
    r"n'est pas possible|pas autorise", re.I)

# La jumelle de la precedente, pour l'etat << inconnu >>. Meme cause mesuree le
# meme jour : un manque rendu comme une certitude. Ici c'etait un plancher
# ecrit comme un prix (<< ne coute que 0,00 $ >>, deux tirages sur trois).
_DOUTE_DIT = re.compile(
    r"ne peut pas|ne peuvent pas|impossible|inconnu|incertain|"
    r"pas mesur|sans mesure|non mesur|aucune mesure|pas de nombre|"
    r"au moins|au minimum|plancher|on ignore|ne sait pas|"
    r"n'est pas connu|difficile \u00e0 dire", re.I)

# Les cles des faits qui portent une somme. Elles sont declarees ICI, a un seul
# endroit, parce que le 22/09 un renommage (`montant_minimum` -> `plancher`) a
# fait taire la garde sans rien casser : l'ensemble des sommes attendues est
# devenu vide, et un ensemble vide ne rougit pas.
CLES_DE_SOMME = ("montant", "plancher")

# Et la cle qui porte des NOMS d'applications, declaree pour la meme raison.
CLE_DES_NOMS = "applications"

CONSIGNE_PHRASE = """Tu ecris pour quelqu'un qui debute et qui ne programme pas.
Voici les faits etablis sur une chaine d'applications, en JSON :

%s

Ecris-les en francais correct, trois phrases au maximum, sans liste, sans titre,
sans guillemets autour de ta reponse. Accorde les verbes et les articles.

N'invente aucun chiffre et n'en retire aucun : chaque montant present dans les
faits doit se retrouver ecrit exactement pareil, et aucune autre somme d'argent
ne doit apparaitre. Ne promets rien que les faits ne disent pas.

N'emploie pas les mots << brique >>, << noeud >>, << graphe >> ni << composite >> :
la personne qui te lit ne programme pas et ne les connait pas. Dis
<< application >> et << etape >>. Quand un fait porte un remede -- ou aller, ce
qui se passe sans lui -- dis-le : c'est la partie utile.

Le verdict est deja annonce juste avant ta phrase ; tu n'as pas a l'annoncer, et
surtout pas a dire le contraire. Si les faits portent une interdiction, explique
CE QUI EST REFUSE et pourquoi -- n'explique jamais comment s'en servir quand
meme."""

# Une somme d'argent, sous la forme francaise que `format_fr` produit.
# Tout nombre ecrit en chiffres, quel que soit son format : << 0,00 >>,
# << 5,1979 >>, << 1 234,56 >>, << 12.50 >>, << 10 >>. Mesure du 22/09 : un
# motif qui n'acceptait que deux decimales laissait passer cinq inventions sur
# six, dont le format meme du compteur Modal de ce depot.
_UN_NOMBRE = re.compile(r"\d+(?:[.,\u00a0 ]\d+)*")


def _nombres(texte: str) -> set:
    """Les nombres d'un texte, l'espace des milliers retiree pour comparer."""
    return {m.group(0).replace("\u00a0", "").replace(" ", "")
            for m in _UN_NOMBRE.finditer(texte or "")}


def rediger(verdict: dict, appeler_modele=None) -> str:
    """La phrase montree au client. Le modele l'ecrit ; les nombres ne bougent pas.

    Le calcul etablit les faits, le modele les met en francais. C'est le partage
    demande par le proprietaire le 22/09/2026, et il repose sur une mesure : le
    defaut << Plusieurs etapes A BESOIN >> venait d'un gabarit a trou en Python,
    jamais d'un modele de langue.

    Six refus, et chacun rend la phrase ECRITE au lieu d'une phrase douteuse.
    Chacun a ete pose sur un defaut MESURE, jamais sur une crainte :

      - le modele ne repond pas, repond vide, ou repond trop long ;
      - le montant calcule ne se retrouve pas tel quel dans sa reponse ;
      - le nom d'une application en ressort deforme (<< Groq si posible >>,
        deux tirages sur sept le 22/09) ;
      - un nombre apparait que les faits ne portent pas ;
      - un << non >> est explique sans dire le refus ;
      - un << je ne sais pas >> est ecrit comme une certitude.

    Le dernier est le verrou qui compte : un montant invente est exactement ce
    que ce depot refuse partout ailleurs. Et le repli n'est pas un pis-aller --
    c'est la seule reponse possible quand aucun service de chat ne repond, parce
    qu'une phrase qui dit << aucun service de chat ne repond >> ne peut pas etre
    ecrite par un service de chat.
    """
    ecrite = verdict.get("pourquoi") or ""
    faits = verdict.get("faits") or []
    if not faits:
        return ecrite

    attendues = {f[cle] for f in faits for cle in CLES_DE_SOMME
                 if f.get(cle)}
    nommees = {n for f in faits for n in f.get(CLE_DES_NOMS) or ()}
    try:
        appeler = appeler_modele or appeler_le_modele
        rendu = (appeler(CONSIGNE_PHRASE
                         % json.dumps(faits, ensure_ascii=False, indent=1)) or "").strip()
    except Exception:  # noqa: BLE001 -- une phrase ratee ne casse jamais un verdict
        return ecrite

    if not rendu or len(rendu) > 700:
        return ecrite
    if any(somme not in rendu for somme in attendues):
        return ecrite
    # Le NOM d'une application se montre tel qu'il est ecrit sur la page.
    # Mesure du 22/09 : << Dictee « Groq si posible » >>, deux tirages sur sept
    # -- un nom que le client ne retrouvera nulle part. Ni la garde des sommes
    # ni celle des nombres ne peuvent l'attraper : c'est un mot, pas un chiffre.
    if any(nom not in rendu for nom in nommees):
        return ecrite
    # Un nombre que les faits ne portent pas est un nombre invente.
    if _nombres(rendu) - _nombres(json.dumps(faits, ensure_ascii=False)):
        return ecrite
    # Un << non >> explique comme un mode d'emploi n'est pas un << non >>.
    if verdict.get("atteignable") == NON and not _REFUS_DIT.search(rendu):
        return ecrite
    # Et un << je ne sais pas >> ecrit comme un prix n'est pas un << je ne sais
    # pas >>. Rien pour << partiel >> : mesure trois fois, juste trois fois.
    if verdict.get("atteignable") == INCONNU and not _DOUTE_DIT.search(rendu):
        return ecrite
    # L'etat, lui, n'a jamais quitte le calcul.
    return (ENTETE.get(verdict.get("atteignable"), "") + " " + rendu).strip()


def _sonde_defaut():
    """`gpu_local.utilisable` s'il est la. Hors conteneur il peut manquer :
    on rend alors `None`, ce qui donne << inconnu >> -- pas un faux << oui >>."""
    try:
        import gpu_local
    except ImportError:
        return None
    return gpu_local.utilisable


def _verdict(etat, motifs, pourquoi, chaine, total, faits):
    return {
        "atteignable": etat,
        "motifs": list(motifs),
        # Ce qui est VRAI, et ce sur quoi portent les tests. La phrase se redige
        # a partir d'eux ; eux ne se redigent pas.
        "faits": list(faits),
        # Une phrase faite pour etre montree TELLE QUELLE : un << non >> sans
        # chiffre envoie chercher une panne qui n'existe pas.
        "pourquoi": " ".join([ENTETE.get(etat, "")] + pourquoi).strip(),
        "cout_max_usd": total,
        "etapes": [
            {"brique": e["brique"], "fonction": e["fonction"],
             "entrees": e["entrees"], "sorties": e["sorties"],
             "cout_max_usd": e["cout_max_usd"]}
            for e in chaine["etapes"]],
    }


# ---------------------------------------------------------------------------
# 4. executer : et la trace dit OU ca a casse
# ---------------------------------------------------------------------------

# Les briques qui peuvent partir chez le loueur, et le module qui porte DEJA
# leur controle de budget -- avec SA memoire, SON usage et SA phrase de secours.
# La chaine n'en fabrique aucun : `budget_modal.verifier()` est taille pour UN
# travail (un usage parmi quatre, un gpu, une duree), donc un total de chaine
# n'y entre pas et n'a pas a y entrer.
BUDGET_PAR_BRIQUE = {
    "video_rapide": "video",
    "video_soignee": "video",
    "chanson": "chanson",
    "dialogue": "dialogue",
}

# Celles dont le loueur est la SEULE route. Mesure du 22/09 dans `app.py` :
# `/chanson/creer` (l. 2541) et `/dialogue/creer` (l. 2923) appellent
# `budget_verifier` sans jamais consulter `ou_calculer.decider()` ; `/video/creer`
# le consulte AVANT (l. 2309) et ne verifie le budget que si la decision dit
# << modal >> (l. 2333) -- un clip part alors sur la carte d'ici, gratuitement.
#
# Ce que le registre en dit DIVERGE, et c'est note plutot que corrige ici :
# `video_rapide` et `video_soignee` portent `modes: [modal, kaggle, colab]` sans
# `local`, alors que `app.py:2321` les prepare bel et bien en mode maison. Le
# code fait foi ; la fiche du registre est en retard. Sous-plan, pas raccroc.
LOUEUR_SEUL = ("chanson", "dialogue")


def budget_du_noeud(etape) -> str | None:
    """None si ce noeud tient dans le credit offert, la phrase du module sinon.

    Decision du proprietaire, 22/09/2026 : << les depenses sont de fausses
    depenses tant que l'on reste dans le budget free >>. Jusque-la, un noeud
    pouvant partir chez le loueur etait refuse d'avance -- juste tant que rien
    ne verifiait, et faux des lors qu'il existe un moyen de verifier. Il
    s'interdisait un budget qu'on a.

    Ce qui reste interdit, c'est de DEPASSER, et ce n'est pas cette fonction
    qui le dit : c'est `budget_verifier(gpu, duree_max_s)` du module qui porte
    la brique, avec SA memoire, SON usage, SA duree et SA phrase de secours. La
    chaine n'invente aucun de ces quatre chiffres, et surtout pas un total : la
    garde est taillee pour UN travail, et on l'appelle une fois par noeud.
    """
    usage = BUDGET_PAR_BRIQUE.get(etape["brique"])
    if not usage:
        return None
    import importlib

    module = importlib.import_module(usage)
    qualite = QUALITE_DU_NOEUD.get(etape["brique"])
    gpu = (module.MODELES[qualite]["gpu"] if qualite
           else getattr(module, "GPU_MODAL", None))
    try:
        module.budget_verifier(gpu, module.DUREE_MAX_S)
    except module.BudgetDepasse as exc:
        return str(exc)
    return None


def _budget_verifie(etape):
    """La garde de `executer`, posee juste avant CE noeud et pas avant.

    Elle refuse toujours -- mais sur un depassement mesure, plus sur une
    absence de mesure.
    """
    refus = budget_du_noeud(etape)
    if refus:
        raise CompositeRefuse(
            "budget_depasse",
            # << Rien n'est lance >> etait faux des le deuxieme noeud : les
            # precedents ont deja tourne pour de bon. La trace dit lesquels.
            "%s Ce pas n'est pas lance." % refus, ou=CONTROLE)


def executer(chaine: dict, lancer, entree=None, verdict: dict | None = None,
             garde_budget=None) -> dict:
    """Lance la chaine noeud par noeud et rend une trace.

    `lancer(etape, entree) -> sortie` est injecte : chaque noeud part par la
    route qu'il a deja. La trace reprend la forme qui est DEJA en service dans
    le depot (`fallback_attempts`) : une liste d'etapes, chacune avec son
    resultat et son motif.

    Le resultat n'est pas un booleen. << Ou ca a casse >> est ce qui apprend :
    compilation, liaison, controle, execution, sortie invalide. Un booleen ne
    fait pas tourner le volant.
    """
    # `phrase` est le champ que le client LIT. Il manquait, et le motif tenait
    # sa place : quand la carte etait prise, la page montrait le slug
    # << arbitrage_du_client >> au lieu de la question francaise ecrite par
    # `ou_calculer.decider()`. Un motif nomme est fait pour le journal ; une
    # phrase est faite pour un debutant.
    trace = {"etapes": [], "resultat": None, "ou": None, "motif": None,
             "phrase": None, "sortie": None}

    if verdict is not None and verdict["atteignable"] == NON:
        trace.update(resultat="refus", ou=CONTROLE,
                     motif=";".join(verdict["motifs"]) or "refuse",
                     phrase=verdict["pourquoi"])
        return trace

    garde_budget = garde_budget or _budget_verifie
    courant = entree
    for etape in chaine["etapes"]:
        # La demande du client voyage AVEC le pas. Elle etait portee par le
        # graphe, puis par la chaine, et lue par personne : le noeud de chat
        # resumait, quoi qu'on lui ait demande. Copie, pas mutee : la chaine
        # montree au client ne change pas sous ses pieds.
        etape = dict(etape, demande=chaine.get("phrase", ""))
        try:
            # JUSTE AVANT le lancement, et par noeud : c'est la seule place ou
            # le pire cas est celui de CE travail-la.
            garde_budget(etape)
            courant = lancer(etape, courant)
        except CompositeRefuse as refus:
            trace["etapes"].append({"brique": etape["brique"], "resultat": "refus",
                                    "motif": refus.motif, "phrase": refus.phrase})
            trace.update(resultat="refus", ou=refus.ou, motif=refus.motif,
                         phrase=refus.phrase)
            return trace
        except Exception as erreur:  # noqa: BLE001 -- on NOMME l'echec, on ne le masque pas
            # Le motif reste un NOM, comme partout ailleurs, et le texte de
            # l'erreur va dans la phrase. Il occupait le champ du motif, ce qui
            # donnait deux sens a un meme champ selon le chemin emprunte.
            trace["etapes"].append({"brique": etape["brique"], "resultat": "echec",
                                    "motif": type(erreur).__name__,
                                    "phrase": str(erreur)})
            trace.update(resultat="echec", ou=EXECUTION,
                         motif=type(erreur).__name__, phrase=str(erreur))
            return trace

        if courant is None:
            trace["etapes"].append({"brique": etape["brique"], "resultat": "vide",
                                    "motif": "sortie_vide"})
            trace.update(
                resultat="echec", ou=SORTIE, motif="sortie_vide",
                phrase="« %s » n’a rien rendu, et la suite de la chaîne "
                       "attendait quelque chose." % etape["fonction"])
            return trace

        trace["etapes"].append({"brique": etape["brique"], "resultat": "rendu",
                                "motif": None})

    trace.update(resultat="rendu", sortie=courant)
    return trace
# ---------------------------------------------------------------------------
# 5. La production : chaque noeud part par la route qu'il a DEJA
# ---------------------------------------------------------------------------
# Les trois briques de la chaine temoin sont servies par le routeur, qui est
# deja joignable depuis ce service (il l'est depuis le 17/09 pour nettoyer un
# dialogue). Aucun fournisseur neuf, aucune cle neuve, aucune sortie reseau
# supplementaire.

ROUTEUR = os.getenv("SANDBOX_ROUTEUR_URL", "http://free-tier-manager:8000")

# Une chaine de trois pas dont un transcrit un enregistrement : le delai est
# celui de la transcription, mesuree a 63 s pour 147 s de son le 17/09.
DELAI_S = int(os.getenv("COMPOSITE_TIMEOUT_SECONDS", "900"))

# brique -> comment on la lance. La table est EXPLICITE : une brique absente
# d'ici ne se lance pas, elle se refuse avec son motif. Fermee par defaut,
# comme la garde de budget : le silence ne doit jamais valoir autorisation.
ROUTES = {
    "dictee_locale": ("transcription", "/v1/audio/transcriptions"),
    "dictee_groq": ("transcription", "/v1/audio/transcriptions"),
    "chat_auto": ("chat", "/v1/chat/completions"),
    "chat_max": ("chat", "/v1/chat/completions"),
    "voix_fr": ("voix", "/v1/audio/speech"),
    "voix_en": ("voix", "/v1/audio/speech"),
    "image_fabrication": ("image", "/v1/images/generations"),
    "image_lecture": ("vision", "/v1/chat/completions"),
    # Les cinq qui creent un TRAVAIL. Leur << chemin >> est un usage, pas une
    # adresse : il donne les trois adresses d'un coup (voir TRAVAUX).
    "video_rapide": ("travail", "video"),
    "video_soignee": ("travail", "video"),
    "video_maison": ("travail", "video"),
    "chanson": ("travail", "chanson"),
    "dialogue": ("travail", "dialogue"),
}


# Le Studio s'appelle LUI-MEME pour ces cinq briques, aux adresses que ses
# propres pages utilisent. C'est voulu : une chaine ne double pas la machinerie
# des travaux, elle s'en sert. Trois choses viennent donc sans etre reecrites --
# la carte d'ici qui passe devant quand elle est libre, le budget verifie au
# pire cas, et la question rendue au client quand la carte est prise.
SANDBOX = os.getenv("COMPOSITE_SANDBOX_URL", "http://127.0.0.1:8000")

# Ce que la chaine AJOUTE a la demande pour chaque travail. `video_maison` est
# la seule qui IMPOSE la carte d'ici ; les deux autres laissent le reglage du
# client trancher, et son defaut est << maison si libre >>.
TRAVAUX = {
    "video_rapide": ("video", {"qualite": "rapide"}),
    "video_soignee": ("video", {"qualite": "soigne"}),
    "video_maison": ("video", {"ou_calculer": "toujours-maison"}),
    "chanson": ("chanson", {}),
    "dialogue": ("dialogue", {}),
}

# La qualite video de chaque brique, pour aller chercher SA carte dans
# `video.MODELES` au lieu d'ecrire << L4 >> et << A100 >> une deuxieme fois.
QUALITE_DU_NOEUD = {"video_rapide": "rapide", "video_soignee": "soigne"}

# Un travail se regarde toutes les N secondes. Les etats terminaux sont ceux
# que `write_job` ecrit vraiment -- releves dans `app.py`, pas supposes.
ATTENTE_S = float(os.getenv("COMPOSITE_ATTENTE_SECONDS", "5"))
TRAVAIL_RENDU = ("succeeded",)
TRAVAIL_PERDU = ("failed", "cancelled", "needs_configuration", "handoff_ready")

# Les formats d'image que le Studio sait nommer, par leurs premiers
# octets. Le type d'une image ne se DEVINE pas : une image envoyee sous
# une etiquette fausse est acceptee par certains fournisseurs et refusee
# par d'autres, donc le defaut n'apparaitrait qu'une fois sur deux.
SIGNATURES_IMAGE = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


# Ce que la chaine AJOUTE a sa demande pour que la brique servie soit celle
# qu'elle a NOMMEE. Sans ce champ, deux briques arrivent a la meme adresse et
# c'est le reglage global du routeur qui tranche : releve du 22/09, la voix
# partait chez Groq sous l'etiquette de `dictee_locale`, dont le registre
# promet << la voix ne quitte pas la machine >> ; et `chat_max` tournait sur
# le modele de `chat_auto`.
#
# Les deux voix n'y figurent pas, et c'est MESURE : `/v1/audio/speech` decoupe
# le texte et lit chaque segment dans sa propre langue, et n'accepte aucun
# champ de langue. C'est une seule route portant deux fiches, pas une brique
# servie pour une autre. Lui inventer un champ serait inventer une capacite
# que le routeur n'a pas.
PRECISION = {
    "dictee_locale": {"moteur": "local"},
    "dictee_groq": {"moteur": "groq"},
    "chat_auto": {"model": "free-ai-auto"},
    "chat_max": {"model": "free-ai-max"},
    "image_lecture": {"model": "free-ai-auto"},
}


# Ce qu'on annonce au navigateur pour la sortie d'une chaine, et sous quel nom
# elle se telecharge. Une signature d'octets est une MESURE ; le type declare
# par la brique est une promesse. On croit la mesure d'abord.
MIME_PAR_TYPE = {
    "audio": ("audio/wav", "sortie.wav"),
    "image": ("image/png", "sortie.png"),
    "video": ("video/mp4", "sortie.mp4"),
    "fichier": ("application/octet-stream", "sortie.bin"),
    "texte": ("text/plain; charset=utf-8", "sortie.txt"),
}

# Les signatures que le Studio sait lire dans les premiers octets d'un fichier.
# Les images viennent de SIGNATURES_IMAGE : une seule table, pas deux.
NOMS_PAR_MIME = {
    "image/png": "sortie.png", "image/jpeg": "sortie.jpg",
    "image/gif": "sortie.gif", "audio/wav": "sortie.wav",
    "video/mp4": "sortie.mp4",
}


def type_de_sortie(octets, sorties=()) -> tuple[str, str]:
    """(type MIME, nom propose) pour ce qu'une chaine vient de produire.

    Jusqu'au 22/09/2026 au soir la route de lancement annoncait `audio/wav`
    pour tout, parce que la seule chaine possible finissait par une voix. Des
    que la fabrication d'image a eu une route, cette constante est devenue un
    mensonge que rien n'aurait signale : les octets etaient bons, le statut
    etait 200, et le navigateur affichait un lecteur audio muet.
    """
    brut = bytes(octets or b"")
    for signature, mime in SIGNATURES_IMAGE:
        if brut.startswith(signature):
            return mime, NOMS_PAR_MIME[mime]
    if brut[:4] == b"RIFF" and brut[8:12] == b"WAVE":
        return "audio/wav", NOMS_PAR_MIME["audio/wav"]
    if brut[4:8] == b"ftyp":
        return "video/mp4", NOMS_PAR_MIME["video/mp4"]
    # Rien de reconnu : on retombe sur ce que la derniere brique DECLARE
    # rendre, et a defaut sur le type le plus neutre. Jamais sur une supposition
    # qui ferait passer un fichier pour un autre.
    declare = (list(sorties) or ["fichier"])[0]
    return MIME_PAR_TYPE.get(declare, MIME_PAR_TYPE["fichier"])


def _cle_du_routeur() -> str:
    cle = os.getenv("FREE_TIER_MANAGER_KEY", "").strip()
    if not cle:
        raise CompositeRefuse(
            "routeur_sans_cle",
            "Le routeur n'est pas joignable depuis ce service : sa cle interne "
            "manque. Rien n'est lance.", ou=EXECUTION)
    return cle


def appeler_le_modele(consigne: str) -> str:
    """Le SEUL appel a un modele de toute la chaine, et il est gratuit.

    Il passe par la passerelle qui existe deja. Sur une installation sans cle
    de palier gratuit, le chat refuse -- et ce refus-la est une reponse propre,
    pas une panne : il porte son motif et sa phrase.
    """
    import httpx

    with httpx.Client(timeout=DELAI_S) as client:
        reponse = client.post(
            ROUTEUR + "/v1/chat/completions",
            headers={"Authorization": "Bearer " + _cle_du_routeur()},
            json={"model": "free-ai-auto", "stream": False,
                  "messages": [{"role": "user", "content": consigne}]})
        if reponse.status_code >= 400:
            raise CompositeRefuse(
                "chat_indisponible",
                "Aucun service de chat gratuit ne repond pour lire votre "
                "demande. Le chat a besoin d'une cle de palier gratuit "
                "configuree (page << Cles >>).", ou=COMPILATION)
        choix = (reponse.json().get("choices") or [{}])[0]
        return (choix.get("message") or {}).get("content") or ""


def lancer_par_le_routeur(etape: dict, entree):
    """Lance UN noeud. `entree` est la sortie du noeud precedent, type nu.

    Aucune conversion implicite : si le type recu n'est pas celui que la brique
    declare, on refuse en le NOMMANT plutot que de tenter une coercition qui
    reussirait parfois.
    """
    import httpx

    route = ROUTES.get(etape["brique"])
    if route is None:
        raise CompositeRefuse(
            "brique_sans_route",
            "<< %s >> n'a pas encore de route dans une chaine. Ce pas n'est "
            "pas lance." % etape["fonction"], ou=EXECUTION)
    genre, chemin = route

    # Les travaux ne passent pas par le routeur du palier gratuit : ils
    # s'adressent au Studio lui-meme, avec sa propre cle.
    if genre == "travail":
        return lancer_un_travail(etape, entree)

    # Ce qui est faux dans la demande se dit AVANT de demander une cle a qui
    # que ce soit -- meme discipline qu'a la route du dialogue, ou un texte mal
    # balise se refuse meme quand Modal n'est pas branche. Un fichier illisible
    # n'a pas besoin d'un routeur joignable pour etre illisible.
    image = _data_uri(etape, entree) if genre == "vision" else None

    entetes = {"Authorization": "Bearer " + _cle_du_routeur()}

    with httpx.Client(timeout=DELAI_S) as client:
        if genre == "transcription":
            if not isinstance(entree, (bytes, bytearray)):
                raise CompositeRefuse(
                    "entree_du_mauvais_type",
                    "<< %s >> attend un enregistrement et a recu autre chose."
                    % etape["fonction"], ou=EXECUTION)
            reponse = client.post(
                ROUTEUR + chemin, headers=entetes,
                data=PRECISION.get(etape["brique"], {}),
                files={"file": ("enregistrement.wav", bytes(entree), "audio/wav")})
            _ou_refus(reponse, etape, "La dictee n'a pas abouti.")
            return (reponse.json().get("text") or "").strip() or None

        if genre == "chat":
            reponse = client.post(
                ROUTEUR + chemin, headers=entetes,
                json=dict(PRECISION.get(etape["brique"], {}), stream=False,
                          messages=[{"role": "user",
                                     "content": _consigne_du_chat(etape, entree)}]))
            _ou_refus(reponse, etape,
                      "Aucun service de chat gratuit ne repond. Ce noeud a "
                      "besoin d'une cle de palier gratuit configuree.")
            choix = (reponse.json().get("choices") or [{}])[0]
            return ((choix.get("message") or {}).get("content") or "").strip() or None

        if genre == "image":
            reponse = client.post(
                ROUTEUR + chemin, headers=entetes,
                json={"prompt": _consigne_du_chat(etape, entree), "n": 1})
            _ou_refus(reponse, etape, "La fabrication d'image n'a pas abouti.")
            images = reponse.json().get("data") or []
            nu = (images[0] or {}).get("b64_json") if images else None
            if not nu:
                raise CompositeRefuse(
                    "noeud_sans_sortie",
                    "<< %s >> a repondu sans image. Ce pas n'est pas lance."
                    % etape["fonction"], ou=EXECUTION)
            return base64.b64decode(nu)

        if genre == "vision":
            reponse = client.post(
                ROUTEUR + chemin, headers=entetes,
                json=dict(PRECISION.get(etape["brique"], {}), stream=False,
                          messages=[{"role": "user", "content": [
                              {"type": "text",
                               "text": _consigne_de_l_image(etape)},
                              {"type": "image_url",
                               "image_url": {"url": image}},
                          ]}]))
            _ou_refus(reponse, etape,
                      "Aucun service gratuit qui sait lire une image ne repond.")
            choix = (reponse.json().get("choices") or [{}])[0]
            return ((choix.get("message") or {}).get("content") or "").strip() or None

        # la voix. Le routeur choisit la langue sur le texte lui-meme.
        texte = str(entree or "")
        reponse = client.post(ROUTEUR + chemin, headers=entetes,
                              json={"input": texte})
        _ou_refus(reponse, etape, "La lecture a haute voix n'a pas abouti.")
        return reponse.content or None


def _cle_du_sandbox() -> str:
    cle = os.getenv("SANDBOX_MANAGER_KEY", "").strip()
    if not cle:
        raise CompositeRefuse(
            "sandbox_sans_cle",
            "Le Studio ne peut pas se lancer un travail a lui-meme : sa cle "
            "interne manque. Ce pas n'est pas lance.", ou=EXECUTION)
    return cle


def demande_du_travail(etape: dict, entree) -> tuple[str, dict]:
    """Ce qui part vraiment a `/<usage>/creer`, depuis le texte recu.

    Chaque usage a sa forme, et `preparer()` la refuse quand elle ne tient pas
    -- avec sa propre phrase francaise, qu'on relaie telle quelle plutot que
    d'en fabriquer une plus vague. La chanson demande DEUX choses d'un coup :
    son style vient de ce que le client a demande, ses paroles de l'etape
    precedente.
    """
    usage, fixe = TRAVAUX[etape["brique"]]
    texte = str(entree or "").strip()
    demande = (etape.get("demande") or "").strip()
    if usage == "video":
        return usage, dict(fixe, description=texte or demande)
    if usage == "chanson":
        return usage, dict(fixe, style=demande or "chanson en français",
                           paroles=texte or demande)
    return usage, dict(fixe, texte=texte or demande)


def lancer_un_travail(etape: dict, entree):
    """Creer, attendre, recuperer -- aux adresses des pages du Studio.

    Le sondeur separe << pas ENCORE >> de << JAMAIS >>. Une boucle d'attente est
    le seul endroit ou une faute ne produit aucun signal : un 404 traduit en
    << pas encore pret >> a coute cinquante minutes sur une adresse morte, le
    21/09/2026. Ici, tout statut >= 400 leve immediatement ; seuls les etats de
    travail que `app.py` ecrit vraiment font attendre.
    """
    import httpx

    usage, demande = demande_du_travail(etape, entree)
    entetes = {"Authorization": "Bearer " + _cle_du_sandbox()}
    base = "%s/%s" % (SANDBOX, usage)

    with httpx.Client(timeout=DELAI_S) as client:
        creation = client.post(base + "/creer", headers=entetes, json=demande)
        if creation.status_code == 409:
            raise CompositeRefuse("arbitrage_du_client",
                                  _phrase_de_l_arbitrage(creation, etape),
                                  ou=EXECUTION)
        _ou_refus(creation, etape, "Ce travail n'a pas pu etre lance.")
        jid = str((creation.json() or {}).get("id") or "")
        if not jid:
            raise CompositeRefuse(
                "travail_sans_identifiant",
                "<< %s >> a ete accepte sans identifiant de travail : le Studio "
                "ne saurait pas en recuperer le resultat." % etape["fonction"],
                ou=EXECUTION)

        fin = time.monotonic() + DELAI_S
        while True:
            etat = client.get("%s/jobs/%s" % (base, jid), headers=entetes)
            _ou_refus(etat, etape, "L'etat de ce travail n'est pas lisible.")
            corps = etat.json() or {}
            statut = str(corps.get("status") or "")
            if statut in TRAVAIL_RENDU:
                break
            if statut in TRAVAIL_PERDU:
                raise CompositeRefuse(
                    "travail_echoue",
                    "<< %s >> s'est arrete : %s. %s"
                    % (etape["fonction"], statut,
                       str(corps.get("message") or "").strip()),
                    ou=EXECUTION)
            if time.monotonic() >= fin:
                raise CompositeRefuse(
                    "travail_trop_long",
                    "<< %s >> n'a pas fini en %d secondes. Il continue peut-etre "
                    "sur sa propre page ; la chaine, elle, s'arrete ici."
                    % (etape["fonction"], DELAI_S), ou=EXECUTION)
            time.sleep(ATTENTE_S)

        # L'adresse du fichier se LIT dans la reponse d'etat, elle ne se
        # fabrique pas. Deux raisons, mesurees toutes les deux :
        #   - la route du fichier ne lit pas l'entete d'autorisation ; elle
        #     compare un jeton par travail passe en parametre
        #     (`hmac.compare_digest(cle, attendu)`, app.py:2395). Une adresse
        #     construite ici repondrait 401, quel que soit le porteur ;
        #   - le nom du champ change avec l'usage : `video_url` (app.py:2379)
        #     pour la video, `son_url` pour la chanson (l. 2599) et le dialogue
        #     (l. 2975).
        adresse = str(corps.get("video_url") or corps.get("son_url") or "")
        if not adresse:
            raise CompositeRefuse(
                "travail_sans_fichier",
                "<< %s >> s'est termine sans deposer de fichier : la chaine "
                "n'a rien a passer au pas suivant." % etape["fonction"],
                ou=EXECUTION)
        fichier = client.get(SANDBOX + adresse, headers=entetes)
        _ou_refus(fichier, etape, "Ce travail n'a rien rendu.")
        return fichier.content or None


def _phrase_de_l_arbitrage(reponse, etape: dict) -> str:
    """Un 409 de `/creer` n'est pas une panne : c'est une question au client.

    La carte est prise, et aucune regle ecrite d'avance ne sait s'il est
    presse. Le module de decision rend deja une phrase francaise faite pour
    etre montree telle quelle : on la reprend, on n'en ecrit pas une autre.
    """
    try:
        decision = reponse.json().get("detail") or {}
    except ValueError:
        decision = {}
    dit = str(decision.get("pourquoi") or "").strip()
    return (dit or ("<< %s >> attend que vous choisissiez entre attendre la "
                    "carte d'ici et louer une machine." % etape["fonction"]))


def _data_uri(etape: dict, octets) -> str:
    """Le type d'une image se LIT dans ses premiers octets, jamais se devine.

    Un format que rien ne reconnait se refuse en le nommant. L'envoyer
    sous une etiquette au hasard marcherait chez un fournisseur et pas
    chez le suivant : le defaut n'apparaitrait qu'une fois sur deux, et
    c'est la panne la plus chere a trouver.
    """
    if not isinstance(octets, (bytes, bytearray)):
        raise CompositeRefuse(
            "entree_du_mauvais_type",
            "<< %s >> attend une image et a recu autre chose."
            % etape["fonction"], ou=EXECUTION)
    brut = bytes(octets)
    for signature, mime in SIGNATURES_IMAGE:
        if brut.startswith(signature):
            return "data:%s;base64,%s" % (mime, base64.b64encode(brut).decode("ascii"))
    raise CompositeRefuse(
        "image_de_format_inconnu",
        "<< %s >> a recu un fichier dont le format d'image n'est pas reconnu. "
        "Le Studio sait lire du PNG, du JPEG et du GIF. Ce pas n'est pas lance."
        % etape["fonction"], ou=EXECUTION)


def _consigne_de_l_image(etape: dict) -> str:
    """Ce que la chaine demande a propos de l'image.

    Meme regle que pour le chat : c'est la demande du CLIENT qui gouverne,
    et la phrase figee ne sert que lorsqu'il n'a rien precise.
    """
    demande = (etape.get("demande") or "").strip()
    return (demande or "Décris cette image en français.") + (
        "\n\nRépondez seulement par le résultat de cette étape.")


def _consigne_du_chat(etape: dict, entree) -> str:
    """Ce que le noeud de chat envoie vraiment -- a part, pour etre lisible.

    Jusqu'au 22/09 ce message etait fige sur << Resume ce texte >>, et la
    demande du client -- portee par le graphe, puis par la chaine -- n'etait
    lue par personne. Une chaine d'un seul noeud de chat recevait donc
    << Resume ce texte ... : None >> et le Studio rendait << C'est fait >> avec
    une reponse a une question que personne n'avait posee.

    Ce qui n'est PAS fait ici, et qui reste ouvert : la demande part entiere a
    chaque noeud, elle n'est pas decoupee en la part qui revient a celui-ci.
    """
    demande = (etape.get("demande") or "").strip()
    if entree is None:
        return demande or "Bonjour."
    return ((demande or "Résume ce texte en quelques phrases, en français.")
            + "\n\nVoici le texte de l'étape précédente. Répondez seulement "
              "par le résultat de cette étape.\n\n" + str(entree))


def _ou_refus(reponse, etape, phrase):
    """Un refus du routeur devient un refus NOMME, avec ce que le routeur a dit.

    Le routeur rend deja des phrases francaises faites pour etre montrees : on
    les reprend telles quelles au lieu d'en fabriquer une plus vague.
    """
    if reponse.status_code < 400:
        return
    detail = ""
    try:
        corps = reponse.json()
        detail = str(corps.get("detail") or (corps.get("error") or {}).get("message") or "")
    except ValueError:
        detail = ""
    raise CompositeRefuse(
        "noeud_refuse",
        ("%s %s" % (detail or phrase, "")).strip(), ou=EXECUTION)


# ---------------------------------------------------------------------------
# 6. La page
# ---------------------------------------------------------------------------
# Un champ, un bouton, le verdict avec son motif, puis le fichier. Elle passe
# par `format_fr.avec_formateurs()` comme les quatre autres, donc l'argent et
# les dates sortent en francais.

PAGE_HTML = """<!doctype html><html lang=fr><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>Encha\u00eener \u2014 Free AI Studio</title>
<style>
body{font-family:system-ui;max-width:760px;margin:35px auto;padding:0 18px;line-height:1.55}
h1{margin-bottom:4px}
.sous{color:#555;margin-top:0}
textarea,input[type=file]{width:100%;box-sizing:border-box;font:inherit}
textarea{min-height:70px;padding:10px;border:1px solid #aaa;border-radius:10px}
button{font:inherit;padding:10px 16px;border:1px solid #777;border-radius:10px;
       background:#f6f6f6;cursor:pointer;margin-top:12px}
button[disabled]{opacity:.55;cursor:progress}
.bloc{border:1px solid #bbb;border-radius:12px;padding:14px 16px;margin-top:18px}
.oui{border-color:#2d7a33}.non{border-color:#a33}.inconnu,.partiel{border-color:#b7791f}
.etat{font-weight:600}
ol{margin:10px 0 0 0;padding-left:22px}
li{margin:3px 0}
.motif{color:#555;font-size:.94em}
.gris{color:#666;font-size:.94em}
</style>
<h1>\U0001f517 Encha\u00eener</h1>
<p class=sous>Dites ce que vous voulez obtenir. Le Studio compose les applications
qu\u2019il a d\u00e9j\u00e0, vous dit <strong>avant de lancer</strong> si c\u2019est possible et
combien \u00e7a co\u00fbte, puis le fait.</p>

<label for=phrase><strong>Ce que vous voulez</strong></label>
<textarea id=phrase placeholder="R\u00e9sume cet enregistrement et lis-le-moi \u00e0 voix haute"></textarea>

<label for=fichier class=gris>Un enregistrement ou une photo, si votre demande en a besoin</label>
<input type=file id=fichier accept="audio/*,image/*">

<button id=voir>Voir si c\u2019est possible</button>
<button id=lancer disabled>Lancer</button>

<div id=verdict></div>
<div id=resultat></div>

<script>
const CLE = "__CLE__";
let derniere = null;

function bloc(v){
  const noms = {oui:"C\u2019est possible", partiel:"Possible, avec une r\u00e9serve",
                inconnu:"Je ne peux pas trancher", non:"Ce n\u2019est pas possible"};
  const etapes = (v.etapes||[]).map(e =>
    "<li>" + e.fonction + " <span class=motif>(" + e.entrees.join(", ") +
    " \u2192 " + e.sorties.join(", ") + ")</span></li>").join("");
  return "<div class='bloc " + v.atteignable + "'>" +
    "<p class=etat>" + (noms[v.atteignable]||v.atteignable) + "</p>" +
    "<p>" + (v.phrase || v.pourquoi) + "</p>" +
    (etapes ? "<ol>" + etapes + "</ol>" : "") + "</div>";
}

async function envoyer(chemin, avecFichier){
  const corps = new FormData();
  corps.append("phrase", document.getElementById("phrase").value);
  // Les briques MONTREES repartent telles quelles : sans elles, la route
  // recompilerait la phrase et pourrait lancer une autre chaine que celle
  // dont le verdict vient d'etre lu.
  if (avecFichier && derniere)
    corps.append("briques", (derniere.etapes||[]).map(e => e.brique).join(","));
  const f = document.getElementById("fichier").files[0];
  if (avecFichier && f) corps.append("fichier", f);
  const r = await fetch(chemin, {method:"POST",
    headers:{"Authorization":"Bearer " + CLE}, body:corps});
  return {ok:r.ok, statut:r.status, corps:r};
}

document.getElementById("voir").onclick = async () => {
  const b = document.getElementById("voir");
  b.disabled = true; b.textContent = "Je regarde\u2026";
  document.getElementById("resultat").innerHTML = "";
  try {
    const r = await envoyer("/composite/verdict", false);
    const v = await r.corps.json();
    if (!r.ok) {
      document.getElementById("verdict").innerHTML =
        "<div class='bloc non'><p class=etat>Je n\u2019ai pas pu lire votre demande</p><p>"
        + (v.detail || "") + "</p></div>";
      derniere = null;
    } else {
      document.getElementById("verdict").innerHTML = bloc(v);
      derniere = v;
    }
  } finally {
    b.disabled = false; b.textContent = "Voir si c\u2019est possible";
    document.getElementById("lancer").disabled =
      !(derniere && (derniere.atteignable === "oui" || derniere.atteignable === "partiel"));
  }
};

document.getElementById("lancer").onclick = async () => {
  const b = document.getElementById("lancer");
  b.disabled = true; b.textContent = "Je fais\u2026";
  try {
    const r = await envoyer("/composite/lancer", true);
    if (!r.ok) {
      const v = await r.corps.json();
      document.getElementById("resultat").innerHTML =
        "<div class='bloc non'><p class=etat>\u00c7a s\u2019est arr\u00eat\u00e9 \u00e0 l\u2019\u00e9tape "
        + (v.ou || "?") + "</p><p>" + (v.detail || "") + "</p></div>";
      return;
    }
    const octets = await r.corps.blob();
    const url = URL.createObjectURL(octets);
    // Ce qu'on montre suit le type que le serveur ANNONCE. Fige sur <audio>
    // jusqu'au 22/09 au soir : une chaine finissant par une image affichait un
    // lecteur audio muet, avec les bons octets derriere.
    const type = octets.type || "";
    const nom = (r.corps.headers.get("X-Composite-Nom") || "sortie.bin");
    let apercu;
    if (type.startsWith("image/"))      apercu = "<img src='" + url + "' alt='' style='max-width:100%'>";
    else if (type.startsWith("video/")) apercu = "<video controls src='" + url + "' style='max-width:100%'></video>";
    else if (type.startsWith("audio/")) apercu = "<audio controls src='" + url + "'></audio>";
    else                                apercu = "";
    document.getElementById("resultat").innerHTML =
      "<div class='bloc oui'><p class=etat>C\u2019est fait</p>"
      + apercu + (apercu ? "<br>" : "")
      + "<a href='" + url + "' download='" + nom + "'>T\u00e9l\u00e9charger le fichier</a></div>";
  } finally {
    b.disabled = false; b.textContent = "Lancer";
  }
};
</script>
</html>"""
