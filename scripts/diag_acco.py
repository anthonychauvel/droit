#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_acco.py — DIAGNOSTIC à lancer une fois pour comprendre le fonds ACCO
avant de relancer un vrai run. ACCO renvoyait une erreur 500 depuis le début ;
ce script teste en direct la recherche /search sur ce fonds et affiche ce que
l'API répond réellement, dans les logs GitHub.

Ne récupère rien, ne commit rien. Répond à :
  - la recherche /search par dates fonctionne-t-elle sur le fonds ACCO
    (ou renvoie-t-elle encore un 500) ?
  - quelle est la vraie structure d'un résultat (où sont l'id et le titre) ?
  - un /consult/acco sur un id récupéré renvoie-t-il bien le contenu ?

Usage (via workflow, cible 'diag-acco') :
    python3 scripts/diag_acco.py
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


def call(base, token, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
        method="POST", headers={"Authorization": f"Bearer {token}",
        "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")[:600]}


def apercu(obj, prof=0, max_prof=3):
    pad = "  " * prof
    if prof > max_prof:
        return pad + "..."
    if isinstance(obj, dict):
        out = []
        for k, v in list(obj.items())[:15]:
            if isinstance(v, (dict, list)):
                out.append(f"{pad}{k}:")
                out.append(apercu(v, prof+1, max_prof))
            else:
                out.append(f"{pad}{k} = {str(v)[:80]}")
        return "\n".join(out)
    if isinstance(obj, list):
        if not obj:
            return pad + "[] (vide)"
        return f"{pad}[liste de {len(obj)}], 1er élément :\n" + apercu(obj[0], prof+1, max_prof)
    return pad + str(obj)[:80]


def recherche_acco(base, token, debut, fin, page=1):
    """MÊME structure que la recherche JORF qui fonctionne, fond=ACCO."""
    return call(base, token, "/search", {
        "fond": "ACCO",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL", "operateur": "ET",
                "criteres": [{"valeur": "télétravail", "typeRecherche": "UN_DES_MOTS", "operateur": "ET"}],
            }],
            "filtres": [{"facette": "DATE_PUBLICATION", "dates": {"start": debut, "end": fin}}],
            "sort": "PUBLICATION_DATE_DESC", "fromAdvancedRecherche": False,
            "pageNumber": page, "pageSize": 10, "typePagination": "DEFAUT", "operateur": "ET",
        },
    })


def main():
    cid = os.environ.get("PISTE_CLIENT_ID")
    secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not cid or not secret:
        print("Identifiants manquants", file=sys.stderr)
        return 1
    token_url, base = get_urls()
    print(f"=== Légifrance {'PROD' if 'sandbox' not in base else 'SANDBOX'} — fonds ACCO ===")
    token = get_token(token_url, cid, secret)
    print("Token OK\n")

    # 1) La recherche ACCO passe-t-elle (ou 500) ?
    print("=" * 60)
    print("1) /search fond=ACCO, thème 'télétravail', AVEC filtre de date")
    print("=" * 60)
    r = recherche_acco(base, token, "2025-01-01", "2025-01-31")
    if "_error" in r:
        print(f">>> ÉCHEC : {r['_error']} — {str(r.get('_detail'))[:200]}")
    else:
        total = r.get("totalResultNumber") or r.get("total") or "?"
        print(f"PASSE. Total annoncé : {total}")

    # 1bis) SANS filtre de date -- pour voir si c'est la date qui fait planter
    print("\n" + "=" * 60)
    print("1bis) /search fond=ACCO SANS filtre de date")
    print("=" * 60)
    r_nodate = call(base, token, "/search", {
        "fond": "ACCO",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL", "operateur": "ET",
                "criteres": [{"valeur": "télétravail", "typeRecherche": "UN_DES_MOTS", "operateur": "ET"}],
            }],
            "sort": "PERTINENCE", "fromAdvancedRecherche": False,
            "pageNumber": 1, "pageSize": 10, "typePagination": "DEFAUT", "operateur": "ET",
        },
    })
    if "_error" in r_nodate:
        print(f">>> ÉCHEC : {r_nodate['_error']} — {str(r_nodate.get('_detail'))[:200]}")
        print(">>> Si ça échoue AUSSI sans date, le problème n'est pas la date.")
    else:
        total = r_nodate.get("totalResultNumber") or r_nodate.get("total") or "?"
        print(f">>> PASSE sans date ! Total : {total}")
        print(">>> Donc c'était le FILTRE DE DATE qui faisait planter ACCO.")
        results = r_nodate.get("results") or r_nodate.get("resultats") or []
        if results:
            print("\nStructure du 1er résultat (sans date) :")
            print(apercu(results[0], max_prof=3))

    # 1ter) Avec un tri par date mais toujours sans filtre
    print("\n" + "=" * 60)
    print("1ter) /search fond=ACCO, tri par date de publication, sans filtre")
    print("=" * 60)
    r_sort = call(base, token, "/search", {
        "fond": "ACCO",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL", "operateur": "ET",
                "criteres": [{"valeur": "télétravail", "typeRecherche": "UN_DES_MOTS", "operateur": "ET"}],
            }],
            "sort": "PUBLICATION_DATE_DESC", "fromAdvancedRecherche": False,
            "pageNumber": 1, "pageSize": 10, "typePagination": "DEFAUT", "operateur": "ET",
        },
    })
    if "_error" in r_sort:
        print(f">>> ÉCHEC : {r_sort['_error']} — {str(r_sort.get('_detail'))[:150]}")
        print(">>> Si ça échoue, c'est le TRI par date qui pose problème sur ACCO.")
    else:
        total = r_sort.get("totalResultNumber") or r_sort.get("total") or "?"
        print(f">>> PASSE avec tri par date. Total : {total}")

    if "_error" in r and "_error" in r_nodate and "_error" in r_sort:
        print("\n>>> Les 3 variantes échouent : le fonds ACCO semble indisponible")
        print("    ou refuse ce type de recherche côté serveur Légifrance.")
        return 1
    # Continuer avec la variante qui a marché pour tester le consult
    r_ok = r_nodate if "_error" not in r_nodate else (r_sort if "_error" not in r_sort else r)

    # 2) Structure + consult sur un id récupéré
    results = r_ok.get("results") or r_ok.get("resultats") or []
    if not results:
        print("\n>>> Une recherche a marché mais 0 résultat -- rien à consulter.")
        return 0
    premier = results[0]
    tid = None
    for t in (premier.get("titles") or premier.get("titres") or []):
        if t.get("id"):
            tid = t["id"]; break
    if not tid:
        tid = premier.get("id")
    print(f"\nID du 1er résultat : {tid}")
    if tid:
        print("\n" + "=" * 60)
        print(f"3) /consult/acco sur {tid}")
        print("=" * 60)
        c = call(base, token, "/consult/acco", {"textCid": str(tid).split("_")[0]})
        if "_error" in c:
            print(f">>> ÉCHEC consult : {c['_error']} — {str(c.get('_detail'))[:150]}")
        else:
            print("Consult OK. Clés :", list(c.keys()))
            print(apercu(c, max_prof=2))

    print("\n=== FIN DIAGNOSTIC ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
