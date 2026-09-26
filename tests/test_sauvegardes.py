"""Sauvegarder et restaurer : les garde-fous se relisent dans le texte des scripts.

docs/SAUVEGARDES.md, section << La procedure >>. Ces tests lisent les deux
scripts comme du texte, ils ne lancent rien : ni Docker, ni tar, ni ssh. Le
26/09/2026 au soir, les deux scripts ont tourne une premiere fois (a chaud,
restauration dans la cible d'essai) ; l'essai complet, joue par le
proprietaire avant le 31/10/2026, reste a faire.

Ce qu'ils tiennent :
- aucune coordonnee en dur (ni adresse IP, ni nom de domaine) : le VPS n'est
  atteint que par VPS_HOTE, VPS_UTILISATEUR, VPS_DOSSIER, nommees vides dans
  .env.example ;
- la cle du coffre n'entre dans aucune piece, donc jamais sur le VPS ;
- la restauration vise par defaut une cible d'essai, jamais le vrai config/ ni
  les vrais volumes sans -Reel ET la saisie d'ECRASER ;
- les scripts sont en ASCII (Windows PowerShell 5.1 lit un .ps1 sans marque
  d'octets dans la page de code ANSI) et s'arretent a la premiere erreur.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
CHEMINS = {
    "sauvegarder": RACINE / "scripts" / "sauvegarder.ps1",
    "restaurer": RACINE / "scripts" / "restaurer.ps1",
}
TEXTES = {nom: chemin.read_text(encoding="utf-8") for nom, chemin in CHEMINS.items()}
SAUVE = TEXTES["sauvegarder"]
RESTAURE = TEXTES["restaurer"]
MODELE = (RACINE / ".env.example").read_text(encoding="utf-8")
DOC = (RACINE / "docs" / "SAUVEGARDES.md").read_text(encoding="utf-8")


def _code(texte: str) -> str:
    """Le script sans ses commentaires : ce qui s'execute."""
    return "\n".join(l for l in texte.splitlines() if not l.lstrip().startswith("#"))


def _bloc(texte: str, debut: str, fin: str) -> str:
    return texte[texte.index(debut):texte.index(fin, texte.index(debut))]


# --- Forme ------------------------------------------------------------------

@pytest.mark.parametrize("nom", sorted(CHEMINS))
def test_ascii_sans_marque_d_octets(nom):
    brut = CHEMINS[nom].read_bytes()
    assert not brut.startswith(b"\xef\xbb\xbf"), nom
    hors_ascii = sorted({c for c in brut if c > 127})
    assert not hors_ascii, "%s : octets non ASCII %r" % (nom, hors_ascii[:5])


@pytest.mark.parametrize("nom", sorted(CHEMINS))
def test_arret_a_la_premiere_erreur(nom):
    code = _code(TEXTES[nom])
    assert '$ErrorActionPreference = "Stop"' in code
    # Juste apres le bloc param, avant tout geste.
    assert code.index('$ErrorActionPreference = "Stop"') < code.index("function ")


@pytest.mark.parametrize("nom", sorted(CHEMINS))
def test_pieges_de_powershell_5_evites(nom):
    code = _code(TEXTES[nom])
    assert "2>&1" not in code
    assert "Out-File" not in code
    # Les && sont dans des commandes envoyees a sh (conteneur, VPS),
    # jamais une chaine de commandes PowerShell.
    for ligne in code.splitlines():
        if "&&" in ligne:
            assert '"' in ligne.split("&&")[0], ligne


# --- Aucune coordonnee en dur ----------------------------------------------

IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
DOMAINE = re.compile(
    # En minuscules, comme un nom de domaine s'ecrit : System.IO n'en est pas un.
    r"\b[a-z0-9][a-z0-9-]*\.(?:com|net|org|fr|eu|io|dev|app|cloud|de|be|ch|uk|info|biz|xyz|host|site)\b"
)


@pytest.mark.parametrize("nom", sorted(CHEMINS))
def test_aucune_adresse_ni_domaine(nom):
    texte = TEXTES[nom]
    assert not IP.findall(texte), IP.findall(texte)
    assert not DOMAINE.findall(texte), DOMAINE.findall(texte)
    assert "http://" not in texte and "https://" not in texte


@pytest.mark.parametrize("nom", sorted(CHEMINS))
def test_le_vps_n_est_atteint_que_par_variables(nom):
    code = _code(TEXTES[nom])
    for variable in ("VPS_HOTE", "VPS_UTILISATEUR", "VPS_DOSSIER"):
        assert 'Variable-Vps "%s"' % variable in code
    # Le compte distant est fait des variables, et de rien d'autre.
    assert re.search(r'\$utilisateur \+ "@" \+ \$hote', code)
    # Aucun @hote ecrit en toutes lettres.
    assert not re.search(r"[A-Za-z0-9_-]+@[A-Za-z0-9-]+\.[A-Za-z]", code)
    # Les valeurs ne sont jamais affichees.
    for ligne in code.splitlines():
        if re.search(r"Write-Host|Bon |Note |Souci ", ligne):
            for v in ("$hote", "$utilisateur", "$dossierVps", "$compte", "$source", "$distant"):
                assert v not in ligne, ligne


def test_les_noms_des_variables_sont_dans_env_example_sans_valeur():
    for nom in ("VPS_HOTE", "VPS_UTILISATEUR", "VPS_DOSSIER", "VPS_PORT_SSH", "VPS_CLE_SSH"):
        assert re.search(rf"^{nom}=$", MODELE, re.M), nom
        for texte in (SAUVE, RESTAURE):
            assert 'Variable-Vps "%s"' % nom in texte, nom


# --- La cle du coffre ------------------------------------------------------

def test_la_cle_du_coffre_n_entre_dans_aucune_piece():
    code = _code(SAUVE)
    # Hors des messages, elle n'est nommee qu'une fois : pour etre lue et
    # reconnue par son empreinte.
    lignes = [l for l in code.splitlines()
              if "coffre.cle" in l and "Write-Host" not in l and not l.lstrip().startswith('"')]
    assert lignes == ['$CleFichier = Join-Path $Racine "secrets\\coffre.cle"'], lignes
    usages = [l for l in code.splitlines() if "$CleFichier" in l]
    for ligne in usages:
        assert not re.search(r"Copy-Item|Move-Item|\$Tar|scp|Ajouter-Piece|docker", ligne), ligne
    # Aucune piece ne vient de secrets/, et aucune archive ne le nomme.
    pieces = "".join(l for l in code.splitlines() if "$Tar" in l or "Ajouter-Piece" in l)
    assert "secrets\\" not in pieces and "secrets/" not in pieces and "$CleFichier" not in pieces
    assert "dans_l_archive = $false" in code


def test_la_copie_vps_ne_prend_que_les_pieces_marquees():
    code = _code(SAUVE)
    vps = _code(_bloc(SAUVE, "if ($VersVps) {", "# --- 6."))
    assert "$PiecesVps = @($Pieces | Where-Object { $_.vps })" in vps
    envoi = [l for l in vps.splitlines() if "$envoi =" in l]
    assert envoi == [
        "    $envoi = @($PiecesVps | ForEach-Object { Join-Path $Dossier $_.nom }) + @($CheminManifeste, $CheminSommes)"
    ]
    assert "secrets" not in vps and "coffre" not in vps
    # Par defaut, seul config.tar est marque pour le VPS ; les magasins et les
    # volumes attendent une decision du proprietaire.
    assert 'Ajouter-Piece "config.tar" "config/ sans les magasins de secrets" $true' in code
    assert re.search(r'Ajouter-Piece "config-magasins\.tar" .* \$VpsAvecMagasinsChiffres\.IsPresent', code)
    assert code.count("$VpsAvecVolumes.IsPresent") == 3


def test_les_magasins_sont_hors_de_config_tar_et_c_est_controle():
    code = _code(SAUVE)
    assert '$Magasins = @("config/keys.json", "config/sandbox-keys.json", "config/notebooklm")' in code
    assert 'foreach ($m in $Magasins) { $argsTar += @("--exclude", $m) }' in code
    # Le controle apres coup retire la piece si un magasin y est entre.
    assert "notebooklm(/|$))' })" in code
    assert 'Remove-Item -LiteralPath (Join-Path $Dossier "config.tar") -Force' in code


def test_l_empreinte_de_la_cle_est_la_meme_des_deux_cotes():
    def fonction(texte):
        return _bloc(texte, "function Empreinte-Cle(", "\n}\n")
    assert fonction(SAUVE) == fonction(RESTAURE)
    assert ".Substring(0, 16)" in fonction(SAUVE)


def test_la_cle_n_est_jamais_affichee():
    for texte in (SAUVE, RESTAURE):
        for ligne in _code(texte).splitlines():
            if "Write-Host" in ligne or re.match(r"\s*(Bon|Note|Souci) ", ligne):
                assert "$texteCle" not in ligne and "$CleTexte" not in ligne, ligne
    assert 'Read-Host "Collez-la ici (rien ne s\'affiche ; Entree seule pour passer)" -AsSecureString' in RESTAURE


# --- La restauration vise l'essai par defaut --------------------------------

def test_la_restauration_par_defaut_ne_vise_pas_le_studio_en_service():
    code = _code(RESTAURE)
    assert re.search(r"\[switch\]\$Reel\b", code)
    reel = _bloc(code, "if ($Reel) {", "} else {")
    assert "$Dossier = [System.IO.Path]::GetFullPath($Racine)" in reel
    assert '$ProjetCible = $Projet\n' in reel + "\n"
    assert 'if ($mot -cne "ECRASER")' in reel
    # Le vrai dossier et le vrai projet ne sont choisis que dans cette branche.
    hors_reel = code.replace(reel, "")
    assert "$Dossier = [System.IO.Path]::GetFullPath($Racine)" not in hors_reel
    assert "$ProjetCible = $Projet\n" not in hors_reel + "\n"
    # Par defaut : un dossier a cote du depot, suffixe -essai, qui ne le recouvre pas.
    assert '((Split-Path -Leaf $Racine) + "-essai")' in code
    assert "La cible d'essai touche le dossier du Studio en service." in code
    assert "if (-not $ProjetCible -or $ProjetCible -eq $Projet) {" in code


def test_rien_n_est_ecrase_ni_supprime():
    code = _code(RESTAURE)
    assert "Remove-Item" not in code
    assert "volume\", \"rm\"" not in code and '"rm"' not in code
    assert "Le volume \" + $nom + \" existe et n'est pas vide. Rien n'a ete ecrit." in code
    # config/ et la cle deja en place sont renommes, jamais ecrases.
    assert code.count("Rename-Item") == 2
    assert '".avant-restauration-"' in code


def test_les_empreintes_sont_verifiees_avant_toute_ecriture():
    code = _code(RESTAURE)
    verif = code.index("# --- 2.") if "# --- 2." in code else code.index("$Fausses = @()")
    arret = code.index("Des pieces ne correspondent pas a leur empreinte. Rien n'a ete ecrit.")
    premiere_ecriture = min(code.index(g) for g in ("git\" @(\"clone\"", "Rename-Item", "$Tar @(\"-xf\"",
                                                     "\"volume\", \"create\"", "WriteAllText"))
    assert verif < arret < premiere_ecriture


def test_le_compte_rendu_dit_ce_qui_manque():
    assert "ILLISIBLES sans elle" in RESTAURE
    assert '".env : jamais dans une sauvegarde' in RESTAURE


def test_la_sauvegarde_refuse_un_dossier_dans_le_depot_et_ne_supprime_rien_du_studio():
    code = _code(SAUVE)
    assert "Le dossier de sauvegarde est dans le depot." in code
    assert '"volume", "rm"' not in code and '"down"' not in code
    # Deux Remove-Item : une piece fautive que le script vient de fabriquer, et
    # la rotation des anciennes sauvegardes (test suivant).
    assert code.count("Remove-Item") == 2
    rotation = _bloc(SAUVE, "# --- 5b. Rotation locale", "# --- 6.")
    assert _code(rotation).count("Remove-Item") == 1
    # S'il a arrete le Studio, il le redemarre dans un finally.
    assert re.search(r"\} finally \{\s+# Redemarre", SAUVE)


def test_la_rotation_est_demandee_ne_vise_que_les_sauvegardes_du_projet_et_garde_la_neuve():
    """Essai reel du 26/09/2026 sur des leurres : -Garder 1 refuse ; sans -Garder,
    rien n'est supprime ; -Garder 2 a supprime les 3 anciennes du projet et laisse
    un autre projet, un dossier sans manifeste et un dossier au nom quelconque."""
    assert "[int]$Garder = 0" in SAUVE
    assert "if ($Garder -ne 0 -and $Garder -lt 2) {" in SAUVE
    rotation = _code(_bloc(SAUVE, "# --- 5b. Rotation locale", "# --- 6."))
    assert "'^studio-[0-9]{8}-[0-9]{6}$'" in rotation
    assert "$_.Name -ne $Nom" in rotation
    assert ".projet -eq $Projet" in rotation
    assert "Select-Object -Skip ($Garder - 1)" in rotation
    # Garder 0 : aucune suppression dans cette branche.
    branche_zero = rotation[rotation.index("if ($Garder -eq 0) {"):rotation.index("} else {")]
    assert "Remove-Item" not in branche_zero
    # Rien sur le VPS : la rotation ne parle ni ssh ni scp.
    assert "$Ssh" not in rotation and "$Scp" not in rotation


# --- Le document ------------------------------------------------------------

def test_le_document_decrit_la_procedure_sans_toucher_a_l_echeance():
    assert "## La procédure" in DOC
    assert "<!-- echeance: restauration-sauvegardes | butoir: 2026-10-31 | etat: en-attente -->" in DOC
    # Une seule ligne d'echeance : l'exemple de preuve ne doit pas en former une seconde.
    assert DOC.count("<!--") == 1
    for script in ("scripts/sauvegarder.ps1", "scripts/restaurer.ps1"):
        assert script in DOC
