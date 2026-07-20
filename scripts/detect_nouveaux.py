#!/usr/bin/env python3
"""
Compare une liste suivie (ex: idcc_list.txt) à l'univers complet obtenu par
un script "lister-tous-..." (ex: idcc_list_complet.txt), et signale ce qui
est nouveau -- SANS modifier automatiquement la liste suivie.

Volontairement prudent : list_all_ccn.py reste exploratoire (cf. son
propre avertissement), donc on préfère signaler et laisser Anthony décider
plutôt que d'empoisonner idcc_list.txt avec un faux résultat.

Écrit un rapport dans le dossier audits/ (repris par lecteur.html comme
n'importe quel autre rapport) si des nouveautés sont trouvées.

Usage:
    python3 detect_nouveaux.py --suivi idcc_list.txt --univers idcc_list_complet.txt --label "IDCC"
"""
import argparse
import datetime
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suivi", required=True, help="Liste actuellement suivie")
    ap.add_argument("--univers", required=True, help="Liste complète de référence (sortie d'un script lister-tous-...)")
    ap.add_argument("--label", default="élément", help="Nom pour l'affichage (ex: IDCC, article)")
    ap.add_argument("--audits-dir", default="audits")
    args = ap.parse_args()

    if not os.path.exists(args.univers):
        print(f"{args.univers} n'existe pas encore -- lance d'abord le run 'lister-tous-...' correspondant. Rien à comparer cette semaine.")
        return

    with open(args.suivi, encoding="utf-8") as f:
        suivi = set(l.strip() for l in f if l.strip())
    with open(args.univers, encoding="utf-8") as f:
        univers = set(l.strip() for l in f if l.strip())

    nouveaux = sorted(univers - suivi)
    disparus = sorted(suivi - univers)

    print(f"{args.label} suivis: {len(suivi)} | univers connu: {len(univers)} | "
          f"nouveaux: {len(nouveaux)} | absents de l'univers: {len(disparus)}")

    if not nouveaux and not disparus:
        return

    os.makedirs(args.audits_dir, exist_ok=True)
    date_str = datetime.date.today().isoformat()
    lines = [f"# Nouveautés détectées — {args.label} — {date_str}", ""]
    if nouveaux:
        lines.append(f"## {len(nouveaux)} nouveau(x) {args.label} pas encore suivi(s)")
        lines.append("")
        lines.append("Pas ajoutés automatiquement à " + args.suivi + " -- à valider avant d'incorporer :")
        for n in nouveaux[:100]:
            lines.append(f"- {n}")
        if len(nouveaux) > 100:
            lines.append(f"- ... et {len(nouveaux)-100} de plus (voir {args.univers} pour la liste complète)")
        lines.append("")
    if disparus:
        lines.append(f"## {len(disparus)} {args.label} suivi(s) mais absent(s) du dernier univers connu")
        lines.append("(peut vouloir dire : retiré de Légifrance, ou simplement pas retrouvé par la recherche large -- à vérifier avant de retirer quoi que ce soit)")
        lines.append("")
        for n in disparus[:50]:
            lines.append(f"- {n}")
        lines.append("")

    out_path = os.path.join(args.audits_dir, f"nouveautes-{args.label.lower()}-{date_str}.md")
    if os.path.exists(out_path):
        out_path = out_path.replace(".md", f"-{datetime.datetime.now().strftime('%H%M')}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Rapport écrit dans {out_path}")

    # Inscrit ce rapport dans le même index.json que generate_audit_report.py,
    # sinon il est bien écrit mais invisible dans l'onglet "Mises à jour" du lecteur.
    now = datetime.datetime.now(datetime.timezone.utc)
    resume_parts = []
    if nouveaux:
        resume_parts.append(f"{len(nouveaux)} nouveau(x)")
    if disparus:
        resume_parts.append(f"{len(disparus)} disparu(s)")
    index_path = os.path.join(args.audits_dir, "index.json")
    try:
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        index = []
    index.insert(0, {
        "fichier": os.path.basename(out_path),
        "date": date_str,
        "heure": now.strftime("%H:%M UTC"),
        "resume": f"Nouveautés {args.label} : " + ", ".join(resume_parts),
        "total_changements": len(nouveaux) + len(disparus),
    })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
