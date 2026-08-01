#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_jorf.py — DIAGNOSTIC à lancer UNE fois pour voir la vraie structure des
réponses de l'API JORF, au lieu de deviner. Affiche tout dans les logs GitHub.

Ne récupère rien, ne commit rien : appelle juste lastNJo + jorfCont sur UN JO
et imprime la structure réelle. On saura enfin :
  - si jorfCont renvoie les titres des textes (ou juste les IDs) ;
  - pourquoi le filtre RH ne matche presque rien ;
  - à quoi ressemble un vrai JORFTEXT id dans la réponse.

Usage (via le workflow, cible 'diag-jorf') :
    python3 scripts/diag_jorf.py
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
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")[:500]}


def apercu(obj, prof=0, max_prof=3):
    """Affiche la structure d'un objet JSON sans tout dévider."""
    pad = "  " * prof
    if prof > max_prof:
        return pad + "..."
    if isinstance(obj, dict):
        lignes = []
        for k, v in list(obj.items())[:15]:
            if isinstance(v, (dict, list)):
                lignes.append(f"{pad}{k}:")
                lignes.append(apercu(v, prof+1, max_prof))
            else:
                s = str(v)[:80]
                lignes.append(f"{pad}{k} = {s}")
        return "\n".join(lignes)
    if isinstance(obj, list):
        if not obj:
            return pad + "[] (vide)"
        return f"{pad}[liste de {len(obj)}], 1er élément :\n" + apercu(obj[0], prof+1, max_prof)
    return pad + str(obj)[:80]


def main():
    cid = os.environ.get("PISTE_CLIENT_ID")
    secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not cid or not secret:
        print("Identifiants manquants", file=sys.stderr)
        return 1
    token_url, base = get_urls()
    print(f"=== Environnement : {'PROD' if 'sandbox' not in base else 'SANDBOX'} ===")
    token = get_token(token_url, cid, secret)
    print("Token OK\n")

    # 1) lastNJo : structure ?
    print("=" * 60)
    print("ÉTAPE 1 — /consult/lastNJo (5 derniers JO seulement pour le diag)")
    print("=" * 60)
    r1 = call(base, token, "/consult/lastNJo", {"nbElement": 5})
    if "_error" in r1:
        print(f"ÉCHEC : {r1['_error']} — {r1.get('_detail')}")
        return 1
    print("Clés de premier niveau :", list(r1.keys()))
    print("\nStructure (aperçu) :")
    print(apercu(r1, max_prof=2))

    # Extraire le 1er conteneur, quel que soit son nom de champ
    items = r1.get("containers") or r1.get("jo") or r1.get("results") or []
    if not items:
        # Chercher n'importe quelle liste dans la réponse
        for k, v in r1.items():
            if isinstance(v, list) and v:
                items = v
                print(f"\n(liste trouvée sous la clé '{k}')")
                break
    if not items:
        print("\nAUCUNE liste de JO trouvée — c'est LE problème.")
        return 1

    premier = items[0]
    print("\n--- 1er conteneur JO en détail ---")
    print(apercu(premier, max_prof=2))

    cont_id = premier.get("id") or premier.get("cid") or premier.get("jorfContId")
    print(f"\nID conteneur extrait : {cont_id}")
    if not cont_id:
        print("PAS D'ID — le champ id a un autre nom, voir ci-dessus.")
        return 1

    # 2) jorfCont sur ce JO : les titres sont-ils là ?
    print("\n" + "=" * 60)
    print(f"ÉTAPE 2 — /consult/jorfCont sur {cont_id}")
    print("=" * 60)
    r2 = call(base, token, "/consult/jorfCont", {"textCid": cont_id})
    if "_error" in r2:
        print(f"ÉCHEC : {r2['_error']} — {r2.get('_detail')}")
        return 1
    print("Clés de premier niveau :", list(r2.keys()))

    # Vérif cruciale : l'ID du joCont renvoyé == l'ID demandé ?
    items = r2.get("items") or []
    if items and isinstance(items[0], dict):
        jocont = items[0].get("joCont", {})
        renvoye = jocont.get("id", "")
        print(f"\n>>> ID demandé  : {cont_id}")
        print(f">>> ID renvoyé  : {renvoye}")
        print(f">>> CORRESPONDENT : {'OUI' if renvoye == cont_id else 'NON -- CEST LE BUG'}")
        # Où sont les textes ? Explorer les clés de joCont
        print(f"\nClés de joCont : {list(jocont.keys())}")
        struct = jocont.get("structure")
        print(f"Type de 'structure' : {type(struct).__name__}, "
              f"{len(struct) if isinstance(struct,(list,dict)) else '?'} éléments")
        # DÉVOILER le contenu de structure -- c'est là que doivent être les textes
        if isinstance(struct, dict):
            print(f"\n>>> Clés de 'structure' : {list(struct.keys())}")
            for k, v in struct.items():
                if isinstance(v, list):
                    print(f"    structure['{k}'] = liste de {len(v)}")
                    if v and isinstance(v[0], dict):
                        print(f"        1er élément, clés : {list(v[0].keys())}")
                        # Montrer id + titre du 1er
                        print(f"        id={v[0].get('id')}  titre={str(v[0].get('title') or v[0].get('titre'))[:50]}")
                elif isinstance(v, dict):
                    print(f"    structure['{k}'] = dict, clés : {list(v.keys())}")
                else:
                    print(f"    structure['{k}'] = {str(v)[:60]}")

    # Compter les JORFTEXT par la méthode structure vs walk global
    def compter(node, restreint):
        found = []
        def walk(n, ok=True):
            if isinstance(n, dict):
                tid = n.get("id") or n.get("cid")
                if tid and str(tid).startswith("JORFTEXT") and ok:
                    found.append(str(tid))
                for k, v in n.items():
                    if restreint:
                        walk(v, ok=(k in ("structure","sections","articles","children","items","tms","joCont")))
                    else:
                        walk(v, ok=True)
            elif isinstance(n, list):
                for v in n: walk(v, ok)
        walk(node)
        return found

    tous = compter(r2, restreint=False)
    struct_only = compter(r2, restreint=True)
    print(f"\nJORFTEXT trouvés (walk global)     : {len(set(tous))}")
    print(f"JORFTEXT trouvés (structure seule) : {len(set(struct_only))}")

    # 2 bis) REFAIRE sur un 2e JO différent pour voir si les IDs changent
    if len(items_liste := (r1.get("containers") or [])) > 1:
        cont_id2 = items_liste[1].get("id")
        print(f"\n--- 2e JO pour comparer : {cont_id2} ---")
        r2b = call(base, token, "/consult/jorfCont", {"textCid": cont_id2})
        tous2 = compter(r2b, restreint=False)
        # Les JORFTEXT du JO1 et du JO2 doivent être DIFFÉRENTS
        communs = set(tous) & set(tous2)
        print(f"JORFTEXT du JO1 : {len(set(tous))}, du JO2 : {len(set(tous2))}")
        print(f"En commun : {len(communs)} "
              f"{'(NORMAL si 0-2)' if len(communs)<3 else '<<< PROBLÈME : mêmes textes partout'}")

    print("\n=== FIN DIAGNOSTIC ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
