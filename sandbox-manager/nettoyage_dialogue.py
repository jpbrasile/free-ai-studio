"""Retire du dialogue rendu les bouts de parole que personne n'a demandes.

CE QU'ON REPARE, ET POURQUOI UNE DECOUPE EST LEGITIME ICI.

FireRedTTS-2 insere, en fin de replique, de la parole qui n'etait pas dans le
texte -- dont de l'ANGLAIS. Releve le 17/09/2026 sur un rendu de 147,5 s :
<< I see. Enthusie, be impressed. >> a 3,9 s, << What a >> a 2:04,8, plus
<< tch. >>, << Voooh >>, << sans. >>. Cinq intrusions, une toutes les ~30 s,
sur un fond de 96,5 % de mots corrects (465/482). C'est du materiel AJOUTE,
pas de la parole abimee : l'enlever ne retire rien de ce qui etait voulu. C'est
exactement ce qui separe ce cas d'une coupe a l'aveugle.

POURQUOI AUCUNE MESURE DE SIGNAL NE PEUT LES TROUVER.

Mesure du meme jour, sur l'intrusion de 3,9 s : voisee, clarte 0,92, platitude
spectrale 0,003, a plein niveau -- soit PLUS periodique qu'un temoin de parole
franche prise sur le meme fichier. C'est de la parole bien formee, seulement
pas la bonne. Derivees, energie, ecretage, bruit dans les pauses : quatre
detecteurs acoustiques ont ete ecrits et jetes, et deux de leurs verdicts ont
du etre retires. Ne pas y revenir, l'impasse est deja payee.

CE QUI MARCHE : la transcription ALIGNEE SUR LE TEXTE ENVOYE. Whisper seul ne
vaudrait rien -- entraine a produire du langage bien forme, il rend un charabia
par le mot reel le plus proche, et SOUS-ESTIME donc : ce qu'on trouve est un
plancher, pas un compte. C'est la verite terrain qui le transforme d'un juge en
un rapporteur : on ne lui demande pas de juger, seulement de rapporter, et
c'est l'ecart au texte connu qui accuse.

CE MODULE NE TRANSCRIT PAS. Il recoit les mots horodates (le routeur les rend,
/v1/audio/alignement) et n'a besoin que de la bibliotheque standard : wave et
array. Aucune dependance nouvelle -- c'est la meme regle qui a fait remplacer
torchaudio.save() par wave dans le script du travail, et tests/test_dialogue.py
l'exige.
"""

from __future__ import annotations

import array
import difflib
import os
import re
import sys
import unicodedata
import wave

# --- Reglages de la coupe -----------------------------------------------------
# Les horodatages de Whisper sont justes a +/-150 ms environ : couper dessus
# mangerait des syllabes. Chaque borne est RECALEE sur le minimum d'energie
# local, puis bornee pour ne jamais mordre le mot voisin.
MARGE_RECALAGE_S = 0.200
GARDE_S = 0.030
# Une soudure franche fait un clic audible : fondu enchaine de 10 ms.
FONDU_S = 0.010
# Sous ce seuil, ce qui reste apres recalage ne vaut pas une coupe.
COUPE_MIN_S = 0.030
# Finesse de la recherche du creux.
TRAME_S = 0.005


def normaliser(mot: str) -> str:
    """Minuscule, sans accent, sans ponctuation : on compare des SONS.

    Whisper ecrit << week-end >> ou << weekend >> indifferemment ; la graphie
    n'est pas la question.
    """
    mot = unicodedata.normalize("NFKD", mot.lower())
    mot = "".join(c for c in mot if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", mot)


def en_mots(texte: str) -> list:
    """Decoupe en mots normalises. L'apostrophe separe : elle porte une elision."""
    return [m for m in (normaliser(x) for x in re.split(r"[\s'’]+", texte)) if m]


# JAMAIS DE CLE D'UNE SEULE LETTRE. En francais elle se confond avec une
# elision : s'etalent, m'a dit, l'eau, d'accord, j'ai, c'est, n'importe.
# Cas reel, deuxieme passe du 17/09 : la cle 's' -> 'secondes' a transforme le
# << s' >> de << elles s'etalent >> en mot etranger, et une coupe de 125 ms
# entamait le mot. La cle 'h' tendait le meme piege. Une unite ambigue coute
# bien plus qu'elle ne rapporte : on ne garde que ce qui ne peut PAS etre un
# mot francais.
UNITES = {
    "cm": "centimetres",
    "mm": "millimetres",
    "km": "kilometres",
    "kg": "kilos",
    "min": "minutes",
}

_UNITS = ("zero", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit",
          "neuf", "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize")
_DIZAINES = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}


def nombre_en_mots(n: int):
    """<< 10 >> -> << dix >>. Sans ca, la reparation COUPE UN MOT LEGITIME.

    Whisper ecrit << 10 cm >> la ou le texte disait << dix centimetres >> : le
    SON est identique, seule la convention d'ecriture differe. L'alignement au
    caractere declare alors << 10 >> etranger, puisque les lettres << 10 >> ne
    figurent pas dans << dixcentimetres >>.

    C'est exactement ce qui s'est produit a la premiere passe, le 17/09 :
    << 10 >>, << 40 >> et << 15 >> ont ete retires alors qu'ils etaient bel et
    bien prononces, soit environ 1,3 s de parole voulue supprimee. Le fichier
    n'a pas ete livre. L'avertissement avait ete ecrit en clair une heure plus
    tot sans etre encode : il l'est ici.
    """
    if n < 0 or n > 100:
        return None
    if n == 100:
        return "cent"
    if n < 17:
        return _UNITS[n]
    if n < 20:
        return "dix" + _UNITS[n - 10]
    if n < 70:
        dix, reste = (n // 10) * 10, n % 10
        if reste == 0:
            return _DIZAINES[dix]
        return _DIZAINES[dix] + ("etun" if reste == 1 else _UNITS[reste])
    if n < 80:
        reste = n - 60
        return "soixante" + ("etonze" if reste == 11 else _UNITS[reste])
    reste = n - 80
    if reste == 0:
        return "quatrevingts"
    if reste < 17:
        return "quatrevingt" + _UNITS[reste]
    return "quatrevingtdix" + _UNITS[reste - 10]


def convertir(norme: str) -> str:
    """Ramene une graphie de Whisper a la forme que le texte source aurait."""
    if norme.isdigit():
        mot = nombre_en_mots(int(norme))
        if mot:
            return mot
    return UNITES.get(norme, norme)


def intrus_dans_remplacement(attendus, entendus) -> list:
    """Dans un groupe de remplacement, quels mots ENTENDUS sont etrangers ?

    On aligne au CARACTERE, pas au mot : << week >> et << end >> se retrouvent
    tous deux dans << weekend >>, alors qu'un alignement au mot les declarerait
    fautifs l'un et l'autre. Un mot entendu dont moins de la moitie des lettres
    trouve place dans le texte attendu est un intrus.
    """
    a = "".join(attendus)
    bornes, b = [], ""
    for mot in entendus:
        bornes.append((len(b), len(b) + len(mot)))
        b += mot
    couverts = [False] * len(b)
    for bloc in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for i in range(bloc.b, bloc.b + bloc.size):
            couverts[i] = True
    intrus = []
    for i, (debut, fin) in enumerate(bornes):
        if fin > debut and sum(couverts[debut:fin]) < 0.5 * (fin - debut):
            intrus.append(i)
    return intrus


def _grouper_consecutifs(indices) -> list:
    groupes = []
    for i in indices:
        if groupes and i == groupes[-1][-1] + 1:
            groupes[-1].append(i)
        else:
            groupes.append([i])
    return groupes


# --- Lecture et ecriture du WAV, sans rien installer ---------------------------

def lire_wav(chemin: str):
    """Rend (echantillons, taux, canaux). Les echantillons sont ENTRELACES.

    wave ecrit et lit du petit-boutiste ; array('h') est dans l'ordre de la
    machine. Sur une machine gros-boutiste, sauter le byteswap donnerait du
    bruit blanc a la place de la parole -- personne ne le verrait sur x86, et
    ca tomberait ailleurs.
    """
    with wave.open(chemin, "rb") as f:
        canaux, largeur, taux = f.getnchannels(), f.getsampwidth(), f.getframerate()
        brut = f.readframes(f.getnframes())
    if largeur != 2:
        raise ValueError("Ce nettoyage ne lit que du PCM 16 bits (recu : %d octets "
                         "par echantillon)." % largeur)
    x = array.array("h")
    x.frombytes(brut)
    if sys.byteorder == "big":
        x.byteswap()
    return x, taux, canaux


def ecrire_wav(chemin: str, x: array.array, taux: int, canaux: int) -> int:
    donnees = x
    if sys.byteorder == "big":
        donnees = array.array("h", x)
        donnees.byteswap()
    with wave.open(chemin, "wb") as f:
        f.setnchannels(canaux)
        f.setsampwidth(2)
        f.setframerate(taux)
        f.writeframes(donnees.tobytes())
    return os.path.getsize(chemin)


def _rms_trame(x, canaux, debut_trame, fin_trame) -> float:
    """Energie moyenne sur une plage de TRAMES (tous canaux confondus)."""
    a, b = debut_trame * canaux, fin_trame * canaux
    if b <= a:
        return 0.0
    total = 0
    for i in range(a, b):
        v = x[i]
        total += v * v
    return (total / float(b - a)) ** 0.5


def creux_le_plus_proche(x, taux, canaux, t, marge=MARGE_RECALAGE_S) -> float:
    """Recale une borne sur le minimum d'energie local.

    Couper la ou le signal est deja faible ne s'entend pas ; couper en pleine
    voyelle s'entend. C'est la difference entre une reparation et un degat.
    """
    trames = len(x) // canaux
    pas = max(1, int(TRAME_S * taux))
    a = max(0, int((t - marge) * taux))
    b = min(trames, int((t + marge) * taux))
    if b - a < 2 * pas:
        return t
    meilleur, meilleure_energie = a, None
    i = a
    while i + pas <= b:
        energie = _rms_trame(x, canaux, i, i + pas)
        if meilleure_energie is None or energie < meilleure_energie:
            meilleure_energie, meilleur = energie, i
        i += pas
    return meilleur / float(taux)


def couper(x, taux, canaux, spans):
    """Retire les spans (en secondes) et soude au fondu enchaine.

    Le fondu evite le clic de la soudure franche. Il se fait canal par canal :
    les echantillons sont entrelaces, un fondu applique a plat melangerait les
    canaux entre eux.
    """
    trames = len(x) // canaux
    fondu = max(1, int(FONDU_S * taux))
    morceaux, position = [], 0
    for debut_s, fin_s in spans:
        a = max(0, min(trames, int(debut_s * taux)))
        b = max(0, min(trames, int(fin_s * taux)))
        if a <= position or b <= a:
            continue
        morceaux.append((position, a))
        position = b
    morceaux.append((position, trames))
    morceaux = [(a, b) for a, b in morceaux if b > a]
    if not morceaux:
        return array.array("h")

    sortie = array.array("h", x[morceaux[0][0] * canaux:morceaux[0][1] * canaux])
    for a, b in morceaux[1:]:
        suivant = x[a * canaux:b * canaux]
        n = min(fondu, len(sortie) // canaux, (b - a))
        if n <= 0:
            sortie.extend(suivant)
            continue
        base = len(sortie) - n * canaux
        for k in range(n):
            montee = (k + 1) / float(n + 1)
            for c in range(canaux):
                i = base + k * canaux + c
                melange = sortie[i] * (1.0 - montee) + suivant[k * canaux + c] * montee
                valeur = int(round(melange))
                sortie[i] = -32768 if valeur < -32768 else (32767 if valeur > 32767 else valeur)
        sortie.extend(suivant[n * canaux:])
    return sortie


# --- Le reperage --------------------------------------------------------------

def reperer(repliques, mots, x, taux, canaux) -> list:
    """Compare le texte ENVOYE a ce qui a ete ENTENDU et rend les spans a couper.

    `repliques` : les repliques telles qu'elles sont parties (balises comprises).
    `mots`      : [{"mot", "debut", "fin"}, ...] rendus par le routeur.
    """
    attendus = []
    for replique in repliques:
        marque = re.match(r"^\[S\d+\](.*)$", str(replique), flags=re.S)
        attendus.extend(en_mots((marque.group(1) if marque else str(replique)).strip()))

    entendus = [convertir(normaliser(m.get("mot", ""))) for m in mots]

    candidats = []
    for code, a1, a2, b1, b2 in difflib.SequenceMatcher(
            a=attendus, b=entendus, autojunk=False).get_opcodes():
        if code == "insert":
            candidats.append((b1, b2, a1))
        elif code == "replace":
            for groupe in _grouper_consecutifs(intrus_dans_remplacement(
                    attendus[a1:a2], entendus[b1:b2])):
                candidats.append((b1 + groupe[0], b1 + groupe[-1] + 1, a1))

    spans, details = [], []
    for b1, b2, a1 in sorted(candidats):
        texte = " ".join(str(mots[i].get("mot", "")) for i in range(b1, b2))

        # GARDE DE CONTEXTE. Un mot deja present dans le texte attendu juste
        # autour n'est pas un intrus : c'est un desalignement. Couper la
        # retirerait de la parole voulue. Cas reel, premiere passe du 17/09 :
        # << de >> signale a 0:28.69 alors que le texte disait << pleine de
        # vers >>.
        voisinage = set(attendus[max(0, a1 - 6):a1 + 6])
        if all(entendus[i] in voisinage for i in range(b1, b2)):
            # Ces motifs sont LUS PAR L'UTILISATEUR depuis que la page affiche
            # celui du rapport au lieu d'en inventer un : ils s'ecrivent donc en
            # francais accentue, a la difference des commentaires de ce fichier.
            details.append({"texte": texte, "garde": "déjà dans le contexte attendu"})
            continue

        # GARDE DE LA PONCTUATION. Whisper rend parfois un << mot >> qui n'est
        # QUE de la ponctuation -- un << ? >> seul, horodate comme le reste.
        # normaliser() le vide de ses caracteres, il ne peut donc s'apparier a
        # rien et l'alignement le declare intrus. Ce n'est pas de la parole :
        # rien a couper, et rien a expliquer par une elision.
        # Cas reel, rendu Kaggle du 17/09 : 8 passages epargnes, TOUS des
        # << ? >>. Ils tombaient dans la garde des fragments ci-dessous, qui
        # sauvait le son -- bon resultat -- mais les faisait annoncer comme des
        # elisions. Le fichier etait juste, le motif affiche etait faux.
        # Ces jetons ne sont PAS retires de `entendus` : leurs indices sont ceux
        # de `mots`, et decaler l'un sans l'autre deplacerait les horodatages.
        if all(not entendus[i] for i in range(b1, b2)):
            details.append({"texte": texte, "garde": "ponctuation, pas de la parole"})
            continue

        # GARDE DES FRAGMENTS, independante des precedentes et VOLONTAIREMENT
        # redondante. Un intrus reduit a une seule lettre est une elision mal
        # decoupee (s', m', l', d', j', c', n', t'), jamais un mot etranger qui
        # vaille une coupe. Si une table fautive etait reintroduite un jour,
        # cette garde tiendrait quand meme -- c'est sa raison d'etre. Elle
        # rattrape aussi la ponctuation, que la garde precedente nomme mieux.
        if sum(len(entendus[i]) for i in range(b1, b2)) <= 1:
            details.append({"texte": texte, "garde": "fragment d'une seule lettre"})
            continue

        t0 = float(mots[b1].get("debut", 0.0))
        t1 = float(mots[b2 - 1].get("fin", 0.0))
        c0 = creux_le_plus_proche(x, taux, canaux, t0)
        c1 = creux_le_plus_proche(x, taux, canaux, t1)
        # Le recalage ne doit jamais deborder sur le mot voisin.
        c0 = min(max(c0, t0 - MARGE_RECALAGE_S), t0 + GARDE_S)
        c1 = max(min(c1, t1 + MARGE_RECALAGE_S), t1 - GARDE_S)
        if c1 - c0 < COUPE_MIN_S:
            details.append({"texte": texte, "garde": "trop court après recalage"})
            continue
        spans.append((c0, c1))
        details.append({"texte": texte, "debut": round(c0, 3), "fin": round(c1, 3),
                        "millisecondes": int(round(1000 * (c1 - c0)))})

    if not spans:
        return [], details

    # Fusionne ce qui se chevauche apres recalage.
    fusion = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= fusion[-1][1]:
            fusion[-1][1] = max(fusion[-1][1], b)
        else:
            fusion.append([a, b])
    return [tuple(s) for s in fusion], details


def nettoyer(chemin_source: str, chemin_sortie: str, repliques, mots) -> dict:
    """Ecrit a cote un dialogue sans les intrusions. L'original n'est PAS touche.

    Rend un rapport : ce qui a ete coupe, ce qui a ete garde, et pourquoi. Le
    rapport compte autant que le fichier -- une coupe silencieuse serait
    invendable, l'utilisateur doit pouvoir savoir ce qui a disparu.
    """
    x, taux, canaux = lire_wav(chemin_source)
    duree_avant = (len(x) // canaux) / float(taux)
    spans, details = reperer(repliques, mots, x, taux, canaux)
    rapport = {
        "coupes": len(spans),
        "duree_avant_s": round(duree_avant, 2),
        "duree_apres_s": round(duree_avant, 2),
        "secondes_retirees": 0.0,
        "details": details,
        "echantillonnage": taux,
        "canaux": canaux,
        # Dit sans detour, parce que c'est vrai et que ca borne la promesse.
        "reserve": "la transcription sous-estime : ce qui est retire est un "
                   "plancher, pas un compte",
    }
    if not spans:
        return rapport
    y = couper(x, taux, canaux, spans)
    retire = sum(b - a for a, b in spans)
    rapport["octets"] = ecrire_wav(chemin_sortie, y, taux, canaux)
    rapport["duree_apres_s"] = round((len(y) // canaux) / float(taux), 2)
    rapport["secondes_retirees"] = round(retire, 2)
    return rapport
