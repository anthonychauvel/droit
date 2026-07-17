# Lecteur CCN & Code du travail

## Installation
Place `lecteur.html` à la RACINE du repo `droit` (au même niveau que `output/`,
`idcc_list.txt`, etc.) — il lit les fichiers via des chemins relatifs
(`output/ccn/...`, `output/code-travail/...`), donc il doit être dans le même repo.

Accessible ensuite à : `https://anthonychauvel.github.io/droit/lecteur.html`

## Fonctionnalités
- Recherche CCN par IDCC ou nom (utilise `output/ccn/_summary.json` comme index,
  rapide, pas besoin de charger les 300+ fichiers d'un coup)
- Recherche Code du travail par numéro d'article
- Fiche détail : affiche le contenu structuré (sections, articles)
- Export .xlsx par fiche, ou export complet (bouton "Exporter tout")
- Lecture seule — aucune modification possible depuis l'interface

## Veille automatique (aspirateur.yml mis à jour)
Le workflow se relance maintenant tout seul **chaque lundi à 6h** (en plus du
bouton manuel qui marche toujours pareil). Comme les résultats sont commités
dans Git, tout changement réel côté Légifrance (nouvel avenant, texte modifié,
IDCC qui redevient accessible) apparaît comme un **nouveau commit avec un
diff** — visible dans l'onglet "Commits" du repo, ou en activant les
notifications GitHub ("Watch" → "Custom" → "Pushes") pour être alerté par
email/notification à chaque changement réel.

Pas besoin de construire un système de surveillance séparé : Git fait déjà
le travail de "qu'est-ce qui a changé depuis la dernière fois".
