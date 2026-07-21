#!/usr/bin/env python3
"""
Construit output/manifest.json : l'INDEX COMPLET et LÉGER de tout ce qui a
été récupéré jusqu'ici. C'est ce fichier que lit la page (index.html) pour
afficher la LISTE INTÉGRALE des conventions, articles et décisions — avec,
à côté de chaque ligne, l'état "validé / abrogé" SANS avoir à ouvrir la fiche.

Différence clé avec les _summary.json :
  - le manifeste est construit en PARCOURANT LES FICHIERS réellement présents
    sur le disque (glob de output/<dossier>/*.json), pas en faisant confiance
    au résumé du dernier run. Donc un run tournant qui ne rafraîchit qu'1/10e
    du corpus n'efface JAMAIS le reste du manifeste : tout ce qui a déjà été
    récupéré (et commité dans git) reste listé.

Format (compact, pour rester léger même avec ~30 000 articles) :
{
  "generated": "2026-07-21T06:00:00Z",
  "counts": {"ccn": 696, "code": 20894, "secu": 10641, "juris": 14},
  "ccn":  [[idcc, titre, etat, source], ...],   # etat CCN = "V" (par défaut)
  "code": [[num, etat], ...],                    # titre = "Article " + num
  "secu": [[num, etat], ...],
  "juris":[[num, titre], ...]
}
etat : "V" en vigueur (validé) · "A" abrogé · "M" modifié · "P" périmé · "?" inconnu

Usage:
    python3 build_manifest.py --out output/manifest.json
"""
import argparse
import glob
import json
import os
from datetime import datetime, timezone


# États Légifrance -> code court affiché
ETAT_MAP = {
    "VIGUEUR": "V", "VIGUEUR_DIFF": "V", "VIGUEUR_ETEN": "V",
    "ABROGE": "A", "ABROGE_DIFF": "A", "ABROGE_TXT": "A",
    "MODIFIE": "M", "MODIFIE_MORT_NE": "M",
    "PERIME": "P", "DISJOINT": "P", "ANNULE": "A", "SANS_TEXTE": "?",
}


def etat_court(raw):
    if not raw:
        return "?"
    return ETAT_MAP.get(str(raw).upper().strip(), "?")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_classification(path):
    data = load_json(path) or {}
    if not isinstance(data, dict):
        return {"ccn": {}, "code_travail": {}, "code_secu": {}}
    return data


def article_num_from_filename(path):
    # output/code-travail/L3121-1.json -> "L3121-1" (les "/" d'origine ont été
    # remplacés par "-" à l'écriture ; on ne peut pas les restaurer à coup sûr,
    # mais le numéro affiché reste correct pour l'immense majorité des articles).
    return os.path.splitext(os.path.basename(path))[0]


def article_etat(data):
    """Récupère l'état d'un article de code, quel que soit l'emplacement exact."""
    if not isinstance(data, dict):
        return "?"
    if "_error" in data:
        return "?"
    art = data.get("article")
    if isinstance(art, dict) and art.get("etat"):
        return etat_court(art.get("etat"))
    # certains retours mettent l'état à la racine
    if data.get("etat"):
        return etat_court(data.get("etat"))
    # article vide (souvent = abrogé, plus de texte servi) : on reste prudent
    return "?"


def build_code(code_dir):
    out = []
    if not os.path.isdir(code_dir):
        return out
    for path in sorted(glob.glob(os.path.join(code_dir, "*.json"))):
        if os.path.basename(path) == "_summary.json":
            continue
        num = article_num_from_filename(path)
        data = load_json(path)
        out.append([num, article_etat(data)])
    return out


def build_ccn(ccn_dir, classification):
    out = []
    if not os.path.isdir(ccn_dir):
        return out
    for path in sorted(glob.glob(os.path.join(ccn_dir, "*.json"))):
        if os.path.basename(path) == "_summary.json":
            continue
        idcc = os.path.splitext(os.path.basename(path))[0]
        data = load_json(path)
        if not isinstance(data, dict) or "_error" in data:
            continue
        titre = data.get("titre") or data.get("title") or f"IDCC {idcc}"
        source = classification.get(str(idcc), "inconnu")
        # Une convention entière n'a pas d'état unique VIGUEUR/ABROGE :
        # on la marque "V" (présente / suivie) ; le détail d'un éventuel
        # avenant abrogé se voit en ouvrant la fiche.
        out.append([idcc, titre, "V", source])
    return out


def build_juris(juris_dir):
    out = []
    if not os.path.isdir(juris_dir):
        return out
    for path in sorted(glob.glob(os.path.join(juris_dir, "*.json"))):
        if os.path.basename(path) == "_summary.json":
            continue
        num = os.path.splitext(os.path.basename(path))[0]
        data = load_json(path)
        if not isinstance(data, dict) or "_error" in data:
            continue
        payload = data.get("text", data)
        titre = payload.get("titre") or payload.get("title") or f"Décision {num}"
        out.append([num, titre])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--code-dir", default="output/code-travail")
    ap.add_argument("--code-secu-dir", default="output/code-secu")
    ap.add_argument("--juris-dir", default="output/jurisprudence")
    ap.add_argument("--classification", default="output/classification-source.json")
    ap.add_argument("--out", default="output/manifest.json")
    args = ap.parse_args()

    classification = load_classification(args.classification)

    ccn = build_ccn(args.ccn_dir, classification.get("ccn", {}))
    code = build_code(args.code_dir)
    secu = build_code(args.code_secu_dir)
    juris = build_juris(args.juris_dir)

    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {"ccn": len(ccn), "code": len(code), "secu": len(secu), "juris": len(juris)},
        "ccn": ccn,
        "code": code,
        "secu": secu,
        "juris": juris,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(args.out) / 1024
    print(f"Manifeste : {len(ccn)} CCN, {len(code)} articles travail, "
          f"{len(secu)} articles sécu, {len(juris)} décisions.")
    print(f"Taille : {size_kb:.0f} Ko -> {args.out}")


if __name__ == "__main__":
    main()
