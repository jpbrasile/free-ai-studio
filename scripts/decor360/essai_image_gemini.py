"""Les deux photos d'un lieu par l'image gratuite du routeur (Gemini, comme `_image_du_studio`) au lieu de
Qwen-Image 2.1 (propriétaire, 06/10 : « you can try gemini free image too ») : mêmes textes que la commande `image` /
`dos` d'essai_tour_texte.py (relus dans <qwen>/<cas>/image*/texte.txt), la vue à 180° avec la photo de face jointe.
Sans `import app` : un petit appel httpx dans le conteneur sandbox-manager, la clé du routeur reste dans son
environnement.

  python essai_image_gemini.py <dossier qwen> <sortie> [cas ...]  -> <sortie>/<cas>/photo.png, photo_dos.png
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import retouche_qwen as rq  # noqa: E402
import video_h3  # noqa: E402
from essai_plans_texte import CAS  # noqa: E402
from essai_plan_studio import chat  # noqa: E402
from essai_tour_texte import CONSIGNE_DOS, DOS  # noqa: E402

CONTENEUR = "free-ai-studio-sandbox-manager"
APPEL = '''import json, os, sys, httpx
d = json.load(open("/tmp/essai_image_demande.json", encoding="utf-8"))
r = httpx.post(os.getenv("SANDBOX_ROUTEUR_URL", "http://free-tier-manager:8000") + "/v1/images/generations",
               headers={"Authorization": "Bearer " + os.environ["FREE_TIER_MANAGER_KEY"], "X-Studio-Interne": "1"},
               json=d, timeout=200)
print("HTTP", r.status_code, r.headers.get("x-free-ai-provider", ""), file=sys.stderr)
images = [x.get("url") for x in (r.json().get("data") or []) if str(x.get("url", "")).startswith("data:image/")]
if not images:
    print(r.text[:800], file=sys.stderr)
    sys.exit(2)
sys.stdout.write(images[0])
'''


def image(dossier, demande):
    (dossier / "essai_image_demande.json").write_text(json.dumps(demande), encoding="utf-8")
    (dossier / "essai_image_appel.py").write_text(APPEL, encoding="utf-8")
    for nom in ("essai_image_demande.json", "essai_image_appel.py"):
        subprocess.run(["docker", "cp", str(dossier / nom), f"{CONTENEUR}:/tmp/{nom}"], check=True)
    t = time.time()
    r = subprocess.run(["docker", "exec", CONTENEUR, "python", "/tmp/essai_image_appel.py"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stderr.strip()[-400:], round(time.time() - t, 1), "s", flush=True)
    if r.returncode or "," not in r.stdout:
        return None
    return base64.b64decode(r.stdout.split(",", 1)[1])


def main(qwen, sortie, noms):
    for nom in noms or list(CAS):
        d = sortie / nom
        d.mkdir(parents=True, exist_ok=True)
        face = (qwen / nom / "image" / "texte.txt")
        if not face.is_file():
            print(json.dumps({"cas": nom, "gemini": "pas de texte de face"}))
            continue
        face = face.read_text(encoding="utf-8")[len(rq.TOILE):]
        if not (d / "photo.png").is_file():
            png = image(d, {"prompt": face, "n": 1, "size": video_h3.TAILLE_IMAGE_DEMANDEE})
            if png:
                (d / "photo.png").write_bytes(png)
        if (d / "photo.png").is_file() and not (d / "photo_dos.png").is_file():
            # propriétaire, 06/10 : « go with gemini, do the back views now » : le chat écrit la vue à 180°
            texte = chat(d, CONSIGNE_DOS % (CAS[nom], face), []).strip().strip('"')
            (d / "texte_dos.txt").write_text(texte, encoding="utf-8")
            entete = DOS.replace("<image2>", "the attached image")
            png = image(d, {"prompt": entete + texte, "n": 1, "size": video_h3.TAILLE_IMAGE_DEMANDEE,
                            "image_reference": ["data:image/png;base64,"
                                                + base64.b64encode((d / "photo.png").read_bytes()).decode()]})
            if png:
                (d / "photo_dos.png").write_bytes(png)
        print(json.dumps({"cas": nom, "photo": (d / "photo.png").is_file(), "dos": (d / "photo_dos.png").is_file()}),
              flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3:])
