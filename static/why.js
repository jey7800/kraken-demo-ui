"use strict";
/* Page 2: a website changes. A classic scraper breaks; Kraken detects, repairs, checks.
   The Kraken side replays a real repair recorded from Retrievr's tests (films/stories.json). */
(function () {
  const $ = (id) => document.getElementById(id);
  const fmtInt = new Intl.NumberFormat("en-GB");
  const money = (v, d) => {
    v = v || 0;
    const digits = d ?? (v > 0 && v < 0.01 ? 4 : (v >= 1000 ? 0 : 2));
    return "€" + v.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const KS = () => window.KS || { paused: false, speed: 1, ai: "SecureGPT" };
  function sleep(ms) {
    return new Promise((res) => {
      let left = ms, last = performance.now();
      (function tick() {
        const now = performance.now();
        if (!KS().paused) left -= (now - last) * KS().speed;
        last = now;
        left <= 0 ? res() : setTimeout(tick, Math.min(30, Math.max(4, left / KS().speed)));
      })();
    });
  }

  let data = null, story = null, built = false, playing = 0;
  const calc = { sites: 60, changes: 2, devDays: 3, rate: 700, downtime: 5 };

  const HTML = `
  <div class="why">
    <header class="why-head">
      <div>
        <h1>A website changes overnight. Then what?</h1>
        <p class="why-lede" id="why-lede"></p>
      </div>
      <div class="why-controls">
        <div class="mode" role="group" aria-label="Kind of change" id="why-kinds"></div>
        <button class="btn primary" id="why-play">Change the website</button>
      </div>
    </header>

    <section class="why-race">
      <article class="lane classic" aria-label="Typical classic scraper">
        <h2>Typical classic scraper</h2>
        <ol class="tl" id="tl-classic"></ol>
        <div class="lane-total"><div><b id="cl-time">—</b><span>until data is back</span></div><div><b id="cl-cost">—</b><span>developer cost</span></div></div>
      </article>

      <div class="site">
        <div class="browser">
          <div class="chrome"><i></i><i></i><i></i><span id="site-url"></span></div>
          <div class="page-a" id="page-a"></div>
          <div class="page-b" id="page-b"></div>
        </div>
        <p class="site-cap" id="site-cap"></p>
      </div>

      <article class="lane kraken" aria-label="Kraken 2.0">
        <h2>Kraken 2.0 + <span class="ainame">SecureGPT</span></h2>
        <ol class="tl" id="tl-kraken"></ol>
        <div class="lane-total"><div><b id="kr-time">—</b><span>until data is back</span></div><div><b id="kr-cost">—</b><span>AI cost</span></div></div>
      </article>
    </section>

    <section class="why-calc" aria-label="Maintenance cost avoided">
      <div class="calc-in">
        <h2>Across all your sites, every year</h2>
        <label>Sites collected <output id="o-sites"></output><input type="range" id="c-sites" min="5" max="500" step="5"></label>
        <label>Changes per site per year <output id="o-changes"></output><input type="range" id="c-changes" min="1" max="6" step="1"></label>
        <label>Developer days per fix <output id="o-devdays"></output><input type="range" id="c-devdays" min="1" max="10" step="1"></label>
        <label>Developer day rate <output id="o-rate"></output><input type="range" id="c-rate" min="300" max="1500" step="50"></label>
      </div>
      <div class="calc-out">
        <div class="vs classic"><span>Classic scrapers</span><b id="r-classic"></b><small id="r-classic-d"></small></div>
        <div class="vs kraken"><span>Kraken 2.0</span><b id="r-kraken"></b><small id="r-kraken-d"></small></div>
        <div class="vs saved"><span>Maintenance avoided</span><b id="r-saved"></b><small>every year</small></div>
      </div>
      <div class="newsite" id="newsite" hidden>
        <h3>And a brand-new site?</h3>
        <p id="newsite-text"></p>
      </div>
    </section>
  </div>`;

  function build() {
    $("page-why").innerHTML = HTML;
    document.querySelectorAll("#page-why .ainame").forEach((n) => (n.textContent = KS().ai || "SecureGPT"));
    const bind = (id, key, fmt) => {
      const input = $("c-" + id);
      input.value = calc[key];
      const paint = () => { calc[key] = Number(input.value); $("o-" + id).textContent = fmt(calc[key]); paintCalc(); };
      input.addEventListener("input", paint);
      paint();
    };
    bind("sites", "sites", (v) => fmtInt.format(v));
    bind("changes", "changes", (v) => String(v));
    bind("devdays", "devDays", (v) => `${v} day${v > 1 ? "s" : ""}`);
    bind("rate", "rate", (v) => money(v, 0));
    $("why-play").addEventListener("click", () => play());
    built = true;
  }

  function choose(id) {
    story = data.stories.find((s) => s.id === id) || data.stories[0];
    $("why-kinds").innerHTML = data.stories.map((s) =>
      `<button aria-pressed="${s.id === story.id}" data-id="${s.id}">${s.id === "rebuilt" ? "Page rebuilt" : "Page restyled"}</button>`).join("");
    $("why-kinds").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { choose(b.dataset.id); reset(); }));
    $("why-lede").textContent = `Real case, replayed: ${story.issuer}. ${story.label}.`;
    paintCalc();
    reset();
  }

  /* ---------- the website ---------- */
  function siteCards() {
    const titles = (story.titles.length ? story.titles : ["Annual report", "Half-year report", "Q3 results"]).slice(0, 6);
    $("page-a").innerHTML = `<div class="pa-head"><b>Financial results</b><span>${story.documents_before} documents</span></div>
      <div class="pa-grid">${titles.map((t) => `<div class="pa-card"><i>PDF</i><span>${esc(t)}</span></div>`).join("")}</div>`;
    $("page-b").innerHTML = `<div class="pb-head"><b>Publications</b><span class="pb-filter">Filter ▾</span></div>
      <div class="pb-list">${titles.map((t, i) => `<div class="pb-row" style="--i:${i}"><span>${esc(t)}</span><em>Download</em></div>`).join("")}</div>`;
    $("site-url").textContent = story.issuer === "Société Générale" ? "investors.societegenerale.com/…" : "credit-agricole.com/finance/…";
  }

  /* ---------- timelines ---------- */
  function classicItems() {
    return [
      { t: "Runs every night", s: "Same page, same code.", cls: "ok" },
      { t: "Finds 0 documents", s: "The code still looks for the old page. Nobody is warned.", cls: "bad", day: 1 },
      { t: "A business user notices missing reports", s: "Days later, during a closing.", day: 2 },
      { t: "Ticket to IT", s: "Waiting for a developer who knows this scraper.", day: 3 },
      { t: "The scraper is rewritten, tested, redeployed", s: `${calc.devDays} developer days.`, day: 5 },
      { t: "Back online", s: "Until the next change, on this site or another.", cls: "ok", day: 5 },
    ];
  }
  function krakenItems() {
    const ai = KS().ai || "SecureGPT";
    const relocated = story.rungs.find((r) => r.rung === "relocate");
    const aiRung = story.rungs.find((r) => r.rung.startsWith("llm"));
    const items = [
      { t: "Runs every night", s: "Recipe replayed, zero AI.", cls: "ok" },
      { t: "Health check: the site has changed", s: `0 of ${story.documents_before} known documents listed. Kraken stops before collecting anything wrong.`, cls: "warn" },
      { t: relocated && relocated.passed ? "Fixed without AI" : "Quick fix without AI: not enough",
        s: relocated && relocated.passed ? "The same blocks were found under their new names." : "The list is no longer in the page itself.",
        cls: relocated && relocated.passed ? "ok" : "warn" },
    ];
    if (aiRung) items.push({ t: `${ai} studies the new page and writes a new recipe`, s: "", cls: "ai", ai: true });
    items.push({ t: "5 checks before anything is used", s: "", cls: "check", checks: true });
    items.push({ t: "Back online", s: `${story.documents_after} of ${story.documents_before} documents, same as before.`, cls: "ok", end: true });
    return items;
  }
  function renderLane(id, items) {
    $(id).innerHTML = items.map((it, i) => `<li class="${it.cls || ""}" data-i="${i}">
      ${it.day ? `<em class="day">Day ${it.day}</em>` : ""}<b>${esc(it.t)}</b><span>${esc(it.s)}</span>
      ${it.ai ? '<div class="ai-meter"><span class="tok">0 tokens</span><span class="aic">€0</span></div>' : ""}
      ${it.checks ? `<ul class="mini-checks">${story.checks.map((c) => `<li title="${esc(c.detail)}">${esc(c.label)}<small>${esc(c.detail)}</small></li>`).join("")}</ul>` : ""}
    </li>`).join("");
  }
  const reveal = (lane, i) => { const li = document.querySelector(`#${lane} li[data-i="${i}"]`); if (li) li.classList.add("on"); return li; };

  function reset() {
    playing++;
    siteCards();
    $("page-a").classList.remove("gone");
    $("page-b").classList.remove("on");
    $("site-cap").textContent = "Today: the list of documents is written in the page.";
    renderLane("tl-classic", classicItems());
    renderLane("tl-kraken", krakenItems());
    reveal("tl-classic", 0); reveal("tl-kraken", 0);
    ["cl-time", "cl-cost", "kr-time", "kr-cost"].forEach((id) => ($(id).textContent = "—"));
    $("why-play").textContent = "Change the website";
  }

  async function play() {
    if ($("why-play").textContent !== "Change the website") { reset(); return; }
    const run = ++playing;
    const alive = () => run === playing;
    $("why-play").textContent = "Reset";
    $("page-a").classList.add("gone");
    await sleep(500);
    $("page-b").classList.add("on");
    $("site-cap").textContent = story.id === "rebuilt"
      ? "Overnight: same documents, but the list now loads from a hidden data feed."
      : "Overnight: same documents, but every building block of the page has a new name.";
    await sleep(1400);
    if (!alive()) return;
    classic(alive);
    await kraken(alive);
  }

  async function classic(alive) {
    const items = classicItems();
    for (let i = 1; i < items.length; i++) {
      await sleep(i === 1 ? 900 : 3600);
      if (!alive()) return;
      reveal("tl-classic", i);
      if (items[i].day) $("cl-time").textContent = `Day ${items[i].day}…`;
    }
    $("cl-time").textContent = `${calc.downtime} days`;
    $("cl-cost").textContent = money(calc.devDays * calc.rate, 0);
  }

  async function kraken(alive) {
    const items = krakenItems();
    const ai = KS().ai || "SecureGPT";
    let clock = 0;
    for (let i = 1; i < items.length; i++) {
      await sleep(900);
      if (!alive()) return;
      const li = reveal("tl-kraken", i);
      const it = items[i];
      if (it.ai) {
        li.classList.add("thinking");
        const tokens = story.input_tokens + story.output_tokens;
        const steps = 30;
        for (let k = 1; k <= steps; k++) {
          await sleep(60);
          if (!alive()) return;
          li.querySelector(".tok").textContent = `${fmtInt.format(Math.round(tokens * k / steps))} tokens`;
          li.querySelector(".aic").textContent = money(story.cost * k / steps, 4);
        }
        li.classList.remove("thinking");
        li.querySelector("span").textContent = `One call, ${story.ai_seconds} s of thinking.`;
      }
      if (it.checks) {
        for (const c of li.querySelectorAll(".mini-checks > li")) { await sleep(380); if (!alive()) return; c.classList.add("ok"); }
      }
      if (it.end) {
        clock = story.estimated_seconds;
        $("kr-time").textContent = clock < 90 ? `≈ ${clock} seconds` : `≈ ${Math.round(clock / 60)} minutes`;
        $("kr-cost").textContent = story.cost ? money(story.cost) : `€0, no ${ai} call`;
      }
    }
  }

  /* ---------- calculator ---------- */
  function paintCalc() {
    if (!built) return;
    const fixes = calc.sites * calc.changes;
    const classic = fixes * calc.devDays * calc.rate;
    const perRepair = story ? story.cost : 0.0011;
    const kraken = fixes * perRepair;
    $("r-classic").textContent = money(classic, 0);
    $("r-classic-d").textContent = `${fmtInt.format(fixes)} fixes, ${fmtInt.format(fixes * calc.downtime)} site-days without data`;
    $("r-kraken").textContent = money(kraken, kraken < 10 ? 2 : 0);
    $("r-kraken-d").textContent = `${fmtInt.format(fixes)} self-repairs, checked, in minutes each`;
    $("r-saved").textContent = money(classic - kraken, 0);
  }

  function newSite() {
    const l = data.learn;
    if (!l) { $("newsite").hidden = true; return; }
    const mins = Math.max(1, Math.round((l.seconds || 0) / 60));
    $("newsite").hidden = false;
    $("newsite-text").innerHTML = `${esc(l.name)} was learned from scratch in <b>${mins} minute${mins > 1 ? "s" : ""}</b>,
      with <b>${l.ai_calls} ${esc(KS().ai || "SecureGPT")} calls</b> for <b>${money(l.cost)}</b>: ${l.found ?? "its"} documents found, then replayed every night with no AI.`;
  }

  window.Why = {
    async show() {
      if (!built) build();
      data = await fetch("/api/stories").then((r) => r.json()).catch(() => ({}));
      if (!data.stories || !data.stories.length) {
        $("why-lede").textContent = "No recorded repair yet: run tools/record_stories.py once.";
        return;
      }
      if (!story) choose("rebuilt"); else paintCalc();
      newSite();
    },
    play,
  };
  document.addEventListener("keydown", (ev) => {
    if ($("page-why").hidden || ev.target.closest("input")) return;
    if (ev.key === "Enter") { ev.preventDefault(); play(); }
  });
})();
