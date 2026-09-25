"""Le bouton « 🏠 Studio » : revenir à la page principale depuis n'importe quelle page.

Demande de l'utilisateur du 25/09/2026 : « add a button to go back to the main
page wherever we are ». Les pages vivent dans deux services (le routeur sur le
port 8010, le bac a sable sur 8020) et sont fabriquees de plusieurs facons ; un
bouton pose page par page en oublierait une. Chaque service declare donc ses
pages une fois, et un intergiciel pose le bouton a l'envoi. Une page nouvelle
qui ne serait pas declaree fait echouer tests/test_accueil.py.

Fichier en deux exemplaires identiques (free-tier-manager, sandbox-manager) :
meme raison que coffre.py, et le meme test le verifie.
"""

from __future__ import annotations

from typing import Iterable

from starlette.requests import Request
from starlette.responses import Response

MARQUE = 'id="studio-accueil"'

# Le lien vise le port du routeur sur la MEME machine que la page : ouverte par
# localhost, 127.0.0.1 ou le nom du poste, elle ramene au meme Studio.
BOUTON = (
    '<a ' + MARQUE + ' href="http://127.0.0.1:8010/studio" title="Revenir à la page du Studio" '
    'style="position:fixed;left:12px;bottom:12px;z-index:2147483000;padding:8px 14px;'
    'border-radius:999px;background:#1f2937;color:#fff;font:600 14px/1.2 system-ui,sans-serif;'
    'text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.3)">🏠 Studio</a>'
    '<script>(function(){var a=document.getElementById("studio-accueil");'
    'if(a&&location.hostname){a.href=location.protocol+"//"+location.hostname+":8010/studio";}})();'
    '</script>'
)


def poser(page: bytes) -> bytes:
    """Ajoute le bouton juste avant la derniere balise </body> (une seule fois)."""
    if MARQUE.encode() in page:
        return page
    bouton = BOUTON.encode("utf-8")
    fin = page.rfind(b"</body>")
    if fin < 0:
        return page + bouton
    return page[:fin] + bouton + page[fin:]


def brancher(app, pages: Iterable[str]) -> None:
    """Pose le bouton sur les pages HTML nommees de ce service (GET seulement)."""
    chemins = frozenset(pages)

    @app.middleware("http")
    async def bouton_accueil(request: Request, suite):
        reponse = await suite(request)
        if (request.method != "GET" or request.url.path not in chemins
                or not reponse.headers.get("content-type", "").startswith("text/html")):
            return reponse
        corps = b"".join([morceau async for morceau in reponse.body_iterator])
        entetes = {k: v for k, v in reponse.headers.items() if k.lower() != "content-length"}
        return Response(poser(corps), status_code=reponse.status_code, headers=entetes)
