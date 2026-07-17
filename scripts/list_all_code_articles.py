#!/usr/bin/env python3
"""
Récupère la table des matières COMPLÈTE d'un code (ex: Code du travail) en
un seul appel API, et en extrait la liste de TOUS les numéros d'article
existants -- pour préparer une récupération exhaustive plus tard (par
opposition à notre liste actuelle de 492 articles, qui ne couvre que ce
qui est déjà cité dans le guide/l'appli).

Ne récupère PAS le contenu des articles ici -- juste la LISTE des numéros.
Une fois cette liste obtenue, on la donne à pull_code_travail.py comme
n'importe quel fichier --articles-file, exactement comme pour les 492
actuels.

Usage:
    python3 list_all_code_articles.py --code-id LEGITEXT000006072050 --out all_articles_code_travail.txt
    python3 list_all_code_articles.py --code-id LEGITEXT000006073189 --out all_articles_code_secu.txt

Attention à l'échelle : le Code du travail à lui seul contient de l'ordre
de 10 000 à 12 000 articles (parties L/R/D confondues). Récupérer TOUT
leur contenu ensuite (pas juste cette liste) prendrait plusieurs heures
même à 1,2s/appel -- prévoir une exécution dédiée, pas la veille du lundi
habituelle.
"""
import os
import sys
import json
import argparse
import datetime
import urllib.request
import urllib.error
import urllib.parse


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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as e:
        print(f"ERREUR obtention du jeton ({e.code}): {e.read().decode(errors='replace')[:500]}", file=sys.stderr)
        sys.exit(1)


def call_api(base_url, token, path, body):
    req = urllib.request.Request(
        base_url + path, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                  "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")}
    except Exception as e:
        return {"_error": "exception", "_detail": f"{type(e).__name__}: {e}"}


def extract_article_numbers(node, numbers=None):
    """Parcourt récursivement sections/articles et collecte tous les
    numéros d'article trouvés. Le nom exact du champ n'est pas garanti
    (num/numero/id) -- on essaie plusieurs pistes raisonnables."""
    if numbers is None:
        numbers = set()
    if not isinstance(node, dict):
        return numbers

    for art in node.get("articles", []) or []:
        num = art.get("num") or art.get("numero")
        if num:
            numbers.add(num)

    for section in node.get("sections", []) or []:
        extract_article_numbers(section, numbers)

    return numbers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-id", required=True, help="Identifiant LEGITEXT du code")
    ap.add_argument("--out", required=True, help="Fichier de sortie (un article par ligne)")
    ap.add_argument("--date", default=None, help="Date de vigueur (défaut: aujourd'hui)")
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.", file=sys.stderr)
        sys.exit(1)

    date = args.date or datetime.date.today().isoformat()
    token_url, base_url = get_urls()
    token = get_token(token_url, client_id, client_secret)

    print(f"Récupération de la table des matières de {args.code_id} (date {date})...")
    result = call_api(base_url, token, "/consult/legi/tableMatieres", {
        "textId": args.code_id, "date": date, "nature": "CODE",
    })

    if "_error" in result:
        print(f"ERREUR: {result['_error']} -- {result.get('_detail','')[:500]}", file=sys.stderr)
        sys.exit(1)

    numbers = extract_article_numbers(result)
    print(f"Articles trouvés: {len(numbers)}")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(numbers)))

    print(f"Liste écrite dans {args.out}")
    print("\nPour récupérer le contenu de tous ces articles ensuite (attention à l'échelle) :")
    print(f"  python3 pull_code_travail.py --articles-file {args.out} --code-id {args.code_id} --out output/code-travail-complet")


if __name__ == "__main__":
    main()
