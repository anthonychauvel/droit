#!/usr/bin/env python3
"""
Complète les CCN déjà téléchargées avec le texte intégral de leur(s) clause(s)
temps partiel / heures complémentaires -- même trou que fetch_overtime_details.py
et fetch_forfaitjours_details.py, mais pour un troisième sujet : le container
KALI de base ne renvoie que des stubs vides pour ces sections aussi.

Cherche spécifiquement les clauses qui fixent :
- le plafond des heures complémentaires (10% par défaut, jusqu'à 1/3 par accord)
- le taux de majoration de ces heures (10% / 25%)
- le délai de prévenance (7j par défaut, 3j minimum par accord)
- le mécanisme d'avenant de complément d'heures

Pour chaque CCN déjà dans output/ccn/<idcc>.json :
1. Trouve la ou les sections "temps partiel/heures complémentaires/complément
   d'heures/délai de prévenance" qui n'ont pas de contenu inline (stub)
2. Récupère leur texte complet via /consult/kaliText
3. Remplace les stubs par le contenu réel, directement dans le même fichier

Usage:
    python3 fetch_partiel_details.py --ccn-dir output/ccn
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

# Mots-clés temps partiel -- volontairement larges, les intitulés varient
KEYWORDS = (
    "temps partiel", "heures complémentaires", "complément d'heures",
    "complément d heures", "délai de prévenance", "avenant de complément",
)


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


def find_all_stubs(node, keywords=KEYWORDS, max_stubs=3):
    """Retourne jusqu'à max_stubs (noeud) triés du plus récent au plus ancien.
    Plusieurs stubs gardés car plafond/majoration/délai de prévenance peuvent
    être répartis sur des sous-articles distincts (vu sur le forfait jours)."""
    candidates = []

    def walk(n):
        titre = n.get('title') or n.get('titre') or ''
        node_id = n.get('id') or n.get('cid')
        articles = n.get('articles') or []
        has_content = any(a.get('content') or a.get('texte') for a in articles)
        sections = n.get('sections') or []
        if node_id and not has_content and not sections and any(k in titre.lower() for k in keywords):
            candidates.append(n)
        for child in sections:
            walk(child)

    walk(node)
    candidates.sort(key=lambda c: extract_date_or_num(c.get('title') or c.get('titre') or ''), reverse=True)
    return candidates[:max_stubs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--max-stubs-par-ccn", type=int, default=3,
                     help="Nombre max de stubs temps-partiel à récupérer par CCN (défaut 3)")
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
    print(f"Token OK. {len(ok_ids)} CCN à examiner pour complément temps partiel/heures complémentaires.")

    n_updated = 0
    n_skipped = 0
    n_error = 0
    n_stubs_total = 0

    for i, idcc in enumerate(ok_ids, 1):
        filepath = os.path.join(args.ccn_dir, f"{idcc}.json")
        if not os.path.exists(filepath):
            continue
        data = json.load(open(filepath, encoding="utf-8"))
        stubs = find_all_stubs(data, max_stubs=args.max_stubs_par_ccn)
        if not stubs:
            n_skipped += 1
            continue

        print(f"[{i}/{len(ok_ids)}] IDCC {idcc}: {len(stubs)} stub(s) temps-partiel trouvé(s)")
        updated_any = False
        for stub_node in stubs:
            text_id = stub_node.get('id') or stub_node.get('cid')
            titre_court = (stub_node.get('title') or stub_node.get('titre') or '')[:60]
            print(f"    -> '{titre_court}'...", end=" ")

            result = call_api(base_url, token, "/consult/kaliText", {"id": text_id})
            if "_error" in result:
                print(f"ERREUR {result['_error']}")
                n_error += 1
                time.sleep(args.delay)
                continue

            stub_node["articles"] = result.get("articles", [])
            stub_node["sections"] = result.get("sections", [])
            stub_node["_texte_complet_recupere"] = True
            stub_node["_type_complement"] = "temps_partiel"

            n_articles = len(stub_node["articles"])
            print(f"OK ({n_articles} article(s))")
            n_stubs_total += 1
            updated_any = True
            time.sleep(args.delay)

        if updated_any:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            n_updated += 1

    print(f"\nTerminé: {n_updated} CCN complétées ({n_stubs_total} stubs au total), "
          f"{n_skipped} sans clause temps-partiel trouvée, {n_error} erreurs.")


if __name__ == "__main__":
    main()
