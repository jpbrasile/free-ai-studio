# -*- coding: utf-8 -*-
"""Écrire les nombres et les dates comme un lecteur français les lit.

POURQUOI CE FICHIER EXISTE. Le 21/09/2026 au soir, la page vidéo annonçait
« 4.88 $ sur les 15.00 $ » et « relevé chez Modal le 2026-09-21 10:58:42 ».
Point décimal anglais et date de journal de machine, sur la première ligne que
le client lit — et elle parle de son argent. Le dégât est petit et permanent.

UN TROISIÈME, LE 22/09/2026 : LA MÉMOIRE. `/essai` écrivait « 23397 Mo libres
sur 24564 ». Cinq chiffres d'affilée, dans le même produit où l'argent et les
dates étaient déjà francisés. Le relevé des écrivains en a trouvé **cinq**, dont
quatre dans un module qui n'était sous aucune garde.

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


# L'espace insécable groupe les milliers ET colle l'unité à son nombre. Deux
# raisons, pas une : un nombre coupé en fin de ligne (« 24 » d'un côté,
# « 138 Mo » de l'autre) se relit faux, et `\d{4,}` ne franchit pas cet espace —
# la garde reconnaît donc d'elle-même un nombre déjà groupé, sans qu'il y ait
# un laissez-passer à écrire nulle part.
# Ecrit par son echappement, JAMAIS par le caractere lui-meme : a l'oeil, un
# insecable est une espace ordinaire, et n'importe quel editeur le remplace
# sans que personne ne le voie -- le groupement se defait alors en silence.
INSECABLE = "\u00a0"


def en_memoire(valeur: float | None, unite: str = "Mo") -> str:
    """« 24 138 Mo ». Les milliers se groupent, l'unité ne se détache pas.

    POURQUOI. `/essai` annonçait « 23397 Mo libres sur 24564 » : cinq chiffres
    d'affilée, que le lecteur compte à la main pour savoir s'il lit vingt-trois
    mille ou deux cent trente-trois mille. L'argent et les dates étaient déjà
    francisés par les deux formateurs du dessus ; la mémoire ne l'était pas.

    Le nombre ne bouge pas : c'est un groupement, pas un arrondi, et surtout pas
    une conversion. Passer en giga-octets aurait fait lire « 23,6 Go libres, il
    en faut 23,6 » sur un refus — deux valeurs distinctes ramenées à la même
    apparence, donc un refus qui se contredit à l'écran.

    `unite=""` rend le nombre groupé seul, pour les phrases qui portent
    plusieurs quantités et n'écrivent l'unité qu'une fois.
    """
    if valeur is None:
        return "?"
    chiffres = "%d" % round(valeur)
    signe, chiffres = ("-", chiffres[1:]) if chiffres.startswith("-") else ("", chiffres)
    groupes = []
    while len(chiffres) > 3:
        groupes.insert(0, chiffres[-3:])
        chiffres = chiffres[:-3]
    groupes.insert(0, chiffres)
    nombre = signe + INSECABLE.join(groupes)
    return nombre + INSECABLE + unite if unite else nombre


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
function moFr(v, u){                                  // formateur-francais
  // Le jumeau de `en_memoire`. Les chiffres de memoire arrivent par le reseau
  // APRES le chargement : ils ne passent jamais par Python, et le bras du rendu
  // de la garde ne les voit donc pas dans le HTML servi. C'est ici que ca se
  // joue, et nulle part ailleurs.
  if (v === null || v === undefined || isNaN(v)) return "?";
  var s = String(Math.round(Number(v))), neg = s.charAt(0) === "-";
  if (neg) s = s.slice(1);
  var groupe = "";
  while (s.length > 3){ groupe = "\\u00a0" + s.slice(-3) + groupe; s = s.slice(0, -3); }
  var n = (neg ? "-" : "") + s + groupe;
  u = (u === undefined) ? "Mo" : u;
  return u ? n + "\\u00a0" + u : n;
}
"""


def avec_formateurs(page: str) -> str:
    """Pose les formateurs en tête du premier `<script>` de la page.

    Une seule insertion : les pages n'ont qu'un bloc de script qui affiche des
    chiffres, et un second jeu de définitions écraserait le premier en silence.
    """
    return page.replace("<script>", "<script>" + JS_FORMATEURS, 1)
