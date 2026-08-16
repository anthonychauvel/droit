#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ASPIRATION HUDOC (CEDH) v3 — texte integral des arrets, avec ECHEC RAPIDE.

v2 : quand HUDOC ne repondait pas, le script ramait des HEURES "dans le vide"
(chaque requete expirait, reessais en boucle, aucun log avant la fin).
v3 corrige :
  - Timeout plus court + moins de reessais -> un echec coute ~20s au lieu de ~90s.
  - LOG PERIODIQUE (tous les 50 items) : on voit en temps reel les statuts
    (200 / 403 / timeout...) au lieu d'un ecran vide.
  - ARRET ANTICIPE : si les 20 premiers items echouent tous (0 succes), ou si
    une longue serie ininterrompue d'echecs survient, on s'arrete PROPREMENT
    avec un diagnostic clair -> plus jamais 5h gaspillees.
  - Conserve : commit+push tous les 700, budget de temps interne.

Meme methode de fond (endpoint docx->html d'echr-extractor) qu'avant.
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
COMMIT_TOUS = 700
MAX_MINUTES = 315
TIMEOUT = 20                 # plus court : un hang coute moins cher
TRIES = 2                    # moins de reessais
MIN_LEN = 200
# Arret anticipe :
ABANDON_DEBUT = 20           # si 0 succes apres 20 items -> HUDOC injoignable, on arrete
ABANDON_SERIE = 80           # si 80 echecs d'affilee (meme apres des succes) -> on arrete
BASE = "https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id=%s"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-aspiration/3.0"}


def _safe(itemid):
    return re.sub(r"[^A-Za-z0-9._-]", "_", itemid)


def extraire_texte(html):
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style"]):
        bad.decompose()
    body = soup.body or soup

    def texte_de(tag):
        BR = "\x00BR\x00"
        for br in tag.find_all("br"):
            br.replace_with(BR)
        t = tag.get_text(" ", strip=True)
        return re.sub(r"[ \t]*\n[ \t]*", "\n", t.replace(BR, "\n"))

    blocs = []
    for el in body.find_all(["p", "li"]):
        if el.name == "p":
            t = texte_de(el)
            if t: blocs.append(t)
        elif el.name == "li" and not el.find("p"):
            t = texte_de(el)
            if t: blocs.append(t)
    texte = "\n\n".join(blocs) if blocs else soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


def get(itemid):
    for i in range(TRIES):
        try:
            r = requests.get(BASE % itemid, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text, 200
            return None, r.status_code
        except Exception:
            if i < TRIES - 1:
                time.sleep(2)
    return None, "timeout"


def main():
    if not os.path.exists(RECENSEMENT):
        print("ERREUR: %s introuvable." % RECENSEMENT); sys.exit(1)
    os.makedirs(DEST, exist_ok=True)
    with open(RECENSEMENT, encoding="utf-8") as f:
        items = json.load(f).get("items", [])
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
    print("=== Aspiration HUDOC (CEDH) v3 — echec rapide ===")
    print("Total %d | faits %d | restants %d" % (len(tous), len(faits), len(a_faire)))
    print("Commit tous les %d | budget %d min | arret si %d echecs au debut / %d d'affilee"
          % (COMMIT_TOUS, MAX_MINUTES, ABANDON_DEBUT, ABANDON_SERIE))

    debut = time.time()
    ok = ko = ok_depuis_commit = consecutifs = tentes = 0
    statuts = {}
    motif_arret = None
    for itemid in a_faire:
        if (time.time() - debut) / 60 > MAX_MINUTES:
            motif_arret = "budget de temps (%d min)" % MAX_MINUTES
            break
        html, st = get(itemid)
        statuts[st] = statuts.get(st, 0) + 1
        tentes += 1
        if not html:
            ko += 1; consecutifs += 1
            if ko <= 10: print("  %s : statut %s" % (itemid, st))
        else:
            texte = extraire_texte(html)
            if not texte or len(texte) < MIN_LEN:
                ko += 1; consecutifs += 1
            else:
                meta = par_id.get(itemid, {})
                rec = {"itemid": itemid, "source": "CEDH", "titre": meta.get("docname", ""),
                       "url": "https://hudoc.echr.coe.int/fre?i=%s" % itemid,
                       "appno": meta.get("appno", ""), "docname": meta.get("docname", ""),
                       "date": meta.get("date", ""), "ecli": meta.get("ecli", ""),
                       "date_aspiration": datetime.date.today().isoformat(), "texte": texte}
                with open(os.path.join(DEST, _safe(itemid) + ".json"), "w", encoding="utf-8") as fo:
                    json.dump(rec, fo, ensure_ascii=False)
                ok += 1; ok_depuis_commit += 1; consecutifs = 0

        # log periodique : on voit ce qui se passe EN TEMPS REEL
        if tentes % 50 == 0:
            print("  [%d testes] OK=%d KO=%d | statuts=%s" % (tentes, ok, ko, statuts))

        # arrets anticipes
        if ok == 0 and ko >= ABANDON_DEBUT:
            motif_arret = "HUDOC injoignable : %d echecs, 0 succes des le depart (statuts=%s)" % (ko, statuts)
            break
        if consecutifs >= ABANDON_SERIE:
            motif_arret = "%d echecs d'affilee -> HUDOC bloque/instable (statuts=%s)" % (consecutifs, statuts)
            break

        if ok_depuis_commit >= COMMIT_TOUS:
            cok, detail = _git_commit.commit_et_push([DEST], "Aspiration HUDOC (auto, %d faits) [skip ci]" % (len(faits) + ok))
            print("  -- commit intermediaire (%d) : %s (%s)" % (ok_depuis_commit, cok, detail))
            ok_depuis_commit = 0
        time.sleep(0.3)

    if ok_depuis_commit > 0:
        cok, detail = _git_commit.commit_et_push([DEST], "Aspiration HUDOC (auto, final) [skip ci]")
        print("  -- commit final (%d) : %s (%s)" % (ok_depuis_commit, cok, detail))

    print("\n--- RESULTAT DU RUN ---")
    print("OK: %d | echecs: %d" % (ok, ko))
    print("Statuts rencontres: %s" % statuts)
    if motif_arret:
        print("ARRET ANTICIPE : %s" % motif_arret)
        if ok == 0:
            print("/!\\ 0 arret recupere. Si les statuts sont surtout 'timeout' ou 403, "
                  "HUDOC bloque le runner GitHub (comme NORMLEX) -> il faudra une autre "
                  "approche pour la CEDH. Envoie-moi les statuts.")
    print("Restants apres ce run: %d" % (len(a_faire) - ok - ko))


if __name__ == "__main__":
    main()
