/* =========================================================================
   Charts. Hand-rolled SVG, no library, no build step.

   Every chart re-renders on a language change rather than mutating labels in
   place, because axis tick formatting, number separators and label widths all
   differ between fr and en. Re-rendering is cheap here and keeps one code path.
   ========================================================================= */
(function (global) {
  'use strict';

  var SVG = 'http://www.w3.org/2000/svg';

  function el(name, attrs, text) {
    var node = document.createElementNS(SVG, name);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k) && attrs[k] !== null) {
          node.setAttribute(k, attrs[k]);
        }
      }
    }
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function cssVar(name, fallback) {
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue(name);
      return (v && v.trim()) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  /* ---------------------------------------------------------------------
     Horizontal probability bars — used for "reaching the runoff".
     --------------------------------------------------------------------- */
  function probabilityBars(mount, rows, opts) {
    opts = opts || {};
    clear(mount);
    if (!rows.length) return;

    var rowH = 30;
    var width0 = Math.max(mount.clientWidth || 640, 320);
    var labelW = Math.min(opts.labelWidth || 168, Math.round(width0 * 0.44));
    var valueW = 54;
    var padR = 8;
    var width = Math.max(mount.clientWidth || 640, 320);
    var barW = Math.max(60, width - labelW - valueW - padR);
    var height = rows.length * rowH + 8;

    var svg = el('svg', {
      viewBox: '0 0 ' + width + ' ' + height,
      width: width, height: height, role: 'img'
    });

    var track = cssVar('--track', '#232a34');
    var dim = cssVar('--text-dim', '#9aa7b4');
    var text = cssVar('--text', '#e6edf3');

    rows.forEach(function (r, i) {
      var y = i * rowH + 4;
      svg.appendChild(el('text', {
        x: labelW - 10, y: y + 15, 'text-anchor': 'end',
        fill: text, 'font-size': labelW < 150 ? 11 : 13
      }, r.label));

      svg.appendChild(el('rect', {
        x: labelW, y: y + 5, width: barW, height: 12, rx: 6, fill: track
      }));
      svg.appendChild(el('rect', {
        x: labelW, y: y + 5, width: Math.max(1, barW * r.value), height: 12,
        rx: 6, fill: r.color
      }));
      svg.appendChild(el('text', {
        x: labelW + barW + 8, y: y + 15, fill: dim, 'font-size': 12
      }, I18n.pct(r.value)));
    });

    mount.appendChild(svg);
  }

  /* ---------------------------------------------------------------------
     Interval plot — first-round share, 90% and 50% bands plus the median.

     Intervals are conditional on the candidate standing. An unconditional
     interval would fold in every simulated world where they are not on the
     ballot and report a 5th percentile of zero for half the field.
     --------------------------------------------------------------------- */
  function intervalPlot(mount, rows, opts) {
    opts = opts || {};
    clear(mount);
    if (!rows.length) return;

    var rowH = 34;
    var width0 = Math.max(mount.clientWidth || 640, 320);
    var labelW = Math.min(opts.labelWidth || 168, Math.round(width0 * 0.44));
    var padR = 40;
    var width = Math.max(mount.clientWidth || 640, 320);
    var plotW = Math.max(80, width - labelW - padR);
    var height = rows.length * rowH + 34;

    var maxV = 0;
    rows.forEach(function (r) { if (r.q95 > maxV) maxV = r.q95; });
    var xmax = Math.min(1, Math.ceil((maxV + 0.02) * 20) / 20);
    var x = function (v) { return labelW + (v / xmax) * plotW; };

    var svg = el('svg', {
      viewBox: '0 0 ' + width + ' ' + height,
      width: width, height: height, role: 'img'
    });

    var border = cssVar('--border', '#262d38');
    var dim = cssVar('--text-dim', '#9aa7b4');
    var faint = cssVar('--text-faint', '#7d8894');
    var text = cssVar('--text', '#e6edf3');

    // gridlines every 5 points
    for (var g = 0; g <= xmax + 1e-9; g += 0.05) {
      svg.appendChild(el('line', {
        x1: x(g), y1: 18, x2: x(g), y2: height - 18,
        stroke: border, 'stroke-width': 1
      }));
      svg.appendChild(el('text', {
        x: x(g), y: height - 4, 'text-anchor': 'middle', fill: faint, 'font-size': 10
      }, I18n.pct(g)));
    }

    rows.forEach(function (r, i) {
      var y = 22 + i * rowH + rowH / 2 - 6;
      svg.appendChild(el('text', {
        x: labelW - 10, y: y + 4, 'text-anchor': 'end', fill: text, 'font-size': labelW < 150 ? 11 : 13
      }, r.label));

      svg.appendChild(el('line', {
        x1: x(r.q05), y1: y, x2: x(r.q95), y2: y,
        stroke: r.color, 'stroke-width': 3, 'stroke-linecap': 'round', opacity: 0.45
      }));
      svg.appendChild(el('line', {
        x1: x(r.q25), y1: y, x2: x(r.q75), y2: y,
        stroke: r.color, 'stroke-width': 9, 'stroke-linecap': 'round', opacity: 0.85
      }));
      svg.appendChild(el('circle', {
        cx: x(r.q50), cy: y, r: 4.5, fill: cssVar('--bg-elev', '#161b22'),
        stroke: r.color, 'stroke-width': 2.5
      }));
      svg.appendChild(el('text', {
        x: x(r.q95) + 8, y: y + 4, fill: dim, 'font-size': 11
      }, I18n.pct(r.q50, 1)));
    });

    mount.appendChild(svg);
  }

  /* ---------------------------------------------------------------------
     Trend lines.
     --------------------------------------------------------------------- */
  function trendLines(mount, trend, meta, legendMount) {
    clear(mount);
    if (legendMount) clear(legendMount);
    if (!trend || !trend.dates || !trend.dates.length) return;

    var width = Math.max(mount.clientWidth || 720, 320);
    var height = Math.min(360, Math.max(240, width * 0.42));
    var padL = 40, padR = 12, padT = 12, padB = 26;
    var plotW = width - padL - padR;
    var plotH = height - padT - padB;

    var dates = trend.dates.map(function (d) { return Date.parse(d); });
    var t0 = dates[0], t1 = dates[dates.length - 1];

    var series = [];
    var maxV = 0.05;
    Object.keys(trend.series).forEach(function (cid) {
      var vals = trend.series[cid];
      vals.forEach(function (v) { if (v > maxV) maxV = v; });
      series.push({ id: cid, values: vals });
    });
    if (!series.length) return;
    var ymax = Math.min(1, Math.ceil((maxV + 0.02) * 20) / 20);

    var x = function (t) { return padL + ((t - t0) / (t1 - t0)) * plotW; };
    var y = function (v) { return padT + plotH - (v / ymax) * plotH; };

    var svg = el('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: width, height: height, role: 'img'
    });

    var border = cssVar('--border', '#262d38');
    var faint = cssVar('--text-faint', '#7d8894');

    for (var g = 0; g <= ymax + 1e-9; g += 0.05) {
      svg.appendChild(el('line', {
        x1: padL, y1: y(g), x2: width - padR, y2: y(g), stroke: border, 'stroke-width': 1
      }));
      svg.appendChild(el('text', {
        x: padL - 6, y: y(g) + 3, 'text-anchor': 'end', fill: faint, 'font-size': 10
      }, I18n.pct(g)));
    }

    // A tick at the start of each quarter keeps the axis readable across a
    // window that is two and a half years wide.
    var seen = {};
    trend.dates.forEach(function (iso, i) {
      var m = iso.slice(0, 7);
      var mm = +iso.slice(5, 7);
      if (mm % 6 !== 1 || seen[m]) return;
      seen[m] = true;
      svg.appendChild(el('text', {
        x: x(dates[i]), y: height - 8, 'text-anchor': 'middle', fill: faint, 'font-size': 10
      }, iso.slice(0, 4) + '-' + iso.slice(5, 7)));
    });

    series.sort(function (a, b) {
      return b.values[b.values.length - 1] - a.values[a.values.length - 1];
    });

    series.forEach(function (s) {
      var colour = meta.colourOf(s.id);
      var d = '';
      s.values.forEach(function (v, i) {
        d += (i ? 'L' : 'M') + x(dates[i]).toFixed(1) + ' ' + y(v).toFixed(1) + ' ';
      });
      svg.appendChild(el('path', {
        d: d, fill: 'none', stroke: colour, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      }));
      if (legendMount) {
        var item = document.createElement('span');
        item.className = 'legend-item';
        var sw = document.createElement('span');
        sw.className = 'legend-swatch';
        sw.style.background = colour;
        item.appendChild(sw);
        item.appendChild(document.createTextNode(meta.nameOf(s.id)));
        legendMount.appendChild(item);
      }
    });

    mount.appendChild(svg);
  }

  global.Charts = {
    probabilityBars: probabilityBars,
    intervalPlot: intervalPlot,
    trendLines: trendLines
  };
})(window);
