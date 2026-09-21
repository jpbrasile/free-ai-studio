"""Le travail qui relit les licences chez l'editeur, et qui ne decide jamais.

`registry/apps.json` porte un champ `verifie_le`, defini dans son propre
en-tete comme << le jour ou la licence a ete lue sur la fiche officielle >>,
suivi de << une licence peut changer >>. Jusqu'au 21/09/2026 rien ne la
relisait : la date vieillissait toute seule et se lisait quand meme comme une
verification.

CE QUE CES TESTS GARDENT, et c'est le seul point qui compte : la difference
entre << concorde >>, << ne concorde pas >> et << je n'ai pas pu verifier >>.
Confondre la troisieme avec la premiere est la facon habituelle de fabriquer
un vert, et elle serait ici la plus chere : une licence passee en non
commercial sans que personne le voie.

Preuve que la troisieme case n'est pas theorique, mesuree au premier vrai
passage du 21/09/2026 : les deux voix pointent vers UN FICHIER de
`rhasspy/piper-voices`, un depot collectif de 3 301 fichiers etiquete `mit`,
alors que le registre porte la licence de LA VOIX (CC BY 4.0 pour SIWIS,
domaine public pour LibriVox). L'outil les a d'abord declarees en desaccord.
Un outil qui crie au loup finit debranche, donc muet le jour ou il a raison.

Aucun appel reseau : toutes les fiches sont fabriquees ici, ou rejouees depuis
un releve ecrit sur disque.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys

import pytest

from conftest import RACINE

CHEMIN = RACINE / "scripts" / "proposer-les-mises-a-jour.py"


def _charger():
    """Le script porte un tiret dans son nom : pas d'import ordinaire."""
    spec = importlib.util.spec_from_file_location("propositions", CHEMIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def outil():
    return _charger()


@pytest.fixture(scope="module")
def registre():
    return json.loads((RACINE / "registry" / "apps.json").read_text(encoding="utf-8"))


def _fiche(licence=None, modifie="2026-01-01T00:00:00.000Z", tags=None):
    fiche = {"lastModified": modifie, "tags": tags or []}
    if licence is not None:
        fiche["cardData"] = {"license": licence}
    return fiche


# --- 1. Lire l'adresse d'une fiche ------------------------------------------

@pytest.mark.parametrize("source,attendu", [
    ("https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers", "Wan-AI/Wan2.2-TI2V-5B-Diffusers"),
    ("https://huggingface.co/rhasspy/piper-voices/blob/main/fr/x/MODEL_CARD", "rhasspy/piper-voices"),
    ("https://ai.google.dev/gemini-api/terms", None),
    ("https://duckduckgo.com/terms", None),
])
def test_le_depot_est_lu_dans_l_adresse(outil, source, attendu):
    assert outil.depot_de(source) == attendu


# --- 2. Lire la licence que l'editeur affiche -------------------------------

def test_la_licence_se_lit_dans_la_carte(outil):
    assert outil.licence_annoncee(_fiche("apache-2.0")) == "apache-2.0"


def test_une_liste_de_licences_rend_la_premiere(outil):
    assert outil.licence_annoncee(_fiche(["mit", "apache-2.0"])) == "mit"


def test_a_defaut_de_carte_la_licence_se_lit_dans_les_etiquettes(outil):
    fiche = _fiche(None, tags=["audio", "license:cc-by-nc-4.0"])
    assert outil.licence_annoncee(fiche) == "cc-by-nc-4.0"


def test_un_editeur_muet_ne_rend_pas_une_licence_inventee(outil):
    assert outil.licence_annoncee(_fiche(None)) is None


# --- 3. Les cinq cases, et surtout la troisieme ------------------------------

def _mini(source, licence_chez_nous, id_="essai"):
    return {"applications": [{"id": id_, "source": source,
                              "licence": licence_chez_nous,
                              "verifie_le": "2026-09-20"}]}


def test_une_licence_identique_concorde(outil):
    verdict = outil.comparer(
        _mini("https://huggingface.co/a/b", "Apache 2.0"),
        {"fiches": {"a/b": _fiche("apache-2.0")}})
    assert [e["id"] for e in verdict["concordent"]] == ["essai"]
    assert not verdict["desaccords"]


def test_une_licence_qui_a_change_chez_l_editeur_est_un_desaccord(outil):
    """LE cas pour lequel ce travail existe.

    Un modele passe d'Apache 2.0 a non commercial : le Studio continuerait de
    l'annoncer libre, et son utilisateur serait en faute sans l'avoir su.
    """
    verdict = outil.comparer(
        _mini("https://huggingface.co/a/b", "Apache 2.0"),
        {"fiches": {"a/b": _fiche("cc-by-nc-4.0")}})
    assert [e["id"] for e in verdict["desaccords"]] == ["essai"]
    assert not verdict["concordent"]


def test_une_fiche_disparue_n_est_pas_un_accord(outil):
    verdict = outil.comparer(
        _mini("https://huggingface.co/a/b", "Apache 2.0"),
        {"fiches": {"a/b": {"absent": True}}})
    assert [e["id"] for e in verdict["disparus"]] == ["essai"]
    assert not verdict["concordent"] and not verdict["desaccords"]


@pytest.mark.parametrize("licence,bout_du_motif", [
    (None, "n'affiche aucune licence"),
    ("other", "ne designe aucune licence"),
    ("licence-maison-2031", "inconnue de la table"),
])
def test_ce_qui_ne_peut_pas_etre_compare_n_est_NI_vert_NI_rouge(outil, licence, bout_du_motif):
    """La case qui protege du faux vert, et qui doit dire POURQUOI.

    Un `non comparable` sans motif se lirait comme une panne de l'outil ; avec
    son motif, il se lit comme un travail a faire a la main.
    """
    verdict = outil.comparer(
        _mini("https://huggingface.co/a/b", "Apache 2.0"),
        {"fiches": {"a/b": _fiche(licence)}})
    assert not verdict["concordent"] and not verdict["desaccords"]
    assert len(verdict["non_comparables"]) == 1
    assert bout_du_motif in verdict["non_comparables"][0]["motif"]


def test_un_fichier_dans_un_depot_collectif_n_est_pas_comparable(outil):
    """La lecon du 21/09/2026, ecrite en test pour qu'elle ne se reperde pas.

    `rhasspy/piper-voices` est etiquete `mit` et contient 3 301 fichiers, une
    voix par fichier, chacune avec sa licence. Comparer la licence du depot a
    celle de la voix produisait deux faux desaccords.
    """
    verdict = outil.comparer(
        _mini("https://huggingface.co/rhasspy/piper-voices/blob/main/fr/x/MODEL_CARD",
              "Voix : CC BY 4.0"),
        {"fiches": {"rhasspy/piper-voices": _fiche("mit")}})
    assert not verdict["desaccords"] and not verdict["concordent"]
    assert "depot collectif" in verdict["non_comparables"][0]["motif"]


def test_une_fiche_hors_hugging_face_est_dite_telle_quelle(outil):
    verdict = outil.comparer(
        _mini("https://ai.google.dev/gemini-api/terms", "conditions de l'API"),
        {"fiches": {}})
    assert [e["id"] for e in verdict["hors_hugging_face"]] == ["essai"]


# --- 4. Rien ne disparait en silence ----------------------------------------

def test_chaque_application_du_registre_tombe_dans_UNE_case(outil, registre):
    """Une entree qui ne tomberait nulle part ne serait jamais verifiee.

    Le controle est ecrit sur le registre REEL et non sur une liste fabriquee
    ici : une liste fabriquee se tairait le jour ou quelqu'un ajoute une
    application d'un genre nouveau.
    """
    fiches = {}
    for app in registre["applications"]:
        depot = outil.depot_de(app["source"])
        if depot:
            fiches[depot] = _fiche("apache-2.0")
    verdict = outil.comparer(registre, {"fiches": fiches})

    cases = ("concordent", "desaccords", "disparus", "non_comparables",
             "hors_hugging_face")
    vus = [e["id"] for case in cases for e in verdict[case]]
    attendus = [a["id"] for a in registre["applications"]]
    assert sorted(vus) == sorted(attendus), \
        "application perdue ou comptee deux fois : %s" % sorted(set(attendus) ^ set(vus))


# --- 5. Les candidats : des noms, jamais un conseil -------------------------

def _releve_avec_voisins(nos_modifs, voisins):
    return {"fiches": {"org/Modele2.1": _fiche("apache-2.0", nos_modifs)},
            "voisins": {"org": voisins}}


def test_seuls_les_voisins_PLUS_RECENTS_de_la_meme_famille_sont_proposes(outil):
    verdict = outil.comparer(
        _mini("https://huggingface.co/org/Modele2.1", "Apache 2.0"),
        _releve_avec_voisins("2026-01-01T00:00:00.000Z", [
            {"id": "org/Modele2.1", "lastModified": "2026-06-01T00:00:00.000Z"},
            {"id": "org/Modele3.0", "lastModified": "2026-06-01T00:00:00.000Z"},
            {"id": "org/Modele1.0", "lastModified": "2025-01-01T00:00:00.000Z"},
            {"id": "org/AutreChose9", "lastModified": "2026-06-01T00:00:00.000Z"},
        ]))
    proposes = [c["depot"] for c in verdict["candidats"]]
    assert proposes == ["org/Modele3.0"], (
        "le depot lui-meme, un plus ancien ou une autre famille ne sont pas "
        "des candidats : %s" % proposes)


def test_les_candidats_sont_plafonnes_a_trois(outil):
    """Un ticket hebdomadaire de 26 lignes ne se lit pas ; le premier en avait 26."""
    voisins = [{"id": "org/Modele%d.0" % n,
                "lastModified": "2026-0%d-01T00:00:00.000Z" % (n % 9 + 1)}
               for n in range(2, 12)]
    verdict = outil.comparer(
        _mini("https://huggingface.co/org/Modele2.1", "Apache 2.0"),
        _releve_avec_voisins("2026-01-01T00:00:00.000Z", voisins))
    assert len(verdict["candidats"]) == 3


# --- 6. Les trois codes de sortie -------------------------------------------

def _jouer(tmp_path, releve):
    fichier = tmp_path / "releve.json"
    fichier.write_text(json.dumps(releve), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(CHEMIN), "--hors-ligne", str(fichier)],
        cwd=RACINE, capture_output=True, text=True, encoding="utf-8")


def test_code_0_quand_tout_concorde(tmp_path, outil, registre):
    fiches = {}
    for app in registre["applications"]:
        depot = outil.depot_de(app["source"])
        if depot:
            fiches[depot] = _fiche(None)  # muet : non comparable, jamais rouge
    assert _jouer(tmp_path, {"fiches": fiches}).returncode == 0


def test_code_1_des_qu_un_humain_doit_trancher(tmp_path, outil, registre):
    fiches = {}
    for app in registre["applications"]:
        depot = outil.depot_de(app["source"])
        if depot:
            fiches[depot] = {"absent": True}
    assert _jouer(tmp_path, {"fiches": fiches}).returncode == 1


def test_le_script_ne_touche_jamais_au_registre(tmp_path, outil, registre):
    """Il PROPOSE. Une licence qui change est une decision humaine.

    S'il se mettait a corriger tout seul, le premier faux desaccord -- il y en
    a eu deux au premier passage -- reecrirait une licence juste par une
    fausse, sans que personne le voie.
    """
    avant = (RACINE / "registry" / "apps.json").read_bytes()
    fiches = {}
    for app in registre["applications"]:
        depot = outil.depot_de(app["source"])
        if depot:
            fiches[depot] = _fiche("cc-by-nc-4.0")
    _jouer(tmp_path, {"fiches": fiches})
    assert (RACINE / "registry" / "apps.json").read_bytes() == avant
    source = CHEMIN.read_text(encoding="utf-8")
    assert "REGISTRE.write" not in source, "le script ecrit dans le registre"
def test_code_2_quand_l_outil_TOMBE_et_jamais_1(tmp_path):
    """Une panne n'est ni un accord ni un desaccord : personne n'a rien verifie.

    Defaut mesure le 21/09/2026 par ce banc meme : le script plantait sur la
    premiere fleche du rapport quand la console n'est pas en UTF-8, et ce
    plantage sortait en code 1 -- qui se lit << un humain doit trancher >>. Un
    humain aurait ouvert un ticket vide en cherchant un desaccord inexistant ;
    la fois suivante il ne l'aurait plus ouvert.
    """
    resultat = subprocess.run(
        [sys.executable, str(CHEMIN), "--hors-ligne", str(tmp_path / "rien.json")],
        cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    assert resultat.returncode == 2, (
        "une panne doit sortir en 2, pas en %d" % resultat.returncode)
    assert "NI une concordance" in resultat.stderr
# --- 7. L'inscription de la relecture : une ligne, et rien d'autre ----------

ECRIVAIN = RACINE / "scripts" / "inscrire-la-relecture.py"


@pytest.fixture(scope="module")
def ecrivain():
    spec = importlib.util.spec_from_file_location("inscription", ECRIVAIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def texte_du_registre():
    return (RACINE / "registry" / "apps.json").read_text(encoding="utf-8")


def test_la_date_de_relecture_se_pose_apres_celle_de_l_humain(ecrivain, texte_du_registre):
    apres = ecrivain.inscrire(texte_du_registre, "chat_auto", "2026-09-21")
    bloc = apres[slice(*ecrivain.bloc_de(apres, "chat_auto"))]
    assert '"relu_le": "2026-09-21"' in bloc
    assert bloc.index('"verifie_le"') < bloc.index('"relu_le"')


def test_le_champ_de_l_humain_n_est_JAMAIS_avance(ecrivain, texte_du_registre):
    """Le point entier de ce second champ.

    `verifie_le` dit << un humain a ouvert la page officielle >>. Une machine
    qui avancerait cette date ferait dire au fichier autre chose que ce qu'il
    sait, en silence.
    """
    avant = re.findall(r'"verifie_le": "[^"]*"', texte_du_registre)
    apres = ecrivain.inscrire(texte_du_registre, "chat_auto", "2026-09-21")
    assert re.findall(r'"verifie_le": "[^"]*"', apres) == avant


def test_inscrire_deux_fois_ne_change_rien_la_seconde(ecrivain, texte_du_registre):
    une = ecrivain.inscrire(texte_du_registre, "chat_auto", "2026-09-21")
    deux = ecrivain.inscrire(une, "chat_auto", "2026-09-21")
    assert une == deux


def test_une_relecture_plus_recente_REMPLACE_au_lieu_d_empiler(ecrivain, texte_du_registre):
    une = ecrivain.inscrire(texte_du_registre, "chat_auto", "2026-09-21")
    deux = ecrivain.inscrire(une, "chat_auto", "2026-09-28")
    assert deux.count('"relu_le"') == 1
    assert '"relu_le": "2026-09-28"' in deux


def test_une_seule_ligne_bouge_par_entree(ecrivain, texte_du_registre):
    """La demande de fusion doit se relire d'un coup d'oeil.

    Un `json.dumps` du registre relu rendait 13 616 octets contre 13 320 :
    toutes les listes ecrites sur une ligne se depliaient, et les 16 entrees
    apparaissaient modifiees. Personne ne relit une demande pareille, donc
    personne ne la refuse.
    """
    apres = ecrivain.inscrire(texte_du_registre, "chat_auto", "2026-09-21")
    avant_l = texte_du_registre.splitlines()
    apres_l = apres.splitlines()
    assert len(apres_l) == len(avant_l) + 1
    ajoutees = [l for l in apres_l if l not in avant_l]
    assert len(ajoutees) == 1 and "relu_le" in ajoutees[0]


def test_le_registre_reste_du_json_valide(ecrivain, texte_du_registre, registre):
    apres = ecrivain.inscrire(texte_du_registre, "chat_auto", "2026-09-21")
    relu = json.loads(apres)
    for avant_app, apres_app in zip(registre["applications"], relu["applications"]):
        attendu = dict(avant_app)
        if apres_app["id"] == "chat_auto":
            attendu["relu_le"] = "2026-09-21"
        assert apres_app == attendu


def test_une_application_inconnue_est_refusee_et_non_ajoutee(ecrivain, texte_du_registre):
    with pytest.raises(KeyError):
        ecrivain.inscrire(texte_du_registre, "application_qui_n_existe_pas", "2026-09-21")


def test_aucune_date_n_est_inscrite_tant_qu_il_reste_a_trancher(tmp_path):
    """Un desaccord veut dire que la lecture du jour CONTREDIT le registre.

    Inscrire quand meme les dates des autres entrees ferait passer pour relu un
    fichier qu'un humain doit ouvrir.
    """
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps(
        {"concordent": [{"id": "chat_auto"}], "desaccords": [{"id": "video_maison"}],
         "disparus": []}), encoding="utf-8")
    avant = (RACINE / "registry" / "apps.json").read_bytes()
    fait = subprocess.run(
        [sys.executable, str(ECRIVAIN), "--verdict", str(verdict), "--jour", "2026-09-21"],
        cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    assert fait.returncode == 1
    assert (RACINE / "registry" / "apps.json").read_bytes() == avant


def test_les_deux_scripts_restent_separes():
    """Un qui lit chez l'editeur, un qui ecrit chez nous. Jamais le meme.

    Si le juge ecrivait, le premier faux desaccord -- il y en a eu deux au
    premier passage -- reecrirait le registre avant que personne ne l'ait vu.
    """
    juge = CHEMIN.read_text(encoding="utf-8")
    ecrivain = ECRIVAIN.read_text(encoding="utf-8")
    assert "REGISTRE.write" not in juge, "le juge ecrit dans le registre"
    assert "urllib" not in ecrivain, "l'ecrivain touche au reseau"


def test_une_date_illisible_est_refusee_sans_rien_ecrire(tmp_path):
    """`--jour` vient d'un travail programme ; une date mal formee doit crier.

    Ecrire `"relu_le": "aujourd'hui"` dans le registre serait pire que ne rien
    ecrire : le champ se lirait encore comme une date.
    """
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps(
        {"concordent": [{"id": "chat_auto"}], "desaccords": [], "disparus": []}),
        encoding="utf-8")
    avant = (RACINE / "registry" / "apps.json").read_bytes()
    fait = subprocess.run(
        [sys.executable, str(ECRIVAIN), "--verdict", str(verdict), "--jour", "lundi"],
        cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    assert fait.returncode == 2
    assert (RACINE / "registry" / "apps.json").read_bytes() == avant


# --- 8. Le travail programme : les trois codes y restent distincts ----------

HEBDO = RACINE / ".github" / "workflows" / "licences.yml"


def _etapes() -> list[str]:
    """Le workflow decoupe en etapes, sans pyyaml -- la CI ne l'installe pas."""
    texte = HEBDO.read_text(encoding="utf-8")
    debut = texte.index("    steps:")
    return re.split(r"\n      - (?=uses:|name:)", texte[debut:])[1:]


def _etape(bout: str) -> str:
    for morceau in _etapes():
        if bout in morceau:
            return morceau
    raise AssertionError("aucune etape ne contient %r" % bout)


def test_une_panne_de_lecture_n_ouvre_NI_ticket_NI_fusion():
    """Le seul endroit ou ce travail peut mentir.

    Un reseau en panne rend 2. S'il ouvrait un ticket << desaccord >>, on
    apprendrait a ne plus lire les tickets ; s'il se taisait, la semaine
    passerait pour verifiee.
    """
    for bout, code in (("gh issue create", "'1'"), ("inscrire-la-relecture", "'0'")):
        etape = _etape(bout)
        assert "steps.relire.outputs.code == %s" % code in etape, (
            "l'etape qui contient %r doit etre conditionnee au code %s" % (bout, code))

    panne = _etape("::error::")
    assert "steps.relire.outputs.code == '2'" in panne
    assert "exit 1" in panne, "une lecture impossible doit faire ECHOUER le travail"


def test_le_juge_n_est_jamais_blanchi():
    """`|| true` et `continue-on-error` transforment un rouge en vert.

    C'est la facon la plus courante de fabriquer une CI verte, et elle avait
    deja coute cinq jours de rouge invisible sur `validate.yml`.
    """
    etape = _etape("proposer-les-mises-a-jour.py")
    assert "continue-on-error" not in etape
    assert "|| true" not in etape
    assert "$GITHUB_OUTPUT" in etape, "le code de sortie doit etre transmis tel quel"


def test_la_machine_ne_pousse_que_sur_une_branche_a_elle():
    """Une fusion reste le geste d'un humain : le robot propose, il ne fusionne pas."""
    etape = _etape("git push")
    assert 'git push origin "$branche"' in etape
    assert "--head" in etape and "gh pr create" in etape
    texte = HEBDO.read_text(encoding="utf-8")
    assert "gh pr merge" not in texte, "le robot fusionnerait tout seul"
    for interdit in ("git push origin main", "git push origin HEAD:main", "--admin"):
        assert interdit not in texte, "le robot ecrit sur la branche par defaut : %s" % interdit


def test_les_deux_scripts_appeles_existent():
    texte = HEBDO.read_text(encoding="utf-8")
    for appele in ("scripts/proposer-les-mises-a-jour.py", "scripts/inscrire-la-relecture.py"):
        assert appele in texte
        assert (RACINE / appele).exists(), "le workflow appelle un script absent : %s" % appele
