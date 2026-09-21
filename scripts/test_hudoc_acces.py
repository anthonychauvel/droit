#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEST_HUDOC_ACCES.PY — HUDOC refuse-t-il GitHub, ou seulement notre identité ?

Depuis le 14/09/2026, l'API HUDOC renvoie HTTP 403 au runner, alors qu'elle
répond normalement ailleurs. Deux causes possibles, qui ne se traitent pas du
tout pareil :
  - blocage des adresses GitHub  -> rien à faire sans serveur à nous ;
  - filtrage de l'en-tête User-Agent (« MonLegiTexte-enrich/1.0 » ne
    ressemble pas à un navigateur) -> se corrige en changeant les en-têtes.

On envoie la MÊME petite requête (1 résultat) sous trois identités, et on
affiche ce que le serveur répond. Ne touche à aucun fichier.
"""
import sys, time
import requests

URL = "https://hudoc.echr.coe.int/app/query/results"
PARAMS = {"query": 'contentsitename:ECHR AND (documentcollectionid2:"JUDGMENTS")',
          "select": "itemid,docname,kpdate", "sort": "kpdate Descending",
          "start": 0, "length": 1}

NAVIGATEUR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
IDENTITES = {
    "A — actuelle (enrich_hudoc.py)": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-enrich/1.0",
        "Accept": "application/json"},
    "B — navigateur complet": {
        "User-Agent": NAVIGATEUR,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Referer": "https://hudoc.echr.coe.int/fre",
        "X-Requested-With": "XMLHttpRequest"},
    "C — python-requests brut": {},
}
SIGNES = ("server", "content-type", "cf-ray", "x-akamai", "akamai", "x-azure-ref",
          "x-cache", "via", "retry-after", "x-ms-", "set-cookie")

resultats = {}
for nom, h in IDENTITES.items():
    print("\n=== %s ===" % nom)
    try:
        r = requests.get(URL, params=PARAMS, headers=h, timeout=45)
        print("HTTP %s" % r.status_code)
        for k, v in r.headers.items():
            if any(k.lower().startswith(s) for s in SIGNES):
                print("  %s: %s" % (k, v[:150]))
        corps = r.text.strip().replace("\n", " ")
        print("  corps : %s" % corps[:400])
        resultats[nom] = r.status_code
    except Exception as e:
        print("ERREUR : %r" % e)
        resultats[nom] = "erreur"
    time.sleep(3)

try:
    ip = requests.get("https://api.ipify.org", timeout=10).text
    print("\nAdresse du runner : %s" % ip)
except Exception:
    pass

print("\n=== VERDICT ===")
for nom, code in resultats.items():
    print("  %-34s %s" % (nom, code))
ok = [n for n, c in resultats.items() if c == 200]
if not ok:
    print("Refusé sous toutes les identités : blocage des adresses GitHub. "
          "Rien à corriger dans les scripts.")
elif resultats.get("A — actuelle (enrich_hudoc.py)") != 200:
    print("Passe avec : %s -> c'est l'identité qui est filtrée. "
          "Il suffit de changer les en-têtes des scripts HUDOC." % ", ".join(ok))
else:
    print("L'identité actuelle passe : le blocage est levé (ou intermittent).")
sys.exit(0)
