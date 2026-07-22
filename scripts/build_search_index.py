#!/usr/bin/env python3
"""
Construit un index de recherche compact (mots-clés) à partir de tous les
fichiers déjà récupérés dans output/ccn/, output/code-travail/, etc.

v2 (approfondissement du moteur) — CHANGEMENTS CLÉS :
  * Les sections de convention sont désormais catégorisées d'après leur TITRE
    ET leur TEXTE (avant : titre seulement). Une clause de contingent glissée
    dans une section intitulée « Durée du travail » est donc enfin détectée.
  * Chaque section retenue embarque un court extrait de TEXTE (`kw`) : le moteur
    peut ainsi retrouver un mot présent dans le corps (pas seulement le titre)
    et renvoyer l'utilisateur sur la bonne section.
  * Chaque section porte toutes ses catégories (`cats`), plus une principale
    (`cat`) pour l'affichage/navigation — la plus spécifique d'abord.

Compatibilité : la forme de sortie reste la même ; on AJOUTE `cats` et `kw`
aux entrées de section (l'ancien front qui ne lit que `cat`/`title` continue
de fonctionner). Le nouveau front (index.html v3) exploite `cats` et `kw`.

Usage :
    python3 build_search_index.py --out output/search-index.json
"""
import json
import os
import re
import glob
import argparse

SNIPPET_LEN = 280      # extrait pour les articles de code
SECTION_KW_LEN = 240   # extrait de texte embarqué par section de convention


def strip_html(raw):
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Catégories utiles. L'ordre = priorité d'affichage (la plus SPÉCIFIQUE d'abord ;
# « durée du travail », très générique, est volontairement en dernier pour ne pas
# éclipser un vrai contingent/majoration détecté dans la même section).
KEYWORDS = {
    "contingent_hs": ["contingent", "contingent annuel", "contingent d'heures",
                       "contingent d heures", "hors contingent", "au-delà du contingent",
                       "au dela du contingent", "quota d'heures", "220 heures"],
    "majoration_hs": ["majoration", "bonification", "taux de majoration", "heures majorées",
                       "majorées à", "majoration pour heures", "travail de nuit",
                       "travail du dimanche", "travail un jour férié", "heures de nuit"],
    "primes": ["prime d'ancienneté", "prime d anciennete", "prime de précarité",
               "prime de precarite", "treizième mois", "13e mois", "13ème mois",
               "prime annuelle", "prime de fin d'année", "prime de vacances",
               "prime de rendement", "gratification annuelle"],
    "minima_salariaux": ["salaire", "rémunération", "minima", "minimum", "classification",
                          "grille", "traitement", "appointement", "rémunérations", "salaires",
                          "salaire minimum", "coefficient", "barème"],
    "temps_partiel": ["temps partiel", "heures complémentaires", "à temps partiel"],
    "astreintes": ["astreinte", "astreintes", "période d'astreinte"],
    "teletravail": ["télétravail", "teletravail", "travail à distance", "travail a distance"],
    "modulation_annualisation": ["modulation", "annualisation", "aménagement du temps de travail",
                                  "répartition de la durée", "forfait annuel", "forfait en heures",
                                  "forfait jours", "forfait en jours", "forfait annuel en jours"],
    "repos": ["repos compensateur", "repos quotidien", "repos hebdomadaire",
              "repos récupérateur", "contrepartie obligatoire en repos", "contrepartie en repos",
              "réduction du temps de travail", "jours de rtt", "jrtt"],
    "contrat_essai": ["période d'essai", "periode d essai", "requalification",
                      "clause de non-concurrence", "clause de non concurrence",
                      "clause de mobilité", "contrat à durée déterminée"],
    "rupture_preavis": ["préavis", "licenciement", "rupture du contrat", "démission",
                         "indemnité de rupture", "indemnité de licenciement", "indemnité de préavis",
                         "rupture conventionnelle", "solde de tout compte", "abandon de poste",
                         "certificat de travail"],
    "conges": ["congé", "congés", "congé payé", "congés payés", "absence exceptionnelle",
               "jours fériés", "jour férié", "congé maternité", "congé paternité",
               "congé parental", "congé sans solde"],
    "duree_travail": ["durée du travail", "temps de travail", "horaire de travail",
                       "durée légale", "durée maximale", "heures supplémentaires",
                       "amplitude", "durée hebdomadaire"],
}
CAT_ORDER = list(KEYWORDS.keys())


def cats_for(text_lower):
    """Toutes les catégories dont au moins un mot-clé apparaît dans le texte."""
    found = []
    for cat in CAT_ORDER:
        if any(kw in text_lower for kw in KEYWORDS[cat]):
            found.append(cat)
    return found


def own_text(node):
    """Texte PROPRE d'une section : son contenu direct + le contenu de ses
    articles directs, SANS descendre dans les sous-sections (pour ne pas
    dupliquer le texte des enfants et gonfler l'index)."""
    if not isinstance(node, dict):
        return ""
    parts = []
    for key in ("texte", "content", "texteHtml"):
        val = node.get(key)
        if val:
            parts.append(strip_html(val))
    for art in (node.get("articles") or []):
        if isinstance(art, dict):
            for key in ("content", "texte", "texteHtml"):
                val = art.get(key)
                if val:
                    parts.append(strip_html(val))
                    break
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def walk_ccn_sections(node, path_titles=None, is_root=True):
    """Retient les sections utiles (catégorisées d'après titre + texte).
    Le chemin ne répète pas le titre de la convention elle-même."""
    if path_titles is None:
        path_titles = []
    results = []
    if not isinstance(node, dict):
        return results
    titre = node.get("title") or node.get("titre")
    current_path = path_titles if is_root else (path_titles + ([titre] if titre else []))
    if titre and not is_root:
        own = own_text(node)
        basis = (titre + " " + own).lower()
        cats = cats_for(basis)
        if cats:
            kw = own if own else titre
            results.append({
                "path": " > ".join(current_path),
                "title": titre,
                "cat": cats[0],          # principale (la plus spécifique)
                "cats": cats,            # toutes
                "kw": kw[:SECTION_KW_LEN],
            })
    for child in (node.get("sections") or []):
        results.extend(walk_ccn_sections(child, current_path, is_root=False))
    return results


def build_ccn_index(ccn_dir, classification=None):
    classification = classification or {}
    if not os.path.isdir(ccn_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(ccn_dir, "*.json"))):
        if os.path.basename(filepath) == "_summary.json":
            continue
        idcc = os.path.splitext(os.path.basename(filepath))[0]
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "_error" in data:
            continue
        hits = walk_ccn_sections(data)
        index.append({
            "num": idcc,
            "title": data.get("titre") or data.get("title") or "",
            "hits": hits,
            "source": classification.get(str(idcc), "inconnu"),
        })
    return index


def _article_payload_and_etat(data):
    if isinstance(data, dict) and isinstance(data.get("article"), dict):
        art = data["article"]
        return art, art.get("etat")
    return data, (data.get("etat") if isinstance(data, dict) else None)


def build_code_index(code_dir, classification=None):
    classification = classification or {}
    if not os.path.isdir(code_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(code_dir, "*.json"))):
        if os.path.basename(filepath) == "_summary.json":
            continue
        art = os.path.splitext(os.path.basename(filepath))[0]
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "_error" in data:
            continue
        payload, etat = _article_payload_and_etat(data)
        text = strip_html(
            (payload.get("texte") if isinstance(payload, dict) else None)
            or (payload.get("content") if isinstance(payload, dict) else None)
            or (payload.get("texteHtml") if isinstance(payload, dict) else None)
            or data.get("texte") or data.get("content") or data.get("texteHtml") or ""
        )
        index.append({
            "num": art,
            "title": f"Article {art}",
            "snippet": text[:SNIPPET_LEN],
            "etat": etat,
            "source": classification.get(art, "inconnu"),
        })
    return index


def build_juris_index(juris_dir):
    if not os.path.isdir(juris_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(juris_dir, "*.json"))):
        if os.path.basename(filepath) == "_summary.json":
            continue
        numero = os.path.splitext(os.path.basename(filepath))[0]
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "_error" in data:
            continue
        payload = data.get("text", data)
        titre = payload.get("titre") or payload.get("title") or f"Décision {numero}"
        text = strip_html(payload.get("texte") or payload.get("texteHtml") or payload.get("content") or "")
        index.append({
            "num": numero,
            "title": titre,
            "snippet": text[:SNIPPET_LEN],
        })
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--code-dir", default="output/code-travail")
    ap.add_argument("--code-secu-dir", default="output/code-secu")
    ap.add_argument("--juris-dir", default="output/jurisprudence")
    ap.add_argument("--classification", default="output/classification-source.json",
                     help="Manifeste conservé/complet écrit par classify_source.py (optionnel)")
    ap.add_argument("--out", default="output/search-index.json")
    args = ap.parse_args()

    classification = {"ccn": {}, "code_travail": {}, "code_secu": {}}
    if os.path.exists(args.classification):
        try:
            with open(args.classification, encoding="utf-8") as f:
                classification = json.load(f)
        except Exception:
            pass

    ccn_index = build_ccn_index(args.ccn_dir, classification.get("ccn"))
    code_index = build_code_index(args.code_dir, classification.get("code_travail"))
    code_secu_index = (build_code_index(args.code_secu_dir, classification.get("code_secu"))
                        if os.path.exists(args.code_secu_dir) else [])
    juris_index = build_juris_index(args.juris_dir) if os.path.exists(args.juris_dir) else []

    full_index = {"ccn": ccn_index, "code": code_index, "code_secu": code_secu_index, "juris": juris_index}

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(full_index, f, ensure_ascii=False, separators=(",", ":"))

    n_hits = sum(len(c["hits"]) for c in ccn_index)
    size_kb = os.path.getsize(args.out) / 1024
    print(f"Index construit: {len(ccn_index)} CCN ({n_hits} sections indexees), "
          f"{len(code_index)} articles travail, {len(code_secu_index)} articles secu, "
          f"{len(juris_index)} decisions.")
    print(f"Taille: {size_kb:.0f} Ko -> {args.out}")


if __name__ == "__main__":
    main()
