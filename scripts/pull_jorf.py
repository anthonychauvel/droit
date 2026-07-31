#!/usr/bin/env python3
"""
pull_jorf.py — Module 2 (Journal Officiel, volet social) : récupère les textes
du fonds JORF pertinents pour la RH (arrêtés d'extension, SMIC, plafonds,
cotisations, activité partielle...) depuis l'API PISTE/Légifrance.

Usage:
    python3 pull_jorf.py --out output/jorf --mots-cles "arrêté d'extension,SMIC"
    (--depuis calculé automatiquement à 10 ans avant aujourd'hui si omis)

Variables d'environnement requises (identiques à pull_ccn.py — même
application PISTE) :
    PISTE_CLIENT_ID
    PISTE_CLIENT_SECRET
    PISTE_ENV = "sandbox" ou "production" (défaut: sandbox)

IMPORTANT, à valider au premier run réel (pas testable dans ce bac à sable,
aucun identifiant PISTE disponible ici) :
  - Le endpoint /consult exact pour un texte JORF individuel est supposé être
    "/consult/jorf" avec {"textCid": id} par analogie avec les autres consult
    de cette même API -- à confirmer contre la vraie documentation PISTE au
    premier essai, pas garanti à 100% comme pour /consult/kaliContIdcc (déjà
    prouvé par pull_ccn.py).
  - Le filtre par ÉMETTEUR (ministère) n'est pas implémenté comme paramètre
    de recherche : je n'ai pas la certitude que /search le supporte
    nativement pour le fonds JORF. À la place, chaque texte récupéré garde
    ses métadonnées brutes -- un filtre par émetteur en post-traitement sur
    le texte récupéré est ajoutable dès que la vraie forme de ces métadonnées
    est connue (premier run réel).
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import date


# ── Authentification et appel générique : identiques à pull_ccn.py, mêmes
#    identifiants PISTE, même application -- rien de nouveau à configurer.
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
        return {"_error": "exception", "_detail": str(e)}


def date_dix_ans_glissante():
    """Aujourd'hui moins 10 ans, recalculé à CHAQUE run -- pas une date fixe
    codée en dur. Cette fenêtre ne sert QU'à borner ce qu'on va CHERCHER de
    nouveau : elle ne supprime jamais rien de ce qui a déjà été récupéré.
    Un texte de 2016 récupéré aujourd'hui reste sur disque même le jour où
    la fenêtre glissante dépasse 2016 -- ce script n'a d'ailleurs aucune
    ligne qui supprime un fichier, seulement des lignes qui en ajoutent.
    """
    aujourdhui = date.today()
    try:
        return aujourdhui.replace(year=aujourdhui.year - 10).isoformat()
    except ValueError:
        # 29 février tombé sur une année non bissextile 10 ans plus tôt.
        return aujourdhui.replace(year=aujourdhui.year - 10, day=28).isoformat()


def search_jorf_par_mot_cle(base_url, token, mot_cle, depuis, page=1):
    """Cherche dans le fonds JORF, mot-clé dans le TITRE du texte -- même
    principe que search_kali_by_idcc (typeChamp), juste un fonds et un champ
    différents. Fenêtre de date via publicationDate pour respecter le
    périmètre "10 dernières années" du cahier des charges."""
    body = {
        "fond": "JORF",
        "recherche": {
            "champs": [{
                "typeChamp": "TITLE",
                "operateur": "ET",
                "criteres": [{
                    "valeur": mot_cle,
                    "typeRecherche": "UN_DES_MOTS",
                    "operateur": "ET",
                }],
            }],
            "filtres": [{
                "facette": "DATE_PUBLICATION",
                "dates": {"start": depuis, "end": None},
            }],
            "sort": "PUBLICATION_DATE_DESC",
            "fromAdvancedRecherche": False,
            "pageNumber": page,
            "pageSize": 20,
            "typePagination": "DEFAUT",
            "operateur": "ET",
        },
    }
    return call_api(base_url, token, "/search", body)


def extract_ids_from_search(search_result):
    """Renvoie [(id_texte, titre, date), ...] depuis une réponse /search."""
    trouves = []
    for r in (search_result or {}).get("results", []):
        titre = r.get("titre") or r.get("title") or ""
        date_pub = r.get("datePublication") or r.get("date") or ""
        for section in (r.get("titles") or [{"id": r.get("id")}]):
            tid = section.get("id") or r.get("id")
            if tid:
                trouves.append((tid, titre, date_pub))
    return trouves


def fetch_un_texte(base_url, token, text_id, debug_dir=None):
    """Récupère le texte intégral d'un document JORF par son identifiant.
    Endpoint /consult/jorf -- À VALIDER au premier run réel, voir note en
    tête de fichier."""
    result = call_api(base_url, token, "/consult/jorf", {"textCid": text_id})
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, f"{text_id}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/jorf", help="Dossier de sortie")
    ap.add_argument("--mots-cles",
                     default="arrêté d'extension,avenant,SMIC,plafond de la sécurité sociale,"
                             "cotisation,activité partielle",
                     help="Mots-clés séparés par des virgules, recherchés dans le TITRE des textes JORF")
    ap.add_argument("--depuis", default=None,
                     help="Date de début (JJJJ-MM-JJ) -- par défaut, calculée comme 10 ans avant "
                          "AUJOURD'HUI (fenêtre glissante, jamais une date fixe). Ne sert qu'à "
                          "borner la recherche de nouveaux textes ; ne supprime jamais l'existant.")
    ap.add_argument("--delay", type=float, default=1.2, help="Délai entre appels (s)")
    ap.add_argument("--only-missing", action="store_true",
                     help="Ne retraite que les textes absents du résumé existant -- beaucoup plus "
                          "rapide sur les runs suivants (mêmes conventions que pull_ccn.py).")
    ap.add_argument("--max", type=int, default=200,
                     help="Plafond de textes traités ce run (0 = pas de plafond).")
    args = ap.parse_args()
    if args.depuis is None:
        args.depuis = date_dix_ans_glissante()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants (GitHub Secrets).", file=sys.stderr)
        sys.exit(1)

    mots_cles = [m.strip() for m in args.mots_cles.split(",") if m.strip()]

    token_url, base_url = get_urls()
    print(f"Environnement: {'production' if 'sandbox' not in base_url else 'SANDBOX (données possiblement périmées)'}")
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(mots_cles)} mot(s)-clé(s) à chercher depuis {args.depuis}.")

    os.makedirs(args.out, exist_ok=True)
    summary_path = os.path.join(args.out, "_summary.json")

    # Même principe de reprise que pull_ccn.py : les "ok" déjà acquis restent
    # acquis, peu importe si un run ultérieur retraite une fenêtre différente.
    existing_summary = {}
    if os.path.exists(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as f:
                for entry in json.load(f):
                    if entry.get("id"):
                        existing_summary[entry["id"]] = entry
        except Exception:
            existing_summary = {}
    preserved_ok = {k: v for k, v in existing_summary.items() if v.get("status") == "ok"}

    # 1) Recherche : un mot-clé à la fois, dédupliqué par identifiant de texte
    #    (un même arrêté peut matcher plusieurs mots-clés à la fois).
    candidats = {}  # id -> (titre, date)
    PAGES_MAX_PAR_MOT_CLE = 50  # 50 × 20 = 1000 résultats max par mot-clé, garde-fou
                                 # contre une boucle qui s'emballerait si l'API se
                                 # comporte de façon inattendue -- pas une vraie limite
                                 # attendue en pratique, juste une sécurité.
    for mot_cle in mots_cles:
        print(f"Recherche : « {mot_cle} »...")
        n_pour_ce_mot = 0
        for page in range(1, PAGES_MAX_PAR_MOT_CLE + 1):
            resultat = search_jorf_par_mot_cle(base_url, token, mot_cle, args.depuis, page=page)
            if "_error" in resultat:
                print(f"  échec page {page} ({resultat['_error']}), mot-clé suivant.", file=sys.stderr)
                break
            trouves = extract_ids_from_search(resultat)
            if not trouves:
                break  # page vide -> plus rien à cette page, mot-clé épuisé
            for tid, titre, date_pub in trouves:
                candidats[tid] = (titre, date_pub)
            n_pour_ce_mot += len(trouves)
            time.sleep(args.delay)
            if len(trouves) < 20:
                break  # dernière page partielle -> confirmé qu'il n'y a rien après
        print(f"  {n_pour_ce_mot} résultat(s) au total (toutes pages).")

    print(f"\n{len(candidats)} texte(s) unique(s) trouvé(s) au total (tous mots-clés confondus).")

    a_traiter = list(candidats.keys())
    if args.only_missing:
        avant = len(a_traiter)
        a_traiter = [tid for tid in a_traiter if tid not in preserved_ok]
        print(f"Mode --only-missing : {avant - len(a_traiter)} déjà OK protégés, {len(a_traiter)} à traiter.")
    if args.max and len(a_traiter) > args.max:
        print(f"Plafond --max {args.max} : {len(a_traiter)} candidats, le reste au run suivant.")
        a_traiter = a_traiter[:args.max]

    # 2) Récupération du texte intégral, un par un.
    debug_dir = os.path.join(args.out, "_debug_search")
    summary = list(preserved_ok.values())
    n_ok, n_echec = 0, 0

    for i, text_id in enumerate(a_traiter, 1):
        titre, date_pub = candidats[text_id]
        print(f"[{i}/{len(a_traiter)}] {titre[:60]}...", end=" ")
        result = fetch_un_texte(base_url, token, text_id, debug_dir=debug_dir)

        if "_error" in result:
            print(f"ÉCHEC ({result['_error']})")
            summary.append({"id": text_id, "titre": titre, "status": "erreur",
                             "detail": str(result.get("_detail", ""))[:200]})
            n_echec += 1
        else:
            chemin = os.path.join(args.out, f"{text_id}.json")
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump({"titre": titre, "datePublication": date_pub, "text": result}, f,
                          ensure_ascii=False, indent=2)
            summary.append({"id": text_id, "titre": titre, "datePublication": date_pub, "status": "ok"})
            print("ok")
            n_ok += 1
        time.sleep(args.delay)

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{n_ok} texte(s) récupéré(s), {n_echec} échec(s), "
          f"{len(preserved_ok)} déjà acquis avant ce run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
