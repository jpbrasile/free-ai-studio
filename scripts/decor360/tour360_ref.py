"""Tour 360° en mode Références (Ref2VA) : chaque tronçon a sa clé de départ épinglée à l'image 0 et sa clé
d'arrivée à la dernière image (MiniMaxH3AddGuide, essai_epingles.py), et chaque élément croisé est un <Subject N>
défini par l'image de sa carte, jamais par une liste de ce qui n'est pas là (guide officiel h3-prompt-writing,
ref-en). Essai du 06/10 sur 60 -> 90° : le salon inventé par l'ancien tronçon (tour360_h3.py) a disparu.

  python tour360_ref.py <dossier de l'essai> [graine] [pas] [--sec]     (par la file : gpu, ~3,5 min/tronçon)
  -> <dossier>/tour360_ref[_<pas>]/troncon_<k>_g<graine>.mp4, planche_<k>.jpg, puis tour360_g<graine>.mp4
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import cartes_elements
import essai_epingles
import tour360_h3

NOMBRES = tour360_h3.NOMBRES


def place(fiche, cap, demi):
    """« at the left edge » / « in the centre » / « at the right edge » : où l'élément tombe dans le cadre."""
    a0, a1 = fiche["azimut"]
    milieu = ((a0 + a1) / 2 - cap + 180) % 360 - 180
    milieu = max(-demi, min(demi, milieu))
    return "at the left of the frame" if milieu < -demi / 3 else (
        "at the right of the frame" if milieu > demi / 3 else "in the centre of the frame")


def invite(fiches, cap, pas, demi, suite=False, arret=True):
    """Les six sections de ref-en pour un tronçon de cap à cap + pas ; rend (texte, cartes dans l'ordre des
    images 3, 4...). `suite` : le début vient du latent du tronçon précédent (MiniMaxH3MotionContext), pas d'une
    image ; seule la clé d'arrivée est une image (<Picture 1>), les cartes suivent (images 2, 3...). `arret=False` :
    tronçon du milieu d'une chaîne latente, la caméra passe par la clé d'arrivée sans ralentir (avec « slows and
    settles » à chaque tronçon, la chaîne s'arrête puis repart à chaque jointure, essai du 06/10)."""
    if suite:
        texte, sujets = invite(fiches, cap, pas, demi, arret=arret)
        return en_suite(texte, len(sujets)), sujets
    debut = cartes_elements.visibles(fiches, cap, demi)
    fin = cartes_elements.visibles(fiches, cap + pas, demi)
    chemin = cartes_elements.visibles(fiches, cap + pas / 2, demi + pas / 2)
    sujets = chemin[:7]                                   # 2 clés + 7 cartes = 9 images, le maximum de H3
    s = {f["nom"]: "<Subject %d>" % (i + 2) for i, f in enumerate(sujets)}
    noms = [f["nom"] for f in sujets]
    dans_debut, dans_fin = {f["nom"] for f in debut}, {f["nom"] for f in fin}
    jardin = "baie_jardin" in noms
    degres = NOMBRES.get(pas, str(pas))
    # amplitude = part du cadre qui change (base-en 4.3) ; moyenne : ne rien dire. Champ horizontal = 2 * demi
    part = pas / (2 * demi)
    mouvement = "pans right" + (" with small amplitude" if part < 0.25 else
                                " with large amplitude" if part > 0.6 else "") + " at slow speed"

    defs = ["<Picture 1> is the first frame of [Shot 1], the view of the living room before the camera turns.",
            "<Picture 2> is the last frame of [Shot 1], the view of the same living room after the camera has turned "
            "about %s degrees to the right." % degres,
            "<Subject 1> is the living room seen in <Picture 1> and <Picture 2>: cream plastered walls with a thin white "
            "baseboard, a beige carpet and a white ceiling, lit by soft afternoon daylight."]
    defs += ["%s is %s in <Picture %d>." % (s[f["nom"]], f["description"], i + 3) for i, f in enumerate(sujets)]

    passe = ", ".join(s[n] for n in noms)
    resume = ("[keyframe completion + reference generation] A single continuous shot in which the camera %s "
              "through <Subject 1>, from" % mouvement + " <Picture 1> to <Picture 2>"
              + (", passing %s." % passe if passe else ", along its plain walls."))

    garde = ["<Picture 1> ([Shot 1] first frame): fully_preserved - the shot starts exactly on this frame.",
             "<Picture 2> ([Shot 1] last frame): fully_preserved - the shot ends exactly on this frame.",
             "<Subject 1> (appears in [Shot 1]): fully_preserved - the same walls, baseboard, carpet, ceiling and light "
             "throughout."]
    garde += ["%s (appears in [Shot 1]): fully_preserved - the same shape, colour and material throughout." % s[n]
              for n in noms]

    def au_depart(n):
        f = next(x for x in sujets if x["nom"] == n)
        return "%s, %s, stands %s" % (s[n], f["description"], place(f, cap, demi))

    def a_l_arrivee(n):
        f = next(x for x in sujets if x["nom"] == n)
        return "%s %s" % (s[n], place(f, cap + pas, demi).replace("at the", "sits at the").replace("in the", "sits in the"))

    depart = [au_depart(n) for n in noms if n in dans_debut]
    phrases = ["The target video is a live-action, cinematic interior shot of a quiet living room in soft, even afternoon "
               "daylight, with a calm, still atmosphere. Only the camera moves.",
               "[Shot 1] The shot begins from <Picture 1>: at eye level, the camera stands in <Subject 1>, the cream "
               "plastered walls meeting the beige carpet along a thin white baseboard and the white ceiling at the top "
               "of the frame." + (" " + "; ".join(depart) + "." if depart else
                                  " A stretch of plain cream wall fills the frame.")]
    # syntaxe caméra du guide (base-en 4.3) : type + amplitude + vitesse, « revealing » nomme ce qui est révélé
    revele = [s[n] for n in noms if n not in dans_debut]
    phrases.append("The camera %s, revealing %s." % (mouvement,
        ", ".join(revele) if revele else "more of the plain cream wall of <Subject 1>"))
    for n in noms:
        f = next(x for x in sujets if x["nom"] == n)
        if n in dans_debut and n not in dans_fin:
            phrases.append("As the camera turns, %s drifts toward the left edge and slides out of the frame." % s[n])
        elif n in dans_debut:
            phrases.append("%s drifts from right to left across the frame, keeping its shape, colour and place in "
                           "the room." % s[n])
        elif n in dans_fin:
            phrases.append("%s, %s, enters from the right edge of the frame and comes into full view." % (s[n], f["description"]))
        else:
            phrases.append("%s, %s, enters from the right edge, crosses the frame and leaves on the left." % (s[n], f["description"]))
    phrases.append("The baseboard and the carpet run as one continuous line across the frame while the view turns, "
                   "and the light on the walls stays soft and even, with a faint warm gradient.")
    arrivee = [a_l_arrivee(n) for n in noms if n in dans_fin]
    # ancres concrètes dans la tournure du guide (ref-en 5.3) : « the shot ends on <Picture N> »
    phrases.append(("The pan slows and settles, and the shot ends on <Picture 2>" if arret else
                    "Keeping its steady speed, the pan reaches the end of the shot, and the shot ends on <Picture 2>")
                   + " with its framing, spacing and composition"
                   + (", where " + ", ".join(arrivee) + "." if arrivee else ", a stretch of plain cream wall."))
    phrases.append("The whole shot is one continuous take; the walls, doors, windows and furniture stay perfectly still"
                   + (", and only the garden leaves stir gently outside the glass wall." if jardin else "."))

    texte = "\n".join([
        "subject_definitions:", *defs, "",
        "summary:", resume, "",
        "retention_analysis:", *garde, "",
        "detailed_description:", " ".join(phrases[:1]), " ".join(phrases[1:]), "",
        "overall_soundscape:",
        "Quiet indoor room tone continues throughout, with birds singing faintly outside in the garden.", "",
        "non_diegetic_music:", "N/A", ""])
    return texte, sujets


def en_suite(texte, n_cartes):
    """Le tronçon enchaîné : plus de première image ; la clé d'arrivée devient <Picture 1>, chaque carte recule
    d'un rang. Le début est décrit comme la continuation, sans coupe, du plan précédent (README du nœud : le
    départ tenu par le latent ne se décrit pas autrement qu'il n'est)."""
    lignes = [x for x in texte.split("\n") if not x.startswith("<Picture 1> ")]
    texte = "\n".join(lignes)
    # ref-en, types de tâche : continuer une vidéo existante avec une image en dernière image
    texte = texte.replace("[keyframe completion + reference generation]",
                          "[video continuation + keyframe completion + reference generation]")
    texte = texte.replace("<Picture 2>", "<Picture §>")
    texte = texte.replace("seen in <Picture 1> and <Picture §>", "seen in <Picture §>")
    texte = texte.replace("from <Picture 1> to <Picture §>",
                          "continuing the pan of the previous shot without a cut, to <Picture §>")
    texte = texte.replace("[Shot 1] The shot begins from <Picture 1>:",
                          "[Shot 1] The shot continues the previous shot without a cut, opening on the exact framing "
                          "where it ended:")
    for k in range(3, 3 + n_cartes):
        texte = texte.replace("<Picture %d>" % k, "<Picture %d>" % (k - 1))
    assert "<Picture 1>" not in texte, "une <Picture 1> de départ reste dans la suite"
    return texte.replace("<Picture §>", "<Picture 1>")


def planche(clip, cle0, cle1, sortie):
    """8 images du tronçon sous ses deux clés."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip), "-vf",
                    "select='not(mod(n\\,17))',scale=336:192,tile=8x1", "-frames:v", "1", str(sortie) + ".tmp.png"],
                   check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(cle0), "-i", str(cle1), "-i", str(sortie) + ".tmp.png",
                    "-filter_complex", "[0]scale=336:192[a];[1]scale=336:192[b];[a][b]hstack,pad=2688:192[h];[h][2]vstack",
                    str(sortie)], check=True)
    Path(str(sortie) + ".tmp.png").unlink()


def main(dossier, graine=11, pas=30, sec=False):
    dossier = Path(dossier).resolve()
    sortie = dossier / ("tour360_ref" + ("" if pas == 45 else "_%d" % pas))
    sortie.mkdir(exist_ok=True)
    fiches = json.loads((dossier / "cartes" / "cartes_lieu.json").read_text(encoding="utf-8"))
    cfg = json.loads((dossier / "scene.json").read_text(encoding="utf-8"))
    cam = next(c for c in cfg["cameras"] if c["nom"] == "verif_plaque")
    demi = math.degrees(math.atan(cfg["taille"][0] / 2 / cam["f"]))
    cles = [dossier / "plaque.png"] + [dossier / "rendus" / ("rendu_r%03d.png" % a) for a in range(pas, 360, pas)] \
        + [dossier / "plaque.png"]
    troncons = []
    for k in range(len(cles) - 1):
        texte, sujets = invite(fiches, cam["lacet"] + k * pas, pas, demi)
        f = sortie / ("troncon_%02d_g%d.mp4" % (k, graine))
        (sortie / ("invite_%02d.txt" % k)).write_text(texte, encoding="utf-8")
        if sec:
            print(k, len(texte.split()), "mots", [x["nom"] for x in sujets], flush=True)
            continue
        if not f.is_file():
            rc = essai_epingles.main([str(sortie), str(sortie / ("invite_%02d.txt" % k)), str(f), str(cles[k]),
                                      str(cles[k + 1]), *(str(dossier / "cartes" / x["image"]) for x in sujets),
                                      "--graine", str(graine)])
            if rc:
                raise SystemExit("tronçon %d en échec (rc %d)" % (k, rc))
            planche(f, cles[k], cles[k + 1], sortie / ("planche_%02d.jpg" % k))
            print("TRONCON", k, f, flush=True)
        troncons.append(f)
    if not sec:
        final = sortie / ("tour360_g%d.mp4" % graine)
        tour360_h3.bout_a_bout(troncons, final)
        print("FAIT", final, len(troncons), "tronçons", flush=True)


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if x != "--sec"]
    main(args[0], *(int(x) for x in args[1:3]), sec="--sec" in sys.argv)
