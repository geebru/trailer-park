import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { api } from "../api.js";
import { number } from "../format.js";
import { store } from "../store.js";
import { openManual, openFiles, openRename, openGrabAll, startJob } from "../dialogs.js";
import { setDisabled } from "../tip.js";
import { toast } from "../toast.js";
import { pageHeading, notice } from "./common.js";

export const title = "Trailers";

const PER_PAGE = [10, 25, 50, 100, 250];
const VIEWS = [
  { value: "", label: "All titles" },
  { value: "status:present", label: "Available" },
  { value: "status:missing", label: "Missing" },
  { value: "tag:name_differs", label: "Name mismatch" },
  { value: "tag:multiple", label: "Multiple found" },
];

function bytes(n) {
  if (!n) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

export function mount(container, { query, navigate }) {
  // All view state lives in the URL, so filters survive reload, back/forward and links like "Review".
  const state = {
    type: query.get("type") === "series" ? "series" : "movie",
    q: query.get("q") || "",
    connection: query.get("connection") || "",
    root: query.get("root") || "",
    view: query.get("status") ? `status:${query.get("status")}` : query.get("tag") ? `tag:${query.get("tag")}` : "",
    per_page: PER_PAGE.includes(+query.get("per_page")) ? +query.get("per_page") : 25,
    page: Math.max(1, parseInt(query.get("page") || "1", 10) || 1),
  };
  let data = null;
  let seq = 0;
  let timer = null;
  let typing = null;
  let stopped = false;
  const picked = new Map();   // "connection:id" -> {connection, id} of missing titles chosen for a batch; survives paging, not filters

  function url(extra = {}) {
    const s = { ...state, ...extra };
    const p = new URLSearchParams();
    if (s.type === "series") p.set("type", "series");
    if (s.q) p.set("q", s.q);
    if (s.connection) p.set("connection", s.connection);
    if (s.root) p.set("root", s.root);
    if (s.view) { const [k, v] = s.view.split(":"); p.set(k, v); }
    if (s.per_page !== 25) p.set("per_page", s.per_page);
    if (s.page > 1) p.set("page", s.page);
    const qs = p.toString();
    return "/trailers" + (qs ? `?${qs}` : "");
  }
  function change(patch) {
    Object.assign(state, { page: 1 }, patch);
    picked.clear();
    history.replaceState({}, "", url());
    load();
  }
  function go(page) { state.page = page; history.pushState({}, "", url()); load(); window.scrollTo(0, 0); }

  /* ── Static frame ─────────────────────────────────────────────────── */
  const bannersEl = h("div", { class: "banners" });
  const actionsEl = h("div", { class: "page-heading__actions" });
  const tabsEl = h("div", { class: "tabs", role: "group", "aria-label": "Library type" });
  const searchEl = h("input", {
    type: "search", class: "input", placeholder: "Search titles", "aria-label": "Search titles", value: state.q, autocomplete: "off",
    oninput: (e) => { clearTimeout(typing); typing = setTimeout(() => change({ q: e.target.value.trim() }), 250); },
  });
  const connEl = h("select", { class: "select", "aria-label": "Filter by connection", onchange: (e) => change({ connection: e.target.value, root: "" }) });
  const rootEl = h("select", { class: "select", "aria-label": "Filter by folder", hidden: true, onchange: (e) => change({ root: e.target.value }) });
  const viewEl = h("select", { class: "select", "aria-label": "Filter by trailer status", onchange: (e) => change({ view: e.target.value }) },
    VIEWS.map((v) => h("option", { value: v.value }, v.label)));
  const listEl = h("ul", { class: "trailer-list" });
  const selectEl = h("div", { class: "trailer-select", hidden: true });
  const footEl = h("div", { class: "trailer-foot" });

  const heading = pageHeading("Trailers", actionsEl);
  container.append(h("div", { class: "page" }, heading, bannersEl,
    h("section", { class: "panel trailers", "aria-label": "Library" },
      h("div", { class: "trailers__bar" }, tabsEl,
        h("div", { class: "trailers__filters" }, h("label", { class: "search" }, icon("magnifying-glass"), searchEl), connEl, rootEl, viewEl)),
      selectEl,
      h("div", { class: "trailer-table" },
        h("div", { class: "trailer-head", "aria-hidden": "true" }, h("span", {}, "Title"), h("span", {}, "Trailer"), h("span", {}, "Actions")),
        listEl),
      footEl)));
  viewEl.value = state.view;

  /* ── Rendering ────────────────────────────────────────────────────── */
  function activeJob(item) {
    return (store.get("jobs") || []).find((j) => j.connection_id === item.connection_id && j.item_id === item.id);
  }

  function scope() {
    const o = { type: state.type };
    if (state.connection) o.connection = state.connection;
    return o;
  }
  function scopeLabel() {
    const conn = (data?.filters.connections || []).find((c) => c.id === state.connection);
    return `${state.type === "series" ? "Shows" : "Movies"} · ${conn ? conn.name : "all connections"}`;
  }

  function renderTabs() {
    const totals = store.get("overview")?.totals;
    replace(tabsEl, [["movie", "Movies", "film", totals?.movies], ["series", "Shows", "tv", totals?.series]].map(([value, label, ic, count]) =>
      h("button", { type: "button", class: "tab", "aria-pressed": String(state.type === value), onclick: () => {
        if (state.type !== value) { state.connection = ""; state.root = ""; state.view = ""; viewEl.value = ""; change({ type: value }); }
      } }, icon(ic), label, count != null ? h("span", { class: "tab__count mono" }, number(count)) : null)));
  }

  function renderFilters() {
    const f = data.filters;
    replace(connEl, h("option", { value: "" }, "All connections"), f.connections.map((c) => h("option", { value: c.id }, c.name)));
    connEl.value = state.connection;
    connEl.hidden = f.connections.length < 2;
    replace(rootEl, h("option", { value: "" }, "All folders"), f.roots.map((r) => h("option", { value: r }, r.split("/").filter(Boolean).slice(-1)[0] || r)));
    rootEl.value = state.root;
    rootEl.hidden = f.roots.length < 2;
    searchEl.placeholder = state.type === "series" ? "Search shows" : "Search movies";
  }

  function renderActions() {
    const c = data.counts;
    replace(actionsEl,
      c.name_differs ? h("button", { type: "button", class: "btn btn--secondary", onclick: () => openRename(scope(), { onChange: load }) }, icon("folder"), `Rename ${number(c.name_differs)}`) : null,
      c.missing ? h("button", { type: "button", class: "btn btn--primary", onclick: () => openGrabAll(scope(), { count: c.missing, label: scopeLabel(), onChange: load }) }, icon("wand-magic-sparkles"), `Grab ${number(c.missing)} missing`) : null);
  }

  function renderBanners() {
    const out = [];
    if (data.scan.state !== "ready") out.push(notice("info", data.items.length ? "Still scanning your libraries. Results may be incomplete." : "Scanning your libraries. This can take a minute."));
    for (const e of data.errors || []) out.push(notice("danger", typeof e === "string" ? e : e.message || `${e.connection || "A connection"} could not be reached.`));
    replace(bannersEl, out);
  }

  const keyOf = (item) => `${item.connection_id}:${item.id}`;
  const refOf = (item) => ({ connection: item.connection_id, id: item.id });
  const selectable = (item) => item.presence === "missing" && !activeJob(item);

  function toggle(item, on) {
    on ? picked.set(keyOf(item), refOf(item)) : picked.delete(keyOf(item));
    renderSelect();
    updateRowChecks();
  }

  function updateRowChecks() {
    for (const box of listEl.querySelectorAll("input[data-key]")) box.checked = picked.has(box.dataset.key);
  }

  async function grabSelected() {
    const items = [...picked.values()];
    if (!items.length) return;
    try {
      const { batch } = await api.post("/batches", { items });
      store.set("batch", batch);
      toast(`Started grabbing ${number(batch.total)} trailer${batch.total === 1 ? "" : "s"}.`, "success");
      picked.clear();
      load();
    } catch (e) { toast(e.message, "danger", 8000); }
  }

  function renderSelect() {
    const rows = data.items.filter(selectable);
    selectEl.hidden = !rows.length && !picked.size;
    if (selectEl.hidden) return;
    const onPage = rows.filter((i) => picked.has(keyOf(i))).length;
    const all = h("input", { type: "checkbox", id: "select-page", checked: rows.length > 0 && onPage === rows.length,
      onchange: (e) => { for (const i of rows) e.target.checked ? picked.set(keyOf(i), refOf(i)) : picked.delete(keyOf(i)); renderSelect(); updateRowChecks(); } });
    all.indeterminate = onPage > 0 && onPage < rows.length;
    if (!rows.length) all.disabled = true;
    const batchRunning = store.get("batch")?.status === "running";
    const grab = h("button", { type: "button", class: "btn btn--primary btn--sm", onclick: grabSelected }, icon("download"), picked.size ? `Grab ${number(picked.size)} selected` : "Grab selected");
    setDisabled(grab, batchRunning ? "A batch is already running. Wait for it to finish or cancel it in the sidebar." : !picked.size && "Select at least one title with no trailer first");
    replace(selectEl,
      h("label", { class: "trailer-select__all", for: "select-page" }, all, h("span", {}, "Select all missing on this page")),
      h("div", { class: "trailer-select__actions" },
        picked.size ? h("span", { class: "muted", role: "status" }, `${number(picked.size)} selected`) : null,
        picked.size ? h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: () => { picked.clear(); renderSelect(); updateRowChecks(); } }, "Clear") : null,
        grab));
  }

  function actionButtons(item) {
    const job = activeJob(item);
    if (job) {
      return h("span", { class: "status status--info" }, job.status === "queued" ? "Queued" : `Downloading${job.progress != null ? ` ${Math.round(job.progress)}%` : ""}`);
    }
    const run = (replace) => () => startJob(`/items/${item.connection_id}/${item.id}/grab`, { replace }, { onDone: load });
    const manual = h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: () => openManual(item, { onDone: load }) }, icon("link"), "Manual");
    return item.presence === "missing"
      ? [manual, h("button", { type: "button", class: "btn btn--primary btn--sm", onclick: run(false) }, icon("download"), "Grab")]
      : [manual,
         h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: run(true) }, icon("download"), "Replace"),
         h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: () => openFiles(item, { onChange: load }) }, icon("folder"), "Files")];
  }

  function check(item) {
    if (!selectable(item)) return h("span", { class: "trailer-row__check", "aria-hidden": "true" });
    const key = keyOf(item);
    return h("label", { class: "trailer-row__check" },
      h("input", { type: "checkbox", "aria-label": `Select ${item.title}${item.year ? ` (${item.year})` : ""}`, dataset: { key }, checked: picked.has(key),
        onchange: (e) => toggle(item, e.target.checked) }));
  }

  function row(item) {
    const missing = item.presence === "missing";
    return h("li", { class: "trailer-row" },
      h("div", { class: "trailer-row__title" },
        h("div", { class: "trailer-row__name" }, check(item), icon(item.type === "series" ? "tv" : "film", "icon tone-neutral"), h("span", {}, item.title)),
        h("div", { class: "trailer-row__meta" }, [item.year, item.connection_name].filter(Boolean).join(" · "))),
      h("div", { class: "trailer-row__file" }, missing
        ? h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), "No trailer file")
        : [h("div", { class: "trailer-row__path" }, (item.primary_file || "").replace(/^trailers\//i, "")),
           h("div", { class: "trailer-row__flags" },
             item.file_count === 1 && item.total_size ? h("span", { class: "trailer-row__size" }, bytes(item.total_size)) : null,
             item.name_differs ? h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), "Name mismatch") : null,
             item.file_count > 1 ? h("span", { class: "flag tone-info" }, icon("circle-info"), `${item.file_count} files`) : null)]),
      h("div", { class: "trailer-row__actions" }, actionButtons(item)));
  }

  function renderRows() {
    // Job polling repaints the rows; keep keyboard focus on the checkbox the user is on.
    const focused = document.activeElement?.dataset?.key;
    listEl.classList.toggle("trailer-list--select", data.items.some(selectable));
    replace(listEl, data.items.length ? data.items.map(row)
      : h("li", { class: "activity-empty" }, data.scan.state !== "ready" ? "Scanning…" : "No titles match your filters."));
    if (focused) listEl.querySelector(`input[data-key="${focused}"]`)?.focus();
    renderSelect();
    const pages = Math.max(1, Math.ceil(data.total / data.per_page));
    const from = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const to = Math.min(data.total, data.page * data.per_page);
    replace(footEl,
      h("div", { class: "trailer-foot__left" },
        h("span", { class: "muted" }, `Showing ${number(from)}–${number(to)} of ${number(data.total)} matching titles`),
        h("label", { class: "rows-per-page" }, h("span", {}, "Rows per page"),
          h("select", { class: "select select--sm", "aria-label": "Rows per page", onchange: (e) => change({ per_page: +e.target.value }) },
            PER_PAGE.map((n) => h("option", { value: n, selected: n === state.per_page }, n))))),
      pages > 1 ? h("div", { class: "pager pager--inline" },
        setDisabled(h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: () => go(data.page - 1) }, icon("chevron-left"), "Previous"), data.page <= 1 && "This is the first page"),
        h("span", { class: "muted" }, `Page ${data.page} of ${pages}`),
        setDisabled(h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: () => go(data.page + 1) }, "Next", icon("chevron-right")), data.page >= pages && "This is the last page")) : null);
  }

  async function load() {
    clearTimeout(timer);
    const mine = ++seq;
    const p = new URLSearchParams({ type: state.type, page: state.page, per_page: state.per_page });
    if (state.q) p.set("q", state.q);
    if (state.connection) p.set("connection", state.connection);
    if (state.root) p.set("root", state.root);
    if (state.view) { const [k, v] = state.view.split(":"); p.set(k, v); }
    try {
      const result = await api.get(`/items?${p}`);
      if (mine !== seq || stopped) return;
      data = result;
      const pages = Math.max(1, Math.ceil(data.total / data.per_page));
      if (state.page > pages) { state.page = pages; return load(); }
      renderTabs(); renderFilters(); renderActions(); renderBanners(); renderRows();
      if (data.scan.state !== "ready") timer = setTimeout(load, 2000);
    } catch (err) {
      if (mine === seq && !stopped) replace(bannersEl, notice("danger", err.message));
    }
  }

  // A running job disappearing from the list means an item changed; reload so the row catches up.
  let before = (store.get("jobs") || []).length;
  const unsubBatch = store.subscribe("batch", () => { if (data) renderSelect(); });
  const unsubscribe = store.subscribe("jobs", () => {
    const now = (store.get("jobs") || []).length;
    const finished = now < before;
    before = now;
    if (data) finished ? load() : renderRows();
  });
  renderTabs();
  load();
  return () => { stopped = true; clearTimeout(timer); clearTimeout(typing); unsubscribe(); unsubBatch(); };
}
