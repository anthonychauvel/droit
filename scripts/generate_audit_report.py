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


def _filled_ids(d):
    """ids des noeuds dont le texte intégral a déjà été récupéré par nos scripts
    de complément (fetch_*_details.py)."""
    ids = set()
    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("_texte_complet_recupere"):
            nid = node.get("id") or node.get("cid")
            if nid:
                ids.add(nid)
        for s in (node.get("sections") or []):
            walk(s)
    walk(d)
    return ids


def _nodes_by_id(d):
    """map id -> noeud, pour comparer le contenu d'un MÊME noeud entre deux versions."""
    out = {}
    def walk(node):
        if not isinstance(node, dict):
            return
        nid = node.get("id") or node.get("cid")
        if nid:
            out[nid] = node
        for s in (node.get("sections") or []):
            walk(s)
    walk(d)
    return out


def _node_fingerprint(node):
    """Signature du contenu propre d'un noeud (titre + texte de ses articles),
    insensible à l'ordre des champs JSON."""
    arts = []
    for a in (node.get("articles") or []):
        if isinstance(a, dict):
            arts.append((a.get("id") or a.get("cid") or "", a.get("content") or a.get("texte") or ""))
    return ((node.get("title") or node.get("titre") or "").strip(), tuple(sorted(arts)))


def describe_ccn_change(path):
    """Résumé lisible d'un changement sur un fichier output/ccn/<idcc>.json.

    Renvoie (categorie, texte) où categorie vaut :
      - "nouveau"     : IDCC récupéré pour la première fois
      - "reel"        : changement qui vient de Légifrance (titre, contenu d'une
                        clause déjà récupérée, section apparue/disparue) -> À LIRE
      - "rattrapage"  : nos propres scripts fetch_*_details.py ont simplement rempli
                        une clause qui était encore un stub vide. Le droit n'a pas
                        bougé, c'est notre fonds qui se complète. -> bruit

    Cette distinction existe parce que les scripts de complément ne remplissent
    qu'UN stub par CCN et par run (une fois rempli, le noeud n'est plus candidat,
    donc le run suivant prend le stub d'après). Sans ce tri, une CCN apparaissait
    "modifiée" à chaque run pendant des semaines et noyait les vrais changements.
    """
    try:
        with open(path, encoding="utf-8") as f:
            new_data = json.load(f)
    except Exception:
        return "reel", f"{path} : illisible après le run (à vérifier manuellement)"

    old_raw = get_old_content(path)
    idcc = path.split("/")[-1].replace(".json", "")

    if old_raw is None:
        titre = new_data.get("titre", "?")
        return "nouveau", f"IDCC {idcc} : NOUVEAU (récupéré pour la première fois) — \"{titre[:80]}\""

    try:
        old_data = json.loads(old_raw)
    except Exception:
        old_data = {}

    # --- 1) Ce qui relève de NOTRE rattrapage : stubs nouvellement remplis ---
    old_filled = _filled_ids(old_data)
    new_filled = _filled_ids(new_data)
    nouvellement_remplis = new_filled - old_filled

    # --- 2) Ce qui relève d'un VRAI changement côté Légifrance ---
    reels = []
    if old_data.get("titre") != new_data.get("titre"):
        reels.append(f"titre changé (\"{old_data.get('titre','?')[:50]}\" → \"{new_data.get('titre','?')[:50]}\")")

    # Contenu modifié sur une clause DÉJÀ récupérée auparavant : là, le texte a
    # vraiment bougé chez Légifrance (ce n'est pas un premier remplissage).
    old_nodes, new_nodes = _nodes_by_id(old_data), _nodes_by_id(new_data)
    modifies = [nid for nid in (old_filled & new_filled)
                if nid in old_nodes and nid in new_nodes
                and _node_fingerprint(old_nodes[nid]) != _node_fingerprint(new_nodes[nid])]
    if modifies:
        exemples = []
        for nid in modifies[:2]:
            t = (new_nodes[nid].get("title") or new_nodes[nid].get("titre") or nid)
            exemples.append(t[:60])
        reels.append(f"⚠️ {len(modifies)} clause(s) déjà récupérée(s) dont le TEXTE a changé : "
                     + ", ".join(exemples))

    added = _top_titles(new_data) - _top_titles(old_data)
    removed = _top_titles(old_data) - _top_titles(new_data)
    if added:
        reels.append("nouvelle(s) section(s) : " + ", ".join(sorted(t for t in added if t)[:3])[:120])
    if removed:
        reels.append("section(s) retirée(s) : " + ", ".join(sorted(t for t in removed if t)[:3])[:120])

    if reels:
        return "reel", f"IDCC {idcc} : " + " ; ".join(reels)

    if nouvellement_remplis:
        os_, oa_, oc_ = _walk_counts(old_data)
        ns_, na_, nc_ = _walk_counts(new_data)
        return "rattrapage", (f"IDCC {idcc} : +{len(nouvellement_remplis)} clause(s) remplie(s) "
                              f"(+{na_ - oa_} article(s), +{ns_ - os_} section(s))")

    return "rattrapage", (f"IDCC {idcc} : réécriture sans changement de structure "
                          f"(ré-enregistrement, pas une modif Légifrance)")


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

    # Compteurs par nature, remplis plus bas — servent au résumé de l'onglet
    # "Mises à jour" pour ne plus annoncer un gros chiffre alarmant alors que
    # l'essentiel n'est que du remplissage de notre propre fonds.
    par_cat = {"nouveau": [], "reel": [], "rattrapage": []}

    # L'en-tête est construit À LA FIN (voir plus bas) : il ne peut annoncer un
    # chiffre honnête qu'une fois les fichiers triés par nature.
    lines = []

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

        # CCN individuelles, triées : les vrais changements d'abord, le rattrapage
        # de notre propre fonds replié en fin de rapport (c'est du bruit récurrent).
        ccn_changes = [p for p in changed["modifies"] + changed["ajoutes"]
                       if "/ccn/" in p and p.endswith(".json") and "_summary" not in p and "_debug_search" not in p]
        if ccn_changes:
            for p in sorted(ccn_changes):
                cat, texte = describe_ccn_change(p)
                par_cat[cat].append(texte)

            if par_cat["reel"]:
                lines.append(f"## ⚠️ Changements réels du droit ({len(par_cat['reel'])}) — à lire")
                lines.append("")
                lines.extend(f"- {t}" for t in par_cat["reel"])
                lines.append("")
            if par_cat["nouveau"]:
                lines.append(f"## Nouvelles CCN récupérées ({len(par_cat['nouveau'])})")
                lines.append("")
                lines.extend(f"- {t}" for t in par_cat["nouveau"])
                lines.append("")
            if par_cat["rattrapage"]:
                lines.append(f"## Rattrapage du fonds ({len(par_cat['rattrapage'])}) — pas un changement du droit")
                lines.append("")
                lines.append("Nos scripts de complément remplissent une clause encore vide par CCN et par run. "
                              "Ces lignes vont se raréfier au fil des runs, jusqu'à disparaître quand tout sera rempli. "
                              "Rien à vérifier ici.")
                lines.append("")
                for t in par_cat["rattrapage"][:40]:
                    lines.append(f"- {t}")
                if len(par_cat["rattrapage"]) > 40:
                    lines.append(f"- ... et {len(par_cat['rattrapage']) - 40} autre(s), même nature")
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

    # En-tête, construit maintenant que le tri est fait : on annonce d'abord ce
    # qui demande une lecture, et le nombre brut de fichiers touchés ensuite,
    # explicitement rattaché au rattrapage quand c'est le cas.
    n_reel, n_nouveau, n_ratt = len(par_cat["reel"]), len(par_cat["nouveau"]), len(par_cat["rattrapage"])
    if total == 0:
        entete = "Aucun changement détecté par rapport au run précédent."
    elif n_reel or n_nouveau:
        bits = []
        if n_reel:
            bits.append(f"**⚠️ {n_reel} changement(s) réel(s) du droit**")
        if n_nouveau:
            bits.append(f"**{n_nouveau} nouvelle(s) CCN**")
        entete = " et ".join(bits) + "."
        if n_ratt:
            entete += f" Le reste ({n_ratt}) n'est que du rattrapage de notre fonds."
    elif n_ratt:
        entete = (f"**Aucun changement du droit.** Les {n_ratt} CCN listées plus bas sont du "
                  f"rattrapage : nos scripts remplissent des clauses encore vides. Rien à vérifier.")
    else:
        entete = f"{total} fichier(s) touché(s), aucun sur une convention collective."

    lines = [
        f"# Audit des changements — run du {date_str} ({now.strftime('%H:%M UTC')})",
        "",
        entete,
        "",
        f"<sub>Détail technique : {total} fichier(s) touché(s) — "
        f"{len(changed['ajoutes'])} ajoutés, {len(changed['modifies'])} modifiés, "
        f"{len(changed['supprimes'])} supprimés.</sub>",
        "",
    ] + lines

    import os
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, f"{date_str}.md")
    # si plusieurs runs le même jour, ne pas ecraser -- ajouter un suffixe horaire
    if os.path.exists(out_path):
        out_path = os.path.join(args.out, f"{date_str}-{now.strftime('%H%M')}.md")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # resume court pour l'index. On met en avant ce qui demande une lecture
    # (vrais changements, nouvelles CCN) et on relègue le rattrapage, sinon
    # l'onglet "Mises à jour" annonce des centaines de modifications qui n'en
    # sont pas et le vrai signal devient invisible.
    if total == 0:
        resume = "Aucun changement"
    else:
        parts = []
        if par_cat["reel"]:
            parts.append(f"⚠️ {len(par_cat['reel'])} changement(s) réel(s)")
        if par_cat["nouveau"]:
            parts.append(f"{len(par_cat['nouveau'])} nouvelle(s) CCN")
        if par_cat["rattrapage"]:
            parts.append(f"{len(par_cat['rattrapage'])} rattrapage(s)")
        if not parts:
            parts.append(f"{total} fichier(s) touché(s)")
        elif not par_cat["reel"]:
            parts.insert(0, "aucun changement du droit")
        resume = ", ".join(parts)

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
        # Le badge de l'onglet "Mises à jour" affiche cette valeur ("N chgt", ou
        # "RAS" si 0). Elle ne compte donc QUE ce qui demande une lecture : un run
        # de pur rattrapage affiche RAS, pas "285 chgt". Le total brut reste
        # disponible juste en dessous et en clair dans le rapport.
        "total_changements": n_reel + n_nouveau,
        "fichiers_touches": total,
        "rattrapages": n_ratt,
    })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    print(f"Rapport d'audit écrit dans {out_path} "
          f"({n_reel} réel(s), {n_nouveau} nouvelle(s), {n_ratt} rattrapage(s), {total} fichier(s) touché(s))")
    print(f"Index mis à jour dans {index_path} ({len(index)} rapport(s) au total)")


if __name__ == "__main__":
    main()
