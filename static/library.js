"use strict";
/* Page 2: the document library. Folders by issuer and year, the documents, and for the
   selected one its AI summary, a chat about it and its metadata. Uses app.js helpers
   ($, esc, fmtInt, fmtEur, toast, LOCK) and window.KS (source: live or film). */
(function () {
  const L = {
    data: null, docs: [], byId: new Map(), issuers: [],
    sel: { issuer: null, year: null }, open: new Set(), q: "",
    docId: null, info: null, summary: null, sumState: "idle",
    chats: new Map(), /* doc id -> [{role, content, meta}] */
    streaming: null, /* {ctrl, docId} */
    loaded: false, dirty: true, known: null, fresh: new Set(),
    live: null, /* {name, filed} while a run files documents */
    viewer: null, /* {docId, page, sheet} */
    token: 0,
  };
  window.LIB = L;
  const ai = () => (L.data && L.data.ai_name) || (window.KS && KS.ai) || "SecureGPT";
  const model = () => (L.data && L.data.model) || "";
  const offline = () => !!(window.KS && KS.source === "film");

  /* ---------- icons ---------- */
  const I = {
    folder: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>',
    caret: '<svg class="caret" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    spark: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l2.1 6.4 6.4 2.1-6.4 2.1L12 19.5l-2.1-6.4L3.5 11l6.4-2.1z" fill="currentColor"/><path d="M19 15.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z" fill="currentColor" opacity=".7"/></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5.5 11.5L12 5l6.5 6.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/></svg>',
    eye: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>',
    ext: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    redo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor" opacity=".18"/><path d="M7.5 12.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    lock: '<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="2" y="5.5" width="8" height="5.5" rx="1.2" fill="currentColor"/><path d="M4 5.5V4a2 2 0 0 1 4 0v1.5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
    ask: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>',
    pages: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9 12h7M9 16h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  };

  /* ---------- formatting ---------- */
  function size(n) {
    if (!n) return "";
    if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / 1048576).toLocaleString("en-GB", { maximumFractionDigits: n < 10485760 ? 1 : 0 })} MB`;
    return `${(n / 1073741824).toLocaleString("en-GB", { maximumFractionDigits: 1 })} GB`;
  }
  function when(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  const secs = (s) => s == null ? "" : `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;
  const initials = (name) => (name.match(/[A-ZÀ-Ý0-9]/g) || [name[0] || "?"]).slice(0, 2).join("").toUpperCase();
  function hue(key) {
    let h = 0;
    for (const c of key) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return 215 + (h % 150); /* blue -> violet -> red, the brand range */
  }
  const ava = (iss) => {
    const h = hue(iss.key);
    return `<span class="ava" style="background:linear-gradient(135deg,hsl(${h} 75% 48%),hsl(${(h + 40) % 360} 70% 34%))">${esc(initials(iss.name))}</span>`;
  };
  function fileIcon(d, big) {
    const cls = d.kind === "pdf" ? "pdf" : d.kind === "sheet" ? "sheet" : d.ext;
    return `<span class="fi ${cls}${big ? " big" : ""}"><b>${esc((d.ext || "?").toUpperCase().slice(0, 4))}</b></span>`;
  }
  const unit = (n, one, many) => `${fmtInt.format(n)} ${n === 1 ? one : many}`;

  /* ---------- data ---------- */
  async function load() {
    const data = await fetch("/api/library").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (!data) {  /* the server is restarting: try again while the page is shown */
      L.dirty = true;
      setTimeout(() => { if (!$("page-library").hidden) load(); }, 1500);
      return;
    }
    const before = L.known;
    L.data = data;
    L.docs = data.docs;
    L.byId = new Map(data.docs.map((d) => [d.id, d]));
    L.issuers = data.issuers;
    if (before) for (const d of data.docs) if (!before.has(d.id)) L.fresh.add(d.id);
    L.known = new Set(data.docs.map((d) => d.id));
    L.loaded = true; L.dirty = false;
    if (L.sel.issuer && !L.issuers.some((i) => i.key === L.sel.issuer)) L.sel = { issuer: null, year: null };
    paintHead(); paintTree(); paintList();
    if (L.docId && !L.byId.has(L.docId)) { L.docId = null; paintWork(); }
  }

  function paintHead() {
    const docs = L.docs, years = new Set(docs.map((d) => d.year).filter(Boolean));
    const bytes = docs.reduce((a, d) => a + (d.size || 0), 0);
    const ready = docs.filter((d) => d.summary).length;
    $("lib-lede").innerHTML = docs.length
      ? `<span><b>${fmtInt.format(docs.length)}</b>documents</span><span><b>${L.issuers.length}</b>issuers</span>`
        + `<span><b>${years.size}</b>fiscal year${years.size > 1 ? "s" : ""}</span><span><b>${size(bytes)}</b>on disk</span>`
        + (ready ? `<span><b>${fmtInt.format(ready)}</b>summarised by ${esc(ai())}</span>` : "")
      : "No document filed yet: run a site on Mission control, the files appear here.";
  }

  /* ---------- tree ---------- */
  function paintTree() {
    const busy = L.live && L.live.issuer;
    const total = L.docs.length;
    let h = `<div class="tree-head">${I.folder}<b>downloads</b><span>${unit(total, "file", "files")}</span></div><div class="tree-scroll">`;
    h += `<button class="node all${!L.sel.issuer ? " sel" : ""}" data-iss=""><span class="ava">${I.folder}</span><span class="nm">All documents</span><span class="n">${fmtInt.format(total)}</span></button>`;
    for (const iss of L.issuers) {
      const open = L.open.has(iss.key);
      const sel = L.sel.issuer === iss.key && !L.sel.year;
      h += `<button class="node${open ? " open" : ""}${sel ? " sel" : ""}" data-iss="${esc(iss.key)}">${ava(iss)}<span class="nm">${esc(iss.name)}</span>`
        + `${iss.private ? `<span class="lock" title="Private portal">${I.lock}</span>` : ""}${busy === iss.key ? '<span class="busy" title="Collecting now"></span>' : ""}`
        + `<span class="n">${fmtInt.format(iss.count)}</span>${I.caret}</button>`;
      if (open) {
        h += '<div class="yrs">';
        for (const y of Object.keys(iss.years).sort().reverse()) {
          const ysel = L.sel.issuer === iss.key && L.sel.year === y;
          h += `<button class="node year${ysel ? " sel" : ""}" data-iss="${esc(iss.key)}" data-year="${esc(y)}">${I.folder}<span class="nm">${esc(y)}</span><span class="n">${iss.years[y]}</span></button>`;
        }
        h += "</div>";
      }
    }
    $("lib-tree").innerHTML = h + "</div>";
  }
  $("lib-tree").addEventListener("click", (ev) => {
    const b = ev.target.closest(".node");
    if (!b) return;
    const iss = b.dataset.iss || null, year = b.dataset.year || null;
    if (iss && !year) {
      const already = L.sel.issuer === iss && !L.sel.year;
      if (!L.open.has(iss)) L.open.add(iss);   /* first click opens and selects */
      else if (already) L.open.delete(iss);    /* a second click folds it */
    }
    L.sel = { issuer: iss, year };
    paintTree(); paintList(true);
  });

  /* ---------- list ---------- */
  function visible() {
    const q = L.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return L.docs.filter((d) => {
      if (L.sel.issuer && d.issuer !== L.sel.issuer) return false;
      if (L.sel.year && String(d.year || "Other") !== L.sel.year) return false;
      if (!q.length) return true;
      const hay = `${d.title} ${d.issuer_name} ${d.type_label} ${d.period_label} ${d.period || ""} ${d.year || ""} ${d.format} ${d.language_label} ${d.file_name}`.toLowerCase();
      return q.every((w) => hay.includes(w));
    });
  }
  function paintList(scrollTop) {
    const docs = visible();
    const iss = L.issuers.find((i) => i.key === L.sel.issuer);
    const title = iss ? `${iss.name}${L.sel.year ? ` · ${L.sel.year}` : ""}` : "All documents";
    $("list-head").innerHTML = `<b>${esc(title)}</b><span>${unit(docs.length, "document", "documents")}${L.q ? " found" : ""}</span>`;
    const box = $("lib-list");
    if (!docs.length) {
      box.innerHTML = L.docs.length
        ? `<div class="list-empty"><b>Nothing matches</b>Try another word, or clear the search.</div>`
        : `<div class="list-empty"><b>The library is empty</b>Run a site on Mission control: every file it files appears here, live.</div>`;
      return;
    }
    let h = "", group = null;
    for (const d of docs) {
      const g = `${d.issuer_name} · ${d.year || "Other"}`;
      if (g !== group) {
        group = g;
        const n = docs.filter((x) => `${x.issuer_name} · ${x.year || "Other"}` === g).length;
        h += `<div class="grp"><span class="cap">${esc(g)}</span><span>${n}</span></div>`;
      }
      const sub = [d.type_label, d.period_label, d.language ? d.language.toUpperCase() : "", size(d.size)].filter(Boolean);
      h += `<button class="doc${d.id === L.docId ? " sel" : ""}${L.fresh.has(d.id) ? " new" : ""}" data-id="${d.id}" title="${esc(d.title)}">`
        + `${fileIcon(d)}<span style="min-width:0"><span class="t">${esc(d.title)}</span><span class="s">${sub.map(esc).join(" <em>·</em> ")}</span></span>`
        + `<span class="side">${L.fresh.has(d.id) ? '<span class="newpill">NEW</span>' : ""}${d.summary ? `<span class="ready" title="${esc(ai())} summary ready">${I.spark}</span>` : ""}</span></button>`;
    }
    box.innerHTML = h;
    if (scrollTop) box.scrollTop = 0;
  }
  $("lib-list").addEventListener("click", (ev) => {
    const b = ev.target.closest(".doc");
    if (b) select(b.dataset.id);
  });
  let qTimer = 0;
  $("lib-q").addEventListener("input", (ev) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { L.q = ev.target.value; paintList(true); }, 90);
  });
  $("lib-q").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { const first = visible()[0]; if (first) select(first.id); ev.target.blur(); }
    if (ev.key === "Escape") { ev.target.value = ""; L.q = ""; paintList(true); ev.target.blur(); }
  });

  /* ---------- selection ---------- */
  async function select(id) {
    if (!L.byId.has(id)) return;
    if (L.streaming && L.streaming.docId !== id) stopStream();
    L.docId = id;
    L.fresh.delete(id);
    document.querySelectorAll(".doc.sel").forEach((b) => b.classList.remove("sel"));
    const btn = document.querySelector(`.doc[data-id="${id}"]`);
    if (btn) { btn.classList.add("sel"); btn.classList.remove("new"); const p = btn.querySelector(".newpill"); if (p) p.remove(); btn.scrollIntoView({ block: "nearest" }); }
    const token = ++L.token;
    L.info = null; L.summary = null; L.sumState = "idle";
    paintWork();
    const info = await fetch(`/api/library/doc?id=${id}`).then((r) => r.json()).catch(() => null);
    if (token !== L.token || !info || info.error) return;
    L.info = info;
    paintMeta();
    const d = info.doc;
    if (!d.readable) { L.sumState = "locked"; paintSummary(); paintComposer(); return; }
    if (info.summary) { L.summary = info.summary; L.sumState = "ready"; paintSummary(true); paintComposer(); return; }
    summarise(false);
  }

  async function summarise(refresh) {
    const id = L.docId, token = L.token;
    const d = L.byId.get(id);
    L.sumState = "reading"; L.summary = null;
    paintSummary(); paintComposer();
    const reading = readingAnimation(d);
    const r = await fetch("/api/library/summary", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, refresh: !!refresh, offline: offline() }) }).catch(() => null);
    const data = r ? await r.json().catch(() => ({ error: "unreadable answer" })) : { error: "the demo server cannot be reached" };
    await reading.finish(!data.error);
    if (token !== L.token) { if (!data.error) markReady(id); return; }
    if (data.error) { L.sumState = "failed"; L.sumError = data.error; paintSummary(); paintComposer(); return; }
    L.summary = data; L.sumState = "ready";
    markReady(id);
    paintSummary(true); paintComposer();
  }
  function markReady(id) {
    const d = L.byId.get(id);
    if (!d || d.summary) return;
    d.summary = true;
    const b = document.querySelector(`.doc[data-id="${id}"] .side`);
    if (b && !b.querySelector(".ready")) b.insertAdjacentHTML("beforeend", `<span class="ready" title="${esc(ai())} summary ready">${I.spark}</span>`);
    paintHead();
  }

  /* While the AI reads: pages counted up over a time that grows with the document, then
     "Writing the summary" until the answer is there. */
  function readingAnimation(d) {
    const total = (L.info && L.info.text && L.info.text.pages) || d.pages || 0;
    const isSheet = d.kind === "sheet";
    const expect = Math.min(14000, Math.max(2600, (total || 30) * 45));
    const t0 = performance.now(), token = L.token;
    let stop = false, done = false;
    function frame() {
      if (stop || token !== L.token) return;
      const box = document.getElementById("reading");
      if (box) {
        const k = Math.min(1, (performance.now() - t0) / expect);
        const eased = 1 - Math.pow(1 - k, 2.2);
        const page = Math.max(1, Math.round(eased * (total || 1)));
        box.querySelector(".pbar i").style.width = `${(done ? 100 : eased * 92).toFixed(1)}%`;
        box.querySelector("p").textContent = k < 1
          ? (total ? `${isSheet ? "Sheet" : "Page"} ${fmtInt.format(page)} of ${fmtInt.format(total)}` : "Reading the text…")
          : `All ${total ? fmtInt.format(total) + " " : ""}${isSheet ? "sheets" : "pages"} read. Writing the summary…`;
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    return {
      async finish(ok) {
        done = true;
        const box = document.getElementById("reading");
        if (ok && box) { box.querySelector(".pbar i").style.width = "100%"; await new Promise((r) => setTimeout(r, 280)); }
        stop = true;
      },
    };
  }

  /* ---------- workspace ---------- */
  function paintWork() {
    const w = $("lib-work");
    const d = L.docId && L.byId.get(L.docId);
    if (!d) { w.innerHTML = emptyState(); return; }
    const chips = [`<span class="chip iss">${esc(d.issuer_name)}</span>`, `<span class="chip">${esc(d.type_label)}</span>`];
    if (d.period_label) chips.push(`<span class="chip">${esc(d.period_label)}</span>`);
    if (d.language_label) chips.push(`<span class="chip">${esc(d.language_label)}</span>`);
    if (d.private) chips.push(`<span class="chip iss">${I.lock}Private portal</span>`);
    const canView = !d.private && (d.kind === "pdf" || d.kind === "sheet");
    w.innerHTML = `
      <div class="w-head">${fileIcon(d, true)}
        <div class="w-id"><h2 title="${esc(d.title)}">${esc(d.title)}</h2><div class="chips" id="w-chips">${chips.join("")}</div></div>
        <div class="w-acts">
          <button class="wbtn view" id="w-view" ${canView ? "" : "disabled"} title="Show the document here">${I.eye}View document</button>
          <button class="wbtn" id="w-open" ${d.private ? "disabled" : ""} title="Open the file with its application">${I.ext}Open file</button>
        </div>
      </div>
      <div class="w-main">
        <div class="chat">
          <div class="msgs" id="msgs"><div id="sumslot"></div><div id="suggest"></div><div id="thread" style="display:contents"></div></div>
          <form class="composer" id="composer" autocomplete="off">
            <div class="cbox"><textarea id="ask" rows="1" placeholder="Ask ${esc(ai())} about this document…"></textarea>
            <button class="send" id="send" type="submit" title="Send (Enter)">${I.send}</button></div>
            <div class="hint" id="hint"></div>
          </form>
        </div>
        <aside class="meta" id="meta"></aside>
      </div>`;
    $("w-view").addEventListener("click", () => openViewer(d.id, 1));
    $("w-open").addEventListener("click", () => fetch("/api/library/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: d.id }) })
      .then((r) => r.ok ? null : r.json().then((x) => toast(x.error || "Cannot open the file", true))));
    const ta = $("ask");
    ta.addEventListener("input", grow);
    ta.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); ask(ta.value); } });
    $("composer").addEventListener("submit", (ev) => { ev.preventDefault(); if (L.streaming) stopStream(); else ask(ta.value); });
    $("msgs").addEventListener("click", onMsgsClick);
    paintSummary(); paintThread(); paintComposer(); paintMeta();
  }
  function grow() {
    const ta = $("ask");
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(140, ta.scrollHeight) + "px";
    paintComposer();
  }

  function emptyState() {
    const n = L.docs.length;
    return `<div class="w-empty"><div>
      <img src="/static/kraken-mark-dark.svg" alt="">
      <h2>Pick a document, ask it anything.</h2>
      <p>${esc(ai())} reads it in seconds, summarises it and answers your questions from that document only, with the page of every figure.${n ? ` ${fmtInt.format(n)} documents are ready.` : ""}</p>
      <div class="feats">
        <div class="feat">${I.spark}<b>Summary in seconds</b><span>The key figures and facts, made once and kept: instant the next time.</span></div>
        <div class="feat">${I.ask}<b>Ask in your words</b><span>English, French or German: the answer comes in the language of the question.</span></div>
        <div class="feat">${I.pages}<b>Every answer sourced</b><span>Page references open the document right where the figure is.</span></div>
      </div></div></div>`;
  }

  /* ---------- summary card ---------- */
  function paintSummary(reveal) {
    const slot = $("sumslot");
    if (!slot) return;
    const d = L.byId.get(L.docId);
    const top = (flag) => `<div class="sum-top"><span class="orbi${L.sumState === "reading" ? " live" : ""}"></span><b>${esc(ai())} summary</b><small>${esc(model())}</small>${flag || ""}</div>`;
    if (L.sumState === "idle") { slot.innerHTML = ""; $("suggest").innerHTML = ""; return; }
    if (L.sumState === "locked") {
      const why = d.private
        ? ["Private portal document", "It stays inside Kraken: no AI reads documents from private portals, and they are not shown in the demo. The metadata on the right is all that leaves the vault."]
        : [`${d.format} files are not read by ${ai()}`, `${ai()} reads PDF and Excel (.xlsx) files. This one is listed with its metadata; open it with its own application.`];
      slot.innerHTML = `<div class="sum locked">${top()}<h3>${esc(why[0])}</h3><p>${esc(why[1])}</p></div>`;
      $("suggest").innerHTML = "";
      return;
    }
    if (L.sumState === "reading") {
      const total = (L.info && L.info.text && L.info.text.pages) || d.pages;
      const what = d.kind === "sheet" ? "sheets" : "pages";
      slot.innerHTML = `<div class="sum">${top('<span class="flag fresh">Reading now</span>')}
        <div class="reading-box" id="reading"><div class="pages"><i></i><i></i><i></i><span class="beam"></span></div>
        <div><h3>${esc(ai())} is reading ${total ? `${fmtInt.format(total)} ${what}` : "the document"}</h3><p>Opening the document…</p><div class="pbar"><i></i></div></div></div>
        <div class="skel"><i style="width:92%"></i><i style="width:78%"></i><i style="width:85%"></i><i style="width:60%"></i></div></div>`;
      $("suggest").innerHTML = "";
      return;
    }
    if (L.sumState === "failed") {
      slot.innerHTML = `<div class="sum failed">${top()}<h3>No summary this time</h3><p>${esc(cap(L.sumError || "the AI did not answer"))}</p>
        <button class="wbtn retry" id="sum-retry">${I.redo}Try again</button></div>`;
      $("sum-retry").addEventListener("click", () => summarise(false));
      $("suggest").innerHTML = "";
      return;
    }
    const s = L.summary;
    const flag = s.cached
      ? `<span class="flag" title="Made ${esc(when(s.at))}">Instant · kept from ${esc(shortDate(s.at))}</span>`
      : `<span class="flag fresh">Just written</span>`;
    const redo = offline() ? "" : `<button class="redo" id="sum-redo" title="Write the summary again (calls ${esc(ai())})">${I.redo}</button>`;
    const figs = (s.key_figures || []).map((f) => `<div class="fig rvi"><span class="v${f.value.length > 9 ? " long" : ""}" title="${esc(f.value)}">${esc(f.value)}</span>${f.change ? `<span class="dl ${/^[-−–]/.test(f.change) ? "down" : /^\+/.test(f.change) ? "up" : ""}">${esc(f.change)}</span>` : ""}<span class="l">${esc(f.label)}</span>${citeChip(f.page, d)}</div>`).join("");
    const pts = (s.key_points || []).map((p) => `<li class="rvi">${inline(p)}</li>`).join("");
    const read = s.pages_total ? (s.pages_read < s.pages_total ? `<span>Read <b>${s.pages_read}</b> of ${s.pages_total} ${s.unit}</span>` : `<span>Read <b>${fmtInt.format(s.pages_total)}</b> ${s.unit}</span>`) : "";
    const cost = s.cached
      ? `<span class="free">0 tokens now: kept from the first reading</span><span>first reading ${fmtInt.format((s.input_tokens || 0) + (s.output_tokens || 0))} tokens · ${fmtEur(s.cost)} · ${secs(s.seconds)}</span>`
      : `<span><b>${fmtInt.format((s.input_tokens || 0) + (s.output_tokens || 0))}</b> tokens</span><span><b>${fmtEur(s.cost)}</b></span><span><b>${secs(s.seconds)}</b></span>`;
    slot.innerHTML = `<div class="sum">${top(flag + redo)}
      <h3 class="rvi">${esc(s.headline)}</h3>
      ${s.overview ? `<p class="ov rvi">${inline(s.overview)}</p>` : ""}
      ${figs ? `<div class="figs">${figs}</div>` : ""}
      ${pts ? `<ul class="pts">${pts}</ul>` : ""}
      <div class="sum-foot rvi">${read}${cost}</div></div>`;
    if (reveal) slot.querySelectorAll(".rvi").forEach((el, i) => { el.classList.add("rv"); el.style.setProperty("--d", i); });
    const redoBtn = $("sum-redo");
    if (redoBtn) redoBtn.addEventListener("click", () => summarise(true));
    paintSuggest();
  }
  const cap = (t) => { t = String(t || "").trim(); return t ? t[0].toUpperCase() + t.slice(1) : t; };
  function shortDate(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "earlier" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }
  function paintSuggest() {
    const box = $("suggest");
    if (!box) return;
    const qs = (L.summary && L.summary.questions) || [];
    const asked = new Set((L.chats.get(L.docId) || []).filter((m) => m.role === "user").map((m) => m.content));
    const left = qs.filter((q) => !asked.has(q));
    box.className = left.length ? "suggest" : "";
    box.innerHTML = left.length
      ? `<span class="cap">Ask ${esc(ai())}</span>` + left.map((q) => `<button class="sq" data-q="${esc(q)}">${I.ask}${esc(q)}</button>`).join("")
      : "";
  }

  /* ---------- chat ---------- */
  function thread() {
    if (!L.chats.has(L.docId)) L.chats.set(L.docId, []);
    return L.chats.get(L.docId);
  }
  function paintThread() {
    const box = $("thread");
    if (!box) return;
    box.innerHTML = (L.chats.get(L.docId) || []).map(msgHtml).join("");
    scrollDown(true);
  }
  function msgHtml(m, i) {
    if (m.role === "user") return `<div class="msg user"><div class="bubble">${esc(m.content)}</div></div>`;
    return `<div class="msg" data-i="${i}"><span class="orbi${m.streaming ? " live" : ""}"></span><div style="min-width:0">
      <div class="who-ai">${esc(ai())}<small>${esc(m.model || model())}</small></div>
      <div class="answer${m.streaming ? " streaming" : ""}">${m.error ? `<p class="err">${esc(m.error)}</p>` : md(m.content || (m.streaming ? "" : "…"), L.byId.get(L.docId))}${m.streaming && !m.content ? "<p></p>" : ""}</div>
      ${m.meta ? `<div class="meta-line">${m.meta}</div>` : ""}</div></div>`;
  }
  function paintLast() {
    const msgs = L.chats.get(L.docId) || [];
    const i = msgs.length - 1, box = $("thread");
    if (!box || i < 0) return;
    const el = box.querySelector(`.msg[data-i="${i}"]`);
    const html = msgHtml(msgs[i], i);
    if (el) el.outerHTML = html; else box.insertAdjacentHTML("beforeend", html);
    const fresh = box.querySelector(`.msg[data-i="${i}"]`);
    if (fresh) fresh.style.animation = "none";
    scrollDown();
  }
  function scrollDown(force) {
    const m = $("msgs");
    if (!m) return;
    if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 260) m.scrollTop = m.scrollHeight;
  }
  function paintComposer() {
    const d = L.byId.get(L.docId), ta = $("ask"), send = $("send"), hint = $("hint");
    if (!d || !ta) return;
    const ready = d.readable && L.sumState !== "reading";
    ta.disabled = !d.readable;
    ta.placeholder = d.readable ? `Ask ${ai()} about this document…` : "This document is not read by the AI";
    send.classList.toggle("stop", !!L.streaming);
    send.innerHTML = L.streaming ? I.stop : I.send;
    send.title = L.streaming ? "Stop the answer" : "Send (Enter)";
    send.disabled = !L.streaming && (!ready || !ta.value.trim());
    document.querySelectorAll(".sq").forEach((b) => (b.disabled = !!L.streaming || !ready));
    const t = L.info && L.info.text;
    const scope = t ? (t.unit === "sheets" ? `${t.pages} sheets` : `${fmtInt.format(t.pages)} pages`) : "";
    hint.innerHTML = d.readable
      ? `<span>Answers from this document only</span>${scope ? `<span>${scope} in context, no search engine</span>` : ""}<span>${offline() ? "Recorded mode: answers replayed" : `${esc(ai())} · ${esc(model())}`}</span>`
      : "";
  }
  function onMsgsClick(ev) {
    const c = ev.target.closest(".cite[data-page]");
    if (c) { openViewer(L.docId, Number(c.dataset.page) || 1); return; }
    const sheet = ev.target.closest(".cite[data-sheet]");
    if (sheet) { openViewer(L.docId, 1, sheet.dataset.sheet); return; }
    const q = ev.target.closest(".sq");
    if (q) ask(q.dataset.q);
  }

  function history() {
    const out = [];
    const s = L.summary;
    if (s) {
      const lines = [s.headline, s.overview, ...(s.key_points || []).map((p) => "- " + p)].filter(Boolean);
      out.push({ role: "assistant", content: lines.join("\n") });
    }
    for (const m of L.chats.get(L.docId) || []) if (!m.error && m.content) out.push({ role: m.role, content: m.content });
    return out;
  }

  async function ask(text) {
    text = String(text || "").trim();
    const d = L.byId.get(L.docId);
    if (!text || !d || !d.readable || L.streaming || L.sumState === "reading") return;
    const ta = $("ask");
    if (ta) { ta.value = ""; grow(); }
    const msgs = thread();
    msgs.push({ role: "user", content: text });
    const docId = L.docId;
    const reply = { role: "assistant", content: "", streaming: true, model: model() };
    const payload = { id: docId, messages: [...history()], offline: offline() };
    msgs.push(reply);
    paintThread(); paintSuggest();
    const ctrl = new AbortController();
    L.streaming = { ctrl, docId };
    paintComposer();
    let pending = false;
    const repaint = () => { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; if (L.docId === docId) paintLast(); }); };
    const t0 = performance.now();
    try {
      const r = await fetch("/api/library/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: ctrl.signal });
      if (!r.ok || !r.body) { const e = await r.json().catch(() => ({})); throw new Error(e.error || `HTTP ${r.status}`); }
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let k;
        while ((k = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, k); buf = buf.slice(k + 1);
          if (!line.trim()) continue;
          const e = JSON.parse(line);
          if (e.type === "delta") { reply.content += e.text; repaint(); }
          else if (e.type === "start" && e.model) reply.model = e.model.split("/").pop();
          else if (e.type === "error") { reply.error = e.text; }
          else if (e.type === "done") reply.meta = metaLine(e, (performance.now() - t0) / 1000);
        }
      }
    } catch (err) {
      if (err.name === "AbortError") { reply.meta = '<span>Stopped</span>'; }
      else reply.error = cap(String(err.message || err)).replace(/\.?$/, ".");
    }
    reply.streaming = false;
    if (!reply.content && !reply.error && !reply.meta) reply.error = "No answer came back.";
    if (L.streaming && L.streaming.ctrl === ctrl) L.streaming = null;
    if (L.docId === docId) { paintLast(); paintComposer(); paintSuggest(); const t = $("ask"); if (t) t.focus(); }
  }
  function metaLine(e, wall) {
    if (e.cached) return `<span class="free">${e.replay === "fallback" ? "Network down: answer replayed from an earlier run" : "Recorded answer, replayed"}</span><span>0 tokens</span>`;
    const tokens = (e.input_tokens || 0) + (e.output_tokens || 0);
    return `<span>${fmtInt.format(tokens)} tokens${e.estimated ? " (estimated)" : ""}</span><span>${fmtEur(e.cost)}</span><span>${secs(e.seconds || wall)}</span>`;
  }
  function stopStream() {
    if (L.streaming) { L.streaming.ctrl.abort(); L.streaming = null; }
    paintComposer();
  }

  /* ---------- markdown, small and safe (escaped first) ---------- */
  function citeChip(page, d) {
    const p = String(page || "").trim();
    if (!p) return "";
    if (d && d.kind === "sheet" && !/^\d+$/.test(p)) return `<button class="cite sheet" data-sheet="${esc(p)}" title="Sheet ${esc(p)}">${esc(p)}</button>`;
    const n = parseInt(p, 10);
    return Number.isFinite(n) ? `<button class="cite" data-page="${n}" title="Open page ${n}">p. ${esc(p)}</button>` : "";
  }
  function inline(t) {
    return esc(t)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[(?:p|pp|page|pages|s|seite|pages?)\.?\s*([\d][\d\s,;–\-]*)\]/gi, (m, list) => pagesChips(list))
      .replace(/\[(?:sheet|feuille|onglet)s?\s+([^\]]+)\]/gi, (m, name) => `<button class="cite sheet" data-sheet="${name.trim()}" title="Sheet ${name.trim()}">${name.trim()}</button>`);
  }
  function pagesChips(list) {
    return list.split(/[,;]/).map((x) => x.trim()).filter(Boolean).map((x) => {
      const n = parseInt(x, 10);
      return Number.isFinite(n) ? `<button class="cite" data-page="${n}" title="Open page ${n}">p. ${x.replace(/\s+/g, "")}</button>` : "";
    }).join("");
  }
  function md(src) {
    const lines = String(src).replace(/\r/g, "").split("\n");
    let h = "", i = 0, para = [];
    const flush = () => { if (para.length) { h += `<p>${inline(para.join(" "))}</p>`; para = []; } };
    const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
    while (i < lines.length) {
      const l = lines[i];
      if (!l.trim()) { flush(); i++; continue; }
      if (isRow(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        flush();
        const cells = (x) => x.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
        h += "<table><thead><tr>" + cells(l).map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>";
        i += 2;
        while (i < lines.length && isRow(lines[i])) { h += "<tr>" + cells(lines[i]).map((c) => `<td>${c}</td>`).join("") + "</tr>"; i++; }
        h += "</tbody></table>";
        continue;
      }
      const head = /^\s*#{1,4}\s+(.*)$/.exec(l);
      if (head) { flush(); h += `<h4>${inline(head[1])}</h4>`; i++; continue; }
      const ul = /^\s*[-*•]\s+/, ol = /^\s*\d+[.)]\s+/;
      if (ul.test(l) || ol.test(l)) {
        flush();
        const tag = ul.test(l) ? "ul" : "ol", re = tag === "ul" ? ul : ol;
        h += `<${tag}>`;
        while (i < lines.length && re.test(lines[i])) {
          let item = lines[i].replace(re, "");
          i++;
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !ul.test(lines[i]) && !ol.test(lines[i])) item += " " + lines[i++].trim();
          h += `<li>${inline(item)}</li>`;
        }
        h += `</${tag}>`;
        continue;
      }
      para.push(l.trim());
      i++;
    }
    flush();
    return h;
  }

  /* ---------- metadata ---------- */
  function paintMeta() {
    const box = $("meta");
    const d = L.byId.get(L.docId);
    if (!box || !d) return;
    const t = L.info && L.info.text;
    const pages = t ? (t.unit === "sheets" ? `${t.pages} sheets` : fmtInt.format(t.pages)) : (d.pages ? fmtInt.format(d.pages) : "");
    const row = (k, v, cls) => v ? `<dt>${k}</dt><dd${cls ? ` class="${cls}"` : ""}>${v}</dd>` : "";
    const src = d.url ? `<a class="src" href="${esc(d.url)}" title="${esc(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.host)}</a>` : "";
    const why = (d.why || []).map((w) => `<div><b>${esc(w.field)}</b> from ${esc(w.from)}</div>`).join("");
    box.innerHTML = `
      <section><span class="cap">Document</span><dl>
        ${row("Issuer", esc(d.issuer_name))}${row("Type", esc(d.type_label))}${row("Period", esc(d.period_label || d.period || ""))}
        ${row("Fiscal year", d.year ? String(d.year) : "")}${row("Language", esc(d.language_label))}
      </dl></section>
      <section><span class="cap">File</span><dl>
        ${row("Format", esc(d.format))}${row(t && t.unit === "sheets" ? "Sheets" : "Pages", pages)}${row("Size", size(d.size))}
        ${row("Filed as", esc(d.rel), "mono")}
      </dl></section>
      ${d.private ? "" : `<section><span class="cap">Checked on download</span><div class="checks-ok">
        <div>${I.check}Real ${esc(d.format)} file, not an error page</div>
        <div>${I.check}Fingerprint recorded, no duplicate</div>
        <div>${I.check}From the issuer's own site</div></div></section>`}
      <section><span class="cap">Provenance</span><dl>
        ${row("Source", src)}${row("Collected", esc(when(d.downloaded_at)))}
        ${row("Recipe", d.recipe ? `${esc(d.recipe)} v${d.recipe_version || 1}` : "")}
        ${row("SHA-256", d.sha256 ? esc(d.sha256.slice(0, 16)) + "…" : "", "mono")}
      </dl></section>
      ${why ? `<section><span class="cap">How Kraken sorted it</span><div class="why-list">${why}</div></section>` : ""}`;
  }

  /* ---------- viewer ---------- */
  async function openViewer(id, page, sheet) {
    const d = L.byId.get(id);
    if (!d || d.private) return;
    const v = $("viewer"), body = $("viewer-body");
    $("viewer-title").textContent = d.title;
    $("viewer-tabs").innerHTML = "";
    const same = L.viewer && L.viewer.docId === id;
    L.viewer = { docId: id, page, sheet };
    v.classList.add("on"); v.setAttribute("aria-hidden", "false");
    if (d.kind === "pdf") {
      $("viewer-sub").textContent = `${d.issuer_name} · page ${page}`;
      const src = `/api/library/file?id=${id}&p=${page}#page=${page}&view=FitH&navpanes=0`;
      const old = body.querySelector("iframe");
      if (old && same) { old.src = src; return; }
      body.innerHTML = `<iframe title="${esc(d.title)}" src="${src}"></iframe>`;
      return;
    }
    if (d.kind === "sheet") {
      $("viewer-sub").textContent = `${d.issuer_name} · Excel workbook`;
      if (!same || !L.viewer.sheets) {
        body.innerHTML = `<div class="viewer-msg"><div><b>Opening the workbook…</b></div></div>`;
        const r = await fetch(`/api/library/sheet?id=${id}`).then((x) => x.json()).catch(() => ({ error: "cannot read it" }));
        if (r.error) { body.innerHTML = `<div class="viewer-msg"><div><b>No preview</b>${esc(r.error)}</div></div>`; return; }
        L.viewer.sheets = r.sheets;
      }
      showSheet(sheet);
      return;
    }
    body.innerHTML = `<div class="viewer-msg"><div><b>No preview for ${esc(d.format)} files</b>Use Open file.</div></div>`;
  }
  function showSheet(name) {
    const sheets = L.viewer.sheets || [];
    const idx = Math.max(0, sheets.findIndex((s) => s.name.toLowerCase() === String(name || "").toLowerCase()));
    $("viewer-tabs").innerHTML = sheets.map((s, i) => `<button data-s="${i}" aria-pressed="${i === idx}">${esc(s.name)}</button>`).join("");
    const s = sheets[idx];
    if (!s) return;
    const width = Math.max(1, ...s.rows.map((r) => r.length));
    let h = `<div class="sheet"><table><thead><tr><th></th>`;
    for (let c = 0; c < width; c++) h += `<th>${colName(c)}</th>`;
    h += "</tr></thead><tbody>";
    s.rows.forEach((r, i) => { h += `<tr><td class="rn">${i + 1}</td>` + Array.from({ length: width }, (_, c) => `<td>${esc(r[c] ?? "")}</td>`).join("") + "</tr>"; });
    h += `</tbody></table>${s.more ? `<div class="more">${fmtInt.format(s.more)} more rows in the file.</div>` : ""}</div>`;
    $("viewer-body").innerHTML = h;
    $("viewer-sub").textContent = `${L.byId.get(L.viewer.docId).issuer_name} · sheet ${s.name}`;
  }
  const colName = (i) => { let s = ""; i++; while (i) { const r = (i - 1) % 26; s = String.fromCharCode(65 + r) + s; i = Math.floor((i - 1) / 26); } return s; };
  $("viewer-tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-s]");
    if (b && L.viewer && L.viewer.sheets) showSheet(L.viewer.sheets[Number(b.dataset.s)].name);
  });
  function closeViewer() {
    const v = $("viewer");
    v.classList.remove("on"); v.setAttribute("aria-hidden", "true");
  }
  $("viewer-x").addEventListener("click", closeViewer);

  /* ---------- live runs ---------- */
  const FILED = ["downloaded", "known_url", "duplicate_content"];
  let liveTimer = 0, reloadTimer = 0;
  function paintLive() {
    const el = $("lib-live"), tab = $("tab-live");
    tab.hidden = !(L.live && !L.live.done);
    if (!L.live) { el.hidden = true; return; }
    el.hidden = false;
    el.classList.toggle("done", !!L.live.done);
    $("lib-live-text").textContent = L.live.done
      ? `Collection complete${L.live.added ? `: ${unit(L.live.added, "new document", "new documents")} in the library` : ""}`
      : `Live · ${L.live.name}${L.live.filed ? ` · ${unit(L.live.filed, "file", "files")} filed` : " · collecting"}`;
  }
  function reloadSoon() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(async () => {
      const before = L.docs.length;
      if (!$("page-library").hidden || L.loaded) await load(); else L.dirty = true;
      if (L.live) { L.live.added = (L.live.added || 0) + Math.max(0, L.docs.length - before); paintLive(); }
    }, 400);
  }
  function issuerOf(rowId, name) {
    const byName = L.issuers.find((i) => i.name === name);
    return byName ? byName.key : rowId;
  }
  function onEvent(e) {
    switch (e.type) {
      case "job_start":
        clearTimeout(liveTimer);
        L.live = { name: "starting", filed: 0, added: 0 };
        paintLive();
        break;
      case "run_start":
        if (!L.live) L.live = { filed: 0, added: 0 };
        Object.assign(L.live, { name: e.name || e.row, issuer: issuerOf(e.row, e.name), filed: 0, done: false });
        paintLive(); if (L.loaded) paintTree();
        break;
      case "doc":
        if (L.live && FILED.includes(e.status)) { L.live.filed += 1; paintLive(); }
        break;
      case "run_end":
        reloadSoon();
        break;
      case "job_end":
        if (L.live) {
          L.live.done = true; L.live.issuer = null; paintLive();
          reloadSoon();
          liveTimer = setTimeout(() => { L.live = null; paintLive(); if (L.loaded) paintTree(); }, 9000);
        }
        break;
    }
  }

  /* ---------- keys ---------- */
  document.addEventListener("keydown", (ev) => {
    if ($("page-library").hidden) return;
    const typing = ev.target.closest("input, textarea");
    if (ev.key === "Escape") {
      if ($("viewer").classList.contains("on")) { closeViewer(); ev.preventDefault(); return; }
      if (L.streaming) { stopStream(); return; }
    }
    if (typing || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key === "/") { ev.preventDefault(); $("lib-q").focus(); $("lib-q").select(); }
    else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const docs = visible();
      if (!docs.length) return;
      const i = docs.findIndex((d) => d.id === L.docId);
      const next = i < 0 ? 0 : Math.min(docs.length - 1, Math.max(0, i + (ev.key === "ArrowDown" ? 1 : -1)));
      select(docs[next].id);
    } else if (ev.key === "Enter" && L.docId && $("ask")) { ev.preventDefault(); $("ask").focus(); }
  });

  window.Library = {
    async show() {
      if (!L.loaded || L.dirty) await load();
      else { paintHead(); paintTree(); paintList(); }
      if (!$("lib-work").innerHTML) paintWork();
      paintLive();
    },
    onEvent,
    select,
    openViewer,
  };
})();
