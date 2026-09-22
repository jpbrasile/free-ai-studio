# -*- coding: utf-8 -*-
"""Écrire les nombres et les dates comme un lecteur français les lit.

POURQUOI CE FICHIER EXISTE. Le 21/09/2026 au soir, la page vidéo annonçait
« 4.88 $ sur les 15.00 $ » et « relevé chez Modal le 2026-09-21 10:58:42 ».
Point décimal anglais et date de journal de machine, sur la première ligne que
le client lit — et elle parle de son argent. Le dégât est petit et permanent.

DEUX LANGAGES, DONC DEUX FORMATEURS. Le montant est écrit tantôt par Python
(la page est fabriquée sur le serveur), tantôt par le JavaScript de la page
(les chiffres arrivent après, par le réseau). `toFixed` rend TOUJOURS un point,
quelle que soit la langue du navigateur : il n'y a pas de réglage à activer.

LES DATES NE CHANGENT PAS DE FORME EN MÉMOIRE. Ce qui est rangé reste
`2026-09-21 10:58:42` — une date de machine se trie, se compare et se relit.
C'est à l'AFFICHAGE qu'elle devient française. Les deux mondes ne se mélangent
pas, et la garde `scripts/verifier-francais.py` regarde l'affichage, pas le
rangement.

Chaque ligne qui contient volontairement le motif que la garde refuse porte la
marque `formateur-francais` : c'est le travail de ce fichier, et de lui seul.
"""
from __future__ import annotations

import re


def en_nombre(valeur: float | None, decimales: int = 2) -> str:
    """« 4,88 ». La virgule est le séparateur décimal en français."""
    if valeur is None:
        return "?"
    return ("%.*f" % (decimales, valeur)).replace(".", ",")  # formateur-francais


def en_dollars(valeur: float | None, decimales: int = 2) -> str:
    """« 4,88 $ »."""
    if valeur is None:
        return "?"
    return en_nombre(valeur, decimales) + " $"


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}:\d{2}))?")  # formateur-francais


def en_date(quand: str | None) -> str:
    """« 21/09/2026 à 10:58 » à partir de « 2026-09-21 10:58:42 ».

    Ce qui n'est pas une date de machine est rendu tel quel : mieux vaut une
    chaîne inattendue à l'écran qu'une exception qui vide la page.
    """
    if not quand:
        return ""
    trouve = _ISO.match(str(quand))
    if not trouve:
        return str(quand)
    annee, mois, jour, heure = trouve.groups()
    return "%s/%s/%s%s" % (jour, mois, annee, (" à %s" % heure) if heure else "")


# --- le même travail, côté navigateur --------------------------------------
# Inséré en tête du premier <script> de chaque page par `avec_formateurs`.
# `fr` sert à TOUS les nombres affichés, pas seulement à l'argent : « 1,5 Go »,
# « 48,5 % » et « 3,0 s » se lisent avec une virgule eux aussi.
JS_FORMATEURS = """
// --- formateur-francais : virgule decimale et dates francaises -------------
function fr(v, d){                                    // formateur-francais
  if (v === null || v === undefined || isNaN(v)) return "?";
  return Number(v).toFixed(d === undefined ? 2 : d).replace(".", ",");
}
function dateFr(s){                                   // formateur-francais
  if (!s) return "";
  var m = String(s).match(/^(\\d{4})-(\\d{2})-(\\d{2})(?:[ T](\\d{2}:\\d{2}))?/);
  if (!m) return String(s);
  return m[3] + "/" + m[2] + "/" + m[1] + (m[4] ? " \\u00e0 " + m[4] : "");
}
"""


def avec_formateurs(page: str) -> str:
    """Pose les formateurs en tête du premier `<script>` de la page.

    Une seule insertion : les pages n'ont qu'un bloc de script qui affiche des
    chiffres, et un second jeu de définitions écraserait le premier en silence.
    """
    return page.replace("<script>", "<script>" + JS_FORMATEURS, 1)
