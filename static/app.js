"use strict";
/* Page 1: the parameters table, the live event stream and its narration. */
const $ = (id) => document.getElementById(id);
const fmtInt = new Intl.NumberFormat("en-GB");
/* Amounts under one cent keep 4 decimals: "€0.0002" says more than "€0.00". */
const fmtEur = (v, d) => {
  v = v || 0;
  const digits = d ?? (v > 0 && v < 0.01 ? 4 : 2);
  return "€" + v.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const FOLDER = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>';
const LOCK = '<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="2" y="5.5" width="8" height="5.5" rx="1.2" fill="currentColor"/><path d="M4 5.5V4a2 2 0 0 1 4 0v1.5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';

const S = {
  sheet: null, results: {}, films: {}, ai: "SecureGPT", source: "live",
  speed: 1, paused: false, running: false,
  totals: { calls: 0, tokens: 0, cost: 0, docs: 0 },
  run: null, /* current row run: {id, row, calls, cost, filed, isNew, total, pages, branch, repaired} */
};
window.KS = S;

/* ---------- timing: pause and speed aware ---------- */
function sleep(ms) {
  return new Promise((res) => {
    let left = ms, last = performance.now();
    (function tick() {
      const now = performance.now();
      if (!S.paused) left -= (now - last) * S.speed;
      last = now;
      left <= 0 ? res() : setTimeout(tick, Math.min(30, Math.max(4, left / S.speed)));
    })();
  });
}
async function countUp(apply, from, to, ms) {
  const steps = Math.max(1, Math.round(ms / 40));
  for (let k = 1; k <= steps; k++) { apply(from + (to - from) * k / steps); await sleep(ms / steps); }
}

/* ---------- narration ---------- */
function say(text, sub, tone) {
  $("say").textContent = text || "";
  $("say").className = "say" + (tone ? " " + tone : "");
  $("sub").textContent = sub || "";
}
const sub = (text) => { $("sub").textContent = text || ""; };
const badge = (row) => row.private ? `<span class="badge priv">${LOCK}Private</span>` : `<span class="badge pub">Public</span>`;
function idle() {
  if (!S.sheet) {
    $("who").textContent = "";
    say("Load your Excel file, then run.", "Each row of the file becomes one Kraken run on one site.");
  } else {
    $("who").textContent = `Ready to run ${S.sheet.rows.length} sites`;
    say("Everything is ready.", S.source === "film" ? "Recorded runs: no network needed." : "Press Run all, or run a single site.");
  }
}

/* ---------- meters ---------- */
function paintMeters() {
  const t = S.totals;
  $("m-calls").textContent = fmtInt.format(t.calls);
  $("m-tokens").textContent = fmtInt.format(Math.round(t.tokens));
  $("m-cost").textContent = fmtEur(t.cost);
  $("m-docs").textContent = fmtInt.format(t.docs);
  $("m-cost-l").textContent = t.docs > 0 && t.cost > 0 ? `that is ${fmtEur(t.cost / t.docs, 4)} per document` : "AI cost";
}

/* ---------- table ---------- */
function yearsText(ys) {
  if (!ys || !ys.length) return "All";
  const sorted = [...ys].sort();
  const contiguous = sorted.every((y, i) => i === 0 || y === sorted[i - 1] + 1);
  return contiguous && sorted.length > 1 ? `${sorted[0]}–${sorted[sorted.length - 1]}` : sorted.join(", ");
}
function renderTable() {
  const tbody = $("rows");
  tbody.innerHTML = "";
  $("dropzone").hidden = !!S.sheet;
  $("file-name").textContent = S.sheet ? S.sheet.filename : "No file loaded";
  const priv = S.sheet ? S.sheet.rows.filter((r) => r.private).length : 0;
  $("file-info").textContent = S.sheet ? `${S.sheet.rows.length} sites${priv ? `, ${priv} private portal${priv > 1 ? "s" : ""}` : ""}` : "";
  if (!S.sheet) { idle(); return; }
  for (const row of S.sheet.rows) {
    const tr = document.createElement("tr");
    tr.id = "row-" + row.id;
    tr.innerHTML = `
      <td class="name" title="${esc(row.url)}">${esc(row.name)}</td>
      <td>${badge(row)}</td>
      <td class="years">${esc(yearsText(row.years))}</td>
      <td class="req" title="${esc(row.request)}">${esc(row.request || "All documents")}</td>
      <td class="force ${row.force_learn ? "yes" : ""}">${row.force_learn ? "Yes" : "No"}</td>
      <td data-c="status"></td><td data-c="found"></td><td data-c="dl"></td>
      <td data-c="ai"></td><td data-c="cost"></td><td data-c="time"></td><td data-c="health"></td>
      <td class="actions"><button class="mini" data-act="run">Run</button><button class="mini relearn" data-act="relearn">Re-learn</button><button class="mini files" data-act="files" title="Open the folder of downloaded files">${FOLDER}Files</button></td>`;
    tbody.appendChild(tr);
    paintResult(row.id, S.results[row.id]);
  }
  paintButtons();
}
function setCell(id, c, html, cls) {
  const td = document.querySelector(`#row-${CSS.escape(id)} [data-c="${c}"]`);
  if (!td) return;
  td.innerHTML = html;
  td.className = (c === "status" || c === "health" ? "" : "num ") + (cls || "");
}
const STATUS_CLASS = { Done: "ok", Learned: "learned", Repaired: "repaired" };
const HEALTH_CLASS = { Good: "good", Repaired: "fixed", "New recipe": "new" };
function duration(s) {
  if (s == null) return "—";
  const m = Math.floor(s / 60), r = String(Math.round(s % 60)).padStart(2, "0");
  return `${m} min ${r}`;
}
function paintResult(id, r) {
  if (!r) {
    setCell(id, "status", '<span class="status idle"><i></i>Ready</span>');
    ["found", "dl", "ai", "cost", "time", "health"].forEach((c) => setCell(id, c, "—", "empty"));
    return;
  }
  const cls = STATUS_CLASS[r.status_label] || "bad";
  const film = r.source === "film" ? " <small>recorded</small>" : "";
  setCell(id, "status", `<span class="status ${cls}" title="${esc(r.notes || "")}"><i></i>${esc(r.status_label)}${film}</span>`);
  setCell(id, "found", r.found ?? "—", r.found == null ? "empty" : "");
  setCell(id, "dl", r.files ?? "—", r.files == null ? "empty" : "");
  setCell(id, "ai", r.ai_calls ?? 0, r.ai_calls ? "aiv" : "zero");
  setCell(id, "cost", fmtEur(r.cost || 0), r.cost ? "aiv" : "zero");
  setCell(id, "time", duration(r.seconds));
  const h = r.health_label || "";
  setCell(id, "health", h ? `<span class="health ${HEALTH_CLASS[h] || "bad"}"><i></i>${esc(h)}</span>` : "—", h ? "" : "empty");
}
function paintButtons() {
  const film = S.source === "film";
  $("runall").textContent = S.running ? "Stop after this site" : "Run all";
  $("runall").classList.toggle("stop", S.running);
  $("runall").classList.toggle("primary", !S.running);
  $("runall").disabled = !S.sheet;
  $("export").setAttribute("aria-disabled", String(!S.sheet));
  if (!S.sheet) return;
  for (const row of S.sheet.rows) {
    const kinds = S.films[row.id] || [];
    const run = document.querySelector(`#row-${CSS.escape(row.id)} [data-act="run"]`);
    const relearn = document.querySelector(`#row-${CSS.escape(row.id)} [data-act="relearn"]`);
    if (!run) continue;
    run.disabled = S.running || (film && !kinds.length);
    relearn.disabled = S.running || (film && !kinds.includes("learn")) || row.private;
    run.title = film && !kinds.length ? "No recorded run yet" : "";
    relearn.title = row.private ? "Private portals use hand-written recipes" : (film && !kinds.includes("learn") ? "No recorded learning yet" : "Learn this site again with the AI");
  }
}

/* ---------- actions ---------- */
async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok && data.error) toast(data.error, true);
  return data;
}
function runRows(ids, relearn) {
  if (S.running) { post("/api/stop"); toast("Stopping after the current site."); return; }
  post("/api/run", { ids, relearn: !!relearn, source: S.source });
}
$("rows").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.closest("tr").id.slice(4);
  if (btn.dataset.act === "files") { post("/api/open", { id }); return; }
  runRows([id], btn.dataset.act === "relearn");
});
$("runall").addEventListener("click", () => runRows([], false));
$("export").addEventListener("click", (ev) => { if (!S.sheet) ev.preventDefault(); });

async function upload(file) {
  const r = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { toast(data.error || "This file could not be read.", true); return; }
  for (const w of data.sheet.warnings || []) toast(w, true);
}
$("file-chip").addEventListener("click", () => $("file-input").click());
$("pick").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) upload(f); ev.target.value = ""; });
const desk = $("desk");
desk.addEventListener("dragover", (ev) => { ev.preventDefault(); desk.classList.add("dragging"); });
desk.addEventListener("dragleave", () => desk.classList.remove("dragging"));
desk.addEventListener("drop", (ev) => { ev.preventDefault(); desk.classList.remove("dragging"); const f = ev.dataTransfer.files[0]; if (f) upload(f); });

function toast(text, bad) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.textContent = text;
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 5200);
}

/* ---------- flying documents ---------- */
function fly(text) {
  const a = Flow.centerOf("download"), b = Flow.centerOf("store");
  const c = document.createElement("div");
  c.className = "card";
  c.textContent = text;
  $("flyers").appendChild(c);
  const w = c.offsetWidth, h = c.offsetHeight;
  c.animate([
    { transform: `translate(${a.x - w / 2}px, ${a.y - h / 2}px) scale(.6)`, opacity: 0 },
    { transform: `translate(${(a.x + b.x) / 2 - w / 2 - 40}px, ${a.y - 130}px) scale(1) rotate(-4deg)`, opacity: 1, offset: .45 },
    { transform: `translate(${b.x - w / 2}px, ${b.y - h / 2}px) scale(.35)`, opacity: 0 },
  ], { duration: 900 / S.speed, easing: "cubic-bezier(.4,.0,.3,1)" }).onfinish = () => c.remove();
}

/* ---------- validation checks ---------- */
async function showChecks(checks) {
  const box = $("checks"), r = Flow.centerOf("verify").r;
  const list = $("checks-list");
  list.innerHTML = checks.map((c) => `<li>${esc(c.label)}</li>`).join("");
  box.style.left = (r.right + 24) + "px";
  box.style.top = Math.max(68, r.top - 40) + "px";
  box.classList.add("on");
  for (const li of list.querySelectorAll("li")) { await sleep(420); li.classList.add("ok"); }
  await sleep(800);
  box.classList.remove("on");
}

/* ---------- step narration ---------- */
const AI_SUB = {
  structure: "reads the page structure.",
  rules: "writes the sorting rules stored with the recipe.",
  label: "settles a few unclear documents, once.",
  filter: "turns your request into a filter, once.",
};
function stepText(step, e, run) {
  const ai = S.ai;
  switch (step) {
    case "site": return ["We start from one row of the Excel file.", run.row.request ? `One site, one request: "${run.row.request}".` : "One site: every document it publishes."];
    case "access": return ["Private portal or public website?", e.private ? "Private portal: a sign-in comes first." : "Public website: no sign-in needed."];
    case "auth": return ["Kraken signs in to the portal.", "Credentials stay in the vault: no password ever reaches the collector."];
    case "known": return ["Have we seen this site before?", e.known ? "Yes: its recipe is on file." : (e.relearn ? "Re-learn requested: the AI starts from scratch." : "No: this is its first visit.")];
    case "learn": return ["New site: the AI reads it once and writes its recipe.", `${ai} works out the page structure and writes the sorting rules stored with the recipe.`, "ai"];
    case "replay": return ["Known recipe: replayed with no AI.", `Zero ${ai} calls, zero cost.`];
    case "read": return [run.branch === "learn" ? "The new recipe runs: we go through the listings." : "We go through the document listings, page by page.", pagesText(run)];
    case "health":
      if (e.changed) return ["The site has changed!", "Documents we knew are missing from the listing.", "amber"];
      if (e.verdict === "baseline") return ["Has the site changed? We compare with earlier runs.", "First run: it becomes the baseline for the next ones."];
      if (e.verdict === "suspect") return ["Something looks unusual on this site.", "It is flagged for review; the collection goes on."];
      return ["Has the site changed? We compare with earlier runs.", "Same documents as before, in the same places."];
    case "repair": return ["The site changed: Kraken repairs itself.", `${ai} studies the new page and proposes a new recipe.`, "amber"];
    case "verify": return e.passed === false
      ? ["No repair passed the checks.", "The old recipe stays active and the team is alerted: nothing wrong is ever collected.", "bad"]
      : ["No human sign-off: the recipe has to prove itself.", "The old recipe stays active until the new one passes every check.", "amber"];
    case "classify":
      if (run.repaired) return ["Repair approved. Each document gets its type and period.", "Same documents as before: their types are already known."];
      if (run.branch === "learn") return ["Each document gets its type and period.", "With the rules the AI has just written."];
      return ["All good. Each document gets its type and period.", "Rules stored with the recipe do it all: zero AI calls."];
    case "download": return ["Every file is downloaded and checked.", "Format verified, fingerprint computed, duplicates dropped."];
    case "store": return ["Filed and ready to use.", run.filed ? `${run.filed} files sorted by issuer, year and type.` : "Sorted by issuer, year and type."];
  }
  return ["", ""];
}
function pagesText(run) {
  const p = run.pages ? `${fmtInt.format(run.pages)} page${run.pages > 1 ? "s" : ""} read` : "";
  return run.total ? `${p}${p ? ", " : ""}${fmtInt.format(run.total)} documents spotted.` : (p ? p + "." : "");
}
const DWELL = { site: 1300, access: 1000, auth: 1400, known: 1000, learn: 900, replay: 1500, read: 1200,
  health: 1300, repair: 700, verify: 300, classify: 1100, download: 500, store: 1400 };

/* ---------- event queue ---------- */
const queue = [];
let pumping = false;
function push(e) { queue.push(e); if (!pumping) pump(); }
async function pump() {
  pumping = true;
  while (queue.length) {
    const e = queue.shift();
    try { await handle(e); } catch (err) { console.error(err, e); }
  }
  pumping = false;
}
const rowOf = (id) => S.sheet && S.sheet.rows.find((r) => r.id === id);
const busy = () => queue.length > 25;

async function handle(e) {
  switch (e.type) {
    case "sheet":
      S.sheet = e.sheet; S.results = {}; renderTable(); idle(); return;
    case "job_start":
      S.running = true; S.totals = { calls: 0, tokens: 0, cost: 0, docs: 0 }; paintMeters();
      e.rows.forEach((id) => setCell(id, "status", '<span class="status queued"><i></i>Queued</span>'));
      paintButtons(); return;
    case "job_end": return jobEnd(e);
    case "notice": return notice(e);
    case "run_start": return runStart(e);
  }
  const run = S.run;
  if (!run || run.id !== e.row) return;
  switch (e.type) {
    case "step": return onStep(e, run);
    case "pages":
      run.pages = e.n;
      if (Flow.current === "read" || Flow.current === "learn") sub(Flow.current === "learn" ? `${pagesText(run)} ${S.ai} is studying them.` : pagesText(run));
      return;
    case "ai_start":
      Flow.aiOn(e.link); $("m-calls-box").classList.add("hot"); Flow.tok("thinking…");
      return;
    case "ai_end": return aiEnd(e, run);
    case "repair_attempt":
      sub(`A first fix without the AI did not pass the checks: ${S.ai} takes over.`);
      await sleep(900); return;
    case "checks":
      if (e.passed && e.checks.length) await showChecks(e.checks);
      return;
    case "doc": return onDoc(e, run);
    case "run_end": return runEnd(e, run);
  }
}

async function runStart(e) {
  const row = rowOf(e.row);
  if (!row) return;
  Flow.reset();
  S.run = { id: e.row, row, calls: 0, cost: 0, filed: 0, isNew: 0, total: 0, pages: 0, branch: null, repaired: false };
  const tr = $("row-" + e.row);
  document.querySelectorAll("tbody tr.running").forEach((t) => (t.className = ""));
  tr.className = "running";
  tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
  setCell(e.row, "status", `<span class="status run"><i></i>${e.source === "film" ? "Replaying" : "Running"}</span>`);
  ["found", "dl", "ai", "cost", "time", "health"].forEach((c) => setCell(e.row, c, "…", "empty"));
  $("who").innerHTML = `${esc(row.name)} ${badge(row)}`;
  await sleep(250);
}

async function onStep(e, run) {
  if (e.step === "learn" || e.step === "replay") {
    run.branch = e.step;
    $("row-" + run.id).className = "running" + (e.step === "learn" ? " ai" : "");
  }
  if (e.step === "repair") $("row-" + run.id).className = "running amber";
  if (e.step === "verify" && e.passed) run.repaired = true;
  if (e.step === "read" && e.found) run.total = e.found;
  if (e.pages) run.pages = Math.max(run.pages, e.pages);
  await Flow.enter(e.step, sleep);
  if (e.step === "verify" && e.passed === false) Flow.fail("verify");
  const [text, subText, tone] = stepText(e.step, e, run);
  say(text, subText, tone);
  if (e.step === "read" && run.total) setCell(run.id, "found", run.total);
  await sleep(busy() ? 250 : DWELL[e.step] || 1000);
}

async function aiEnd(e, run) {
  const ai = S.ai;
  if (e.cached) {
    Flow.aiOn(e.link); Flow.tok("recalled");
    await sleep(400); Flow.aiOff(); $("m-calls-box").classList.remove("hot");
    return;
  }
  Flow.aiOn(e.link); $("m-calls-box").classList.add("hot");
  const what = AI_SUB[e.step] || (String(e.step).startsWith("repair") ? "proposes a new recipe." : "answers.");
  sub(`${ai} ${what}`);
  S.totals.calls += 1; run.calls += 1;
  const tokens = (e.input_tokens || 0) + (e.output_tokens || 0);
  const t0 = S.totals.tokens, c0 = S.totals.cost, r0 = run.cost;
  await countUp((v) => {
    const k = tokens ? (v - t0) / tokens : 1;
    S.totals.tokens = v; S.totals.cost = c0 + e.cost * k; run.cost = r0 + e.cost * k;
    Flow.tok("+" + fmtInt.format(Math.round(v - t0)) + " tokens");
    paintMeters();
  }, t0, t0 + tokens, busy() ? 200 : 900);
  setCell(run.id, "ai", run.calls, "aiv"); setCell(run.id, "cost", fmtEur(run.cost), "aiv");
  await sleep(200);
  Flow.aiOff(); $("m-calls-box").classList.remove("hot");
}

const FILED = ["downloaded", "known_url", "duplicate_content"];
async function onDoc(e, run) {
  run.total = e.total;
  if (FILED.includes(e.status)) {
    run.filed += 1; S.totals.docs += 1;
    if (e.status === "downloaded") run.isNew += 1;
    setCell(run.id, "dl", run.filed);
    paintMeters();
    if (run.filed <= 14 || run.filed % 5 === 0) fly(e.label || "Document");
  }
  else {
    run.failed = (run.failed || 0) + 1;
    if (e.reason) run.reason = `${e.status}: ${e.reason}`;
  }
  setCell(run.id, "found", run.total);
  const failed = run.failed ? ` ${run.failed} not downloaded${run.reason ? ` (${run.reason})` : ""}.` : "";
  sub(`${run.filed} of ${run.total} filed${run.isNew ? `: ${run.isNew} new` : ""}.${failed}`);
  await sleep(busy() ? 25 : (e.index <= 14 ? 160 : 50));
}

/* "the site blocks downloads: blocked: challenge page (Imperva) at https://..." ->
   "The site's files are behind a bot protection (Imperva challenge page)." */
function blockedTitle(notes) {
  const m = /blocked: (.+?) at https?:/.exec(notes || "") || /blocked: ([^;]+)/.exec(notes || "");
  const what = m ? m[1].trim() : "";
  const named = /^(.*?)\s*\(([^)]+)\)$/.exec(what);  // "challenge page (Imperva)"
  const label = named ? `${named[2]} ${named[1]}` : what;
  const files = /blocks downloads/.test(notes || "") ? "The site's files are" : "The site is";
  return label ? `${files} behind a bot protection (${label}).` : "The site refused our robot.";
}

async function runEnd(e, run) {
  const r = e.result || {};
  S.results[run.id] = r;
  if (r.files != null) run.filed = r.files;
  const ok = ["Done", "Learned", "Repaired"].includes(r.status_label);
  if (ok) {
    if (Flow.current !== "store") await Flow.enter("store", sleep);
    const [text, subText] = stepText("store", {}, run);
    say(text, subText);
    await sleep(busy() ? 200 : 1100);
    Flow.finish();
  } else {
    const msg = {
      Blocked: [blockedTitle(r.notes), "Kraken stops cleanly: no workaround, no stealth. The site is marked blocked."],
      "Sign-in refused": ["Sign-in failed: nothing was collected.", r.notes || ""],
      Degraded: ["The site changed and no repair passed the checks.", "The previous recipe stays active and the team is alerted."],
      "No recipe": ["No recipe for this site yet.", "Run it with Re-learn first."],
      "Not downloaded": ["The documents were found, but none could be downloaded.", r.notes || ""],
      "Not validated": ["The new recipe did not pass the checks.", "Nothing was activated: Kraken never uses a recipe it could not verify."],
      "Over budget": ["The AI budget for this run was reached.", "Kraken stops: costs are capped on every run."],
    }[r.status_label] || ["Something went wrong on this site.", r.notes || ""];
    say(msg[0], msg[1], "bad");
    if (Flow.current) Flow.fail(Flow.current);
    await sleep(1800);
  }
  paintResult(run.id, r);
  $("row-" + run.id).className = "";
  S.run = null;
}

async function jobEnd(e) {
  S.running = false;
  S.films = e.films || S.films;
  paintButtons();
  document.querySelectorAll("tbody tr.running").forEach((t) => (t.className = ""));
  if (S.sheet) S.sheet.rows.forEach((row) => { if (!S.results[row.id]) paintResult(row.id, null); });
  const t = S.totals;
  Flow.reset();
  if (t.docs || t.calls) {
    $("who").textContent = e.cancelled ? "Run stopped" : "Run complete";
    say(`${fmtInt.format(t.docs)} documents filed for ${fmtEur(t.cost)} of AI.`,
      t.calls ? `Next time, these sites replay with zero ${S.ai} calls.` : `Not a single ${S.ai} call was needed.`);
  }
}

function notice(e) {
  if (e.kind === "no_film") { toast(e.text, true); return; }
  if (e.kind === "blocked" || e.kind === "unauthorized" || e.kind === "llm_error" || e.kind === "budget_exceeded") {
    toast(e.text || e.kind, true);
  }
}

/* ---------- connection ---------- */
function connect() {
  const es = new EventSource("/events");
  es.onopen = () => { $("conn").classList.add("on"); refresh(); };
  es.onerror = () => { $("conn").classList.remove("on"); };
  es.onmessage = (m) => {
    let e;
    try { e = JSON.parse(m.data); } catch (err) { console.error(err); return; }
    push(e);
    if (window.Library) Library.onEvent(e);  // the library follows runs live, unpaced
  };
}
async function refresh() {
  const st = await fetch("/api/state").then((r) => r.json());
  S.ai = st.ai_name || "SecureGPT";
  document.querySelectorAll(".ainame").forEach((n) => (n.textContent = S.ai));
  Flow.setAIName(S.ai);
  S.films = st.films || {};
  S.speed = st.speed || 1;
  paintSpeed();
  if (!S.running) {
    S.sheet = st.sheet; S.results = st.results || {};
    S.running = st.running;
    renderTable();
    if (!S.run) idle();
  }
}

/* ---------- presenter controls ---------- */
const SPEEDS = [0.5, 1, 1.5, 2, 4];
function paintSpeed() { $("speed").textContent = S.paused ? "Paused" : `Speed ×${S.speed}`; }
function setSpeed(dir) {
  const i = SPEEDS.indexOf(S.speed);
  S.speed = SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, (i < 0 ? 1 : i) + dir))];
  paintSpeed();
  post("/api/speed", { speed: S.speed });
}
function setSource(src) {
  S.source = src;
  $("m-live").setAttribute("aria-pressed", String(src === "live"));
  $("m-film").setAttribute("aria-pressed", String(src === "film"));
  paintButtons();
  if (!S.running && !S.run) idle();
}
$("m-live").addEventListener("click", () => setSource("live"));
$("m-film").addEventListener("click", () => setSource("film"));
function showPage(name) {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-current", t.dataset.page === name ? "page" : "false"));
  $("page-mission").hidden = name !== "mission";
  $("page-library").hidden = name !== "library";
  $("page-why").hidden = name !== "why";
  if (name === "why" && window.Why) Why.show();
  if (name === "library" && window.Library) Library.show();
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showPage(t.dataset.page)));
document.addEventListener("keydown", (ev) => {
  if (ev.target.closest("input, textarea") || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (ev.key === " " && !$("page-library").hidden) return;
  if (ev.key === " ") { ev.preventDefault(); S.paused = !S.paused; paintSpeed(); }
  else if (ev.key === "+" || ev.key === "=") setSpeed(1);
  else if (ev.key === "-") setSpeed(-1);
  else if (ev.key === "?") $("help").classList.toggle("on");
  else if (ev.key === "Escape") $("help").classList.remove("on");
  else if (ev.key.toLowerCase() === "f") setSource(S.source === "live" ? "film" : "live");
  else if (ev.key === "1") showPage("mission");
  else if (ev.key === "2") showPage("library");
  else if (ev.key === "3") showPage("why");
});
$("keys").addEventListener("click", () => $("help").classList.toggle("on"));
$("help").addEventListener("click", () => $("help").classList.remove("on"));

paintMeters();
idle();
connect();
