#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reparer_titres_jorf.py — Répare les titres VIDES des textes JORF récupérés par
l'ancienne méthode (énumération), sans tout re-télécharger.

Contexte : les ~50 premiers textes JORF ont été récupérés avant qu'on passe à
la recherche par dates. Ils ont un champ 'titre' vide -> le manifest affiche
"Texte JORF {id}" en secours, illisible. Ce script parcourt output/jorf,
repère les fichiers à titre vide, va chercher leur titre via /consult/jorf
(endpoint qui fonctionne) et le remplit. Il ne touche QUE ces fichiers-là.

Usage (via workflow, cible 'reparer-titres') :
    python3 scripts/reparer_titres_jorf.py --out output/jorf
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
import subprocess


def get_urls():
    env = os.environ.get("PISTE_ENV", "sandbox").lower()
    if env == "production":
        return ("https://oauth.piste.gouv.fr/api/oauth/token",
                "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app")
    return ("https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
            "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app")


def get_token(token_url, cid, secret):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid,
        "client_secret": secret, "scope": "openid"}).encode()
    req = urllib.request.Request(token_url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


class Client:
    """Client avec renouvellement de token sur 401."""
    def __init__(self, token_url, base, cid, secret):
        self.token_url, self.base = token_url, base
        self.cid, self.secret = cid, secret
        self.token = get_token(token_url, cid, secret)

    def consult(self, text_id, _retry=True):
        req = urllib.request.Request(
            self.base + "/consult/jorf",
            data=json.dumps({"textCid": text_id}).encode(),
            method="POST", headers={"Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry:
                self.token = get_token(self.token_url, self.cid, self.secret)
                return self.consult(text_id, _retry=False)
            return {"_error": e.code}
        except Exception as e:
            return {"_error": str(e)}


def titre_depuis_reponse(rep):
    """Extrait le titre d'une réponse /consult/jorf."""
    if not isinstance(rep, dict):
        return ""
    # Le titre peut être à divers endroits selon la structure
    for cle in ("title", "titre"):
        if rep.get(cle):
            return rep[cle]
    txt = rep.get("text") or rep.get("texte") or {}
    if isinstance(txt, dict):
        for cle in ("title", "titre"):
            if txt.get(cle):
                return txt[cle]
    return ""


def commit_push(dossier, n):
    try:
        subprocess.run(["git", "add", dossier], check=False, capture_output=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"],
                          capture_output=True).returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", f"JORF: réparation de {n} titres vides"],
                       check=False, capture_output=True)
        r = subprocess.run(["git", "push"], capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"],
                           check=False, capture_output=True)
            subprocess.run(["git", "push"], check=False, capture_output=True)
        print(f"  {n} titres réparés, committés et poussés.")
    except Exception as e:
        print(f"  commit non bloquant échoué : {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/jorf")
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    cid = os.environ.get("PISTE_CLIENT_ID")
    secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not cid or not secret:
        print("Identifiants manquants", file=sys.stderr)
        return 1

    # 1) Repérer les fichiers à titre vide
    a_reparer = []
    for nom in os.listdir(args.out):
        if not nom.startswith("JORFTEXT") or not nom.endswith(".json"):
            continue
        chemin = os.path.join(args.out, nom)
        try:
            d = json.load(open(chemin, encoding="utf-8"))
        except Exception:
            continue
        if not (d.get("titre") or "").strip():
            a_reparer.append((nom[:-5], chemin))  # (id sans .json, chemin)

    print(f"{len(a_reparer)} fichier(s) JORF à titre vide repérés.")
    if not a_reparer:
        print("Rien à réparer.")
        return 0

    # 2) Récupérer et remplir les titres
    token_url, base = get_urls()
    client = Client(token_url, base, cid, secret)
    n_ok = 0
    summary_path = os.path.join(args.out, "_summary.json")
    summary = []
    if os.path.exists(summary_path):
        try:
            summary = json.load(open(summary_path, encoding="utf-8"))
        except Exception:
            summary = []
    summary_par_id = {e.get("id"): e for e in summary}

    for i, (tid, chemin) in enumerate(a_reparer, 1):
        rep = client.consult(tid)
        if "_error" in rep:
            print(f"  [{i}/{len(a_reparer)}] {tid} : échec ({rep['_error']})", file=sys.stderr)
            time.sleep(args.delay)
            continue
        titre = titre_depuis_reponse(rep)
        if not titre:
            print(f"  [{i}/{len(a_reparer)}] {tid} : pas de titre trouvé", file=sys.stderr)
            time.sleep(args.delay)
            continue
        # Mettre à jour le fichier
        try:
            d = json.load(open(chemin, encoding="utf-8"))
            d["titre"] = titre
            if isinstance(d.get("text"), dict) and not d["text"].get("titre"):
                d["text"]["titre"] = titre
            json.dump(d, open(chemin, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            # Mettre à jour le summary
            if tid in summary_par_id:
                summary_par_id[tid]["titre"] = titre
            n_ok += 1
            print(f"  [{i}/{len(a_reparer)}] {tid} : {titre[:55]}")
        except Exception as e:
            print(f"  [{i}/{len(a_reparer)}] {tid} : erreur écriture {e}", file=sys.stderr)
        time.sleep(args.delay)

    # 3) Réécrire le summary et committer
    json.dump(summary, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    commit_push(args.out, n_ok)
    print(f"\n{n_ok}/{len(a_reparer)} titres réparés.")
    print("Le manifest sera régénéré par l'étape suivante du workflow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
