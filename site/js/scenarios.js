/* =========================================================================
   Named ballots.

   The default view marginalises over who stands, which is the honest headline
   and not the question people ask. These let a reader fix the ballot and see
   the conditional answer instead.

   THE ONE RULE HERE: every number shown under a scenario is CONDITIONAL on
   that ballot, and the page must say so while they are on screen. A
   conditional probability presented as an unconditional one is the most
   natural way for this page to mislead, so the banner is not dismissible and
   is rendered from the same code path as the numbers themselves.
   ========================================================================= */
(function (global) {
  'use strict';

  function scenarioById(data, id) {
    var list = (data && data.scenarios) || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i];
    }
    return null;
  }

  /* What the charts should draw: either the full simulation or one fixed
     ballot. Returning the same shape from both keeps every render function
     ignorant of which it is showing. */
  function view(data, scenarioId) {
    var s = scenarioId ? scenarioById(data, scenarioId) : null;
    if (!s) {
      return {
        candidats: data.candidats,
        duels: data.duels,
        scenario: null
      };
    }
    return {
      candidats: s.candidats,
      duels: s.duels,
      scenario: s
    };
  }

  function label(s, lang) {
    return lang === 'fr' ? s.nom_fr : s.nom_en;
  }

  function note(s, lang) {
    return lang === 'fr' ? s.note_fr : s.note_en;
  }

  /* The switcher. Buttons rather than a <select>: there are few options, they
     benefit from being visible at once, and each is a real choice a reader
     might not know was available. */
  function renderBar(mount, data, currentId, onSelect) {
    mount.innerHTML = '';
    var list = (data && data.scenarios) || [];
    if (!list.length) {
      mount.hidden = true;
      return;
    }
    mount.hidden = false;

    var options = [{ id: null, text: I18n.t('scenario.model') }];
    for (var i = 0; i < list.length; i++) {
      options.push({ id: list[i].id, text: label(list[i], I18n.lang) });
    }

    options.forEach(function (opt) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'scenario-btn' + (opt.id === currentId ? ' is-active' : '');
      b.textContent = opt.text;
      b.setAttribute('aria-pressed', opt.id === currentId ? 'true' : 'false');
      b.addEventListener('click', function () { onSelect(opt.id); });
      mount.appendChild(b);
    });
  }

  /* The caveat panel, shown only while a scenario is active. */
  function renderNote(mount, s) {
    mount.innerHTML = '';
    if (!s) {
      mount.hidden = true;
      return;
    }
    mount.hidden = false;

    var warn = document.createElement('p');
    warn.className = 'scenario-warning';
    warn.textContent = I18n.t('scenario.conditional');
    mount.appendChild(warn);

    var text = note(s, I18n.lang);
    if (text) {
      var p = document.createElement('p');
      p.className = 'scenario-note';
      p.textContent = text;
      mount.appendChild(p);
    }

    if (s.sur_le_bulletin && s.sur_le_bulletin.length) {
      var names = s.candidats.map(function (c) { return c.nom; });
      var who = document.createElement('p');
      who.className = 'scenario-field';
      who.textContent = I18n.t('scenario.ballot') + ' ' + names.join(' · ');
      mount.appendChild(who);
    }
  }

  global.Scenarios = {
    view: view,
    renderBar: renderBar,
    renderNote: renderNote
  };
})(window);
