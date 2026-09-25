// Free AI Studio : le bouton « 🏠 Studio » dans le chat.
//
// Demande de l'utilisateur du 25/09/2026 : « cliquer sur chat fait sortir du
// studio ». Les autres pages ont ce bouton (accueil.py) ; le chat est Open WebUI,
// qu'on ne modifie pas. Open WebUI charge ce fichier, vide d'origine, sur chaque
// page (static/loader.js) : c'est sa porte prévue pour ce genre d'ajout.
// docker-compose.yml le monte en lecture seule. Rien d'autre ici : pas de
// lecture des conversations, pas d'appel réseau.
(function () {
  function poser() {
    if (document.getElementById("studio-accueil") || !document.body) return;
    var a = document.createElement("a");
    a.id = "studio-accueil";
    a.textContent = "🏠 Studio";
    a.title = "Revenir à la page du Studio";
    a.href = location.protocol + "//" + (location.hostname || "127.0.0.1") + ":8010/studio";
    // En haut, au milieu : les coins sont pris par Open WebUI (menu, profil,
    // envoi du message).
    a.style.cssText = "position:fixed;top:10px;left:50%;transform:translateX(-50%);" +
      "z-index:2147483000;padding:6px 14px;border-radius:999px;background:#1f2937;color:#fff;" +
      "font:600 14px/1.2 system-ui,sans-serif;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.3)";
    document.body.appendChild(a);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", poser);
  } else {
    poser();
  }
  // Open WebUI refait sa page sans la recharger : on repose le bouton s'il part.
  setInterval(poser, 2000);
})();
