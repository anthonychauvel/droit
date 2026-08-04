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

SNIPPET_LEN = 600      # extrait pour les articles de code (aligné : assez de texte
                       # pour que l'affichage se recentre sur la disposition, même
                       # si elle n'est pas au tout début — 70% des articles > 280)
SNIPPET_LEN_LONG = 600 # extrait plus long pour JORF/ACCO (contenu riche : on
                       # veut que la recherche matche au-delà du tout début du
                       # texte, ex. un montant ou une prime cités plus loin)
SECTION_KW_LEN = 600   # extrait de texte embarqué par section de convention


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


_OBSOLETE_PREFIXES = ("ABROGE", "PERIME", "REMPLACE", "ANNULE")


def _obsolete_article(art):
    """Version d'article qui n'est plus en vigueur (remplacée/abrogée/périmée)."""
    e = (art.get("etat") or "").upper()
    return e.startswith(_OBSOLETE_PREFIXES) or "MORT_NEE" in e


def own_text(node):
    """Texte PROPRE d'une section : son contenu direct + le contenu de ses
    articles directs, SANS descendre dans les sous-sections (pour ne pas
    dupliquer le texte des enfants et gonfler l'index). On ne retient QUE les
    versions d'article EN VIGUEUR : sinon on prévisualise une version obsolète
    (ex. le contingent 120 h remplacé en 2001 au lieu du 180/220 h en vigueur
    depuis 2012)."""
    if not isinstance(node, dict):
        return ""
    parts = []
    for key in ("texte", "content", "texteHtml"):
        val = node.get(key)
        if val:
            parts.append(strip_html(val))
    arts = [a for a in (node.get("articles") or []) if isinstance(a, dict)]
    vivants = [a for a in arts if not _obsolete_article(a)]
    for art in (vivants if vivants else arts):
        for key in ("content", "texte", "texteHtml"):
            val = art.get(key)
            if val:
                parts.append(strip_html(val))
                break
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def make_kw(text, cats, length=SECTION_KW_LEN):
    """Aperçu centré sur la 1re occurrence d'un mot-clé de la catégorie PRINCIPALE
    (la plus spécifique = cats[0]), pour prévisualiser la DISPOSITION de ce thème
    (ex. « …fixé à 180 heures… ») et non le début générique de l'article. À défaut,
    début du texte."""
    if not text:
        return ""
    low = text.lower()
    pos = -1
    principal = cats[0] if cats else None
    for kw in KEYWORDS.get(principal, ()):
        p = low.find(kw)
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    if pos > 80:
        start = max(0, pos - 60)
        snip = text[start:start + length]
        return ("…" + snip) if start > 0 else snip
    return text[:length]


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
            kw = make_kw(own, cats) if own else titre[:SECTION_KW_LEN]
            results.append({
                "path": " > ".join(current_path),
                "title": titre,
                "cat": cats[0],          # principale (la plus spécifique)
                "cats": cats,            # toutes
                "kw": kw,
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
            "juridiction": payload.get("juridiction") or "",
        })
    return index


def texte_depuis_payload(payload):
    """Extrait le texte d'un payload JORF/ACCO pour le snippet de recherche.

    CORRECTIF 01/08 : l'ancien code cherchait le texte dans payload.texte /
    texteHtml / content -- mais le vrai contenu est dans payload.articles[].content
    (et payload.sections, et payload.extraits pour ACCO). Résultat : snippet
    vide, la recherche ne matchait que le titre. On lit maintenant la vraie
    structure, comme le fait l'affichage.
    """
    morceaux = []
    # Champs directs (au cas où)
    for cle in ("texte", "texteHtml", "content", "visa", "signers"):
        v = payload.get(cle)
        if isinstance(v, str) and v.strip():
            morceaux.append(v)
    # Articles (la vraie source du contenu)
    for art in (payload.get("articles") or []):
        if isinstance(art, dict):
            c = art.get("content") or art.get("texte") or ""
            if c:
                morceaux.append(c)
    # Sections imbriquées
    def walk_sections(sections):
        for s in sections or []:
            if isinstance(s, dict):
                for art in (s.get("articles") or []):
                    if isinstance(art, dict) and (art.get("content") or art.get("texte")):
                        morceaux.append(art.get("content") or art.get("texte"))
                walk_sections(s.get("sections"))
    walk_sections(payload.get("sections"))
    # Extraits (ACCO)
    for ex in (payload.get("extraits") or []):
        if isinstance(ex, str) and ex.strip():
            morceaux.append(ex)
    brut = " ".join(morceaux)
    return strip_html(brut) if brut else ""


def build_jorf_index(jorf_dir):
    """Même principe que build_juris_index -- même format de fichier produit
    par pull_jorf.py."""
    if not os.path.isdir(jorf_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(jorf_dir, "*.json"))):
        if os.path.basename(filepath) == "_summary.json":
            continue
        numero = os.path.splitext(os.path.basename(filepath))[0]
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "_error" in data:
            continue
        titre = data.get("titre") or f"Texte JORF {numero}"
        payload = data.get("text") or {}
        text = texte_depuis_payload(payload)
        index.append({
            "num": numero,
            "title": titre,
            "snippet": text[:SNIPPET_LEN_LONG],
        })
    return index


def build_acco_index(acco_dir):
    """Même principe, avec en plus les thèmes matchés pour un futur filtre
    par thématique RH côté interface."""
    if not os.path.isdir(acco_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(acco_dir, "*.json"))):
        if os.path.basename(filepath) == "_summary.json":
            continue
        numero = os.path.splitext(os.path.basename(filepath))[0]
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "_error" in data:
            continue
        titre = data.get("titre") or f"Accord {numero}"
        payload = data.get("text") or {}
        text = texte_depuis_payload(payload)
        index.append({
            "num": numero,
            "title": titre,
            "snippet": text[:SNIPPET_LEN_LONG],
            "themes": data.get("themes") or [],
        })
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--code-dir", default="output/code-travail")
    ap.add_argument("--code-secu-dir", default="output/code-secu")
    ap.add_argument("--juris-dir", default="output/jurisprudence")
    ap.add_argument("--jorf-dir", default="output/jorf")
    ap.add_argument("--acco-dir", default="output/acco")
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
    jorf_index = build_jorf_index(args.jorf_dir) if os.path.exists(args.jorf_dir) else []
    acco_index = build_acco_index(args.acco_dir) if os.path.exists(args.acco_dir) else []

    full_index = {"ccn": ccn_index, "code": code_index, "code_secu": code_secu_index,
                  "juris": juris_index, "jorf": jorf_index, "acco": acco_index}

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(full_index, f, ensure_ascii=False, separators=(",", ":"))

    n_hits = sum(len(c["hits"]) for c in ccn_index)
    size_kb = os.path.getsize(args.out) / 1024
    print(f"Index construit: {len(ccn_index)} CCN ({n_hits} sections indexees), "
          f"{len(code_index)} articles travail, {len(code_secu_index)} articles secu, "
          f"{len(juris_index)} decisions, {len(jorf_index)} textes JORF, "
          f"{len(acco_index)} accords d'entreprise.")
    print(f"Taille: {size_kb:.0f} Ko -> {args.out}")


if __name__ == "__main__":
    main()
