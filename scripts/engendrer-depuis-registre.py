#!/usr/bin/env python3
"""Ecrit, depuis `registry/apps.json`, les blocs que des documents recopiaient.

POURQUOI CE SCRIPT EXISTE. Le 20/09/2026, la meme verite etait recopiee a six
endroits et quatre avaient diverge. Mesure ce jour-la : << FireRedTTS2 >>
apparaissait 28 fois dans le code et 0 fois dans le README ; << Wan2.2 >> 10 et
0 ; << maison >> 99 et 0. Le README -- le seul document qu'un debutant lit AVANT
d'installer -- annoncait donc que la video exige une carte bancaire, alors
qu'elle se fabrique gratuitement sur la carte du PC depuis la veille, et ne
nommait nulle part l'application Dialogue.

Recopier a la main, c'est recommencer. Chaque bloc est donc ENGENDRE, entre deux
reperes, et `tests/test_registre.py` refuse un document qui ne suivrait plus.

DEUX BLOCS, DEUX ROLES DIFFERENTS, et c'est tout l'interet du second :

  README.md          le tableau des licences -- ce que chaque application
                     utilise, et sous quelle licence.
  notebooks/         << Ce que le Studio sert aujourd'hui >>. Ce document liste
  SOTA_LINKS.md      des CANDIDATS pour les carnets Colab/Kaggle ; rien n'y
                     disait ce qui tourne REELLEMENT, et un lecteur -- humain ou
                     agent -- prenait la recommandation pour la configuration.

    python scripts/engendrer-depuis-registre.py            # ecrit
    python scripts/engendrer-depuis-registre.py --verifier # dit seulement si c'est a jour
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REGISTRE = RACINE / "registry" / "apps.json"
MOI = "scripts/engendrer-depuis-registre.py"


def _cellule(texte: str) -> str:
    """Une barre verticale dans une cellule couperait le tableau en silence."""
    return texte.replace("|", "\\|").replace("\n", " ").strip()


def _applications() -> list[dict]:
    return json.loads(REGISTRE.read_text(encoding="utf-8"))["applications"]


def tableau_licences(debut: str, fin: str) -> str:
    lignes = [
        debut,
        "",
        "| Fonction | Fournisseur, modèle | Nature | Licence, territoire |",
        "|---|---|---|---|",
    ]
    notes = []
    for app in _applications():
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
        "Ne pas le modifier à la main : `python %s`.*" % MOI,
        "",
        fin,
    ]
    return "\n".join(lignes)


def en_service(debut: str, fin: str) -> str:
    """Ce que le Studio sert VRAIMENT, en face des candidats du document.

    Le critere est `modes`, pas `vram_min_go` : une application dont le seul
    mode est `api` n'a pas de poids a faire tourner et n'a rien a faire ici,
    tandis que la video rapide, la chanson et le dialogue en ont -- sur Modal,
    Kaggle ou Colab -- sans que leur place sur la carte ait ete mesuree chez
    nous. Filtrer sur `vram_min_go` ne laissait qu'UNE ligne sur huit, et ce
    tableau se serait lu comme << le Studio ne fait tourner qu'un modele >>.
    """
    lignes = [
        debut,
        "",
        "## Ce que le Studio sert aujourd'hui",
        "",
        "Les sections ci-dessus listent des **candidats** pour les carnets "
        "Colab/Kaggle. Le tableau qui suit dit ce qui tourne **réellement** dans "
        "le Studio, et il est engendré : il ne peut pas vieillir sans que la "
        "suite de tests le dise.",
        "",
        "| Fonction | Modèle | Où il tourne | Place sur la carte |",
        "|---|---|---|---|",
    ]
    for app in _applications():
        if not app["modele"] or set(app["modes"]) <= {"api"}:
            continue
        place = ("**non mesurée**" if app["vram_min_go"] is None
                 else "%s Go mesurés" % str(app["vram_min_go"]).replace(".", ","))
        lignes.append("| %s | `%s` | %s | %s |" % (
            _cellule(app["fonction"]), _cellule(app["modele"]),
            _cellule(", ".join(app["modes"])), place))
    lignes += [
        "",
        "*Engendré depuis `registry/apps.json` par `python %s`. "
        "Un modèle change dans le code, ce tableau change ici ; il n'y a plus de "
        "version recopiée à la main.*" % MOI,
        "",
        fin,
    ]
    return "\n".join(lignes)


# (fichier, repere de debut, repere de fin, fonction qui engendre le bloc)
CIBLES = [
    (RACINE / "README.md",
     "<!-- TABLEAU-LICENCES: engendre par %s -->" % MOI,
     "<!-- FIN-TABLEAU-LICENCES -->",
     tableau_licences),
    (RACINE / "notebooks" / "SOTA_LINKS.md",
     "<!-- EN-SERVICE: engendre par %s -->" % MOI,
     "<!-- FIN-EN-SERVICE -->",
     en_service),
]


def a_jour(cible) -> tuple[bool, str]:
    """Rend (est_a_jour, le fichier tel qu'il devrait etre)."""
    fichier, debut, fin, engendre = cible
    texte = fichier.read_text(encoding="utf-8")
    if debut not in texte or fin not in texte:
        raise SystemExit(
            "ECHEC : les reperes du bloc sont absents de %s.\n"
            "Ils encadrent le bloc engendre :\n  %s\n  %s"
            % (fichier.name, debut, fin))
    avant = texte[:texte.index(debut)]
    apres = texte[texte.index(fin) + len(fin):]
    voulu = avant + engendre(debut, fin) + apres
    return texte == voulu, voulu


def main() -> int:
    verifier = "--verifier" in sys.argv
    perimes = 0
    for cible in CIBLES:
        fichier = cible[0]
        vrai, voulu = a_jour(cible)
        if vrai:
            print("%-26s a jour." % fichier.name)
            continue
        perimes += 1
        if verifier:
            print("%-26s ECHEC : ne suit plus registry/apps.json." % fichier.name)
            continue
        # En octets, fins de ligne LF : `write_text` sous Windows traduit \n en
        # \r\n et retournerait le fichier entier (mesure le 20/09/2026 sur
        # PLAN.md, 490 CRLF contre 0 en base).
        fichier.write_bytes(voulu.encode("utf-8"))
        print("%-26s reecrit depuis le registre." % fichier.name)
    return 1 if (verifier and perimes) else 0


if __name__ == "__main__":
    sys.exit(main())
