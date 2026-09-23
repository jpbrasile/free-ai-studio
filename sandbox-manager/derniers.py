"""Les derniers travaux d'une page : un rechargement ne perd plus rien.

Le 23/09/2026, un clip loue chez Modal a << disparu >> : la page avait ete
rechargee, et elle repartait d'un ecran vide alors que le travail tournait
encore, et etait facture. La fiche du travail, elle, n'avait rien perdu : elle
vit sur le disque du Studio. Il manquait seulement a la page un moyen de la
retrouver.

D'ou deux pieces, les memes pour /video, /chanson et /dialogue :

- `lister()` rend les derniers travaux d'une page, lus dans les fiches ;
- `supprimer()` efface un travail : sa fiche et ses fichiers. Un travail en
  cours est d'abord ARRETE par le service (<< refusee si en cours : non, ca
  devient abort >>, proprietaire, 23/09), puis efface ;
- `dans_la_page()` ajoute a la page une liste << Vos travaux >> -- revoir,
  telecharger, supprimer -- et reprend tout seul le suivi d'un travail encore
  en cours.

Demande du proprietaire le meme jour : << on doit pouvoir voir nos travaux
passes, les telecharger ou les supprimer >>.

Le suivi lui-meme n'est pas reecrit : chaque page a deja sa fonction
`suivre(id)`, qui sait afficher un travail en cours comme un travail fini. On
l'appelle, rien de plus. Le serveur plutot que le navigateur : la liste suit
aussi un autre onglet, un autre navigateur, et un Studio redemarre.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Callable, Optional

EN_COURS = ("queued", "routing", "preparing", "submitting", "running")
USAGES = ("video", "chanson", "dialogue")
NOMBRE = 20
# Les fiches lues au plus : les plus recentes d'abord. Les autres usages
# (bac a sable, carnets) partagent le dossier, d'ou une marge.
FICHES_LUES = 200


def libelle(job: dict, usage: str) -> str:
    """Ce qui distingue ce travail des autres, en une ligne."""
    if usage == "video":
        texte = str((job.get("video") or {}).get("description") or "")
    elif usage == "dialogue":
        repliques = job.get("dialogue_repliques") or []
        texte = str(repliques[0]) if repliques else ""
        # « [S1]Bonjour » : l'etiquette du locuteur n'aide pas a reconnaitre.
        if texte.startswith("[S") and "]" in texte:
            texte = texte.split("]", 1)[1]
    else:
        secondes = (job.get("chanson") or {}).get("secondes_max")
        texte = "chanson de %s s au plus" % secondes if secondes else "chanson"
    texte = " ".join(texte.split())
    return texte if len(texte) <= 70 else texte[:69] + "…"


def lister(dossier: Path, usage: str, nombre: int = NOMBRE,
           lien: Optional[Callable[[str], str]] = None) -> list[dict]:
    """Les derniers travaux de cette page, le plus recent d'abord.

    `lien(id)` rend l'adresse de telechargement d'un travail fini, ou "" s'il
    n'a pas de fichier ; il vient du service, seul a savoir signer l'adresse.
    Une fiche illisible est sautee sans casser la liste : elle ne dit rien de
    plus a la page qu'une fiche absente."""
    if usage not in USAGES:
        raise ValueError("usage inconnu : %s" % usage)
    fiches = sorted(dossier.glob("*/job.json"), key=lambda p: p.stat().st_mtime,
                    reverse=True)[:FICHES_LUES]
    sortie = []
    for chemin in fiches:
        try:
            job = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict) or usage not in job:
            continue
        statut = str(job.get("status") or "")
        sortie.append({
            "id": str(job.get("id") or chemin.parent.name),
            "status": statut,
            "en_cours": statut in EN_COURS,
            "created_at": job.get("created_at"),
            # Seul Modal se paie ; Kaggle et la carte d'ici sont gratuits.
            "loue": (job.get("provider_effective") or job.get("provider")) == "modal",
            "libelle": libelle(job, usage),
        })
    sortie.sort(key=lambda t: t["created_at"] or 0, reverse=True)
    sortie = sortie[:nombre]
    for t in sortie:
        t["telecharger"] = (lien(t["id"]) or "") if lien and t["status"] == "succeeded" else ""
    return sortie


class TravailEnCours(Exception):
    """Le service arrete un travail AVANT de l'effacer. Effacer la fiche d'un
    travail qui tourne laisserait une machine louee facturee sans personne pour
    la voir : ce module refuse donc, et c'est le filet si l'arret a ete oublie."""


_ID_SUR = re.compile(r"[A-Za-z0-9_-]{1,64}")


def id_sur(jid: str) -> bool:
    """Un identifiant qui ne peut pas sortir du dossier des travaux."""
    return bool(_ID_SUR.fullmatch(jid or ""))


def supprimer(jobs: Path, artefacts: Path, usage: str, jid: str) -> list[str]:
    """Efface la fiche du travail et les fichiers qu'il a rendus.

    Rend les noms effaces. `LookupError` si le travail n'existe pas ou n'est
    pas de cette page -- /video n'efface pas une chanson --, `TravailEnCours`
    s'il tourne encore. Les noms de fichier viennent de la fiche : un nom qui
    sortirait du dossier des artefacts est ignore, jamais suivi."""
    if usage not in USAGES:
        raise ValueError("usage inconnu : %s" % usage)
    if not id_sur(jid):
        raise LookupError(jid)
    dossier = jobs / jid
    try:
        job = json.loads((dossier / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise LookupError(jid) from None
    if not isinstance(job, dict) or usage not in job:
        raise LookupError(jid)
    if str(job.get("status") or "") in EN_COURS:
        raise TravailEnCours(jid)
    effaces = []
    for art in job.get("artifacts") or []:
        noms = [str(art.get("path") or "")]
        if art.get("id"):
            noms.append("%s.json" % art["id"])
        for nom in noms:
            if not nom or Path(nom).name != nom or nom in (".", ".."):
                continue
            chemin = artefacts / nom
            if chemin.is_file() and not chemin.is_symlink():
                chemin.unlink()
                effaces.append(nom)
    shutil.rmtree(dossier)
    effaces.append(jid + "/")
    return effaces


ETATS_JS = """{queued:"en attente", routing:"en attente", preparing:"en préparation",
  submitting:"envoi", running:"en cours", succeeded:"fini", failed:"échec",
  cancelled:"arrêté", handoff_ready:"à lancer vous-même",
  needs_configuration:"à configurer"}"""

BLOC = """
<section id="derniers" hidden style="margin-top:2em">
<h2>Vos travaux</h2>
<p class="avert">Un travail continue même si vous fermez ou rechargez la page. Cliquez sur
l’heure pour le revoir.</p>
<ul id="derniers-liste"></ul>
</section>
<script>
(function(){
  const USAGE = "__USAGE__";
  const ETATS = """ + ETATS_JS + """;
  let vu = null;       // le travail affiché en ce moment, pour l'effacer aussi de l'écran
  function texteSur(t){
    return String(t == null ? "" : t).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"})[c]);
  }
  function heure(s){
    if(!s) return "";
    const d = new Date(s * 1000);
    return String(d.getDate()).padStart(2,"0") + "/" + String(d.getMonth()+1).padStart(2,"0")
      + " à " + String(d.getHours()).padStart(2,"0") + " h " + String(d.getMinutes()).padStart(2,"0");
  }
  function revoir(id){
    if(minuteur){ clearInterval(minuteur); minuteur = null; }
    vu = id;
    document.getElementById("lancer").disabled = true;
    document.getElementById("etat").textContent = "Lecture du travail…";
    suivre(id);
  }
  function ligne(t){
    return '<li><a href="#" data-voir="' + texteSur(t.id) + '">' + heure(t.created_at) + "</a> — "
      + texteSur(ETATS[t.status] || t.status) + (t.loue ? " (loué)" : "")
      + (t.libelle ? " — « " + texteSur(t.libelle) + " »" : "")
      + (t.telecharger ? ' <a class="bouton discret" href="' + texteSur(t.telecharger)
                         + '">⬇️ Télécharger</a>' : "")
      + ' <button type="button" class="discret" data-suppr="' + texteSur(t.id)
      + '" data-encours="' + (t.en_cours ? "1" : "") + '">' + libelleSuppr(t.en_cours) + "</button>"
      + "</li>";
  }
  // Un travail en cours s'arrête d'abord (une machine louée cesse d'être
  // facturée), puis s'efface : le bouton le dit avant qu'on clique.
  function libelleSuppr(enCours){
    return enCours ? "⛔ Arrêter et supprimer" : "🗑️ Supprimer";
  }
  // Deux clics, sans fenêtre qui surgit : le premier demande, le second efface.
  // Au bout de cinq secondes sans second clic, le bouton redevient sage.
  function supprimer(b){
    const enCours = b.dataset.encours === "1";
    if(b.dataset.arme !== "1"){
      b.dataset.arme = "1";
      b.textContent = enCours ? "Confirmer : arrêter et effacer" : "Confirmer : effacer pour de bon";
      setTimeout(() => { b.dataset.arme = ""; b.textContent = libelleSuppr(enCours); }, 5000);
      return;
    }
    const id = b.dataset.suppr;
    b.disabled = true;
    fetch("/" + USAGE + "/jobs/" + encodeURIComponent(id),
          {method:"DELETE", headers:{"Authorization":"Bearer "+CLE}})
      .then(async r => {
        const d = await r.json().catch(() => ({}));
        if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
        if(vu === id){
          if(minuteur){ clearInterval(minuteur); minuteur = null; }
          vu = null;
          document.getElementById("lancer").disabled = false;
          document.getElementById("resultat").innerHTML = "";
          // Ce que l'arrêt a vraiment fait, mot pour mot : Kaggle, par exemple,
          // n'a pas d'annulation, et le client doit le lire.
          document.getElementById("etat").textContent = d.arret
            ? "Travail arrêté et supprimé. " + d.arret : "Travail supprimé.";
        }
        charger(false);
      })
      .catch(e => { b.disabled = false; b.textContent = "✖ " + e.message; });
  }
  function charger(reprendre){
    return fetch("/" + USAGE + "/derniers", {headers:{"Authorization":"Bearer "+CLE}})
      .then(r => r.ok ? r.json() : [])
      .then(liste => {
        const bloc = document.getElementById("derniers");
        if(!Array.isArray(liste) || !liste.length){ bloc.hidden = true; return; }
        const ul = document.getElementById("derniers-liste");
        ul.innerHTML = liste.map(ligne).join("");
        ul.querySelectorAll("a[data-voir]").forEach(a => a.addEventListener("click", e => {
          e.preventDefault(); revoir(a.dataset.voir);
        }));
        ul.querySelectorAll("button[data-suppr]").forEach(b => b.addEventListener("click",
          () => supprimer(b)));
        bloc.hidden = false;
        // Un travail tourne encore : on le reprend sans attendre de clic. C'est
        // tout le but : la page rechargée retrouve ce qu'elle suivait.
        const enCours = liste.find(t => t.en_cours);
        if(reprendre && enCours && !minuteur){
          revoir(enCours.id);
          document.getElementById("etat").textContent =
            "⏳ Suivi repris : travail lancé le " + heure(enCours.created_at) + ".";
        }
      })
      .catch(() => {});
  }
  charger(true);
  // La liste se tient à jour d'elle-même : un travail lancé ou fini ici y
  // apparaît sans recharger la page.
  setInterval(() => charger(false), 30000);
})();
</script>
"""


def dans_la_page(page: str, usage: str) -> str:
    """Ajoute la liste en bas de page, dans un script a part.

    A part, et apres le script de la page : `minuteur`, `suivre` et `CLE` y
    sont declares au niveau global, donc visibles d'ici ; `format_fr` pose ses
    formateurs dans le PREMIER script, qui reste celui de la page."""
    if usage not in USAGES:
        raise ValueError("usage inconnu : %s" % usage)
    if page.count("</body>") != 1:
        raise ValueError("la page doit avoir un seul </body>")
    return page.replace("</body>", BLOC.replace("__USAGE__", usage) + "</body>")
