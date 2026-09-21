#!/usr/bin/env python3
"""Inscrit dans le registre le jour ou une machine a RELU la licence.

POURQUOI UN CHAMP DE PLUS, et pas la mise a jour de celui qui existe.
`verifie_le` est defini dans l'en-tete du registre comme << le jour ou la
licence a ete lue sur la fiche officielle >>. C'est le geste d'un humain qui
ouvre la page et lit les conditions. Si un travail programme avancait cette
date, le champ changerait de sens en silence : il dirait << un humain a lu >>
en voulant dire << une machine a compare deux etiquettes >>. C'est exactement
le mal que l'etape 6 passe son temps a retirer -- un document qui affirme
autre chose que ce qu'il sait.

Le champ ajoute est donc distinct : `relu_le`. Il dit ce qu'il est, il ne
remplace rien, et il ne vaut que pour les entrees qui CONCORDENT.

CE SCRIPT EST CHIRURGICAL. Il n'ecrit pas le registre a partir de l'objet
relu : `json.dumps` reformaterait les 16 entrees d'un coup (les listes ecrites
sur une ligne se deplieraient), la demande de fusion ferait 400 lignes et
personne ne la relirait. Il insere une ligne par entree concernee, et le reste
du fichier est identique a l'octet.

    python scripts/proposer-les-mises-a-jour.py --verdict v.json
    python scripts/inscrire-la-relecture.py --verdict v.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REGISTRE = RACINE / "registry" / "apps.json"


def bloc_de(texte: str, identifiant: str) -> tuple[int, int]:
    """Les bornes de l'objet d'une application, dans le texte du registre.

    Rendre les bornes plutot que l'objet : on retouche une ligne a l'interieur,
    on ne reconstruit pas l'objet.
    """
    depart = re.search(r'\{\n\s+"id": "%s"' % re.escape(identifiant), texte)
    if not depart:
        raise KeyError("application absente du registre : %s" % identifiant)
    fin = texte.index("\n    }", depart.start())
    return depart.start(), fin


def inscrire(texte: str, identifiant: str, jour: str) -> str:
    """Pose ou remplace `relu_le` dans UNE entree, juste apres `verifie_le`."""
    debut, fin = bloc_de(texte, identifiant)
    bloc = texte[debut:fin]

    deja = re.search(r'\n(\s+)"relu_le": "[^"]*",?', bloc)
    if deja:
        nouveau = bloc[:deja.start()] + '\n%s"relu_le": "%s",' % (deja.group(1), jour) \
            + bloc[deja.end():]
    else:
        ancre = re.search(r'\n(\s+)"verifie_le": "[^"]*",', bloc)
        if not ancre:
            raise KeyError("`verifie_le` absent de l'entree %s" % identifiant)
        nouveau = bloc[:ancre.end()] + '\n%s"relu_le": "%s",' % (ancre.group(1), jour) \
            + bloc[ancre.end():]
    return texte[:debut] + nouveau + texte[fin:]


def main() -> int:
    if "--verdict" not in sys.argv:
        print(__doc__, file=sys.stderr)
        return 2
    verdict = json.loads(
        Path(sys.argv[sys.argv.index("--verdict") + 1]).read_text(encoding="utf-8"))

    jour = (sys.argv[sys.argv.index("--jour") + 1] if "--jour" in sys.argv
            else time.strftime("%Y-%m-%d"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", jour):
        print("date illisible : %r" % jour, file=sys.stderr)
        return 2

    # Un desaccord ou une fiche disparue veut dire que la lecture du jour
    # CONTREDIT le registre. Inscrire alors une date de relecture, meme sur les
    # autres entrees, ferait passer pour verifie un fichier qu'un humain doit
    # ouvrir. On s'arrete et on le dit.
    a_trancher = len(verdict.get("desaccords", [])) + len(verdict.get("disparus", []))
    if a_trancher:
        print("%d entree(s) a trancher : rien n'est inscrit." % a_trancher,
              file=sys.stderr)
        return 1

    octets = REGISTRE.read_bytes()
    texte = octets.decode("utf-8")
    for entree in verdict.get("concordent", []):
        texte = inscrire(texte, entree["id"], jour)
    nouveau = texte.encode("utf-8")

    if nouveau == octets:
        print("rien a inscrire : les dates sont deja celles du jour.")
        return 0
    REGISTRE.write_bytes(nouveau)
    print("%d date(s) de relecture inscrite(s) au %s."
          % (len(verdict.get("concordent", [])), jour))
    return 0


if __name__ == "__main__":
    sys.exit(main())
