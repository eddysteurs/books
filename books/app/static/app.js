/* Books — front end. All URLs are relative so it works behind HA ingress. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { books: [], filter: "all", sort: localStorage.getItem("books.sort") || "author",
  view: localStorage.getItem("books.view") || "grid", lang: "", q: "", editing: null };

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new Error((data && data.error) || `${res.status} ${res.statusText}`);
  return data;
}

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}

function open(id) { $("#" + id).hidden = false; document.body.style.overflow = "hidden"; }
function close(id) {
  $("#" + id).hidden = true;
  if (id === "add") stopScan();
  if ($$(".sheet").every((s) => s.hidden)) document.body.style.overflow = "";
}

/* ------------------------------------------------------------ list */

const sortKey = (b) => (b.authors && b.authors[0] ? lastName(b.authors[0]) : "\uffff");
function lastName(n) { const p = n.trim().split(/\s+/); return (p[p.length - 1] + " " + n).toLowerCase(); }
const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

function hue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function coverHtml(b, badge = true) {
  const h = hue(b.title || "x");
  const ph = `<div class="ph" style="--c1:hsl(${h} 45% 45%);--c2:hsl(${(h + 40) % 360} 50% 28%)">${esc(b.title)}<small>${esc((b.authors || [])[0] || "")}</small></div>`;
  const img = b.cover ? `<img loading="lazy" src="${esc(b.cover)}" alt="" onerror="this.remove()">` : "";
  let bd = "";
  if (badge && b.status === "wishlist") bd = `<span class="badge wish">wishlist</span>`;
  else if (badge && b.read) bd = `<span class="badge read">read</span>`;
  return `<div class="cover">${ph}${img}${bd}</div>`;
}

function visibleBooks() {
  const terms = norm(state.q).split(/\s+/).filter(Boolean);
  let list = state.books.filter((b) => {
    if (state.filter === "wishlist" ? b.status !== "wishlist" : b.status === "wishlist" && state.filter !== "all") return false;
    if (state.filter === "read" && !b.read) return false;
    if (state.filter === "unread" && b.read) return false;
    if (state.lang && b.language !== state.lang) return false;
    if (!terms.length) return true;
    const hay = norm([b.title, b.subtitle, b.series, (b.authors || []).join(" "), b.isbn, b.publisher, b.location, b.pub_year].join(" "));
    return terms.every((t) => hay.includes(t));
  });
  const cmp = {
    author: (a, b) => sortKey(a).localeCompare(sortKey(b)) || (a.pub_year || 0) - (b.pub_year || 0) || a.title.localeCompare(b.title),
    title: (a, b) => a.title.localeCompare(b.title, undefined, { numeric: true }),
    added: (a, b) => (b.added_at || 0) - (a.added_at || 0) || b.id - a.id,
    year: (a, b) => (b.pub_year || 0) - (a.pub_year || 0),
  }[state.sort];
  return list.sort(cmp);
}

function render() {
  const list = visibleBooks();
  const grid = $("#grid");
  grid.className = "grid" + (state.view === "list" ? " list" : "");
  grid.innerHTML = list.map((b) => `
    <div class="book" data-id="${b.id}">
      ${coverHtml(b)}
      <div class="t">${esc(b.title)}</div>
      <div class="a">${esc((b.authors || []).join(", "))}</div>
      <div class="y">${esc(b.pub_year || "")}</div>
      <div class="s ${b.status === "wishlist" ? "wish" : b.read ? "read" : ""}">${b.status === "wishlist" ? "Wishlist" : b.read ? "Read" : "Unread"}</div>
    </div>`).join("");
  const owned = state.books.filter((b) => b.status !== "wishlist").length;
  $("#count").textContent = list.length === state.books.length ? `${owned} books` : `${list.length} of ${state.books.length}`;
  $("#empty").hidden = state.books.length > 0;
}

function fillLists() {
  const uniq = (k) => [...new Set(state.books.map((b) => b[k]).filter(Boolean))].sort();
  const langs = uniq("language");
  $("#lang").innerHTML = `<option value="">All languages</option>` + langs.map((l) => `<option ${l === state.lang ? "selected" : ""}>${esc(l)}</option>`).join("");
  $("#langList").innerHTML = langs.map((l) => `<option value="${esc(l)}">`).join("");
  $("#formatList").innerHTML = uniq("format").map((l) => `<option value="${esc(l)}">`).join("");
  $("#locList").innerHTML = uniq("location").map((l) => `<option value="${esc(l)}">`).join("");
}

async function load() {
  state.books = await api("api/books");
  fillLists();
  render();
}

/* ------------------------------------------------------------ details */

async function showBook(id) {
  const b = await api(`api/books/${id}`);
  const stars = b.rating ? `<span class="stars">${"★".repeat(b.rating)}${"☆".repeat(5 - b.rating)}</span>` : "";
  const rows = [
    ["Series", b.series], ["Publisher", b.publisher], ["Published", b.pub_date || b.pub_year], ["Pages", b.pages],
    ["ISBN", b.isbn], ["Language", b.language], ["Format", b.format], ["Location", b.location],
    ["Owner", b.owner], ["Status", b.status === "wishlist" ? "Wishlist" : "In collection"],
    ["Read", b.read ? "Yes" + (b.read_date ? ` (${b.read_date})` : "") : "No"], ["Rating", stars],
    ["Purchased", [b.purchase_date, b.store, b.purchase_price].filter(Boolean).join(" · ")],
    ["Added", b.added_at ? new Date(b.added_at * 1000).toLocaleDateString() : ""], ["Source", b.source],
  ].filter(([, v]) => v !== "" && v !== null && v !== undefined);
  $("#detailBody").innerHTML = `
    <div class="dt">
      <div>${coverHtml(b, false)}</div>
      <div>
        <h2>${esc(b.title)}</h2>
        ${b.subtitle ? `<div class="sub">${esc(b.subtitle)}</div>` : ""}
        <div class="authors">${(b.authors || []).map((a) => `<a data-author="${esc(a)}">${esc(a)}</a>`).join(", ")}</div>
        <dl class="meta">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${k === "Rating" ? v : esc(v)}</dd>`).join("")}</dl>
        ${b.plot ? `<div class="plot">${esc(b.plot)}</div>` : ""}
        ${b.notes ? `<p class="plot"><em>${esc(b.notes)}</em></p>` : ""}
        <div class="tagrow">${[...(b.subjects || []), ...(b.tags || [])].map((s) => `<span class="tag">${esc(s)}</span>`).join("")}</div>
        <div class="dt-actions">
          <button class="primary" data-act="edit">Edit</button>
          <button data-act="toggleRead">${b.read ? "Mark as unread" : "Mark as read"}</button>
          ${b.status === "wishlist" ? `<button data-act="own">I bought it</button>` : ""}
          <button class="danger" data-act="delete">Delete</button>
        </div>
      </div>
    </div>`;
  $("#detailBody").onclick = async (e) => {
    const a = e.target.closest("[data-author]");
    if (a) return showAuthor(a.dataset.author);
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "edit") { close("detail"); editBook(b); }
    if (act === "toggleRead") {
      await api(`api/books/${b.id}`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ read: !b.read, read_date: !b.read && !b.read_date ? new Date().toISOString().slice(0, 10) : b.read_date }) });
      await load(); showBook(b.id);
    }
    if (act === "own") {
      await api(`api/books/${b.id}`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "collection", purchase_date: new Date().toISOString().slice(0, 10) }) });
      await load(); showBook(b.id); toast("Moved to your collection");
    }
    if (act === "delete" && confirm(`Delete "${b.title}"?`)) {
      await api(`api/books/${b.id}`, { method: "DELETE" });
      close("detail"); await load(); toast("Book deleted");
    }
  };
  open("detail");
}

async function showAuthor(name) {
  $("#authorBody").innerHTML = `<h2>${esc(name)}</h2><p class="msg">Looking up author details…</p>`;
  open("author");
  const mine = state.books.filter((b) => (b.authors || []).includes(name))
    .sort((a, b) => (a.pub_year || 0) - (b.pub_year || 0));
  const minesHtml = `<div class="au-books"><h3>In your collection (${mine.length})</h3><ul>${mine.map((b) =>
    `<li data-id="${b.id}">${esc(b.title)}${b.pub_year ? ` (${b.pub_year})` : ""}${b.read ? " ✓" : ""}</li>`).join("")}</ul></div>`;
  let info = {};
  try { info = await api(`api/author?name=${encodeURIComponent(name)}`); } catch (err) { info = { error: err.message }; }
  const dates = [info.birth_date && `° ${info.birth_date}`, info.death_date && `† ${info.death_date}`].filter(Boolean).join("  ");
  $("#authorBody").innerHTML = `
    <h2>${esc(name)}</h2>
    <div class="au">
      <div>${info.photo_url ? `<img src="${esc(info.photo_url)}" alt="" onerror="this.remove()">` : ""}</div>
      <div>
        ${dates ? `<div class="dates">${esc(dates)}</div>` : ""}
        ${info.bio ? `<div class="bio">${esc(info.bio)}</div><div class="src">Source: ${esc(info.bio_source)}</div>`
                   : `<p class="msg">${info.error ? esc(info.error) : "No biography found online."}</p>`}
        ${info.work_count ? `<p class="msg">${info.work_count} works on Open Library${info.top_work ? ` · best known: <em>${esc(info.top_work)}</em>` : ""}</p>` : ""}
        <div class="links">${(info.links || []).map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`).join("")}</div>
      </div>
    </div>
    ${minesHtml}
    <p><button data-act="search-more">Find more books by ${esc(name)}</button> <button data-act="refresh">Refresh details</button></p>`;
  $("#authorBody").onclick = (e) => {
    const li = e.target.closest("li[data-id]");
    if (li) { close("author"); showBook(li.dataset.id); }
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "refresh") { api(`api/author?name=${encodeURIComponent(name)}&refresh=1`).then(() => showAuthor(name)); }
    if (act === "search-more") {
      close("author"); close("detail"); openAdd("search");
      $("#sAuthor").value = name; $("#sTitle").value = ""; runSearch();
    }
  };
}

/* ------------------------------------------------------------ add */

function openAdd(tab = "isbn") {
  $("#results").innerHTML = ""; setAddMsg("");
  switchTab(tab);
  open("add");
  setTimeout(() => (tab === "isbn" ? $("#isbn") : $("#sAuthor")).focus(), 50);
}

function switchTab(t) {
  $$("#addTabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
  $("#fIsbn").hidden = t !== "isbn";
  $("#fSearch").hidden = t !== "search";
  if (t !== "isbn") stopScan();
  if (t === "manual") { close("add"); editBook(null); }
}

function setAddMsg(msg, err = false) { const m = $("#addMsg"); m.textContent = msg; m.classList.toggle("err", err); }

function renderResults(list, already = []) {
  const box = $("#results");
  if (!list.length) { box.innerHTML = ""; return; }
  box._list = list;
  box.innerHTML = (already.length ? `<p class="msg err">You already have this ISBN: ${already.map((a) => `<a href="#" data-id="${a.id}">${esc(a.title)}</a>`).join(", ")}</p>` : "") +
    list.map((r, i) => `
    <div class="res ${i === 0 && list.length > 1 && r.source.includes("+") ? "best" : ""}">
      ${r.cover_url ? `<img src="${esc(r.cover_url)}" alt="" loading="lazy" onerror="this.outerHTML='<div class=noimg></div>'">` : `<div class="noimg"></div>`}
      <div>
        <div class="t">${esc(r.title)}${r.subtitle ? ` — <span class="a">${esc(r.subtitle)}</span>` : ""}<span class="srcb">${esc(r.source)}</span></div>
        <div class="a">${esc((r.authors || []).join(", "))}</div>
        <div class="m">${esc([r.publisher, r.pub_year, r.language, r.pages && r.pages + " p.", r.isbn && "ISBN " + r.isbn].filter(Boolean).join(" · "))}</div>
      </div>
      <div><button class="primary" data-pick="${i}">Use this</button></div>
    </div>`).join("");
}

$("#results").addEventListener("click", (e) => {
  const a = e.target.closest("a[data-id]");
  if (a) { e.preventDefault(); close("add"); showBook(a.dataset.id); return; }
  const p = e.target.closest("[data-pick]");
  if (!p) return;
  const r = $("#results")._list[+p.dataset.pick];
  close("add");
  editBook(null, { ...r, source: r.source, status: state.filter === "wishlist" ? "wishlist" : "collection" });
});

async function runIsbn(isbn) {
  isbn = (isbn || $("#isbn").value).replace(/[^0-9Xx]/g, "");
  if (!isbn) return;
  $("#isbn").value = isbn;
  setAddMsg("Searching Open Library and Google Books…"); $("#results").innerHTML = "";
  try {
    const d = await api(`api/lookup/isbn?isbn=${encodeURIComponent(isbn)}`);
    if (!d.results.length) {
      setAddMsg("Nothing found for this ISBN. Try author & title, or enter it manually.", true);
      $("#results").innerHTML = `<p><button data-manual>Enter manually with ISBN ${esc(isbn)}</button></p>`;
      $("#results [data-manual]").onclick = () => { close("add"); editBook(null, { isbn, title: "" }); };
    } else { setAddMsg(""); renderResults(d.results, d.already_have); }
  } catch (err) { setAddMsg(err.message, true); }
}

async function runSearch() {
  const author = $("#sAuthor").value.trim(), title = $("#sTitle").value.trim();
  if (!author && !title) return;
  setAddMsg("Searching…"); $("#results").innerHTML = "";
  try {
    const d = await api(`api/lookup/search?author=${encodeURIComponent(author)}&title=${encodeURIComponent(title)}`);
    setAddMsg(d.results.length ? `${d.results.length} results` : "Nothing found. Try fewer words, or enter it manually.", !d.results.length);
    renderResults(d.results);
  } catch (err) { setAddMsg(err.message, true); }
}

/* ------------------------------------------------------------ barcode scanning */

let reader = null, stream = null;
async function startScan() {
  $("#scanBox").hidden = false;
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera API");
    if (!window.ZXing) throw new Error("scanner not loaded");
    const hints = new Map();
    hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8, ZXing.BarcodeFormat.UPC_A]);
    reader = new ZXing.BrowserMultiFormatReader(hints);
    await reader.decodeFromConstraints({ video: { facingMode: "environment" } }, $("#video"), (res) => {
      if (res) { const code = res.getText(); stopScan(); navigator.vibrate?.(80); runIsbn(code); }
    });
  } catch (err) {
    console.warn("live scan unavailable", err);
    stopScan();
    setAddMsg("Live camera isn't available here — taking a photo of the barcode instead.");
    $("#photo").click();
  }
}
function stopScan() {
  try { reader?.reset(); } catch { /* */ }
  reader = null;
  stream?.getTracks().forEach((t) => t.stop()); stream = null;
  $("#scanBox").hidden = true;
}
async function decodePhoto(file) {
  if (!file) return;
  setAddMsg("Reading barcode from photo…");
  const url = URL.createObjectURL(file);
  try {
    if ("BarcodeDetector" in window) {
      const det = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a"] });
      const img = await createImageBitmap(file);
      const codes = await det.detect(img);
      if (codes.length) return runIsbn(codes[0].rawValue);
    }
    const r = new ZXing.BrowserMultiFormatReader();
    const res = await r.decodeFromImageUrl(url);
    runIsbn(res.getText());
  } catch {
    setAddMsg("No barcode found in that photo. Hold it closer and keep it sharp, or type the ISBN.", true);
  } finally { URL.revokeObjectURL(url); $("#photo").value = ""; }
}

/* ------------------------------------------------------------ edit */

const FIELDS = ["title", "subtitle", "authors", "series", "isbn", "publisher", "pub_year", "pages", "language", "format",
  "location", "status", "owner", "read", "read_date", "rating", "purchase_date", "purchase_price", "store",
  "subjects", "tags", "plot", "notes", "cover_url"];

function editBook(book, prefill = {}) {
  state.editing = book ? book.id : null;
  const b = { status: "collection", rating: 0, ...(book || {}), ...prefill };
  const f = $("#fEdit");
  f.reset();
  for (const k of FIELDS) {
    const el = f.elements[k]; if (!el) continue;
    let v = b[k];
    if (Array.isArray(v)) v = v.join("; ");
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v ?? "";
  }
  f._source = b.source || (book ? book.source : "Manual");
  $("#eCover").src = b.cover || b.cover_url || "";
  $("#editTitle").textContent = book ? "Edit book" : "New book";
  $("#editMsg").textContent = "";
  open("edit");
  setTimeout(() => f.elements.title.focus(), 50);
}

function formData() {
  const f = $("#fEdit"), d = {};
  for (const k of FIELDS) {
    const el = f.elements[k]; if (!el) continue;
    d[k] = el.type === "checkbox" ? el.checked : el.value.trim();
  }
  return d;
}

$("#fEdit").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData();
  try {
    let saved;
    if (state.editing) {
      saved = await api(`api/books/${state.editing}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    } else {
      d.source = $("#fEdit")._source || "Manual";
      saved = await api("api/books", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    }
    close("edit"); await load(); toast(state.editing ? "Saved" : `Added “${saved.title}”`);
    showBook(saved.id);
  } catch (err) { $("#editMsg").textContent = err.message; $("#editMsg").classList.add("err"); }
});

$("#fEdit").elements.cover_url.addEventListener("change", (e) => ($("#eCover").src = e.target.value));

$("#btnFill").addEventListener("click", async () => {
  const f = $("#fEdit"), d = formData(), msg = $("#editMsg");
  msg.classList.remove("err");
  msg.textContent = "Looking up…";
  try {
    let r = null;
    if (d.isbn) r = (await api(`api/lookup/isbn?isbn=${encodeURIComponent(d.isbn)}`)).results[0];
    if (!r && (d.title || d.authors)) {
      r = (await api(`api/lookup/search?title=${encodeURIComponent(d.title)}&author=${encodeURIComponent(d.authors.split(";")[0] || "")}`)).results[0];
    }
    if (!r) { msg.textContent = "Nothing found online."; return; }
    let n = 0;
    for (const k of FIELDS) {
      const el = f.elements[k]; if (!el || el.type === "checkbox" || el.tagName === "SELECT") continue;
      let v = r[k]; if (Array.isArray(v)) v = v.join("; ");
      if (!el.value.trim() && v) { el.value = v; n++; }
    }
    if (f.elements.cover_url.value) $("#eCover").src = f.elements.cover_url.value;
    msg.textContent = n ? `Filled ${n} empty field${n > 1 ? "s" : ""} from ${r.source}.` : "No empty fields to fill.";
  } catch (err) { msg.textContent = err.message; msg.classList.add("err"); }
});

/* ------------------------------------------------------------ import */

async function importFile(file) {
  if (!file) return;
  toast("Importing… this can take a moment", 10000);
  try {
    const r = await api("api/import/clz", { method: "POST", headers: { "Content-Type": "application/xml" }, body: file });
    await load();
    toast(`Imported ${r.total} books: ${r.added} new, ${r.updated} updated. Covers are being saved in the background.`, 6000);
  } catch (err) { toast("Import failed: " + err.message, 8000); }
  $("#importFile").value = "";
}

/* ------------------------------------------------------------ wiring */

$("#q").addEventListener("input", (e) => { state.q = e.target.value; render(); });
$("#chips").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  state.filter = b.dataset.f; $$("#chips button").forEach((x) => x.classList.toggle("on", x === b)); render();
});
$("#lang").addEventListener("change", (e) => { state.lang = e.target.value; render(); });
$("#sort").value = state.sort;
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; localStorage.setItem("books.sort", state.sort); render(); });
$$("#view button").forEach((b) => b.classList.toggle("on", b.dataset.v === state.view));
$("#view").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  state.view = b.dataset.v; localStorage.setItem("books.view", state.view);
  $$("#view button").forEach((x) => x.classList.toggle("on", x === b)); render();
});
$("#grid").addEventListener("click", (e) => { const b = e.target.closest(".book"); if (b) showBook(b.dataset.id); });
$("#btnAdd").addEventListener("click", () => openAdd("isbn"));
$("#addTabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) switchTab(b.dataset.t); });
$("#fIsbn").addEventListener("submit", (e) => { e.preventDefault(); runIsbn(); });
$("#fSearch").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
$("#btnScan").addEventListener("click", startScan);
$("#btnStopScan").addEventListener("click", stopScan);
$("#photo").addEventListener("change", (e) => decodePhoto(e.target.files[0]));
$("#importFile").addEventListener("change", (e) => importFile(e.target.files[0]));

$("#btnMenu").addEventListener("click", async (e) => {
  e.stopPropagation();
  const m = $("#menu"); m.hidden = !m.hidden;
  if (!m.hidden) {
    try {
      const s = await api("api/stats");
      $("#statsLine").textContent = `${s.total} books · ${s.read} read · ${s.wishlist} wishlist · ${s.authors} authors · ` +
        (s.covers.running ? `saving covers ${s.covers.done}/${s.covers.total}` : `v${s.version}`);
    } catch { /* */ }
  }
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".menu")) $("#menu").hidden = true;
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "import") { $("#menu").hidden = true; $("#importFile").click(); }
  if (act === "add") openAdd("isbn");
  if (act === "covers") { $("#menu").hidden = true; api("api/covers/retry", { method: "POST" }).then(() => toast("Retrying missing covers")); }
  const c = e.target.closest("[data-close]");
  if (c) close(c.closest(".sheet").id);
  if (e.target.classList.contains("sheet")) close(e.target.id);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { const s = $$(".sheet").reverse().find((x) => !x.hidden); if (s) close(s.id); }
  if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") { e.preventDefault(); $("#q").focus(); }
});

load().catch((err) => toast("Could not load books: " + err.message, 8000));
