"""Que faire d'un travail qu'un redemarrage a laisse sans personne derriere lui.

Ce module ne parle a personne : il decide, et rend des mots. Le branchement sur
Modal, sur Kaggle et sur le disque est dans `app.py`, ou vivent deja les
fonctions qui savent le faire. Ici il n'y a que le raisonnement, et il se teste
sans reseau.

LE DEFAUT QU'IL REPARE, mesure le 22/09/2026. Le fil qui suit un travail paye
est un `threading.Thread(daemon=True)`. Il meurt avec le conteneur. Rien ne le
remplace au demarrage -- zero ligne de reprise dans tout le service. Deux
consequences, toutes deux constatees le meme soir :

- un travail Modal cree a 13:22:25 a survecu a la recreation du gestionnaire de
  13:26. Le compteur reel est monte 5,1979 -> 5,3268 -> 5,4417 $ : quatre
  minutes facturees apres que plus personne ne regardait, et un fichier que
  personne n'allait chercher ;
- un travail Kaggle est a `running` depuis le 09/09/2026, soit 318 h.

LA LECON DU SECOND, ET C'EST ELLE QUI GOUVERNE `echeance_kaggle()`. Kaggle a
pourtant DEUX delais : le `-t` remis a `kaggle kernels push`, qui fait arreter
le notebook par Kaggle lui-meme, et `deadline = pousse + limite + marge` dans la
boucle d'attente du Studio. Aucun des deux n'a pu jouer dans la fiche, parce que
les deux vivent dans le fil. **Un delai qui vit dans un fil ne se declenche que
si quelqu'un regarde encore.** La reprise recalcule donc l'echeance depuis
l'heure de DEPART du travail. Repartir de maintenant offrirait une heure neuve
a un travail vieux de treize jours -- et le ferait patienter pour rien.

DECISION DU PROPRIETAIRE, 22/09/2026 : **readopter**, et non arreter. Retrouver
la machine et la suivre de nouveau, pour que le fichier deja paye soit rendu.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Les statuts d'un travail que quelqu'un est cense suivre. `submitting` et
# `routing` en font partie : un travail coupe entre l'envoi et le lancement est
# orphelin lui aussi, et c'est le cas le plus silencieux des trois.
VIVANTS = ("queued", "routing", "preparing", "submitting", "running")

# Ce qu'on fait d'une fiche vivante. Quatre mots, pas un booleen : ce qui
# apprend, c'est OU ca a casse et ce qu'on peut encore en tirer.
REPRENDRE_MODAL = "reprendre-modal"
REPRENDRE_KAGGLE = "reprendre-kaggle"
ORPHELIN = "orphelin"      # plus personne ne peut le retrouver : on le dit
RIEN = "rien"              # deja clos, ou jamais parti


def qui_tenait(fiche: Dict[str, Any]) -> str:
    """Le fournisseur reellement utilise, a defaut celui demande."""
    return str(fiche.get("provider_effective") or fiche.get("provider") or "").strip()


def que_faire(fiche: Dict[str, Any]) -> str:
    """Le verdict sur une fiche, sans rien toucher.

    Modal se reprend TOUJOURS, meme sans `remote_ref` : cette cle n'est ecrite
    qu'a la FIN du travail (`app.py:677`), donc une reprise qui s'appuierait
    dessus ne retrouverait que les travaux qui n'en ont pas besoin.
    L'etiquette `free-ai-studio-job`, elle, est posee des la creation de la
    machine (`app.py:584`). C'est deja le raisonnement de `arreter_modal()`,
    ecrit le 17/09, et il a tenu le 22/09 sur un travail sans `remote_ref`.

    Kaggle est l'inverse : `remote_ref` y est ecrit AVANT la poussee
    (`app.py:953`), et c'est la seule prise qu'on ait sur un notebook. Sans
    elle, il n'y a rien a interroger.

    Le calcul local, lui, est mort avec le conteneur qu'on vient de remplacer.
    Il n'y a rien a retrouver, et faire semblant serait pire que de le dire.
    """
    if str(fiche.get("status") or "") not in VIVANTS:
        return RIEN
    ou = qui_tenait(fiche)
    if ou == "modal":
        return REPRENDRE_MODAL
    if ou == "kaggle" and str(fiche.get("remote_ref") or "").strip():
        return REPRENDRE_KAGGLE
    return ORPHELIN


def depart(fiche: Dict[str, Any]) -> float:
    """L'heure a laquelle ce travail est parti. Jamais l'heure qu'il est.

    `started_at` d'abord, `created_at` a defaut. Zero si la fiche n'a ni l'un
    ni l'autre -- et zero rend toute echeance deja depassee, ce qui est la
    bonne reponse : un travail dont on ne sait meme pas quand il est parti ne
    merite pas qu'on l'attende.
    """
    for cle in ("started_at", "created_at"):
        valeur = fiche.get(cle)
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool) and valeur > 0:
            return float(valeur)
    return 0.0


def echeance_kaggle(fiche: Dict[str, Any], *, limite: float, marge: float) -> float:
    """L'echeance d'ORIGINE du travail, celle que le fil mort portait."""
    return depart(fiche) + float(limite) + float(marge)


def echeance_depassee(fiche: Dict[str, Any], *, limite: float, marge: float,
                      maintenant: float) -> bool:
    """Le delai a-t-il expire pendant qu'on ne regardait pas ?"""
    return float(maintenant) >= echeance_kaggle(fiche, limite=limite, marge=marge)


def travail_fini_dans_la_boite(sortie_de_la_sonde: Optional[str]) -> bool:
    """Le calcul du client est-il termine DANS la machine Modal ?

    POURQUOI ON NE DEMANDE PAS A LA MACHINE. Elle est creee avec `sleep` pour
    entrypoint (`app.py:572`) : `poll()` rend None tant que sa duree de vie
    n'est pas ecoulee, MEME quand le python du client est fini depuis
    longtemps. La machine ne repond donc pas a la question posee. On cherche le
    processus.

    Et une sonde muette ne vaut pas << termine >>. Si elle ne rend rien du tout
    -- None -- on ne conclut pas : on la redemandera. La dire terminee ferait
    ramasser un dossier a moitie ecrit, et un sondeur doit separer << pas
    ENCORE >> de << JAMAIS >>.
    """
    if sortie_de_la_sonde is None:
        return False
    return not str(sortie_de_la_sonde).strip()
