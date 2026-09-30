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
)
NUMEROS = {etape: [n for n, e, _ in REGLES if e == etape] for etape in ("texte", "depart", "clip")}
# Les règles qui arrêtent le tournage (avant tout sou) : texte et image de départ.
AVANT_TOURNAGE = NUMEROS["texte"] + NUMEROS["depart"]

# « the », « le », « l' »… : un nom se retrouve dans le texte sans son article.
_ARTICLES = {"the", "a", "an", "le", "la", "les", "l", "un", "une", "des", "du", "de"}
_PROFONDEURS = (("foreground", "foreground"), ("background", "background"), ("midground", "middle"),
                ("middle ground", "middle"), ("middle distance", "middle"))
_COTES = (("left", "left"), ("right", "right"), ("centre", "centre"), ("center", "centre"), ("middle", "centre"))


def resultat(ok, pourquoi: str = "") -> dict:
    return {"ok": ok, "pourquoi": " ".join(str(pourquoi or "").split())[:300]}


def present_au_debut(e: dict) -> bool:
    debut = video_h3._norme_replique(e.get("debut", ""))
    if debut in {video_h3._norme_replique(x) for x in video_h3._SANS_DEPART}:
        return False
    return not any(debut.startswith(video_h3._norme_replique(h)) for h in video_h3.HORS_CHAMP)


def mots_du_nom(nom: str) -> list:
    return [m for m in video_h3._mots(nom) if m not in _ARTICLES]


def nomme_dans(nom: str, texte: str) -> bool:
    """Tous les mots du nom (sans article) sont dans le texte."""
    mots, dans = mots_du_nom(nom), set(video_h3._mots(texte))
    return bool(mots) and all(m in dans for m in mots)


def position(debut: str):
    """(profondeur, côté) lus au début d'un élément ; None s'il en manque un."""
    t = " ".join(video_h3._mots(debut))
    profondeur = next((v for k, v in _PROFONDEURS if re.search(r"\b%s\b" % k, t)), None)
    # Le côté se lit après la profondeur : « middle ground » n'est pas un côté.
    reste = re.sub(r"\bmiddle (ground|distance)\b", " ", t)
    cote = next((v for k, v in _COTES if re.search(r"\b%s\b" % k, reste)), None)
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

def qui_parle(texte: str, noms: list) -> list:
    """[(réplique, rang du nom qui la dit, ou None)] : la règle de attribuer_repliques
    (le PREMIER nom de la phrase de la réplique, sinon le dernier nommé avant), sans
    le repli « le premier personnage » : ici, un locuteur inconnu est une faute."""
    texte = str(texte or "")
    vues = list(video_h3._PAROLES.finditer(texte))
    dedans = [(m.start(), m.end()) for m in vues]
    places = sorted((m.start(), k) for k, nom in enumerate(noms) if str(nom).strip()
                    for m in re.finditer(video_h3._motif_nom(nom), texte, re.I)
                    if not any(a <= m.start() < b for a, b in dedans))
    sortie, fin_precedente = [], 0
    for m in vues:
        avant = texte[fin_precedente:m.start()]
        debut_phrase = fin_precedente + max(avant.rfind(c) for c in ".!?;\n") + 1
        dans_la_phrase = [k for a, k in places if debut_phrase <= a < m.start()]
        plus_tot = [k for a, k in places if a < debut_phrase]
        k = dans_la_phrase[0] if dans_la_phrase else plus_tot[-1] if plus_tot else None
        sortie.append((next(g for g in m.groups() if g).strip(), k))
        fin_precedente = m.end()
    return sortie


def regle_voix(plan: dict, fiches: list, langues: dict, langue: str) -> dict:
    """Règle 4. `fiches` : les fiches du scénario (dicts du Studio : id, nom, genre, voix) ;
    `langues` : {fiche : langue de ses répliques} ; `langue` : celle par défaut.
    Décision du propriétaire, 30/09 : « all speaker is created with a profile before
    hand including its voice in the appropriate language : to be hard coded in studio »."""
    texte = plan.get("image_paroles", "") + " " + plan.get("ambiance", "")
    noms = [f["nom"] for f in fiches] + [e["nom"] for e in plan.get("elements") or []]
    dites = qui_parle(texte, noms)
    if not dites:
        return resultat(None, "Pas de réplique dans ce plan.")
    fautes, locuteurs = [], []
    for replique, k in dites:
        court = "« %s »" % (replique[:40] + ("…" if len(replique) > 40 else ""))
        if k is None:
            fautes.append(court + " : personne n'est nommé pour la dire")
            continue
        if k >= len(fiches):
            fautes.append(court + " : %s n'a pas de fiche" % noms[k])
            continue
        f = fiches[k]
        if f.get("genre", "personne") != "personne":
            fautes.append(court + " : « %s » est un objet, il ne parle pas" % f["nom"])
            continue
        voulue, _ = video_h3.langue_de_replique(replique, (langues or {}).get(f["id"]) or langue)
        voix = f.get("voix") or {}
        if not voix:
            fautes.append(court + " : la fiche de %s n'a pas de voix" % f["nom"])
        elif not voix.get("langue"):
            fautes.append(court + " : la langue de la voix de %s n'est pas notée (reposez la voix)" % f["nom"])
        elif voix["langue"] != voulue:
            fautes.append(court + " : %s parle %s, sa voix est en %s" % (
                f["nom"], video_h3.LANGUES_PAROLES.get(voulue, voulue),
                video_h3.LANGUES_PAROLES.get(voix["langue"], voix["langue"])))
        if f["id"] not in locuteurs:
            locuteurs.append(f["id"])
    # Un plan « suite » part de la dernière image, sans fiche : aucune voix ne part avec
    # lui (audit du 30/09 : « Ils volent ! » dit par un Marc inventé, d'un timbre inconnu).
    if plan.get("enchainement") == "suite":
        fautes.append("plan « suite » : il part sans fiche, donc sans voix ; faites-en une coupe "
                      "ou déplacez la réplique")
    elif len(locuteurs) > video_h3.VOIX_PAR_PLAN:
        fautes.append("%d personnages parlent, %d voix au plus partent avec un plan" % (
            len(locuteurs), video_h3.VOIX_PAR_PLAN))
    return resultat(not fautes, " ; ".join(fautes) + ("." if fautes else ""))


# --- Règle 5 : rien n'est créé deux fois --------------------------------------------

# Ce qui fait ENTRER un élément dans le cadre : dit d'un élément déjà là, le modèle
# le dessine une seconde fois (librairie, 30/09 : Léa « enters » alors que la
# première image la montrait déjà ; deux Léa sur l'image de départ).
_ENTREE = re.compile(r"\b(enters?|entering|entered|walks? in|walking in|comes? in|coming in|steps? in|"
                     r"steps? into|appears?|appearing|comes? into (?:view|frame|the frame)|"
                     r"into (?:view|frame|the frame)|pops? up|emerges?)\b", re.I)


def _phrases(texte: str) -> list:
    """Les phrases du texte, répliques retirées (un mot d'une réplique n'est pas une action)."""
    return [p for p in re.split(r"[.;!?\n]", video_h3._PAROLES.sub(" ", str(texte or ""))) if p.strip()]


def _entre(nom: str, texte: str) -> bool:
    return any(nomme_dans(nom, p) and _ENTREE.search(p) for p in _phrases(texte))


def regle_deux_fois(plans: list, k: int) -> dict:
    """Règle 5 pour le plan k (compté de 1). Deux sources de doublon, lues dans le tableau :
    un élément présent au début que le texte (ou son mouvement) fait entrer ; et, pour une
    suite, un élément sur la dernière image du plan d'avant qui manque au tableau, part
    hors champ, change de place, ou entre."""
    plan = plans[k - 1]
    elements = plan.get("elements") or []
    if not elements:
        return resultat(None, "Plan sans tableau des éléments.")
    fautes = []
    for e in elements:
        if present_au_debut(e) and (_entre(e["nom"], plan.get("image_paroles", ""))
                                     or _ENTREE.search(str(e.get("mouvement", "")))):
            fautes.append("%s est déjà à l'image au début, et le plan le fait entrer" % e["nom"])
    if plan.get("enchainement") == "suite" and k > 1:
        ici = {_cle(e["nom"]): e for e in elements}
        for avant in plans[k - 2].get("elements") or []:
            fin = str(avant.get("fin", ""))
            if _hors_champ(fin):
                continue
            e = ici.get(_cle(avant["nom"]))
            if e is None:
                fautes.append("%s est sur la dernière image du plan d'avant mais absent du tableau" % avant["nom"])
                continue
            if not present_au_debut(e):
                fautes.append("%s est déjà sur la dernière image du plan d'avant, pas hors champ" % e["nom"])
                continue
            p_fin, p_debut = position(fin), position(e.get("debut", ""))
            if p_fin and p_debut and p_fin != p_debut:
                fautes.append("%s finit le plan d'avant %s, %s et repart %s, %s" % (e["nom"], *p_fin, *p_debut))
    fautes = list(dict.fromkeys(fautes))
    return resultat(not fautes, " ; ".join(fautes) + ("." if fautes else ""))


def regles_texte(plans: list, continuite: dict, fiches: list, langues=None, langue=video_h3.LANGUE_PAROLES) -> list:
    """Règles 0 à 5, par le code seul. `fiches` : les fiches du scénario (id, nom, genre, voix)."""
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
        r[4] = regle_voix(plan, fiches or [], langues or {}, langue)
        r[5] = regle_deux_fois(plans, k)
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


def consigne_presence(attendus: list) -> str:
    liste = " ".join("%d. %s%s, expected: %s." % (i + 1, a["nom"], (" (" + a["description"] + ")") if a["description"]
                                                  else "", a["ou"]) for i, a in enumerate(attendus))
    return ("This image is the FIRST FRAME of a video shot. Expected in it, each exactly once: " + liste + " "
            "For each numbered item, count how many times it appears in the image (0 if absent, 2 or more if "
            "the same person or the same object is shown twice). Then say whether a speech bubble, a caption, "
            "subtitles or any text was ADDED over the picture (text that belongs to the scene, like a sign or "
            "a book cover, does not count). Answer with JSON only: {\"comptes\": [one integer per item, in "
            "order], \"texte_ajoute\": true or false, \"remarque\": \"in French, what is wrong, empty if "
            "nothing\"}.")


def lire_presence(reponse: str, nombre: int) -> dict:
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


def regles_depart(attendus: list, presence, ressemblances: dict) -> dict:
    """Règles 6 à 8. `presence` : lire_presence(), ou None si illisible ;
    `ressemblances` : {nom : "forte" | "moyenne" | "faible" | None}."""
    r = {}
    if presence is None:
        r[6] = resultat(None, "Le contrôle de l'image n'a pas pu être lu.")
        r[8] = resultat(None, "Le contrôle de l'image n'a pas pu être lu.")
    else:
        faux = ["%s ×%d" % (a["nom"], c) for a, c in zip(attendus, presence["comptes"]) if c != 1]
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
