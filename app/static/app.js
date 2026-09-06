"use strict";

const AREAS = [
  ["all", "All focus areas"], ["a", "People Movement"], ["b", "Regulated Goods"],
  ["c", "Cross-border Smuggling"], ["d", "Coastal & Maritime"],
  ["e", "Cross-Cutting Enablers"], ["news", "Daily News"], ["x", "Areas of Interest"],
];
const LABELS = Object.fromEntries(AREAS);
const PRODUCTS = ["Threat Assessment", "Risk Assessment", "Modus Operandi Profile", "Watch Note"];
const QUICK = [
  "Threats against Cape Town International Airport",
  "Risk of illegal border crossing from Zimbabwe (Beitbridge)",
  "Modus operandi of syndicates smuggling narcotics into Gauteng",
];
const uiKey = "nbtc_brief_ui_v1";
const state = {
  me:null, csrf:"", brief:{clusters:{}}, interests:[], watch:{open:[],archived:[]},
  assessments:[], exports:[], users:[], active:"all",
};
try { state.active = JSON.parse(localStorage.getItem(uiKey) || "{}").active || "all"; } catch (_) {}

const view = document.getElementById("view");
const statusBox = document.getElementById("status");
const dialog = document.getElementById("documentDialog");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
}
function date(value) { return value ? new Date(value).toLocaleString() : ""; }
function canWrite() { return state.me && ["analyst","admin"].includes(state.me.role); }
function setStatus(text, error=false) { statusBox.textContent = text || ""; statusBox.className = error ? "status error" : "status"; }

async function api(path, options={}) {
  const init = {...options, headers:{...(options.headers || {})}};
  if (init.body && typeof init.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  if (init.method && !["GET","HEAD"].includes(init.method.toUpperCase())) init.headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(path, init);
  if (response.status === 401) { location.assign("/login"); throw new Error("Authentication required"); }
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.detail || payload?.error || `HTTP ${response.status}`);
  return payload;
}

async function load() {
  try {
    state.me = await api("/api/me"); state.csrf = state.me.csrf;
    const [brief, interests, watch, assessments, exports] = await Promise.all([
      api("/api/brief"), api("/api/interests"), api("/api/watchlist"),
      api("/api/assessments"), api("/api/exports"),
    ]);
    state.brief = brief; state.interests = interests.interests; state.watch = watch;
    state.assessments = assessments.assessments; state.exports = exports.exports;
    await api("/api/brief/viewed", {method:"POST"});
    if (state.me.role === "admin") state.users = (await api("/api/users")).users;
    document.getElementById("identity").innerHTML = `<div>${esc(state.me.displayName || state.me.email)}</div><div class="role">${esc(state.me.role)}</div>`;
    document.getElementById("refreshBtn").hidden = !canWrite();
    render();
  } catch (error) { setStatus(error.message, true); }
}

function allArticles() {
  return Object.values(state.brief.clusters || {}).flat();
}
function articlesFor(area) {
  if (area === "all") return ["a","b","c","d","e"].flatMap(key => state.brief.clusters[key] || []);
  return state.brief.clusters[area] || [];
}
function isPinned(articleId) { return state.watch.open.some(item => item.articleId === articleId); }

function renderTabs() {
  const items = [...AREAS, ["watch","Watchlist"], ["assess","Assessments"], ["exports","Exports"]];
  if (state.me.role === "admin") items.push(["admin","Administration"]);
  document.getElementById("tabs").innerHTML = items.map(([key,label]) => {
    let count = "";
    if (AREAS.some(([value]) => value === key)) count = articlesFor(key).length;
    if (key === "watch") count = state.watch.open.length;
    if (key === "assess") count = state.assessments.length;
    if (key === "exports") count = state.exports.length;
    return `<button class="tab ${state.active === key ? "active" : ""}" data-tab="${key}" type="button">${esc(label)}${count !== "" ? `<span class="count">${count}</span>` : ""}</button>`;
  }).join("");
  document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click", () => {
    state.active = button.dataset.tab; localStorage.setItem(uiKey, JSON.stringify({active:state.active})); render();
  }));
}

function articleCard(item) {
  const pinned = isPinned(item.id);
  return `<article class="card">
    <div class="card-top"><div><span class="tag">${esc(item.sourceName)}</span><span class="tag">${esc(item.sub)}</span></div>
      ${canWrite() ? `<button class="secondary" data-pin="${item.id}" data-area="${esc(item.area)}" ${pinned ? "disabled" : ""}>${pinned ? "Pinned" : "Pin"}</button>` : ""}</div>
    <div class="headline">${esc(item.headline)}</div>
    ${item.note ? `<div class="summary">${esc(item.note)}</div>` : ""}
    <div class="meta">${esc(item.date)} · <a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">source</a>${item.scope === "intl" ? " · International context" : ""}</div>
  </article>`;
}

function renderBrief(area) {
  const articles = articlesFor(area);
  const refreshed = state.brief.run ? `Last successful refresh ${date(state.brief.run.completedAt)}` : "No successful refresh yet";
  view.innerHTML = `<div class="view-head"><div><h2>${esc(LABELS[area])}</h2><div class="sub">${esc(refreshed)}</div></div></div>
    ${articles.length ? `<div class="grid">${articles.map(articleCard).join("")}</div>` : '<div class="empty">No current articles. An analyst can run the first refresh.</div>'}`;
  view.querySelectorAll("[data-pin]").forEach(button => button.addEventListener("click", async () => {
    try { await api("/api/watchlist", {method:"POST", body:{articleId:Number(button.dataset.pin), area:button.dataset.area}}); await reloadOperational(); }
    catch (error) { setStatus(error.message, true); }
  }));
}

function renderInterests() {
  const articles = articlesFor("x");
  view.innerHTML = `<div class="view-head"><div><h2>Areas of Interest</h2><div class="sub">Shared time-limited watch topics included in every refresh.</div></div></div>
    ${canWrite() ? `<form id="interestForm" class="panel form-row"><input id="interestLabel" maxlength="200" required placeholder="Short name"><input id="interestQuery" maxlength="500" required placeholder="Search terms"><button class="primary">Add</button></form>` : ""}
    <div class="chips">${state.interests.map(item => `<span class="tag">${esc(item.label)} ${canWrite() ? `<button class="quiet" data-interest-delete="${item.id}" aria-label="Remove">×</button>` : ""}</span>`).join("") || "No shared topics."}</div>
    ${articles.length ? `<div class="grid">${articles.map(articleCard).join("")}</div>` : '<div class="empty">No collected articles for the active topics.</div>'}`;
  document.getElementById("interestForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    try { await api("/api/interests", {method:"POST", body:{label:document.getElementById("interestLabel").value,query:document.getElementById("interestQuery").value}}); await reloadOperational(); }
    catch (error) { setStatus(error.message, true); }
  });
  view.querySelectorAll("[data-interest-delete]").forEach(button => button.addEventListener("click", async () => {
    try { await api(`/api/interests/${button.dataset.interestDelete}`, {method:"DELETE"}); await reloadOperational(); }
    catch (error) { setStatus(error.message, true); }
  }));
  view.querySelectorAll("[data-pin]").forEach(button => button.addEventListener("click", async () => {
    try { await api("/api/watchlist", {method:"POST", body:{articleId:Number(button.dataset.pin),area:"x"}}); await reloadOperational(); }
    catch (error) { setStatus(error.message, true); }
  }));
}

function watchItem(item, archived=false) {
  return `<section class="watch-item"><span class="tag">${esc(LABELS[item.area] || item.area)}</span>
    <div class="headline">${esc(item.headline)}</div><div class="meta">Pinned ${date(item.pinnedAt)} · <a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">source</a></div>
    ${item.notes.length ? `<ul class="notes">${item.notes.map(note => `<li>${esc(note.text)} <span>${date(note.createdAt)}</span></li>`).join("")}</ul>` : ""}
    ${canWrite() && !archived ? `<form class="form-row note-form" data-watch="${item.id}"><input maxlength="4000" required placeholder="Add a tracking note"><button class="secondary">Add note</button><button class="quiet" data-archive="${item.id}" type="button">Close and archive</button></form>` : ""}</section>`;
}

function renderWatch() {
  view.innerHTML = `<div class="view-head"><div><h2>Watchlist</h2><div class="sub">Shared tracking notes and archived items.</div></div>
    ${canWrite() ? '<button class="secondary" id="archiveExport">Create archive export</button>' : ""}</div>
    <div class="split"><div class="panel"><h3>Open (${state.watch.open.length})</h3>${state.watch.open.map(item => watchItem(item)).join("") || '<div class="empty">Nothing is currently pinned.</div>'}</div>
    <div class="panel"><h3>Archive (${state.watch.archived.length})</h3>${state.watch.archived.slice().reverse().map(item => watchItem(item,true)).join("") || '<div class="empty">The archive is empty.</div>'}</div></div>`;
  view.querySelectorAll(".note-form").forEach(form => form.addEventListener("submit", async event => {
    event.preventDefault();
    try { await api(`/api/watchlist/${form.dataset.watch}/notes`, {method:"POST",body:{text:form.querySelector("input").value}}); await reloadOperational(); }
    catch (error) { setStatus(error.message, true); }
  }));
  view.querySelectorAll("[data-archive]").forEach(button => button.addEventListener("click", async () => {
    try { await api(`/api/watchlist/${button.dataset.archive}/archive`, {method:"POST"}); await reloadOperational(); }
    catch (error) { setStatus(error.message, true); }
  }));
  document.getElementById("archiveExport")?.addEventListener("click", () => createExport({kind:"archive",format:"markdown"}));
}

function renderAssessments() {
  view.innerHTML = `<div class="view-head"><div><h2>Risk / Threat Assessments</h2><div class="sub">Products use server-selected records from the latest successful briefing.</div></div></div>
    ${canWrite() ? `<form id="assessmentForm" class="panel"><div class="form-row"><select id="product">${PRODUCTS.map(value => `<option>${esc(value)}</option>`).join("")}</select><input id="assessmentQuery" maxlength="2000" required placeholder="Assessment question"><button class="primary" ${state.me.aiEnabled ? "" : "disabled"}>Generate</button></div>
      <div class="chips">${QUICK.map(value => `<button class="secondary quick" type="button" data-query="${esc(value)}">${esc(value)}</button>`).join("")}</div>
      <div class="sub">${state.me.aiEnabled ? "Up to 50 current source records will be sent to the configured Anthropic service." : "AI assessment generation is disabled on this server."}</div></form>` : ""}
    <div class="panel">${state.assessments.map(item => `<section class="assessment"><strong>${esc(item.product)} — ${esc(item.query)}</strong><div class="meta">${date(item.createdAt)}</div><div class="actions"><button class="secondary" data-view-assessment="${item.id}">View</button>${canWrite() ? `<button class="primary" data-export-assessment="${item.id}">Create DOCX</button>` : ""}</div></section>`).join("") || '<div class="empty">No assessments have been generated.</div>'}</div>`;
  view.querySelectorAll(".quick").forEach(button => button.addEventListener("click", () => { document.getElementById("assessmentQuery").value = button.dataset.query; }));
  document.getElementById("assessmentForm")?.addEventListener("submit", async event => {
    event.preventDefault(); setStatus("Generating assessment…");
    try {
      await api("/api/assessments", {method:"POST", body:{product:document.getElementById("product").value,query:document.getElementById("assessmentQuery").value,articleIds:allArticles().slice(0,50).map(item=>item.id)}});
      state.assessments = (await api("/api/assessments")).assessments; setStatus("Assessment generated."); render();
    } catch (error) { setStatus(error.message, true); }
  });
  view.querySelectorAll("[data-view-assessment]").forEach(button => button.addEventListener("click", () => {
    const item = state.assessments.find(value => value.id === Number(button.dataset.viewAssessment));
    document.getElementById("dialogTitle").textContent = `${item.product} — ${item.query}`;
    document.getElementById("dialogBody").textContent = item.result; dialog.showModal();
  }));
  view.querySelectorAll("[data-export-assessment]").forEach(button => button.addEventListener("click", () => createExport({kind:"assessment",assessmentId:Number(button.dataset.exportAssessment)})));
}

async function createExport(body) {
  try { await api("/api/exports", {method:"POST",body}); state.exports = (await api("/api/exports")).exports; setStatus("Export created and retained on the server."); render(); }
  catch (error) { setStatus(error.message, true); }
}
function renderExports() {
  view.innerHTML = `<div class="view-head"><div><h2>Exports</h2><div class="sub">Retained products are available to every authorised user.</div></div></div><div class="panel">
    ${state.exports.map(item => `<section class="export"><strong>${esc(item.name)}</strong><div class="meta">${date(item.createdAt)} · ${Math.ceil(item.size/1024)} KB</div><div class="actions"><a class="secondary" href="/api/exports/${item.id}/download">Download</a>${state.me.role === "admin" ? `<button class="danger" data-delete-export="${item.id}">Delete</button>` : ""}</div></section>`).join("") || '<div class="empty">No retained exports.</div>'}</div>`;
  view.querySelectorAll("[data-delete-export]").forEach(button => button.addEventListener("click", async () => {
    try { await api(`/api/exports/${button.dataset.deleteExport}`, {method:"DELETE"}); state.exports=(await api("/api/exports")).exports; render(); }
    catch (error) { setStatus(error.message, true); }
  }));
}

function renderAdmin() {
  view.innerHTML = `<div class="view-head"><div><h2>Administration</h2><div class="sub">Approved accounts and one-time migration.</div></div><a href="/legacy-export">Export legacy browser data</a></div>
    <form id="userForm" class="panel form-row"><input id="newEmail" type="email" required placeholder="Approved email"><select id="newRole"><option>viewer</option><option>analyst</option><option>admin</option></select><button class="primary">Add user</button></form>
    <div class="panel"><table><thead><tr><th>Email</th><th>Role</th><th>Active</th><th></th></tr></thead><tbody>${state.users.map(user => `<tr><td>${esc(user.email)}</td><td><select data-user-role="${user.id}"><option ${user.role==="viewer"?"selected":""}>viewer</option><option ${user.role==="analyst"?"selected":""}>analyst</option><option ${user.role==="admin"?"selected":""}>admin</option></select></td><td><input data-user-active="${user.id}" type="checkbox" ${user.is_active?"checked":""}></td><td><button class="secondary" data-save-user="${user.id}">Save</button></td></tr>`).join("")}</tbody></table></div>
    <form id="importForm" class="panel"><h3>Import legacy migration file</h3><div class="form-row"><input id="importFile" type="file" accept="application/json" required><button class="primary">Import</button></div></form>`;
  document.getElementById("userForm").addEventListener("submit", async event => {
    event.preventDefault(); try { await api("/api/users",{method:"POST",body:{email:document.getElementById("newEmail").value,role:document.getElementById("newRole").value}}); state.users=(await api("/api/users")).users; render(); } catch(error){setStatus(error.message,true);}
  });
  view.querySelectorAll("[data-save-user]").forEach(button => button.addEventListener("click", async () => {
    const id=Number(button.dataset.saveUser), user=state.users.find(value=>value.id===id);
    try { await api("/api/users",{method:"POST",body:{id,email:user.email,role:view.querySelector(`[data-user-role="${id}"]`).value,is_active:view.querySelector(`[data-user-active="${id}"]`).checked,display_name:user.display_name}}); state.users=(await api("/api/users")).users; render(); } catch(error){setStatus(error.message,true);}
  }));
  document.getElementById("importForm").addEventListener("submit", async event => {
    event.preventDefault(); const file=document.getElementById("importFile").files[0]; if(!file)return;
    try { const response=await fetch("/api/import/legacy",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:await file.text()}); const data=await response.json(); if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`); setStatus(data.duplicate?"This migration was already imported.":"Legacy records imported."); await reloadOperational(); } catch(error){setStatus(error.message,true);}
  });
}

function render() {
  renderTabs();
  if (AREAS.some(([key]) => key === state.active)) state.active === "x" ? renderInterests() : renderBrief(state.active);
  else if (state.active === "watch") renderWatch();
  else if (state.active === "assess") renderAssessments();
  else if (state.active === "exports") renderExports();
  else if (state.active === "admin" && state.me.role === "admin") renderAdmin();
  else { state.active = "all"; renderBrief("all"); }
}

async function reloadOperational() {
  const [brief, interests, watch] = await Promise.all([api("/api/brief"),api("/api/interests"),api("/api/watchlist")]);
  state.brief=brief; state.interests=interests.interests; state.watch=watch; render();
}
async function pollRefresh(id) {
  for (;;) {
    const run=await api(`/api/refresh/${id}`);
    if (["succeeded","failed","interrupted"].includes(run.status)) {
      document.getElementById("refreshBtn").disabled=false;
      if (run.status === "succeeded") { setStatus("Shared briefing refreshed."); await reloadOperational(); }
      else setStatus(run.error || "Refresh failed; the last successful briefing is unchanged.", true);
      return;
    }
    await new Promise(resolve => setTimeout(resolve,1500));
  }
}

document.getElementById("refreshBtn").addEventListener("click", async event => {
  event.currentTarget.disabled=true; setStatus("Refresh queued…");
  try { const run=await api("/api/refresh",{method:"POST"}); await pollRefresh(run.id); }
  catch(error){event.currentTarget.disabled=false;setStatus(error.message,true);}
});
document.getElementById("logoutBtn").addEventListener("click", async () => { try { await api("/logout",{method:"POST"}); location.assign("/login"); } catch(error){setStatus(error.message,true);} });
document.getElementById("dialogClose").addEventListener("click", () => dialog.close());
load();
