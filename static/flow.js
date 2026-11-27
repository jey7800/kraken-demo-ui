"use strict";
/* The diagram of a Kraken run: stations, edges, the AI orb. Exposes window.Flow. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  const $ = (id) => document.getElementById(id);

  /* Scale the 1920 px canvas to the window, like a slide. A 16:10 window keeps the full
     width and gets a taller canvas (more room for the diagram); a window wider than 16:9
     keeps 1080 px of height and is centred. 1920x1200 at 150% gives a 1280 px wide
     window: scale 2/3, so the page shows exactly the pixels of 1920x1080 at 100%. */
  const W = 1920, H = 1080;
  const FIT = (window.FIT = { s: 1, ox: 0 });
  function fit() {
    const app = document.querySelector(".app");
    let s = window.innerWidth / W, h = window.innerHeight / s, ox = 0;
    if (h < H) { s = window.innerHeight / H; h = H; ox = (window.innerWidth - W * s) / 2; }
    app.style.height = h + "px";
    app.style.transform = `translate(${ox}px, 0) scale(${s})`;
    FIT.s = s; FIT.ox = ox;
  }
  window.addEventListener("resize", fit);
  fit();
  /* A screen rectangle in canvas coordinates. */
  function toCanvas(r) {
    const left = (r.left - FIT.ox) / FIT.s, top = r.top / FIT.s, width = r.width / FIT.s, height = r.height / FIT.s;
    return { left, top, width, height, right: left + width, bottom: top + height };
  }

  /* seabed contours, the only decoration */
  (function contours() {
    const svg = $("contours");
    svg.setAttribute("viewBox", "0 0 1920 1080");
    svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
    for (let i = 0; i < 14; i++) {
      const cx = 1520, cy = 920, rx = 160 + i * 95, ry = 90 + i * 55;
      let d = "";
      for (let a = 0; a <= 360; a += 6) {
        const t = a * Math.PI / 180;
        const wob = 1 + .06 * Math.sin(3 * t + i * .7) + .04 * Math.sin(5 * t - i);
        d += (a ? "L" : "M") + (cx + rx * wob * Math.cos(t)).toFixed(1) + " " + (cy + ry * wob * Math.sin(t)).toFixed(1);
      }
      el("path", { d: d + "Z", fill: "none", stroke: i % 3 ? "#1e2a78" : "#5a1030", "stroke-width": 1, opacity: (0.6 - i * .035).toFixed(2) }, svg);
    }
  })();

  const ICONS = {
    globe: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M3 12h18M12 3c3.5 3 3.5 15 0 18M12 3c-3.5 3-3.5 15 0 18",
    lock: "M7.5 11V8a4.5 4.5 0 0 1 9 0v3 M5.5 11h13v9.5h-13z M12 14.5v2.5",
    spark: "M11 3l1.9 5.6L18.5 10.5l-5.6 1.9L11 18l-1.9-5.6L3.5 10.5l5.6-1.9z M18.5 15.5l.8 2.2l2.2.8l-2.2.8l-.8 2.2l-.8-2.2l-2.2-.8l2.2-.8z",
    replay: "M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v4h4 M10.5 9l4.5 3l-4.5 3z",
    list: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
    wrench: "M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3l5.3-5.3a4 4 0 0 0 5.4-5.4l-2.4 2.4l-2.6-.4l-.4-2.6z",
    check: "M12 3l7 3v6c0 4.5-3 7.5-7 9c-4-1.5-7-4.5-7-9V6z M8.8 12l2.2 2.2l4.2-4.4",
    tag: "M3.5 12.5V4.5h8l9 9l-8 8z M8 8.5h.01",
    download: "M12 4v11M7.5 10.5L12 15l4.5-4.5M5 20h14",
    folder: "M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  };
  const MAIN = 235, UP = 85;
  const STATIONS = [
    { id: "site", x: 60, y: MAIN, label: "Website", icon: "globe" },
    { id: "access", x: 200, y: MAIN, label: "Private or public?", gate: true },
    { id: "auth", x: 345, y: UP, label: "Sign-in", icon: "lock" },
    { id: "known", x: 490, y: MAIN, label: "Known site?", gate: true },
    { id: "learn", x: 690, y: UP, label: "AI learns the site", icon: "spark", tone: "ai" },
    { id: "replay", x: 690, y: MAIN, label: "Replay, no AI", icon: "replay" },
    { id: "read", x: 860, y: MAIN, label: "Read listings", icon: "list" },
    { id: "health", x: 1020, y: MAIN, label: "Site changed?", gate: true },
    { id: "repair", x: 1160, y: UP, label: "Self-repair", icon: "wrench", tone: "amber" },
    { id: "verify", x: 1310, y: UP, label: "5 checks", icon: "check", tone: "amber" },
    { id: "classify", x: 1450, y: MAIN, label: "Classify", icon: "tag" },
    { id: "download", x: 1600, y: MAIN, label: "Verified download", icon: "download" },
    { id: "store", x: 1740, y: MAIN, label: "Filed", icon: "folder" },
  ];
  const EDGES = {
    e1: { d: "M100 235H158" },
    eA: { d: "M200 193C200 125 255 85 305 85", label: ["private", 188, 132, "", "end"] },
    eB: { d: "M385 85C430 85 415 235 448 235" },
    eP: { d: "M242 235H448", label: ["public", 330, 222] },
    e3: { d: "M490 193C490 125 570 85 650 85", label: ["new site", 506, 172, "ai", "start"] },
    e4: { d: "M532 235H650", label: ["known recipe", 591, 222] },
    e5: { d: "M730 85C810 85 860 130 860 195" },
    e6: { d: "M730 235H820" },
    e7: { d: "M900 235H978" },
    e8: { d: "M1020 193C1020 125 1070 85 1120 85", label: ["change detected", 1036, 174, "amber", "start"], amber: true },
    e9: { d: "M1062 235H1410", label: ["no change", 1236, 222] },
    e10: { d: "M1200 85H1270", amber: true },
    e11: { d: "M1350 85C1420 85 1450 130 1450 195", amber: true },
    e12: { d: "M1490 235H1560" },
    e13: { d: "M1640 235H1700" },
  };
  const FILS = {
    a1: "M890 64C840 28 760 32 718 57",
    a2: "M960 64C1010 28 1095 32 1132 57",
    a3: "M948 108C1040 200 1340 205 1412 222",
  };
  const EDGE_OF = {
    "site>access": "e1", "access>auth": "eA", "auth>known": "eB", "access>known": "eP",
    "known>learn": "e3", "known>replay": "e4", "learn>read": "e5", "replay>read": "e6",
    "read>health": "e7", "health>repair": "e8", "health>classify": "e9", "repair>verify": "e10",
    "verify>classify": "e11", "classify>download": "e12", "download>store": "e13",
  };
  const SKIPS = {
    auth: ["eP"], eP: ["eA", "auth", "eB"],
    learn: ["e4", "replay", "e6"], replay: ["e3", "learn", "e5"],
    repair: ["e9"], e9: ["e8", "repair", "e10", "verify", "e11"],
  };

  const edgesG = $("edges"), filsG = $("fils"), stG = $("stations");
  for (const [id, e] of Object.entries(EDGES)) {
    el("path", { d: e.d, id, class: "edge" + (e.amber ? " amber" : "") }, edgesG);
    if (e.label) {
      const [txt, x, y, tone, anchor] = e.label;
      el("text", { x, y, id: id + "-l", class: "elabel" + (tone ? " " + tone : ""), "text-anchor": anchor || "middle" }, edgesG).textContent = txt;
    }
  }
  for (const [id, d] of Object.entries(FILS)) el("path", { d, id, class: "fil" + (id === "a3" ? " ghost" : "") }, filsG);
  for (const s of STATIONS) {
    const g = el("g", { transform: `translate(${s.x} ${s.y})`, id: "st-" + s.id, class: "st" + (s.tone ? " " + s.tone : "") }, stG);
    const body = el("g", { class: "body" }, g);
    el("circle", { r: 56, class: "halo" }, body);
    if (s.gate) {
      el("rect", { x: -30, y: -30, width: 60, height: 60, rx: 9, transform: "rotate(45)", class: "ring" }, body);
      el("text", { class: "gate-q", "text-anchor": "middle", y: 10 }, body).textContent = "?";
    } else {
      el("circle", { r: 40, class: "ring" }, body);
      el("path", { d: ICONS[s.icon], transform: "translate(-17 -17) scale(1.42)", class: "ico" }, body);
    }
    el("text", { y: s.gate ? 72 : 66, class: "lbl", "text-anchor": "middle" }, g).textContent = s.label;
  }
  const orb = el("g", { transform: "translate(925 80)", class: "orb", id: "orb" }, stG);
  el("circle", { r: 70, class: "glow" }, orb);
  el("circle", { r: 36, class: "core" }, orb);
  el("path", { d: ICONS.spark, transform: "translate(-16 -16) scale(1.35)", class: "spark" }, orb);
  const orbName = el("text", { y: -50, class: "name", "text-anchor": "middle" }, orb);
  orbName.textContent = "SecureGPT";
  el("text", { x: 50, y: 50, class: "tok", id: "tok" }, orb);

  let current = null;
  const node = (id) => $(id) || $("st-" + id);

  window.Flow = {
    setAIName(name) { orbName.textContent = name; },
    reset() {
      document.querySelectorAll(".st").forEach((n) => n.classList.remove("active", "done", "skipped", "failed"));
      document.querySelectorAll(".edge").forEach((n) => n.classList.remove("lit", "done", "skipped"));
      document.querySelectorAll(".elabel").forEach((n) => n.classList.remove("on"));
      document.querySelectorAll(".fil").forEach((n) => n.classList.remove("lit"));
      $("orb").classList.remove("calling");
      $("tok").textContent = "";
      current = null;
    },
    get current() { return current; },
    /* Move to ``step``: light the edge from the current station, then activate it. */
    async enter(step, sleep) {
      const prev = current;
      if (prev) { node(prev).classList.remove("active"); node(prev).classList.add("done"); }
      const edge = prev ? EDGE_OF[prev + ">" + step] : null;
      for (const key of [step, edge]) (SKIPS[key] || []).forEach((id) => node(id).classList.add("skipped"));
      if (edge) {
        const e = $(edge);
        e.classList.add("lit");
        const l = $(edge + "-l"); if (l) l.classList.add("on");
        await sleep(520);
        e.classList.remove("lit"); e.classList.add("done");
      }
      current = step;
      node(step).classList.add("active");
    },
    finish() {
      if (current) { node(current).classList.remove("active"); node(current).classList.add("done"); }
      current = null;
    },
    fail(step) { node(step).classList.add("failed"); },
    aiOn(link) { $("orb").classList.add("calling"); if (link) $(link).classList.add("lit"); },
    aiOff() { $("orb").classList.remove("calling"); document.querySelectorAll(".fil").forEach((n) => n.classList.remove("lit")); $("tok").textContent = ""; },
    tok(text) { $("tok").textContent = text; },
    centerOf(id) {
      const r = toCanvas(node(id).querySelector(".ring").getBoundingClientRect());
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, r };
    },
  };
})();
