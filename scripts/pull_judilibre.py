#!/usr/bin/env python3
"""
Aspirateur Jurisprudence via JUDILIBRE (Cour de cassation + cours d'appel),
exposé sur PISTE comme l'API Légifrance -- donc AVEC LES MÊMES identifiants
(PISTE_CLIENT_ID / PISTE_CLIENT_SECRET), une fois l'API "Judilibre" ajoutée à
la même application PISTE et ses CGU validées.

Pourquoi Judilibre plutôt que le fonds JURI de Légifrance : Légifrance n'offre
pas de recherche thématique pratique de la jurisprudence, alors que Judilibre
est un vrai moteur (GET /search) qui filtre par chambre (ex. chambre sociale
`soc`, la plus pertinente pour le droit du travail), par date, par publication,
etc. On récupère ensuite le texte intégral d'une décision par GET /decision.

Deux modes :
  1) Découverte par THÈME (défaut) : cherche les décisions les plus récentes
     et pertinentes sur une liste de thèmes de droit du travail, puis récupère
     leur texte. Idéal pour alimenter le corpus automatiquement.
  2) Par NUMÉRO de pourvoi (--arrets-file) : résout chaque numéro puis récupère
     son texte -- compatible avec l'ancien arrets_list.txt.

Sortie : un fichier par décision dans output/jurisprudence/<numero>.json, au
format déjà attendu par le lecteur / l'index / le manifeste :
    { "text": { "titre": ..., "texte": ..., "numero": ..., "ecli": ...,
                "date": ..., "chambre": ..., "juridiction": ..., "solution": ...,
                "source": "judilibre", "id": <id judilibre> } }
plus un _summary.json : [ { "numero", "status", "titre" }, ... ]

Endpoints (PISTE) :
  sandbox    : https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0
  production : https://api.piste.gouv.fr/cassation/judilibre/v1.0
  /search   (GET) : recherche paginée (max 50/page, 10 000 résultats max)
  /decision (GET) : texte intégral d'une décision par son id

Variables d'environnement (GitHub Secrets, déjà en place pour Légifrance) :
    PISTE_CLIENT_ID, PISTE_CLIENT_SECRET, PISTE_ENV = "sandbox" | "production"

Usage :
    python3 pull_judilibre.py --out output/jurisprudence
    python3 pull_judilibre.py --out output/jurisprudence --chamber soc --per-theme 30 --max-decisions 400 --only-missing
    python3 pull_judilibre.py --out output/jurisprudence --arrets-file arrets_list.txt

RAPPEL PRUDENCE (identique à pull_jurisprudence.py) : le contenu récupéré est
le texte INTÉGRAL de la décision (pseudonymisé), pas un résumé du principe.
Toute réutilisation dans le guide/l'appli doit repasser par une lecture humaine.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


# Thèmes de droit du travail par défaut (mode découverte). Modifiable via --themes.
THEMES_DEFAUT = [
    "forfait jours nullité",
    "forfait jours convention individuelle",
    "cadre dirigeant requalification",
    "heures supplémentaires preuve",
    "heures complémentaires temps partiel",
    "temps partiel requalification",
    "contingent annuel heures supplémentaires",
    "rupture conventionnelle",
    "prise d'acte de la rupture",
    "licenciement sans cause réelle et sérieuse",
    "faute grave licenciement",
    "inaptitude reclassement",
    "harcèlement moral",
    "requalification CDD en CDI",
    "droit à la déconnexion",
    "congés payés report maladie",
]

# Libellés courts pour composer un titre lisible
JURIDICTION_LABEL = {"cc": "Cass.", "ca": "CA", "tj": "TJ", "tcom": "T. com."}
CHAMBRE_LABEL = {
    "soc": "soc.", "civ1": "1re civ.", "civ2": "2e civ.", "civ3": "3e civ.",
    "comm": "com.", "crim": "crim.", "mixte": "ch. mixte", "pl": "ass. plén.",
    "creun": "ch. réunies", "ordo": "ord.",
}


def get_urls():
    env = os.environ.get("PISTE_ENV", "sandbox").lower()
    if env == "production":
        return ("https://oauth.piste.gouv.fr/api/oauth/token",
                "https://api.piste.gouv.fr/cassation/judilibre/v1.0")
    return ("https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
            "https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0")


def get_token(token_url, client_id, client_secret):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": client_id,
        "client_secret": client_secret, "scope": "openid",
    }).encode()
    req = urllib.request.Request(token_url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as e:
        print(f"ERREUR obtention du jeton ({e.code}): "
              f"{e.read().decode(errors='replace')[:400]}", file=sys.stderr)
        sys.exit(1)


def api_get(base_url, token, path, params, retries=3):
    """GET JUDILIBRE avec Bearer. Renvoie le JSON, ou {"_error": ...}."""
    url = base_url + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            code = e.code
            body = e.read().decode(errors="replace")
            # 429 = quota : on attend et on réessaie
            if code == 429 and attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"  (429 quota, pause {wait}s)", end=" ")
                time.sleep(wait)
                continue
            return {"_error": code, "_detail": body[:400]}
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return {"_error": "network", "_detail": str(e)}
    return {"_error": "unreachable"}


def _first(*vals):
    for v in vals:
        if v:
            return v
    return None


def compose_titre(meta):
    """Construit un titre lisible à partir des métadonnées d'une décision."""
    jur = JURIDICTION_LABEL.get(str(meta.get("jurisdiction", "")).lower(),
                                meta.get("jurisdiction") or "")
    ch = CHAMBRE_LABEL.get(str(meta.get("chamber", "")).lower(),
                           meta.get("chamber") or "")
    date = meta.get("decision_date") or meta.get("date") or ""
    num = numero_of(meta)
    parts = [p for p in [jur, ch] if p]
    tete = " ".join(parts).strip()
    bout = []
    if date:
        bout.append(date)
    if num:
        bout.append(f"n° {num}")
    titre = tete
    if bout:
        titre = (tete + ", " if tete else "") + ", ".join(bout)
    return titre or f"Décision {num or meta.get('id', '')}"


def numero_of(meta):
    """Numéro de pourvoi : champ 'number' (str) ou premier de 'numbers' (list)."""
    num = meta.get("number")
    if not num:
        nums = meta.get("numbers") or meta.get("pourvois")
        if isinstance(nums, list) and nums:
            num = nums[0]
    return str(num).strip() if num else None


def extract_text(decision):
    """Texte intégral : Judilibre le renvoie sous 'text' (parfois 'texte')."""
    return _first(decision.get("text"), decision.get("texte"),
                  decision.get("textHighlight"), decision.get("content")) or ""


def search_theme(base_url, token, query, chamber, jurisdiction, per_theme):
    """Renvoie une liste d'ids de décisions pour un thème (paginée)."""
    ids = []
    page = 0
    page_size = min(50, per_theme)
    while len(ids) < per_theme:
        params = {
            "query": query,
            "field": ["expose", "moyens", "motivations", "dispositif", "summary", "text"],
            "operator": "and",
            "page": page,
            "page_size": page_size,
            "sort": "date",
            "order": "desc",
            "resolve_references": "false",
        }
        if chamber:
            params["chamber"] = chamber
        if jurisdiction:
            params["jurisdiction"] = jurisdiction
        data = api_get(base_url, token, "/search", params)
        if "_error" in data:
            print(f"  [search '{query}'] erreur {data['_error']}", file=sys.stderr)
            break
        results = data.get("results") or []
        if not results:
            break
        for r in results:
            rid = r.get("id")
            if rid:
                ids.append(rid)
        total = data.get("total", 0)
        page += 1
        if page * page_size >= total or page >= 20:
            break
        time.sleep(0.4)
    return ids[:per_theme]


def fetch_decision(base_url, token, decision_id):
    return api_get(base_url, token, "/decision",
                   {"id": decision_id, "resolve_references": "true"})


def resolve_numero(base_url, token, numero, chamber, jurisdiction):
    """Mode --arrets-file : retrouve l'id d'une décision par son numéro."""
    params = {"query": numero, "field": ["number"], "page": 0, "page_size": 5}
    if jurisdiction:
        params["jurisdiction"] = jurisdiction
    data = api_get(base_url, token, "/search", params)
    if "_error" in data:
        return None
    for r in (data.get("results") or []):
        if numero.replace(" ", "") in str(numero_of(r) or "").replace(" ", ""):
            return r.get("id")
    res = data.get("results") or []
    return res[0].get("id") if res else None


def build_record(decision):
    """Transforme une décision Judilibre en fichier au format du lecteur."""
    numero = numero_of(decision) or decision.get("id")
    return {
        "text": {
            "titre": compose_titre(decision),
            "texte": extract_text(decision),
            "numero": numero,
            "ecli": decision.get("ecli"),
            "date": decision.get("decision_date") or decision.get("date"),
            "chambre": decision.get("chamber"),
            "juridiction": decision.get("jurisdiction"),
            "solution": decision.get("solution"),
            "publication": decision.get("publication"),
            "source": "judilibre",
            "id": decision.get("id"),
        }
    }, numero


def safe_name(numero):
    return str(numero).replace("/", "-").replace(" ", "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/jurisprudence")
    ap.add_argument("--themes", nargs="*", default=None,
                    help="Thèmes de recherche (défaut : liste droit du travail intégrée)")
    ap.add_argument("--arrets-file", default=None,
                    help="Mode numéros : un numéro de pourvoi par ligne")
    ap.add_argument("--chamber", default="soc",
                    help="Chambre (défaut 'soc' = sociale ; vide = toutes)")
    ap.add_argument("--jurisdiction", default="cc",
                    help="Juridiction : 'cc' (Cour de cassation, défaut), 'ca' (cours d'appel), vide = toutes")
    ap.add_argument("--per-theme", type=int, default=25,
                    help="Nb max de décisions récupérées par thème")
    ap.add_argument("--max-decisions", type=int, default=400,
                    help="Plafond global de décisions récupérées ce run")
    ap.add_argument("--only-missing", action="store_true",
                    help="Ne récupère que les décisions dont le fichier n'existe pas déjà")
    ap.add_argument("--delay", type=float, default=0.8, help="Délai entre appels (s)")
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants (GitHub Secrets).",
              file=sys.stderr)
        sys.exit(1)

    token_url, base_url = get_urls()
    is_sandbox = "sandbox" in base_url
    print(f"Environnement: {'SANDBOX (données possiblement périmées)' if is_sandbox else 'production'}")
    token = get_token(token_url, client_id, client_secret)
    print("Token OK.")

    os.makedirs(args.out, exist_ok=True)
    chamber = args.chamber.strip() or None
    jurisdiction = args.jurisdiction.strip() or None

    def already(numero):
        return os.path.exists(os.path.join(args.out, f"{safe_name(numero)}.json"))

    # --- Étape 1 : rassembler les décisions à récupérer (ids) ---
    ids = []
    if args.arrets_file:
        with open(args.arrets_file, encoding="utf-8") as f:
            numeros = [l.strip() for l in f if l.strip()]
        print(f"Mode numéros : {len(numeros)} pourvoi(s) à résoudre.")
        for numero in numeros:
            if args.only_missing and already(numero):
                continue
            rid = resolve_numero(base_url, token, numero, chamber, jurisdiction)
            if rid:
                ids.append(rid)
            time.sleep(args.delay)
    else:
        themes = args.themes if args.themes else THEMES_DEFAUT
        print(f"Mode découverte : {len(themes)} thème(s), chambre={chamber or 'toutes'}, "
              f"juridiction={jurisdiction or 'toutes'}.")
        seen = set()
        for theme in themes:
            found = search_theme(base_url, token, theme, chamber, jurisdiction, args.per_theme)
            nouveaux = [i for i in found if i not in seen]
            for i in nouveaux:
                seen.add(i)
            ids.extend(nouveaux)
            print(f"  '{theme}' -> {len(found)} résultats ({len(nouveaux)} nouveaux)")
            time.sleep(args.delay)

    # dédoublonnage en gardant l'ordre, puis plafond
    vus, ids_uniq = set(), []
    for i in ids:
        if i not in vus:
            vus.add(i)
            ids_uniq.append(i)
    if args.max_decisions and len(ids_uniq) > args.max_decisions:
        print(f"Plafond --max-decisions {args.max_decisions} : {len(ids_uniq)} trouvées, "
              f"on en récupère {args.max_decisions} ce run (le reste au run suivant).")
        ids_uniq = ids_uniq[:args.max_decisions]

    print(f"\n{len(ids_uniq)} décision(s) à récupérer.\n")

    # --- Étape 2 : récupérer le texte + écrire, sans jamais écraser un bon fichier ---
    summary = {}
    summary_path = os.path.join(args.out, "_summary.json")
    if os.path.exists(summary_path):
        try:
            for e in json.load(open(summary_path, encoding="utf-8")):
                if e.get("numero"):
                    summary[e["numero"]] = e
        except Exception:
            summary = {}

    n_ok = 0
    for idx, did in enumerate(ids_uniq, 1):
        decision = fetch_decision(base_url, token, did)
        if "_error" in decision:
            print(f"[{idx}/{len(ids_uniq)}] id={did} ERREUR {decision['_error']}")
            time.sleep(args.delay)
            continue
        record, numero = build_record(decision)
        numero = numero or did
        if args.only_missing and already(numero):
            time.sleep(args.delay)
            continue
        out_path = os.path.join(args.out, f"{safe_name(numero)}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        summary[numero] = {"numero": numero, "status": "ok",
                           "titre": record["text"]["titre"]}
        n_ok += 1
        print(f"[{idx}/{len(ids_uniq)}] {numero} OK — {record['text']['titre']}")
        time.sleep(args.delay)

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(list(summary.values()), f, ensure_ascii=False, indent=2)

    print(f"\nTerminé : {n_ok} décision(s) écrite(s). "
          f"Total suivi : {len(summary)} dans le résumé.")


if __name__ == "__main__":
    main()
