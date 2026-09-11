"""Syntaxe du JavaScript embarque dans les pages des services (node --check).

Les pages HTML vivent dans des chaines Python. Un \\n ecrit sans double
barre oblique y devient un vrai retour a la ligne, et casse TOUT le script de
la page dans le navigateur, sans aucune erreur cote Python : /studio est reste
ainsi sans JavaScript du commit ed3e71d au 11/09/2026. py_compile, ruff et le
test d'import ne voient rien ; node, si.

Charge chaque service comme scripts/verifier-imports.py, demande ses pages HTML
(sans suivre leurs fetch() : aucun appel reseau), ajoute les chaines HTML des
modules, extrait chaque <script> sans src et le passe a `node --check`.
Sort en 1 au premier script invalide.
"""
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
os.environ["FREE_AI_CONFIG_DIR"] = tempfile.mkdtemp(prefix="free-ai-config-")
os.environ["SANDBOX_WORKSPACE"] = tempfile.mkdtemp(prefix="free-ai-workspace-")
os.environ.setdefault("FREE_TIER_MANAGER_KEY", "cle-de-verification")
os.environ.setdefault("SANDBOX_MANAGER_KEY", "cle-de-verification")
# Hors conteneur, le compte courant n'a pas le droit de changer un proprietaire.
os.chown = lambda *args, **kwargs: None

from fastapi.testclient import TestClient  # noqa: E402

SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)
PAGES = {
    "free-tier-manager": ["/studio", "/diagnostic", "/cles"],
    "sandbox-manager": ["/", "/cles", "/video", "/essai"],
}


def charger(dossier: str):
    sys.path.insert(0, str(RACINE / dossier))
    nom = "verif_js_" + dossier.replace("-", "_")
    spec = importlib.util.spec_from_file_location(nom, RACINE / dossier / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chaines_html(module) -> dict:
    return {nom: v for nom, v in vars(module).items() if isinstance(v, str) and "<script" in v}


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("ECHEC  node introuvable : impossible de verifier le JavaScript")
        return 1
    sources = {}
    for dossier, chemins in PAGES.items():
        module = charger(dossier)
        client = TestClient(module.app)
        for chemin in chemins:
            r = client.get(chemin)
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                print("ECHEC  %s GET %s : %d, pas une page HTML" % (dossier, chemin, r.status_code))
                return 1
            sources["%s %s" % (dossier, chemin)] = r.text
        for nom, html in chaines_html(module).items():
            sources["%s %s" % (dossier, nom)] = html
    video = sys.modules.get("video")
    if video is not None:
        for nom, html in chaines_html(video).items():
            sources["video.py %s" % nom] = html

    vus, echecs = set(), 0
    dossier_js = Path(tempfile.mkdtemp(prefix="free-ai-js-"))
    for origine, html in sources.items():
        for i, bloc in enumerate(SCRIPT.findall(html)):
            empreinte = hashlib.sha256(bloc.encode("utf-8")).hexdigest()
            if not bloc.strip() or empreinte in vus:
                continue
            vus.add(empreinte)
            fichier = dossier_js / (empreinte[:16] + ".js")
            fichier.write_text(bloc, encoding="utf-8")
            r = subprocess.run([node, "--check", str(fichier)], capture_output=True, text=True)
            if r.returncode == 0:
                print("ok     %s, script %d" % (origine, i))
            else:
                echecs += 1
                print("ECHEC  %s, script %d" % (origine, i))
                print(r.stderr.strip()[:1200])
    print("%d script(s) distinct(s), %d en echec" % (len(vus), echecs))
    return 1 if echecs or not vus else 0


if __name__ == "__main__":
    sys.exit(main())
