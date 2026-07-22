# Mettre l'appli derrière Cloudflare (masquer le nom du dépôt + bande passante Cloudflare)

Objectif : les utilisateurs finaux ouvrent une adresse Cloudflare neutre (ex.
`https://droit.ton-sous-domaine.workers.dev/`). Ni ton nom, ni le dépôt GitHub
n'apparaissent, et toutes les données passent par le cache de Cloudflare.

## Pourquoi un Worker (et pas Cloudflare Pages)

Cloudflare **Pages** est limité à **20 000 fichiers** par site (offre gratuite).
Ton corpus complet (Code du travail ~20 000 articles + sécu ~10 000 + CCN…)
dépasse cette limite → Pages échouerait. Le **Worker** ci-joint n'a pas cette
limite : il va chercher chaque fichier dans le dépôt à la demande et le met en
cache au bord. C'est donc l'option qui passe à l'échelle.

## Pré-requis

1. Ton dépôt GitHub est **public** (le Worker lit les fichiers via l'adresse
   « raw »). Il l'est déjà.
2. `index.html` doit être la **version fournie ici** : elle ne contient plus
   aucune adresse GitHub (tout est en chemins relatifs), donc rien ne fuite
   dans le code source vu par le visiteur. Mets-la bien à jour sur le dépôt.

## Étapes (depuis Safari ou l'app, sans ordinateur)

1. Crée un compte gratuit sur **cloudflare.com** (si tu n'en as pas).
2. Dans le tableau de bord : **Workers & Pages** → **Create** →
   **Create Worker**.
3. Donne-lui un **nom neutre** (ex. `droit`, `fonds-droit`, `guide`). À la
   première création, Cloudflare te fait choisir un **sous-domaine**
   `xxxx.workers.dev` — choisis quelque chose de neutre aussi (pas ton nom).
   Clique **Deploy** (ça crée l'adresse `droit.xxxx.workers.dev`).
4. Clique **Edit code** (ou « Modifier le code »). **Efface** tout le contenu
   par défaut et **colle** le contenu du fichier `cloudflare-worker.js` fourni.
5. Dans ce code, **une seule ligne à vérifier**, tout en haut :
   ```
   const ORIGIN = "https://raw.githubusercontent.com/anthonychauvel/droit/main";
   ```
   - Laisse `anthonychauvel/droit` (c'est bien ton dépôt).
   - **Vérifie la branche** à la fin : `main` **ou** `master` selon ton dépôt.
     (En haut à gauche de ton dépôt GitHub, tu vois le nom de la branche.)
6. Clique **Deploy** (ou « Déployer »).
7. C'est en ligne : ouvre `https://droit.xxxx.workers.dev/`. C'est **cette
   adresse** que tu donnes aux utilisateurs finaux.

## (Facultatif) Ton propre nom de domaine

Si tu possèdes un domaine (ex. `mon-guide.fr`), tu peux l'associer au Worker :
dans le Worker → **Settings** → **Domains & Routes** → **Add** → **Custom
domain**. L'appli sera alors sur `https://droit.mon-guide.fr/` (encore plus
neutre). Cloudflare gère le certificat HTTPS automatiquement.

## Fraîcheur / cache

Le Worker met en cache au bord de Cloudflare :
- `manifest.json`, `search-index.json`, les rapports d'`audits/` : **5 min**
  (pour que les nouveautés d'un run apparaissent vite).
- Les fiches d'articles / décisions / CCN : **1 h** (elles changent rarement).

Tu peux ajuster ces deux durées en haut du fichier (`TTL_INDEX`, `TTL_FILE`).
Après un run GitHub, les nouveautés sont donc visibles sur l'adresse Cloudflare
au bout de quelques minutes, sans rien refaire.

## Ce qui reste caché

Le nom du dépôt (`ORIGIN`) est utilisé **uniquement côté serveur**, dans le
Worker : il n'est jamais envoyé au navigateur du visiteur. Combiné à l'`index.html`
sans adresse GitHub, ton nom n'apparaît nulle part côté public.
