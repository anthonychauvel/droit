#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT CJUE v3 — jurisprudence sociale/travail (arrets citant les
grandes directives sociales UE).

v2 interrogeait les 27 directives EN UNE SEULE requete -> trop lourde pour
CELLAR (timeout -> 0 resultat). v3 interroge DIRECTIVE PAR DIRECTIVE : chaque
requete part du texte cite (tres selectif) et recupere les arrets qui le
citent. On agrege ensuite les arrets uniques. Plus leger, plus robuste, et on
voit le compte PAR directive (debug facile).

Source : CELLAR SPARQL public (sans cle, sans compte).
"""

import json, sys, time, datetime, os
try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' est requis (pip install requests).", file=sys.stderr)
    sys.exit(2)

ENDPOINT = "http://publications.europa.eu/webapi/rdf/sparql"
TIMEOUT = 120
OUT = "output/intl/recensement-cjue.json"

DIRECTIVES = [
    "32003L0088", "31993L0104", "31999L0070", "31997L0081", "32008L0104",
    "32019L1152", "31991L0533", "31996L0071", "32018L0957", "32014L0067",
    "31998L0059", "32001L0023", "32002L0014", "32009L0038", "31994L0033",
    "32008L0094", "32006L0054", "32000L0078", "32000L0043", "32019L1158",
    "31992L0085", "32010L0041", "31989L0391", "32004R0883", "32009R0987",
    "32023L0970", "32024L2831",
]

TYPES = ("<http://publications.europa.eu/resource/authority/resource-type/JUDG>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/ORDER>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/OPIN_JUR>")

PREFIXES = "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"

def q_pour(celex_dir):
    # On part du TEXTE CITE (tres selectif) puis on remonte aux arrets citants.
    return (PREFIXES +
            "SELECT DISTINCT ?celex ?ecli WHERE {\n"
            "  ?cited cdm:resource_legal_id_celex ?cc.\n"
            '  FILTER(str(?cc)="%s")\n'
            "  ?work cdm:work_cites_work ?cited.\n"
            "  ?work cdm:work_has_resource-type ?type.\n"
            "  FILTER(?type=%s)\n"
            "  OPTIONAL { ?work cdm:resource_legal_id_celex ?celex. }\n"
            "  OPTIONAL { ?work cdm:case-law_ecli ?ecli. }\n"
            "} LIMIT 2000" % (celex_dir, TYPES))

def sparql(query, tries=4):
    headers = {"Accept": "application/sparql-results+json",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-recensement/3.0"}
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
        print("    ... retry %d/%d (%s), pause %ds" % (i + 1, tries, last, wait))
        time.sleep(wait)
    raise RuntimeError("Echec: %s" % last)

def ecrire(result):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

def main():
    print("=== Recensement CJUE v3 (arret par arret, directive par directive) ===")
    arrets = {}        # celex -> ecli
    par_directive = {} # celex_dir -> nb d'arrets
    erreurs = []
    for d in DIRECTIVES:
        try:
            data = sparql(q_pour(d))
            rows = data.get("results", {}).get("bindings", [])
            n = 0
            for b in rows:
                c = b.get("celex", {}).get("value")
                if c:
                    arrets[c] = b.get("ecli", {}).get("value", "")
                    n += 1
            par_directive[d] = n
            print("  %s -> %d arret(s) citant (total unique: %d)" % (d, n, len(arrets)))
        except Exception as e:
            par_directive[d] = -1
            erreurs.append(d)
            print("  %s -> ERREUR (%s)" % (d, e))
        time.sleep(1)  # politesse entre requetes

    ids = sorted(arrets.keys())
    ecrire({
        "source": "CJUE / CELLAR",
        "champ": "Arrets/ordonnances/avis citant les grandes directives sociales UE",
        "date_recensement": datetime.date.today().isoformat(),
        "methode": "une requete par directive (evite le timeout de la requete combinee)",
        "total_arrets_uniques": len(ids),
        "par_directive": par_directive,
        "directives_en_erreur": erreurs,
        "items": [{"celex": c, "ecli": arrets[c]} for c in ids],
    })
    print("\n--- RESULTAT ---")
    print("Arrets uniques     : %d" % len(ids))
    if erreurs:
        print("Directives en erreur (timeout ?) : %s" % ", ".join(erreurs))
    print("Ecrit dans         : %s" % OUT)
    if ids:
        print("Echantillon CELEX  : %s" % ", ".join(ids[:8]))
    else:
        print("/!\\ 0 arret. Si beaucoup d'erreurs -> CELLAR lent, relancer. Sinon, "
              "la propriete work_cites_work ne matche pas -> on curera (comme l'OIT).")

if __name__ == "__main__":
    main()
