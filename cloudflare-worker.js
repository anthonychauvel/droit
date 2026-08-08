/**
 * Worker Cloudflare — façade pour l'application "Fonds Droit".
 *
 * Rôle : servir l'appli (index.html + données output/… + audits/…) sous une
 * adresse Cloudflare neutre (ex. https://droit.<ton-sous-domaine>.workers.dev/),
 * en allant chercher les fichiers dans ton dépôt GitHub CÔTÉ SERVEUR. Le
 * visiteur ne voit donc jamais l'adresse GitHub : le nom du dépôt (et ton nom)
 * reste masqué, et toute la bande passante passe par le cache de Cloudflare.
 *
 * ── CE QU'IL FAUT RÉGLER (une seule ligne) ──
 * Mets ci-dessous l'adresse "raw" de ton dépôt, SANS slash final.
 * Forme :  https://raw.githubusercontent.com/<COMPTE>/<DEPOT>/<BRANCHE>
 * Ex.   :  https://raw.githubusercontent.com/anthonychauvel/droit/main
 * ⚠ Vérifie la BRANCHE : "main" ou "master" selon ton dépôt.
 * (Cette valeur reste sur le serveur Cloudflare, elle n'est jamais envoyée au
 *  visiteur — c'est ça qui masque ton nom.)
 */
const ORIGIN = "https://raw.githubusercontent.com/anthonychauvel/droit/main";

/* Gros index servis en brotli si le navigateur l'accepte et si le .br existe.
 * Le workflow génère output/<nom>.json.br (voir scripts/compress_index.py).
 * Transfert mobile ~10x plus léger (159 Mo -> 16,5 Mo mesuré). Repli automatique
 * sur le JSON brut si le .br n'a pas encore été généré : rien ne casse. */
const COMPRESSIBLE = /\/(search-index|clauses-index|manifest|classification-source)\.json$/;

/* Durées de cache au bord Cloudflare (en secondes). À ajuster si besoin. */
const TTL_INDEX = 300;      // manifest / index / audits : 5 min (fraîcheur des mises à jour)
const TTL_FILE  = 3600;     // fiches d'articles / décisions / CCN : 1 h (elles changent rarement)

const MIME = {
  html: "text/html; charset=utf-8",
  json: "application/json; charset=utf-8",
  js:   "text/javascript; charset=utf-8",
  css:  "text/css; charset=utf-8",
  svg:  "image/svg+xml",
  md:   "text/markdown; charset=utf-8",
  txt:  "text/plain; charset=utf-8",
  png:  "image/png",
  jpg:  "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  ico:  "image/x-icon",
};

export default {
  async fetch(request, env, ctx) {
    // Seules les lectures sont autorisées
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Méthode non autorisée", { status: 405 });
    }

    const url = new URL(request.url);
    let path = decodeURIComponent(url.pathname);
    if (path === "/" || path === "") path = "/index.html";

    // robots.txt servi directement par le worker (pas depuis le dépôt) : ainsi
    // il ne peut ni manquer ni être oublié lors d'un déploiement.
    //
    // Note importante : on autorise volontairement le crawl de la racine. Un
    // "Disallow: /" empêcherait les moteurs de LIRE l'en-tête X-Robots-Tag
    // ci-dessous, et l'URL pourrait alors rester affichée en résultat, sans
    // contenu. Pour sortir vraiment de l'index il faut être crawlable ET
    // renvoyer noindex. En revanche on bloque les répertoires de données, qui
    // sont volumineux et n'ont aucune raison d'être parcourus.
    if (path === "/robots.txt") {
      return new Response(
        "# MonLegiTexte est réservé aux utilisateurs de l'application SimulHeures.\n" +
        "# Le contenu ne doit pas apparaître dans les moteurs de recherche.\n" +
        "User-agent: *\n" +
        "Allow: /\n" +
        "Disallow: /output/\n" +
        "Disallow: /audits/\n",
        { status: 200, headers: {
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "public, max-age=3600",
            "X-Robots-Tag": "noindex, nofollow",
        } });
    }

    // Petite sécurité : pas de remontée de dossier
    if (path.includes("..")) return new Response("Requête invalide", { status: 400 });

    const cache = caches.default;

    // 0) Voie brotli pour les gros index : si le client accepte "br" ET qu'un
    //    fichier .br existe côté dépôt, on le sert tel quel avec Content-Encoding:
    //    br (le navigateur décompresse de façon transparente — l'appli continue
    //    d'appeler fetch('output/search-index.json'), rien à changer côté front).
    //    Clé de cache distincte (?__enc=br) pour ne jamais servir des octets
    //    compressés à un client qui ne les attend pas.
    const acceptsBr = (request.headers.get("Accept-Encoding") || "").includes("br");
    if (acceptsBr && COMPRESSIBLE.test(path)) {
      const brKey = new Request(url.origin + path + "?__enc=br");
      const brHit = await cache.match(brKey);
      if (brHit) return brHit;

      const upBr = await fetch(ORIGIN + path + ".br", {
        cf: { cacheTtl: 0, cacheEverything: false },
        headers: { "User-Agent": "cloudflare-worker-droit" },
      });
      if (upBr.ok) {
        const h = new Headers();
        h.set("Content-Type", "application/json; charset=utf-8");
        h.set("Content-Encoding", "br");
        h.set("Vary", "Accept-Encoding");
        h.set("Cache-Control", `public, max-age=${TTL_INDEX}`);
        h.set("X-Content-Type-Options", "nosniff");
        h.set("X-Robots-Tag", "noindex, nofollow");
        h.set("Access-Control-Allow-Origin", "*");
        const respBr = new Response(upBr.body, { status: 200, headers: h });
        ctx.waitUntil(cache.put(brKey, respBr.clone()));
        return respBr;
      }
      // .br absent (pas encore généré par un run) : on retombe sur le brut ci-dessous.
    }

    // 1) Cache au bord : si on l'a déjà, on répond sans toucher GitHub
    const cached = await cache.match(request);
    if (cached) return cached;

    // 2) Sinon on va chercher le fichier dans le dépôt (côté serveur)
    const upstream = await fetch(ORIGIN + path, {
      // on gère nous-mêmes le cache ci-dessous
      cf: { cacheTtl: 0, cacheEverything: false },
      headers: { "User-Agent": "cloudflare-worker-droit" },
    });

    if (!upstream.ok) {
      // 404, etc. : on renvoie tel quel et on NE met PAS en cache (pour qu'un
      // fichier ajouté plus tard soit bien servi dès qu'il existe).
      return new Response(upstream.status === 404 ? "Introuvable" : "Erreur amont",
                          { status: upstream.status });
    }

    // 3) On reconstruit la réponse avec le bon type + une durée de cache
    const ext = (path.split(".").pop() || "").toLowerCase();
    const headers = new Headers();
    headers.set("Content-Type", MIME[ext] || "text/plain; charset=utf-8");

    const isIndex =
      /\/(manifest|search-index|ccn-liste|classification-source)\.json$/.test(path) ||
      path.startsWith("/audits/") ||
      path === "/index.html";
    const ttl = isIndex ? TTL_INDEX : TTL_FILE;
    headers.set("Cache-Control", `public, max-age=${ttl}`);
    headers.set("X-Content-Type-Options", "nosniff");
    // Interdit l'indexation de TOUT ce que sert le worker, y compris les .json
    // (une balise <meta> ne couvrirait que le HTML). C'est le signal qui sort
    // réellement les pages de l'index Google.
    headers.set("X-Robots-Tag", "noindex, nofollow");
    // (même origine pour l'appli, mais on autorise large au cas où)
    headers.set("Access-Control-Allow-Origin", "*");

    const response = new Response(upstream.body, { status: 200, headers });

    // 4) On garde une copie au bord Cloudflare pour les prochains visiteurs
    ctx.waitUntil(cache.put(request, response.clone()));
    return response;
  },
};
