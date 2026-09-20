#!/usr/bin/env python3
"""Ecrit le tableau des licences du README depuis `registry/apps.json`.

POURQUOI CE SCRIPT EXISTE. Le 20/09/2026, la meme verite etait recopiee a six
endroits et quatre avaient diverge. Mesure ce jour-la : << FireRedTTS2 >>
apparaissait 28 fois dans le code et 0 fois dans le README ; << Wan2.2 >> 10 et
0 ; << maison >> 99 et 0. Le README -- le seul document qu'un debutant lit AVANT
d'installer -- annoncait donc que la video exige une carte bancaire, alors
qu'elle se fabrique gratuitement sur la carte du PC depuis la veille, et ne
nommait nulle part l'application Dialogue.

Recopier a la main, c'est recommencer. Le tableau est donc ENGENDRE, entre deux
reperes, et `tests/test_registre.py` refuse un README qui ne serait plus a jour.

    python scripts/generer-tableau-readme.py            # ecrit
    python scripts/generer-tableau-readme.py --verifier # dit seulement si c'est a jour
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REGISTRE = RACINE / "registry" / "apps.json"
README = RACINE / "README.md"

DEBUT = "<!-- TABLEAU-LICENCES: engendre par scripts/generer-tableau-readme.py -->"
FIN = "<!-- FIN-TABLEAU-LICENCES -->"


def _cellule(texte: str) -> str:
    """Une barre verticale dans une cellule couperait le tableau en silence."""
    return texte.replace("|", "\\|").replace("\n", " ").strip()


def tableau() -> str:
    registre = json.loads(REGISTRE.read_text(encoding="utf-8"))
    apps = registre["applications"]

    lignes = [
        DEBUT,
        "",
        "| Fonction | Fournisseur, modèle | Nature | Licence, territoire |",
        "|---|---|---|---|",
    ]
    notes = []
    for app in apps:
        modele = app["modele"]
        qui = app["fournisseur"] if not modele else "%s, `%s`" % (app["fournisseur"], modele)
        licence = "%s ([fiche](%s)) ; territoire : %s" % (
            app["licence"], app["source"], app["territoire"])
        marque = ""
        if app.get("note"):
            marque = " <sup>%d</sup>" % (len(notes) + 1)
            notes.append((len(notes) + 1, app["fonction"], app["note"]))
        lignes.append("| %s%s | %s | %s | %s |" % (
            _cellule(app["fonction"]), marque, _cellule(qui),
            _cellule(app["nature"]), _cellule(licence)))

    if notes:
        lignes += ["", "**Ce que la seule licence ne dit pas :**", ""]
        for numero, fonction, note in notes:
            lignes.append("%d. **%s** — %s" % (numero, fonction, note))

    lignes += [
        "",
        "*Tableau engendré depuis `registry/apps.json` ; la date de la dernière "
        "lecture de chaque licence y est écrite, champ `verifie_le`. "
        "Ne pas le modifier à la main : `python scripts/generer-tableau-readme.py`.*",
        "",
        FIN,
    ]
    return "\n".join(lignes)


def readme_a_jour() -> tuple[bool, str]:
    """Rend (est_a_jour, le README tel qu'il devrait etre)."""
    texte = README.read_text(encoding="utf-8")
    if DEBUT not in texte or FIN not in texte:
        raise SystemExit(
            "ECHEC : les reperes du tableau sont absents du README.\n"
            "Ils encadrent le tableau engendre :\n  %s\n  %s" % (DEBUT, FIN))
    avant = texte[:texte.index(DEBUT)]
    apres = texte[texte.index(FIN) + len(FIN):]
    voulu = avant + tableau() + apres
    return texte == voulu, voulu


def main() -> int:
    a_jour, voulu = readme_a_jour()
    if "--verifier" in sys.argv:
        print("README a jour." if a_jour else
              "ECHEC : le tableau du README ne suit plus registry/apps.json.")
        return 0 if a_jour else 1
    if a_jour:
        print("README deja a jour, rien a ecrire.")
        return 0
    # En octets, fins de ligne LF : `write_text` sous Windows traduit \n en
    # \r\n et retournerait le fichier entier (mesure le 20/09/2026 sur PLAN.md,
    # 490 CRLF contre 0 en base).
    README.write_bytes(voulu.encode("utf-8"))
    print("README : tableau des licences reecrit depuis le registre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
