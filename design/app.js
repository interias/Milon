/* Milon · Design-Exploration — Playground-Logik (vanilla JS, keine Build-Tools).
   Eine Referenz-Oberflaeche, 11 umschaltbare Themes (nur CSS-Variablen),
   plus Dichte-, Ansicht- und Asset-Schalter. */

(() => {
  "use strict";
  const THEMES = window.MILON_THEMES;
  const ICONS = window.MILON_ICONS;
  const root = document.documentElement;

  const TOKENS = [
    "bg", "surface", "surfaceAlt", "text", "textMuted", "border",
    "accent", "accentContrast", "accent2", "good", "warn", "bad",
    "radius", "shadow", "fontDisplay", "fontBody",
    "chartGrid", "chartLine", "chartFill",
  ];

  // ---------------------------------------------------- Mock-Daten (Demo)
  const MOCK = {
    date: "Mo · 23. Juni",
    koerper: { value: "72,3", unit: "kg", delta: "▼ 0,4 kg / 7 T", kind: "good",
      a: ["TDEE", "2.480 kcal"], b: ["KFA-Trend", "18,2 %"],
      spark: [74.1, 73.8, 73.9, 73.4, 73.1, 73.2, 72.8, 72.6, 72.7, 72.3] },
    laufen: { value: "38,2", unit: "km/Wo", delta: "▲ 6,1 km", kind: "good",
      a: ["Pace ø", "5:12 /km"], b: ["VO₂max", "52"],
      spark: [22, 28, 25, 31, 27, 34, 30, 33, 36, 38] },
    kraft: { value: "142", unit: "kg e1RM", delta: "▲ 4 kg", kind: "good",
      a: ["Tonnage", "12,4 t"], b: ["RPE ø", "7,5"],
      spark: [128, 130, 131, 133, 134, 136, 138, 139, 140, 142] },
    weight90: [74.8, 74.6, 74.9, 74.3, 74.4, 73.9, 74.1, 73.6, 73.8, 73.3,
      73.5, 73.0, 73.2, 72.8, 72.9, 72.5, 72.7, 72.3, 72.5, 72.1, 72.3],
    coach:
      "Diese Woche zeigt klar nach vorn: <b>Gewicht</b> −0,4 kg im 7-Tage-Mittel bei stabiler Tonnage — du hältst Kraft im Defizit. <b>Laufvolumen</b> +6 km, aber die Pace stagniert. Eine konkrete Anpassung: ein lockerer Dauerlauf weniger, dafür ein Intervall. Höhenmeter fürs Beast bleiben die tote Stelle.",
  };
  const LABEL = { koerper: "Körper", laufen: "Laufen", kraft: "Kraft" };
  const SUB = { koerper: "Gewicht & TDEE", laufen: "Volumen & Tempo", kraft: "Kraftaufbau" };

  // -------------------------------------------------------- SVG-Helfer
  let _uid = 0;
  const nextId = () => "mc" + ++_uid;

  function pts(vals, w, h, pad) {
    const min = Math.min(...vals), max = Math.max(...vals), range = (max - min) || 1, n = vals.length;
    return vals.map((v, i) => [
      pad + (i / (n - 1)) * (w - 2 * pad),
      pad + (1 - (v - min) / range) * (h - 2 * pad),
    ]);
  }
  const lineP = (p) => p.map((q, i) => (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1)).join(" ");
  const areaP = (p, h) => lineP(p) + " L" + p[p.length - 1][0].toFixed(1) + " " + h + " L" + p[0][0].toFixed(1) + " " + h + " Z";

  function grad(id, top) {
    return '<linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" style="stop-color:var(--chartLine);stop-opacity:' + top + '"/>' +
      '<stop offset="1" style="stop-color:var(--chartLine);stop-opacity:0"/></linearGradient>';
  }
  function spark(vals) {
    const id = nextId(), p = pts(vals, 100, 32, 3);
    return '<svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">' +
      "<defs>" + grad(id, ".28") + "</defs>" +
      '<path d="' + areaP(p, 32) + '" fill="url(#' + id + ')"/>' +
      '<path d="' + lineP(p) + '" fill="none" style="stroke:var(--chartLine)" stroke-width="2" ' +
      'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>';
  }
  function areaChart(vals) {
    const id = nextId(), W = 100, H = 42, p = pts(vals, W, H, 4);
    const grid = [0.25, 0.5, 0.75].map((g) =>
      '<line x1="0" x2="' + W + '" y1="' + (H * g).toFixed(1) + '" y2="' + (H * g).toFixed(1) +
      '" style="stroke:var(--chartGrid)" stroke-width="1" vector-effect="non-scaling-stroke"/>').join("");
    return '<svg class="area" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" aria-hidden="true">' +
      "<defs>" + grad(id, ".32") + "</defs>" + grid +
      '<path d="' + areaP(p, H) + '" fill="url(#' + id + ')"/>' +
      '<path d="' + lineP(p) + '" fill="none" style="stroke:var(--chartLine)" stroke-width="2.5" ' +
      'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>';
  }

  // ---------------------------------------------------- Markup-Bausteine
  function card(domain, m) {
    return '<div class="card"><div class="card-head">' +
      '<div class="card-ico" aria-hidden="true"><span class="glyph">' + ICONS.glyphs[domain] + "</span>" +
      '<img alt="" onload="this.parentNode.classList.add(\'has-img\')" src="assets/' + domain + '.png"></div>' +
      '<div><div class="card-label">' + LABEL[domain] + '</div><div class="card-sub">' + SUB[domain] + "</div></div></div>" +
      '<div class="kpi-row"><span class="kpi-value">' + m.value + '</span><span class="kpi-unit">' + m.unit + "</span></div>" +
      '<span class="delta ' + m.kind + '">' + m.delta + "</span>" +
      spark(m.spark) +
      '<div class="subrow"><span>' + m.a[0] + " <b>" + m.a[1] + "</b></span><span>" + m.b[0] + " <b>" + m.b[1] + "</b></span></div></div>";
  }

  function dashboard() {
    return '<div class="frame-head"><div><div class="title">Übersicht</div>' +
      '<div class="date">' + MOCK.date + '</div></div><span class="pill">● Coach-Snapshot bereit</span></div>' +
      '<div class="kpi-grid">' + card("koerper", MOCK.koerper) + card("laufen", MOCK.laufen) + card("kraft", MOCK.kraft) + "</div>" +
      '<div class="wide-grid"><div class="card chart-card"><h3>Gewicht · 90 Tage</h3>' +
      '<div class="chart-sub">7-Tage-EWMA · Defizit greift, Wasser-Rauschen gefiltert</div>' + areaChart(MOCK.weight90) + "</div>" +
      '<div class="card coach"><div class="coach-top"><div class="coach-ava">' +
      '<img alt="" src="assets/coach.png"></div><div><div class="coach-name">Coach</div>' +
      '<div class="coach-role">ehrlich-motivierend</div></div></div>' +
      '<div class="coach-msg">' + MOCK.coach + "</div>" +
      '<span class="chip">⛰ Höhenmeter: nicht verfügbar</span></div></div>';
  }

  const firstFamily = (stack) => {
    const m = String(stack).match(/^\s*['"]?([^'",]+)['"]?/);
    return m ? m[1].trim() : stack;
  };
  function moodboard(t) {
    const sw = [["bg", "BG"], ["surface", "Surface"], ["accent", "Accent"], ["accent2", "Accent 2"], ["good", "Good"], ["bad", "Bad"]]
      .map(([k]) => '<div class="swatch" title="' + k + ": " + t.tokens[k] + '" style="background:' + t.tokens[k] + '"></div>').join("");
    return '<div class="moodboard"><h4>' + t.name + '</h4><div class="mood">' + t.mood + "</div>" +
      '<div class="swatches">' + sw + "</div>" +
      '<div class="mood-row"><span>Display</span><span>' + firstFamily(t.tokens.fontDisplay) + "</span></div>" +
      '<div class="mood-row"><span>Body</span><span>' + firstFamily(t.tokens.fontBody) + "</span></div>" +
      '<div class="mood-row"><span>Radius</span><span>' + t.tokens.radius + "</span></div>" +
      '<div class="mood-row"><span>Akzent</span><span>' + t.tokens.accent + "</span></div>" +
      '<div class="sig"><span class="ph">Signatur-Asset<br>(generiert)</span>' +
      '<img alt="" onload="this.parentNode.classList.add(\'has-img\')" src="assets/' + t.id + '.png"></div></div>';
  }

  function tile(t) {
    const pal = ["bg", "surface", "accent", "accent2", "good", "bad"]
      .map((k) => '<i style="background:' + t.tokens[k] + '"></i>').join("");
    return '<div class="tile" tabindex="0" role="button">' +
      '<div class="tile-sig"><span class="ph">' + t.name + "</span>" +
      '<img alt="" onload="this.parentNode.classList.add(\'has-img\')" src="assets/' + t.id + '.png"></div>' +
      '<div class="tile-body"><div class="tile-name">' + t.name + "</div>" +
      '<div class="tile-mood">' + t.mood + "</div>" +
      '<div class="tile-kpis"><div class="tile-kpi"><b>72,3</b><span>kg</span></div>' +
      '<div class="tile-kpi"><b>38</b><span>km/Wo</span></div>' +
      '<div class="tile-kpi"><b>142</b><span>e1RM</span></div></div>' +
      '<div class="tile-pal">' + pal + "</div>" +
      '<div class="tile-foot"><span>' + (t.googleFonts[0] || "") + '</span><span class="badge">öffnen ›</span></div></div></div>';
  }

  // ------------------------------------------------------------- Theme
  function applyTheme(el, t) {
    TOKENS.forEach((k) => el.style.setProperty("--" + k, t.tokens[k]));
    el.setAttribute("data-treatment", t.treatment || "");
  }

  // ------------------------------------------------------------- Fonts
  const SINGLE = { Anton: "400", "Archivo Black": "400" };
  function loadFonts() {
    const fams = new Set();
    THEMES.forEach((t) => t.googleFonts.forEach((f) => fams.add(f)));
    const pre1 = document.createElement("link"); pre1.rel = "preconnect"; pre1.href = "https://fonts.googleapis.com";
    const pre2 = document.createElement("link"); pre2.rel = "preconnect"; pre2.href = "https://fonts.gstatic.com"; pre2.crossOrigin = "anonymous";
    document.head.append(pre1, pre2);
    fams.forEach((f) => {
      const w = SINGLE[f] || "300;400;500;600;700;800";
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = "https://fonts.googleapis.com/css2?family=" + f.trim().replace(/\s+/g, "+") + ":wght@" + w + "&display=swap";
      document.head.appendChild(l);
    });
  }

  // ------------------------------------------------------------- State
  const state = { index: 0, density: "normal", view: "single", assets: "on" };
  const current = () => THEMES[state.index];

  function renderSingle() {
    const frame = document.getElementById("frame");
    applyTheme(frame, current());
    frame.innerHTML = dashboard();
    document.getElementById("moodboard-slot").innerHTML = moodboard(current());
  }
  function renderGallery() {
    const g = document.getElementById("gallery");
    g.innerHTML = "";
    THEMES.forEach((t) => {
      const wrap = document.createElement("div");
      wrap.innerHTML = tile(t);
      const el = wrap.firstElementChild;
      applyTheme(el, t);
      const open = () => { state.index = THEMES.indexOf(t); setView("single"); sync(); renderSingle(); };
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
      g.appendChild(el);
    });
  }
  function setView(v) {
    state.view = v;
    document.getElementById("single-view").classList.toggle("hidden", v !== "single");
    document.getElementById("gallery-view").classList.toggle("hidden", v !== "gallery");
    if (v === "gallery") renderGallery();
    sync();
  }
  function sync() {
    document.getElementById("theme-select").value = current().id;
    document.querySelectorAll("#density-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.density === state.density)));
    document.querySelectorAll("#view-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadFonts();
    root.dataset.density = state.density;
    root.dataset.assets = state.assets;

    const sel = document.getElementById("theme-select");
    THEMES.forEach((t) => { const o = document.createElement("option"); o.value = t.id; o.textContent = t.name; sel.appendChild(o); });
    sel.addEventListener("change", () => { state.index = THEMES.findIndex((t) => t.id === sel.value); renderSingle(); });

    document.getElementById("prev").addEventListener("click", () => { state.index = (state.index - 1 + THEMES.length) % THEMES.length; sync(); renderSingle(); });
    document.getElementById("next").addEventListener("click", () => { state.index = (state.index + 1) % THEMES.length; sync(); renderSingle(); });
    document.querySelectorAll("#density-seg button").forEach((b) => b.addEventListener("click", () => { state.density = b.dataset.density; root.dataset.density = state.density; sync(); }));
    document.querySelectorAll("#view-seg button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
    document.getElementById("assets-toggle").addEventListener("change", (e) => { state.assets = e.target.checked ? "on" : "off"; root.dataset.assets = state.assets; });

    document.addEventListener("keydown", (e) => {
      if (e.target.tagName === "SELECT") return;
      if (e.key === "ArrowRight") document.getElementById("next").click();
      if (e.key === "ArrowLeft") document.getElementById("prev").click();
    });

    renderSingle();
    sync();
  });
})();
