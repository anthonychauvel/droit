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


def extract_etat(result):
    """État de l'article (VIGUEUR / ABROGE / ...) quel que soit l'emplacement."""
    if not isinstance(result, dict):
        return None
    art = result.get("article")
    if isinstance(art, dict) and art.get("etat"):
        return art.get("etat")
    return result.get("etat")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", help="Articles séparés par des virgules, ex: L3121-1,L3141-3")
    ap.add_argument("--articles-file", help="Fichier texte, un article par ligne")
    ap.add_argument("--out", default="output/code-travail")
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--code-id", default=CODE_TRAVAIL_TEXT_ID,
                     help="Identifiant LEGITEXT du code (défaut: Code du travail)")
    ap.add_argument("--only-missing", action="store_true",
                     help="Ne (re)traiter que les articles pas encore présents sur le disque")
    ap.add_argument("--max", type=int, default=0,
                     help="Plafond d'articles traités ce run (0 = pas de plafond). "
                          "Utile pour la passe prioritaire des nouveautés : on remplit "
                          "au plus N manquants par run, le reste au run suivant.")
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

    def safe_path(a):
        return os.path.join(args.out, f"{a.replace('/', '-')}.json")

    # On repart du résumé existant pour NE PAS écraser ce que les runs
    # précédents ont déjà acquis (un run tournant ne traite qu'une tranche).
    summary_path = os.path.join(args.out, "_summary.json")
    existing = {}
    if os.path.exists(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as f:
                for e in json.load(f):
                    if e.get("article"):
                        existing[e["article"]] = e
        except Exception:
            existing = {}

    # --only-missing : on saute les articles dont le fichier existe déjà (bon fichier).
    to_process = articles
    if args.only_missing:
        to_process = [a for a in articles
                      if not (os.path.exists(safe_path(a))
                              and "_error" not in (_load(safe_path(a)) or {"_error": 1}))]
        print(f"Mode --only-missing : {len(articles) - len(to_process)} déjà présents, "
              f"{len(to_process)} à récupérer.")

    if args.max and args.max > 0 and len(to_process) > args.max:
        print(f"Plafond --max {args.max} : {len(to_process)} candidats, on en traite "
              f"{args.max} ce run (le reste au run suivant).")
        to_process = to_process[:args.max]

    for i, art in enumerate(to_process, 1):
        print(f"[{i}/{len(to_process)}] Article {art}...", end=" ")
        result = fetch_article_by_num(base_url, token, art, code_id=args.code_id)
        out_path = safe_path(art)
        ok = "_error" not in result

        if ok:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            existing[art] = {"article": art, "status": "ok", "etat": extract_etat(result)}
            print("OK")
        else:
            # Échec réseau/API : on NE TOUCHE PAS au fichier déjà présent (il
            # reste bon). On ne dégrade le résumé que si on n'avait rien avant.
            if os.path.exists(out_path):
                print(f"ERREUR ({result.get('_error')}) — fichier existant conservé")
            else:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                existing.setdefault(art, {"article": art, "status": "error", "etat": None})
                print(f"ERREUR: {result.get('_error')}")
        time.sleep(args.delay)

    summary = list(existing.values())
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    n_ok = sum(1 for s in summary if s.get("status") == "ok")
    print(f"\nTerminé: {n_ok}/{len(summary)} articles OK au total (corpus cumulé).")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


if __name__ == "__main__":
    main()
