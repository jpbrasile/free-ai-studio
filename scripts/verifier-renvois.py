#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Garde : un renvoi `fichier:ligne` cite ce qu'il prétend citer.

Un renvoi périmé est le plus silencieux des défauts. Il ne casse aucun test, ne
fait tomber aucune garde, et n'a aucun signe extérieur : il envoie simplement le
prochain lecteur sur une autre ligne, qui a l'air d'une réponse. C'est un
faux-vert de documentation.

Le 22/09/2026, l'ajout d'un bloc de 273 lignes dans un module a rendu faux d'un
coup **25 renvois écrits le jour même**. Rien ne l'a signalé. Et en échantillonnant
six renvois anciens pour écrire cette garde, **trois étaient déjà faux**, avec des
dérives de 8, 31 et 59 lignes — dont un que le plan disait « vérifié aujourd'hui ».

CE QUI REND LA VÉRIFICATION POSSIBLE : LE MOTIF
-----------------------------------------------
Un numéro de ligne seul est invérifiable — rien ne dit ce qu'il devrait y avoir.
Un renvoi se donne donc un témoin, entre parenthèses et entre accents graves :

    `sandbox-manager/app.py:385` (`def forget_secrets`)

La garde ouvre le fichier, lit la ligne 369, et y cherche `def forget_secrets`.
Absent, elle le cherche dans tout le fichier et **dit où il est** : la réparation
ne demande alors aucune enquête.

CE QUE LA GARDE NE FAIT PAS, ET POURQUOI
----------------------------------------
Elle ignore aussi les renvois d'une ligne qui porte le marqueur `renvoi-exemple` :
ceux-là illustrent la forme au lieu de prétendre quelque chose de ce dépôt. Sans
lui, les tests de cette garde — dont tout l'objet est d'écrire des renvois qui
mentent — la feraient rougir, et elle s'interdirait elle-même d'entrer dans la
CI. Le marqueur n'est jamais silencieux : le nombre d'exemples ignorés est dit.

Elle ignore les renvois **sans** motif. Le dépôt en porte 177 qui n'en ont pas ;
les faire rougir d'un coup imposerait de les reprendre un par un, ce qui est une
décision du propriétaire et non la mienne. La garde ne bloque donc personne, et
grossit à mesure qu'on écrit. Un renvoi sans motif reste un pari ; il n'est
simplement pas encore tenu.

Usage :
    python scripts/verifier-renvois.py [--lister] [chemins...]

Sortie 0 = tout renvoi motivé cite bien sa ligne. Sortie 1 = la liste des fautes,
chacune avec le numéro réel quand il est trouvable.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Forme reconnue : `chemin/fichier.ext : 123` (`motif`), ou un intervalle
# `... : 12-18`. Les deux-points sont ESPACES ici pour que ces illustrations ne
# soient pas prises pour de vrais renvois -- la garde irait chercher un fichier
# nomme << chemin/fichier.ext >>. Quand la forme COLLEE est indispensable, comme
# dans les tests de cette garde, la ligne porte le marqueur ci-dessous.
#
# Le motif est entre accents graves : sans eux, une parenthese de prose qui suit
# un renvoi serait prise pour un temoin, et la garde inventerait des fautes.
#
# La forme abregee -- deux-points, numero, sans fichier -- herite du fichier cite
# plus tot SUR LA MEME LIGNE : c'est ainsi qu'on l'ecrit et ainsi qu'on le lit.
# La portee s'arrete a la ligne ; un heritage courant sur tout un document ferait
# pointer un renvoi vers un fichier nomme trois paragraphes plus haut, ce
# qu'aucun lecteur ne fait.
RENVOI = re.compile(
    r"`([^`\s:]+\.[A-Za-z0-9_]+)?:(\d+)(?:-(\d+))?`\s*\(`([^`]+)`\)")

# Une ligne qui porte ce marqueur ecrit des renvois pour l'EXEMPLE : ils ne
# pretendent rien de ce depot-ci. Sans lui, les tests de cette garde -- dont
# tout l'objet est de fabriquer des renvois faux -- la feraient rougir, et elle
# s'interdirait elle-meme d'entrer dans la CI. Le marqueur est explicite, tenu a
# la ligne, et JAMAIS silencieux : le nombre d'exemples ignores est affiche.
MARQUE = "renvoi-exemple"

# Ce qu'on ne parcourt pas : ni les dependances, ni ce que git ignore.
EXCLUS = ("node_modules/", ".git/", "__pycache__/")


def fichiers_suivis(motifs=("*.md", "*.py")) -> list[Path]:
    """Les fichiers que git suit. Un fichier non suivi n'engage personne."""
    sortie = subprocess.run(["git", "ls-files", "-z", *motifs],
                            cwd=RACINE, capture_output=True, text=True, check=True)
    noms = [n for n in sortie.stdout.split("\0") if n]
    return [RACINE / n for n in noms
            if not any(x in n for x in EXCLUS)]


def resoudre(chemin: str) -> tuple[Path | None, str]:
    """Le chemin cite, rendu absolu. Un nom nu ne vaut que s'il est unique.

    `app.py` existe deux fois dans ce depot -- une par service. Un renvoi qui
    l'ecrit nu ne designe rien : la garde le dit au lieu d'en choisir un.
    """
    direct = RACINE / chemin
    if direct.is_file():
        return direct, ""
    suffixe = "/" + chemin.replace("\\", "/")
    candidats = [f for f in fichiers_suivis(("*",))
                 if f.as_posix().endswith(suffixe)]
    if len(candidats) == 1:
        return candidats[0], ""
    if not candidats:
        return None, "fichier introuvable"
    montres = ", ".join(c.relative_to(RACINE).as_posix() for c in candidats[:4])
    return None, "chemin ambigu (%d fichiers : %s)" % (len(candidats), montres)


def lignes_de(chemin: Path) -> list[str]:
    return chemin.read_text(encoding="utf-8", errors="replace").splitlines()


def ou_est_il(lignes: list[str], motif: str) -> str:
    """Le motif est-il ailleurs ? C'est ce qui transforme un refus en reparation."""
    trouves = [i + 1 for i, ligne in enumerate(lignes) if motif in ligne]
    if not trouves:
        return "et il n'est nulle part dans ce fichier"
    if len(trouves) == 1:
        return "il est en realite ligne %d" % trouves[0]
    return "il est aux lignes %s" % ", ".join(str(t) for t in trouves[:5])


def verifier_un(source: Path, num_source: int, chemin: str, debut: int,
                fin: int | None, motif: str) -> str | None:
    ou = "%s:%d" % (source.relative_to(RACINE).as_posix(), num_source)
    cible, souci = resoudre(chemin)
    if cible is None:
        return "%s : `%s:%d` -- %s" % (ou, chemin, debut, souci)
    lignes = lignes_de(cible)
    dernier = fin or debut
    if debut < 1 or dernier > len(lignes):
        return ("%s : `%s:%d` depasse la fin du fichier (%d lignes). %s"
                % (ou, chemin, debut, len(lignes), ou_est_il(lignes, motif)))
    tranche = lignes[debut - 1:dernier]
    if any(motif in ligne for ligne in tranche):
        return None
    vue = tranche[0].strip()[:60] or "(ligne vide)"
    return ("%s : `%s:%d` annonce `%s`, la ligne dit << %s >> -- %s"
            % (ou, chemin, debut, motif, vue, ou_est_il(lignes, motif)))


def parcourir(fichiers: list[Path]) -> tuple[list[str], list[tuple], int]:
    """Rend les fautes, les renvois motives rencontres, et les exemples ignores."""
    fautes: list[str] = []
    vus: list[tuple] = []
    exemples = 0
    for fichier in fichiers:
        try:
            texte = fichier.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for num, ligne in enumerate(texte.splitlines(), start=1):
            if MARQUE in ligne:
                exemples += len(RENVOI.findall(ligne))
                continue
            # L'heritage du fichier ne franchit pas la fin de la ligne.
            dernier = ""
            for trouve in RENVOI.finditer(ligne):
                chemin, debut, fin, motif = trouve.groups()
                if chemin:
                    dernier = chemin
                elif dernier:
                    chemin = dernier
                else:
                    ou = fichier.relative_to(RACINE).as_posix()
                    fautes.append(
                        "%s:%d : `:%s` est un renvoi abrege, mais aucun fichier "
                        "n'est nomme avant lui sur cette ligne." % (ou, num, debut))
                    continue
                vus.append((fichier, num, chemin, debut, motif))
                faute = verifier_un(fichier, num, chemin, int(debut),
                                    int(fin) if fin else None, motif)
                if faute:
                    fautes.append(faute)
    return fautes, vus, exemples


def main(argv: list[str]) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("chemins", nargs="*",
                         help="fichiers a lire (defaut : tout ce que git suit)")
    parseur.add_argument("--lister", action="store_true",
                         help="montrer chaque renvoi motive et son verdict")
    args = parseur.parse_args(argv)

    fichiers = ([Path(c).resolve() for c in args.chemins] if args.chemins
                else fichiers_suivis())
    fautes, vus, exemples = parcourir(fichiers)

    if args.lister:
        for fichier, num, chemin, debut, motif in vus:
            print("  %s:%d -> %s:%s (%s)"
                  % (fichier.relative_to(RACINE).as_posix(), num, chemin, debut, motif))

    # Jamais silencieux : un marqueur qu'on ne compte pas est un interrupteur cache.
    suite = (" %d exemple(s) ignore(s) (ligne marquee << %s >>)." % (exemples, MARQUE)
             if exemples else "")

    if not fautes:
        print("%d renvoi(s) motive(s) : chacun cite bien sa ligne.%s"
              % (len(vus), suite))
        return 0

    for faute in fautes:
        print(faute)
    print("\n%d faute(s) sur %d renvoi(s) motive(s).%s"
          % (len(fautes), len(vus), suite))
    print("Un renvoi perime n'a aucun signe exterieur : il envoie le prochain "
          "lecteur sur une ligne qui a l'air d'une reponse.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
