"""Les deux butoirs du 31/10/2026, relus par la CI plutot que par la memoire.

Decisions 9 et 15 de l'utilisateur, 19/09/2026 (docs/PLAN-PLATEFORME.md, §8,
rang 3 de l'ordre : << elles ne coutent rien a poser et tout a oublier >>).
Chaque date est ecrite dans le document qu'elle concerne, sur une ligne de
commentaire HTML que ce script relit :

    <!-- echeance: <id> | butoir: AAAA-MM-JJ | etat: <etat> | preuve: <texte> -->

Trois etats, et un seul devient illegal le lendemain du butoir :

    en-attente   rien n'a encore ete fait
    tenue        c'est joue, et la preuve est ecrite a cote
    abandonnee   on renonce a mesurer, et le document le dit en toutes lettres

Ce que ce script refuse :

1. la ligne disparue, dupliquee, ou dont le butoir a bouge sans que ce fichier
   bouge -- reporter une date redevient ainsi une decision visible en revue,
   pas un caractere change dans un document de 1900 lignes ;
2. << en-attente >> apres le butoir : c'est exactement ce que la date interdit
   (decision 9 : << passe ce jour sans verdicts, le document ecrit *mesure
   abandonnee*, pas *en attente* >>) ;
3. << tenue >> ou << abandonnee >> sans preuve -- la regle du depot, un fait
   cite sa preuve ;
4. << abandonnee >> sans que le document porte les mots de l'abandon.

Il ne lit aucune valeur, ne touche ni au reseau ni a git, et se joue a une date
arbitraire (--aujourdhui) pour que les tests couvrent l'apres-butoir sans
attendre le 1er novembre.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

MARQUEUR = re.compile(r"<!--(?P<corps>\s*echeance\s*:.*?)-->", re.S)

ETATS = ("en-attente", "tenue", "abandonnee")


@dataclass(frozen=True)
class Echeance:
    """Une date, le document qui la porte, et ce qu'elle exige."""

    id: str
    fichier: str
    butoir: date
    quoi: str
    mots_abandon: str


# Le butoir vit ICI autant que dans le document : les deux doivent bouger
# ensemble, ce qui est tout l'interet.
ECHEANCES = (
    Echeance(
        id="essai-machine-neuve",
        fichier="docs/ESSAI_MACHINE_NEUVE.md",
        butoir=date(2026, 10, 31),
        quoi="la grille des six taches, jouee sur un autre ordinateur",
        mots_abandon="mesure abandonnee",
    ),
    Echeance(
        id="restauration-sauvegardes",
        fichier="docs/SAUVEGARDES.md",
        butoir=date(2026, 10, 31),
        quoi="le premier essai de restauration, joue et date",
        mots_abandon="essai abandonne",
    ),
)


def _sans_accents(texte: str) -> str:
    """Compare des mots sans dependre des accents ni de la casse.

    Le document ecrit << mesure abandonnee >> avec ses accents ; ce fichier-ci
    n'en porte aucun, par convention. Sans cette normalisation le controle du
    point 4 refuserait une phrase correcte."""
    remplacements = {
        "à": "a", "â": "a", "ä": "a",
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "ù": "u", "û": "u", "ü": "u",
        "ç": "c",
    }
    texte = texte.lower()
    for accentue, simple in remplacements.items():
        texte = texte.replace(accentue, simple)
    return texte


def _champs(corps: str):
    """Decoupe le corps du marqueur en dictionnaire cle -> valeur."""
    champs = {}
    for morceau in corps.split("|"):
        if not morceau.strip():
            continue
        if ":" not in morceau:
            return None, "champ sans deux-points : %r" % morceau.strip()
        cle, _, valeur = morceau.partition(":")
        champs[cle.strip().lower()] = valeur.strip()
    return champs, None


def verifier(racine: Path, aujourdhui: date):
    """Rend (problemes, lignes_d_etat). Aucun probleme = la CI passe."""
    problemes: list[str] = []
    etats: list[str] = []

    for echeance in ECHEANCES:
        chemin = racine / echeance.fichier
        if not chemin.is_file():
            problemes.append(
                "%s : %s est absent. C'est le document qui porte la date ; "
                "le supprimer supprime l'echeance." % (echeance.id, echeance.fichier)
            )
            continue

        texte = chemin.read_text(encoding="utf-8")
        trouves = []
        for brut in MARQUEUR.finditer(texte):
            champs, erreur = _champs(brut.group("corps"))
            if erreur:
                problemes.append("%s : marqueur illisible, %s" % (echeance.fichier, erreur))
                continue
            if champs.get("echeance") == echeance.id:
                trouves.append(champs)

        if not trouves:
            problemes.append(
                "%s : aucune ligne << echeance: %s >> dans %s. Attendu : %s, "
                "butoir %s."
                % (echeance.id, echeance.id, echeance.fichier, echeance.quoi,
                   echeance.butoir.isoformat())
            )
            continue
        if len(trouves) > 1:
            problemes.append(
                "%s : %d lignes d'echeance dans %s. Une seule fait foi ; deux se "
                "contredisent le jour ou elles divergent."
                % (echeance.id, len(trouves), echeance.fichier)
            )
            continue

        champs = trouves[0]

        butoir_ecrit = champs.get("butoir", "")
        try:
            butoir = date.fromisoformat(butoir_ecrit)
        except ValueError:
            problemes.append(
                "%s : butoir illisible (%r). Format attendu AAAA-MM-JJ."
                % (echeance.id, butoir_ecrit)
            )
            continue
        if butoir != echeance.butoir:
            problemes.append(
                "%s : le document dit %s, ce script dit %s. Reporter une date est "
                "une decision : elle se prend dans les deux fichiers, en revue."
                % (echeance.id, butoir.isoformat(), echeance.butoir.isoformat())
            )
            continue

        etat = champs.get("etat", "")
        if etat not in ETATS:
            problemes.append(
                "%s : etat %r inconnu. Les trois etats sont %s."
                % (echeance.id, etat, ", ".join(ETATS))
            )
            continue

        preuve = champs.get("preuve", "")
        if etat in ("tenue", "abandonnee") and not preuve:
            problemes.append(
                "%s : etat << %s >> sans preuve. Un fait cite sa preuve ; sans "
                "elle c'est << non verifie >>." % (echeance.id, etat)
            )
            continue

        if etat == "abandonnee":
            if echeance.mots_abandon not in _sans_accents(texte):
                problemes.append(
                    "%s : etat << abandonnee >> mais %s n'ecrit nulle part "
                    "<< %s >>. La decision se lit dans le document, pas seulement "
                    "dans un commentaire."
                    % (echeance.id, echeance.fichier, echeance.mots_abandon)
                )
                continue
            etats.append("%s : abandonnee -- %s" % (echeance.id, preuve))
            continue

        if etat == "tenue":
            etats.append("%s : tenue -- %s" % (echeance.id, preuve))
            continue

        # en-attente : c'est ici que la date mord.
        restant = (butoir - aujourdhui).days
        if restant < 0:
            problemes.append(
                "%s : BUTOIR DEPASSE de %d jour(s) (%s) et le document dit encore "
                "<< en attente >>. Ce qui manque : %s. Deux issues, pas trois -- "
                "jouer l'essai et ecrire << etat: tenue | preuve: ... >>, ou "
                "renoncer et ecrire << etat: abandonnee | preuve: ... >> avec "
                "<< %s >> dans le texte de %s."
                % (echeance.id, -restant, butoir.isoformat(), echeance.quoi,
                   echeance.mots_abandon, echeance.fichier)
            )
            continue
        etats.append(
            "%s : en attente, %d jour(s) avant le %s -- %s"
            % (echeance.id, restant, butoir.isoformat(), echeance.quoi)
        )

    return problemes, etats


def main(argv=None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "--aujourdhui",
        help="date a jouer, AAAA-MM-JJ (defaut : aujourd'hui). Pour repondre a "
        "<< que se passe-t-il le 1er novembre ? >> sans attendre.",
    )
    parseur.add_argument("--racine", default=str(RACINE), help=argparse.SUPPRESS)
    args = parseur.parse_args(argv)

    aujourdhui = date.fromisoformat(args.aujourdhui) if args.aujourdhui else date.today()
    problemes, etats = verifier(Path(args.racine), aujourdhui)

    for ligne in etats:
        print("  ok   %s" % ligne)
    for ligne in problemes:
        print("ECHEC  %s" % ligne)

    if problemes:
        print("\n%d echeance(s) en defaut, au %s." % (len(problemes), aujourdhui.isoformat()))
        return 1
    print("\n%d echeance(s) en regle, au %s." % (len(etats), aujourdhui.isoformat()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
