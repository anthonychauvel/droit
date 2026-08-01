#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_judilibre.py — DIAGNOSTIC à lancer une fois pour comprendre pourquoi les
cours d'appel ne remontent pas (on n'a que de la Cour de cassation).

Teste en direct l'API Judilibre avec jurisdiction=ca et affiche ce qu'elle
renvoie réellement, dans les logs GitHub. Ne récupère rien, ne commit rien.

Répond à : est-ce que l'API a des décisions de cours d'appel pour nos thèmes
sociaux ? Et sous quelle valeur de paramètre ?

Usage (via workflow, cible 'diag-judilibre') :
    python3 scripts/diag_judilibre.py
"""
import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse


def get_urls():
    env = os.environ.get("PISTE_ENV", "sandbox").lower()
    if env == "production":
        return ("https://oauth.piste.gouv.fr/api/oauth/token",
                "https://api.piste.gouv.fr/cassation/judilibre/v1.0")
    return ("https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
            "https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0")


def get_token(token_url, cid, secret):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid,
        "client_secret": secret, "scope": "openid"}).encode()
    req = urllib.request.Request(token_url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def get(base, token, path, params):
    url = base + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")[:400]}


def main():
    cid = os.environ.get("PISTE_CLIENT_ID")
    secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not cid or not secret:
        print("Identifiants manquants", file=sys.stderr)
        return 1
    token_url, base = get_urls()
    print(f"=== Judilibre {'PROD' if 'sandbox' not in base else 'SANDBOX'} ===")
    token = get_token(token_url, cid, secret)
    print("Token OK\n")

    # 1) La taxonomie : quelles valeurs de jurisdiction existent ?
    print("=" * 60)
    print("1) /taxonomy?id=jurisdiction — les juridictions disponibles")
    print("=" * 60)
    tax = get(base, token, "/taxonomy", {"id": "jurisdiction"})
    if "_error" in tax:
        print(f"ÉCHEC : {tax['_error']} — {tax.get('_detail')}")
    else:
        print(json.dumps(tax, ensure_ascii=False)[:600])

    # 2) Recherche SANS filtre de juridiction sur un thème social
    print("\n" + "=" * 60)
    print("2) /search 'licenciement' SANS filtre — répartition des juridictions")
    print("=" * 60)
    r = get(base, token, "/search", {
        "query": "licenciement sans cause réelle et sérieuse",
        "field": ["text"], "operator": "and", "page": 0, "page_size": 20,
        "sort": "date", "order": "desc"})
    if "_error" in r:
        print(f"ÉCHEC : {r['_error']} — {r.get('_detail')}")
    else:
        total = r.get("total", 0)
        results = r.get("results", [])
        print(f"total = {total}, {len(results)} résultats en page 0")
        from collections import Counter
        jurs = Counter(res.get("jurisdiction", "?") for res in results)
        print(f"juridictions dans ces 20 résultats : {dict(jurs)}")

    # 3) Recherche AVEC jurisdiction=ca (cours d'appel)
    print("\n" + "=" * 60)
    print("3) /search 'licenciement' AVEC jurisdiction=ca (cours d'appel)")
    print("=" * 60)
    rca = get(base, token, "/search", {
        "query": "licenciement sans cause réelle et sérieuse",
        "field": ["text"], "operator": "and", "page": 0, "page_size": 20,
        "sort": "date", "order": "desc", "jurisdiction": "ca"})
    if "_error" in rca:
        print(f"ÉCHEC : {rca['_error']} — {rca.get('_detail')}")
        print(">>> Si erreur ici mais pas en (2), le filtre jurisdiction=ca pose problème.")
    else:
        total = rca.get("total", 0)
        results = rca.get("results", [])
        print(f"total avec jurisdiction=ca = {total}")
        from collections import Counter
        jurs = Counter(res.get("jurisdiction", "?") for res in results)
        print(f"juridictions obtenues : {dict(jurs)}")
        if total == 0:
            print(">>> ZÉRO résultat : l'API n'a pas (ou peu) de cours d'appel pour ce thème,")
            print("    OU la valeur 'ca' n'est pas la bonne (voir taxonomie en 1).")
        else:
            print(">>> Des cours d'appel existent ! Le souci est ailleurs (peut-être le")
            print("    run 'découvrir' avec jurisdiction vide qui ne les demande pas).")
            for res in results[:5]:
                print(f"    {res.get('jurisdiction')} | {res.get('id','')[:40]}")

    print("\n=== FIN DIAGNOSTIC ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
