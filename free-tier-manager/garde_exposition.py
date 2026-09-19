# -*- coding: utf-8 -*-
"""Refus au demarrage quand les cles seraient exposees.

Le plan d'origine pose une regle dure : << Never store, proxy or share user API
keys. Keys live client-side only, encrypted. >> Ce depot les ecrit EN CLAIR,
dans config/keys.json et config/sandbox-keys.json. Tant que le Studio tourne sur
le PC de son utilisateur, derriere un port publie sur 127.0.0.1, l'ecart est
theorique : les seules cles en jeu sont les siennes, sur sa machine.

Le jour ou ce n'est plus vrai, rien ne bronchait. Ce module est le refus qui
manquait (docs/PLAN-PLATEFORME.md, paragraphe 2.1, option (c) ; decision 3 de
l'utilisateur du 19/09/2026). Il tient le patron que le depot applique deja
partout -- budget_verifier() refuse avant de depenser, preparer() refuse LoRA+T4
au lieu de parier, exiger_page_du_studio() refuse cote serveur : REFUSER PLUTOT
QUE PARIER.

Deux conditions, et elles ne sont pas de meme nature.

1. STUDIO_HEBERGE=true. C'est une DECLARATION. Elle ne se constate pas : une
   instance exposee par un moyen qui n'en laisse aucune trace doit etre declaree
   a la main (sandbox-manager/app.py, meme remarque). Une declaration protege
   celui qui la fait, pas celui qui l'oublie.

2. STUDIO_ADRESSE_PUBLIEE hors boucle locale. Celle-la SE CONSTATE, parce que la
   meme variable ecrit la publication dans docker-compose.yml et arrive ici :
   `ports: - "${STUDIO_ADRESSE_PUBLIEE:-127.0.0.1}:8010:8000"`. On ne peut pas
   publier sur 0.0.0.0 sans que ce module le voie -- c'est le meme texte des deux
   cotes. A l'interieur du conteneur uvicorn ecoute toujours 0.0.0.0 ; lire sa
   propre liaison ne dirait donc rien. Ce qui compte est l'adresse d'HOTE sur
   laquelle le port est publie, et elle n'est connue que de compose.

Ce que ce module ne fait PAS : chiffrer. Le chiffrement au repos est utile --
il defend le cas du fichier qui s'echappe sans sa machine, sauvegarde egaree ou
disque revendu -- mais il n'est pas un prealable, et mieux vaut un refus qui
marche sans chiffrement qu'un chiffrement sans refus. Il n'y a donc ici aucun
drapeau << les cles sont chiffrees >> : il serait faux, et un drapeau faux est
pire que pas de drapeau.

ATTENTION -- ce fichier existe en deux exemplaires IDENTIQUES, un par service :
free-tier-manager/ et sandbox-manager/ ecrivent chacun leur magasin de secrets,
et les deux images ont des contextes de construction separes. Le contexte ne
peut pas etre la racine du depot : elle contient .env et config/, c'est-a-dire
precisement les secrets que ce module protege. Les envoyer dans un contexte de
construction pour y installer leur garde serait absurde.
tests/test_garde_exposition.py echoue si les deux copies divergent d'un octet.
C'est le meme remede que test_les_deux_tables_de_prix_ne_divergent_pas.
"""

import os
from typing import Dict, List, Optional

# Ce qui ne sort pas de la machine. "localhost" y figure parce que compose
# l'accepte dans une publication de port ; "::1" est la meme chose en IPv6.
ADRESSES_LOCALES = frozenset({"127.0.0.1", "::1", "localhost", "[::1]"})


class ClesExposees(RuntimeError):
    """Le service refuse de demarrer : ses cles seraient lisibles d'ailleurs."""


def motifs_d_exposition(heberge: Optional[str], adresse: Optional[str]) -> List[str]:
    """Les raisons de refuser, en clair. Liste vide = rien a redire.

    Separe du refus pour une raison : une page de diagnostic doit pouvoir poser
    la question sans faire tomber le service.
    """
    motifs: List[str] = []

    if (heberge or "").strip().lower() == "true":
        motifs.append(
            "STUDIO_HEBERGE=true : cette instance est declaree hebergee, "
            "donc les cles saisies ne sont plus celles de la personne qui est "
            "devant l'ecran."
        )

    valeur = (adresse or "127.0.0.1").strip()
    if valeur.lower() not in ADRESSES_LOCALES:
        motifs.append(
            "STUDIO_ADRESSE_PUBLIEE=%s : les ports ne sont plus publies sur la "
            "boucle locale, donc le Studio est joignable depuis le reseau."
            % valeur
        )

    return motifs


def message_de_refus(magasin: str, motifs: List[str]) -> str:
    """Le texte que l'utilisateur lira dans les journaux du conteneur."""
    lignes = [
        "DEMARRAGE REFUSE : les cles seraient exposees.",
        "",
        "Ce service ecrit les cles d'API EN CLAIR dans %s." % magasin,
        "Aucun chiffrement au repos n'existe dans ce depot a ce jour.",
        "",
        "Ce qui a ete constate :",
    ]
    lignes += ["  - " + m for m in motifs]
    lignes += [
        "",
        "Trois facons d'en sortir, de la plus sure a la plus risquee :",
        "  1. Revenir a un Studio personnel : STUDIO_HEBERGE=false et",
        "     STUDIO_ADRESSE_PUBLIEE=127.0.0.1 dans le .env, puis redemarrer.",
        "     C'est l'usage pour lequel ce Studio est ecrit.",
        "  2. Mettre un chiffrement au repos sur ce magasin, puis rouvrir ce",
        "     refus. Il n'est pas ecrit : ce message ne pretend pas le contraire.",
        "  3. Ne rien y mettre de sensible : effacer le magasin et servir sans",
        "     cle. Les fonctions qui en ont besoin refuseront, ce qui est le but.",
        "",
        "Ce refus est la decision du 19/09/2026 (docs/PLAN-PLATEFORME.md,",
        "paragraphe 2.1 et paragraphe 8, decision 3). Il n'a pas d'interrupteur :",
        "un garde-fou qu'on eteint par une variable n'est pas un garde-fou.",
    ]
    return "\n".join(lignes)


def verifier_ou_refuser(magasin: str, env: Optional[Dict[str, str]] = None) -> None:
    """Leve ClesExposees si le magasin serait lisible d'ailleurs que d'ici.

    Appele a l'import du service, pas dans un evenement de demarrage : uvicorn
    doit refuser de charger l'application, pas la servir a moitie.
    """
    source = os.environ if env is None else env
    motifs = motifs_d_exposition(source.get("STUDIO_HEBERGE"),
                                 source.get("STUDIO_ADRESSE_PUBLIEE"))
    if motifs:
        raise ClesExposees(message_de_refus(magasin, motifs))
