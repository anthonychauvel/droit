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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _git_commit
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
COMMIT_TOUS = 700          # commit+push tous les N fichiers reussis
MAX_MINUTES = 315          # budget interne (5h15)
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
    print("=== Aspiration HUDOC (CEDH), sans plafond ===")
    print("Total %d | faits %d | restants %d" % (len(tous), len(faits), len(a_faire)))
    print("Commit tous les %d | budget interne %d min" % (COMMIT_TOUS, MAX_MINUTES))

    debut = time.time()
    ok = ko = ok_depuis_commit = 0
    statuts = {}
    arret_budget = False
    for itemid in a_faire:
        if (time.time() - debut) / 60 > MAX_MINUTES:
            print("\n/!\\ Budget de temps atteint (%d min) -> arret propre." % MAX_MINUTES)
            arret_budget = True
            break
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
        rec = {"itemid": itemid, "source": "CEDH", "titre": meta.get("docname", ""),
               "url": "https://hudoc.echr.coe.int/fre?i=%s" % itemid,
               "appno": meta.get("appno", ""),
               "docname": meta.get("docname", ""), "date": meta.get("date", ""),
               "ecli": meta.get("ecli", ""), "date_aspiration": datetime.date.today().isoformat(),
               "texte": texte}
        with open(os.path.join(DEST, _safe(itemid) + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        ok += 1; ok_depuis_commit += 1
        if ok % 25 == 0: print("  ... %d OK (dernier: %d Ko)" % (ok, len(texte) // 1024))
        if ok_depuis_commit >= COMMIT_TOUS:
            cok, detail = _git_commit.commit_et_push(
                [DEST], "Aspiration HUDOC (auto, %d faits) [skip ci]" % (len(faits) + ok))
            print("  -- commit intermediaire (%d fichiers) : %s (%s)" % (ok_depuis_commit, cok, detail))
            ok_depuis_commit = 0
        time.sleep(0.3)

    if ok_depuis_commit > 0:
        cok, detail = _git_commit.commit_et_push([DEST], "Aspiration HUDOC (auto, final) [skip ci]")
        print("  -- commit final (%d fichiers) : %s (%s)" % (ok_depuis_commit, cok, detail))

    print("\n--- RESULTAT DU RUN ---")
    print("OK: %d | echecs: %d | arret pour budget de temps: %s" % (ok, ko, arret_budget))
    print("Statuts rencontres: %s" % statuts)
    print("Restants apres ce run: %d" % (len(a_faire) - ok - ko))

if __name__ == "__main__":
    main()
