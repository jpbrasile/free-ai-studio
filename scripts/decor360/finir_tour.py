"""Finir un tour (skill h3-syntaxe : « 4K d'abord, GIMM ensuite, musique en dernier »), d'un seul travail de la file :
agrandir_ici.py (FlashVSR, carte d'ici) -> gimm_vfi.py (60 i/s à pas égaux, chemin mesuré sur le clip d'avant
l'agrandissement) -> musique_ici.py creer (route « ici » du Studio, MUSIQUE_OU=ici, repli Modal ; propriétaire, 06/10 :
« music local too ») -> musique_ici.py poser. Chaque étape déjà faite est sautée ; un échec arrête et le dit.

  python finir_tour.py <tour.mp4> <dossier de sortie> "<style de musique>"   (par la file : gpu)
  -> <sortie>/tour_4k.mp4, tour_4k_60.mp4, musique.flac, tour_final.mp4
"""
import os
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent


def etape(nom, cible, args, env=None):
    if cible.is_file():
        print("DEJA", nom, cible, flush=True)
        return True
    print("ETAPE", nom, flush=True)
    r = subprocess.run([sys.executable, str(ICI / args[0])] + [str(a) for a in args[1:]], env=env)
    ok = r.returncode == 0 and cible.is_file()
    print(("FAIT " if ok else "ECHEC ") + nom, "rc", r.returncode, cible, flush=True)
    return ok


def main(tour, sortie, style):
    tour, sortie = Path(tour).resolve(), Path(sortie).resolve()
    sortie.mkdir(parents=True, exist_ok=True)
    k4, k60, son, final = (sortie / n for n in ("tour_4k.mp4", "tour_4k_60.mp4", "musique.flac", "tour_final.mp4"))
    if not etape("4K", k4, ["agrandir_ici.py", tour, k4]):
        return 1
    if not etape("GIMM", k60, ["gimm_vfi.py", k4, k60, tour]):
        return 1
    if not son.is_file():
        ok = etape("musique ici", son, ["musique_ici.py", "creer", style, son],
                   dict(os.environ, MUSIQUE_OU="ici"))
        if not ok:
            print("REPLI musique chez Modal", flush=True)
            if not etape("musique modal", son, ["musique_ici.py", "creer", style, son],
                         dict(os.environ, MUSIQUE_OU="modal")):
                print("SANS MUSIQUE : tour_4k_60.mp4 est le résultat", flush=True)
                return 2
    return 0 if etape("poser", final, ["musique_ici.py", "poser", k60, son, final]) else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
