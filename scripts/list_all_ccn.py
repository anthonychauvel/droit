#!/usr/bin/env python3
"""
Liste TOUS les IDCC (conventions collectives) disponibles sur Légifrance,
équivalent de list_all_code_articles.py mais pour le fonds KALI.

DIFFÉRENCE IMPORTANTE avec list_all_code_articles.py : le Code du travail a
un endpoint dédié et stable pour lister sa table des matières
(/consult/legi/tableMatieres). Le fonds KALI n'a pas d'équivalent aussi
direct pour "donne-moi tous les containers" -- ce script réutilise le seul
mécanisme prouvé dans ce repo (/search, fond=KALI, déjà utilisé par
pull_ccn.py pour chercher un IDCC précis), mais avec une requête volontairement
large et une pagination complète pour tout faire remonter.

CE SCRIPT EST PLUS EXPLORATOIRE que les autres du repo : contrairement à
kaliContIdcc (endpoint direct, comportement stable, confirmé sur des
centaines d'appels ce mois-ci), la forme exacte des résultats de /search en
recherche large n'a jamais été testée ici. Le script sauvegarde donc la
1re page brute dans un fichier debug pour permettre d'ajuster l'extraction
si le format observé diffère de ce qui est codé ici.

Usage:
    python3 list_all_ccn.py --out idcc_list_complet.txt
    python3 list_all_ccn.py --out idcc_list_complet.txt --debug-dir debug_list_ccn
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


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


def search_page(base_url, token, page_number, page_size=100):
    """Recherche large sur le fonds KALI, un lot de résultats à la fois.
    Requête volontairement générique (tous les mots, sur tous les champs)
    pour faire remonter le plus large éventail de containers possible --
    même logique que /search déjà utilisé dans pull_ccn.py, juste sans
    filtrer sur un IDCC précis."""
    body = {
        "fond": "KALI",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "ET",
                "criteres": [{
                    "valeur": "convention collective",
                    "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP",
                    "operateur": "ET",
                }],
            }],
            "sort": "PERTINENCE",
            "fromAdvancedRecherche": False,
            "pageNumber": page_number,
            "pageSize": page_size,
            "typePagination": "DEFAUT",
            "operateur": "ET",
        },
    }
    return call_api(base_url, token, "/search", body)


IDCC_PATTERNS = [
    re.compile(r'\bIDCC\s*[:n°]*\s*(\d{1,4})\b', re.I),
    re.compile(r'brochure\s*(?:n[°o]?)?\s*(\d{4})', re.I),
]


def extract_idcc_candidates(result_item):
    """Le format exact n'étant pas garanti (cf. note en tête de fichier),
    on cherche l'IDCC à plusieurs endroits plausibles plutôt qu'un seul
    chemin fixe : champ dédié si présent, sinon dans le titre."""
    for key in ("idcc", "IDCC", "numeroIdcc"):
        if result_item.get(key):
            return [str(result_item[key])]
    titles = result_item.get("titles") or result_item.get("titres") or []
    text_blobs = [t.get("title") or t.get("titre") or "" for t in titles]
    text_blobs.append(result_item.get("title") or result_item.get("titre") or "")
    found = []
    for blob in text_blobs:
        for pat in IDCC_PATTERNS:
            found.extend(pat.findall(blob))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="idcc_list_complet.txt",
                     help="Fichier de sortie : un IDCC par ligne (dossier créé si besoin)")
    ap.add_argument("--debug-dir", default="debug_list_ccn",
                     help="Dossier où sauvegarder la 1re page brute pour inspection/ajustement")
    ap.add_argument("--max-pages", type=int, default=200,
                     help="Garde-fou : arrête après ce nombre de pages même si l'API en propose plus")
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.", file=sys.stderr)
        sys.exit(1)

    # dossiers de destination créés explicitement -- c'est ce qui manquait
    # dans une version précédente de ce type de script
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    os.makedirs(args.debug_dir, exist_ok=True)

    token_url, base_url = get_urls()
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK (env={os.environ.get('PISTE_ENV','sandbox')}). Début de l'énumération KALI.")

    all_idcc = set()
    page = 1
    total_results_annonce = None

    while page <= args.max_pages:
        result = search_page(base_url, token, page)

        if page == 1:
            debug_path = os.path.join(args.debug_dir, "page1_brute.json")
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Page 1 brute sauvegardée dans {debug_path} -- à inspecter si les résultats "
                  f"paraissent vides ou faux, pour ajuster extract_idcc_candidates().")

        if "_error" in result:
            print(f"ERREUR page {page}: {result['_error']} -- {str(result.get('_detail',''))[:200]}")
            break

        results = result.get("results") or result.get("resultats") or []
        if total_results_annonce is None:
            total_results_annonce = (result.get("totalResultNumber")
                                      or result.get("totalResultat") or "?")
            print(f"Total annoncé par l'API : {total_results_annonce} résultats")

        if not results:
            print(f"Page {page} : aucun résultat, fin de la pagination.")
            break

        new_this_page = 0
        for item in results:
            for idcc in extract_idcc_candidates(item):
                if idcc not in all_idcc:
                    all_idcc.add(idcc)
                    new_this_page += 1

        print(f"Page {page} : {len(results)} résultat(s), {new_this_page} nouvel(aux) IDCC "
              f"(total cumulé : {len(all_idcc)})")

        if new_this_page == 0 and page > 1:
            print("Plus aucun IDCC nouveau depuis 1 page -- arrêt (fin probable des résultats utiles).")
            break

        page += 1
        time.sleep(args.delay)

    sorted_idcc = sorted(all_idcc, key=lambda x: int(x) if x.isdigit() else 0)
    with open(args.out, "w", encoding="utf-8") as f:
        for i in sorted_idcc:
            f.write(f"{i}\n")

    print(f"\nTerminé : {len(sorted_idcc)} IDCC uniques écrits dans {args.out}")
    if len(sorted_idcc) < 300:
        print("ATTENTION : ce chiffre semble bas comparé aux ~485 CCN actives connues par ailleurs "
              "(fichier DARES officiel). Vérifier debug_list_ccn/page1_brute.json avant de faire "
              "confiance à ce résultat -- le format de /search en recherche large n'a jamais été "
              "testé en conditions réelles avant ce run.")


if __name__ == "__main__":
    main()
