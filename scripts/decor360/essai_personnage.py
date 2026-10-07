"""Essai : un personnage dans le tour 360° (propriétaire, 06/10 : « je vise de mettre des personnages dans la pièce »,
puis « oui lance l'essai avec Leila sur 10 s (2*5) en respectant le skill »).

Même chaîne que le tour (latent_chaine.preparer : 2 tronçons de 60° enchaînés par le latent, épingle finale seule,
vues exactes du panorama épinglées), avec trois changements :
- invites Ref2VA écrites à la main (le personnage = <Subject 1>, défini par les photos de sa fiche) ;
- les vues épinglées dont le champ contient le secteur du personnage sont retirées (la vue exacte y montre le
  fauteuil vide : l'épingler effacerait le personnage) ;
- la clé d'arrivée du 1er tronçon (fauteuil vide) n'est pas mise en référence.

  python essai_personnage.py preparer <dossier essai> <travail> <pano.png> <invite_1> <invite_2> <photo>...
  python essai_personnage.py local <travail> [clip.mp4]  (par la file dsh3, gpu ; tronçons recollés dans clip.mp4)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import latent_chaine  # noqa: E402

CAP0, PAS = 60, 60
SECTEUR = (65.0, 165.0)   # caps dont le champ (demi-champ 36,6°, marge 5°) voit le fauteuil (106-124° en cap)
# la bibliothèque entre au bord droit à la fin du 1er tronçon : sans sa carte, H3 en inventait une vide (06/10)
CARTES_1 = ["portes_droite.png", "porte_bois.png", "fauteuil.png", "lampe.png", "grande_bibliotheque.png"]
CARTES_2 = ["fauteuil.png", "lampe.png", "grande_bibliotheque.png"]


def hors_secteur(angle):
    return not SECTEUR[0] <= angle <= SECTEUR[1]


def preparer(dossier, travail, pano, invite_1, invite_2, photos):
    import essai_epingles
    import tour360_ref
    textes = [Path(invite_1).read_text(encoding="utf-8"), Path(invite_2).read_text(encoding="utf-8")]
    photos = [{"image": str(Path(p).resolve())} for p in photos]

    def invite(fiches, cap, pas, demi, suite=False, arret=True):
        cartes = [{"image": c} for c in (CARTES_2 if suite else CARTES_1)]
        return textes[1 if suite else 0], cartes + photos

    demande = essai_epingles.demande

    def sans_cle_arrivee(inv, images, graine, longueur):
        return demande(inv, [images[0], *images[2:]], graine, longueur)

    p1, ps = latent_chaine.pins_1, latent_chaine.pins_suite
    tour360_ref.invite = invite
    essai_epingles.demande = sans_cle_arrivee
    latent_chaine.pins_1 = lambda pas: [f for f in p1(pas) if hors_secteur(CAP0 + pas * f / 123)]
    latent_chaine.pins_suite = lambda pas: [f for f in ps(pas)
                                            if hors_secteur(CAP0 + PAS + pas * (f - 22 + 1) / 119)]
    print("épingles gardées : tronçon 1", [round(CAP0 + PAS * f / 123, 1) for f in latent_chaine.pins_1(PAS)],
          "tronçon 2", [round(CAP0 + PAS + PAS * (f - 21) / 119, 1) for f in latent_chaine.pins_suite(PAS)],
          flush=True)
    latent_chaine.preparer(dossier, travail, graine=11, pas=PAS, cap0=CAP0, n=2, arret_final=True,
                           epingle_milieu=False, pano=pano)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "preparer":
        preparer(a[1], a[2], a[3], a[4], a[5], a[6:])
    else:
        rc = latent_chaine.local(a[1])
        if rc or len(a) < 3:
            sys.exit(rc)
        import subprocess    # les tronçons recollés en un seul clip (copie, sans réencodage)
        clips = sorted(Path(a[1]).glob("clip_*.mp4"))
        (Path(a[1]) / "liste.txt").write_text("".join("file '%s'\n" % p.name for p in clips), encoding="utf-8")
        sys.exit(subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i",
                                 str(Path(a[1]) / "liste.txt"), "-c", "copy", a[2]]).returncode)
