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
    ap.add_argument("--auto-incorporer", action="store_true",
                    help="Ajoute directement les nouveautés à la liste suivie, au lieu "
                         "de seulement les signaler. À n'activer que si l'univers vient "
                         "d'une source fiable (référentiel DARES), pas d'un scraping "
                         "exploratoire.")
    ap.add_argument("--fusions",
                    help="CSV 'ancien_idcc,nouvel_idcc' (produit par dares_to_univers.py). "
                         "Permet de distinguer une convention FUSIONNÉE d'une vraie "
                         "disparition : sans lui, les 1144 fusions officielles "
                         "ressortiraient comme autant de fausses alertes.")
    args = ap.parse_args()

    if not os.path.exists(args.univers):
        print(f"{args.univers} n'existe pas encore -- lance d'abord le run 'lister-tous-...' correspondant. Rien à comparer cette semaine.")
        return

    with open(args.suivi, encoding="utf-8") as f:
        suivi = set(l.strip() for l in f if l.strip())
    with open(args.univers, encoding="utf-8") as f:
        univers = set(l.strip() for l in f if l.strip())

    # Garde-fou : un univers vide ou anormalement petit signifie que le run de
    # découverte a échoué (quota API, panne Légifrance, réponse 500…), PAS que
    # le droit a disparu. Sans cette vérification, un fichier vide fait passer
    # la totalité de la liste suivie en "disparus" et déclenche une fausse
    # alerte massive dans l'onglet "Mises à jour".
    if not univers:
        print(f"{args.univers} est VIDE -- le run de découverte n'a rien produit. "
              f"On ne signale rien : sans univers de référence, toute comparaison "
              f"ferait passer les {len(suivi)} {args.label} suivis pour disparus.")
        return
    if suivi and len(univers) < len(suivi) / 2:
        print(f"{args.univers} ne contient que {len(univers)} entrées pour "
              f"{len(suivi)} {args.label} suivis -- univers manifestement incomplet, "
              f"probable échec partiel du run de découverte. Comparaison abandonnée.")
        return

    nouveaux = sorted(univers - suivi)
    disparus = sorted(suivi - univers)

    # Une entrée absente de l'univers n'a pas forcément disparu : le plus souvent
    # elle a FUSIONNÉ dans une autre convention. DARES fournit la correspondance,
    # ce qui transforme une alerte inquiétante en information utile.
    fusions = {}
    if args.fusions and os.path.exists(args.fusions):
        with open(args.fusions, encoding="utf-8") as f:
            for ligne in f:
                bouts = ligne.strip().split(",")
                if len(bouts) == 2 and bouts[0].isdigit() and bouts[1].isdigit():
                    fusions[bouts[0]] = bouts[1]
    fusionnes = [d for d in disparus if d in fusions]
    disparus  = [d for d in disparus if d not in fusions]

    # Incorporation automatique : les nouveautés rejoignent la liste suivie, donc
    # le run les récupère dans la foulée (pull_ccn.py --only-missing). Les garde-fous
    # ci-dessus protègent l'opération : on n'arrive ici que si l'univers est
    # non vide et de taille plausible.
    #
    # Les "disparus" ne sont JAMAIS retirés automatiquement : une convention peut
    # disparaître de l'univers parce qu'elle a fusionné, et sa fiche garde alors
    # une valeur pour l'utilisateur encore couvert par l'ancien texte. Cette
    # décision reste manuelle.
    if args.auto_incorporer and nouveaux:
        with open(args.suivi, encoding="utf-8") as f:
            lignes = [l.rstrip("\n") for l in f]
        while lignes and not lignes[-1].strip():
            lignes.pop()
        lignes.extend(str(n) for n in nouveaux)
        with open(args.suivi, "w", encoding="utf-8") as f:
            f.write("\n".join(lignes) + "\n")
        print(f"{len(nouveaux)} {args.label} ajouté(s) automatiquement à {args.suivi} "
              f"({len(suivi)} -> {len(suivi) + len(nouveaux)}). Ils seront récupérés par "
              f"la passe --only-missing de ce run.")

    print(f"{args.label} suivis: {len(suivi)} | univers connu: {len(univers)} | "
          f"nouveaux: {len(nouveaux)} | absents de l'univers: {len(disparus)}")

    if not nouveaux and not disparus and not fusionnes:
        return

    os.makedirs(args.audits_dir, exist_ok=True)
    date_str = datetime.date.today().isoformat()
    lines = [f"# Fonds à incorporer — {args.label} — {date_str}", ""]
    if nouveaux:
        pct = round(100 * len(suivi) / len(univers)) if univers else 0
        lines.append(f"**Ce n'est pas un changement du droit.** Ce sont des {args.label} qui "
                     f"existent chez Légifrance mais que le fonds ne suit pas encore.")
        lines.append("")
        lines.append(f"Couverture actuelle : {len(suivi)} suivis sur {len(univers)} "
                     f"existants ({pct} %). Il reste {len(nouveaux)} à incorporer.")
        lines.append("")
        lines.append(f"## {len(nouveaux)} {args.label} pas encore suivi(s)")
        lines.append("")
        lines.append("Pas ajoutés automatiquement à " + args.suivi + " -- à valider avant d'incorporer :")
        for n in nouveaux[:100]:
            lines.append(f"- {n}")
        if len(nouveaux) > 100:
            lines.append(f"- ... et {len(nouveaux)-100} de plus (voir {args.univers} pour la liste complète)")
        lines.append("")
    if fusionnes:
        lines.append(f"## {len(fusionnes)} {args.label} fusionné(s) dans une autre convention")
        lines.append("")
        lines.append("Ce ne sont pas des disparitions : DARES indique la convention repreneuse. "
                     "Les fiches restent utiles (un salarié peut encore relever de l'ancien texte), "
                     "mais c'est la convention repreneuse qui fait foi aujourd'hui.")
        lines.append("")
        for d in fusionnes[:60]:
            lines.append(f"- {d} → {fusions[d]}")
        if len(fusionnes) > 60:
            lines.append(f"- ... et {len(fusionnes)-60} de plus (voir {args.fusions})")
        lines.append("")
    if disparus:
        lines.append(f"## ⚠️ {len(disparus)} {args.label} suivi(s) mais absent(s) du dernier univers connu")
        lines.append("(peut vouloir dire : retiré de Légifrance, ou simplement pas retrouvé par la recherche large -- à vérifier avant de retirer quoi que ce soit)")
        lines.append("")
        for n in disparus[:50]:
            lines.append(f"- {n}")
        if len(disparus) > 50:
            lines.append(f"- ... et {len(disparus)-50} de plus")
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
    if disparus:
        resume_parts.append(f"⚠️ {len(disparus)} disparu(s) à vérifier")
    if fusionnes:
        resume_parts.append(f"{len(fusionnes)} fusionné(s)")
    if nouveaux:
        resume_parts.append(f"{len(nouveaux)} {args.label} à incorporer")
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
        "resume": "Fonds " + args.label + " : " + ", ".join(resume_parts),
        # Le badge de l'onglet affiche cette valeur ("N chgt", ou "RAS" si 0).
        # Seuls les "disparus" méritent une lecture : un élément suivi qui n'est
        # plus retrouvé peut signaler une abrogation. Les "nouveaux" ne sont que
        # l'arriéré du fonds — les compter ici afficherait "10634 chgt" pour un
        # simple retard de couverture, et noierait les vraies alertes.
        "total_changements": len(disparus),
        "a_incorporer": len(nouveaux),
        "fusionnes": len(fusionnes),
        "couverture": f"{len(suivi)}/{len(univers)}",
    })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
