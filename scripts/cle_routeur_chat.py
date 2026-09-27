"""La cle du routeur hors des copies du chat (docs/SAUVEGARDES.md, proposition (1), 27/09/2026).

Open WebUI garde la cle interne du routeur EN CLAIR dans sa base (`webui.db`,
table `config` : `openai.api_keys`, `image_generation.openai.api_key`,
`audio.stt.openai.api_key`, `audio.tts.openai.api_key` ; mesure du 26/09).
Chaque copie du volume du chat etait donc une sauvegarde de secret.

    python cle_routeur_chat.py retirer  <dossier>   (sauvegarder.ps1, sur une COPIE)
    python cle_routeur_chat.py remettre <dossier>   (restaurer.ps1, remettre-cle-routeur.ps1)

La cle vient de la variable d'environnement FAS_CLE_ROUTEUR, jamais d'un
argument : un argument se lit dans la liste des processus. Ce script ne
l'affiche jamais. Il tourne dans un conteneur jetable (image d'Open WebUI, qui
a python et sqlite) ; la derniere ligne qu'il ecrit est lue par PowerShell :

    RESULTAT lignes=<n> restes=<fichiers separes par des virgules, ou rien>

`retirer` remplace la cle par MARQUE (et non par du vide : un chat restaure sans
sa cle se voit alors refuser par le routeur, au lieu de parler a vide), avec
`secure_delete` pour que l'ancien texte ne survive pas dans les pages liberees,
puis relit TOUS les fichiers du dossier, octet par octet. S'il en reste une
trace dans la base, il la compacte (VACUUM) et relit encore. S'il en reste une
ailleurs, il le dit et sort en 3 : la sauvegarde s'arrete plutot que de porter
la cle.
"""
import os
import sqlite3
import sys
from pathlib import Path

MARQUE = "cle-du-routeur-retiree-par-la-sauvegarde"
BLOC = 1 << 20


def fichiers_qui_portent(racine: Path, motif: bytes) -> list:
    """Les fichiers de `racine` qui contiennent `motif`, lus par blocs qui se chevauchent."""
    trouves = []
    for chemin in sorted(p for p in racine.rglob("*") if p.is_file() and not p.is_symlink()):
        reste = b""
        with open(chemin, "rb") as f:
            while True:
                bloc = f.read(BLOC)
                if not bloc:
                    break
                vu = reste + bloc
                if motif in vu:
                    trouves.append(chemin.relative_to(racine).as_posix())
                    break
                # La fin de TOUT ce qui a ete lu, pas du seul dernier bloc : un
                # bloc plus court que le motif le couperait sinon en trois.
                reste = vu[-(len(motif) - 1):]
    return trouves


def ouvrir(base: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(base))
    # Ecrase de zeros ce que l'UPDATE libere : sans cela, l'ancienne valeur peut
    # rester lisible dans une page libre du fichier.
    con.execute("PRAGMA secure_delete=ON")
    return con


def fermer(con: sqlite3.Connection) -> None:
    con.commit()
    # Tout le journal WAL rentre dans la base et le fichier -wal revient a zero.
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()


def remplacer(base: Path, avant: str, apres: str) -> int:
    con = ouvrir(base)
    n = con.execute("UPDATE config SET value = replace(value, ?, ?) WHERE instr(value, ?) > 0",
                    (avant, apres, avant)).rowcount
    fermer(con)
    return n


def retirer(racine: Path, cle: str) -> tuple:
    base = racine / "webui.db"
    n = remplacer(base, cle, MARQUE) if base.is_file() else 0
    restes = fichiers_qui_portent(racine, cle.encode())
    if any(r.startswith("webui.db") for r in restes) and base.is_file():
        con = ouvrir(base)
        con.execute("VACUUM")
        fermer(con)
        restes = fichiers_qui_portent(racine, cle.encode())
    return n, restes


def remettre(racine: Path, cle: str) -> int:
    base = racine / "webui.db"
    return remplacer(base, MARQUE, cle) if base.is_file() else 0


def main(argv: list) -> int:
    if len(argv) != 3 or argv[1] not in ("retirer", "remettre"):
        print("usage : cle_routeur_chat.py retirer|remettre <dossier>")
        return 2
    cle = os.environ.get("FAS_CLE_ROUTEUR", "").strip()
    if len(cle) < 16:
        # Une cle trop courte ferait remplacer n'importe quel bout de texte.
        print("RESULTAT erreur=cle-absente-ou-trop-courte")
        return 2
    racine = Path(argv[2])
    if argv[1] == "retirer":
        n, restes = retirer(racine, cle)
        print("RESULTAT lignes=%d restes=%s" % (n, ",".join(restes)))
        return 3 if restes else 0
    n = remettre(racine, cle)
    print("RESULTAT lignes=%d restes=" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
