#!/usr/bin/env python3
"""Relit les licences chez leur editeur, et PROPOSE -- il ne decide jamais.

POURQUOI. `registry/apps.json` porte un champ `verifie_le`, defini dans son
propre en-tete comme << le jour ou la licence a ete lue sur la fiche
officielle >>, suivi de << une licence peut changer >>. Jusqu'ici rien ne la
relisait : la date vieillissait toute seule et se lisait quand meme comme une
verification. C'est le meme mal que les six copies du 20/09/2026, deplace dans
le temps au lieu de l'espace.

CE QUE CE SCRIPT NE FAIT PAS, et c'est le point qui compte. Il ne change aucune
licence, aucun modele, aucun territoire. Une licence qui a change chez
l'editeur est une decision humaine -- elle peut interdire un usage commercial
du jour au lendemain. Le script rend un rapport et un code de sortie ; le
travail programme (`.github/workflows/licences.yml`) ouvre un ticket ou une
demande de fusion, et un humain tranche.

TROIS CODES DE SORTIE, jamais confondus :
    0  tout concorde
    1  au moins un desaccord, ou une fiche disparue : a un humain de trancher
    2  la lecture elle-meme a echoue (reseau, editeur en panne). PAS un vert :
       un banc qui rend 0 quand il n'a rien pu lire ment plus qu'il n'informe.

    python scripts/proposer-les-mises-a-jour.py                    # lit chez l'editeur
    python scripts/proposer-les-mises-a-jour.py --hors-ligne f.json  # rejoue un releve
    python scripts/proposer-les-mises-a-jour.py --releve f.json      # ecrit le releve lu
    python scripts/proposer-les-mises-a-jour.py --verdict f.json     # ecrit le verdict

CE SCRIPT N'ECRIT JAMAIS DANS `registry/apps.json`. C'est
`scripts/inscrire-la-relecture.py` qui y inscrit la date de relecture, a partir
du verdict, et seulement pour les entrees qui concordent. Separer les deux fait
de cette phrase un controle (`tests/test_propositions.py`) au lieu d'une
intention.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REGISTRE = RACINE / "registry" / "apps.json"

API = "https://huggingface.co/api/models/%s"
API_AUTEUR = "https://huggingface.co/api/models?author=%s&sort=lastModified&direction=-1&limit=100"
DEPOT = re.compile(r"^https://huggingface\.co/([^/]+)/([^/?#]+)")
AGENT = "free-ai-studio/verificateur-de-licences (+https://github.com/jpbrasile/free-ai-studio)"

# Identifiant de licence chez Hugging Face -> comment il s'ecrit chez nous.
# `None` = connu, mais impossible a comparer automatiquement : dit comme tel,
# jamais compte comme une concordance.
EQUIVALENCES = {
    "apache-2.0": "apache 2.0",
    "mit": "mit",
    "bsd-3-clause": "bsd-3-clause",
    "cc-by-4.0": "cc by 4.0",
    "cc-by-nc-4.0": "cc by-nc 4.0",
    "cc-by-sa-4.0": "cc by-sa 4.0",
    "cc0-1.0": "domaine public",
    "gpl-3.0": "gpl-3.0",
    "agpl-3.0": "agpl-3.0",
    "openrail": "openrail",
    "other": None,
    "unknown": None,
}


def _nu(texte: str) -> str:
    """Le mot tel qu'on le compare : minuscules, sans accents."""
    import unicodedata
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _famille(nom: str) -> str:
    """La racine d'un nom de modele : `Wan2.1-VACE-1.3B` -> `Wan`.

    Sert a proposer des versions plus recentes du MEME modele, et non le
    catalogue entier d'un editeur.
    """
    trouve = re.match(r"[A-Za-z]+", nom)
    return trouve.group(0) if trouve else nom


def depot_de(source: str) -> str | None:
    """Le depot Hugging Face derriere une adresse de fiche, s'il y en a un.

    L'adresse peut viser un FICHIER (`.../blob/main/fr/xxx.onnx`) : le depot
    reste les deux premiers segments. Les fiches qui ne sont pas chez Hugging
    Face -- conditions de Google, de DuckDuckGo, page de modeles d'OpenRouter --
    rendent None, et sont dites NON VERIFIABLES plutot que vertes.
    """
    trouve = DEPOT.match(source)
    return "%s/%s" % (trouve.group(1), trouve.group(2)) if trouve else None


# --- La lecture chez l'editeur (la seule partie qui touche au reseau) -------

def _lire(adresse: str, delai: int = 20):
    requete = urllib.request.Request(adresse, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(requete, timeout=delai) as reponse:  # noqa: S310
        return json.loads(reponse.read().decode("utf-8"))


def relever(depots: list[str]) -> dict:
    """Rend {depot: fiche} ; une fiche absente vaut {"absent": True}.

    Une panne de reseau n'est pas transformee en resultat : elle remonte, et
    l'appelant sort en code 2.
    """
    releve = {"lu_le": time.strftime("%Y-%m-%d %H:%M:%S"), "fiches": {}, "voisins": {}}
    auteurs = set()
    for depot in depots:
        try:
            releve["fiches"][depot] = _lire(API % depot)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                releve["fiches"][depot] = {"absent": True}
            else:
                raise
        auteurs.add(depot.split("/")[0])
    for auteur in sorted(auteurs):
        releve["voisins"][auteur] = _lire(API_AUTEUR % auteur)
    return releve


# --- Le jugement (aucun reseau : c'est ici que les tests mordent) -----------

def licence_annoncee(fiche: dict) -> str | None:
    """L'identifiant de licence que l'editeur affiche, ou None s'il se tait."""
    carte = fiche.get("cardData") or {}
    licence = carte.get("license")
    if isinstance(licence, list):
        licence = licence[0] if licence else None
    if not licence:
        for etiquette in fiche.get("tags", []):
            if etiquette.startswith("license:"):
                licence = etiquette.split(":", 1)[1]
                break
    return licence.strip().lower() if isinstance(licence, str) else None


def comparer(registre: dict, releve: dict) -> dict:
    """Range chaque application dans UNE case, et n'en invente aucune.

    Les cinq cases sont exclusives, et la nuance entre les trois dernieres est
    tout l'interet : << je n'ai pas pu verifier >> n'est ni un accord ni un
    desaccord, et le confondre avec l'un des deux est la facon habituelle de
    fabriquer un vert.
    """
    verdict = {"concordent": [], "desaccords": [], "disparus": [],
               "non_comparables": [], "hors_hugging_face": [], "candidats": []}
    fiches = releve["fiches"]

    for app in registre["applications"]:
        depot = depot_de(app["source"])
        if depot is None:
            verdict["hors_hugging_face"].append(
                {"id": app["id"], "source": app["source"]})
            continue
        if "/blob/" in app["source"] or "/resolve/" in app["source"]:
            # Mesure du 21/09/2026, premier vrai passage : les deux voix
            # pointaient vers un FICHIER de `rhasspy/piper-voices`, un depot
            # collectif de 3 301 fichiers etiquete `mit`. Le registre, lui,
            # porte la licence de LA VOIX -- CC BY 4.0 pour SIWIS, domaine
            # public pour LibriVox -- qui est plus precise et plus protectrice.
            # Les compter comme desaccords faisait crier au loup ; et un outil
            # qui crie au loup finit debranche, donc muet le jour ou il a
            # raison.
            verdict["non_comparables"].append(
                {"id": app["id"], "depot": depot,
                 "motif": "la fiche vise un FICHIER dans un depot collectif ; "
                          "la licence du depot ne gouverne pas ce fichier"})
            continue
        fiche = fiches.get(depot)
        if fiche is None:
            verdict["non_comparables"].append(
                {"id": app["id"], "depot": depot, "motif": "fiche non relevee"})
            continue
        if fiche.get("absent"):
            verdict["disparus"].append({"id": app["id"], "depot": depot})
            continue

        annoncee = licence_annoncee(fiche)
        if annoncee is None:
            verdict["non_comparables"].append(
                {"id": app["id"], "depot": depot,
                 "motif": "l'editeur n'affiche aucune licence"})
            continue
        if annoncee not in EQUIVALENCES:
            verdict["non_comparables"].append(
                {"id": app["id"], "depot": depot,
                 "motif": "licence inconnue de la table : %r" % annoncee})
            continue
        attendu = EQUIVALENCES[annoncee]
        if attendu is None:
            verdict["non_comparables"].append(
                {"id": app["id"], "depot": depot,
                 "motif": "l'editeur ecrit %r, qui ne designe aucune licence" % annoncee})
            continue

        ligne = {"id": app["id"], "depot": depot, "chez_nous": app["licence"],
                 "chez_l_editeur": annoncee, "verifie_le": app["verifie_le"]}
        if _nu(attendu) in _nu(app["licence"]):
            verdict["concordent"].append(ligne)
        else:
            verdict["desaccords"].append(ligne)

        verdict["candidats"] += _candidats(app, depot, fiche, releve)

    return verdict


def _candidats(app: dict, depot: str, fiche: dict, releve: dict) -> list[dict]:
    """Des NOMS de modeles plus recents de la meme famille. Pas un conseil.

    Le Studio n'a aucun banc d'essai : dire << celui-ci est meilleur >> serait
    un chiffre invente. On rend donc le nom, sa licence et sa date, et un
    humain va voir.
    """
    auteur, nom = depot.split("/", 1)
    famille = _famille(nom)
    a_nous = fiche.get("lastModified") or ""
    trouves = []
    for voisin in releve.get("voisins", {}).get(auteur, []):
        autre = voisin.get("id", "")
        if autre == depot or "/" not in autre:
            continue
        if not _famille(autre.split("/", 1)[1]).lower() == famille.lower():
            continue
        if (voisin.get("lastModified") or "") <= a_nous:
            continue
        trouves.append({"pour": app["id"], "depot": autre,
                        "modifie_le": (voisin.get("lastModified") or "")[:10],
                        "licence": licence_annoncee(voisin) or "non affichee"})
    # Trois au plus, les plus recents : le premier passage en rendait 26 pour
    # huit applications, et un ticket hebdomadaire de 26 lignes ne se lit pas.
    return sorted(trouves, key=lambda c: c["modifie_le"], reverse=True)[:3]


# --- Le rapport ------------------------------------------------------------

def rapport(verdict: dict, releve: dict) -> str:
    lignes = ["# Relecture des licences chez leur éditeur", "",
              "Relevé le %s. Ce document est **engendré** ; il ne modifie rien."
              % releve.get("lu_le", "?"), ""]

    def bloc(titre, cles, entrees, vide):
        # `lignes.extend` et non `lignes += [...]` : la seconde forme ferait de
        # `lignes` une variable LOCALE a cette fonction imbriquee, et Python
        # leverait avant meme d'ecrire la premiere ligne.
        lignes.append("## %s" % titre)
        lignes.append("")
        if not entrees:
            lignes.extend([vide, ""])
            return
        lignes.append("| " + " | ".join(cles) + " |")
        lignes.append("|" + "---|" * len(cles))
        for e in entrees:
            lignes.append("| " + " | ".join(str(e.get(c.split(" ")[0], "")) for c in cles) + " |")
        lignes.append("")

    bloc("Désaccords — à trancher par un humain",
         ["id", "depot", "chez_l_editeur", "chez_nous"], verdict["desaccords"],
         "Aucun. Ce que le registre annonce est ce que l'éditeur affiche.")
    bloc("Fiches disparues", ["id", "depot"], verdict["disparus"],
         "Aucune.")
    bloc("Non comparables — dit, jamais compté comme vert",
         ["id", "depot", "motif"], verdict["non_comparables"],
         "Aucun.")
    bloc("Candidats plus récents de la même famille — des noms, pas un conseil",
         ["pour", "depot", "modifie_le", "licence"], verdict["candidats"],
         "Aucun.")
    bloc("Concordent", ["id", "depot", "chez_l_editeur", "verifie_le"],
         verdict["concordent"], "Aucun.")

    lignes += ["## Hors Hugging Face — aucune lecture automatique possible", "",
               "Conditions d'API et pages de fournisseurs : elles se lisent à la main.", ""]
    for e in verdict["hors_hugging_face"]:
        lignes.append("- `%s` → %s" % (e["id"], e["source"]))
    lignes.append("")
    return "\n".join(lignes)


def main() -> int:
    registre = json.loads(REGISTRE.read_text(encoding="utf-8"))
    depots = sorted({d for d in (depot_de(a["source"]) for a in registre["applications"]) if d})

    hors_ligne = None
    if "--hors-ligne" in sys.argv:
        hors_ligne = Path(sys.argv[sys.argv.index("--hors-ligne") + 1])

    if hors_ligne:
        releve = json.loads(hors_ligne.read_text(encoding="utf-8"))
    else:
        try:
            releve = relever(depots)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print("ECHEC DE LECTURE : %s" % exc, file=sys.stderr)
            print("Code 2 : rien n'a pu etre lu. Ce n'est PAS une concordance.",
                  file=sys.stderr)
            return 2

    if "--releve" in sys.argv:
        Path(sys.argv[sys.argv.index("--releve") + 1]).write_bytes(
            json.dumps(releve, ensure_ascii=False, indent=1).encode("utf-8"))

    verdict = comparer(registre, releve)
    if "--verdict" in sys.argv:
        Path(sys.argv[sys.argv.index("--verdict") + 1]).write_bytes(
            json.dumps(verdict, ensure_ascii=False, indent=1).encode("utf-8"))
    texte = rapport(verdict, releve)
    if "--rapport" in sys.argv:
        Path(sys.argv[sys.argv.index("--rapport") + 1]).write_bytes(texte.encode("utf-8"))
    else:
        print(texte)

    a_trancher = len(verdict["desaccords"]) + len(verdict["disparus"])
    print("\n%d concordent, %d desaccords, %d disparus, %d non comparables, "
          "%d hors Hugging Face, %d candidats."
          % (len(verdict["concordent"]), len(verdict["desaccords"]),
             len(verdict["disparus"]), len(verdict["non_comparables"]),
             len(verdict["hors_hugging_face"]), len(verdict["candidats"])),
          file=sys.stderr)
    return 1 if a_trancher else 0


if __name__ == "__main__":
    # La console Windows est en cp1252 : sans cette ligne le script PLANTE sur
    # la premiere fleche du rapport, et ce plantage sortait en code 1, c'est a
    # dire << un humain doit trancher >>. Mesure le 21/09/2026.
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- une panne n'est jamais un verdict
        import traceback
        traceback.print_exc()
        print("\nCode 2 : l'outil est tombe. Ce n'est NI une concordance, "
              "NI un desaccord -- rien n'a ete verifie. (%s)" % exc,
              file=sys.stderr)
        sys.exit(2)
