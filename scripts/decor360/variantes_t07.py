"""Murs déformés dans le tour Ref2VA (tronçon 7, 210 -> 240°) : trois variantes, une seule chose changée chacune
(propriétaire, 06/10 : « oui lance A, B et C sur le tronçon 7 »).

  A : Ref2VA, clés épinglées par AddGuide SEULEMENT (plus en <Picture 1>/<Picture 2>), cartes en <Subject N>
  B : comme le tour (clés épinglées + références), SANS LoRA turbo, 20 pas (réglage du modèle officiel
      video_minimax_h3_r2v.json : BasicScheduler simple 20)
  D : le tour tel quel, cartes redressées en perspective (propriétaire : « les murs sont arrondis »)
  C : FL2VA comme l'ancien tour (modèle et LoRA fl2v 768p, first/last natifs), invite du chemin sans liste de ce
      qui n'est pas là, sans cartes

  python variantes_t07.py <dossier de l'essai> [A B C]       (par la file : gpu)
"""
import json
import math
import re
import sys
from pathlib import Path

import essai_epingles
import tour360_ref
import travelling_h3

K, PAS, GRAINE = 7, 30, 11


def sans_cles(texte, n_cartes):
    """L'invite du tour sans <Picture 1>/<Picture 2> : les clés ne sont plus des références, les cartes reculent de
    deux rangs."""
    lignes = [x for x in texte.split("\n") if not re.match(r"<Picture [12]> ", x)]
    texte = "\n".join(lignes)
    texte = texte.replace(" seen in <Picture 1> and <Picture 2>", "")
    texte = texte.replace("from <Picture 1> to <Picture 2>", "from its opening framing to its closing framing")
    texte = texte.replace("[Shot 1] The shot begins from <Picture 1>:", "[Shot 1] The shot begins:")
    texte = texte.replace("composition of <Picture 2>", "final composition")
    for k in range(3, 3 + n_cartes):
        texte = texte.replace("<Picture %d>" % k, "<Picture %d>" % (k - 2))
    assert "<Picture %d>" % (n_cartes + 1) not in texte
    return texte


def en_mots(texte, sujets):
    """Le chemin du tour en mots, pour FL2VA (pas de <Subject N> hors Ref2VA, guide base-en)."""
    desc = tour360_ref_descriptions(sujets)
    corps = texte.split("detailed_description:\n", 1)[1].split("\n\noverall_soundscape", 1)[0]
    corps = corps.split("\n", 1)[1]                                     # sans la phrase de style
    corps = corps.replace("[Shot 1] The shot begins from <Picture 1>: ", "")
    corps = corps.replace("composition of <Picture 2>", "composition of Picture 2")
    corps = corps.replace("<Subject 1>", "the living room")
    for etiquette, d in desc.items():
        corps = corps.replace("%s, %s," % (etiquette, d), d + ",")
        corps = corps.replace(etiquette, "the " + re.sub(r"^(a|an|two|the) ", "", d).split(",")[0])
    corps = re.sub(r"(\. )([a-z])", lambda m: m.group(1) + m.group(2).upper(), corps)
    return corps[0].upper() + corps[1:]


def tour360_ref_descriptions(sujets):
    return {"<Subject %d>" % (i + 2): f["description"] for i, f in enumerate(sujets)}


def main(dossier, quoi):
    dossier = Path(dossier).resolve()
    sortie = dossier / "variantes_t07"
    sortie.mkdir(exist_ok=True)
    fiches = json.loads((dossier / "cartes" / "cartes_lieu.json").read_text(encoding="utf-8"))
    cfg = json.loads((dossier / "scene.json").read_text(encoding="utf-8"))
    cam = next(c for c in cfg["cameras"] if c["nom"] == "verif_plaque")
    demi = math.degrees(math.atan(cfg["taille"][0] / 2 / cam["f"]))
    cle0, cle1 = (dossier / "rendus" / ("rendu_r%03d.png" % a) for a in (K * PAS, K * PAS + PAS))
    texte, sujets = tour360_ref.invite(fiches, cam["lacet"] + K * PAS, PAS, demi)
    cartes = [str(dossier / "cartes" / f["image"]) for f in sujets]

    for v in quoi:
        f = sortie / ("t07_%s_g%d.mp4" % (v, GRAINE))
        if f.is_file():
            continue
        if v == "A":
            inv = sans_cles(texte, len(sujets))
            d, _ = essai_epingles.demande(inv, [str(cle0), str(cle1), *cartes], GRAINE, 124)
            g = d["graphe"]
            # les clés restent chargées (60, 61) pour AddGuide, mais sortent de la liste des références
            refs = [k for k in g["10"]["inputs"] if k.startswith("ref_images.")]
            for k in refs:
                del g["10"]["inputs"][k]
            for i in range(len(cartes)):
                g["10"]["inputs"]["ref_images.ref_image_%d" % i] = ["6%d" % (i + 2), 0]
            rc = essai_epingles.lancer(d, inv, f)
        elif v == "D":
            # le tour tel quel, seules les cartes changent : redressées (cartes_elements.py --redresser)
            d, _ = essai_epingles.demande(texte, [str(cle0), str(cle1), *cartes], GRAINE, 124)
            rc = essai_epingles.lancer(d, texte, f)
        elif v == "B":
            # cartes du tour (courbes) : seul le LoRA change
            courbes = [c.replace(".png", "_courbe.png") if Path(c.replace(".png", "_courbe.png")).is_file() else c
                       for c in cartes]
            d, _ = essai_epingles.demande(texte, [str(cle0), str(cle1), *courbes], GRAINE, 124)
            g = d["graphe"]
            g["9"]["inputs"]["model"] = ["1", 0]
            g["13"]["inputs"]["model"] = ["1", 0]
            g["9"]["inputs"]["steps"] = 20
            del g["2"]
            d["delai_s"] = 5400
            rc = essai_epingles.lancer(d, texte, f)
        else:
            consigne = {"mouvement": en_mots(texte, sujets),
                        "premiere": "the living room, seen from where the camera stands.",
                        "derniere": "the same living room, the camera turned further to the right.",
                        "camera": {"mouvement": "pano_droite", "vitesse": "lente"}}
            (sortie / "consigne_C.json").write_text(json.dumps(consigne, indent=1, ensure_ascii=False), encoding="utf-8")
            rc, _ = travelling_h3.clip(cle0, cle1, f, GRAINE, consigne=consigne)
        print("VARIANTE", v, "rc", rc, f, flush=True)
        if not rc:
            tour360_ref.planche(f, cle0, cle1, sortie / ("planche_%s.jpg" % v))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["A", "B", "C"])
