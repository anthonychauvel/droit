#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT NORMLEX (OIT) — conventions ratifiees par la France.

But : COMPTER les conventions de l'Organisation internationale du travail
ratifiees par la France (et distinguer celles EN VIGUEUR), et sortir la liste
de leurs numeros (C155, C190, ...). Sert a dimensionner l'aspiration.

Source : NORMLEX (donnees publiques, sans cle ni compte). On lit la page de
profil "ratifications" de la France et on en extrait le tableau.

/!\ A CONFIRMER AU 1er RUN : NORMLEX est une appli web (URL avec parametres de
session). L'URL et la structure HTML ci-dessous sont un point de depart ; le
script affiche ce qu'il trouve pour qu'on l'ajuste sur du reel. Repere connu :
la France a ratifie ~129 conventions, dont ~79 en vigueur.
"""

import json, sys, time, datetime, re, os
try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' est requis (pip install requests).", file=sys.stderr)
    sys.exit(2)
try:
    from bs4 import BeautifulSoup
    HAVE_BS4 = True
except ImportError:
    HAVE_BS4 = False

# ------------------------------------------------------------------ REGLAGES
# Profil pays FRANCE sur NORMLEX (liste des ratifications).
# P11200_COUNTRY_ID pour la France = 102691 (a verifier au 1er run).
URL = ("https://normlex.ilo.org/dyn/normlex/fr/f?p=NORMLEXPUB:11200:0::NO::"
       "P11200_COUNTRY_ID:102691")
TIMEOUT = 90
OUT = "output/intl/recensement-normlex.json"

def fetch(tries=4):
    # Le serveur OIT renvoie 403 aux requetes "brutes". On imite un navigateur
    # (en-tetes complets) et on utilise une SESSION : on amorce d'abord la page
    # d'accueil NORMLEX pour recuperer les cookies, puis on charge la page France.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Referer": "https://normlex.ilo.org/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    sess = requests.Session()
    sess.headers.update(headers)
    try:
        sess.get("https://normlex.ilo.org/dyn/normlex/fr/f?p=NORMLEXPUB:1:0", timeout=TIMEOUT)
    except Exception:
        pass  # amorcage best-effort
    last = None
    for i in range(tries):
        try:
            r = sess.get(URL, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = repr(e)
        wait = 2 ** i
        print("  ... tentative %d/%d echouee (%s), pause %ds" % (i + 1, tries, last, wait))
        time.sleep(wait)
    raise RuntimeError("Echec requete NORMLEX: %s" % last)

def parse(html):
    """Extrait les numeros de conventions (Cxxx) + statut, de facon tolerante."""
    conventions = {}   # 'C155' -> {"statut": "...", "intitule": "..."}
    if HAVE_BS4:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a"):
            txt = (a.get_text() or "").strip()
            m = re.search(r"\bC0*(\d{1,3})\b", txt)
            if m:
                num = "C%03d" % int(m.group(1))
                conventions.setdefault(num, {"intitule": txt})
        # statut "en vigueur" / "denoncee" : cherche dans le texte des lignes
        for tr in soup.find_all("tr"):
            row = tr.get_text(" ", strip=True)
            m = re.search(r"\bC0*(\d{1,3})\b", row)
            if not m:
                continue
            num = "C%03d" % int(m.group(1))
            statut = ""
            low = row.lower()
            if "denonc" in low:
                statut = "denoncee"
            elif "en vigueur" in low or "in force" in low:
                statut = "en vigueur"
            conventions.setdefault(num, {})["statut"] = statut
    else:
        # repli sans bs4 : regex brute sur le HTML
        for m in re.finditer(r"\bC0*(\d{1,3})\b", html):
            num = "C%03d" % int(m.group(1))
            conventions.setdefault(num, {})
    return conventions

def main():
    print("=== Recensement NORMLEX (OIT) — ratifications France ===")
    if not HAVE_BS4:
        print("  (info: bs4 absent -> parsing degrade en regex ; installer beautifulsoup4 pour mieux)")
    html = fetch()
    print("  page recue: %d caracteres" % len(html))
    conv = parse(html)
    nums = sorted(conv.keys(), key=lambda x: int(x[1:]))
    en_vigueur = [n for n in nums if conv[n].get("statut") == "en vigueur"]
    denoncees = [n for n in nums if conv[n].get("statut") == "denoncee"]

    result = {
        "source": "NORMLEX / OIT",
        "champ": "Conventions ratifiees par la France",
        "date_recensement": datetime.date.today().isoformat(),
        "total_detecte": len(nums),
        "dont_en_vigueur": len(en_vigueur),
        "dont_denoncees": len(denoncees),
        "repere_attendu": "~129 ratifiees, ~79 en vigueur",
        "note": "Extraction tolerante depuis la page profil France. Verifier l'URL (P11200_COUNTRY_ID) et le comptage au 1er run.",
        "conventions": nums,
        "en_vigueur": en_vigueur,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n--- RESULTAT ---")
    print("Conventions detectees : %d" % len(nums))
    print("Dont en vigueur       : %d" % len(en_vigueur))
    print("Dont denoncees        : %d" % len(denoncees))
    print("Ecrit dans            : %s" % OUT)
    if nums:
        print("Echantillon           : %s" % ", ".join(nums[:12]))
    if len(nums) < 50:
        print("/!\\ Peu de resultats : l'URL du profil France ou le parsing sont "
              "probablement a ajuster (voir NORMLEX, parametre P11200_COUNTRY_ID).")

if __name__ == "__main__":
    main()
