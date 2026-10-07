"""Validation du plan au sol SANS photo sur des lieux variés (propriétaire, 06/10 : « validate the 2d plan on
various use cases castle, forest… ») : chaque description passe par le chat du Studio comme le fera l'étape 6
(plan_piece.consigne_plan_texte -> lire_texte), puis par le relecteur (consigne_relecture -> lire_relecture).
Appel du chat : essai_plan_studio.chat (conteneur sandbox-manager vivant, sans `import app`).

  python essai_plans_texte.py <dossier de sortie> [nom du cas ...] [--depuis <sortie d'un essai précédent>]
  (--depuis : les mêmes plans proposés, relus à nouveau ; pour comparer deux relecteurs)
  -> <sortie>/<cas>/{reponse,plan,relecture,plan_relu}.json, planche.png (vue de dessus, proposé | relu), bilan.json
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import plan_piece  # noqa: E402
import tour360  # noqa: E402
from essai_plan_studio import chat  # noqa: E402

CAS = {
    "chateau": "The great hall of a medieval castle: stone walls with tapestries, a huge fireplace, a long oak "
               "banquet table with benches, a throne on a dais at the far end, torches, tall narrow windows.",
    "foret": "A forest clearing at dawn: tall oak and pine trees all around, a small campfire ringed with stones, "
             "a fallen mossy log to sit on, a canvas tent, a narrow path leaving through the trees.",
    "plage": "A sandy tropical beach: palm trees, a wooden lifeguard tower, two deck chairs under a striped "
             "parasol, a beached rowing boat, the sea in front and a line of palms behind.",
    "rue": "A narrow cobbled street in a medieval village: half-timbered houses on both sides with doors and "
           "windows, a stone well in the middle, a wooden cart, a lantern on a post.",
    "cuisine": "A modern open kitchen: white cabinets along the walls, a kitchen island with three bar stools, a "
               "big fridge, a window over the sink, a dining table with four chairs.",
    "chambre": "A child's bedroom: a single bed with a quilt, a desk and chair under the window, a bookshelf full "
               "of toys, a rug, a wardrobe, posters on the walls.",
    "grotte": "A large limestone cave: rock pillars, boulders, an underground lake, stalagmites, a narrow opening "
              "letting in daylight.",
    "passerelle": "The bridge of a starship: a captain's chair in the middle, two control consoles in front, a huge "
                  "viewport showing stars, sliding doors at the back.",
}
COULEURS = {"arbre": "#4a4", "rocher": "#888", "colonne": "#aaa", "batiment": "#c96", "objet": "#c6c", "surface": "#8bd"}


def dessus(plan, titre, px=None):
    """Vue de dessus en PNG (la page du Studio montre la même en SVG)."""
    x0, x1, z0, z1 = plan["piece"]
    px = px or min(60.0, 560.0 / max(x1 - x0, z1 - z0))
    w, h = int((x1 - x0) * px) + 40, int((z1 - z0) * px) + 60
    im = Image.new("RGB", (w, h), "#f4f1ea" if not plan.get("dehors") else "#e6efe0")
    d = ImageDraw.Draw(im)
    X = lambda x: 20 + (x - x0) * px                                   # noqa: E731
    Z = lambda z: 40 + (z1 - z) * px                                   # noqa: E731  (z vers le haut de l'image)
    d.rectangle([X(x0), Z(z1), X(x1), Z(z0)], outline="#333" if not plan.get("dehors") else "#7a7", width=2)
    for e in sorted(plan["elements"], key=lambda e: e["genre"] not in plan_piece.PLATS):
        a, b, c, f = e["emprise"]
        couleur = COULEURS.get(e["genre"], plan_piece.COULEURS.get(e["genre"], "#99a"))
        d.rectangle([X(a), Z(f), X(b), Z(c)], fill=couleur, outline="#222")
        d.text((X(a) + 2, Z(f) + 2), e["nom"][:14], fill="#000")
    d.polygon([(X(0), Z(0)), (X(-0.25), Z(-0.3)), (X(0.25), Z(-0.3))], fill="#d22")
    d.line([X(0), Z(0), X(0), Z(min(z1, 2.0))], fill="#d22", width=2)
    d.text((6, 6), titre, fill="#000")
    return im


def un_cas(sortie, nom, description, depuis=None):
    dossier = sortie / nom
    dossier.mkdir(parents=True, exist_ok=True)
    bilan = {"cas": nom}
    reponse = ((depuis / nom / "reponse.txt").read_text(encoding="utf-8") if depuis else
               chat(dossier, plan_piece.consigne_plan_texte(description), []))
    (dossier / "reponse.txt").write_text(reponse, encoding="utf-8")
    try:
        plan, geo, remarques = plan_piece.lire_texte(reponse)
    except ValueError as exc:
        bilan["echec"] = str(exc)
        return bilan, None
    (dossier / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    bruts = plan_piece._json_de(reponse).get("elements") or []
    bilan.update(dehors=bool(plan.get("dehors")), piece=plan["piece"], plafond=plan["plafond"],
                 elements=len(plan["elements"]), remarques=remarques,
                 genres_inconnus=sorted({str(e.get("genre")) for e in bruts if e.get("genre") not in
                                         plan_piece.GENRES}),
                 constats_avant=plan_piece.defauts(plan, geo))
    # le relecteur du Studio tel quel (tour360.relire_plan : seconde passe si des défauts restent)
    etat = {"plan": plan, "mesure": geo, "description": description, "plan_remarques": []}
    passes = []

    def chat_compte(consigne, images):
        rep = chat(dossier, consigne, images, "free-ai-max")      # comme app._tour360_relecteur
        passes.append(rep)
        (dossier / ("reponse_relecture_%d.txt" % len(passes))).write_text(rep, encoding="utf-8")
        return rep

    bilan["relecture"] = dict(tour360.relire_plan(etat, chat_compte), passes=len(passes),
                              remarques=etat["plan_remarques"])
    relu = etat["plan"]
    if relu is not plan:
        (dossier / "plan_relu.json").write_text(json.dumps(relu, indent=1, ensure_ascii=False), encoding="utf-8")
    cartes = plan_piece.cartes_du_plan(relu, geo)
    bilan.update(elements_relus=len(relu["elements"]),
                 constats_apres=plan_piece.defauts(relu, geo),
                 devant=sum(plan_piece.cadre_vu(e, relu, geo) is not None for e in relu["elements"]),
                 murs_nus=sum(c["nom"].startswith("mur_nu_") for c in cartes),
                 parties=len(plan_piece.scene_du_plan(relu, geo)["boites"]))
    a, b = dessus(plan, nom + " : propose"), dessus(relu, nom + " : relu")
    planche = Image.new("RGB", (a.width + b.width + 10, max(a.height, b.height)), "white")
    planche.paste(a, (0, 0))
    planche.paste(b, (a.width + 10, 0))
    planche.save(dossier / "planche.png")
    return bilan, planche


def main(sortie, noms, depuis=None):
    sortie = Path(sortie).resolve()
    sortie.mkdir(parents=True, exist_ok=True)
    bilans, planches = [], []
    for nom in noms or list(CAS):
        bilan, planche = un_cas(sortie, nom, CAS[nom], Path(depuis) if depuis else None)
        bilans.append(bilan)
        if planche:
            planches.append(planche)
        print(json.dumps(bilan, ensure_ascii=False), flush=True)
    (sortie / "bilan.json").write_text(json.dumps(bilans, indent=1, ensure_ascii=False), encoding="utf-8")
    if planches:
        largeur = max(p.width for p in planches)
        tout = Image.new("RGB", (largeur, sum(p.height + 10 for p in planches)), "white")
        y = 0
        for p in planches:
            tout.paste(p, (0, y))
            y += p.height + 10
        tout.save(sortie / "planche_tous.png")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    d = None
    if "--depuis" in a:
        i = a.index("--depuis")
        d = a[i + 1]
        del a[i:i + 2]
    sys.exit(main(a[0], a[1:], d))
