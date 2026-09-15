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
      'method.dataBody': 'Sondages compilés par le dépôt open source <a href="https://github.com/MieuxVoter/presidentielle2027">MieuxVoter/presidentielle2027</a> (licence MIT), lui-même alimenté par les notices de la <a href="http://www.commission-des-sondages.fr/">Commission des sondages</a>. Ce site n’est affilié ni à l’une ni à l’autre.',
      'method.modelBody': 'Logit emboîté hiérarchique et dynamique. Les candidats sont regroupés en blocs à l’intérieur desquels le report de voix est fort ; la force de ce report est estimée, pas supposée. Effets de maison contraints à somme nulle. Second tour modélisé par report de voix selon la proximité, avec un terme de « front républicain » estimé.',
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
      'method.dataBody': 'Polls compiled by the open-source repository <a href="https://github.com/MieuxVoter/presidentielle2027">MieuxVoter/presidentielle2027</a> (MIT licence), which in turn draws on the notices filed with the <a href="http://www.commission-des-sondages.fr/">Commission des sondages</a>. This site is affiliated with neither.',
      'method.modelBody': 'A hierarchical dynamic nested logit. Candidates sit in blocs within which substitution is strong; how strong is estimated, not assumed. House effects are constrained to sum to zero. The runoff is modelled as vote transfers by ideological proximity, with an estimated front républicain term.',
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
