#!/usr/bin/env python3
"""
pull_acco.py — Module 3 (Accords d'entreprise, benchmarking RH) : récupère les
accords du fonds ACCO pertinents pour la RH (télétravail, forfait jours, PPV,
CET, égalité professionnelle, QVT, droit à la déconnexion) depuis l'API
PISTE/Légifrance.

Usage:
    python3 pull_acco.py --out output/acco --themes "télétravail,forfait jours"

Variables d'environnement requises (identiques à pull_ccn.py / pull_jorf.py —
même application PISTE) :
    PISTE_CLIENT_ID
    PISTE_CLIENT_SECRET
    PISTE_ENV = "sandbox" ou "production" (défaut: sandbox)

IMPORTANT, à valider au premier run réel (pas testable dans ce bac à sable,
aucun identifiant PISTE disponible ici) :
  - Le endpoint /consult exact pour un accord individuel est supposé être
    "/consult/acco" avec {"textCid": id} par analogie avec /consult/jorf et
    /consult/kaliContIdcc -- ce dernier seul est confirmé fonctionner (déjà
    prouvé par pull_ccn.py), les deux autres restent une hypothèse cohérente,
    pas une certitude.
  - Filtre par SECTEUR (code APE/NAF) : PAS implémenté comme paramètre de
    recherche. Je n'ai aucune confirmation que /search le permette pour ce
    fonds. Chaque accord garde ses métadonnées brutes -- un filtre sectoriel
    en post-traitement est ajoutable dès que la vraie forme de ces métadonnées
    est connue (premier run réel), exactement comme pour l'émetteur JORF.
  - Filtre par THÈME : implémenté par mot-clé dans le TITRE (même mécanisme
    que JORF) -- raisonnable puisqu'un accord d'entreprise est généralement
    titré par son sujet ("Accord relatif au télétravail chez X"), mais pas
    garanti à 100% si des accords sont titrés de façon générique.

Fenêtre temporelle : 10 ans glissants, recalculée à chaque run (jamais une
date fixe) -- voir date_dix_ans_glissante(). Ne supprime jamais rien de
l'existant : cette fenêtre ne borne que la RECHERCHE de nouveaux textes,
aucune ligne de ce script n'efface un fichier déjà récupéré.
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


# ── Authentification et appel générique : identiques à pull_ccn.py et
#    pull_jorf.py, mêmes identifiants PISTE, même application.
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
    """Identique à pull_jorf.py : aujourd'hui moins 10 ans, recalculé à
    chaque run. Ne sert qu'à borner la recherche, jamais à supprimer
    l'existant -- ce script n'a aucune ligne qui efface un fichier."""
    aujourdhui = date.today()
    try:
        return aujourdhui.replace(year=aujourdhui.year - 10).isoformat()
    except ValueError:
        return aujourdhui.replace(year=aujourdhui.year - 10, day=28).isoformat()


def search_acco_par_theme(base_url, token, theme, depuis, page=1):
    """Cherche dans le fonds ACCO, thème dans TOUT LE TEXTE (typeChamp=ALL,
    pas TITLE) -- un accord d'entreprise est généralement titré par son
    entreprise/sa nature générique ("Accord NAO 2024"), pas par son thème --
    même principe que search_jorf_par_mot_cle, juste un fonds différent.

    Note trouvée le 31/07/2026 : les vraies données ACCO ont un champ
    "themes" STRUCTURÉ ET CODÉ ({code, groupe, libelle}), pas du texte libre
    -- typeChamp=ALL est un correctif honnête, pas la solution idéale. La
    bonne façon de filtrer par thème serait probablement de connaître les
    codes de cette taxonomie et de filtrer dessus, pas de deviner un mot-clé
    à chercher dans le texte."""
    body = {
        "fond": "ACCO",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "OU",
                "criteres": [{
                    "valeur": theme,
                    "typeRecherche": "UN_DES_MOTS",
                    "operateur": "OU",
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
            "operateur": "OU",
        },
    }
    return call_api(base_url, token, "/search", body)


def extract_ids_from_search(search_result):
    """Renvoie [(id_texte, titre, date), ...] depuis une réponse /search.

    Même correctif que pull_jorf.py (31/07/2026) : le "id" des sous-sections
    "titles" peut porter un suffixe de date collé au CID réel -- on ne garde
    que ce qui précède le premier "_".
    """
    trouves = []
    for r in (search_result or {}).get("results", []):
        titre = r.get("titre") or r.get("title") or ""
        date_pub = r.get("datePublication") or r.get("date") or ""
        for section in (r.get("titles") or [{"id": r.get("id")}]):
            tid = section.get("id") or r.get("id")
            if tid:
                tid = str(tid).split("_")[0]
                trouves.append((tid, titre, date_pub))
    return trouves


def fetch_un_accord(base_url, token, text_id, debug_dir=None):
    """Récupère le texte intégral d'un accord par son identifiant.
    Endpoint /consult/acco -- À VALIDER au premier run réel, voir note en
    tête de fichier."""
    result = call_api(base_url, token, "/consult/acco", {"textCid": text_id})
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, f"{text_id}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/acco", help="Dossier de sortie")
    ap.add_argument("--themes",
                     default="télétravail,forfait jours,prime de partage de la valeur,"
                             "compte épargne-temps,égalité professionnelle,"
                             "qualité de vie au travail,droit à la déconnexion",
                     help="Thèmes RH séparés par des virgules, recherchés dans le TITRE des accords")
    ap.add_argument("--depuis", default=None,
                     help="Date de début (JJJJ-MM-JJ) -- par défaut, calculée comme 10 ans avant "
                          "AUJOURD'HUI (fenêtre glissante, jamais une date fixe). Ne sert qu'à "
                          "borner la recherche de nouveaux textes ; ne supprime jamais l'existant.")
    ap.add_argument("--delay", type=float, default=1.2, help="Délai entre appels (s)")
    ap.add_argument("--only-missing", action="store_true",
                     help="Ne retraite que les textes absents du résumé existant -- beaucoup plus "
                          "rapide sur les runs suivants (mêmes conventions que pull_ccn.py/pull_jorf.py).")
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

    themes = [t.strip() for t in args.themes.split(",") if t.strip()]

    token_url, base_url = get_urls()
    print(f"Environnement: {'production' if 'sandbox' not in base_url else 'SANDBOX (données possiblement périmées)'}")
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. {len(themes)} thème(s) à chercher depuis {args.depuis} (fenêtre glissante 10 ans).")

    os.makedirs(args.out, exist_ok=True)
    summary_path = os.path.join(args.out, "_summary.json")

    # Même principe de reprise que pull_ccn.py / pull_jorf.py.
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

    # 1) Recherche : un thème à la fois, dédupliqué par identifiant de texte
    #    (un même accord peut couvrir plusieurs thèmes à la fois).
    candidats = {}
    PAGES_MAX_PAR_THEME = 50  # même garde-fou que pull_jorf.py, pas une vraie limite attendue.
    for theme in themes:
        print(f"Recherche : « {theme} »...")
        n_pour_ce_theme = 0
        for page in range(1, PAGES_MAX_PAR_THEME + 1):
            resultat = search_acco_par_theme(base_url, token, theme, args.depuis, page=page)
            if page == 1 and "_error" not in resultat:
                debug_path = os.path.join(args.out, "_debug_reponse_search_brute.json")
                if not os.path.exists(debug_path):
                    os.makedirs(args.out, exist_ok=True)
                    with open(debug_path, "w", encoding="utf-8") as f:
                        json.dump(resultat, f, ensure_ascii=False, indent=2)
            if "_error" in resultat:
                print(f"  échec page {page} ({resultat['_error']}) : "
                      f"{str(resultat.get('_detail',''))[:300]}", file=sys.stderr)
                break
            trouves = extract_ids_from_search(resultat)
            if not trouves:
                break
            for tid, titre, date_pub in trouves:
                entree = candidats.setdefault(tid, (titre, date_pub, []))
                if theme not in entree[2]:
                    entree[2].append(theme)
            n_pour_ce_theme += len(trouves)
            time.sleep(args.delay)
            if len(trouves) < 20:
                break
        print(f"  {n_pour_ce_theme} résultat(s) au total (toutes pages).")

    print(f"\n{len(candidats)} accord(s) unique(s) trouvé(s) au total (tous thèmes confondus).")

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
        titre, date_pub, themes_matches = candidats[text_id]
        print(f"[{i}/{len(a_traiter)}] {titre[:60]}...", end=" ")
        result = fetch_un_accord(base_url, token, text_id, debug_dir=debug_dir)

        if "_error" in result:
            print(f"ÉCHEC ({result['_error']}) : {str(result.get('_detail',''))[:300]}")
            summary.append({"id": text_id, "titre": titre, "status": "erreur",
                             "detail": str(result.get("_detail", ""))[:200]})
            n_echec += 1
        else:
            chemin = os.path.join(args.out, f"{text_id}.json")
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump({"titre": titre, "datePublication": date_pub,
                           "themes": themes_matches, "text": result}, f,
                          ensure_ascii=False, indent=2)
            summary.append({"id": text_id, "titre": titre, "datePublication": date_pub,
                             "themes": themes_matches, "status": "ok"})
            print("ok")
            n_ok += 1
        time.sleep(args.delay)

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{n_ok} accord(s) récupéré(s), {n_echec} échec(s), "
          f"{len(preserved_ok)} déjà acquis avant ce run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
