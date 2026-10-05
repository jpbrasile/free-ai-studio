"""Le fond continu d'un lieu sous les plans d'un film (05/10/2026, jalon 0 bis, PLAN 21).

Chaque clip H3 réinvente son ambiance : au montage, le fond change à chaque coupe, même
quand le lieu ne change pas. La pratique du cinéma est une nappe par lieu, posée sous les
coupes (ScreenWeaver, StudioBinder, relus le 05/10) ; la séparation dialogue + réattribution
au fond de ce qui fuit est celle de Fraunhofer (« Better Together »).

Ici, numpy seul (torch reste dans app.py) :
- `voix` = DeepFilterNet3(film), calculée par le service ; `reste` = film − voix ;
- le motif d'un lieu = le plus long passage sans voix de son premier clip qui en a un ;
- sortie = voix + motif bouclé sur tous les clips du lieu + reste rouvert par une porte,
  pour rendre ce que DeepFilterNet range hors de la voix : fins de phrase, souffles, pas
  (propriétaire, 05/10 : « le remixing coupe la fin des séquences voix »).

Essai hors Studio sur « Leila » 1-8 (05/10) : « c'est parfait, compatible de la respiration
de Leila ». Les réglages marqués PROVISOIRE attendent la validation du propriétaire.
"""
from __future__ import annotations

import numpy as np

TRAME_S = 0.05
# Voix de DeepFilterNet par trames de 50 ms, film « Leila » 1-8 (05/10) : silences à −94 dB
# (médiane), répliques à −22 dB ; entre −60 et −45 dB, 3 % des trames seulement.
VOIX_PRESENTE_DB = -60.0
# Le motif reste à distance d'une réplique : sinon un fantôme de la voix y passe (essai du
# 05/10 : −29 dB au lieu de −50 autour, diaphonie entendue par le propriétaire).
MARGE_VOIX_S = 0.5
MOTIF_MIN_S = 2.0   # au moins deux fondus de boucle
MOTIF_MAX_S = 8.0
MUET_DB = -80.0     # sous ce niveau, un passage est un silence numérique, pas un fond
FONDU_S = 1.0       # fondu enchaîné à puissance constante entre deux tours de boucle
# PROVISOIRE (05/10, à valider à l'écoute) : la porte s'ouvre quand le reste dépasse de
# PORTE_AU_DESSUS_DB la médiane du motif. Essai « Leila » : médiane −51,7 dB, porte réglée
# à −45 dB et jugée bonne, soit +6,7.
PORTE_AU_DESSUS_DB = 6.0
PORTE_OUVRE_S = 0.010
PORTE_FERME_S = 0.300


def niveaux(x: np.ndarray, sr: int) -> np.ndarray:
    """Le niveau (dB) de chaque trame de TRAME_S, canaux moyennés."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    p = max(1, int(sr * TRAME_S))
    n = len(m) // p
    if n == 0:
        return np.zeros(0)
    t = m[:n * p].reshape(n, p)
    return 20 * np.log10(np.sqrt((t ** 2).mean(axis=1)) + 1e-12)


def passage_sans_voix(voix: np.ndarray, sr: int, debut: int, fin: int):
    """Le plus long passage (échantillons, bornes absolues) de [debut, fin) sans voix, à
    MARGE_VOIX_S de toute réplique, ramené à MOTIF_MAX_S ; None sous MOTIF_MIN_S."""
    p = max(1, int(sr * TRAME_S))
    parle = niveaux(voix[debut:fin], sr) > VOIX_PRESENTE_DB
    marge = int(round(MARGE_VOIX_S / TRAME_S))
    libre = ~parle
    for k in np.flatnonzero(parle):
        libre[max(0, k - marge):k + marge + 1] = False
    meilleur, a = None, None
    for k, v in enumerate(list(libre) + [False]):
        if v and a is None:
            a = k
        elif not v and a is not None:
            if meilleur is None or k - a > meilleur[1] - meilleur[0]:
                meilleur = (a, k)
            a = None
    if meilleur is None or (meilleur[1] - meilleur[0]) * TRAME_S < MOTIF_MIN_S:
        return None
    a, b = meilleur
    b = min(b, a + int(round(MOTIF_MAX_S / TRAME_S)))
    return debut + a * p, debut + b * p


def boucler(motif: np.ndarray, n: int, sr: int) -> np.ndarray:
    """Le motif répété sur n échantillons, chaque tour fondu dans le suivant."""
    f = min(int(FONDU_S * sr), len(motif) // 2)
    t = np.linspace(0, np.pi / 2, f, dtype=np.float32)[:, None]
    entree, sortie = np.sin(t), np.cos(t)
    out = motif.copy()
    while len(out) < n:
        out = np.concatenate([out[:-f], out[-f:] * sortie + motif[:f] * entree, motif[f:]])
    return out[:n]


def porte(reste: np.ndarray, sr: int, seuil_db: float) -> np.ndarray:
    """Gain (0..1, une colonne) ouvert là où le reste dépasse seuil_db sur une trame ;
    ouverture PORTE_OUVRE_S, fermeture PORTE_FERME_S, calculées à la milliseconde."""
    n = len(reste)
    ouvert = (niveaux(reste, sr) > seuil_db).astype(np.float32)
    ms = int(np.ceil(n / sr * 1000))
    cible = ouvert[np.minimum((np.arange(ms) / 1000 / TRAME_S).astype(int), max(len(ouvert) - 1, 0))] \
        if len(ouvert) else np.zeros(ms, np.float32)
    a, r = 1 - np.exp(-0.001 / PORTE_OUVRE_S), 1 - np.exp(-0.001 / PORTE_FERME_S)
    g, v = np.empty(ms, np.float32), 0.0
    for i, c in enumerate(cible):
        v += (a if c > v else r) * (c - v)
        g[i] = v
    return np.interp(np.arange(n) / sr * 1000, np.arange(ms), g).astype(np.float32)[:, None]


def remixer(film: np.ndarray, voix: np.ndarray, sr: int, bornes_s: list, lieux: list) -> tuple:
    """Le son du film (n, canaux) avec un fond continu par lieu, et le rapport.

    `bornes_s` : la fin de chaque clip (s) ; `lieux` : l'étiquette du lieu de chaque clip.
    Les clips d'un lieu sans passage sans voix gardent leur son, et le rapport le dit."""
    if len(bornes_s) != len(lieux) or not bornes_s:
        raise ValueError("Une borne et un lieu par clip.")
    n = min(len(film), len(voix))
    film, voix = film[:n], voix[:n]
    fins = [min(n, int(round(b * sr))) for b in bornes_s]
    plages = list(zip([0] + fins[:-1], fins))
    if any(b <= a for a, b in plages):
        raise ValueError("Les bornes des clips doivent croître.")
    reste = film - voix
    sortie = film.copy()
    rapport = {"lieux": []}
    for lieu in dict.fromkeys(lieux):
        siens = [k for k, x in enumerate(lieux) if x == lieu]
        motif = None
        for k in siens:
            motif = passage_sans_voix(voix, sr, *plages[k])
            # Un clip au son coupé au montage (paroles non écrites, 04/10) est muet partout :
            # son silence n'est pas le fond du lieu.
            if motif and np.median(niveaux(reste[motif[0]:motif[1]], sr)) < MUET_DB:
                motif = None
            if motif:
                break
        if not motif:
            rapport["lieux"].append({"lieu": lieu, "clips": [k + 1 for k in siens], "fond": None,
                                     "raison": "aucun passage sans voix de %.0f s" % MOTIF_MIN_S})
            continue
        m = reste[motif[0]:motif[1]]
        fond_db = float(np.median(niveaux(m, sr)))
        nappe = boucler(m, sum(plages[k][1] - plages[k][0] for k in siens), sr)
        t, portes = 0, []
        for k in siens:
            a, b = plages[k]
            r = reste[a:b]
            # Un clip dont le fond propre est plus fort que celui du lieu : la porte part de son
            # fond à lui, sinon elle le laisserait passer tout entier comme un bruit net.
            seuil = max(fond_db, float(np.median(niveaux(r, sr)))) + PORTE_AU_DESSUS_DB
            sortie[a:b] = voix[a:b] + nappe[t:t + b - a] + r * porte(r, sr, seuil)
            portes.append(round(seuil, 1))
            t += b - a
        rapport["lieux"].append({"lieu": lieu, "clips": [k + 1 for k in siens],
                                 "fond": [round(motif[0] / sr, 2), round(motif[1] / sr, 2)],
                                 "fond_db": round(fond_db, 1), "porte_db": portes})
    return np.clip(sortie, -1, 1), rapport
