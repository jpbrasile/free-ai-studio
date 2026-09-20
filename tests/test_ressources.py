"""La fonction de vidage : ce que le Studio occupe, et ce qu'on peut rendre.

Trois choses se gardent ici, dans cet ordre de degat.

1. **Le travail du client n'est jamais propose a la suppression.** Ses fichiers
   et ses conversations sont dans des volumes voisins de ceux qu'on vide ; un
   `docker volume rm` de trop et six mois de travail partent sans confirmation
   possible. Les deux scripts les AFFICHENT et refusent de les toucher.
2. **Une seule route efface les 34 Go** : `supprimer-modele-video`, qui porte
   ses propres gardes. Sans cette regle, le jour ou l'une des deux routes
   apprend quelque chose, l'autre l'ignore.
3. **Les deux jumeaux proposent les memes lignes.** Un client sous Linux et un
   client sous Windows doivent pouvoir rendre la meme place.

Ces tests lisent les fichiers ; ils ne lancent pas docker. Ce que lire ne peut
pas dire a ete joue en vrai le 20/09 (les six chemins, et la mesure sur cette
machine : 49,70 Go telecharges contre 1,81 Go de travail).
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

SH = (RACINE / "scripts" / "ressources.sh").read_text(encoding="utf-8")
PS1 = (RACINE / "scripts" / "ressources.ps1").read_text(encoding="utf-8")

# Les cles que le client tape. Elles sont affichees entre crochets dans le
# tableau : si l'une disparait d'un cote, le tableau ment de ce cote-la.
CLES = ("video-poids", "video-image", "chat", "whisper", "studio", "tout")

# Les deux volumes qui contiennent le travail de la personne, et rien d'autre.
TRAVAIL = ("sandbox-data", "open-webui-data")


def lignes_de_code(source: str, commentaire: str) -> list[str]:
    return [l.strip() for l in source.splitlines()
            if l.strip() and not l.strip().startswith(commentaire)]


def test_les_deux_jumeaux_proposent_les_memes_lignes():
    for cle in CLES:
        assert cle in SH, cle
        assert cle in PS1, cle


def test_le_travail_du_client_est_montre_mais_jamais_supprime():
    """LE test qui compte : un `docker volume rm` de trop, et six mois partent.

    Les deux volumes du travail sont voisins de ceux qu'on vide. Ils doivent
    apparaitre dans le tableau -- le client a le droit de savoir ce qu'ils
    pesent -- et n'apparaitre dans AUCUNE ligne qui efface."""
    # Les appels passent par des fonctions -- `vider_volume`, `ViderImage` --,
    # pas par `docker volume rm` en direct. Une garde qui ne regarde que les
    # commandes brutes laisse passer la faute : verifie par mutation le 20/09,
    # elle passait. Ce sont donc les DEUX qu'on regarde.
    for source, commentaire, efface in (
            (SH, "#", ("rm -rf", "docker volume rm", "docker image rm",
                       "vider_volume", "vider_image", "vider_poids")),
            (PS1, "#", ("Remove-Item", "docker volume rm", "docker image rm",
                        "ViderVolume", "ViderImage", "ViderPoids"))):
        code = lignes_de_code(source, commentaire)
        # Ils sont mesures : le client voit ce qu'ils pesent.
        assert any("sandbox-data" in l for l in code)
        assert any("open-webui-data" in l for l in code)
        # Mais jamais dans une ligne qui efface pour de bon. La seule mention
        # autorisee a cote d'un `rm` est celle qu'on ECRIT a l'ecran, pour que
        # la personne puisse le faire elle-meme en connaissance de cause.
        for l in code:
            if not any(e in l for e in efface):
                continue
            if l.startswith("echo") or l.startswith("Write-Host") or '"    docker volume rm' in l:
                continue
            if l.startswith("vider_") or l.startswith("function Vider"):
                continue          # la definition de la fonction, pas un appel
            for v in TRAVAIL:
                assert v not in l, l


def test_une_seule_route_efface_les_34_go():
    """Le vidage appelle le script dedie : ses gardes valent pour les deux."""
    assert "./scripts/supprimer-modele-video.sh --oui" in SH
    assert "supprimer-modele-video.ps1" in PS1
    # Et surtout : pas de suppression du modele en direct, qui contournerait
    # les gardes du script dedie (dossier du modele seulement, jamais la racine
    # du cache Hugging Face, qui contient les modeles des autres outils).
    for source, commentaire, efface in ((SH, "#", "rm -rf"), (PS1, "#", "Remove-Item")):
        for l in lignes_de_code(source, commentaire):
            if efface in l:
                assert "models--Wan-AI" not in l, l


def test_rien_ne_s_efface_sans_que_la_question_soit_posee():
    assert "read -r reponse" in SH
    assert "Read-Host" in PS1
    # Sans terminal, le .sh refuse au lieu de supposer.
    assert "[ ! -t 0 ]" in SH
    # Et sans argument, les deux se contentent de mesurer.
    assert 'if [ -z "$cle" ]' in SH
    assert "if (-not $Vider)" in PS1


def test_le_prix_du_retour_est_dit_avant_la_question():
    """Un vidage qui ne dit pas son prix n'est pas un choix."""
    for source in (SH, PS1):
        assert "Pour revenir" in source or "retour" in source
    # Et pour les 34 Go, le prix du retour est devenu << rien a faire >> :
    # c'est la regle du proprietaire du 20/09, et elle doit etre ECRITE la ou
    # le client decide, pas seulement tenue par le service.
    assert "le Studio les retélécharge" in SH
    assert "le Studio les retelecharge" in PS1


def test_le_total_ne_se_fait_pas_passer_pour_exact():
    """Les images Docker partagent des couches : additionner majore."""
    assert "borne haute" in SH
    assert "borne haute" in PS1
