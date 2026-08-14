#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT HUDOC (CEDH) — arrets lies au travail / vie privee au travail.

But : COMPTER les arrets de la Cour europeenne des droits de l'homme
pertinents pour un salarie (vie privee au travail art. 8, discrimination
art. 14, etc.) et sortir la liste de leurs identifiants (ECLI / n de requete).

Source : point d'acces REST public de HUDOC (celui qu'utilise l'interface web).
  -> PAS de cle, PAS de compte. Plusieurs aspirateurs open-source l'utilisent.
  -> Appel cote script (pagination par tranches pour eviter les timeouts).

/!\ A CONFIRMER AU 1er RUN : la SYNTAXE de filtre HUDOC est particuliere
(champs 'contentsitename', 'kpthesaurus', 'article'...). La requete ci-dessous
est un point de depart raisonnable ; le script affiche le total renvoye par
HUDOC et un echantillon pour qu'on l'affine sur du reel.
"""

import json, sys, time, datetime, os
try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' est requis (pip install requests).", file=sys.stderr)
    sys.exit(2)

# ------------------------------------------------------------------ REGLAGES
BASE = "https://hudoc.echr.coe.int/app/query/results"
# Filtre HUDOC (syntaxe interne). On vise : JUGEMENTS (pas decisions), langue
# FR ou EN, portant sur l'article 8 (vie privee) OU 14 (discrimination), et on
# resserrera ensuite sur le contexte "travail" via les mots-cles.
# NB: '%22' = guillemet ; la requete est deja url-encodee cote 'query'.
QUERY = ('contentsitename:ECHR '
         'AND (documentcollectionid2:"JUDGMENTS") '
         'AND (article:"8" OR article:"14")')
FIELDS = "itemid,docname,appno,article,ecli,kpdate,conclusion"
PAGE = 500
MAX_PAGES = 40
TIMEOUT = 90
OUT = "output/intl/recensement-hudoc.json"

def fetch(start, length, tries=4):
    params = {
        "query": QUERY,
        "select": FIELDS,
        "sort": "kpdate Descending",
        "start": start,
        "length": length,
    }
    headers = {"User-Agent": "MonLegiTexte-recensement/1.0 (contact via depot droit)",
               "Accept": "application/json"}
    last = None
    for i in range(tries):
        try:
            r = requests.get(BASE, params=params, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = repr(e)
        wait = 2 ** i
        print("  ... tentative %d/%d echouee (%s), pause %ds" % (i + 1, tries, last, wait))
        time.sleep(wait)
    raise RuntimeError("Echec requete HUDOC: %s" % last)

def main():
    print("=== Recensement HUDOC (CEDH) — arrets art. 8 / 14 ===")
    items = {}   # itemid -> infos
    total_annonce = None
    for page in range(MAX_PAGES):
        start = page * PAGE
        print("Page %d (start %d)..." % (page + 1, start))
        data = fetch(start, PAGE)
        # HUDOC renvoie typiquement {"resultcount": N, "results": [{"columns": {...}}, ...]}
        if total_annonce is None:
            total_annonce = data.get("resultcount")
            if total_annonce is not None:
                print("  HUDOC annonce %s resultats au total" % total_annonce)
        results = data.get("results") or []
        if not results:
            print("  (plus de resultats)")
            break
        for it in results:
            col = it.get("columns", it) or {}
            iid = col.get("itemid") or it.get("itemid")
            if not iid:
                continue
            items[iid] = {
                "docname": col.get("docname", ""),
                "appno": col.get("appno", ""),
                "ecli": col.get("ecli", ""),
                "article": col.get("article", ""),
                "date": col.get("kpdate", ""),
            }
        print("  +%d lignes (total unique: %d)" % (len(results), len(items)))
        if len(results) < PAGE:
            break
        time.sleep(1)

    ids = sorted(items.keys())
    result = {
        "source": "HUDOC / CEDH",
        "champ": "Arrets (JUDGMENTS) portant sur l'article 8 ou 14 — a resserrer sur le contexte travail",
        "date_recensement": datetime.date.today().isoformat(),
        "total_hudoc_annonce": total_annonce,
        "total_collecte": len(ids),
        "note": "Compte LARGE (tous art.8/14). L'etape suivante resserrera sur les mots-cles 'travail/emploi/surveillance' via kpthesaurus. Verifier la structure de reponse au 1er run.",
        "items": [{"itemid": i, **items[i]} for i in ids[:5000]],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n--- RESULTAT ---")
    print("HUDOC annonce      : %s" % total_annonce)
    print("Collecte           : %d" % len(ids))
    print("Ecrit dans         : %s" % OUT)
    if ids:
        ex = items[ids[0]]
        print("Echantillon        : %s | %s | %s" % (ex.get("appno"), ex.get("date"), ex.get("docname", "")[:60]))
    else:
        print("/!\\ AUCUN resultat : la syntaxe de la requete HUDOC est a ajuster "
              "(champs/valeurs). Voir la lib 'echr-extractor' comme reference.")

if __name__ == "__main__":
    main()
