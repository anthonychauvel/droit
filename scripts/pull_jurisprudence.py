#!/usr/bin/env python3
"""
Aspirateur Jurisprudence — récupère des arrêts précis (Cour de cassation,
cours d'appel) à partir de leur numéro de pourvoi public, via l'API
PISTE/Légifrance (fonds JURI).

Contrairement à KALI et au Code du travail, il n'existe pas de raccourci
direct "numéro public -> contenu" pour la jurisprudence -- il faut d'abord
chercher (/search, fond JURI) pour résoudre le numéro de pourvoi vers un
identifiant interne JURITEXT, puis consulter ce texte (/consult/juri).

Usage:
    python3 pull_jurisprudence.py --arrets-file arrets_list.txt --out output/jurisprudence

Le fichier arrets_list.txt : un numéro de pourvoi par ligne, ex.
    21-25.029
    18-10.919

Variables d'environnement requises (GitHub Secrets):
    PISTE_CLIENT_ID
    PISTE_CLIENT_SECRET
    PISTE_ENV = "sandbox" ou "production"

ATTENTION (rappel) : la jurisprudence demande plus de prudence qu'un texte
de loi brut -- le contenu récupéré est le texte intégral de la décision,
PAS un résumé du principe juridique. Toute utilisation dans le guide/l'appli
doit repasser par une lecture humaine pour en extraire l'attendu de principe
correctement, pas un simple copier-coller automatisé.
"""
import os
import sys
import json
import time
import argparse
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


def search_juri_by_numero(base_url, token, numero_pourvoi):
    """Cherche une décision par son numéro de pourvoi public (ex: 21-25.029)."""
    body = {
        "fond": "JURI",
        "recherche": {
            "champs": [{
                "typeChamp": "NUM_AFFAIRE",
                "operateur": "ET",
                "criteres": [{"valeur": numero_pourvoi, "typeRecherche": "EXACTE", "operateur": "ET"}],
            }],
            "sort": "PERTINENCE",
            "fromAdvancedRecherche": False,
            "pageNumber": 1,
            "pageSize": 5,
            "typePagination": "DEFAUT",
            "operateur": "ET",
        },
    }
    return call_api(base_url, token, "/search", body)


def extract_juritext_id(search_result):
    """Essaie plusieurs chemins raisonnables pour extraire l'id JURITEXT
    des résultats de recherche -- le format exact n'est pas garanti,
    donc on reste défensif et on renvoie aussi le brut pour debug."""
    results = search_result.get("results") or []
    for r in results:
        if r.get("id", "").startswith("JURITEXT"):
            return r["id"]
        titles = r.get("titles") or []
        for t in titles:
            if t.get("id", "").startswith("JURITEXT"):
                return t["id"]
    return None


def fetch_one_arret(base_url, token, numero, debug_dir=None):
    search_result = search_juri_by_numero(base_url, token, numero)
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        safe = numero.replace("/", "-")
        with open(os.path.join(debug_dir, f"{safe}_search_raw.json"), "w", encoding="utf-8") as f:
            json.dump(search_result, f, ensure_ascii=False, indent=2)

    if "_error" in search_result:
        return {"_error": search_result["_error"], "_detail": search_result.get("_detail",""), "_step": "search"}

    juritext_id = extract_juritext_id(search_result)
    if not juritext_id:
        return {"_error": "not_found_in_search", "_detail": json.dumps(search_result)[:500], "_step": "extract_id"}

    result = call_api(base_url, token, "/consult/juri", {"textId": juritext_id})
    if "_error" in result:
        result["_step"] = "consult"
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arrets", help="Numéros de pourvoi séparés par des virgules")
    ap.add_argument("--arrets-file", help="Fichier texte, un numéro par ligne")
    ap.add_argument("--out", default="output/jurisprudence")
    ap.add_argument("--delay", type=float, default=1.2)
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.", file=sys.stderr)
        sys.exit(1)

    numeros = []
    if args.arrets:
        numeros = [a.strip() for a in args.arrets.split(",") if a.strip()]
    elif args.arrets_file:
        with open(args.arrets_file) as f:
            numeros = [line.strip() for line in f if line.strip()]
    else:
        print("ERREUR: fournir --arrets ou --arrets-file", file=sys.stderr)
        sys.exit(1)

    token_url, base_url = get_urls()
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(numeros)} arrêt(s) à traiter.")

    os.makedirs(args.out, exist_ok=True)
    debug_dir = os.path.join(args.out, "_debug_search")
    summary = []

    for i, numero in enumerate(numeros, 1):
        print(f"[{i}/{len(numeros)}] Pourvoi n°{numero}...", end=" ")
        result = fetch_one_arret(base_url, token, numero, debug_dir=debug_dir)
        safe_name = numero.replace("/", "-")

        if "_error" in result:
            print(f"ERREUR {result['_error']} (étape: {result.get('_step','?')})")
            summary.append({"numero": numero, "status": "error",
                             "http_status": result.get("_error"), "step": result.get("_step")})
            time.sleep(args.delay)
            continue

        out_path = os.path.join(args.out, f"{safe_name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print("OK")
        summary.append({"numero": numero, "status": "ok", "titre": result.get("title") or result.get("titre")})
        time.sleep(args.delay)

    with open(os.path.join(args.out, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    n_ok = sum(1 for s in summary if s["status"] == "ok")
    print(f"\nTerminé: {n_ok}/{len(numeros)} OK.")


if __name__ == "__main__":
    main()
