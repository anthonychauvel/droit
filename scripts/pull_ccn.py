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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        return payload["access_token"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        print(f"ERREUR obtention du jeton ({e.code}): {detail[:500]}", file=sys.stderr)
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
        body_txt = e.read().decode(errors="replace")
        return {"_error": e.code, "_detail": body_txt}
    except Exception as e:
        # Filet de sécurité: timeout, coupure réseau, etc. -- ne jamais planter
        # le script sur un lot de centaines d'appels, juste logger et continuer.
        return {"_error": "exception", "_detail": f"{type(e).__name__}: {e}"}


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
    Récupère le conteneur KALI complet pour un IDCC donné.

    Note historique: on avait ajouté un détour par /search pour résoudre
    un id KALICONT, en pensant que kaliContIdcc l'exigeait. En pratique,
    /search (fond KALI, champ IDCC) renvoie des ids KALITEXT (textes
    individuels : avenants, accords), pas des KALICONT (conteneur de la
    convention) -- passer un KALITEXT à kaliContIdcc échoue (erreur 500).
    kaliContIdcc accepte directement le numéro IDCC brut (confirmé par sa
    propre documentation: "Identifiant de la convention collective OU
    son numéro IDCC"). Le blocage qu'on avait au début était la
    souscription API manquante, pas le format -- donc appel direct.

    Note sur le retry (retiré) : testé avec 2 tentatives supplémentaires
    sur les 500 -- confirmé 0 succès n'en avait besoin (échecs
    déterministes, pas transitoires). En mode --only-missing, la quasi-
    totalité du lot restant est justement ces échecs connus : retenter
    systématiquement doublait/triplait la durée du run pour zéro gain.
    Retiré purement et simplement.
    """
    result = call_api(base_url, token, "/consult/kaliContIdcc", {"id": str(idcc)})
    if debug_dir and "_error" in result:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, f"{idcc}_consult_raw.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    if "_error" in result:
        result["_step"] = "consult"
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
    ap.add_argument("--delay", type=float, default=1.2, help="Délai entre appels (s)")
    ap.add_argument("--only-missing", action="store_true",
                     help="Ne retraite que les IDCC absents ou en erreur dans le résumé existant "
                          "(ignore les 'ok' déjà présents) -- beaucoup plus rapide sur les runs suivants.")
    ap.add_argument("--max", type=int, default=0,
                     help="Plafond d'IDCC traités ce run (0 = pas de plafond). Pour la passe "
                          "prioritaire des nouveautés : au plus N manquants par run.")
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

    # Reprend le résumé existant : garde TOUS les "ok" déjà acquis, peu importe
    # si l'IDCC est encore dans idcc_list.txt aujourd'hui -- une donnée déjà
    # récupérée avec succès ne doit jamais disparaître silencieusement juste
    # parce que la liste a changé entre-temps.
    existing_summary = {}
    summary_path = os.path.join(args.out, "_summary.json")
    # On relit TOUJOURS le résumé existant (même hors --only-missing) pour ne
    # jamais raboter le corpus déjà acquis : un run tournant ne traite qu'une
    # tranche, mais le résumé doit rester complet.
    if os.path.exists(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as f:
                for entry in json.load(f):
                    if entry.get("idcc"):
                        existing_summary[entry["idcc"]] = entry
        except Exception:
            existing_summary = {}

    preserved_ok = [e for e in existing_summary.values() if e.get("status") == "ok"]
    preserved_ok_ids = {e["idcc"] for e in preserved_ok}

    to_process = idcc_list
    if args.only_missing:
        to_process = [i for i in idcc_list if i not in preserved_ok_ids]
        print(f"Mode --only-missing: {len(preserved_ok)} déjà OK protégés (peu importe la liste actuelle), {len(to_process)} à traiter.")

    if args.max and args.max > 0 and len(to_process) > args.max:
        print(f"Plafond --max {args.max} : {len(to_process)} candidats, on en traite "
              f"{args.max} ce run (le reste au run suivant).")
        to_process = to_process[:args.max]

    token_url, base_url = get_urls()
    print(f"Environnement: {'production' if 'sandbox' not in base_url else 'SANDBOX (données possiblement périmées)'}")
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(to_process)} IDCC à traiter.")

    os.makedirs(args.out, exist_ok=True)
    debug_dir = os.path.join(args.out, "_debug_search")
    summary = list(preserved_ok)  # on repart avec TOUS les "ok" déjà acquis, protégés

    for i, idcc in enumerate(to_process, 1):
        print(f"[{i}/{len(to_process)}] IDCC {idcc}...", end=" ")
        result = fetch_one_idcc(base_url, token, idcc, debug_dir=debug_dir)

        if "_error" in result:
            print(f"ERREUR {result['_error']} (étape: {result.get('_step','?')})")
            summary.append({
                "idcc": idcc, "status": "error",
                "http_status": result.get("_error"),
                "step": result.get("_step"),
                "detail": result.get("_detail", "")[:300],
                "retries": result.get("_retries", 0),
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

    # Filet de sécurité: dédoublonne par IDCC avant d'écrire, "ok" prioritaire
    # sur "error" pour le même IDCC (évite les doublons si une entrée existe
    # déjà deux fois pour une raison ou une autre).
    by_idcc = {}
    for entry in summary:
        idcc = entry["idcc"]
        if idcc not in by_idcc or entry["status"] == "ok":
            by_idcc[idcc] = entry
    summary = list(by_idcc.values())

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    n_ok = sum(1 for s in summary if s["status"] == "ok")
    n_err = sum(1 for s in summary if s["status"] == "error")
    print(f"\nTerminé: {n_ok} OK, {n_err} erreurs. Résumé dans {summary_path}")


if __name__ == "__main__":
    main()
