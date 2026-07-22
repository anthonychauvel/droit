#!/usr/bin/env python3
"""
Complète les CCN déjà téléchargées avec le texte intégral de leur avenant
salarial le plus récent -- comble le trou laissé par kaliContIdcc, qui ne
renvoie que des références vides ("stubs") pour les textes attachés.

Pour chaque CCN déjà dans output/ccn/<idcc>.json :
1. Trouve la section "salaire/rémunération/minima" la plus récente qui n'a
   pas de contenu inline (juste un id/titre)
2. Récupère son texte complet via /consult/kaliText
3. Remplace le stub par le contenu réel, directement dans le même fichier

Usage:
    python3 fetch_salary_details.py --ccn-dir output/ccn
"""
import os
import sys
import json
import time
import re
import argparse
import urllib.request
import urllib.error
import urllib.parse

MOIS = {'janvier':1,'février':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,
        'août':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12}


def get_urls():
    env = os.environ.get("PISTE_ENV", "sandbox").lower()
    if env == "production":
        return ("https://oauth.piste.gouv.fr/api/oauth/token",
                 "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app")
    return ("https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
             "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app")


def get_token(token_url, client_id, client_secret):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": client_id,
        "client_secret": client_secret, "scope": "openid",
    }).encode()
    req = urllib.request.Request(token_url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def call_api(base_url, token, path, body):
    req = urllib.request.Request(
        base_url + path, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                  "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")}
    except Exception as e:
        return {"_error": "exception", "_detail": f"{type(e).__name__}: {e}"}


def extract_date_or_num(titre):
    m = re.search(r'(\d{1,2})\s+(' + '|'.join(MOIS) + r')\s+(\d{4})', titre.lower())
    if m:
        return (int(m.group(3)), MOIS.get(m.group(2), 0), int(m.group(1)))
    m2 = re.search(r'[Nn]°?\s*(\d+)', titre)
    if m2:
        return (0, 0, int(m2.group(1)))
    return (0, 0, 0)


def find_best_stub(node, keywords=("salaire", "rémunération", "minima")):
    """Retourne (noeud, chemin_vers_le_noeud) du meilleur stub salaire trouvé,
    ou None. path est une liste d'index pour remonter au noeud dans l'arbre."""
    candidates = []

    def walk(n, path):
        titre = n.get('title') or n.get('titre') or ''
        node_id = n.get('id') or n.get('cid')
        articles = n.get('articles') or []
        has_content = any(a.get('content') or a.get('texte') for a in articles)
        sections = n.get('sections') or []
        if node_id and not has_content and not sections and any(k in titre.lower() for k in keywords):
            candidates.append((n, path))
        for i, child in enumerate(sections):
            walk(child, path + [i])

    walk(node, [])
    if not candidates:
        return None
    return max(candidates, key=lambda c: extract_date_or_num(c[0].get('title') or c[0].get('titre') or ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--delay", type=float, default=1.2)
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.", file=sys.stderr)
        sys.exit(1)

    summary_path = os.path.join(args.ccn_dir, "_summary.json")
    summary = json.load(open(summary_path, encoding="utf-8"))
    ok_ids = [d["idcc"] for d in summary if d["status"] == "ok"]

    token_url, base_url = get_urls()
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(ok_ids)} CCN à examiner pour complément salaire.")

    n_updated = 0
    n_skipped = 0
    n_error = 0

    for i, idcc in enumerate(ok_ids, 1):
        filepath = os.path.join(args.ccn_dir, f"{idcc}.json")
        if not os.path.exists(filepath):
            continue
        data = json.load(open(filepath, encoding="utf-8"))
        best = find_best_stub(data)
        if not best:
            n_skipped += 1
            continue

        stub_node, _ = best
        # Deja recupere lors d'un run precedent : on NE re-telecharge PAS et on NE
        # reecrit PAS le fichier. C'est ce re-telechargement systematique (a chaque run,
        # pour chaque CCN) qui faisait bouger des centaines de fichiers pour rien.
        if stub_node.get("_texte_complet_recupere"):
            n_skipped += 1
            continue
        text_id = stub_node.get('id') or stub_node.get('cid')
        print(f"[{i}/{len(ok_ids)}] IDCC {idcc}: récupération de '{stub_node.get('title','')[:50]}'...", end=" ")

        result = call_api(base_url, token, "/consult/kaliText", {"id": text_id})
        if "_error" in result:
            print(f"ERREUR {result['_error']}")
            n_error += 1
            time.sleep(args.delay)
            continue

        # Fusionne le contenu récupéré dans le noeud stub d'origine
        stub_node["articles"] = result.get("articles", [])
        stub_node["sections"] = result.get("sections", [])
        stub_node["_texte_complet_recupere"] = True

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        n_articles = len(stub_node["articles"])
        print(f"OK ({n_articles} article(s))")
        n_updated += 1
        time.sleep(args.delay)

    print(f"\nTerminé: {n_updated} CCN complétées, {n_skipped} sans avenant salaire trouvé, {n_error} erreurs.")


if __name__ == "__main__":
    main()
