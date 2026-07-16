#!/usr/bin/env python3
"""
Aspirateur CCN — récupère le contenu complet de chaque convention collective
(fonds KALI) depuis l'API PISTE/Légifrance, à partir d'une liste d'IDCC.

Usage:
    python3 pull_ccn.py --idcc-file idcc_list.txt --out output/ccn
    python3 pull_ccn.py --idcc 207,2528,1978 --out output/ccn

Variables d'environnement requises (définies en GitHub Secrets):
    PISTE_CLIENT_ID
    PISTE_CLIENT_SECRET
    PISTE_ENV = "sandbox" ou "production" (défaut: sandbox)

IMPORTANT: en sandbox, les données PISTE peuvent être différentes/périmées
par rapport à la production (confirmé par la FAQ officielle Légifrance).
Pour des données réellement à jour, il faut une appli PRODUCTION (souscription
supplémentaire, validation par la DILA).
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error


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
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    return payload["access_token"]


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
        body_txt = e.read().decode(errors="replace")
        return {"_error": e.code, "_detail": body_txt}


def search_kali_by_idcc(base_url, token, idcc):
    """
    Étape 1 (documentée officiellement) : cherche le conteneur KALI
    correspondant à un IDCC via /search, fond=KALI, typeChamp=IDCC.
    Renvoie la réponse brute de recherche.
    """
    body = {
        "fond": "KALI",
        "recherche": {
            "champs": [{
                "typeChamp": "IDCC",
                "operateur": "ET",
                "criteres": [{
                    "valeur": str(idcc),
                    "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP",
                    "operateur": "ET",
                }],
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


def extract_kali_id_from_search(search_result):
    """
    Le format exact des résultats de /search n'est pas garanti stable —
    on essaie plusieurs chemins raisonnables et on renvoie aussi le
    résultat brut pour debug si rien ne matche.
    """
    results = search_result.get("results") or search_result.get("resultats") or []
    for r in results:
        # Chemin le plus courant observé pour ce type d'API Légifrance
        titles = r.get("titles") or r.get("titres") or []
        for t in titles:
            if t.get("id"):
                return t["id"], r
        if r.get("id"):
            return r["id"], r
    return None, None


def fetch_one_idcc(base_url, token, idcc, debug_dir=None):
    """
    Récupère le conteneur KALI complet pour un IDCC donné, via le
    parcours officiel en 2 étapes : /search (résoudre l'id KALICONT)
    puis /consult/kaliContIdcc ou /consult/kaliCont avec cet id.
    """
    search_result = search_kali_by_idcc(base_url, token, idcc)

    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, f"{idcc}_search_raw.json"), "w", encoding="utf-8") as f:
            json.dump(search_result, f, ensure_ascii=False, indent=2)

    if "_error" in search_result:
        return {"_error": search_result["_error"], "_detail": search_result.get("_detail", ""), "_step": "search"}

    kali_id, raw_match = extract_kali_id_from_search(search_result)
    if not kali_id:
        return {
            "_error": "not_found_in_search",
            "_detail": json.dumps(search_result)[:500],
            "_step": "extract_id",
        }

    # kaliContIdcc accepte soit l'IDCC brut, soit l'id KALICONT résolu.
    # On utilise l'id résolu (documentation officielle), plus fiable.
    result = call_api(base_url, token, "/consult/kaliContIdcc", {"id": kali_id})
    if "_error" in result:
        result["_step"] = "consult"
        result["_resolved_kali_id"] = kali_id
        result["_detail"] = (result.get("_detail","") + f" | id_utilisé={kali_id}")[:400]
    return result


def extract_salary_sections(kali_response):
    """
    Isole les sections qui ressemblent à des grilles de salaires
    (titres contenant 'salaire', 'rémunération', 'minima', 'classification')
    pour éviter de devoir tout re-parser côté Claude à chaque fois.
    """
    keywords = ["salaire", "rémunération", "remuneration", "minima", "classification", "grille"]
    matches = []

    def walk(node, path=""):
        if not isinstance(node, dict):
            return
        titre = (node.get("titre") or node.get("title") or "").lower()
        if any(k in titre for k in keywords):
            matches.append({"path": path, "titre": node.get("titre") or node.get("title"), "id": node.get("id")})
        for child in node.get("sections", []) or node.get("children", []) or []:
            walk(child, path + "/" + (node.get("titre") or ""))

    walk(kali_response)
    return matches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idcc", help="Liste d'IDCC séparés par des virgules")
    ap.add_argument("--idcc-file", help="Fichier texte, un IDCC par ligne")
    ap.add_argument("--out", default="output/ccn", help="Dossier de sortie")
    ap.add_argument("--delay", type=float, default=0.5, help="Délai entre appels (s)")
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants (GitHub Secrets).", file=sys.stderr)
        sys.exit(1)

    idcc_list = []
    if args.idcc:
        idcc_list = [x.strip() for x in args.idcc.split(",") if x.strip()]
    elif args.idcc_file:
        with open(args.idcc_file) as f:
            idcc_list = [line.strip() for line in f if line.strip()]
    else:
        print("ERREUR: fournir --idcc ou --idcc-file", file=sys.stderr)
        sys.exit(1)

    token_url, base_url = get_urls()
    print(f"Environnement: {'production' if 'sandbox' not in base_url else 'SANDBOX (données possiblement périmées)'}")
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(idcc_list)} IDCC à traiter.")

    os.makedirs(args.out, exist_ok=True)
    debug_dir = os.path.join(args.out, "_debug_search")
    summary = []

    for i, idcc in enumerate(idcc_list, 1):
        print(f"[{i}/{len(idcc_list)}] IDCC {idcc}...", end=" ")
        result = fetch_one_idcc(base_url, token, idcc, debug_dir=debug_dir)

        if "_error" in result:
            print(f"ERREUR {result['_error']} (étape: {result.get('_step','?')})")
            summary.append({
                "idcc": idcc, "status": "error",
                "http_status": result.get("_error"),
                "step": result.get("_step"),
                "resolved_kali_id": result.get("_resolved_kali_id"),
                "detail": result.get("_detail", "")[:300],
            })
            continue

        out_path = os.path.join(args.out, f"{idcc}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        salary_sections = extract_salary_sections(result)
        print(f"OK ({len(salary_sections)} section(s) salaire détectée(s))")
        summary.append({
            "idcc": idcc,
            "status": "ok",
            "titre": result.get("titre"),
            "salary_sections_found": len(salary_sections),
            "salary_sections": salary_sections,
        })
        time.sleep(args.delay)

    with open(os.path.join(args.out, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    n_ok = sum(1 for s in summary if s["status"] == "ok")
    n_err = sum(1 for s in summary if s["status"] == "error")
    print(f"\nTerminé: {n_ok} OK, {n_err} erreurs. Résumé dans {args.out}/_summary.json")


if __name__ == "__main__":
    main()
