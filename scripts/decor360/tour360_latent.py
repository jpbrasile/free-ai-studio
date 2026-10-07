"""Tour 360° enchaîné par le LATENT (propriétaire, 06/10 : « oui, passe le tour avant B ») : 12 tronçons de 30° en
3 groupes de 4. Dans un groupe, un seul graphe (latent_chaine.preparer) : le 1er tronçon part de sa clé épinglée,
les 3 suivants partent du latent du précédent (MotionContext) ; chacun finit sur sa clé épinglée, sans ralentir
sauf le dernier tronçon du tour. Chaque groupe repart d'une clé : la dérive ne s'accumule pas sur 12 tronçons.

  python tour360_latent.py <dossier de l'essai> [graine] [--bouts] [--groupes 0,1] [--nom dossier] [--pano pano.png] [--pas 60 --par-groupe 3]
      (par la file : gpu, ~15 min par groupe sur la 4090)
  -> <dossier>/tour360_latent[_bouts]/troncon_<k>.mp4, planche_<k>.jpg, tour360_latent_g<graine>.mp4
  --bouts : clé d'arrivée épinglée au dernier tronçon du groupe seulement (latent_chaine, epingle_milieu=False).
  --pano : 3 vues exactes de plus par tronçon (7,5°, 15°, 22,5°), épinglées (latent_chaine.preparer).
  --groupes : seulement ces groupes (essai) ; le tour complet n'est collé que si les 3 sont faits.
"""
import shutil
import sys
from pathlib import Path

import latent_chaine
import tour360_h3
import tour360_ref



def main(dossier, graine=11, bouts=False, groupes=None, nom=None, pano=None, pas=30, par_groupe=4):
    dossier = Path(dossier).resolve()
    sortie = dossier / (nom or "tour360_latent" + ("_bouts" if bouts else ""))
    sortie.mkdir(exist_ok=True)
    troncons = []
    n_groupes = 360 // pas // par_groupe
    groupes = range(n_groupes) if groupes is None else groupes
    for gr in groupes:
        cap0 = gr * par_groupe * pas
        travail = sortie / ("groupe_%d" % gr)
        clips = sorted(travail.glob("clip_*.mp4"))
        if len(clips) < par_groupe:
            latent_chaine.preparer(dossier, travail, graine=graine, pas=pas, cap0=cap0, n=par_groupe,
                                   arret_final=gr == n_groupes - 1, epingle_milieu=not bouts,
                                   pano=pano)
            rc = latent_chaine.local(travail)
            clips = sorted(travail.glob("clip_*.mp4"))
            if rc or len(clips) < par_groupe:
                raise SystemExit("groupe %d en échec (rc %d, %d clips) : %s" % (gr, rc, len(clips),
                                                                               travail / "sortie.log"))
        for i, c in enumerate(clips):
            k = gr * par_groupe + i
            f = sortie / ("troncon_%02d_g%d.mp4" % (k, graine))
            shutil.copyfile(c, f)
            tour360_ref.planche(f, latent_chaine.cle_de(dossier, k * pas), latent_chaine.cle_de(dossier, (k + 1) * pas),
                                sortie / ("planche_%02d.jpg" % k))
            print("TRONCON", k, f, flush=True)
            troncons.append(f)
    if len(troncons) < 360 // pas:
        print("FAIT", len(troncons), "tronçons, pas de tour complet", flush=True)
        return
    final = sortie / ("tour360_latent_g%d.mp4" % graine)
    tour360_h3.bout_a_bout(troncons, final)
    print("FAIT", final, len(troncons), "tronçons", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    groupes = None
    if "--groupes" in a:
        i = a.index("--groupes")
        groupes = [int(x) for x in a[i + 1].split(",")]
        del a[i:i + 2]
    nom = None
    if "--nom" in a:
        i = a.index("--nom")
        nom = a[i + 1]
        del a[i:i + 2]
    pas, par_groupe = 30, 4
    if "--pas" in a:                                  # 360° en 30 s : --pas 60 --par-groupe 3 (6 clips de 5 s)
        i = a.index("--pas")
        pas, par_groupe = int(a[i + 1]), int(a[i + 3])
        del a[i:i + 4]
    pano = None
    if "--pano" in a:
        i = a.index("--pano")
        pano = a[i + 1]
        del a[i:i + 2]
    bouts = "--bouts" in a
    a = [x for x in a if x != "--bouts"]
    main(a[0], *(int(x) for x in a[1:2]), bouts=bouts, groupes=groupes, nom=nom, pano=pano, pas=pas, par_groupe=par_groupe)
