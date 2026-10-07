"""Essai réel de l'étape « plan » du tour 360° (PLAN 21.6 étape 1) : la même consigne que le Studio
(plan_piece.consigne_plan), envoyée au chat du Studio (routeur, free-ai-auto, avec la photo) depuis le conteneur
sandbox-manager vivant, puis lue comme le Studio la lit (plan_piece.lire_proposition). Sans `import app` : un petit
appel httpx copié dans /tmp du conteneur, la clé du routeur reste dans son environnement.

  python essai_plan_studio.py <photo.png> <dossier de mesure> "<description>" [--retouche "<message>"]
  (dossier de mesure = sortie d'essai_mesure_studio.py : geometrie.json, grille.json)
  -> <dossier>/consigne.txt, reponse.txt, plan.json, remarques.json, dessus.svg, camera.svg
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import plan_piece  # noqa: E402

CONTENEUR = "free-ai-studio-sandbox-manager"
APPEL = '''import json, os, sys, httpx
d = json.load(open("/tmp/essai_plan_demande.json", encoding="utf-8"))
contenu = [{"type": "text", "text": d["consigne"]}] + [{"type": "image_url", "image_url": {"url": u}} for u in d["images"]]
r = httpx.post(os.getenv("SANDBOX_ROUTEUR_URL", "http://free-tier-manager:8000") + "/v1/chat/completions",
               headers={"Authorization": "Bearer " + os.environ["FREE_TIER_MANAGER_KEY"], "X-Studio-Interne": "1"},
               json={"model": d.get("modele", "free-ai-auto"), "stream": False, "messages": [{"role": "user", "content": contenu}]},
               timeout=300)
print("HTTP", r.status_code, r.headers.get("x-free-ai-provider", ""), file=sys.stderr)
sys.stdout.write(((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "")
'''


def chat(dossier, consigne, images, modele="free-ai-auto"):
    (dossier / "essai_plan_demande.json").write_text(
        json.dumps({"consigne": consigne, "images": images, "modele": modele}), encoding="utf-8")
    (dossier / "essai_plan_appel.py").write_text(APPEL, encoding="utf-8")
    for nom in ("essai_plan_demande.json", "essai_plan_appel.py"):
        subprocess.run(["docker", "cp", str(dossier / nom), f"{CONTENEUR}:/tmp/{nom}"], check=True)
    t = time.time()
    r = subprocess.run(["docker", "exec", CONTENEUR, "python", "/tmp/essai_plan_appel.py"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    subprocess.run(["docker", "exec", CONTENEUR, "rm", "-f", "/tmp/essai_plan_demande.json",
                    "/tmp/essai_plan_appel.py"], check=False)
    print(r.stderr.strip()[-500:], round(time.time() - t, 1), "s", flush=True)
    if r.returncode:
        raise SystemExit("appel du chat en échec")
    return r.stdout


def main(photo, dossier, description, retouche=None):
    dossier = Path(dossier).resolve()
    geo = json.loads((dossier / "geometrie.json").read_text(encoding="utf-8"))
    grille = json.loads((dossier / "grille.json").read_text(encoding="utf-8"))
    if retouche:
        plan = json.loads((dossier / "plan.json").read_text(encoding="utf-8"))
        consigne = plan_piece.consigne_retouche(plan, retouche)
        images = []
    else:
        consigne = plan_piece.consigne_plan(description, geo)
        images = ["data:image/png;base64," + base64.b64encode(Path(photo).read_bytes()).decode()]
    suffixe = "_retouche" if retouche else ""
    (dossier / f"consigne{suffixe}.txt").write_text(consigne, encoding="utf-8")
    reponse = chat(dossier, consigne, images)
    (dossier / f"reponse{suffixe}.txt").write_text(reponse, encoding="utf-8")
    if retouche:
        lignes = reponse.strip().splitlines()
        plan, remarques = plan_piece.lire_plan(plan_piece._json_de("\n".join(lignes[1:]) or reponse), geo)
    else:
        plan, remarques = plan_piece.lire_proposition(reponse, geo, grille)
    (dossier / f"plan{suffixe}.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    (dossier / f"remarques{suffixe}.json").write_text(json.dumps(remarques, indent=1, ensure_ascii=False),
                                                     encoding="utf-8")
    (dossier / f"dessus{suffixe}.svg").write_text(plan_piece.svg_dessus(plan, geo), encoding="utf-8")
    (dossier / f"camera{suffixe}.svg").write_text(plan_piece.svg_camera(plan, geo), encoding="utf-8")
    print("PLAN", len(plan["elements"]), "elements :",
          ", ".join("%s(%s)" % (e["nom"], e["genre"]) for e in plan["elements"]), flush=True)
    print("REMARQUES", remarques, flush=True)
    if retouche:
        return 0
    # le relecteur, comme tour360.relire_plan : texte, photo, plan proposé, constats calculés
    consigne = plan_piece.consigne_relecture(description, plan, geo, True)
    (dossier / "consigne_relecture.txt").write_text(consigne, encoding="utf-8")
    reponse = chat(dossier, consigne, images, "free-ai-max")          # comme app._tour360_relecteur
    (dossier / "reponse_relecture.txt").write_text(reponse, encoding="utf-8")
    problemes, corrige, rem = plan_piece.lire_relecture(reponse, geo)
    print("RELECTURE", "corrigé" if corrige else "inchangé", problemes, rem, flush=True)
    if corrige:
        (dossier / "plan_relu.json").write_text(json.dumps(corrige, indent=1, ensure_ascii=False), encoding="utf-8")
        (dossier / "dessus_relu.svg").write_text(plan_piece.svg_dessus(corrige, geo), encoding="utf-8")
        (dossier / "camera_relu.svg").write_text(plan_piece.svg_camera(corrige, geo), encoding="utf-8")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    r = None
    if "--retouche" in a:
        i = a.index("--retouche")
        r = a[i + 1]
        del a[i:i + 2]
    sys.exit(main(a[0], a[1], a[2], r))
