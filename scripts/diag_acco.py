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
    print("1) /search fond=ACCO, thème 'télétravail', sur un mois récent")
    print("=" * 60)
    r = recherche_acco(base, token, "2025-01-01", "2025-01-31")
    if "_error" in r:
        print(f">>> ÉCHEC : {r['_error']}")
        print(f">>> Détail : {r.get('_detail')}")
        if r["_error"] == 500:
            print(">>> Toujours le 500. La structure de requête ne convient pas au")
            print("    fonds ACCO -- le détail ci-dessus devrait dire pourquoi.")
        return 1
    print("La recherche PASSE (plus de 500).")
    print("Clés de premier niveau :", list(r.keys()))
    total = r.get("totalResultNumber") or r.get("total") or "?"
    print(f"Nombre total de résultats annoncé : {total}")

    # 2) Structure d'un résultat : où sont l'id et le titre ?
    print("\n" + "=" * 60)
    print("2) Structure d'un résultat de recherche")
    print("=" * 60)
    results = r.get("results") or r.get("resultats") or []
    if not results:
        print("Aucun résultat sur ce mois. Essai sur une fenêtre plus large...")
        r2 = recherche_acco(base, token, "2024-01-01", "2024-12-31")
        results = r2.get("results") or r2.get("resultats") or []
    if not results:
        print(">>> Toujours aucun résultat -- le fonds ACCO a peut-être peu de")
        print("    contenu accessible par ce thème, ou le filtre de date bloque.")
        return 0
    print(f"{len(results)} résultat(s). Structure du 1er :")
    print(apercu(results[0], max_prof=3))

    # Extraire l'id du 1er résultat
    premier = results[0]
    tid = None
    for t in (premier.get("titles") or premier.get("titres") or []):
        if t.get("id"):
            tid = t["id"]; break
    if not tid:
        tid = premier.get("id")
    print(f"\nID extrait du 1er résultat : {tid}")

    # 3) /consult/acco sur cet id : contenu récupérable ?
    if tid:
        print("\n" + "=" * 60)
        print(f"3) /consult/acco sur {tid}")
        print("=" * 60)
        c = call(base, token, "/consult/acco", {"textCid": str(tid).split("_")[0]})
        if "_error" in c:
            print(f">>> ÉCHEC consult : {c['_error']} — {c.get('_detail')}")
        else:
            print("Consult OK. Clés :", list(c.keys()))
            print("\nStructure (aperçu) :")
            print(apercu(c, max_prof=2))

    print("\n=== FIN DIAGNOSTIC ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
