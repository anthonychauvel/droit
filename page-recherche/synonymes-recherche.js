/**
 * MOTEUR DE RECHERCHE AVEC SYNONYMES — pour les utilisateurs finaux de l'app HS
 * =============================================================================
 * Version : 1.0.0 — 20 juillet 2026
 *
 * Objectif : un utilisateur ne connaît pas son numéro d'IDCC, ne va pas taper
 * "L3121-36", et décrit sa situation en langage courant ("je suis coiffeuse",
 * "mon patron", "heures supp"). Ce moteur fait le pont entre ce langage
 * courant et les données réelles (CCN_API, glossaires, articles).
 *
 * Construit sur la liste des 316 CCN vérifiées de conventions-collectives.js
 * v5.6.12 (audit croisé 6 sources, session des 17-20/07/2026).
 *
 * 3 couches, dans l'ordre où rechercheIntelligente() les utilise :
 *   1. PROFESSIONS_VERS_IDCC : "je suis X" -> IDCC directement (le cas le
 *      plus fréquent et le plus fiable, une correspondance quasi individuelle)
 *   2. TERMES_SYNONYMES : normalise le vocabulaire courant vers les termes
 *      utilisés dans les données (glossaire, notes CCN)
 *   3. Recherche floue sur le nom/secteur CCN en dernier recours
 *
 * Usage typique (calc-engine / views) :
 *   const resultats = window.M_RechercheSynonymes.rechercheIntelligente(
 *     "je travaille dans un salon de coiffure", CCN_API.CCN_ALIASES
 *   );
 *   // -> [{idcc: 2596, nom: "Coiffure entreprises", score: 100, via: "profession"}]
 */
(function (window) {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════════
  // 1. PROFESSIONS -> IDCC
  // Clé : terme de recherche en langage courant (déjà normalisé : minuscule,
  // sans accent -- voir normaliser() plus bas, appliqué aussi aux clés au
  // chargement). Valeur : liste d'IDCC candidats, du plus probable au moins
  // probable. La plupart des métiers ont UN SEUL IDCC très probable ; certains
  // (ex: "vendeur") sont trop génériques et renvoient plusieurs pistes.
  // ═══════════════════════════════════════════════════════════════════════
  const PROFESSIONS_VERS_IDCC_RAW = {
    // --- Hôtellerie / restauration classique (HCR) ---
    'serveur': [1979], 'serveuse': [1979], 'cuisinier': [1979], 'cuisiniere': [1979],
    'chef de cuisine': [1979], 'second de cuisine': [1979], 'commis de cuisine': [1979],
    'plongeur': [1979], 'plongeur restaurant': [1979], 'chef de rang': [1979],
    'maitre d hotel': [1979], 'receptionniste hotel': [1979], 'femme de chambre': [1979],
    'valet de chambre': [1979], 'gouvernante hotel': [1979], 'barman': [1979], 'barmaid': [1979],
    'sommelier': [1979], 'veilleur de nuit': [1979], 'night auditor': [1979],
    'employe hotel': [1979], 'employe restaurant': [1979], 'travaille dans un hotel': [1979],
    'travaille dans un restaurant': [1979], 'traiteur': [1979], 'extra restauration': [1979],
    // --- Restauration rapide ---
    'restauration rapide': [1501], 'fast food': [1501], 'employe mcdo': [1501],
    'equipier': [1501], 'equipier polyvalent': [1501], 'employe polyvalent restauration rapide': [1501],
    'livreur restauration rapide': [1501],
    'chaine de cafeterias': [2060], 'employe cafeteria': [2060],
    'restauration collective': [1266], 'cantine scolaire': [1266], 'cuisine centrale': [1266],
    // --- Coiffure / esthétique ---
    'coiffeur': [2596], 'coiffeuse': [2596], 'apprenti coiffeur': [2596], 'salon de coiffure': [2596],
    'esthéticienne': [3032], 'estheticienne': [3032], 'esthetique': [3032], 'institut de beaute': [3032],
    'onglerie': [3032], 'prothesiste ongulaire': [3032], 'spa praticienne': [3032],
    // --- Commerce / vente ---
    'vendeur': [1517, 2216, 1505], 'vendeuse': [1517, 2216, 1505],
    'caissier': [2216, 1505], 'caissiere': [2216, 1505], 'hotesse de caisse': [2216],
    'supermarche': [2216], 'hypermarche': [2216], 'grande surface': [2216],
    'grand magasin': [2156], 'magasin populaire': [2156],
    'commerce de detail': [1517], 'boutique': [1517], 'vendeur textile': [1483],
    'vendeur habillement': [1483], 'vendeur pret a porter': [1483],
    'vendeur chaussures': [468], 'employe chaussures': [468],
    'vendeur bricolage': [1606], 'employe bricolage': [1606],
    'employe libre service': [2216, 1505], 'vendeur epicerie': [3237],
    'commerce alimentaire': [1505, 573, 3237],
    'e-commerce': [2198], 'vente a distance': [2198], 'preparateur de commandes e-commerce': [2198],
    'jardinerie': [1760], 'employe jardinerie': [1760], 'graineterie': [1760],
    'opticien': [1431], 'vendeur optique': [1431], 'monteur lunettier': [1431],
    'bijoutier': [3251], 'joaillier': [3251], 'horloger': [1487], 'vendeur bijouterie': [3251, 1487],
    'fleuriste': [1978], 'vendeur animalerie': [1978],
    'libraire': [3013], 'vendeur librairie': [3013],
    'vendeur sport': [1557], 'magasin de sport': [1557],
    // --- Bâtiment / travaux publics ---
    'macon': [1596, 1597], 'macon batiment': [1596, 1597], 'ouvrier batiment': [1596, 1597],
    'coffreur': [1596, 1597], 'couvreur': [1596, 1597], 'plombier batiment': [1596, 1597],
    'electricien batiment': [1596, 1597], 'peintre batiment': [1596, 1597], 'carreleur': [1596, 1597],
    'menuisier batiment': [1596, 1597], 'chef de chantier': [2609], 'conducteur de travaux': [2609, 3212],
    'ingenieur travaux publics': [3212], 'cadre batiment': [2420], 'architecte': [2332],
    'geometre': [2543], 'economiste de la construction': [3213], 'metreur': [3213],
    'ouvrier travaux publics': [1702], 'conducteur d engins tp': [1702],
    'etam batiment': [2609], 'etam travaux publics': [2614],
    // --- Métallurgie / industrie ---
    'metallurgie': [3248], 'usinage': [3248], 'ouvrier metallurgie': [3248],
    'chaudronnier': [3248], 'soudeur': [3248], 'technicien industriel': [3248],
    'ingenieur metallurgie': [3248], 'automobile industrie': [3248], 'aeronautique': [3248],
    'plasturgie': [292], 'plasturgiste': [292], 'chimie': [44], 'operateur chimie': [44],
    'industrie pharmaceutique': [176], 'production pharmaceutique': [176],
    'textile': [18], 'ouvrier textile': [18], 'industrie du bois': [3222, 158],
    'imprimerie': [184], 'imprimeur': [184], 'operateur imprimerie': [184],
    'papeterie industrie': [3238], 'verre industrie': [669], 'verrier': [669],
    'ceramique': [1558], 'meunerie': [1930], 'meunier': [1930],
    // --- Automobile ---
    'garage automobile': [1090], 'mecanicien automobile': [1090], 'mecanicien auto': [1090],
    'carrossier': [1090], 'controle technique': [1090], 'vendeur automobile': [1090],
    'concessionnaire automobile': [1090], 'expert automobile': [1951],
    // --- Transport ---
    'chauffeur routier': [16], 'conducteur routier': [16], 'chauffeur poids lourd': [16],
    'chauffeur livreur': [16], 'transporteur': [16], 'transport marchandises': [16],
    'chauffeur bus': [1424], 'conducteur bus': [1424], 'transport urbain': [1424],
    'chauffeur car': [1424], 'transport en commun': [1424],
    'taxi': [2219], 'chauffeur taxi': [2219], 'chauffeur vtc': [2219],
    'personnel navigant': [1944, 1612], 'hotesse de l air': [275], 'steward': [275],
    'agent aeroportuaire': [275], 'personnel au sol aeroport': [275],
    'marin': [2972, 3223], 'officier marine marchande': [3223], 'docker': [3017],
    'transport maritime': [2972, 3223], 'batelier': [5021], 'transport fluvial': [5021],
    // --- Santé / médico-social ---
    'infirmiere liberale': [1619], 'infirmier': [2264, 29], 'aide soignante': [2264, 29],
    'aide soignant': [2264, 29], 'clinique privee': [2264], 'hopital prive': [2264],
    'assistante dentaire': [1619], 'secretaire medicale': [1619, 1147],
    'cabinet medical': [1147], 'cabinet dentaire': [1619], 'dentiste employeur': [1619],
    'laboratoire analyses medicales': [959], 'technicien laboratoire medical': [959],
    'ehpad': [29, 2264], 'maison de retraite': [29, 2264], 'auxiliaire de vie': [2941, 3239],
    'aide a domicile': [2941], 'aide menagere': [2941, 3239], 'garde d enfants': [3239],
    'assistante maternelle': [3239], 'nounou': [3239], 'particulier employeur': [3239],
    'employe de maison': [3239],
    'educateur specialise': [413, 29], 'moniteur educateur': [413, 29],
    'foyer handicapes': [413], 'centre social': [1261], 'animateur social': [1261],
    'veterinaire cabinet': [1875], 'assistante veterinaire': [1875], 'clinique veterinaire': [1875],
    'pharmacien officine': [1996], 'preparateur en pharmacie': [1996], 'pharmacie officine': [1996],
    'prothesiste dentaire': [993],
    // --- Bureau / tertiaire / conseil ---
    'secretaire': [1486, 1517], 'assistante administrative': [1486],
    'developpeur informatique': [1486], 'ingenieur informatique': [1486], 'consultant informatique': [1486],
    'ssii': [1486], 'esn': [1486], 'bureau d etudes': [1486], 'ingenieur conseil': [1486],
    'comptable': [787], 'expert comptable': [787], 'cabinet comptable': [787],
    'assurance': [1672], 'agent d assurance': [2335], 'agence assurance': [2335],
    'courtier assurance': [2247], 'conseiller banque': [2120], 'banque': [2120, 3210],
    'avocat collaborateur': [3253], 'cabinet d avocats': [3253], 'assistante juridique': [3253],
    'notaire clerc': [2205], 'clerc de notaire': [2205], 'etude notariale': [2205],
    'huissier': [3250], 'commissaire de justice': [3250],
    'agent immobilier': [1527], 'syndic': [1527], 'gestionnaire immobilier': [1527],
    'agence immobiliere': [1527], 'promoteur immobilier': [1512],
    'publicite agence': [86], 'communication agence': [86],
    'journaliste': [1480], 'redacteur presse': [1480], 'pigiste': [1480],
    'edition livre': [2121], 'maison d edition': [2121],
    'recrutement cabinet': [2978], 'detective prive': [2978], 'enqueteur prive': [2978],
    // --- Agroalimentaire / artisanat alimentaire ---
    'boulanger': [843], 'boulangere': [843], 'boulangerie patisserie': [843],
    'patissier': [1267], 'patisserie artisanale': [1267], 'chocolatier': [1286], 'confiseur': [1286],
    'boucher': [3254], 'bouchere': [3254], 'boucherie': [3254], 'poissonnier': [3254, 1589],
    'charcutier': [953], 'charcuterie': [953], 'traiteur charcuterie': [953],
    'industrie laitiere': [112], 'fromagerie industrielle': [112],
    'brasseur': [1513], 'brasserie boissons': [1513],
    // --- Agriculture ---
    'agriculteur salarie': [7024], 'exploitation agricole': [7024], 'ouvrier agricole': [7024],
    'viticulture': [7005], 'vendanges': [7005], 'cave cooperative': [7005],
    'maraichage': [7024], 'horticulture': [7024], 'paysagiste': [7018], 'jardinier paysagiste': [7018],
    'elevage': [7024], 'aquaculture': [7010], 'conchyliculture': [7019], 'ostreiculteur': [7019],
    'pecheur': [5619], 'peche maritime': [5619],
    'cooperative agricole': [7028, 7002], 'msa': [7502],
    // --- Sécurité / propreté ---
    'agent de securite': [1351], 'gardiennage': [1351], 'vigile': [1351], 'maitre chien securite': [1351],
    'agent de nettoyage': [3043], 'femme de menage entreprise': [3043], 'agent d entretien': [3043],
    'proprete': [3043], 'nettoyage industriel': [3043],
    'gardien immeuble': [1043], 'concierge': [1043], 'gardienne d immeuble': [1043],
    // --- Culture / spectacle / sport ---
    'animateur centre de loisirs': [1518], 'animateur colonie': [1518], 'bafa employeur': [1518],
    'coach sportif': [2511], 'educateur sportif': [2511], 'salle de sport': [2511], 'club de sport': [2511],
    'comedien': [1285, 3097], 'acteur': [3097], 'technicien spectacle': [3090, 3252],
    'intermittent du spectacle': [3090], 'production audiovisuelle': [2642],
    'cinema salle': [1307], 'projectionniste': [1307], 'guichetier cinema': [1307],
    'musee': [1285], 'golf employe': [2021],
    // --- Nettoyage / pressing / autres services ---
    'pressing': [2002], 'blanchisserie': [2002], 'teinturerie': [2002],
    'pompes funebres': [759], 'agent funeraire': [759], 'marbrier funeraire': [759],
    'photographe': [3168], 'studio photo': [3168],
    'esthetique parfumerie': [3032, 3235], 'parfumerie selective': [3235],
    'telecommunications': [2148], 'operateur telecom': [2148],
    'centre d appel': [1486, 3127], 'services a la personne': [3127],
    // --- Interim / formation ---
    'agence interim': [1413, 2378], 'interimaire': [2378], 'travail temporaire': [1413, 2378],
    'organisme de formation': [1516], 'formateur': [1516],
  };

  // ═══════════════════════════════════════════════════════════════════════
  // 2. TERMES DU LANGAGE COURANT -> VOCABULAIRE DES DONNÉES
  // Sert à élargir la recherche texte libre (glossaire, notes CCN, noms de
  // secteur) avec les mots qu'un utilisateur tape naturellement.
  // ═══════════════════════════════════════════════════════════════════════
  const TERMES_SYNONYMES_RAW = {
    // Heures / temps de travail
    'heure sup': ['heures supplementaires'], 'heures supp': ['heures supplementaires'],
    'heure supp': ['heures supplementaires'], 'hs': ['heures supplementaires'],
    'heure comp': ['heures complementaires'], 'heures comp': ['heures complementaires'],
    'temps partiel': ['heures complementaires', 'contrat temps partiel'],
    'forfait jour': ['forfait jours'], 'au forfait': ['forfait jours', 'forfait heures'],
    'recup': ['repos compensateur', 'jour de recuperation'],
    'compteur heures': ['heures supplementaires', 'heures complementaires'],
    // Salaire / paie
    'fiche de paie': ['bulletin de salaire'], 'fiche de paye': ['bulletin de salaire'],
    'salaire minimum': ['minimum conventionnel', 'smic'], 'smic horaire': ['smic'],
    'treizieme mois': ['13e mois', 'prime annuelle'], '13eme mois': ['13e mois', 'prime annuelle'],
    'prime anciennete': ['prime d anciennete'],
    'net a payer': ['salaire net'], 'brut': ['salaire brut'],
    // Employeur / hierarchie
    'patron': ['employeur'], 'boss': ['employeur'], 'chef': ['employeur', 'superieur hierarchique'],
    'boite': ['entreprise'], 'boulot': ['travail', 'emploi'], 'taf': ['travail', 'emploi'],
    // Contrat / rupture
    'lettre de licenciement': ['notification de licenciement'],
    'rupture conventionnelle': ['rupture conventionnelle homologuee'],
    'demission': ['demission'], 'preavis': ['delai de preavis'],
    'periode d essai': ['periode d essai'], 'cdd': ['contrat a duree determinee'],
    'cdi': ['contrat a duree indeterminee'], 'fin de contrat': ['rupture du contrat de travail'],
    'indemnite de licenciement': ['indemnite legale de licenciement'],
    'chomage': ['allocation chomage', 'pole emploi'],
    // Congés
    'conges payes': ['conges payes'], 'cp': ['conges payes'],
    'arret maladie': ['arret de travail maladie'], 'arret de travail': ['arret maladie'],
    'conge maternite': ['conge maternite'], 'conge paternite': ['conge paternite'],
    'conge parental': ['conge parental d education'],
    'jour ferie': ['jours feries'], 'ferie': ['jour ferie'],
    'rtt': ['reduction du temps de travail', 'jour de rtt'],
    // Cadres / forfait
    'cadre dirigeant': ['cadre dirigeant', 'article L3111-2'],
    'cadre autonome': ['forfait jours'],
    'plafond jours': ['plafond forfait jours', '218 jours'],
    'rachat de jours': ['rachat de jours de repos', 'renonciation aux jours de repos'],
    // Divers fréquent
    'deconnexion': ['droit a la deconnexion'],
    'teletravail': ['travail a distance'],
    'accident du travail': ['accident du travail'], 'at': ['accident du travail'],
    'mutuelle': ['complementaire sante'], 'prevoyance': ['prevoyance collective'],
    'convention collective': ['ccn', 'idcc'],
    'harcelement': ['harcelement moral', 'harcelement sexuel'],
    'discrimination': ['discrimination au travail'],
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Normalisation : minuscule, sans accents, ponctuation réduite à des
  // espaces simples. Appliquée aux clés des dictionnaires ci-dessus (une
  // fois, au chargement) ET à chaque requête utilisateur.
  // ═══════════════════════════════════════════════════════════════════════
  function normaliser(s) {
    if (!s) return '';
    return s
      .toString()
      .toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '') // retire les accents
      .replace(/[^a-z0-9\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function normaliserCles(dictBrut) {
    const out = {};
    for (const cle in dictBrut) {
      out[normaliser(cle)] = dictBrut[cle];
    }
    return out;
  }

  const PROFESSIONS_VERS_IDCC = normaliserCles(PROFESSIONS_VERS_IDCC_RAW);
  const TERMES_SYNONYMES = normaliserCles(TERMES_SYNONYMES_RAW);

  // Distance de Levenshtein plafonnée -- tolère 1-2 fautes de frappe sur les
  // mots de 5+ lettres, sans faire exploser le coût sur des mots courts.
  function distanceLimitee(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    const dp = [];
    for (let i = 0; i <= a.length; i++) dp.push([i]);
    for (let j = 0; j <= b.length; j++) dp[0][j] = j;
    for (let i = 1; i <= a.length; i++) {
      for (let j = 1; j <= b.length; j++) {
        dp[i][j] = a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1]
          : 1 + Math.min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1]);
      }
    }
    return dp[a.length][b.length];
  }

  function motsProches(motRequete, motCible) {
    if (motRequete.length < 4 || motCible.length < 4) return motRequete === motCible;
    if (motRequete === motCible) return true;
    if (motCible.startsWith(motRequete) || motRequete.startsWith(motCible)) return true;
    if (motRequete.length >= 5 && motCible.length >= 5) {
      return distanceLimitee(motRequete, motCible, 1) <= 1;
    }
    return false;
  }

  /**
   * Recherche intelligente principale.
   * @param {string} query - texte tapé par l'utilisateur, brut
   * @param {Array} ccnData - CCN_API.CCN_ALIASES (ou équivalent {i,n,s})
   * @param {number} limite - nombre max de résultats (défaut 8)
   * @returns {Array<{idcc, nom, secteur, score, via}>}
   */
  function rechercheIntelligente(query, ccnData, limite) {
    limite = limite || 8;
    const q = normaliser(query);
    if (!q) return [];

    const resultats = new Map(); // idcc -> {idcc, nom, secteur, score, via}
    const ccnParId = {};
    (ccnData || []).forEach(function (c) { if (!(c.i in ccnParId)) ccnParId[c.i] = c; });

    function ajouter(idcc, score, via) {
      const ccn = ccnParId[idcc];
      if (!ccn) return;
      const existant = resultats.get(idcc);
      if (!existant || existant.score < score) {
        resultats.set(idcc, { idcc: idcc, nom: ccn.n, secteur: ccn.s, score: score, via: via });
      }
    }

    // --- Couche 1 : correspondance profession directe (la plus fiable) ---
    // Sous-couche a) substring exact (le plus rapide, priorité la plus haute)
    for (const cle in PROFESSIONS_VERS_IDCC) {
      if (q === cle || q.indexOf(cle) !== -1 || cle.indexOf(q) !== -1) {
        const score = q === cle ? 100 : 85;
        PROFESSIONS_VERS_IDCC[cle].forEach(function (idcc) { ajouter(idcc, score, 'profession'); });
      }
    }
    // Sous-couche b) tolérance aux fautes de frappe, mot à mot (ex: "coifeuse"
    // doit quand même retrouver "coiffeuse") -- seulement si a) n'a rien donné,
    // pour ne pas ralentir le cas courant qui marche du premier coup.
    if (resultats.size === 0) {
      const motsReq = q.split(' ');
      for (const cle in PROFESSIONS_VERS_IDCC) {
        const motsCle = cle.split(' ');
        const proche = motsReq.some(function (mr) {
          return motsCle.some(function (mc) { return mr.length >= 5 && motsProches(mr, mc); });
        });
        if (proche) {
          PROFESSIONS_VERS_IDCC[cle].forEach(function (idcc) { ajouter(idcc, 75, 'profession-approchee'); });
        }
      }
    }

    // --- Couche 2 : expansion par synonymes de termes, puis recherche des
    // termes étendus dans le nom/secteur de chaque CCN ---
    let termesElargis = [q];
    for (const cle in TERMES_SYNONYMES) {
      if (q.indexOf(cle) !== -1) {
        termesElargis = termesElargis.concat(TERMES_SYNONYMES[cle].map(normaliser));
      }
    }

    // --- Couche 3 : recherche floue sur nom + secteur de chaque CCN ---
    const motsRequete = q.split(' ').filter(function (m) { return m.length > 1; });
    (ccnData || []).forEach(function (ccn) {
      const texteCcn = normaliser(ccn.n + ' ' + (ccn.s || ''));
      const motsCcn = texteCcn.split(' ');

      termesElargis.forEach(function (terme) {
        if (texteCcn.indexOf(terme) !== -1) {
          ajouter(ccn.i, 70, 'texte');
        }
      });

      let motsTrouves = 0;
      motsRequete.forEach(function (mr) {
        if (motsCcn.some(function (mc) { return motsProches(mr, mc); })) motsTrouves++;
      });
      if (motsRequete.length > 0 && motsTrouves > 0) {
        const score = Math.round(50 * (motsTrouves / motsRequete.length));
        if (score > 20) ajouter(ccn.i, score, 'flou');
      }
    });

    const listeResultats = Array.from(resultats.values())
      .sort(function (a, b) { return b.score - a.score; })
      .slice(0, limite);

    // Si la recherche CCN ne donne rien de suffisamment confiant (un simple
    // chevauchement flou à faible score ne compte pas) MAIS que la requête
    // correspond à un terme connu (heures sup, RTT, licenciement...), le
    // signaler explicitement plutôt que de renvoyer du bruit sans rapport.
    const meilleurScore = listeResultats.length > 0 ? listeResultats[0].score : 0;
    if (meilleurScore < 50) {
      for (const cle in TERMES_SYNONYMES) {
        if (q.indexOf(cle) !== -1 || cle.indexOf(q) !== -1) {
          return [{
            idcc: null, nom: null, secteur: null, score: 0, via: 'terme-general',
            termeGeneral: TERMES_SYNONYMES[cle][0],
            suggestion: 'Ceci concerne une règle générale ("' + TERMES_SYNONYMES[cle][0] +
              '"), pas une convention collective précise -- cherchez ce terme dans le glossaire.',
          }];
        }
      }
    }

    return listeResultats;
  }

  window.M_RechercheSynonymes = {
    PROFESSIONS_VERS_IDCC: PROFESSIONS_VERS_IDCC,
    TERMES_SYNONYMES: TERMES_SYNONYMES,
    normaliser: normaliser,
    rechercheIntelligente: rechercheIntelligente,
  };
})(window);
