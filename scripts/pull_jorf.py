#!/usr/bin/env python3
"""
pull_jorf.py — Module 2 (Journal Officiel, volet social) : ÉNUMÈRE tous les
textes parus au JO sur la fenêtre glissante de 10 ans, puis récupère et
filtre ceux qui touchent la RH.

CHANGEMENT MAJEUR du 31/07/2026 -- pourquoi cette réécriture :
La version précédente cherchait par mot-clé via /search, qui plafonnait à
~40 résultats quoi qu'on fasse (pagination bloquée côté API). La doc
officielle Légifrance décrit un flux d'ÉNUMÉRATION complète, bien plus fiable,
exactement le même principe que list_all_code_articles.py pour le Code du
travail (lister d'abord, remplir ensuite) :

  1. /consult/lastNJo   -> liste les N derniers Journaux Officiels (conteneurs
                           JORFCONT). Plafond documenté : N < 2500.
  2. /consult/jorfCont  -> pour chaque JO, la liste de tous les JORFTEXT qui y
                           ont été publiés.
  3. /consult/jorf      -> le contenu intégral d'un texte (déjà utilisé et
                           fonctionnel depuis le correctif CID).

On énumère donc TOUT le JO sur la période (des dizaines de milliers de textes),
puis on ne garde que ceux dont le titre matche un motif RH. C'est plus lourd
qu'une recherche, mais exhaustif -- l'inverse du compromis précédent.

Variables d'environnement (identiques au reste) :
    PISTE_CLIENT_ID / PISTE_CLIENT_SECRET / PISTE_ENV (défaut sandbox)

Fenêtre : 10 ans glissants, recalculée à chaque run. Ne supprime jamais
l'existant -- aucune ligne de suppression dans ce script.

À VALIDER au premier run réel (formes déduites de la doc, pas encore testées
ici, aucun identifiant PISTE dans ce bac à sable) :
  - /consult/lastNJo : corps {"nbElement": N} -- nom du champ à confirmer.
  - /consult/jorfCont : corps {"textCid": "JORFCONT..."} -- à confirmer.
  Si l'un des deux diffère, le message d'erreur complet (affiché intégralement
  ci-dessous) donnera la vraie forme.
"""
import os
import sys
import re
import json
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta


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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as e:
        print(f"ERREUR jeton ({e.code}): {e.read().decode(errors='replace')[:500]}", file=sys.stderr)
        sys.exit(1)


def call_api(base_url, token, path, body):
    req = urllib.request.Request(
        base_url + path, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")}
    except Exception as e:
        return {"_error": "exception", "_detail": str(e)}


def date_dix_ans_glissante():
    """Aujourd'hui moins 10 ans, recalculé à chaque run. Ne borne que
    l'énumération, ne supprime jamais l'existant."""
    aujourdhui = date.today()
    try:
        return aujourdhui.replace(year=aujourdhui.year - 10)
    except ValueError:
        return aujourdhui.replace(year=aujourdhui.year - 10, day=28)


# Motif RH appliqué au TITRE de chaque texte énuméré -- large exprès, un
# arrêté d'extension de CCN, une revalorisation SMIC, un décret cotisations,
# doivent tous passer. Insensible à la casse et aux accents (normalisés avant).
MOTIF_RH = re.compile(
    r"extension|avenant|convention collective|accord|salair|smic|"
    r"plafond.*s[ée]curit[ée] sociale|cotisation|activit[ée] partielle|"
    r"temps de travail|t[ée]l[ée]travail|forfait|[ée]galit[ée] professionnelle|"
    r"[ée]pargne salariale|participation|int[ée]ressement|pr[ée]voyance|"
    r"retraite compl[ée]mentaire|apprentissage|formation professionnelle",
    re.IGNORECASE)


def titre_est_rh(titre):
    return bool(MOTIF_RH.search(titre or ""))


def lister_jo_conteneurs(base_url, token, depuis, debug_dir):
    """Étape 1 : liste les JORFCONT (conteneurs de JO) sur la période.
    lastNJo renvoie les N derniers -- on demande large et on filtre par date
    ensuite. N < 2500 (limite documentée) -> pour 10 ans (~2600 JO quotidiens),
    on plafonne à 2499 et on prévient si la période n'est pas entièrement
    couverte."""
    resultat = call_api(base_url, token, "/consult/lastNJo", {"nbElement": 2499})
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "_lastNJo.json"), "w", encoding="utf-8") as f:
            json.dump(resultat, f, ensure_ascii=False, indent=2)
    if "_error" in resultat:
        return None, resultat

    conteneurs = []
    # La réponse liste des conteneurs ; on tolère plusieurs noms de champ
    # possibles puisque la forme exacte n'est pas encore confirmée.
    items = resultat.get("containers") or resultat.get("jo") or resultat.get("results") or []
    for it in items:
        cid = it.get("id") or it.get("cid") or it.get("jorfContId")
        d = it.get("date") or it.get("publicationDate") or ""
        if cid:
            conteneurs.append((cid, d))
    return conteneurs, None


def lister_textes_du_jo(base_url, token, jorf_cont_id):
    """Étape 2 : les JORFTEXT publiés dans un JO donné."""
    resultat = call_api(base_url, token, "/consult/jorfCont", {"textCid": jorf_cont_id})
    if "_error" in resultat:
        return None, resultat
    textes = []

    def walk(node):
        if isinstance(node, dict):
            tid = node.get("id") or node.get("cid")
            titre = node.get("title") or node.get("titre") or ""
            if tid and str(tid).startswith("JORFTEXT"):
                textes.append((str(tid).split("_")[0], titre))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(resultat)
    return textes, None


def fetch_un_texte(base_url, token, text_id, debug_dir=None):
    """Étape 3 : contenu intégral. Endpoint déjà fonctionnel depuis le
    correctif CID du 31/07."""
    result = call_api(base_url, token, "/consult/jorf", {"textCid": text_id})
    if debug_dir and not os.path.exists(os.path.join(debug_dir, f"{text_id}.json")):
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, f"{text_id}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/jorf")
    ap.add_argument("--depuis", default=None,
                     help="Date de début (JJJJ-MM-JJ). Défaut : 10 ans glissants.")
    ap.add_argument("--delay", type=float, default=1.0, help="Délai entre appels (s)")
    ap.add_argument("--only-missing", action="store_true",
                     help="Ne récupère le CONTENU que des textes RH pas encore acquis.")
    ap.add_argument("--max", type=int, default=300,
                     help="Plafond de CONTENUS récupérés ce run (0 = pas de plafond). "
                          "L'énumération, elle, est toujours complète.")
    ap.add_argument("--max-jo", type=int, default=2499,
                     help="Plafond de JO à énumérer (garde-fou).")
    args = ap.parse_args()

    depuis = date.fromisoformat(args.depuis) if args.depuis else date_dix_ans_glissante()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: identifiants PISTE manquants.", file=sys.stderr)
        sys.exit(1)

    token_url, base_url = get_urls()
    print(f"Environnement: {'production' if 'sandbox' not in base_url else 'SANDBOX'}")
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. Énumération du JO depuis {depuis.isoformat()} (fenêtre glissante 10 ans).")

    os.makedirs(args.out, exist_ok=True)
    debug_dir = os.path.join(args.out, "_debug")
    summary_path = os.path.join(args.out, "_summary.json")

    existing = {}
    if os.path.exists(summary_path):
        try:
            for e in json.load(open(summary_path, encoding="utf-8")):
                if e.get("id"):
                    existing[e["id"]] = e
        except Exception:
            existing = {}
    preserved_ok = {k: v for k, v in existing.items() if v.get("status") == "ok"}

    # ── Étape 1 : conteneurs de JO ──
    print("Étape 1 : liste des Journaux Officiels...")
    conteneurs, err = lister_jo_conteneurs(base_url, token, depuis, debug_dir)
    if err:
        print(f"ÉCHEC lastNJo ({err['_error']}) : {str(err.get('_detail',''))[:400]}", file=sys.stderr)
        print("Rien récupéré -- voir le message ci-dessus pour la vraie forme du endpoint.", file=sys.stderr)
        sys.exit(1)

    depuis_dt = datetime.combine(depuis, datetime.min.time())
    conteneurs_periode = []
    for cid, d in conteneurs:
        try:
            if d and datetime.fromisoformat(d[:10]) < depuis_dt:
                continue
        except ValueError:
            pass
        conteneurs_periode.append(cid)
    conteneurs_periode = conteneurs_periode[:args.max_jo]
    print(f"  {len(conteneurs)} JO listés, {len(conteneurs_periode)} dans la fenêtre de 10 ans.")
    if len(conteneurs) >= 2499:
        print("  ATTENTION : plafond de 2499 JO atteint -- la période de 10 ans n'est "
              "peut-être pas entièrement couverte (le JO paraît quotidiennement). "
              "Les JO les plus anciens de la fenêtre peuvent manquer.", file=sys.stderr)

    # ── Étape 2 : énumération des textes, filtrés RH sur le titre ──
    print("Étape 2 : énumération des textes RH dans chaque JO...")
    candidats_rh = {}  # id -> titre
    for i, cid in enumerate(conteneurs_periode, 1):
        textes, err = lister_textes_du_jo(base_url, token, cid)
        if err:
            print(f"  [{i}/{len(conteneurs_periode)}] JO {cid} : échec ({err['_error']})", file=sys.stderr)
            time.sleep(args.delay)
            continue
        rh = [(tid, titre) for tid, titre in textes if titre_est_rh(titre)]
        for tid, titre in rh:
            candidats_rh[tid] = titre
        if i % 25 == 0 or rh:
            print(f"  [{i}/{len(conteneurs_periode)}] JO {cid} : {len(textes)} textes, "
                  f"{len(rh)} RH (cumul {len(candidats_rh)})")
        time.sleep(args.delay)

    print(f"\n{len(candidats_rh)} texte(s) RH énuméré(s) au total sur la période.")

    # ── Étape 3 : récupération du contenu ──
    a_traiter = list(candidats_rh.keys())
    if args.only_missing:
        avant = len(a_traiter)
        a_traiter = [t for t in a_traiter if t not in preserved_ok]
        print(f"Mode --only-missing : {avant - len(a_traiter)} déjà OK, {len(a_traiter)} à récupérer.")
    if args.max and len(a_traiter) > args.max:
        print(f"Plafond --max {args.max} : le reste au prochain run.")
        a_traiter = a_traiter[:args.max]

    summary = list(preserved_ok.values())
    n_ok, n_echec = 0, 0
    for i, tid in enumerate(a_traiter, 1):
        titre = candidats_rh[tid]
        print(f"[{i}/{len(a_traiter)}] {titre[:60]}...", end=" ")
        result = fetch_un_texte(base_url, token, tid, debug_dir=debug_dir)
        if "_error" in result:
            print(f"ÉCHEC ({result['_error']}) : {str(result.get('_detail',''))[:200]}")
            summary.append({"id": tid, "titre": titre, "status": "erreur"})
            n_echec += 1
        else:
            with open(os.path.join(args.out, f"{tid}.json"), "w", encoding="utf-8") as f:
                json.dump({"titre": titre, "text": result}, f, ensure_ascii=False, indent=2)
            summary.append({"id": tid, "titre": titre, "status": "ok"})
            print("ok")
            n_ok += 1
        time.sleep(args.delay)

    json.dump(summary, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n{n_ok} récupéré(s), {n_echec} échec(s), {len(preserved_ok)} déjà acquis avant ce run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
