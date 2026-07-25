# Correctif — délai de 3-4 s avant l'affichage d'un article

Un seul fichier : `index.html`, dépôt **droit**.

---

## La cause

Au clic sur un lien de l'application, `monlegitexte` charge **quatre fichiers en
série** avant même de commencer à demander l'article visé :

```
manifest.json → search-index.json → ccn-liste.json → search-trends.json → (enfin) l'article
```

Le deep-link (`?idcc=…`, `?art=…`) était câblé dans le `.then()` de cette chaîne : il
attendait la fin des quatre téléchargements avant de démarrer le sien.

Or ces quatre fichiers ne servent **qu'aux listes de navigation** — invisibles derrière
le panneau qui s'ouvre. `openDetail()`, qui affiche l'article, fait son propre appel
réseau et ne dépend d'aucun des quatre : vérifié, `INDEX`, `SEARCH`, `CCN_LISTE` et
`TRENDS` n'apparaissent nulle part dans son code.

## Le correctif

Le deep-link est sorti de la chaîne et démarre **avant** `loadAll()`, en parallèle :

```js
// Avant : loadAll().then(() => deep-link)     — 5 appels en série
// Après : deep-link ; loadAll()                — 2 chaînes en parallèle
```

L'article s'affiche dès que sa propre requête répond, sans attendre les quatre autres.
`loadAll()` continue en arrière-plan, pour que la navigation (liste, recherche, filtres)
soit prête si l'utilisateur revient à la liste.

## Un piège vérifié avant de conclure

Mon premier essai avait seulement **documenté** le problème sans le résoudre : le code
restait physiquement à l'intérieur du `.then()`, malgré le commentaire annonçant le
contraire. Deuxième passe : le bloc est réellement sorti de la chaîne de promesses.

Vérifié aussi que le déplacement ne casse rien : tous les éléments DOM utilisés
(`scrim`, `panel`, `d-num`, `d-title`…) sont définis plus haut dans le HTML, et ce script
est le dernier avant `</body>` — donc déjà présents dans le document au moment de
l'exécution, qu'elle soit immédiate ou dans un `.then()`.

## Gain simulé

Une simulation avec des latences réseau illustratives (les fichiers réels ne sont pas
mesurables ici, générés par le workflow et non versionnés) :

| | Délai |
|---|---|
| Avant | ~1200 ms (4 appels en série + article) |
| Après | ~210 ms (article seul) |

Le principe ne dépend pas des valeurs exactes : la fiche s'affiche désormais dès que
**son** appel répond, quel que soit le temps que prennent les quatre autres — c'est
l'écart entre requêtes séquentielles et parallèles qui est éliminé, pas une latence
particulière.

## À vérifier après déploiement

Clique sur un article ou une convention depuis l'application. La fiche doit s'ouvrir
sans délai perceptible, la navigation (recherche, filtres, liste) restant utilisable
une fraction de seconde après.
