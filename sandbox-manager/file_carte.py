"""La file d'attente de la carte de cet ordinateur, pour les calculs « sans urgence ».

Demande du propriétaire, 01/10/2026 : « le client débutant n'aura peut-être pas une
carte GPU et en tout cas aucun hook installé. Studio doit gérer les deux configs ».
Jusque-là, tout ce qui a tourné sur la 4090 pour H3 passait par la file de la machine
du propriétaire (dsh3, `scripts/maison_calcul.py`), qu'aucun client n'a. Cette file-ci
vit dans le Studio et ne suppose rien d'autre que la carte.

Trois règles, et rien de plus :
  - un travail à la fois, dans l'ordre d'arrivée ;
  - il part quand la carte est LIBRE (`gpu_local.libre_pour_un_code_inconnu`, le seuil
    du bureau Windows) : H3 prend toute la place qu'on lui laisse (pic relevé
    23 141 Mio sur 24 564, carte vide, 01/10), donc « assez de place » veut dire
    « personne d'autre » ;
  - elle ATTEND, sans limite de durée : elle n'arrête jamais celui qui tient la carte.
    Le client l'arrête, lui, par le bouton du travail.

Ce qu'elle ne fait pas : survivre à un redémarrage du Studio. Un travail en attente
meurt avec le conteneur, et la reprise le dit (`reprise.que_faire`, ORPHELIN).
"""
from __future__ import annotations

import threading
from typing import Callable

import gpu_local

SONDE_S = 20.0

_cond = threading.Condition()
_file: list[str] = []
_en_cours: str | None = None


def position(jid: str) -> int | None:
    """1 = le prochain à partir ; None = pas dans la file (ou déjà parti)."""
    with _cond:
        return _file.index(jid) + 1 if jid in _file else None


def etat() -> dict:
    with _cond:
        return {"en_cours": _en_cours, "en_attente": list(_file)}


def attendre_son_tour(jid: str, annule: Callable[[], bool],
                      noter: Callable[[int, str], None],
                      libre: Callable[[], tuple] | None = None,
                      sonde_s: float | None = None) -> bool:
    """Bloque jusqu'à ce que `jid` soit en tête ET que la carte soit libre.

    Rend True : la carte est à lui jusqu'à `rendre(jid)`. Rend False : le client a
    annulé pendant l'attente (`annule()`), rien n'a tourné. `noter(position, motif)`
    est appelé à chaque changement, pour que la page dise pourquoi on attend."""
    global _en_cours
    libre = libre or gpu_local.libre_pour_un_code_inconnu
    sonde_s = SONDE_S if sonde_s is None else sonde_s
    with _cond:
        _file.append(jid)
    dit = None
    try:
        while True:
            if annule():
                return False
            with _cond:
                rang = _file.index(jid) + 1
                tete = rang == 1 and _en_cours is None
            if tete:
                ok, motif, _ = libre()
                if ok:
                    with _cond:
                        if _file and _file[0] == jid and _en_cours is None:
                            _file.pop(0)
                            _en_cours = jid
                            return True
                    continue
            else:
                motif = ("%d calcul%s avant celui-ci sur la carte de cet ordinateur."
                         % (rang - 1 + (_en_cours is not None),
                            "s" if rang - 1 + (_en_cours is not None) > 1 else ""))
            if (rang, motif) != dit:
                noter(rang, motif)
                dit = (rang, motif)
            with _cond:
                # Relu SOUS le verrou, juste avant d'attendre (02/10) : un arrêt écrit puis
                # signalé (`reveiller`) entre la lecture du haut et ce wait perdait son
                # signal, et l'attente dormait toute la sonde (20 s) avant de le voir.
                if annule():
                    return False
                _cond.wait(sonde_s)
    finally:
        with _cond:
            if jid in _file:
                _file.remove(jid)
            _cond.notify_all()


def rendre(jid: str) -> None:
    """La carte est rendue ; le suivant regarde tout de suite."""
    global _en_cours
    with _cond:
        if _en_cours == jid:
            _en_cours = None
        _cond.notify_all()


def reveiller() -> None:
    """Un arrêt demandé : les attentes relisent `annule()` sans attendre la sonde."""
    with _cond:
        _cond.notify_all()


