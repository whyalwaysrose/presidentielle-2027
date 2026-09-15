/* =========================================================================
   Page controller.

   Loads site/data/forecast.json, renders, and re-renders on a language change.

   Two things here are deliberate rather than incidental:

   * SCHEMA_VERSION is checked against the payload. A cached page against new
     data should say so, not silently render blanks.
   * Everything runs inside a try/catch that puts the message on the page. A
     forecast page that renders its shell and then does nothing, with the error
     only in a console the reader will never open, is the single hardest
     failure to diagnose from a bug report.
   ========================================================================= */
(function () {
  'use strict';

  var SCHEMA_VERSION = 2;
  var BUILD = '2026-09-07.7';

  var state = { data: null, scenario: null };

  function showError(message, detail) {
    var box = document.getElementById('load-error');
    if (!box) return;
    box.hidden = false;
    box.textContent = message;
    if (detail) {
      var code = document.createElement('code');
      code.textContent = String(detail);
      box.appendChild(code);
    }
  }

  function blocColour(data, blocKey) {
    var b = data.blocs && data.blocs[blocKey];
    return (b && b.couleur) || '#7d8894';
  }

  function candidate(data, id) {
    var lists = [data.candidats];
    if (state.scenario) {
      var v = Scenarios.view(data, state.scenario);
      lists.unshift(v.candidats);
    }
    for (var l = 0; l < lists.length; l++) {
      for (var i = 0; i < lists[l].length; i++) {
        if (lists[l][i].id === id) return lists[l][i];
      }
    }
    return null;
  }

  /* "Marine Le Pen" -> "Le Pen", not "Pen". Taking the last token drops the
     particle in exactly the names where it carries the identity: Le Pen,
     de Villepin, Dupont-Aignan. Dropping the FIRST token instead is correct
     for every name in this field, compound forenames included
     ("Jean-Luc Mélenchon" -> "Mélenchon"). */
  function surname(fullName) {
    var parts = String(fullName || '').trim().split(/\s+/);
    return parts.length > 1 ? parts.slice(1).join(' ') : parts[0];
  }

  function meta(data) {
    return {
      colourOf: function (id) {
        var c = candidate(data, id);
        return c ? blocColour(data, c.bloc) : '#7d8894';
      },
      nameOf: function (id) {
        var c = candidate(data, id);
        return c ? c.nom : id;
      }
    };
  }

  /* Switching scenario or language rewrites most of the page in place. A
     sighted user sees that instantly; without an announcement nobody else
     knows anything happened at all. */
  function announce(message) {
    var live = document.getElementById('a11y-live');
    if (!live || !message) return;
    // Re-setting identical text does not re-announce, so clear first.
    live.textContent = '';
    setTimeout(function () { live.textContent = message; }, 50);
  }

  function view() {
    return Scenarios.view(state.data, state.scenario);
  }

  /* --- header ---------------------------------------------------------- */
  function renderHeader(data) {
    document.getElementById('as-of').textContent = I18n.date(data.as_of);
    document.getElementById('countdown').textContent =
      I18n.t('countdown', data.election.jours_restants);
    document.getElementById('build-stamp').textContent =
      BUILD + ' · ' + data.model_fingerprint;
  }

  /* --- who wins -------------------------------------------------------- */
  function renderWinners(data) {
    var mount = document.getElementById('win-list');
    mount.innerHTML = '';
    var rows = view().candidats.slice(0, 6).filter(function (c) {
      return (c.p_win || 0) >= 0.005;
    });
    if (!rows.length) rows = view().candidats.slice(0, 3);

    rows.forEach(function (c) {
      var wrap = document.createElement('li');
      wrap.className = 'win-row';

      var top = document.createElement('div');
      top.className = 'win-top';

      var name = document.createElement('div');
      name.className = 'win-name';
      name.textContent = c.nom;
      var party = document.createElement('span');
      party.className = 'win-party';
      party.textContent = c.parti;
      name.appendChild(party);

      var val = document.createElement('div');
      val.className = 'win-value';
      val.textContent = I18n.pct(c.p_win);
      // Deliberately NOT tinted with the bloc colour. These hues are chosen to
      // read on the dark ground; on the light theme the centre's amber and the
      // Socialists' pink fall to roughly 2:1 against white, well under the 4.5:1
      // floor for text. The bar directly beneath is full-width and bloc-coloured,
      // so the association is carried by the element that can afford it.

      top.appendChild(name);
      top.appendChild(val);

      var track = document.createElement('div');
      track.className = 'bar-track';
      // The bar repeats the number beside it; announcing it twice is noise.
      track.setAttribute('aria-hidden', 'true');
      var fill = document.createElement('div');
      fill.className = 'bar-fill';
      fill.style.width = Math.max(0.6, (c.p_win || 0) * 100) + '%';
      fill.style.background = blocColour(data, c.bloc);
      track.appendChild(fill);

      wrap.appendChild(top);
      wrap.appendChild(track);
      mount.appendChild(wrap);
    });
  }

  /* --- qualification --------------------------------------------------- */
  function renderQualify(data) {
    var rows = view().candidats
      .filter(function (c) { return (c.p_qualify || 0) >= 0.01; })
      .sort(function (a, b) { return b.p_qualify - a.p_qualify; })
      .slice(0, 10)
      .map(function (c) {
        return { label: c.nom, value: c.p_qualify, color: blocColour(data, c.bloc) };
      });
    Charts.probabilityBars(document.getElementById('qualify-chart'), rows);
  }

  /* --- first round ------------------------------------------------------ */
  function renderShares(data) {
    var rows = view().candidats
      .filter(function (c) { return c.share && c.share.q50 !== null && (c.p_standing || 0) >= 0.05; })
      .sort(function (a, b) { return b.share.q50 - a.share.q50; })
      .map(function (c) {
        return {
          label: c.nom,
          q05: c.share.q05, q25: c.share.q25, q50: c.share.q50,
          q75: c.share.q75, q95: c.share.q95,
          color: blocColour(data, c.bloc)
        };
      });
    Charts.intervalPlot(document.getElementById('share-chart'), rows);
  }

  /* --- runoffs ---------------------------------------------------------- */
  function renderDuels(data) {
    var mount = document.getElementById('duels-list');
    mount.innerHTML = '';
    (view().duels || []).slice(0, 8).forEach(function (d) {
      var ca = candidate(data, d.a), cb = candidate(data, d.b);
      var colA = ca ? blocColour(data, ca.bloc) : '#888';
      var colB = cb ? blocColour(data, cb.bloc) : '#888';

      var card = document.createElement('div');
      card.className = 'duel';

      var head = document.createElement('div');
      head.className = 'duel-head';
      var names = document.createElement('div');
      names.className = 'duel-names';
      names.textContent = d.nom_a + ' — ' + d.nom_b;
      var prob = document.createElement('div');
      prob.className = 'duel-prob';
      prob.textContent = I18n.pct(d.p_matchup) + ' ' + I18n.t('duel.likely');
      head.appendChild(names);
      head.appendChild(prob);

      var bar = document.createElement('div');
      bar.className = 'duel-bar';
      // Two coloured halves reading "44%" "56%" say nothing about whose. One
      // labelled group says the whole thing once.
      bar.setAttribute('role', 'group');
      bar.setAttribute('aria-label',
        d.nom_a + ' ' + I18n.pct(d.p_a_wins) + ', ' +
        d.nom_b + ' ' + I18n.pct(1 - d.p_a_wins));
      var left = document.createElement('div');
      left.className = 'duel-side';
      left.style.width = (d.p_a_wins * 100) + '%';
      left.style.background = colA;
      left.textContent = I18n.pct(d.p_a_wins);
      var right = document.createElement('div');
      right.className = 'duel-side right';
      right.style.width = ((1 - d.p_a_wins) * 100) + '%';
      right.style.background = colB;
      right.textContent = I18n.pct(1 - d.p_a_wins);
      left.setAttribute('aria-hidden', 'true');
      right.setAttribute('aria-hidden', 'true');
      bar.appendChild(left);
      bar.appendChild(right);

      card.appendChild(head);
      card.appendChild(bar);
      mount.appendChild(card);
    });
  }

  /* --- ballot ----------------------------------------------------------- */
  function renderBallot(data) {
    var mount = document.getElementById('ballot-panel');
    mount.innerHTML = '';
    var b = data.ballot || {};

    var left = document.createElement('div');
    var h1 = document.createElement('h3');
    h1.textContent = I18n.t('ballot.arbitration');
    left.appendChild(h1);

    (b.arbitrations || []).forEach(function (arb) {
      var box = document.createElement('div');
      box.className = 'arb';
      var blocName = I18n.blocName(data.blocs[arb.bloc]);
      var title = document.createElement('div');
      title.className = 'arb-bloc';
      title.textContent = blocName;
      box.appendChild(title);

      var bar = document.createElement('div');
      bar.className = 'arb-bar';
      // The labels under it carry the same numbers in text.
      bar.setAttribute('aria-hidden', 'true');
      var labels = document.createElement('div');
      labels.className = 'arb-labels';

      arb.options.forEach(function (cid, i) {
        var p = arb.probabilities[i];
        var seg = document.createElement('div');
        seg.className = 'arb-seg';
        seg.style.width = (p * 100) + '%';
        seg.style.background = blocColour(data, arb.bloc);
        seg.style.opacity = 0.45 + 0.55 * (1 - i / Math.max(1, arb.options.length));
        var c = candidate(data, cid);
        seg.textContent = p > 0.12 ? (c ? surname(c.nom) : cid) : '';
        bar.appendChild(seg);

        var lab = document.createElement('span');
        lab.textContent = (c ? c.nom : cid) + ' ' + I18n.pct(p);
        labels.appendChild(lab);
      });
      if (arb.p_none > 0.001) {
        var none = document.createElement('div');
        none.className = 'arb-seg';
        none.style.width = (arb.p_none * 100) + '%';
        none.style.background = 'var(--track)';
        bar.appendChild(none);
        var nl = document.createElement('span');
        nl.textContent = I18n.t('ballot.none') + ' ' + I18n.pct(arb.p_none);
        labels.appendChild(nl);
      }
      box.appendChild(bar);
      box.appendChild(labels);
      left.appendChild(box);
    });

    var right = document.createElement('div');
    var h2 = document.createElement('h3');
    h2.textContent = I18n.t('ballot.independent');
    right.appendChild(h2);

    var entries = Object.keys(b.independent || {}).map(function (cid) {
      return { id: cid, p: b.independent[cid] };
    }).filter(function (e) { return e.p >= 0.02; })
      .sort(function (a, z) { return z.p - a.p; });

    entries.forEach(function (e) {
      var c = candidate(data, e.id);
      var row = document.createElement('div');
      row.className = 'stand-row';
      var n = document.createElement('div');
      n.className = 'stand-name';
      n.textContent = c ? c.nom : e.id;
      var v = document.createElement('div');
      v.className = 'stand-val';
      v.textContent = I18n.pct(e.p);
      var track = document.createElement('div');
      track.className = 'stand-track';
      track.setAttribute('aria-hidden', 'true');
      var fill = document.createElement('div');
      fill.className = 'stand-fill';
      fill.style.width = (e.p * 100) + '%';
      fill.style.background = c ? blocColour(data, c.bloc) : '#888';
      track.appendChild(fill);
      row.appendChild(n);
      row.appendChild(v);
      row.appendChild(track);
      right.appendChild(row);
    });

    mount.appendChild(left);
    mount.appendChild(right);
  }

  /* --- polls ------------------------------------------------------------ */
  function renderPolls(data) {
    var mount = document.getElementById('polls-table');
    mount.innerHTML = '';
    var table = document.createElement('table');
    var cap = document.createElement('caption');
    cap.className = 'sr-only';
    cap.textContent = I18n.t('a11y.pollsCaption');
    table.appendChild(cap);
    var thead = document.createElement('thead');
    var hr = document.createElement('tr');
    [I18n.t('polls.institute'), I18n.t('polls.dates'),
     I18n.t('polls.sample'), I18n.t('polls.top')].forEach(function (h) {
      var th = document.createElement('th');
      th.setAttribute('scope', 'col');
      th.textContent = h;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    (data.derniers_sondages || []).forEach(function (p) {
      var tr = document.createElement('tr');

      var td1 = document.createElement('th');
      td1.setAttribute('scope', 'row');
      var inst = document.createElement('span');
      inst.className = 'poll-inst';
      inst.textContent = p.institut;
      td1.appendChild(inst);
      if (p.commanditaire) {
        var cl = document.createElement('span');
        cl.className = 'poll-client';
        cl.textContent = p.commanditaire;
        td1.appendChild(cl);
      }
      tr.appendChild(td1);

      var td2 = document.createElement('td');
      td2.textContent = I18n.shortDate(p.debut) + ' – ' + I18n.shortDate(p.fin);
      tr.appendChild(td2);

      var td3 = document.createElement('td');
      td3.textContent = p.echantillon ? String(p.echantillon) : '—';
      tr.appendChild(td3);

      var td4 = document.createElement('td');
      var top = document.createElement('span');
      top.className = 'poll-top';
      top.textContent = (p.tete || []).map(function (t) {
        return surname(t.nom) + ' ' + I18n.pct(t.part);
      }).join(' · ');
      td4.appendChild(top);
      tr.appendChild(td4);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    mount.appendChild(table);
  }

  /* --- headline over time ------------------------------------------------ */
  function renderHistory(data) {
    var card = document.getElementById('history-card');
    var hist = data.historique;
    if (!hist || !hist.dates || hist.dates.length < 2) {
      // One data point is not a history. Hide rather than draw a dot.
      card.hidden = true;
      return;
    }
    card.hidden = false;
    Charts.historyLines(
      document.getElementById('history-chart'), hist, meta(data),
      document.getElementById('history-legend')
    );
    // Earlier points came from earlier arithmetic. Saying so is the difference
    // between a history and a misleading one.
    var warn = document.getElementById('history-warning');
    warn.hidden = !hist.model_changed;
    warn.textContent = hist.model_changed ? I18n.t('history.modelChanged') : '';
  }

  /* --- the model's own record ------------------------------------------- */
  function renderRecord(data) {
    var card = document.getElementById('record-card');
    var rec = data.palmares;
    if (!rec || !rec.runs || !rec.runs.length) {
      // Nothing scored yet. Better silent than a section claiming a record
      // that does not exist.
      card.hidden = true;
      return;
    }
    card.hidden = false;

    var mount = document.getElementById('record-table');
    mount.innerHTML = '';
    var table = document.createElement('table');
    var cap = document.createElement('caption');
    cap.className = 'sr-only';
    cap.textContent = I18n.t('record.title');
    table.appendChild(cap);

    var head = [I18n.t('record.horizon'), I18n.t('record.top2'),
                I18n.t('record.mae'), I18n.t('record.cov90'),
                I18n.t('record.pwinner')];
    var thead = document.createElement('thead');
    var hr = document.createElement('tr');
    head.forEach(function (h) {
      var th = document.createElement('th');
      th.setAttribute('scope', 'col');
      th.textContent = h;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var worstCoverage = 1;
    rec.runs.forEach(function (r) {
      if (typeof r.coverage_90 === 'number') {
        worstCoverage = Math.min(worstCoverage, r.coverage_90);
      }
      var tr = document.createElement('tr');
      var cells = [
        I18n.t('record.days', r.days_out),
        r.top2_correct ? I18n.t('record.yes') : I18n.t('record.no'),
        (r.mae_points != null ? r.mae_points.toFixed(1) : '—') + ' pts',
        I18n.pct(r.coverage_90),
        I18n.pct(r.p_winner)
      ];
      cells.forEach(function (c, i) {
        var cell = document.createElement(i === 0 ? 'th' : 'td');
        if (i === 0) cell.setAttribute('scope', 'row');
        cell.textContent = c;
        tr.appendChild(cell);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    mount.appendChild(table);

    // The caveats are not decoration. A record shown without them reads as
    // independent validation, which this is not.
    var cav = document.getElementById('record-caveats');
    cav.innerHTML = '';
    var h = document.createElement('h3');
    h.textContent = I18n.t('record.caveats');
    cav.appendChild(h);

    var items = [{ key: 'record.vuln', main: true }];
    if (worstCoverage < 0.9) items.push({ key: 'record.undercover' });
    if (rec.circular) items.push({ key: 'record.circular' });

    items.forEach(function (it) {
      var p = document.createElement('p');
      p.textContent = I18n.t(it.key);
      if (it.main) p.className = 'is-key';
      cav.appendChild(p);
    });
  }

  /* --- commentary and diagnostics --------------------------------------- */
  function renderCommentary(data) {
    var mount = document.getElementById('commentary');
    var text = (data.commentaire && data.commentaire[I18n.lang]) || '';
    mount.textContent = text;

    var diag = document.getElementById('diagnostics');
    diag.innerHTML = '';
    var s = data.sondages || {}, d = data.diagnostics || {};
    var bits = [
      s.surveys + ' ' + I18n.t('diag.surveys'),
      s.hypotheses_tour1 + ' ' + I18n.t('diag.hypotheses'),
      (data.n_simulations || 0).toLocaleString(I18n.lang === 'fr' ? 'fr-FR' : 'en-GB') +
        ' ' + I18n.t('diag.sims'),
      I18n.t('diag.fit') + ': R-hat ' + (d.max_rhat ? d.max_rhat.toFixed(3) : '—') +
        ', ESS ' + (d.min_ess_bulk ? Math.round(d.min_ess_bulk) : '—')
    ];
    bits.forEach(function (b) {
      var span = document.createElement('span');
      span.textContent = b;
      diag.appendChild(span);
    });
  }

  /* --- what moved ------------------------------------------------------- */
  function renderChange(data) {
    var el = document.getElementById('change-line');
    var text = (data.changement && data.changement.texte &&
                data.changement.texte[I18n.lang]) || '';
    if (!text) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.textContent = text;
    // A model change is not polling news, and the styling says so as well as
    // the words.
    el.classList.toggle('is-model-change',
      !!(data.changement && data.changement.model_changed));
  }

  /* --- scenarios -------------------------------------------------------- */
  function renderScenarios(data) {
    Scenarios.renderBar(
      document.getElementById('scenario-bar'), data, state.scenario,
      function (id) {
        state.scenario = id;
        renderAll();
        var v = view().scenario;
        announce(v
          ? I18n.t('a11y.announceScenario',
                   I18n.lang === 'fr' ? v.nom_fr : v.nom_en)
          : I18n.t('a11y.announceModel'));
      }
    );
    Scenarios.renderNote(
      document.getElementById('scenario-note'),
      view().scenario
    );
    // The ballot panel answers "who will stand", which a fixed scenario has
    // already answered by fiat. Hiding it avoids showing a 67% next to a
    // ballot that assumes 100%.
    var ballot = document.getElementById('ballot-panel');
    if (ballot && ballot.closest) {
      var card = ballot.closest('.card');
      if (card) card.hidden = !!state.scenario;
    }
  }

  /* --- render all ------------------------------------------------------- */
  function renderAll() {
    var data = state.data;
    if (!data) return;
    renderHeader(data);
    renderChange(data);
    renderScenarios(data);
    renderWinners(data);
    renderQualify(data);
    renderShares(data);
    renderDuels(data);
    renderBallot(data);
    renderPolls(data);
    renderHistory(data);
    renderRecord(data);
    renderCommentary(data);
    Charts.trendLines(
      document.getElementById('trend-chart'),
      data.tendance,
      meta(data),
      document.getElementById('trend-legend')
    );
  }

  /* An aggregate count of deliberate language switches, so the one thing
     worth knowing about a bilingual page - whether the English half is read
     at all, and so whether it is worth maintaining - is answerable. It fires
     only on a real click, never on the default, so it measures a choice
     rather than a page load.

     Everything is guarded: if the counter is blocked, absent, or throws, the
     toggle itself must still work. Analytics is never allowed to be on the
     critical path of the page functioning. */
  function countLanguageSwitch(lang) {
    try {
      if (!window.goatcounter || typeof window.goatcounter.count !== 'function') return;
      window.goatcounter.count({
        path: 'lang-switch-' + lang,
        title: 'Language switched to ' + lang,
        event: true
      });
    } catch (e) {
      /* never let counting break the toggle */
    }
  }

  /* --- boot ------------------------------------------------------------- */
  function boot() {
    I18n.apply();
    document.documentElement.setAttribute('lang', I18n.lang);

    var btns = document.querySelectorAll('.lang-btn');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        var lang = this.getAttribute('data-lang');
        I18n.set(lang);
        countLanguageSwitch(lang);
      });
    }
    I18n.onChange(renderAll);

    var resizeTimer = null;
    window.addEventListener('resize', function () {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(renderAll, 150);
    });

    fetch('data/forecast.json?v=' + encodeURIComponent(BUILD))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (data.schema_version !== SCHEMA_VERSION) {
          showError(I18n.t('error.schema'),
            'page ' + SCHEMA_VERSION + ' / data ' + data.schema_version);
          return;
        }
        state.data = data;
        renderAll();
      })
      .catch(function (err) {
        showError(I18n.t('error.load'), err && err.message);
      });
  }

  try {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot);
    } else {
      boot();
    }
  } catch (err) {
    showError('Erreur au démarrage / startup error', err && err.message);
  }
})();
