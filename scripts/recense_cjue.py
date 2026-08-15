#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT CJUE v2 — jurisprudence sociale/travail de la Cour de justice de l'UE.

La jurisprudence n'est PAS classee par code de repertoire dans CELLAR (teste :
1 seul resultat). On PIVOTE : on recupere les arrets/ordonnances/avis qui
CITENT l'une des grandes directives/reglements sociaux (temps de travail,
egalite, CDD, transfert d'entreprise, detachement, coordination secu...).
Ce sont exactement les arrets qui INTERPRETENT le droit social de l'UE.

Source : CELLAR SPARQL public (sans cle, sans compte).
Propriete cle : cdm:work_cites_work (existe et documentee dans le package eurlex).
"""

import json, sys, time, datetime, os
try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' est requis (pip install requests).", file=sys.stderr)
    sys.exit(2)

ENDPOINT = "http://publications.europa.eu/webapi/rdf/sparql"
PAGE = 500
MAX_PAGES = 80
TIMEOUT = 90
OUT = "output/intl/recensement-cjue.json"

# Grandes directives / reglements sociaux de l'UE (CELEX). Les arrets qui les
# citent forment le coeur de la jurisprudence sociale. Liste ajustable.
DIRECTIVES = [
    "32003L0088", "31993L0104",              # temps de travail
    "31999L0070", "31997L0081", "32008L0104", # CDD, temps partiel, interim
    "32019L1152", "31991L0533",              # conditions de travail transparentes
    "31996L0071", "32018L0957", "32014L0067", # detachement
    "31998L0059", "32001L0023", "32002L0014", # licenciements coll., transfert, info-consult
    "32009L0038", "31994L0033", "32008L0094", # CEE, jeunes, insolvabilite
    "32006L0054", "32000L0078", "32000L0043", # egalite (emploi, cadre, race)
    "32019L1158", "31992L0085", "32010L0041", # equilibre vie, grossesse, independants
    "31989L0391",                            # cadre sante-securite
    "32004R0883", "32009R0987",              # coordination securite sociale
    "32023L0970", "32024L2831",              # transparence salariale, travail plateforme
]

TYPES = ("<http://publications.europa.eu/resource/authority/resource-type/JUDG>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/ORDER>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/OPIN_JUR>")

PREFIXES = "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"

def bloc_where():
    values = " ".join('"%s"' % c for c in DIRECTIVES)
    return """
  ?work cdm:work_has_resource-type ?type.
  FILTER(?type=%s)
  ?work cdm:work_cites_work ?cited.
  ?cited cdm:resource_legal_id_celex ?citedcelex.
  VALUES ?citedcelex { %s }
""" % (TYPES, values)

def q_count():
    return PREFIXES + "SELECT (COUNT(DISTINCT ?work) AS ?n) WHERE {" + bloc_where() + "}"

def q_list(limit, offset):
    return (PREFIXES + "SELECT DISTINCT ?celex ?ecli WHERE {" + bloc_where() +
            "  OPTIONAL { ?work cdm:resource_legal_id_celex ?celex. }\n"
            "  OPTIONAL { ?work cdm:case-law_ecli ?ecli. }\n"
            "} ORDER BY ?celex LIMIT %d OFFSET %d" % (limit, offset))

def sparql(query, tries=4):
    headers = {"Accept": "application/sparql-results+json",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-recensement/2.0"}
    last = None
    for i in range(tries):
        try:
            r = requests.get(ENDPOINT, params={"query": query}, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = repr(e)
        wait = 2 ** i
        print("  ... tentative %d/%d echouee (%s), pause %ds" % (i + 1, tries, last, wait))
        time.sleep(wait)
    raise RuntimeError("Echec requete SPARQL: %s" % last)

def ecrire(result):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

def main():
    print("=== Recensement CJUE v2 (arrets citant les directives sociales) ===")
    print("Directives ciblees : %d" % len(DIRECTIVES))
    try:
        data = sparql(q_count())
        b = data.get("results", {}).get("bindings", [])
        total = int(b[0]["n"]["value"]) if b else 0
    except Exception as e:
        print("Erreur comptage:", e); total = -1
    print("Comptage : %s arrets" % total)
    if total <= 0:
        ecrire({"source": "CJUE / CELLAR", "date_recensement": datetime.date.today().isoformat(),
                "total_arrets": 0, "directives_ciblees": DIRECTIVES,
                "note": "Aucun arret cite ces directives (a verifier : propriete work_cites_work / format CELEX)."})
        print("/!\\ 0 arret. A investiguer."); return

    arrets = {}
    for page in range(MAX_PAGES):
        data = sparql(q_list(PAGE, page * PAGE))
        rows = data.get("results", {}).get("bindings", [])
        if not rows:
            break
        for b in rows:
            c = b.get("celex", {}).get("value")
            if c:
                arrets[c] = b.get("ecli", {}).get("value", "")
        print("  page %d : +%d (total %d)" % (page + 1, len(rows), len(arrets)))
        if len(rows) < PAGE:
            break
        time.sleep(1)

    ids = sorted(arrets.keys())
    ecrire({
        "source": "CJUE / CELLAR",
        "champ": "Arrets/ordonnances/avis citant les grandes directives sociales UE",
        "date_recensement": datetime.date.today().isoformat(),
        "directives_ciblees": DIRECTIVES,
        "total_arrets": len(ids),
        "items": [{"celex": c, "ecli": arrets[c]} for c in ids],
    })
    print("\n--- RESULTAT ---")
    print("Arrets trouves     : %d" % len(ids))
    print("Ecrit dans         : %s" % OUT)
    if ids:
        print("Echantillon CELEX  : %s" % ", ".join(ids[:8]))

if __name__ == "__main__":
    main()
