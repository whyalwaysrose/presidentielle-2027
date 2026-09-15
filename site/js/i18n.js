/* =========================================================================
   Bilingual strings.

   French is the default and the source of truth: this is a French election,
   the page opens in French, and the English is a translation rather than the
   other way round. Both are written by hand. The generated commentary is also
   written in both languages at build time - see src/presidentielle/commentary.py
   for why it is not translated in the browser.

   The chosen language is remembered, but every localStorage access is wrapped:
   getItem THROWS (SecurityError) when cookies are blocked or inside some
   in-app webviews, and an unguarded read at startup takes the whole script
   down with it, leaving a page that renders perfectly and responds to nothing.
   ========================================================================= */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'presidentielle2027.lang';

  var STRINGS = {
    fr: {
      'html.lang': 'fr',
      'title': 'Présidentielle 2027',
      'subtitle': 'Prévision bayésienne à partir des sondages publiés',
      'updated': 'Données au',
      'countdown': function (n) {
        return n + (n > 1 ? ' jours avant le premier tour' : ' jour avant le premier tour');
      },
      'scenario.model': 'Modèle complet',
      'scenario.conditional': 'Scénario : toutes les probabilités ci-dessous supposent ce bulletin précis. Ce ne sont pas des probabilités globales.',
      'scenario.ballot': 'Sur le bulletin :',
      'change.none': '',
      'a11y.skip': 'Aller au contenu',
      'a11y.scenarioNav': 'Choisir un scénario',
      'a11y.barsTitle': 'Probabilité par candidat',
      'a11y.intervalTitle': 'Score au premier tour, intervalle à 90 %',
      'a11y.trendTitle': 'Évolution du score estimé au premier tour',
      'a11y.trendTable': 'Score estimé le plus récent, par candidat',
      'a11y.candidate': 'Candidat',
      'a11y.probability': 'Probabilité',
      'a11y.low': 'Borne basse',
      'a11y.high': 'Borne haute',
      'a11y.latest': 'Dernière valeur',
      'a11y.pollsCaption': 'Dernières enquêtes publiées',
      'a11y.announceScenario': function (name) {
        return 'Scénario appliqué : ' + name + '. Les probabilités affichées supposent ce bulletin.';
      },
      'a11y.announceModel': 'Modèle complet rétabli. Les probabilités tiennent compte de l’incertitude sur le bulletin.',
      'record.title': 'Ce que vaut ce modèle',
      'record.note': 'Une probabilité est une affirmation sur des fréquences. Voici comment ce même modèle s’en est sorti lorsqu’on le rejoue sur l’élection de 2022, en ne lui donnant que ce qui était connu à la date indiquée.',
      'record.horizon': 'Avant le scrutin',
      'record.top2': 'Bon duo de second tour',
      'record.mae': 'Erreur médiane',
      'record.cov90': 'Couverture à 90 %',
      'record.pwinner': 'Probabilité donnée au vainqueur',
      'record.days': function (n) { return n + ' jours'; },
      'record.yes': 'oui',
      'record.no': 'non',
      'record.caveats': 'Ce qu’il faut en retenir',
      'record.circular': 'La couverture mesurée ci-dessus est en partie circulaire : les deux paramètres qui fixent la largeur des intervalles ont été calibrés sur ce même cycle 2022, faute d’un second. Ce n’est donc pas une validation indépendante. Ce qui ne l’est pas : le duo de tête, la simulation du bulletin et l’erreur médiane.',
      'record.vuln': 'La plus grande fragilité reste le « front républicain » : le report des voix vers un finaliste RN est estimé sur les reports mesurés de 2022, sur 317 duels des législatives de 2024 et sur les sondages de second tour, et rien ne garantit qu’il se comporte pareil en 2027. C’est l’hypothèse qui peut déplacer le chiffre principal de dix points.',
      'record.undercover': 'Les intervalles restent trop étroits : ce qui est annoncé à 90 % a contenu le résultat moins souvent que cela. À lire comme un minimum d’incertitude, pas un maximum.',
      'history.title': 'Évolution de la probabilité d’être élu',
      'history.note': 'Ce que cette page affichait à chaque état des sondages — un point par date de données, et non par exécution du modèle.',
      'history.modelChanged': 'Attention : le modèle a été modifié au cours de cette période. Les points antérieurs ont été produits par une version différente du calcul, ce n’est donc pas une comparaison à méthode constante.',
      'history.a11yTitle': 'Probabilité d’être élu, par candidat et par date',
      'history.date': 'Date',
      'hero.title': 'Qui sera élu ?',
      'hero.note': 'Probabilité de remporter le second tour, en tenant compte de l’incertitude sur la composition du bulletin.',
      'qualify.title': 'Qualification pour le second tour',
      'qualify.note': 'Se qualifier et gagner sont deux questions différentes. Un candidat peut dominer le premier tour et perdre le second.',
      'first.title': 'Premier tour',
      'first.note': 'Intervalle à 90 % du score au premier tour, sachant que le candidat se présente. La barre plus épaisse est l’intervalle à 50 %.',
      'duels.title': 'Seconds tours possibles',
      'duels.note': 'Chaque duel que la simulation a produit, avec sa probabilité de se tenir et son vainqueur.',
      'trend.title': 'Évolution',
      'trend.note': 'Score estimé au premier tour au fil du temps, pour le bulletin de référence.',
      'ballot.title': 'Qui sera sur le bulletin ?',
      'ballot.note': 'Les candidatures ne sont closes que le 12 mars 2027. Le modèle simule le bulletin au lieu de le supposer. Ces probabilités sont estimées à partir de la fréquence à laquelle les instituts testent chaque candidat — un indicateur, pas une mesure.',
      'ballot.arbitration': 'Candidatures mutuellement exclusives',
      'ballot.independent': 'Probabilité de figurer sur le bulletin',
      'ballot.none': 'aucun',
      'polls.title': 'Derniers sondages',
      'polls.note': 'Chaque enquête renvoie à la notice déposée auprès de la Commission des sondages, qui est la source primaire.',
      'polls.institute': 'Institut',
      'polls.dates': 'Terrain',
      'polls.sample': 'Échantillon',
      'polls.top': 'En tête',
      'polls.notice': 'notice',
      'method.title': 'Méthode et limites',
      'method.data': 'Données',
      'method.model': 'Modèle',
      'method.caveat': 'Ce que ce n’est pas',
      'method.dataBody': 'Sondages compilés par le dépôt open source <a href="https://github.com/MieuxVoter/presidentielle2027">MieuxVoter/presidentielle2027</a> (licence MIT), lui-même alimenté par les notices de la <a href="http://www.commission-des-sondages.fr/">Commission des sondages</a>. Le report des voix au second tour s’appuie en outre sur les résultats officiels du <a href="https://www.data.gouv.fr/">ministère de l’Intérieur</a> (présidentielle 2022, législatives 2024, Licence Ouverte 2.0). Ce site n’est affilié à aucun d’eux.',
      'method.modelBody': 'Logit emboîté hiérarchique et dynamique. Les candidats sont regroupés en blocs à l’intérieur desquels le report de voix est fort ; la force de ce report est estimée, pas supposée. Effets de maison contraints à somme nulle. Second tour modélisé par report de voix selon la proximité, avec un terme de « front républicain » estimé à la fois sur les reports mesurés de 2022, sur les 317 duels RN des législatives de 2024 et sur les hypothèses de second tour. Une élection législative n’est pas une présidentielle : le modèle lui laisse sa propre géométrie plutôt que de la confondre avec celle de 2027.',
      'method.caveatBody': 'Ce n’est pas une prédiction, et ce n’est pas un sondage. C’est ce que les sondages publiés impliquent sous les hypothèses décrites, avec leur incertitude. Sept mois avant le scrutin, cette incertitude est grande.',
      'footer.build': 'Version',
      'footer.source': 'Source des sondages',
      'footer.disclaimer': 'Projet personnel, sans lien avec un institut de sondage, un parti ou un média.',
      'label.win': 'élu',
      'label.qualify': 'au second tour',
      'label.standing': 'sur le bulletin',
      'label.median': 'médiane',
      'duel.likely': 'de probabilité',
      'duel.wins': 'l’emporte',
      'diag.surveys': 'enquêtes',
      'diag.hypotheses': 'hypothèses de premier tour',
      'diag.sims': 'simulations',
      'diag.fit': 'Convergence',
      'error.load': 'Impossible de charger les données de la prévision.',
      'error.schema': 'Cette page attend une version de données différente. Videz le cache et rechargez.'
    },
    en: {
      'html.lang': 'en',
      'title': 'French Presidential Election 2027',
      'subtitle': 'A Bayesian forecast from published polling',
      'updated': 'Data to',
      'countdown': function (n) {
        return n + (n > 1 ? ' days to the first round' : ' day to the first round');
      },
      'scenario.model': 'Full model',
      'scenario.conditional': 'Scenario: every probability below assumes this exact ballot. These are not overall probabilities.',
      'scenario.ballot': 'On the ballot:',
      'change.none': '',
      'a11y.skip': 'Skip to content',
      'a11y.scenarioNav': 'Choose a scenario',
      'a11y.barsTitle': 'Probability by candidate',
      'a11y.intervalTitle': 'First-round share, 90% interval',
      'a11y.trendTitle': 'Estimated first-round share over time',
      'a11y.trendTable': 'Most recent estimated share, by candidate',
      'a11y.candidate': 'Candidate',
      'a11y.probability': 'Probability',
      'a11y.low': 'Lower bound',
      'a11y.high': 'Upper bound',
      'a11y.latest': 'Latest value',
      'a11y.pollsCaption': 'Most recent published surveys',
      'a11y.announceScenario': function (name) {
        return 'Scenario applied: ' + name + '. The probabilities shown assume this ballot.';
      },
      'a11y.announceModel': 'Full model restored. Probabilities allow for uncertainty about the ballot.',
      'record.title': 'How good is this model?',
      'record.note': 'A probability is a claim about frequencies. Here is how this same model did when replayed on the 2022 election, given only what was known on the date shown.',
      'record.horizon': 'Before the vote',
      'record.top2': 'Right runoff pair',
      'record.mae': 'Median error',
      'record.cov90': '90% coverage',
      'record.pwinner': 'Probability given to the winner',
      'record.days': function (n) { return n + ' days'; },
      'record.yes': 'yes',
      'record.no': 'no',
      'record.caveats': 'What to take from this',
      'record.circular': 'The coverage above is partly circular: both parameters that set interval width were calibrated on this same 2022 cycle, for want of a second one. It is not independent validation. What is not circular: the runoff pair, the ballot simulation, and the median error.',
      'record.vuln': 'The biggest fragility remains the front républicain — how readily votes transfer to an RN finalist is estimated from the measured 2022 transfers, from 317 duels in the 2024 legislative elections and from runoff polling, and nothing guarantees 2027 behaves the same. It is the assumption that can move the headline by ten points.',
      'record.undercover': 'The intervals are still too narrow: what is labelled 90% contained the result less often than that. Read them as a floor on the uncertainty, not a ceiling.',
      'history.title': 'Probability of being elected, over time',
      'history.note': 'What this page showed at each state of the polling — one point per data date, not per model run.',
      'history.modelChanged': 'Note: the model was changed during this period. Earlier points were produced by different arithmetic, so this is not a like-for-like comparison.',
      'history.a11yTitle': 'Probability of being elected, by candidate and date',
      'history.date': 'Date',
      'hero.title': 'Who becomes president?',
      'hero.note': 'Probability of winning the runoff, allowing for uncertainty about who is on the ballot.',
      'qualify.title': 'Reaching the runoff',
      'qualify.note': 'Qualifying and winning are different questions. A candidate can lead the first round comfortably and lose the second.',
      'first.title': 'First round',
      'first.note': 'The 90% interval for a candidate’s first-round share, given that they stand. The thicker bar is the 50% interval.',
      'duels.title': 'Possible runoffs',
      'duels.note': 'Every runoff the simulation produced, with how likely it is and who wins it.',
      'trend.title': 'Trend',
      'trend.note': 'Estimated first-round share over time, for the reference ballot.',
      'ballot.title': 'Who is on the ballot?',
      'ballot.note': 'Candidacies do not close until 12 March 2027. The model simulates the ballot instead of assuming it. These probabilities come from how often institutes test each candidate — a proxy, not a measurement.',
      'ballot.arbitration': 'Mutually exclusive candidacies',
      'ballot.independent': 'Probability of being on the ballot',
      'ballot.none': 'none',
      'polls.title': 'Latest polls',
      'polls.note': 'Each survey links to the notice filed with the Commission des sondages, which is the primary source.',
      'polls.institute': 'Institute',
      'polls.dates': 'Fieldwork',
      'polls.sample': 'Sample',
      'polls.top': 'Leading',
      'polls.notice': 'notice',
      'method.title': 'Method and limits',
      'method.data': 'Data',
      'method.model': 'Model',
      'method.caveat': 'What this is not',
      'method.dataBody': 'Polls compiled by the open-source repository <a href="https://github.com/MieuxVoter/presidentielle2027">MieuxVoter/presidentielle2027</a> (MIT licence), which in turn draws on the notices filed with the <a href="http://www.commission-des-sondages.fr/">Commission des sondages</a>. Second-round transfers additionally use official results from the French <a href="https://www.data.gouv.fr/">Interior Ministry</a> (2022 presidential, 2024 legislative, Licence Ouverte 2.0). This site is affiliated with none of them.',
      'method.modelBody': 'A hierarchical dynamic nested logit. Candidates sit in blocs within which substitution is strong; how strong is estimated, not assumed. House effects are constrained to sum to zero. The runoff is modelled as vote transfers by ideological proximity, with a front républicain term estimated jointly on the measured 2022 transfers, on 317 RN duels from the 2024 legislative elections and on runoff polling. A legislative election is not a presidential one, so the model gives it its own geometry rather than conflating it with 2027’s.',
      'method.caveatBody': 'This is not a prediction and it is not a poll. It is what published polling implies under the stated assumptions, with its uncertainty attached. Seven months out, that uncertainty is large.',
      'footer.build': 'Build',
      'footer.source': 'Polling source',
      'footer.disclaimer': 'A personal project, unconnected to any polling institute, party or news organisation.',
      'label.win': 'president',
      'label.qualify': 'reach runoff',
      'label.standing': 'on ballot',
      'label.median': 'median',
      'duel.likely': 'likely',
      'duel.wins': 'wins',
      'diag.surveys': 'surveys',
      'diag.hypotheses': 'first-round hypotheses',
      'diag.sims': 'simulations',
      'diag.fit': 'Convergence',
      'error.load': 'Could not load the forecast data.',
      'error.schema': 'This page expects a different data version. Clear the cache and reload.'
    }
  };

  function safeGet(key) {
    try {
      return global.localStorage ? global.localStorage.getItem(key) : null;
    } catch (e) {
      return null;
    }
  }

  function safeSet(key, value) {
    try {
      if (global.localStorage) global.localStorage.setItem(key, value);
    } catch (e) {
      /* Storage blocked. The toggle still works for this page view. */
    }
  }

  function initialLang() {
    var stored = safeGet(STORAGE_KEY);
    if (stored === 'fr' || stored === 'en') return stored;
    // ALWAYS French on a first visit. Deliberately not navigator.language:
    // this is a French election, the French text is the source of truth
    // rather than the translation, and an English-speaking reader is one
    // click away. Once they click, the choice is remembered.
    return 'fr';
  }

  var current = initialLang();
  var listeners = [];

  var I18n = {
    get lang() { return current; },

    t: function (key, arg) {
      var table = STRINGS[current] || STRINGS.fr;
      var v = table[key];
      if (v === undefined) v = (STRINGS.fr[key] !== undefined) ? STRINGS.fr[key] : key;
      return (typeof v === 'function') ? v(arg) : v;
    },

    set: function (lang) {
      if (lang !== 'fr' && lang !== 'en') return;
      current = lang;
      safeSet(STORAGE_KEY, lang);
      document.documentElement.setAttribute('lang', lang);
      I18n.apply();
      listeners.forEach(function (fn) { fn(lang); });
    },

    onChange: function (fn) { listeners.push(fn); },

    /* Replace the text of anything carrying data-i18n. Elements whose markup
       matters (links inside a paragraph) are left alone by omitting the
       attribute in the HTML. */
    apply: function () {
      var nodes = document.querySelectorAll('[data-i18n]');
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var key = el.getAttribute('data-i18n');
        var value = I18n.t(key);
        if (typeof value !== 'string') continue;
        if (el.hasAttribute('data-i18n-html')) {
          // Only for the few strings that carry a link. The markup is a
          // literal in this file - never anything from the data feed - so
          // there is nothing here that could be injected.
          el.innerHTML = value;
        } else {
          el.textContent = value;
        }
      }
      var labelled = document.querySelectorAll('[data-i18n-aria]');
      for (var k = 0; k < labelled.length; k++) {
        var v = I18n.t(labelled[k].getAttribute('data-i18n-aria'));
        if (typeof v === 'string') labelled[k].setAttribute('aria-label', v);
      }
      var btns = document.querySelectorAll('.lang-btn');
      for (var j = 0; j < btns.length; j++) {
        var on = btns[j].getAttribute('data-lang') === current;
        btns[j].classList.toggle('is-active', on);
        btns[j].setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    },

    /* Number and date formatting follow the language, not the machine. */
    pct: function (x, digits) {
      if (x === null || x === undefined || isNaN(x)) return '—';
      var d = (digits === undefined) ? 0 : digits;
      if (x > 0 && x < 0.005) return current === 'fr' ? '< 1 %' : '<1%';
      if (x < 1 && x > 0.995) return current === 'fr' ? '> 99 %' : '>99%';
      var n = (x * 100).toFixed(d);
      return current === 'fr' ? n.replace('.', ',') + ' %' : n + '%';
    },

    date: function (iso) {
      if (!iso) return '—';
      var parts = String(iso).slice(0, 10).split('-');
      if (parts.length !== 3) return iso;
      var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
      try {
        return d.toLocaleDateString(current === 'fr' ? 'fr-FR' : 'en-GB', {
          day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'
        });
      } catch (e) {
        return iso;
      }
    },

    shortDate: function (iso) {
      if (!iso) return '—';
      var parts = String(iso).slice(0, 10).split('-');
      if (parts.length !== 3) return iso;
      var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
      try {
        return d.toLocaleDateString(current === 'fr' ? 'fr-FR' : 'en-GB', {
          day: 'numeric', month: 'short', timeZone: 'UTC'
        });
      } catch (e) {
        return iso;
      }
    },

    blocName: function (bloc) {
      if (!bloc) return '';
      return current === 'fr' ? bloc.nom_fr : bloc.nom_en;
    }
  };

  global.I18n = I18n;
})(window);
