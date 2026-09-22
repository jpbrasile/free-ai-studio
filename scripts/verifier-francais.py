#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Garde : l'argent et les dates s'écrivent en français, sur toutes les pages.

Le Studio s'adresse à un débutant francophone. La première ligne qu'il lit sur la
page vidéo parle de SON argent — et elle était écrite « 4.88 $ sur les 15.00 $ »,
avec la date « 2026-09-21 10:58:42 » à côté. Point décimal et date de journal de
machine, dans un produit entièrement en français.

Deux bras, et ils ne servent pas à la même chose :

  BRAS 1 — LE RENDU. On demande les pages au service qui tourne et on refuse,
  dans le HTML rendu, tout montant à point (`4.88 $`) et toute date ISO
  (`2026-09-21`). C'est ce que le client voit vraiment.

  BRAS 2 — LA SOURCE. Le bras 1 se tait quand la page n'a rien à montrer : pas
  de dépense ce mois-ci, pas de relevé, et le point décimal reste dans le code,
  prêt à revenir. Le bras 2 refuse donc les endroits qui FABRIQUENT un montant
  ou une date sans passer par les deux formateurs. Une garde qui ne peut pas
  échouer ne protège rien.

Usage :
    python scripts/verifier-francais.py [--base http://127.0.0.1:8020] [--sans-rendu]

Sortie 0 = tout est en français. Sortie 1 = la liste des endroits fautifs.
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BASE_DEFAUT = "http://127.0.0.1:8020"
PAGES = ["/", "/essai", "/video", "/chanson", "/dialogue", "/composite"]

# --- ce qu'on refuse dans le rendu -----------------------------------------
# « 4.88 $ », « 15.00 $ » : le point décimal anglais devant l'unité.
MONTANT_A_POINT = re.compile(r"\d+\.\d+\s*(?:\$|USD)")
# « 2026-09-21 » : la date de journal de machine.
DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# --- ce qu'on refuse dans la source ----------------------------------------
# Python : un montant écrit à la main au lieu de passer par le formateur.
PY_MONTANT = re.compile(r"%\.\d+f\s*\$|:\.\d+f\}\s*\$|:\.\d+f\}\s*USD")
# JavaScript : toFixed rend TOUJOURS un point, quelle que soit la langue.
JS_MONTANT = re.compile(r"\.toFixed\s*\(")
# JavaScript : une date qu'on affiche sans l'avoir francisée. Les champs
# d'horodatage se nomment tous `…_le` (`usd_reel_le`, `prix_releve_le`,
# `releve_le`) ; les écrire dans une phrase sans `dateFr(` autour, c'est imprimer
# « 2026-09-21 10:58:42 » au client. Ce contrôle-ci PEUT échouer : toute nouvelle
# ligne d'affichage le déclenche tant qu'elle n'appelle pas le formateur.
JS_DATE_NUE = re.compile(r"(?<!dateFr\()\b[A-Za-z_$][\w$]*\.[\w$]*_le\b")
# JavaScript : la date de la machine, sortie telle quelle.
JS_DATE = re.compile(r"toISOString\s*\(|toLocaleDateString\s*\(\s*\)")
# Python : une date fabriquée en ISO **pour être lue**. Le rangement, lui, garde
# la forme de machine -- elle se trie et se compare -- et porte la marque
# `date-machine` ; cette marque ne dispense de rien d'autre, et surtout pas de
# franciser l'affichage, dont s'occupe le contrôle du dessus.
PY_DATE = re.compile(r"%Y-%m-%d|\.isoformat\s*\(|strftime\(\s*[\"']%Y")
MARQUE_RANGEMENT = "date-machine"

MODULES = [
    "sandbox-manager/budget_modal.py",
    "sandbox-manager/app.py",
    "sandbox-manager/ou_calculer.py",
    "sandbox-manager/depenses.py",
    "sandbox-manager/video.py",
    "sandbox-manager/chanson.py",
    "sandbox-manager/dialogue.py",
    "sandbox-manager/composite.py",
]

# Les formateurs eux-mêmes ont le droit de contenir le motif : c'est leur travail.
# On les nomme par une marque écrite sur la ligne, pas par un numéro de ligne, qui
# vieillirait au premier remaniement.
LAISSEZ_PASSER = "formateur-francais"


def _lire(url: str, delai: float = 8.0) -> str:
    with urllib.request.urlopen(url, timeout=delai) as r:  # noqa: S310 (adresse locale)
        brut = r.read()
    return brut.decode("utf-8", "replace")


def bras_rendu(base: str) -> list[str]:
    """Ce que le client voit. Muet si le service ne répond pas — et il le DIT."""
    fautes: list[str] = []
    for chemin in PAGES:
        url = base.rstrip("/") + chemin
        try:
            html = _lire(url)
        except (urllib.error.URLError, OSError) as erreur:
            fautes.append(
                "RENDU INDISPONIBLE  %s : %s\n"
                "    (le service ne répond pas ; relancez-le, ou passez --sans-rendu\n"
                "     en sachant que seule la source aura été vérifiée)" % (url, erreur)
            )
            continue
        for nom, motif in (("montant à point", MONTANT_A_POINT), ("date ISO", DATE_ISO)):
            for trouve in dict.fromkeys(m.group(0) for m in motif.finditer(html)):
                fautes.append("RENDU  %-10s %-16s « %s »" % (chemin, nom, trouve))
        # Une page qui APPELLE `fr(...)` sans que la page les PORTE n'affiche plus
        # rien du tout : le JavaScript s'arrête sur « fr is not defined » et la
        # bannière entière disparaît, sans un mot dans les journaux du serveur.
        # C'est le seul défaut de cette famille qui soit pire que l'anglais.
        for appel, definition in (("fr(", "function fr("), ("dateFr(", "function dateFr(")):
            if appel in html and definition not in html:
                fautes.append(
                    "RENDU  %-10s formateur manquant  la page appelle « %s » sans le définir\n"
                    "    (le rendu a oublié format_fr.avec_formateurs ; la bannière est vide)"
                    % (chemin, appel))
    return fautes


def bras_source() -> list[str]:
    """Les endroits qui fabriquent un montant ou une date sans formateur."""
    fautes: list[str] = []
    for rel in MODULES:
        fichier = RACINE / rel
        if not fichier.exists():
            continue
        for n, ligne in enumerate(fichier.read_text(encoding="utf-8").split("\n"), 1):
            if LAISSEZ_PASSER in ligne:
                continue
            controles = [
                ("montant Python", PY_MONTANT),
                ("montant JS", JS_MONTANT),
                ("date affichée", JS_DATE_NUE),
                ("date JS", JS_DATE),
            ]
            # Une date RANGÉE garde sa forme de machine : c'est ce qui la rend
            # triable. La marque est posée ligne par ligne, jamais sur un fichier.
            if MARQUE_RANGEMENT not in ligne:
                controles.append(("date Python", PY_DATE))
            for nom, motif in controles:
                if motif.search(ligne):
                    fautes.append("SOURCE %s:%d  %-14s %s" % (rel, n, nom, ligne.strip()[:90]))
    return fautes


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=BASE_DEFAUT, help="adresse du service (defaut : %s)" % BASE_DEFAUT)
    ap.add_argument("--sans-rendu", action="store_true", help="ne verifier que la source")
    args = ap.parse_args(argv)

    fautes = bras_source()
    if not args.sans_rendu:
        fautes = bras_rendu(args.base) + fautes

    if not fautes:
        print("L'argent et les dates sont en francais sur les %d pages et les %d modules."
              % (len(PAGES), len(MODULES)))
        return 0

    for f in fautes:
        print(f)
    montants = sum(1 for f in fautes if "montant" in f)
    dates = sum(1 for f in fautes if "date" in f.lower())
    print("\n%d endroit(s) : %d sur l'argent, %d sur les dates." % (len(fautes), montants, dates))
    print("Le client lit ces lignes. Un point decimal et une date ISO ne sont pas du francais.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
