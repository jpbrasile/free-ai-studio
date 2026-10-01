"""Les règles numérotées du Studio vidéo, et leur contrôle plan par plan.

Demande du propriétaire, 30/09/2026, après l'audit des deux films de la nuit : « add a
reviewer that say for each clip that rule n° 1 to xx are followed », puis « the hard
code is to do all the post processing from the user initial prompt in english ».

L'audit (PLAN.md) avait trouvé que le Studio VOYAIT la plupart des défauts (relecteur,
comparaison des visages, juge) sans que rien n'agisse : le tournage partait quand même.
Ici, chaque règle a un numéro, une étape, et un contrôle. Le rapport dit, pour chaque
plan : suivie (True), non suivie (False, avec la raison), sans objet ou illisible (None).

Étapes : « texte » (le code, avant tout), « depart » (l'image de départ, vue par le
modèle qui voit, gratuit), « clip » (le plan tourné : planche et écoute, gratuit).
"""
import json
import re

import video_h3

REGLES = (
    (0, "texte", "Tout le travail part de l'histoire traduite en anglais ; seules les répliques gardent leur langue."),
    (1, "texte", "Chaque personnage ou objet présent au début du plan est nommé dans le texte du plan."),
    (2, "texte", "Aucune remarque bloquante du relecteur ne reste sur le plan."),
    (3, "texte", "Deux personnages ne partent pas du même endroit du cadre."),
    (4, "texte", "Chaque personnage qui parle a sa fiche, avec un profil voix dans la langue de ses répliques, "
                 "et sa voix part avec le plan."),
    (5, "texte", "Rien n'est créé deux fois : ce qui est déjà à l'image au début du plan (posé au début, ou sur "
                 "la dernière image du plan d'avant pour une suite) n'y entre pas, n'y apparaît pas et repart "
                 "de là où il était."),
    (6, "depart", "Chaque personnage et chaque objet présent au début apparaît une fois, et une seule, "
                  "sur l'image de départ."),
    (7, "depart", "Sur l'image de départ, le visage de chaque personnage ressemble à sa fiche."),
    (8, "depart", "Ni texte, ni bulle, ni légende ajoutés sur l'image de départ."),
    (9, "clip", "Chaque réplique est entendue comme elle est écrite."),
    (10, "clip", "Aucun personnage ni objet n'apparaît en double dans le plan tourné."),
    (11, "clip", "Les personnages restent ceux de leurs fiches pendant tout le plan."),
    (12, "clip", "La fin du plan montre ce que le tableau des éléments annonce en « fin »."),
    # 01/10, propriétaire : « simply say the start and the end pose and leave H3 free to execute ».
    (13, "texte", "Un personnage qui change de place : le texte dit d'où il part et où il s'arrête, jamais le "
                  "trajet (côté par où il entre, passage devant, derrière ou à côté de quelqu'un, traversée "
                  "du cadre) ; le modèle vidéo choisit le chemin."),
    # 01/10, propriétaire : « tyler parle et leila ne se retourne pas vers lui […] on généralise comment ? »
    (14, "texte", "Quand un personnage parle à un autre qui est dans le plan, le texte dit ce que fait celui "
                  "qui écoute juste après la réplique (il regarde, se tourne, répond), ou qu'il ne réagit pas."),
)
NUMEROS = {etape: [n for n, e, _ in REGLES if e == etape] for etape in ("texte", "depart", "clip")}
# Les règles qui arrêtent le tournage (avant tout sou) : texte et image de départ.
AVANT_TOURNAGE = NUMEROS["texte"] + NUMEROS["depart"]

# « the », « le », « l' »… : un nom se retrouve dans le texte sans son article.
_ARTICLES = {"the", "a", "an", "le", "la", "les", "l", "un", "une", "des", "du", "de",
             # Le compte que la consigne du découpage fait écrire (« the only ball ») : le
             # 30/09, « the only bulletin board » était dit absent d'un texte qui le nommait.
             "only", "single", "seul", "seule"}
_PROFONDEURS = (("foreground", "foreground"), ("background", "background"), ("midground", "middle"),
                ("middle ground", "middle"), ("middle distance", "middle"))
_COTES = (("left", "left"), ("right", "right"), ("centre", "centre"), ("center", "centre"), ("middle", "centre"))


def resultat(ok, pourquoi: str = "") -> dict:
    return {"ok": ok, "pourquoi": " ".join(str(pourquoi or "").split())[:300]}


def present_au_debut(e: dict) -> bool:
    debut = video_h3._norme_replique(e.get("debut", ""))
    if debut in {video_h3._norme_replique(x) for x in video_h3._SANS_DEPART}:
        return False
    return not video_h3.hors_champ(debut)


def mots_du_nom(nom: str) -> list:
    return [m for m in video_h3._mots(nom) if m not in _ARTICLES]


def nomme_dans(nom: str, texte: str) -> bool:
    """Tous les mots du nom (sans article) sont dans le texte."""
    mots, dans = mots_du_nom(nom), set(video_h3._mots(texte))
    return bool(mots) and all(m in dans for m in mots)


# Ce qui dit une direction sans dire une place : « facing right », « left hand »…
# Revue du 30/09 : « foreground, centre, facing right » était lu (foreground, right).
_PAS_UNE_PLACE = re.compile(
    r"\b(?:facing|looking|turned|turning|pointing|leaning|glancing|gazing|seen from the|profile facing)"
    r"(?: to| towards| toward)?(?: the)? (?:left|right|centre|center|camera|forward|away)\b"
    r"|\b(?:left|right) (?:hand|hands|arm|arms|foot|feet|leg|legs|shoulder|shoulders|side of \w+ body|eye|ear)\b")


def position(debut: str):
    """(profondeur, côté) lus au début d'un élément ; None s'il en manque un. Le premier
    mot de place l'emporte (la place est écrite en tête : « foreground, left, … »)."""
    t = _PAS_UNE_PLACE.sub(" ", " ".join(video_h3._mots(debut)))
    trouve = lambda paires, texte: min(((m.start(), v) for k, v in paires
                                        for m in re.finditer(r"\b%s\b" % k, texte)), default=(0, None))[1]
    profondeur = trouve(_PROFONDEURS, t)
    # Le côté se lit après la profondeur : « middle ground » n'est pas un côté.
    cote = trouve(_COTES, re.sub(r"\bmiddle (ground|distance)\b", " ", t))
    return (profondeur, cote) if profondeur and cote else None


def en_francais(plan: dict) -> list:
    """Les cases du plan où il reste du français hors des répliques (règle 0)."""
    cases = [("le texte", plan.get("image_paroles", "")), ("l'ambiance", plan.get("ambiance", ""))]
    for e in plan.get("elements") or []:
        cases.append(("« %s »" % e.get("nom", ""), " ".join(str(e.get(k, "")) for k in video_h3.TABLEAU_CHAMPS)))
    return [ou for ou, t in cases if video_h3.reste_du_francais(t)]


def _cle(nom: str) -> str:
    return " ".join(mots_du_nom(nom))


def _hors_champ(etat: str) -> bool:
    return not present_au_debut({"debut": etat})


# --- Règle 4 : qui parle, et avec quelle voix ---------------------------------------

# Un verbe de parole juste après un nom sans fiche : « Tom says », « Tom asks ».
_PAROLE = re.compile(r"^\W*(?:\w+\W+){0,3}?(?:says?|said|asks?|asked|shouts?|shouted|answers?|answered|replies|"
                     r"replied|calls?|called|whispers?|whispered|cries|cried|exclaims?|exclaimed|responds?|"
                     r"responded|adds?|added|tells?|told|murmurs?|yells?|yelled|dit|demande|répond|crie)\b", re.I)


def qui_parle(texte: str, personnes: list, autres=()) -> list:
    """[(réplique, rang dans `personnes` ou None, nom sans fiche ou None)].

    `personnes` : les noms des fiches de PERSONNES, seuls locuteurs possibles, comme
    dans attribuer_repliques, qui fait le texte envoyé : le premier d'entre eux nommé
    dans la phrase de la réplique, sinon le dernier nommé avant. `autres` : les noms du
    tableau sans fiche de personne ; un de ceux-là suivi d'un verbe de parole dans la
    phrase (« Tom says ») est un locuteur sans fiche, donc une faute. Revue du 30/09 :
    les fiches et le tableau comptés ensemble faisaient dire « Leila n'a pas de fiche »
    à une réplique que Leila dit bien, et un objet nommé en tête de phrase parlait."""
    texte = str(texte or "")
    vues = list(video_h3._PAROLES.finditer(texte))
    dedans = [(m.start(), m.end()) for m in vues]

    def places(noms):
        return sorted((m.start(), m.end(), k) for k, nom in enumerate(noms) if str(nom).strip()
                      for m in re.finditer(video_h3._motif_nom(nom), texte, re.I)
                      if not any(a <= m.start() < b for a, b in dedans))
    les_personnes, les_autres = places(personnes), places(autres)
    sortie, fin_precedente = [], 0
    for m in vues:
        avant = texte[fin_precedente:m.start()]
        debut_phrase = fin_precedente + max(avant.rfind(c) for c in ".!?;\n") + 1
        dans_la_phrase = [k for a, _, k in les_personnes if debut_phrase <= a < m.start()]
        plus_tot = [k for a, _, k in les_personnes if a < debut_phrase]
        sans_fiche = [autres[k] for a, b, k in les_autres
                      if debut_phrase <= a < m.start() and _PAROLE.search(texte[b:m.start()])]
        replique = next(g for g in m.groups() if g).strip()
        if dans_la_phrase:
            sortie.append((replique, dans_la_phrase[0], None))
        elif sans_fiche:
            sortie.append((replique, None, sans_fiche[0]))
        else:
            sortie.append((replique, plus_tot[-1] if plus_tot else None, None))
        fin_precedente = m.end()
    return sortie


def regle_voix(plan: dict, fiches: list, langues: dict, langue: str, envoyees=None) -> dict:
    """Règle 4. `fiches` : les fiches du scénario (dicts du Studio : id, nom, genre, voix) ;
    `langues` : {fiche : langue de ses répliques} ; `langue` : celle par défaut ;
    `envoyees` : les fiches dont la voix part VRAIMENT avec ce plan (mode et place
    comptés par l'appelant ; None : toutes, un plan « suite » n'en emporte aucune).
    Décision du propriétaire, 30/09 : « all speaker is created with a profile before
    hand including its voice in the appropriate language : to be hard coded in studio »."""
    texte = plan.get("image_paroles", "") + " " + plan.get("ambiance", "")
    parlants = [f for f in fiches if f.get("genre", "personne") == "personne"]
    connus = {_cle(f["nom"]) for f in fiches}
    autres = [e["nom"] for e in plan.get("elements") or [] if _cle(e["nom"]) not in connus]
    dites = qui_parle(texte, [f["nom"] for f in parlants], autres)
    if not dites:
        return resultat(None, "Pas de réplique dans ce plan.")
    if envoyees is None:
        envoyees = {f["id"] for f in fiches}
    fautes, locuteurs, paires = [], [], []
    for replique, k, sans_fiche in dites:
        court = "« %s »" % (replique[:40] + ("…" if len(replique) > 40 else ""))
        if sans_fiche:
            fautes.append(court + " : %s n'a pas de fiche de personne" % sans_fiche)
            continue
        if k is None:
            fautes.append(court + " : aucun personnage de fiche n'est nommé pour la dire")
            continue
        f = parlants[k]
        voulue, _ = video_h3.langue_de_replique(replique, (langues or {}).get(f["id"]) or langue)
        voix = f.get("voix") or {}
        # La voix d'origine, et les mêmes clonées dans d'autres langues (30/09).
        en = [voix.get("langue")] + list(f.get("voix_langues") or {}) if voix else []
        if not voix:
            fautes.append(court + " : la fiche de %s n'a pas de voix" % f["nom"])
        elif not voix.get("langue"):
            fautes.append(court + " : la langue de la voix de %s n'est pas notée (reposez la voix)" % f["nom"])
        elif voulue not in en:
            fautes.append(court + " : %s parle %s, sa voix est en %s (créez-la en %s depuis sa fiche)" % (
                f["nom"], video_h3.LANGUES_PAROLES.get(voulue, voulue),
                " et en ".join(video_h3.LANGUES_PAROLES.get(l, l) for l in en),
                video_h3.LANGUES_PAROLES.get(voulue, voulue)))
        elif f["id"] not in envoyees:
            fautes.append(court + " : la voix de %s ne part pas avec ce plan%s" % (
                f["nom"], " (plan « suite » parti de la dernière image seule)"
                if plan.get("enchainement") == "suite" else ""))
        if f["id"] not in locuteurs:
            locuteurs.append(f["id"])
        if (f["id"], voulue) not in paires:
            paires.append((f["id"], voulue))
    # Audit du 30/09 : « Ils volent ! » dit par un Marc inventé, d'un timbre inconnu, dans
    # une suite partie sans fiche. Depuis, une suite garde ses fiches quand elles tiennent
    # avec la dernière image ; l'appelant dit lesquelles partent (`envoyees`).
    if len(locuteurs) > video_h3.VOIX_PAR_PLAN:
        fautes.append("%d personnages parlent, %d voix au plus partent avec un plan" % (
            len(locuteurs), video_h3.VOIX_PAR_PLAN))
    elif len(paires) > video_h3.VOIX_PAR_PLAN:
        fautes.append("%d voix (une par personnage et par langue), %d au plus partent avec un plan" % (
            len(paires), video_h3.VOIX_PAR_PLAN))
    return resultat(not fautes, " ; ".join(fautes) + ("." if fautes else ""))


# --- Règle 5 : rien n'est créé deux fois --------------------------------------------

# Ce qui fait ENTRER un élément dans le cadre : dit d'un élément déjà là, le modèle
# le dessine une seconde fois (librairie, 30/09 : Léa « enters » alors que la
# première image la montrait déjà ; deux Léa sur l'image de départ). La revue du 30/09
# a trouvé « walks into the room », « comes back », « reappears », « runs in », « is
# back », et le sujet dit par un pronom (« She enters »).
# « back » seul ne compte qu'après come : « walks back to the centre » est un déplacement
# dans le cadre (film parc2, 30/09 : faux « Marc est déjà à l'image et le plan le fait entrer »).
_ENTREE = re.compile(
    r"\b(?:enters?|entering|entered|re-?enters?|(?:walks?|walking|walked|runs?|running|ran|rushes|rushing|"
    r"rushed|hurries|hurrying|hurried|steps?|stepping|stepped|comes?|coming|came|bursts?|slips?|strolls?|"
    r"wanders?|marches|marching|dashes|dashing|skips?|skipping|jogs?|jogging) (?:back )?(?:in|into)\b|"
    r"(?:comes?|coming|came) back\b|"
    r"(?:re)?appears?|(?:re)?appearing|(?:re)?appeared|returns?|returning|returned|is back|are back|"
    r"comes? into (?:view|frame|the frame|shot)|into (?:view|frame|the frame|shot)|pops? up|popping up|"
    r"emerges?|emerging|emerged|arrives? (?:in|into) (?:the )?(?:frame|shot|view|scene|room|shop|park))",
    re.I)
_PRONOMS = re.compile(r"\b(he|she|they|it|his|her|him|their)\b", re.I)


def _phrases(texte: str) -> list:
    """Les phrases du texte, répliques retirées (un mot d'une réplique n'est pas une action)."""
    return [p for p in re.split(r"[.;!?\n]", video_h3._PAROLES.sub(" ", str(texte or ""))) if p.strip()]


SANS_NOM = "?"   # une entrée dont le sujet n'est dit que par un pronom, sans nom avant


def entrants(texte: str, noms: list) -> set:
    """Les noms (de `noms`) que le texte fait entrer : le nom qui précède le verbe
    d'entrée dans sa phrase ; sans nom, un pronom renvoie au dernier nommé avant ; sans
    nom avant du tout, SANS_NOM (« She enters » : qui ?)."""
    sortie, dernier = set(), None
    for phrase in _phrases(texte):
        cites = sorted((m.start(), nom) for nom in noms if str(nom).strip()
                       for m in re.finditer(video_h3._motif_nom(nom), phrase, re.I))
        # Les mots d'un nom sans accent ni article : « the red ball » cité « the ball » ne compte pas.
        if not cites:
            cites = [(0, nom) for nom in noms if nomme_dans(nom, phrase)]
        for m in _ENTREE.finditer(phrase):
            avant = [nom for a, nom in cites if a < m.start()]
            if avant:
                sortie.add(avant[-1])
            elif _PRONOMS.search(phrase[:m.start()]):
                sortie.add(dernier or SANS_NOM)
        if cites:
            dernier = cites[-1][1]
    return sortie


def _entre(nom: str, texte: str) -> bool:
    return nom in entrants(texte, [nom])


def _meme_mouvement(a: str, b: str) -> bool:
    """Deux mouvements qui disent la même action (mots pleins en commun, 70 % au moins)."""
    vides = {"none", "the", "a", "an", "and", "then", "his", "her", "their", "its", "with", "to", "of",
             "on", "in", "at", "by", "from", "into", "onto", "up", "down", "it", "him", "them"}
    ma = {m for m in video_h3._mots(a) if m not in vides and len(m) > 2}
    mb = {m for m in video_h3._mots(b) if m not in vides and len(m) > 2}
    if not ma or not mb:
        return False
    # « falls down » deux fois : un seul mot plein, mais le même.
    return ma == mb or (len(ma) >= 2 and len(mb) >= 2 and len(ma & mb) / min(len(ma), len(mb)) >= 0.7)


def regle_deux_fois(plans: list, k: int) -> dict:
    """Règle 5 pour le plan k (compté de 1). Trois sources de doublon, lues dans le tableau :
    un élément présent au début que le texte (ou son mouvement) fait entrer ; pour une
    suite, un élément sur la dernière image du plan d'avant qui manque au tableau, part
    hors champ ou change de place ; et, pour tout plan, un mouvement déjà fait au plan
    d'avant (revue du 30/09 : le cerf-volant qui retombe une seconde fois)."""
    plan = plans[k - 1]
    elements = plan.get("elements") or []
    if not elements:
        return resultat(None, "Plan sans tableau des éléments.")
    fautes = []
    noms = [e["nom"] for e in elements]
    entres = entrants(plan.get("image_paroles", ""), noms)
    for e in elements:
        if present_au_debut(e) and (e["nom"] in entres or _ENTREE.search(str(e.get("mouvement", "")))):
            fautes.append("%s est déjà à l'image au début, et le plan le fait entrer" % e["nom"])
        # « A second Lea », « another kite » : le texte demande lui-même un double.
        motif = r"\b(?:a second|another|a copy of|a double of|two|both)\s+" + video_h3._motif_nom(e["nom"])
        if re.search(motif, video_h3._PAROLES.sub(" ", plan.get("image_paroles", "")), re.I):
            fautes.append("le texte demande un second %s" % e["nom"])
    if SANS_NOM in entres:
        fautes.append("le texte fait entrer quelqu'un par un pronom, sans le nommer : nommez qui entre")
    avant = plans[k - 2].get("elements") or [] if k > 1 else []
    precedents = {_cle(e["nom"]): e for e in avant}
    for e in elements:
        p = precedents.get(_cle(e["nom"]))
        if p and _meme_mouvement(p.get("mouvement", ""), e.get("mouvement", "")):
            fautes.append("%s refait au plan %d le mouvement du plan %d (« %s »)"
                          % (e["nom"], k, k - 1, str(e.get("mouvement", ""))[:60]))
    if plan.get("enchainement") == "suite" and k > 1:
        ici = {_cle(e["nom"]): e for e in elements}
        for a in avant:
            fin = str(a.get("fin", ""))
            if _hors_champ(fin):
                continue
            e = ici.get(_cle(a["nom"]))
            if e is None:
                fautes.append("%s est sur la dernière image du plan d'avant mais absent du tableau" % a["nom"])
                continue
            if not present_au_debut(e):
                fautes.append("%s est déjà sur la dernière image du plan d'avant, pas hors champ" % e["nom"])
                continue
            p_fin, p_debut = position(fin), position(e.get("debut", ""))
            if p_fin and p_debut and p_fin != p_debut:
                fautes.append("%s finit le plan d'avant %s, %s et repart %s, %s" % (e["nom"], *p_fin, *p_debut))
    fautes = list(dict.fromkeys(fautes))
    return resultat(not fautes, " ; ".join(fautes) + ("." if fautes else ""))


# Règle 13. Les verbes de marche seulement : un objet (« the ball rolls from the left »)
# garde son trajet, que PHYSIQUE exige.
_MARCHE = (r"(?:walks?|walking|walked|runs?|running|ran|steps?|stepping|stepped|strolls?|strolling|comes?|"
           r"coming|came|enters?|entering|entered|jogs?|jogging|hurries|hurrying|hurried|rushes|rushing|"
           r"rushed|approaches|approaching|approached|moves?|moving|moved)")
_TRAJET = re.compile(
    r"\b%s\b[^.;]*?\bfrom\b[^.;]{0,30}?\b(?:left|right)\b|"
    r"\b(?:pass(?:es|ing|ed)?|%s|cross(?:es|ing|ed)?|cuts?|cutting)\s+(?:right\s+|just\s+|slowly\s+)?"
    r"(?:in front of|behind|past|across)\b|"
    r"\bcross(?:es|ing|ed)?\s+(?:the\s+)?(?:frame|shot|screen)\b" % (_MARCHE, _MARCHE), re.I)


def regle_trajet(plan: dict) -> dict:
    """Règle 13 : le trajet d'un personnage n'est pas écrit, ni dans le texte du plan
    (répliques retirées), ni dans les mouvements du tableau."""
    sources = _phrases(plan.get("image_paroles", "")) + [
        str(e.get("mouvement", "")) for e in plan.get("elements") or [] if isinstance(e, dict)]
    trouves = list(dict.fromkeys(m.group(0).strip() for s in sources for m in _TRAJET.finditer(s)))
    return resultat(not trouves, ("Trajet écrit : « %s ». Dites seulement d'où le personnage part et où il "
                                  "s'arrête." % "», « ".join(trouves)) if trouves else "")


# Règle 14. Le 01/10, plan 1 du film campus, quatre graines sur la 4090 : Tyler dit « Hey,
# are you lost? » et Leila garde les yeux sur la carte. Le texte ne disait rien d'elle
# après la réplique : H3 fait ce qui est écrit, et la laisse dans sa pose.
def _qui_parle(dans: list, avant: str):
    """Le sujet de la phrase qui porte la réplique : le premier personnage nommé depuis le
    dernier point (« Marc walks in, facing Leila, and says: » → Marc) ; sinon le dernier
    nommé avant. None si personne."""
    def premier(nom, mots):
        cles = set(mots_du_nom(nom))
        return min((i for i, m in enumerate(mots) if m in cles), default=None)
    phrase = video_h3._mots(re.split(r"[.;!?]", avant)[-1])
    vus = {nom: premier(nom, phrase) for nom in dans}
    vus = {n: i for n, i in vus.items() if i is not None}
    if vus:
        return min(vus, key=vus.get)
    mots = video_h3._mots(avant)
    derniers = {nom: max((i for i, m in enumerate(mots) if m in set(mots_du_nom(nom))), default=-1)
                for nom in dans}
    qui = max(derniers, key=derniers.get)
    return qui if derniers[qui] >= 0 else None


def regle_ecoute(plan: dict, personnes: set) -> dict:
    """Règle 14 : après chaque réplique, le texte dit ce que fait chaque autre personnage
    du plan (il regarde, se tourne, répond… ou ne réagit pas, si c'est voulu). Celui qui
    parle est le sujet de la phrase qui porte la réplique."""
    texte = str(plan.get("image_paroles", ""))
    repliques = list(video_h3._PAROLES.finditer(texte))
    dans = list(dict.fromkeys(e["nom"] for e in plan.get("elements") or []
                              if isinstance(e, dict) and e.get("nom") and _cle(e["nom"]) in personnes))
    if not repliques or len(dans) < 2:
        return resultat(None, "Pas de réplique adressée à un autre personnage du plan.")
    # Qui a déjà parlé dans le plan est dans l'échange : sa réplique était sa réaction.
    fautes, parle = [], set()
    for m in repliques:
        avant = video_h3._PAROLES.sub(". ", texte[:m.start()])   # une réplique clôt la phrase
        apres = video_h3._PAROLES.sub(" ", texte[m.end():])
        qui = _qui_parle(dans, avant)
        if qui is None:
            return resultat(None, "Qui dit « %s » n'est pas nommé avant la réplique." % m.group(0)[:60])
        muets = [nom for nom in dans if nom != qui and nom not in parle and not nomme_dans(nom, apres)]
        parle.add(qui)
        if muets:
            fautes.append("après %s (%s), rien n'est dit de %s" % (m.group(0)[:60], qui, ", ".join(muets)))
    fautes = list(dict.fromkeys(fautes))
    # Pas « ou qu'il ne réagit pas » : le 01/10, la correction a pris cette sortie
    # (« Leila does not react ») et le défaut restait. Ne pas réagir, écrit, passe la règle.
    return resultat(not fautes, ("Réaction de qui écoute non écrite : " + " ; ".join(fautes) + ". Dites ce "
                                 "qu'il fait juste après la réplique, comme l'histoire le veut (il lève les "
                                 "yeux, se tourne vers celui qui parle, répond…).") if fautes else "")


def regles_texte(plans: list, continuite: dict, fiches: list, langues=None, langue=video_h3.LANGUE_PAROLES,
                 envoyees=None) -> list:
    """Règles 0 à 5, 13 et 14, par le code seul. `fiches` : les fiches du scénario (id, nom, genre, voix) ;
    `envoyees` : pour chaque plan, les fiches dont la voix part avec lui (None : toutes)."""
    personnes = {_cle(f["nom"]) for f in fiches or [] if f.get("genre", "personne") == "personne"}
    problemes = {}
    for p in (continuite or {}).get("problemes") or []:
        problemes.setdefault(p.get("plan"), []).append(p.get("quoi", ""))
    lisible = (continuite or {}).get("ok") is not None
    rapport = []
    for k, plan in enumerate(plans, 1):
        r = {}
        restes = en_francais(plan)
        r[0] = resultat(not restes, ("Reste du français dans " + ", ".join(restes) + ".") if restes else "")
        presents = [e for e in plan.get("elements") or [] if present_au_debut(e)]
        if not plan.get("elements"):
            r[1] = resultat(None, "Plan sans tableau des éléments.")
        else:
            absents = [e["nom"] for e in presents if not nomme_dans(e["nom"], plan.get("image_paroles", ""))]
            r[1] = resultat(not absents, ("Présents au début mais absents du texte : " + ", ".join(absents) + ".")
                            if absents else "")
        if not lisible:
            r[2] = resultat(None, "La relecture n'a pas pu être lue.")
        else:
            r[2] = resultat(not problemes.get(k), " ; ".join(problemes.get(k) or []))
        places = {}
        for e in presents:
            if _cle(e["nom"]) in personnes:
                pos = position(e["debut"])
                if pos:
                    places.setdefault(pos, []).append(e["nom"])
        ensemble = [noms for noms in places.values() if len(noms) > 1]
        if not personnes or not plan.get("elements"):
            r[3] = resultat(None, "Pas de personnage de fiche à placer.")
        else:
            r[3] = resultat(not ensemble, " ; ".join(" et ".join(n) + " partent du même endroit" for n in ensemble))
        r[4] = regle_voix(plan, fiches or [], langues or {}, langue, (envoyees or [None] * len(plans))[k - 1])
        r[5] = regle_deux_fois(plans, k)
        r[13] = regle_trajet(plan)
        r[14] = regle_ecoute(plan, personnes)
        rapport.append(r)
    return rapport


# --- Règles 6 à 8 : l'image de départ, vue par le modèle qui voit -------------------

def attendus_du_depart(plan: dict, fiches: list) -> list:
    """Ce qui doit être sur l'image de départ : les éléments présents au début.
    `fiches` : [(nom, description, genre)] ; la description d'une fiche aide à reconnaître."""
    par_nom = {_cle(n): (d, g) for n, d, g in fiches or []}
    attendus = []
    for e in plan.get("elements") or []:
        if not present_au_debut(e):
            continue
        description, genre = par_nom.get(_cle(e["nom"]), ("", ""))
        attendus.append({"nom": e["nom"], "ou": e["debut"], "description": description,
                         "personne": genre == "personne"})
    return attendus


def absents_du_depart(plan: dict, fiches: list) -> list:
    """Ce qui NE doit PAS être sur l'image de départ : les éléments hors champ au début
    (revue du 30/09 : Marc déjà dessiné alors qu'il devait entrer plus tard, puis entré
    une seconde fois). Même forme qu'attendus_du_depart."""
    par_nom = {_cle(n): (d, g) for n, d, g in fiches or []}
    return [{"nom": e["nom"], "ou": e["debut"], "description": par_nom.get(_cle(e["nom"]), ("", ""))[0],
             "personne": par_nom.get(_cle(e["nom"]), ("", ""))[1] == "personne"}
            for e in plan.get("elements") or [] if not present_au_debut(e)]


def consigne_presence(attendus: list, absents=()) -> str:
    tous = list(attendus) + list(absents)
    liste = " ".join("%d. %s%s, expected: %s." % (i + 1, a["nom"], (" (" + a["description"] + ")") if a["description"]
                                                  else "", a["ou"] if i < len(attendus) else "NOT in the image yet")
                     for i, a in enumerate(tous))
    attendu = ("Items 1 to %d are expected each exactly once; items %d to %d must NOT be visible yet (count "
               "0 when absent). " % (len(attendus), len(attendus) + 1, len(tous))) if absents else \
        "Expected in it, each exactly once. "
    return ("This image is the FIRST FRAME of a video shot. Items: " + liste + " " + attendu +
            "For each numbered item, count how many times it appears in the image (0 if absent, 2 or more if "
            "the same person or the same object is shown twice). Then say whether a speech bubble, a caption, "
            "subtitles or any text was ADDED over the picture (text that belongs to the scene, like a sign or "
            "a book cover, does not count). Answer with JSON only: {\"comptes\": [one integer per item, in "
            "order], \"texte_ajoute\": true or false, \"remarque\": \"in French, what is wrong, empty if "
            "nothing\"}.")


def lire_presence(reponse: str, nombre: int) -> dict:
    """`nombre` : attendus ET absents, dans l'ordre de consigne_presence."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
        comptes = [int(x) for x in d["comptes"]]
    except (ValueError, TypeError, KeyError):
        raise ValueError("Le contrôle de l'image de départ n'a pas pu être lu.")
    if len(comptes) != nombre or not isinstance(d.get("texte_ajoute"), bool):
        raise ValueError("Le contrôle de l'image de départ n'a pas pu être lu.")
    return {"comptes": comptes, "texte_ajoute": d["texte_ajoute"],
            "remarque": " ".join(str(d.get("remarque") or "").split())[:300]}


def regles_depart(attendus: list, presence, ressemblances: dict, absents=()) -> dict:
    """Règles 6 à 8. `presence` : lire_presence(), ou None si illisible ;
    `ressemblances` : {nom : "forte" | "moyenne" | "faible" | None} ;
    `absents` : les éléments hors champ au début, comptés après les attendus."""
    r = {}
    if presence is None:
        r[6] = resultat(None, "Le contrôle de l'image n'a pas pu être lu.")
        r[8] = resultat(None, "Le contrôle de l'image n'a pas pu être lu.")
    else:
        comptes = presence["comptes"]
        faux = ["%s ×%d" % (a["nom"], c) for a, c in zip(attendus, comptes) if c != 1]
        faux += ["%s ×%d (doit être hors champ)" % (a["nom"], c)
                 for a, c in zip(absents, comptes[len(attendus):]) if c != 0]
        r[6] = resultat(not faux, ("Compté : " + ", ".join(faux) + ".") if faux else "")
        r[8] = resultat(not presence["texte_ajoute"], "Texte ou bulle ajouté sur l'image."
                        if presence["texte_ajoute"] else "")
    if not ressemblances:
        r[7] = resultat(None, "Aucun personnage de fiche au début du plan.")
    elif any(v is None for v in ressemblances.values()):
        r[7] = resultat(None, "Une comparaison de visage n'a pas pu être lue.")
    else:
        faibles = [n for n, v in ressemblances.items() if v == "faible"]
        r[7] = resultat(not faibles, ("Ressemblance faible : " + ", ".join(faibles) + ".") if faibles else "")
    return r


def sans_depart(plan: dict) -> dict:
    """Règles 6 à 8 d'un plan sans image de départ : sans objet, et pourquoi."""
    pourquoi = ("Plan « suite » : il part de la dernière image du plan d'avant." if plan.get("enchainement") == "suite"
                else "Pas d'image de départ : le plan part des photos des fiches.")
    return {n: resultat(None, pourquoi) for n in NUMEROS["depart"]}


# --- Règles 10 à 12 : le plan tourné, sur sa planche --------------------------------

def consigne_regles_clip(noms: list, plan: dict) -> str:
    refs = " ".join("Image %d shows %s, a reference picture." % (k + 1, n) for k, n in enumerate(noms))
    fins = " ".join("%s: %s." % (e["nom"], e["fin"]) for e in plan.get("elements") or [] if e.get("fin"))
    regle12 = ("Rule 12: the LAST frames show what the shot must end on: " + fins) if fins else \
        "Rule 12: not applicable (answer ok true)."
    return (refs + " Image %d is a contact sheet of ONE video shot, one frame every 0.5 s, numbered from 1, "
            "read left to right then top to bottom; black cells after the end are empty. Check these rules "
            "one by one. Rule 10: no person and no object is shown twice at the same time in any frame, and "
            "no person or object already in the first frame walks in or appears a second time later. "
            "Rule 11: the characters keep the faces, hair and clothes of their reference pictures in every "
            "frame. " % (len(noms) + 1) + regle12 + " Answer in French, JSON only: {\"regles\": [{\"n\": 10, "
            "\"ok\": true or false, \"pourquoi\": \"what breaks the rule, empty if followed\"}, {\"n\": 11, ...}, "
            "{\"n\": 12, ...}]}.")


def lire_regles_clip(reponse: str) -> dict:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
        vus = {int(x["n"]): x for x in d["regles"]}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {n: resultat(None, "Le contrôle du plan n'a pas pu être lu.") for n in (10, 11, 12)}
    r = {}
    for n in (10, 11, 12):
        x = vus.get(n)
        r[n] = (resultat(x["ok"], "" if x["ok"] else x.get("pourquoi", "")) if x and isinstance(x.get("ok"), bool)
                else resultat(None, "Règle sans réponse lisible."))
    return r


def regle_paroles(paroles) -> dict:
    """Règle 9, depuis l'écoute du juge (video_h3.comparer_paroles)."""
    if not isinstance(paroles, dict) or paroles.get("erreur"):
        return resultat(None, "L'écoute n'a pas pu se faire.")
    if not paroles.get("attendu"):
        # 30/09 : un plan sans réplique où le clip parle quand même est une faute.
        if paroles.get("ok") is False:
            return resultat(False, "Aucune réplique écrite, et le clip parle : « %s »." % paroles.get("entendu", ""))
        if paroles.get("doute"):
            return resultat(None, "Aucune réplique écrite ; voix possible : à vérifier à l'oreille.")
        return resultat(None, "Pas de réplique dans ce plan.")
    if paroles.get("ok") is None:
        return resultat(None, "Écoute douteuse : à vérifier à l'oreille.")
    return resultat(bool(paroles["ok"]), "" if paroles["ok"] else "Entendu : « %s »." % paroles.get("entendu", ""))


def en_liste(r: dict) -> list:
    """{n: résultat} → [{n, regle, ok, pourquoi}], dans l'ordre des numéros."""
    textes = {n: t for n, _, t in REGLES}
    return [dict({"n": n, "regle": textes[n]}, **r[n]) for n in sorted(r)]


def non_suivies(rapport: list, numeros=None) -> list:
    """[(plan, n, pourquoi)] des règles non suivies (False), dans `numeros` si donné."""
    return [(p["plan"], x["n"], x["pourquoi"]) for p in rapport for x in p["regles"]
            if x["ok"] is False and (numeros is None or x["n"] in numeros)]
