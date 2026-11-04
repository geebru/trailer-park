import { h, replace } from "./dom.js";
import { icon } from "./icons.js";
import { api } from "./api.js";
import { store } from "./store.js";
import { openJob } from "./dialogs.js";
import { toast } from "./toast.js";
import { poll } from "./poller.js";
import { hostOf, timeUntil } from "./format.js";
import { navigate } from "./router.js";
import { setDisabled } from "./tip.js";

const NAV = [
  { href: "/", route: "overview", icon: "house", label: "Overview" },
  { href: "/trailers", route: "trailers", icon: "film", label: "Trailers" },
  { href: "/activity", route: "activity", icon: "clock-rotate-left", label: "Activity" },
  { href: "/settings", route: "settings", icon: "gear", label: "Settings" },
];

const COLLAPSE_KEY = "tp.sidebar";
const readCollapsed = () => { try { return localStorage.getItem(COLLAPSE_KEY) === "collapsed"; } catch { return false; } };
const writeCollapsed = (v) => { try { localStorage.setItem(COLLAPSE_KEY, v ? "collapsed" : "open"); } catch { /* private mode */ } };

let sidebar, scrim, toggleButton, servicesEl, jobsEl, collapsedBadge;

export function isDesktop() { return window.matchMedia("(min-width: 64rem)").matches; }

export function openMenu() {
  sidebar.dataset.open = "true";
  scrim.hidden = false;
  document.body.classList.add("menu-open");
  sidebar.querySelector(".nav__item")?.focus();
}
export function closeMenu({ restoreFocus = false } = {}) {
  if (sidebar.dataset.open !== "true") return;
  sidebar.dataset.open = "false";
  scrim.hidden = true;
  document.body.classList.remove("menu-open");
  if (restoreFocus) document.querySelector(".menu-button")?.focus();
}

function setCollapsed(collapsed) {
  document.body.dataset.sidebar = collapsed ? "collapsed" : "open";
  toggleButton.setAttribute("aria-expanded", String(!collapsed));
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  toggleButton.setAttribute("aria-label", label);
  toggleButton.title = label;
  writeCollapsed(collapsed);
}

export function setActiveRoute(route) {
  for (const link of sidebar.querySelectorAll(".nav__item")) {
    if (link.dataset.route === route) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

/* ── Services panel ─────────────────────────────────────────────────── */

function statusWord(online) { return online === true ? "Online" : online === false ? "Offline" : "Checking"; }
function statusTone(online) { return online === true ? "success" : online === false ? "danger" : "neutral"; }

function renderServices(overview) {
  const connections = overview?.connections || [];
  const offline = connections.filter((c) => c.online === false).length;
  const unknown = connections.filter((c) => c.online == null).length;
  const overall = !connections.length ? ["neutral", "No services"]
    : offline ? ["danger", `${offline} offline`]
    : unknown ? ["neutral", "Checking…"]
    : ["success", "All online"];

  const groups = [["radarr", "Radarr"], ["sonarr", "Sonarr"]]
    .map(([type, label]) => ({ label, items: connections.filter((c) => c.type === type) }))
    .filter((g) => g.items.length);

  const watcher = overview?.watcher;
  const nextSync = !watcher ? "—" : !watcher.enabled ? "Off" : watcher.syncing ? "Now" : timeUntil(watcher.next_run_at) || "—";

  const rows = groups.map(({ label, items }) => {
    const down = items.filter((c) => c.online === false).length;
    const tipId = `tip-${label.toLowerCase()}`;
    return h("li", { class: "service" },
      h("button", { type: "button", class: "service__button", "aria-describedby": tipId },
        h("span", {}, label),
        h("span", { class: `service__count mono${down ? " tone-danger" : ""}` },
          down ? `${items.length - down} of ${items.length} online` : `${items.length} connected`)),
      h("div", { role: "tooltip", id: tipId, class: "service__tip" },
        h("span", { class: "service__tip-title" }, `${label} servers`),
        items.map((c) => h("span", { class: "service__tip-row" },
          h("span", { class: "service__tip-line" },
            h("span", { class: "service__tip-name" }, c.name),
            h("span", { class: `service__state tone-${statusTone(c.online)}` },
              h("span", { class: "dot" }), statusWord(c.online))),
          h("span", { class: "service__tip-host mono" }, hostOf(c.url))))));
  });

  replace(servicesEl,
    h("div", { class: "services__head" },
      h("span", { class: "services__title" }, "Services"),
      h("span", { class: `services__overall tone-${overall[0]}` }, h("span", { class: "dot" }), overall[1])),
    h("ul", { class: "services__list" }, rows),
    h("div", { class: "services__sync" },
      h("span", { class: "services__sync-label" }, icon("tower-broadcast"), "Next sync"),
      h("span", { class: "mono services__sync-value" }, nextSync)));

  const summary = `${connections.length} service${connections.length === 1 ? "" : "s"}: ${overall[1].toLowerCase()}. Next sync ${nextSync}.`;
  collapsedBadge.title = summary;
  collapsedBadge.setAttribute("aria-label", summary);
  collapsedBadge.classList.toggle("is-alert", offline > 0);
}

/* ── Running jobs panel ─────────────────────────────────────────────── */

function renderJobs() {
  const jobs = store.get("jobs") || [];
  const batch = store.get("batch");
  const batchRunning = batch && batch.status === "running";
  jobsEl.hidden = !jobs.length && !batchRunning;
  if (jobsEl.hidden) { replace(jobsEl); return; }

  const children = jobs.filter((j) => !j.batch_id);   // batch children are summarised by the batch row
  replace(jobsEl,
    h("div", { class: "jobs__title" }, h("span", { class: "dot dot--pulse" }), "Running"),
    batchRunning && h("div", { class: "job" },
      h("div", { class: "job__line" },
        h("span", { class: "job__name" }, `Batch · ${batch.scope}`),
        h("span", { class: "mono job__meta" }, `${batch.done} of ${batch.total}`)),
      progress(batch.total ? (batch.done / batch.total) * 100 : 0, `Batch ${batch.scope}`),
      setDisabled(h("button", { type: "button", class: "btn btn--tertiary btn--sm job__cancel", onclick: cancelBatch },
        batch.cancel_requested ? "Cancelling…" : "Cancel batch"), batch.cancel_requested && "Cancel already requested")),
    children.map((j) => h("button", { type: "button", class: "job job--link", "aria-label": `Show output for ${j.title}`, onclick: () => openJob(j) },
      h("div", { class: "job__line" },
        h("span", { class: "job__name" }, j.title),
        h("span", { class: "mono job__meta" }, j.status === "queued" ? "Queued" : j.progress != null ? `${Math.round(j.progress)}%` : "…")),
      j.progress != null && j.status === "running" ? progress(j.progress, j.title) : null)));
}

async function cancelBatch() {
  try { await api.post("/batches/current/cancel", {}); toast("Cancelling after the active downloads finish.", "info"); store.set("batch", (await api.get("/batches/current")).batch); }
  catch (e) { toast(e.message, "danger"); }
}

function progress(percent, label) {
  const bar = h("div", { class: "progress", role: "progressbar", "aria-label": label,
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(percent)) },
    h("span", { style: `width:${Math.max(0, Math.min(100, percent))}%` }));
  return bar;
}

/* ── Build + start ──────────────────────────────────────────────────── */

export function buildShell(root) {
  scrim = h("button", { type: "button", class: "scrim", hidden: true, "aria-label": "Close navigation", onclick: () => closeMenu({ restoreFocus: true }) });
  toggleButton = h("button", { type: "button", class: "btn btn--tertiary sidebar__toggle", onclick: () => setCollapsed(document.body.dataset.sidebar !== "collapsed") },
    icon("chevron-left", "icon sidebar__toggle-icon"));
  servicesEl = h("section", { class: "services", "aria-label": "Services" });
  jobsEl = h("section", { class: "jobs", "aria-label": "Running jobs", "aria-live": "polite", hidden: true });
  collapsedBadge = h("button", { type: "button", class: "services-badge", onclick: () => setCollapsed(false) }, icon("tower-broadcast", "icon"));

  sidebar = h("aside", { class: "sidebar", id: "sidebar", "data-open": "false" },
    h("a", { class: "brand", href: "/" },
      h("span", { class: "brand__mark" }, icon("trailer", "icon brand__icon")),
      h("span", { class: "brand__text" },
        h("span", { class: "brand__name" }, "Trailer Park"),
        h("span", { class: "brand__sub" }, "Trailer automation")),
      h("span", { class: "sr-only" }, ", overview")),
    toggleButton,
    h("nav", { class: "nav", "aria-label": "Primary" },
      NAV.map((n) => h("a", { class: "nav__item", href: n.href, "data-route": n.route, title: n.label },
        icon(n.icon, "icon nav__icon"), h("span", { class: "nav__text" }, n.label)))),
    jobsEl,
    servicesEl,
    collapsedBadge);

  root.append(sidebar, scrim);
  setCollapsed(readCollapsed());
  renderServices(store.get("overview"));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar.dataset.open === "true") closeMenu({ restoreFocus: true });
  });
  window.matchMedia("(min-width: 64rem)").addEventListener("change", () => closeMenu());
  store.subscribe("overview", renderServices);
  store.subscribe("jobs", renderJobs);
  store.subscribe("batch", renderJobs);
  setInterval(() => renderServices(store.get("overview")), 30000);
}

export function startPolling() {
  const overview = poll(async () => store.set("overview", await api.get("/overview")), () => 15000);
  const jobs = poll(async () => {
    const [j, b] = await Promise.all([api.get("/jobs?active=1"), api.get("/batches/current")]);
    store.set("jobs", j.jobs);
    store.set("batch", b.batch);
  }, () => ((store.get("jobs") || []).length || store.get("batch")?.status === "running" ? 1500 : 6000));
  return { overview, jobs };
}

export { navigate };
