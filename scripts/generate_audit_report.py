#!/usr/bin/env python3
"""
Génère un rapport daté et lisible des changements survenus pendant CE run
(comparé au dernier commit, donc à l'état d'avant-run), pour output/.

Contrairement à un `git diff` brut sur des JSON imbriqués (illisible), ce
script résume en français ce qui a changé, fichier par fichier, avec un
niveau de détail spécifique pour les CCN (nouveau IDCC, statut changé,
nouveau texte forfait jours/heures sup/temps partiel récupéré, titre
modifié) et générique pour le reste (Code du travail, jurisprudence).

Doit tourner APRÈS toutes les étapes de récupération mais AVANT le commit
final, pour que git diff compare bien "avant ce run" vs "juste après".

Usage:
    python3 generate_audit_report.py --out audits
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


def git(args):
    r = subprocess.run(["git"] + args, capture_output=True, text=True)
    return r.stdout


def get_changed_files():
    """Fichiers modifiés/ajoutés/supprimés par rapport au dernier commit
    (donc par rapport à l'état d'avant ce run)."""
    raw = git(["status", "--porcelain"])
    changed = {"ajoutes": [], "modifies": [], "supprimes": []}
    # IMPORTANT : ne pas faire .strip() sur toute la sortie multi-lignes avant de
    # découper -- ça rognerait le(s) premier(s) caractère(s) significatifs (l'espace
    # de status " M ...") de la toute première ligne et décalerait tout le parsing.
    for line in raw.split("\n"):
        if not line.strip():
            continue
        status, path = line[:2], line[3:]
        if "??" in status or "A" in status:
            changed["ajoutes"].append(path)
        elif "D" in status:
            changed["supprimes"].append(path)
        else:
            changed["modifies"].append(path)
    return changed


def get_old_content(path):
    """Contenu du fichier tel qu'il était au dernier commit, ou None si
    le fichier n'existait pas (nouveau fichier)."""
    content = git(["show", f"HEAD:{path}"])
    if content.startswith("fatal:") or content == "":
        return None
    return content


def _walk_counts(d):
    """(#sections, #articles, #textes_intégraux_récupérés) en profondeur."""
    ns = na = nc = 0
    def walk(node):
        nonlocal ns, na, nc
        if not isinstance(node, dict):
            return
        if node.get("_texte_complet_recupere"):
            nc += 1
        na += len([a for a in (node.get("articles") or []) if isinstance(a, dict)])
        for s in (node.get("sections") or []):
            ns += 1
            walk(s)
    walk(d)
    return ns, na, nc


def _top_titles(d):
    return set((s.get("title") or s.get("titre") or "").strip()
               for s in (d.get("sections") or []) if isinstance(s, dict))


def describe_ccn_change(path):
    """Résumé lisible d'un changement sur un fichier output/ccn/<idcc>.json."""
    try:
        with open(path, encoding="utf-8") as f:
            new_data = json.load(f)
    except Exception:
        return f"{path} : illisible après le run (à vérifier manuellement)"

    old_raw = get_old_content(path)
    idcc = path.split("/")[-1].replace(".json", "")

    if old_raw is None:
        titre = new_data.get("titre", "?")
        return f"IDCC {idcc} : NOUVEAU (récupéré pour la première fois) — \"{titre[:80]}\""

    try:
        old_data = json.loads(old_raw)
    except Exception:
        old_data = {}

    notes = []
    if old_data.get("titre") != new_data.get("titre"):
        notes.append(f"titre changé (\"{old_data.get('titre','?')[:50]}\" → \"{new_data.get('titre','?')[:50]}\")")

    def count_complements(d, kind):
        n = 0
        def walk(node):
            nonlocal n
            if not isinstance(node, dict):
                return
            if node.get("_type_complement") == kind:
                n += 1
            for s in (node.get("sections") or []):
                walk(s)
        walk(d)
        return n

    for kind, label in [("forfait_jours", "forfait jours"), ("temps_partiel", "temps partiel")]:
        old_n = count_complements(old_data, kind)
        new_n = count_complements(new_data, kind)
        if new_n > old_n:
            notes.append(f"+{new_n - old_n} clause(s) {label} nouvellement récupérée(s)")

    if not notes:
        os_, oa_, oc_ = _walk_counts(old_data)
        ns_, na_, nc_ = _walk_counts(new_data)
        if nc_ > oc_:
            notes.append(f"+{nc_ - oc_} clause(s) au texte intégral récupéré")
        if ns_ != os_:
            notes.append(f"{'+' if ns_ > os_ else ''}{ns_ - os_} section(s)")
        if na_ != oa_:
            notes.append(f"{'+' if na_ > oa_ else ''}{na_ - oa_} article(s)")
        added = _top_titles(new_data) - _top_titles(old_data)
        removed = _top_titles(old_data) - _top_titles(new_data)
        if added:
            notes.append("nouvelle(s) section(s) : " + ", ".join(sorted(t for t in added if t)[:3])[:120])
        if removed:
            notes.append("section(s) retirée(s) : " + ", ".join(sorted(t for t in removed if t)[:3])[:120])
        if not notes:
            # Même structure (mêmes sections/articles) mais octets différents : le plus
            # souvent une simple réécriture (ordre des champs), pas un vrai changement de droit.
            notes.append("réécriture sans changement de structure (probable ré-enregistrement, pas une modif Légifrance)")

    return f"IDCC {idcc} : " + " ; ".join(notes)


def describe_summary_change(path):
    """_summary.json : combien de statuts ok/error ont changé."""
    try:
        with open(path, encoding="utf-8") as f:
            new_data = json.load(f)
    except Exception:
        return None
    old_raw = get_old_content(path)
    if old_raw is None:
        return None
    try:
        old_data = {str(d["idcc"]): d.get("status") for d in json.loads(old_raw)}
    except Exception:
        old_data = {}
    new_status = {str(d["idcc"]): d.get("status") for d in new_data}
    newly_ok = [i for i, s in new_status.items() if s == "ok" and old_data.get(i) != "ok"]
    newly_error = [i for i, s in new_status.items() if s == "error" and old_data.get(i) == "ok"]
    lines = []
    if newly_ok:
        lines.append(f"{len(newly_ok)} IDCC nouvellement récupérés avec succès : {', '.join(sorted(newly_ok)[:20])}" +
                      (" ..." if len(newly_ok) > 20 else ""))
    if newly_error:
        lines.append(f"⚠️ {len(newly_error)} IDCC qui marchaient avant et sont MAINTENANT en erreur "
                      f"(possible changement côté Légifrance à vérifier) : {', '.join(sorted(newly_error)[:20])}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="audits")
    args = ap.parse_args()

    changed = get_changed_files()
    total = len(changed["ajoutes"]) + len(changed["modifies"]) + len(changed["supprimes"])

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    lines = [
        f"# Audit des changements — run du {date_str} ({now.strftime('%H:%M UTC')})",
        "",
        f"**{total} fichier(s) touché(s)** par ce run "
        f"({len(changed['ajoutes'])} ajoutés, {len(changed['modifies'])} modifiés, {len(changed['supprimes'])} supprimés).",
        "",
    ]

    if total == 0:
        lines.append("Aucun changement détecté par rapport au run précédent — tout est déjà à jour.")
    else:
        # _summary.json d'abord (vue d'ensemble)
        summary_changes = []
        for p in changed["modifies"] + changed["ajoutes"]:
            if p.endswith("_summary.json") and "/ccn/" in p:
                s = describe_summary_change(p)
                if s:
                    summary_changes.extend(s)
        if summary_changes:
            lines.append("## Vue d'ensemble (statuts CCN)")
            lines.extend(f"- {s}" for s in summary_changes)
            lines.append("")

        # CCN individuelles
        ccn_changes = [p for p in changed["modifies"] + changed["ajoutes"]
                       if "/ccn/" in p and p.endswith(".json") and "_summary" not in p and "_debug_search" not in p]
        if ccn_changes:
            lines.append(f"## Conventions collectives modifiées ou ajoutées ({len(ccn_changes)})")
            for p in sorted(ccn_changes):
                lines.append(f"- {describe_ccn_change(p)}")
            lines.append("")

        # Code du travail / sécu / jurisprudence -- juste la liste, moins de detail utile a resumer
        categorized = set()
        for folder, label in [("code-travail", "Code du travail"), ("code-secu", "Code de la sécurité sociale"),
                               ("jurisprudence", "Jurisprudence")]:
            others = [p for p in changed["modifies"] + changed["ajoutes"] if f"/{folder}/" in p and p.endswith(".json")]
            if others:
                lines.append(f"## {label} ({len(others)} article(s)/décision(s))")
                for p in sorted(others)[:30]:
                    tag = "nouveau" if p in changed["ajoutes"] else "modifié"
                    lines.append(f"- {p.split('/')[-1].replace('.json','')} ({tag})")
                if len(others) > 30:
                    lines.append(f"- ... et {len(others)-30} de plus")
                lines.append("")
                categorized.update(others)

        # Fourre-tout : tout ce qui a changé mais ne rentre dans aucune catégorie ci-dessus
        # (ex: all_articles_code_travail.txt, idcc_list_complet.txt -- fichiers racine
        # produits par les options "lister-tous-..."). Sans ça, ces fichiers étaient comptés
        # dans le total mais jamais nommés, ce qui a rendu un vrai bug difficile à diagnostiquer.
        categorized.update(ccn_changes)
        non_categorises = [p for p in changed["modifies"] + changed["ajoutes"] if p not in categorized]
        if non_categorises:
            lines.append(f"## Autres fichiers ({len(non_categorises)})")
            for p in sorted(non_categorises):
                tag = "nouveau" if p in changed["ajoutes"] else "modifié"
                lines.append(f"- {p} ({tag})")
            lines.append("")

        if changed["supprimes"]:
            lines.append(f"## Fichiers supprimés ({len(changed['supprimes'])})")
            for p in sorted(changed["supprimes"])[:30]:
                lines.append(f"- {p}")
            lines.append("")

    import os
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, f"{date_str}.md")
    # si plusieurs runs le même jour, ne pas ecraser -- ajouter un suffixe horaire
    if os.path.exists(out_path):
        out_path = os.path.join(args.out, f"{date_str}-{now.strftime('%H%M')}.md")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # resume court pour l'index (1ere ligne utile apres le titre, ou "aucun changement")
    if total == 0:
        resume = "Aucun changement"
    else:
        resume = f"{total} fichier(s) touché(s)"
        if changed["ajoutes"]:
            resume += f", {len(changed['ajoutes'])} nouveau(x)"

    index_path = os.path.join(args.out, "index.json")
    try:
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        index = []
    index.insert(0, {
        "fichier": os.path.basename(out_path),
        "date": date_str,
        "heure": now.strftime("%H:%M UTC"),
        "resume": resume,
        "total_changements": total,
    })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    print(f"Rapport d'audit écrit dans {out_path} ({total} changement(s))")
    print(f"Index mis à jour dans {index_path} ({len(index)} rapport(s) au total)")


if __name__ == "__main__":
    main()
