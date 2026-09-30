#!/usr/bin/env python3
"""
Complète les CCN déjà téléchargées avec le texte intégral de leurs textes
RÉCENTS, quel que soit leur sujet (30/09/2026).

Les cinq scripts fetch_*_details.py ne complètent que les stubs dont le titre
parle de salaires, d'heures sup, de forfait jours, de temps partiel ou de
classification. Un avenant récent sur un autre sujet (astreintes, travail de
nuit, congés, durée du travail « déguisée » sous un titre vague) restait un
stub : titre et date seulement. Le tableau de bord de veille ne pouvait alors
chercher ses mots-clés que dans le titre.

Ici : tout texte (KALITEXT) sans contenu dont la dateModif est récente
(--jours, 120 par défaut) est récupéré via /consult/kaliText, du plus récent au
plus ancien, dans la limite de --budget-appels appels par run. Déjà complété
(_texte_complet_recupere) = jamais re-téléchargé.

Usage:
    python3 fetch_recents_details.py --ccn-dir output/ccn --jours 120 --budget-appels 300
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


def find_recent_stubs(node, depuis):
    """Tous les textes KALITEXT sans contenu, modifiés depuis « depuis » (AAAA-MM-JJ)."""
    out = []

    def walk(n):
        if isinstance(n, dict):
            node_id = str(n.get('id') or n.get('cid') or '')
            articles = n.get('articles') or []
            has_content = any(isinstance(a, dict) and (a.get('content') or a.get('texte')) for a in articles)
            sections = n.get('sections') or []
            if (node_id.startswith('KALITEXT') and not has_content and not sections
                    and not n.get('_texte_complet_recupere')
                    and str(n.get('dateModif') or '') >= depuis):
                out.append(n)
            for child in sections:
                walk(child)
        elif isinstance(n, list):
            for child in n:
                walk(child)

    walk(node.get('sections') or [])
    out.sort(key=lambda c: str(c.get('dateModif') or ''), reverse=True)
    return out


def main():
    from datetime import date, timedelta
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--jours", type=int, default=120,
                     help="Ne compléter que les textes modifiés depuis N jours (défaut 120)")
    ap.add_argument("--budget-appels", type=int, default=300,
                     help="Nombre max d'appels /consult/kaliText par run (défaut 300)")
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.", file=sys.stderr)
        sys.exit(1)

    depuis = (date.today() - timedelta(days=args.jours)).isoformat()
    summary_path = os.path.join(args.ccn_dir, "_summary.json")
    summary = json.load(open(summary_path, encoding="utf-8"))
    ok_ids = [d["idcc"] for d in summary if d.get("status") == "ok"]

    token_url, base_url = get_urls()
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(ok_ids)} CCN à examiner (textes modifiés depuis le {depuis}, "
          f"budget {args.budget_appels} appels).")

    n_appels = n_ok = n_err = n_ccn = 0
    for idcc in ok_ids:
        if n_appels >= args.budget_appels:
            print("Budget d'appels atteint -- la suite au prochain run.")
            break
        filepath = os.path.join(args.ccn_dir, f"{idcc}.json")
        if not os.path.exists(filepath):
            continue
        data = json.load(open(filepath, encoding="utf-8"))
        stubs = find_recent_stubs(data, depuis)
        if not stubs:
            continue
        modifie = False
        for stub in stubs:
            if n_appels >= args.budget_appels:
                break
            text_id = stub.get('id') or stub.get('cid')
            print(f"  IDCC {idcc} -> {(stub.get('title') or '')[:70]}...", end=" ")
            result = call_api(base_url, token, "/consult/kaliText", {"id": text_id})
            n_appels += 1
            if "_error" in result:
                print(f"ERREUR {result['_error']}")
                n_err += 1
                time.sleep(args.delay)
                continue
            stub["articles"] = result.get("articles", [])
            stub["sections"] = result.get("sections", [])
            stub["_texte_complet_recupere"] = True
            stub["_type_complement"] = "recent"
            print(f"OK ({len(stub['articles'])} article(s))")
            n_ok += 1
            modifie = True
            time.sleep(args.delay)
        if modifie:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            n_ccn += 1

    print(f"\nTerminé : {n_ok} texte(s) récent(s) complété(s) dans {n_ccn} CCN, {n_err} erreur(s), "
          f"{n_appels} appel(s).")


if __name__ == "__main__":
    main()
