"""Tenir la carte pour un lot de travail de l'opérateur (07/10 : « put that in priority, run living doc after
completion »), déposé dans la file dsh3 en `urgente --ok` : ce qui tenait gpu/julia est arrêté et redéposé juste
derrière ; il repart quand ce porteur finit.

Pendant qu'il tient : les travaux du Studio « ici » passent (la carte est libre), et chaque commande déposée dans
<dossier>/a_faire/NNN.json ({"cmd": [...], "cwd": "...", "journal": "..."}) est exécutée dans l'ordre, puis rangée
dans fait/ avec son code de retour. Le fichier <dossier>/FIN arrête le porteur (après la commande en cours).

  python porteur.py <dossier>
"""
import json
import subprocess
import sys
import time
from pathlib import Path


def main(dossier):
    d = Path(dossier)
    a_faire, fait = d / "a_faire", d / "fait"
    a_faire.mkdir(parents=True, exist_ok=True)
    fait.mkdir(exist_ok=True)
    print("PORTEUR tient la carte", time.strftime("%H:%M:%S"), flush=True)
    while not (d / "FIN").exists():
        travaux = sorted(a_faire.glob("*.json"))
        if not travaux:
            time.sleep(15)
            continue
        f = travaux[0]
        t = json.loads(f.read_text(encoding="utf-8"))
        debut = time.time()
        print("LANCE", f.name, t["cmd"], flush=True)
        with open(t["journal"], "a", encoding="utf-8") as j:
            rc = subprocess.run(t["cmd"], cwd=t.get("cwd"), stdout=j, stderr=subprocess.STDOUT).returncode
        t.update(rc=rc, duree_s=round(time.time() - debut, 1), fini=time.strftime("%H:%M:%S"))
        (fait / f.name).write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
        f.unlink()
        print("FINI", f.name, "rc", rc, t["duree_s"], "s", flush=True)
    print("PORTEUR rend la carte", time.strftime("%H:%M:%S"), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
