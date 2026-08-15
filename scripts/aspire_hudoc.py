#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ASPIRATION HUDOC (CEDH) — texte integral des arrets.

Lit output/intl/recensement-hudoc.json (items[].itemid) et telecharge le
texte de chaque arret via le point de conversion docx->html de HUDOC :
  https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id=<itemid>
(methode reprise du projet open-source echr-extractor, qui l'utilise en
production -> fiable, contrairement a une URL devinee).

Ecrit un JSON par arret dans output/intl/textes-hudoc/<itemid_assaini>.json.
REPRENABLE, PAR LOTS, DEFENSIF (comme aspire_eurlex.py).
"""

import json, sys, time, datetime, os, re
try:
    import requests
except ImportError:
    print("ERREUR: 'requests' requis.", file=sys.stderr); sys.exit(2)
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERREUR: 'beautifulsoup4' requis.", file=sys.stderr); sys.exit(2)

RECENSEMENT = "output/intl/recensement-hudoc.json"
DEST = "output/intl/textes-hudoc"
LOT = 250
TIMEOUT = 30
MIN_LEN = 200
BASE = "https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id=%s"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-aspiration/1.0"}

def _safe(itemid):
    """Nom de fichier sûr (l'itemid HUDOC contient parfois des caractères
    comme des espaces ou parenthèses)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", itemid)

def extraire_texte(html):
    """Reprend la logique de l'extracteur HUDOC de reference : on lit les
    paragraphes <p>/<li> plutot qu'un get_text() brut (bien plus propre sur
    ce format, qui contient beaucoup de mise en forme residuelle)."""
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style"]):
        bad.decompose()
    body = soup.body or soup

    def texte_de(tag):
        BR = "\x00BR\x00"
        for br in tag.find_all("br"):
            br.replace_with(BR)
        t = tag.get_text(" ", strip=True)
        t = t.replace(BR, "\n")
        return re.sub(r"[ \t]*\n[ \t]*", "\n", t)

    blocs = []
    for el in body.find_all(["p", "li"]):
        if el.name == "p":
            t = texte_de(el)
            if t: blocs.append(t)
        elif el.name == "li" and not el.find("p"):
            t = texte_de(el)
            if t: blocs.append(t)
    texte = "\n\n".join(blocs) if blocs else soup.get_text("\n", strip=True)
    texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
    return texte

def get(itemid, tries=3):
    for i in range(tries):
        try:
            r = requests.get(BASE % itemid, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text, r.status_code
            return None, r.status_code
        except Exception:
            time.sleep(2 ** i)
    return None, "reseau"

def main():
    if not os.path.exists(RECENSEMENT):
        print("ERREUR: %s introuvable." % RECENSEMENT); sys.exit(1)
    os.makedirs(DEST, exist_ok=True)
    with open(RECENSEMENT, encoding="utf-8") as f:
        items = json.load(f).get("items", [])
    # map fichier-sûr -> (itemid réel, appno, date, docname) pour retrouver
    # facilement les métadonnées déjà connues du recensement.
    par_id = {it.get("itemid"): it for it in items if it.get("itemid")}
    tous = list(par_id.keys())
    faits = set()
    for f in os.listdir(DEST):
        if f.endswith(".json"):
            try:
                faits.add(json.load(open(os.path.join(DEST, f), encoding="utf-8"))["itemid"])
            except Exception:
                pass
    a_faire = [i for i in tous if i not in faits]
    print("=== Aspiration HUDOC (CEDH) ===")
    print("Total %d | faits %d | restants %d | ce lot: %d max" % (len(tous), len(faits), len(a_faire), LOT))

    ok = ko = 0
    statuts = {}
    for itemid in a_faire[:LOT]:
        html, st = get(itemid)
        statuts[st] = statuts.get(st, 0) + 1
        if not html:
            ko += 1
            if ko <= 8: print("  %s : statut %s" % (itemid, st))
            continue
        texte = extraire_texte(html)
        if not texte or len(texte) < MIN_LEN:
            ko += 1
            if ko <= 8: print("  %s : texte trop court" % itemid)
            continue
        meta = par_id.get(itemid, {})
        rec = {"itemid": itemid, "source": "CEDH", "appno": meta.get("appno", ""),
               "docname": meta.get("docname", ""), "date": meta.get("date", ""),
               "ecli": meta.get("ecli", ""), "date_aspiration": datetime.date.today().isoformat(),
               "texte": texte}
        with open(os.path.join(DEST, _safe(itemid) + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        ok += 1
        if ok % 25 == 0: print("  ... %d OK (dernier: %d Ko)" % (ok, len(texte) // 1024))
        time.sleep(0.3)

    print("\n--- RESULTAT DU RUN ---")
    print("OK: %d | echecs: %d" % (ok, ko))
    print("Statuts rencontres: %s" % statuts)
    print("Restants apres ce run: %d" % max(0, len(a_faire) - min(LOT, len(a_faire))))

if __name__ == "__main__":
    main()
