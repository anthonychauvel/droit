#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAJ_DARES.PY — va chercher la dernière version du fichier DARES « Suivi
historique des conventions collectives » (l'univers des IDCC), au lieu
d'attendre qu'on la pose à la main dans ccn/.

Les pages officielles qui publient le fichier changent de forme de temps en
temps : le script les parcourt, prend les liens vers un .xlsx qui parle de
conventions / de suivi, télécharge le plus récent, et ne le garde QUE s'il
s'ouvre et contient la feuille « Conventions de branche » (sinon on garde
l'ancien : un fichier cassé ne doit jamais vider l'univers).

Écrit :
  ccn/Dares_Suivi_DERNIER.xlsx   le fichier à utiliser (nom fixe)
  ccn/dares-source.json          d'où il vient, quand (lu par le tableau de bord)

Sortie : affiche le chemin du fichier à utiliser sur la DERNIÈRE ligne
(DERNIER s'il existe, sinon le plus récent des Dares_*.xlsx du dépôt).

USAGE
    python3 scripts/maj_dares.py [--ccn ccn] [--pages URL,URL]
"""
import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PAGES = [
    "https://travail-emploi.gouv.fr/conventions-collectives-nomenclatures",
    "https://code.travail.gouv.fr/fiche-ministere-travail/conventions-collectives-nomenclatures",
    "https://dares.travail-emploi.gouv.fr/donnees/les-conventions-collectives-de-branche",
    "https://www.data.gouv.fr/api/1/datasets/?q=conventions%20collectives%20dares&page_size=20",
]
UA = "Mozilla/5.0 (X11; Linux x86_64) veille-SimulHeures (+https://github.com/anthonychauvel/droit)"
LIEN_XLSX = re.compile(r'(https?://[^"\'\s<>]+?\.xlsx|/[^"\'\s<>]+?\.xlsx)', re.I)
BON_NOM = re.compile(r"suivi|dares", re.I)   # « Grille_de_classification_… » n'est pas le bon fichier
MOIS = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12}


def ouvrir(url, delai=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return r.read()


def date_du_nom(nom):
    m = re.search(r"(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)[_ -]?(20\d\d)",
                  nom, re.I)
    if m:
        return f"{m.group(2)}-{MOIS[m.group(1).lower()]:02d}"
    m = re.search(r"(20\d\d)[_-]?(0[1-9]|1[0-2])", nom)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def valide(octets):
    try:
        import openpyxl
    except ImportError:
        print("openpyxl absent : impossible de vérifier le fichier, on ne le garde pas.")
        return False
    try:
        wb = openpyxl.load_workbook(io.BytesIO(octets), read_only=True)
        return "Conventions de branche" in wb.sheetnames
    except Exception as e:                           # noqa: BLE001
        print(f"  fichier illisible : {e}")
        return False


def candidats(pages):
    vus = []
    for p in pages:
        try:
            brut = ouvrir(p).decode("utf-8", "replace")
        except Exception as e:                       # noqa: BLE001
            print(f"  {p} : {e}")
            continue
        n = 0
        for lien in LIEN_XLSX.findall(html.unescape(brut).replace("\\/", "/")):
            u = urllib.parse.urljoin(p, lien)
            nom = urllib.parse.unquote(u.rsplit("/", 1)[-1])
            if BON_NOM.search(nom) and u not in vus:
                vus.append(u)
                n += 1
        print(f"  {p} : {n} fichier(s) .xlsx sur les conventions")
    return vus


def fichier_actuel(ccn):
    dernier = os.path.join(ccn, "Dares_Suivi_DERNIER.xlsx")
    if os.path.isfile(dernier):
        return dernier
    autres = [n for n in os.listdir(ccn) if n.lower().startswith("dares") and n.lower().endswith(".xlsx")]
    autres.sort(key=lambda n: date_du_nom(n) or n)
    return os.path.join(ccn, autres[-1]) if autres else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn", default="ccn")
    ap.add_argument("--pages", default="")
    args = ap.parse_args()
    pages = [p for p in args.pages.split(",") if p] or PAGES
    chemin_src = os.path.join(args.ccn, "dares-source.json")
    try:
        src = json.load(open(chemin_src, encoding="utf-8"))
    except Exception:
        src = {}

    print("Recherche du fichier DARES le plus récent :")
    liens = candidats(pages)
    liens.sort(key=lambda u: date_du_nom(urllib.parse.unquote(u)) or "0000")
    actuel = os.path.basename(fichier_actuel(args.ccn))
    nom_actuel = src.get("fichier") or actuel
    mois_actuel = date_du_nom(nom_actuel)
    aujourd_hui = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not liens:
        print("  Aucun lien trouvé (site bloqué ou page déplacée) : on garde le fichier actuel.")
    for u in reversed(liens[-3:]):                   # les plus récents d'abord
        nom = urllib.parse.unquote(u.rsplit("/", 1)[-1])
        mois = date_du_nom(nom)
        # Test du 02/10/2026 : la page officielle propose encore Juin2026 = le
        # fichier du dépôt est À JOUR (la DARES n'a rien publié depuis). On le
        # note, pour que le tableau de bord ne crie pas au fichier périmé.
        if nom == nom_actuel or (mois and mois_actuel and mois <= mois_actuel):
            src.update({"fichier": nom_actuel, "verifie_le": aujourd_hui, "a_jour": True,
                        "date_publication": src.get("date_publication") or (f"{mois_actuel}-01" if mois_actuel else None)})
            src.pop("nouvelle_version", None)
            print(f"  {nom} : c'est la version la plus récente publiée, déjà dans le dépôt.")
            break
        try:
            octets = ouvrir(u, delai=180)
        except Exception as e:                       # noqa: BLE001
            octets = b""
            print(f"  {nom} : téléchargement impossible ({e})")
        h = hashlib.sha1(octets).hexdigest() if octets else ""
        if not octets or not valide(octets):
            # Version plus récente publiée mais pas récupérable (site anti-robot) :
            # le tableau de bord le signale avec le lien, pour la poser à la main.
            src.update({"nouvelle_version": {"fichier": nom, "url": u, "vue_le": aujourd_hui},
                        "a_jour": False, "verifie_le": aujourd_hui})
            print(f"  {nom} : version plus récente publiée, mais pas récupérable automatiquement.")
            break
        open(os.path.join(args.ccn, "Dares_Suivi_DERNIER.xlsx"), "wb").write(octets)
        src = {"url": u, "fichier": nom, "sha1": h, "telecharge_le": aujourd_hui, "verifie_le": aujourd_hui,
               "a_jour": True, "date_publication": f"{mois}-01" if mois else None}
        print(f"  NOUVEAU fichier DARES : {nom} -> ccn/Dares_Suivi_DERNIER.xlsx")
        break
    if src:
        json.dump(src, open(chemin_src, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(fichier_actuel(args.ccn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
