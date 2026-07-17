# Mise à jour : recherche par mots-clés + veille auto

## 3 fichiers à remplacer/ajouter sur GitHub

1. `lecteur.html` → racine du repo (remplace l'ancien) — recherche
   maintenant par IDCC/nom ET par mot-clé (ex: "préavis", "astreinte")
2. `scripts/build_search_index.py` → nouveau fichier dans `scripts/`
3. `.github/workflows/aspirateur.yml` → remplace l'ancien — ajoute
   l'étape de construction d'index + le déclenchement auto du lundi

## Ce que ça change
Le workflow construit maintenant `output/search-index.json` à chaque run
(léger, ~10 Mo pour les 696 IDCC estimés, seulement les titres de section
qui matchent congés/salaire/durée du travail/rupture — pas le texte
intégral, pour rester utilisable sur mobile).

Le lecteur charge cet index et permet de chercher un mot-clé qui apparaît
dans un TITRE de section (pas dans le texte complet de l'article — ça,
il faut ouvrir la fiche pour le lire).
