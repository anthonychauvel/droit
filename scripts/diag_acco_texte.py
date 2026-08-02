#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_acco_texte.py — Teste TOUTES les pistes pour récupérer PLUS de texte des
accords ACCO, afin de décider : remplir 20 000 avec du texte long, ou 54 000
avec du texte court ?

Pistes testées sur UN accord :
  1. La recherche standard (ce qu'on a déjà) -> longueur de 'text' et 'extracts'
  2. Augmenter le nombre/taille des extraits demandés
  3. Différents endpoints de consultation (au cas où l'un donne le texte complet)
  4. Le champ 'text' brut sans troncature

Usage (via workflow, cible 'diag-acco-texte') :
    python3 scripts/diag_acco_texte.py
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
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")[:300]}


def longueur_texte(resultat):
    """Mesure le texte total d'un résultat de recherche."""
    results = resultat.get("results") or []
    if not results:
        return None, 0, 0, None
    r = results[0]
    text = r.get("text") or ""
    extraits = r.get("extracts") or []
    total_ex = sum(len(str(e.get("values", e))) for e in extraits if isinstance(e, dict))
    tid = None
    for t in (r.get("titles") or []):
        if t.get("id"):
            tid = t["id"]; break
    return r, len(text), total_ex, tid


def main():
    cid = os.environ.get("PISTE_CLIENT_ID")
    secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not cid or not secret:
        print("Identifiants manquants", file=sys.stderr)
        return 1
    token_url, base = get_urls()
    print(f"=== Test longueur texte ACCO {'PROD' if 'sandbox' not in base else 'SANDBOX'} ===\n")
    token = get_token(token_url, cid, secret)

    def recherche(page_size, taille_extrait=None):
        body = {
            "fond": "ACCO",
            "recherche": {
                "champs": [{"typeChamp": "ALL", "operateur": "ET",
                    "criteres": [{"valeur": "participation", "typeRecherche": "UN_DES_MOTS", "operateur": "ET"}]}],
                "sort": "PERTINENCE", "fromAdvancedRecherche": False,
                "pageNumber": 1, "pageSize": page_size,
                "typePagination": "DEFAUT", "operateur": "ET",
            },
        }
        if taille_extrait:
            body["recherche"]["tailleExtrait"] = taille_extrait
        return call(base, token, "/search", body)

    # PISTE 1 : recherche standard
    print("=" * 60)
    print("1) Recherche standard : longueur du texte renvoyé")
    print("=" * 60)
    r1 = recherche(10)
    if "_error" in r1:
        print(f"ÉCHEC : {r1['_error']}")
        return 1
    premier, len_text, len_ex, tid = longueur_texte(r1)
    print(f"Champ 'text' : {len_text} caractères")
    print(f"Extraits (total) : {len_ex} caractères")
    print(f"ID du 1er accord : {tid}")
    if premier:
        print(f"Clés du résultat : {list(premier.keys())}")
        # Y a-t-il un champ moreArticlesCount ?
        print(f"moreArticlesCount : {premier.get('moreArticlesCount', 'absent')}")

    # PISTE 2 : demander des extraits plus longs (paramètre tailleExtrait)
    print("\n" + "=" * 60)
    print("2) Avec tailleExtrait augmentée (2000)")
    print("=" * 60)
    r2 = recherche(10, taille_extrait=2000)
    if "_error" in r2:
        print(f"ÉCHEC (le paramètre n'existe peut-être pas) : {r2['_error']}")
    else:
        _, len_text2, len_ex2, _ = longueur_texte(r2)
        print(f"Champ 'text' : {len_text2} caractères (avant : {len_text})")
        print(f"Extraits : {len_ex2} caractères (avant : {len_ex})")
        if len_ex2 > len_ex or len_text2 > len_text:
            print(">>> Le paramètre tailleExtrait AUGMENTE le texte ! Piste à exploiter.")
        else:
            print(">>> Pas de changement, le paramètre est ignoré.")

    # PISTE 3 : endpoints de consultation alternatifs
    if tid:
        cid_court = str(tid).split("_")[0]
        print("\n" + "=" * 60)
        print(f"3) Endpoints de consultation pour le texte COMPLET de {cid_court}")
        print("=" * 60)
        for endpoint, corps in [
            ("/consult/acco", {"textCid": cid_court}),
            ("/consult/acco", {"id": cid_court}),
            ("/consult/accord", {"textCid": cid_court}),
            ("/consult/getArticle", {"id": cid_court}),
            ("/consult/legiPart", {"textId": cid_court, "date": "2024-01-01"}),
        ]:
            c = call(base, token, endpoint, corps)
            if "_error" in c:
                print(f"  {endpoint} {list(corps.keys())} -> ÉCHEC {c['_error']}")
            else:
                # Mesurer le texte obtenu
                s = json.dumps(c, ensure_ascii=False)
                print(f"  {endpoint} {list(corps.keys())} -> OK, {len(s)} car de JSON")
                print(f"     clés : {list(c.keys())}")
                print(f"     >>> CET ENDPOINT MARCHE ! Texte complet possible.")
                break

    print("\n" + "=" * 60)
    print("CONCLUSION")
    print("=" * 60)
    print("Si piste 2 ou 3 donne plus de texte -> on peut enrichir les 20 000.")
    print("Sinon -> extraits courts, autant viser les 54 000 (peu de place).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
