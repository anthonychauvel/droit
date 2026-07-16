#!/usr/bin/env python3
"""
Aspirateur Code du travail — récupère des articles précis du Code du travail
(fonds LEGI) depuis l'API PISTE/Légifrance.

Le Code du travail entier fait des dizaines de milliers d'articles — inutile
de tout aspirer. Ce script prend une LISTE D'ARTICLES PRÉCIS (ex: L3121-1,
R3121-2...) et récupère leur contenu à jour, un par un.

Usage:
    python3 pull_code_travail.py --articles-file articles_list.txt --out output/code-travail
    python3 pull_code_travail.py --articles L3121-1,L3141-3 --out output/code-travail

Le fichier articles_list.txt : un article par ligne, ex.
    L3121-1
    L3141-3
    R3243-1

Variables d'environnement requises (GitHub Secrets):
    PISTE_CLIENT_ID
    PISTE_CLIENT_SECRET
    PISTE_ENV = "sandbox" ou "production"

Note: l'identifiant chronique (textId) du Code du travail lui-même est
LEGITEXT000006072050 — stable et bien connu, inutile de le rechercher.
"""
import os
import sys
import json
import time
import argparse
import datetime
import urllib.request
import urllib.error
import urllib.parse

CODE_TRAVAIL_TEXT_ID = "LEGITEXT000006072050"


def get_urls():
    env = os.environ.get("PISTE_ENV", "sandbox").lower()
    if env == "production":
        return (
            "https://oauth.piste.gouv.fr/api/oauth/token",
            "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app",
        )
    return (
        "https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
        "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app",
    )


def get_token(token_url, client_id, client_secret):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "openid",
    }).encode()
    req = urllib.request.Request(
        token_url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def call_api(base_url, token, path, body):
    req = urllib.request.Request(
        base_url + path,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")}


def search_article_id(base_url, token, article_num):
    """
    Cherche l'identifiant LEGIARTI d'un article via /search, en filtrant
    sur le Code du travail. Nécessaire car l'API veut un ID interne,
    pas juste "L3121-1".
    """
    body = {
        "recherche": {
            "champs": [{
                "typeChamp": "NUM_ARTICLE",
                "criteres": [{"typeRecherche": "EXACTE", "valeur": article_num, "operateur": "ET"}],
                "operateur": "ET",
            }],
            "filtres": [{"facette": "NOM_CODE", "valeurs": ["Code du travail"]}],
            "pageSize": 5,
            "pageNumber": 1,
        },
        "fond": "CODE_ETAT",
    }
    result = call_api(base_url, token, "/search", body)
    return result


def fetch_article_by_num(base_url, token, article_num, date=None):
    date = date or datetime.date.today().isoformat()
    search_result = search_article_id(base_url, token, article_num)
    if "_error" in search_result:
        return search_result

    results = search_result.get("results", [])
    if not results:
        return {"_error": "not_found", "_detail": f"Aucun résultat pour {article_num}"}

    # Le premier résultat pertinent devrait contenir l'ID de texte
    first = results[0]
    text_id = first.get("titles", [{}])[0].get("id") or first.get("id")
    if not text_id:
        return {"_error": "no_id", "_raw": first}

    article = call_api(base_url, token, "/consult/legiPart", {
        "textId": text_id if text_id.startswith("LEGITEXT") else CODE_TRAVAIL_TEXT_ID,
        "date": date,
    })
    return article


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", help="Articles séparés par des virgules, ex: L3121-1,L3141-3")
    ap.add_argument("--articles-file", help="Fichier texte, un article par ligne")
    ap.add_argument("--out", default="output/code-travail")
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.", file=sys.stderr)
        sys.exit(1)

    articles = []
    if args.articles:
        articles = [a.strip() for a in args.articles.split(",") if a.strip()]
    elif args.articles_file:
        with open(args.articles_file) as f:
            articles = [line.strip() for line in f if line.strip()]
    else:
        print("ERREUR: fournir --articles ou --articles-file", file=sys.stderr)
        sys.exit(1)

    token_url, base_url = get_urls()
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(articles)} article(s) à traiter.")

    os.makedirs(args.out, exist_ok=True)
    summary = []

    for i, art in enumerate(articles, 1):
        print(f"[{i}/{len(articles)}] Article {art}...", end=" ")
        result = fetch_article_by_num(base_url, token, art)
        safe_name = art.replace("/", "-")
        out_path = os.path.join(args.out, f"{safe_name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        ok = "_error" not in result
        print("OK" if ok else f"ERREUR: {result.get('_error')}")
        summary.append({"article": art, "status": "ok" if ok else "error"})
        time.sleep(args.delay)

    with open(os.path.join(args.out, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    n_ok = sum(1 for s in summary if s["status"] == "ok")
    print(f"\nTerminé: {n_ok}/{len(articles)} OK.")


if __name__ == "__main__":
    main()
