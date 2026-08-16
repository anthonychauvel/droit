#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Aide partagee : commit + push ROBUSTE depuis un script Python (pas seulement
depuis le YAML du workflow). Utilisee par les scripts d'aspiration pour
committer PERIODIQUEMENT (ex. tous les 700 fichiers), pas seulement une fois
a la toute fin -> si le job est interrompu (timeout, coupure), le travail deja
fait est deja sur main, pas perdu.

Meme logique que le workflow : jusqu'a 5 tentatives, avec fetch+rebase entre
chaque pour absorber un commit concurrent. Si ca echoue quand meme, on
REMONTE l'echec (l'appelant decide quoi faire) plutot que de l'avaler.
"""

import subprocess, time


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def commit_et_push(chemins, message, tentatives=5):
    """Ajoute les chemins donnes, committe, pousse. Renvoie (ok, detail).
    Ne leve jamais d'exception -> l'appelant garde la main sur l'echec."""
    for p in chemins:
        _run(["git", "add", p])

    diff = _run(["git", "diff", "--staged", "--quiet"])
    if diff.returncode == 0:
        return True, "rien de nouveau a committer"

    c = _run(["git", "commit", "-m", message])
    if c.returncode != 0:
        return False, "echec du commit : %s" % (c.stderr or c.stdout)[:300]

    for tentative in range(1, tentatives + 1):
        p = _run(["git", "push"])
        if p.returncode == 0:
            return True, "pousse (tentative %d)" % tentative
        time.sleep(tentative * 5)
        _run(["git", "fetch", "origin", "main"])
        r = _run(["git", "rebase", "origin/main"])
        if r.returncode != 0:
            _run(["git", "rebase", "--abort"])
            return False, "rebase en conflit a la tentative %d : %s" % (tentative, (r.stderr or "")[:300])
    return False, "push impossible apres %d tentatives" % tentatives
