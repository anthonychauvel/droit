#!/usr/bin/env python3
"""
Aspirateur d'articles de code (fonds LEGI) depuis l'API PISTE/Légifrance --
généralisé pour n'importe quel code (Code du travail, Code de la sécurité
sociale, etc.), pas seulement le Code du travail.

Chaque code entier fait des dizaines de milliers d'articles — inutile de
tout aspirer. Ce script prend une LISTE D'ARTICLES PRÉCIS et récupère leur
contenu à jour, un par un, pour LE CODE INDIQUÉ.

Usage:
    python3 pull_code_articles.py --articles-file articles_list.txt \
        --code-id LEGITEXT000006072050 --out output/code-travail
    python3 pull_code_articles.py --articles L136-1,L242-1 \
        --code-id LEGITEXT000006073189 --out output/code-secu

Identifiants de codes connus (stables, inutile de les rechercher) :
    Code du travail            : LEGITEXT000006072050
    Code de la sécurité sociale: LEGITEXT000006073189

Variables d'environnement requises (GitHub Secrets):
    PISTE_CLIENT_ID
    PISTE_CLIENT_SECRET
    PISTE_ENV = "sandbox" ou "production"
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
CODE_SECU_TEXT_ID = "LEGITEXT000006073189"


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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        print(f"ERREUR obtention du jeton ({e.code}): {detail[:500]}", file=sys.stderr)
        print("Note: si une étape précédente du même run a réussi avec les mêmes "
              "identifiants, ce n'est probablement pas un souci de CGU/souscription "
              "mais peut-être une limite de débit sur la ré-émission de jetons.", file=sys.stderr)
        sys.exit(1)


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
    except Exception as e:
        # Filet de sécurité: timeout, coupure réseau, JSON mal formé, etc.
        # Ne doit JAMAIS faire planter le script sur 467 appels — on logue et on continue.
        return {"_error": "exception", "_detail": f"{type(e).__name__}: {e}"}


def fetch_article_by_num(base_url, token, article_num, code_id=CODE_TRAVAIL_TEXT_ID):
    """
    Récupération directe, sans recherche intermédiaire : l'endpoint
    getArticleWithIdAndNum accepte directement le numéro d'article
    (ex: "L3111-2") avec l'id du CODE concerné (Code du travail par
    défaut, mais fonctionne pour n'importe quel code -- CSS, etc.).
    """
    result = call_api(base_url, token, "/consult/getArticleWithIdAndNum", {
        "id": code_id,
        "num": article_num,
    })
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", help="Articles séparés par des virgules, ex: L3121-1,L3141-3")
    ap.add_argument("--articles-file", help="Fichier texte, un article par ligne")
    ap.add_argument("--out", default="output/code-travail")
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--code-id", default=CODE_TRAVAIL_TEXT_ID,
                     help="Identifiant LEGITEXT du code (défaut: Code du travail)")
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
    print(f"Token OK. Code: {args.code_id}. {len(articles)} article(s) à traiter.")

    os.makedirs(args.out, exist_ok=True)

    # IMPORTANT : fusionner avec le _summary.json existant plutôt que l'écraser.
    # Sans ça, un run qui ne traite qu'une tranche (rotation hebdomadaire, lot du
    # batch "complet") effaçait le souvenir de tout ce que les runs précédents
    # avaient déjà récupéré -- même si les fichiers .json individuels restaient
    # bien sur le disque, plus rien ne savait qu'ils existaient.
    summary_path = os.path.join(args.out, "_summary.json")
    existant = {}
    if os.path.exists(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as f:
                for e in json.load(f):
                    existant[e["article"]] = e
        except Exception:
            existant = {}

    for i, art in enumerate(articles, 1):
        print(f"[{i}/{len(articles)}] Article {art}...", end=" ")
        result = fetch_article_by_num(base_url, token, art, code_id=args.code_id)
        safe_name = art.replace("/", "-")
        out_path = os.path.join(args.out, f"{safe_name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        ok = "_error" not in result
        print("OK" if ok else f"ERREUR: {result.get('_error')}")
        existant[art] = {"article": art, "status": "ok" if ok else "error"}
        time.sleep(args.delay)

    summary = list(existant.values())
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    n_ok = sum(1 for s in summary if s["status"] == "ok")
    print(f"\nTerminé : {sum(1 for a in articles if existant.get(a,{}).get('status')=='ok')}/{len(articles)} "
          f"OK sur ce run. Total cumulé dans {summary_path} : {n_ok}/{len(summary)}.")


if __name__ == "__main__":
    main()
