#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT NORMLEX (OIT) — conventions ratifiees par la France.

Le serveur de l'OIT bloque souvent les requetes automatisees (403), en
particulier depuis des IP de datacenter (comme les runners GitHub). Ce script :
  1) tente plusieurs URL (chemins EN/FR) avec des en-tetes de navigateur
     complets + une session (cookies) ;
  2) s'il est bloque sur toutes, il N'PLANTE PAS : il ecrit un resultat
     "bloque" avec la marche a suivre (repli sur une liste curee).

Repere attendu si l'acces passe : ~129 conventions ratifiees, ~79 en vigueur.
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

# URL candidates du profil pays FRANCE (P11200_COUNTRY_ID:102691 a verifier).
URLS = [
    "https://normlex.ilo.org/dyn/normlex/en/f?p=NORMLEXPUB:11200:0::NO::P11200_COUNTRY_ID:102691",
    "https://normlex.ilo.org/dyn/normlex/fr/f?p=NORMLEXPUB:11200:0::NO::P11200_COUNTRY_ID:102691",
    "https://normlex.ilo.org/dyn/nrmlx_en/f?p=NORMLEXPUB:11200:0::NO::P11200_COUNTRY_ID:102691",
]
TIMEOUT = 90
OUT = "output/intl/recensement-normlex.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Safari";v="17"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Referer": "https://normlex.ilo.org/",
}

def fetch_any(tries=3):
    """Essaie chaque URL avec session+en-tetes. Renvoie (html, url) ou (None, dernier_statut)."""
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        sess.get("https://normlex.ilo.org/", timeout=TIMEOUT)  # amorce cookies
    except Exception:
        pass
    dernier = "aucune tentative"
    for url in URLS:
        for i in range(tries):
            try:
                r = sess.get(url, timeout=TIMEOUT)
                if r.status_code == 200 and r.text and len(r.text) > 2000:
                    print("  OK via %s" % url)
                    return r.text, url
                dernier = "HTTP %s (%s)" % (r.status_code, url)
            except Exception as e:
                dernier = "%s (%s)" % (repr(e), url)
            print("  ... %s -> %s" % (url, dernier))
            time.sleep(2 ** i)
    return None, dernier

def parse(html):
    conventions = {}
    if HAVE_BS4:
        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.find_all("tr"):
            row = tr.get_text(" ", strip=True)
            m = re.search(r"\bC0*(\d{1,3})\b", row)
            if not m:
                continue
            num = "C%03d" % int(m.group(1))
            low = row.lower()
            statut = "denoncee" if "denonc" in low else ("en vigueur" if ("en vigueur" in low or "in force" in low) else "")
            conventions[num] = {"statut": statut}
        if not conventions:
            for a in soup.find_all("a"):
                m = re.search(r"\bC0*(\d{1,3})\b", a.get_text() or "")
                if m:
                    conventions.setdefault("C%03d" % int(m.group(1)), {"statut": ""})
    else:
        for m in re.finditer(r"\bC0*(\d{1,3})\b", html):
            conventions.setdefault("C%03d" % int(m.group(1)), {"statut": ""})
    return conventions

def ecrire(result):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

def main():
    print("=== Recensement NORMLEX (OIT) — ratifications France ===")
    if not HAVE_BS4:
        print("  (info: bs4 absent -> parsing degrade)")
    html, info = fetch_any()
    if html is None:
        print("\n/!\\ Acces NORMLEX BLOQUE (%s)." % info)
        ecrire({
            "source": "NORMLEX / OIT",
            "date_recensement": datetime.date.today().isoformat(),
            "statut": "BLOQUE",
            "dernier_retour": info,
            "total_detecte": 0,
            "note": "L'OIT bloque l'acces automatise (probable filtrage des IP de "
                    "datacenter GitHub). Repli recommande : liste CUREE des conventions "
                    "ratifiees par la France pertinentes pour un salarie (petite, stable). "
                    "Alternative lourde : navigateur headless (Playwright) pour cette source.",
        })
        print("Ecrit un resultat 'bloque' (le workflow continue).")
        return

    conv = parse(html)
    nums = sorted(conv.keys(), key=lambda x: int(x[1:]))
    en_vigueur = [n for n in nums if conv[n].get("statut") == "en vigueur"]
    denoncees = [n for n in nums if conv[n].get("statut") == "denoncee"]
    ecrire({
        "source": "NORMLEX / OIT",
        "champ": "Conventions ratifiees par la France",
        "date_recensement": datetime.date.today().isoformat(),
        "statut": "OK",
        "url_ok": info,
        "total_detecte": len(nums),
        "dont_en_vigueur": len(en_vigueur),
        "dont_denoncees": len(denoncees),
        "repere_attendu": "~129 ratifiees, ~79 en vigueur",
        "conventions": nums,
        "en_vigueur": en_vigueur,
    })
    print("\n--- RESULTAT ---")
    print("Conventions detectees : %d (en vigueur ~%d, denoncees %d)" % (len(nums), len(en_vigueur), len(denoncees)))
    print("Ecrit dans            : %s" % OUT)
    if nums:
        print("Echantillon           : %s" % ", ".join(nums[:12]))
    if len(nums) < 50:
        print("/!\\ Peu de resultats : URL (P11200_COUNTRY_ID) ou parsing a ajuster.")

if __name__ == "__main__":
    main()
