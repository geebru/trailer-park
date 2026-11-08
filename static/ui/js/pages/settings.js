import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { toast } from "../toast.js";
import { timeAgo } from "../format.js";
import { createDialog } from "../dialog.js";
import { setDisabled } from "../tip.js";
import { pageHeading, notice } from "./common.js";

export const title = "Settings";

const SECTIONS = [
  { id: "connections", label: "Connections", icon: "link", blurb: "Connect any number of Radarr and Sonarr services." },
  { id: "naming", label: "Naming", icon: "folder", blurb: "Choose where trailers live and how downloaded files are named." },
  { id: "behavior", label: "Behavior", icon: "sliders", blurb: "How trailers are matched and what happens when TMDB has nothing suitable." },
  { id: "tmdb", label: "TMDB", icon: "key", blurb: "Credentials used to find trailers for each title." },
  { id: "ytdlp", label: "Downloads", icon: "terminal", blurb: "Video quality, file type, and the yt-dlp downloader." },
  { id: "automation", label: "Automation", icon: "arrows-rotate", blurb: "How often connected services sync and how long activity is kept." },
  { id: "notifications", label: "Notifications", icon: "bell", blurb: "Send download results to a Discord webhook." },
];
const SECRET_KEYS = ["tmdb_api_key", "discord_webhook_url"];
const INTERVALS = [[0, "Off"], [5, "5 minutes"], [10, "10 minutes"], [15, "15 minutes"], [30, "30 minutes"], [60, "1 hour"], [360, "6 hours"], [1440, "24 hours"]];
const RETENTION = [[60, "60 days"], [90, "90 days"], [180, "180 days"], [365, "1 year"], [0, "Forever"]];
const SEASON_FALLBACK = [["first", "First season (spoiler-free)"], ["latest", "Latest season"], ["off", "Off"]];
const QUALITY = [[480, "480p"], [720, "720p"], [1080, "1080p"], [2160, "4K"]];

/* ── Small form pieces ─────────────────────────────────────────────── */
let uid = 0;
function field(label, hint, control, id, badge) {
  // The hint sits beside the label, not inside it, so the field's name is just its title; the hint is its description.
  const title = h("label", { class: "label", for: id }, label);
  const note = hint ? h("span", { class: "label__hint", id: `${id}-hint` }, hint) : null;
  if (note) control.setAttribute("aria-describedby", note.id);
  return h("div", { class: "field" }, note || badge ? h("div", { class: "field__head" }, title, note, badge) : title, control);
}
function textInput(value, onInput, extra = {}) {
  const id = `f${++uid}`;
  const el = h("input", { class: "input input--full", id, value: value ?? "", autocomplete: "off", spellcheck: "false", oninput: (e) => onInput(e.target.value), ...extra });
  return { el, id };
}
function selectInput(options, value, onChange) {
  const id = `f${++uid}`;
  const list = options.some(([v]) => String(v) === String(value)) ? options : [...options, [value, String(value)]];
  const el = h("select", { class: "select select--full", id, onchange: (e) => onChange(e.target.value) },
    list.map(([v, l]) => h("option", { value: v, selected: String(v) === String(value) }, l)));
  return { el, id };
}
function toggle(label, description, on, onChange) {
  let state = on;
  const knob = h("span", { class: "switch__knob" });
  const el = h("button", { type: "button", role: "switch", "aria-checked": String(state), class: "switch",
    onclick: () => { state = !state; el.setAttribute("aria-checked", String(state)); onChange(state); } },
    h("span", { class: "switch__text" }, h("span", { class: "switch__label" }, label), h("span", { class: "switch__desc" }, description)),
    h("span", { class: "switch__track" }, knob));
  return el;
}
const btn = (cls, label, onclick, ic, extra = {}) => h("button", { type: "button", class: `btn ${cls}`, onclick, ...extra }, ic ? icon(ic) : null, label);
const card = (...kids) => h("div", { class: "card" }, kids);

/* ── Page ──────────────────────────────────────────────────────────── */

export function mount(container, { query, navigate }) {
  const wanted = query.get("section") === "scoring" ? "behavior" : query.get("section"); // "scoring" was renamed
  let section = SECTIONS.some((s) => s.id === wanted) ? wanted : "connections";
  let server = null;                 // last settings from the API
  let draft = {};                    // editable copy of public settings
  let secrets = {};                  // {tmdb_api_key, discord_webhook_url, clear_*}
  let ytdlp = null;
  let stopped = false;
  let nextTimer = null;

  const navEl = h("nav", { class: "settings-nav", "aria-label": "Settings sections" });
  const headEl = h("div", { class: "panel__head settings__head" });
  const bodyEl = h("div", { class: "settings__body" });
  const footEl = h("div", { class: "settings__foot" });
  const bannerEl = h("div", { class: "banners" });
  container.append(h("div", { class: "page" }, pageHeading("Settings"), bannerEl,
    h("div", { class: "settings" }, navEl,
      h("section", { class: "panel settings__panel", "aria-labelledby": "settings-title" }, headEl, bodyEl, footEl))));

  const dirtyKeys = () => Object.keys(draft).filter((k) => String(draft[k]) !== String(server.settings[k]));
  const dirty = () => dirtyKeys().length > 0 || SECRET_KEYS.some((k) => secrets[k] || secrets[`clear_${k}`]);
  function setDraft(key, value) { draft[key] = value; paintFoot(); }
  function setSecret(key, value) { secrets[key] = value; if (value) secrets[`clear_${key}`] = false; paintFoot(); }

  /* nav + frame */
  function paintNav() {
    replace(navEl, SECTIONS.map((s) => h("a", { class: "settings-nav__item", href: `/settings?section=${s.id}`, "aria-current": s.id === section ? "page" : null,
      onclick: (e) => { e.preventDefault(); section = s.id; history.replaceState({}, "", `/settings?section=${s.id}`); paintSection(); container.querySelector(`[aria-current="page"]`)?.focus(); } },
      icon(s.icon), s.label)));
    navEl.querySelector('[aria-current="page"]')?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }
  let saveMsg = "";
  function paintFoot() {
    if (section === "connections") { replace(footEl); footEl.hidden = true; return; }
    footEl.hidden = false;
    const d = dirty();
    replace(footEl,
      h("span", { class: "settings__saved", role: "status" }, saveMsg ? [icon("check"), saveMsg] : null),
      h("div", { class: "dialog__actions" },
        setDisabled(btn("btn--tertiary", "Discard", discard), !d && "No changes to discard"),
        setDisabled(btn("btn--primary", "Save changes", save), !d && "No changes to save")));
  }
  function discard() { draft = { ...server.settings }; secrets = {}; saveMsg = ""; paintSection(); }
  async function save() {
    const payload = {};
    for (const k of dirtyKeys()) payload[k] = draft[k];
    for (const k of SECRET_KEYS) {
      if (secrets[k]) payload[k] = secrets[k];
      if (secrets[`clear_${k}`]) payload[`clear_${k}`] = true;
    }
    try {
      server = await api.put("/settings", payload);
      draft = { ...server.settings }; secrets = {}; replace(bannerEl);
      saveMsg = "Changes saved";
      paintSection();
      setTimeout(() => { saveMsg = ""; if (!stopped) paintFoot(); }, 2500);
    } catch (e) { replace(bannerEl, notice("danger", e.message)); window.scrollTo(0, 0); }
  }

  function paintSection() {
    const def = SECTIONS.find((s) => s.id === section);
    paintNav();
    replace(headEl, h("div", {}, h("h2", { id: "settings-title", class: "panel__title" }, def.label), h("p", { class: "settings__blurb" }, def.blurb)));
    clearInterval(nextTimer);
    replace(bodyEl, ({ connections, naming, behavior, tmdb, ytdlp: downloads, automation, notifications }[section])());
    paintFoot();
  }

  /* ── Connections ─────────────────────────────────────────────────── */
  function connections() {
    const online = new Map((store.get("overview")?.connections || []).map((c) => [c.id, c]));
    const list = h("div", { class: "stack" });
    const render = () => replace(list, server.connections.map((c) => connectionCard(c, online.get(c.id), render)),
      server.connections.length ? null : h("p", { class: "muted" }, "No connections yet."));
    render();
    const addHolder = h("div", {});
    const close = () => { replace(addHolder); add.hidden = false; };
    const add = btn("btn--primary", "Add connection", () => { add.hidden = true; addHolder.replaceChildren(connectionForm(null, () => { close(); render(); }, close)); addHolder.querySelector("input")?.focus(); }, "plus");
    return h("div", { class: "stack" },
      h("div", { class: "split" }, h("div", {}, h("div", { class: "card__title" }, "Connected services"), h("div", { class: "hint" }, "Connections are merged into the Movies or Shows view based on their type.")), add),
      addHolder, list);
  }
  function connectionCard(c, live, rerender) {
    const holder = h("div", {});
    const status = !live ? null : live.online ? h("span", { class: "status status--success" }, "Connected") : h("span", { class: "status status--danger", title: live.error }, "Unreachable");
    const el = card(
      h("div", { class: "split" },
        h("div", { class: "row-gap" }, h("div", { class: "file__icon" }, icon(c.type === "radarr" ? "film" : "tv")),
          h("div", {}, h("div", { class: "card__title" }, c.name), h("div", { class: "hint mono" }, c.url))),
        h("div", { class: "row-gap" }, status,
          btn("btn--tertiary btn--sm", "Edit", () => { holder.replaceChildren(connectionForm(c, () => { replace(holder); rerender(); }, () => replace(holder))); }, "pen"),
          btn("btn--tertiary btn--sm btn--danger", "Remove", () => removeConnection(c, rerender), "trash"))),
      live && !live.online && live.error ? h("p", { class: "hint tone-danger" }, live.error) : null, holder);
    return el;
  }
  function connectionForm(existing, done, cancel) {
    const f = { name: existing?.name || "", type: existing?.type || "radarr", url: existing?.url || "", api_key: "" };
    const err = h("div", {});
    const typeSel = selectInput([["radarr", "Radarr"], ["sonarr", "Sonarr"]], f.type, (v) => { f.type = v; });
    typeSel.el.disabled = !!existing;
    const name = textInput(f.name, (v) => { f.name = v; });
    const sameServer = (a, b) => { try { return new URL(a).origin === new URL(b).origin; } catch { return false; } };
    const keyHint = () => !existing ? "API key"
      : sameServer(f.url, existing.url) ? "Leave blank to keep the saved key" : "Enter the API key for this server";
    const url = textInput(f.url, (v) => { f.url = v; key.el.placeholder = keyHint(); }, { placeholder: "http://radarr:7878" });
    const key = textInput("", (v) => { f.api_key = v; }, { type: "password", placeholder: keyHint() });
    const go = btn("btn--primary", "Test and save", async () => {
      setDisabled(go, "Testing the connection…"); replace(err);
      try {
        const body = { ...f, ...(existing ? { id: existing.id } : {}) };
        const r = await api.post("/connections/test", body);
        toast(r.message, "success");
        server.connections = (await api.get("/settings")).connections;
        store.set("overview", await api.get("/overview"));
        done();
      } catch (e) { replace(err, notice("danger", e.message)); setDisabled(go, null); }
    });
    return h("form", { class: "subform", onsubmit: (e) => { e.preventDefault(); go.click(); } },
      h("div", { class: "grid2" }, field("Name", null, name.el, name.id), field("Type", existing ? "Can't be changed" : null, typeSel.el, typeSel.id),
        field("Base URL", null, url.el, url.id), field("API key", null, key.el, key.id)),
      err, h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", cancel), go));
  }
  function removeConnection(c, rerender) {
    const d = createDialog({ title: `Remove ${c.name}?`, size: "sm", role: "alertdialog", tone: "danger" });
    const err = h("div", {});
    d.body.append(h("p", { class: "hint hint--lead" }, "Trailer Park will stop watching this connection. Your trailer files and the Arr itself are not touched."), err);
    d.footer.append(h("span", {}), h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", d.close),
      btn("btn--danger-solid", "Remove", async () => {
        try {
          const keep = server.connections.filter((x) => x.id !== c.id).map(({ id, name, type, url }) => ({ id, name, type, url }));
          server = await api.put("/settings", { connections: keep });
          draft = { ...server.settings, ...Object.fromEntries(dirtyKeysFrom(draft)) };
          store.set("overview", await api.get("/overview"));
          d.close(); rerender(); toast(`Removed ${c.name}.`, "info");
        } catch (e) { replace(err, notice("danger", e.message)); }
      })));
  }
  const dirtyKeysFrom = (d) => Object.entries(d).filter(([k, v]) => String(v) !== String(server.settings[k]));

  /* ── Naming ──────────────────────────────────────────────────────── */
  function naming() {
    const preview = h("div", { class: "mono preview" });
    const note = h("div", {});
    let t = null;
    async function refresh() {
      try {
        const r = await api.post("/settings/naming-preview", { template: draft.filename_template, folder: draft.trailer_folder, container: draft.container });
        replace(preview, `<movie folder>/${r.path}`);
        replace(note);
      } catch (e) { replace(preview, "—"); replace(note, notice("danger", e.message)); }
    }
    const queue = () => { clearTimeout(t); t = setTimeout(refresh, 250); };
    const root = textInput(draft.media_root, (v) => { setDraft("media_root", v); queue(); });
    const folder = textInput(draft.trailer_folder, (v) => { setDraft("trailer_folder", v); queue(); });
    const tpl = textInput(draft.filename_template, (v) => { setDraft("filename_template", v); queue(); });
    refresh();
    return h("div", { class: "stack" },
      field("Media folder", "Where your Radarr/Sonarr libraries live inside this container", root.el, root.id),
      h("div", { class: "grid2" }, field("Trailer folder", "Leave blank to save beside the media file", folder.el, folder.id), field("File name template", null, tpl.el, tpl.id)),
      card(h("div", { class: "card__title" }, icon("folder", "icon tone-accent"), "Output preview"), preview, note,
        h("p", { class: "hint" }, "Files that don't match this template get a ", h("span", { class: "tone-warning" }, "Name mismatch"), " tag. Titles with more than one trailer get a ", h("span", { class: "tone-info" }, "Multiple found"), " tag; having several is allowed and isn't an error.")),
      group("Available variables", null, h("div", { class: "chips" }, ["{title}", "{year}"].map((t2) => h("span", { class: "chip mono" }, t2)))));
  }

  /* ── Behavior ────────────────────────────────────────────────────── */
  function termEditor(key, label, tone, caption) {
    const wrap = h("div", { class: "terms" });
    const terms = () => String(draft[key] || "").split(",").map((s) => s.trim()).filter(Boolean);
    const set = (list) => { setDraft(key, list.join(",")); render(); };
    const input = h("input", { class: "terms__input", "aria-label": `Add ${label.toLowerCase()} keyword`, placeholder: "+ Add keyword", autocomplete: "off",
      onkeydown: (e) => {
        if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
        else if (e.key === "Backspace" && !input.value && terms().length) set(terms().slice(0, -1));
      }, onblur: () => add() });
    function add() { const v = input.value.trim().replace(/,/g, " "); if (v && !terms().some((x) => x.toLowerCase() === v.toLowerCase())) set([...terms(), v]); else input.value = ""; }
    function render() {
      replace(wrap, terms().map((w, i) => h("span", { class: `chip chip--${tone}` }, w,
        h("button", { type: "button", class: "chip__x", "aria-label": `Remove keyword ${w}`, onclick: () => set(terms().filter((_, j) => j !== i)) }, icon("xmark")))), input);
      if (document.activeElement === document.body) input.focus();
    }
    render();
    return h("div", {}, h("div", { class: "label" }, label), h("div", { class: `hint tone-${tone}` }, caption), wrap);
  }
  const group = (heading, blurb, ...kids) => h("section", { class: "group" },
    h("div", {}, h("h3", { class: "group__title" }, heading), blurb ? h("p", { class: "hint" }, blurb) : null), ...kids);
  function seasonFallback() {
    const sel = selectInput(SEASON_FALLBACK, draft.season_fallback, (v) => setDraft("season_fallback", v));
    // The one-line hint stays visible (and describes the select); the detail folds away.
    const more = h("details", { class: "disclosure hint" },
      h("summary", {}, "How the fallback works"),
      h("div", { class: "disclosure__body" },
        h("p", {}, h("strong", {}, "First season"), " tries season 1, then season 2. ",
          h("strong", {}, "Latest season"), " tries the newest season, the one before it, then season 1. At most three lookups; specials are skipped."),
        h("p", {}, "Show-level trailers that mention a later season (“Season 8”, “Final Season”) are ranked last, but still used if nothing else exists."),
        h("p", {}, "The keywords ", h("span", { class: "mono" }, "season 1"), " and ", h("span", { class: "mono" }, "season 01"),
          " are positive keywords by default and add score. Existing installs keep their saved keywords.")));
    const el = field("TV season fallback", "Used only when a show has no show-level trailer on TMDB.", sel.el, sel.id);
    el.append(more);
    return h("div", { class: "narrow" }, el);
  }
  function youtubeSearch() {
    const sel = selectInput([["off", "Off"], ["on", "On"]], draft.youtube_search, (v) => setDraft("youtube_search", v));
    return h("div", { class: "narrow" },
      field("YouTube search fallback", "Search YouTube directly. Results are scored with the same keywords.", sel.el, sel.id));
  }
  function behavior() {
    return h("div", { class: "stack stack--loose" },
      group("Keywords", "Trailer titles are scored against these words to pick the best match.",
        h("div", { class: "grid2" }, termEditor("preferred_terms", "Positive keywords", "success", "Increase score"), termEditor("excluded_terms", "Negative keywords", "danger", "Reduce score"))),
      group("Fallbacks", "What to try when TMDB has no suitable trailer for a title.",
        seasonFallback(), youtubeSearch()));
  }

  /* ── Secrets (TMDB, Discord) ─────────────────────────────────────── */
  function secretField(key, label, hint, service, testLabel) {
    const configured = server.configured[service];
    const input = textInput("", (v) => setSecret(key, v), { type: "password", placeholder: configured ? "Configured. Leave blank to keep it." : "Not set" });
    const result = h("div", {});
    const test = btn("btn--secondary", testLabel, async () => {
      setDisabled(test, "Testing…"); replace(result);
      try {
        const body = secrets[key] ? { [key]: secrets[key] } : {};
        const r = await api.post(`/settings/test/${service}`, body);
        server.configured = r.configured; secrets[key] = "";
        replace(result, notice("info", r.message || "Works."));
        paintSection();
      } catch (e) { replace(result, notice("danger", e.message)); setDisabled(test, null); }
    }, service === "discord" ? "play" : "check");
    return h("div", { class: "stack" },
      h("div", { class: "field" },
        field(label, hint, input.el, input.id, configured ? h("span", { class: "status status--success" }, "Configured") : h("span", { class: "status" }, "Not set")),
        h("div", { class: "row-gap" },
          test,
          configured ? btn("btn--tertiary btn--danger", "Remove", () => { secrets[`clear_${key}`] = true; secrets[key] = ""; paintFoot(); toast("Press Save changes to remove it.", "info"); }, "trash") : null)),
      result);
  }
  const tmdb = () => h("div", { class: "stack narrow" },
    secretField("tmdb_api_key", "TMDB API key", "Required to find trailers", "tmdb", "Test key"),
    h("p", { class: "hint" }, "A free key from themoviedb.org. It's used to look up each title and its official trailers before anything is downloaded."));

  /* ── Downloads / yt-dlp ──────────────────────────────────────────── */
  function downloads() {
    const statusEl = h("div", {});
    const paintYt = () => {
      if (!ytdlp) { replace(statusEl, h("p", { class: "muted" }, "Loading…")); return; }
      const stateChip = ytdlp.up_to_date ? h("span", { class: "status status--success" }, "Up to date") : ytdlp.latest ? h("span", { class: "status status--warning" }, `${ytdlp.latest} available`) : null;
      const busy = (b, fn) => async () => { setDisabled(b, "Working…"); try { ytdlp = await fn(); } catch (e) { toast(e.message, "danger", 8000); } paintYt(); };
      const check = btn("btn--secondary", "Check for updates", () => busy(check, () => api.post("/yt-dlp/check", {}))());
      const upd = btn("btn--primary", "Update", () => busy(upd, async () => { const r = await api.post("/yt-dlp/update", {}); toast("yt-dlp updated.", "success"); return r; })(), "download");
      replace(statusEl, card(h("div", { class: "split" },
        h("div", { class: "row-gap" }, h("div", { class: "file__icon" }, icon("terminal")),
          h("div", {}, h("div", { class: "row-gap" }, h("span", { class: "card__title" }, "yt-dlp"), stateChip),
            h("div", { class: "hint mono" }, `version ${ytdlp.active || "unknown"}${ytdlp.using_override ? " (updated copy)" : ""}`),
            ytdlp.last_checked ? h("div", { class: "hint" }, `Checked ${timeAgo(ytdlp.last_checked)} ago`) : null)),
        h("div", { class: "row-gap" }, check, upd)),
        ytdlp.last_error ? h("p", { class: "hint tone-warning" }, `Last check failed: ${ytdlp.last_error}`) : null));
    };
    if (!ytdlp) api.get("/yt-dlp").then((r) => { ytdlp = r; if (!stopped && section === "ytdlp") paintYt(); }).catch(() => {});
    paintYt();
    const q = selectInput(QUALITY, draft.video_quality, (v) => setDraft("video_quality", v));
    const c = selectInput([["mkv", "mkv"], ["mp4", "mp4"]], draft.container, (v) => setDraft("container", v));
    const n = selectInput([1, 2, 3, 4].map((x) => [x, String(x)]), draft.max_concurrent_downloads, (v) => setDraft("max_concurrent_downloads", v));
    return h("div", { class: "stack" }, statusEl,
      h("div", { class: "grid3" }, field("Resolution", "Maximum", q.el, q.id), field("Output container", null, c.el, c.id), field("Concurrent downloads", null, n.el, n.id)),
      h("p", { class: "hint" }, "mp4 prefers H.264 video so files play on more devices. Changing these only affects new downloads."));
  }

  /* ── Automation ──────────────────────────────────────────────────── */
  function automation() {
    const iv = selectInput(INTERVALS, draft.watch_interval_minutes, (v) => setDraft("watch_interval_minutes", v));
    const rt = selectInput(RETENTION, draft.activity_retention_days, (v) => setDraft("activity_retention_days", v));
    const nextEl = h("div", { class: "mono card__big" });
    const syncBtn = btn("btn--secondary", "Sync now", async () => {
      setDisabled(syncBtn, "Starting a sync…");
      try { await api.post("/watcher/run", {}); toast("Sync started.", "info"); store.set("overview", await api.get("/overview")); }
      catch (e) { toast(e.message, "danger"); }
      paintNext();
    }, "arrows-rotate");
    function paintNext() {
      const w = store.get("overview")?.watcher;
      replace(nextEl, !w ? "—" : !w.enabled ? "Off" : w.syncing ? "Syncing…" : nextIn(w.next_run_at));
      setDisabled(syncBtn, w?.syncing && "A sync is already running");
    }
    paintNext();
    nextTimer = setInterval(paintNext, 1000);
    return h("div", { class: "stack" },
      h("div", { class: "grid2" }, field("Sync interval", "How often to check every connection", iv.el, iv.id), field("Activity retention", "Older entries are removed automatically", rt.el, rt.id)),
      card(h("div", { class: "split" }, h("div", {}, h("div", { class: "label" }, "Next sync"), nextEl), syncBtn)),
      h("p", { class: "hint" }, "A sync is a lightweight check for added or changed titles. Trailer searches and downloads only run when something relevant changed."));
  }
  function nextIn(iso) {
    const s = Math.round((Date.parse(iso || "") - Date.now()) / 1000);
    if (Number.isNaN(s)) return "—";
    if (s <= 0) return "Due";
    const m = Math.floor(s / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
  }

  /* ── Notifications ───────────────────────────────────────────────── */
  const notifications = () => h("div", { class: "stack" },
    secretField("discord_webhook_url", "Discord webhook URL", "Optional. Must be a discord.com webhook.", "discord", "Send test"),
    group("Events to send", null,
      h("div", { class: "stack stack--tight" },
        toggle("Trailer downloaded", "Send the title, source and file name after a successful download.", draft.notify_success === "on", (v) => setDraft("notify_success", v ? "on" : "off")),
        toggle("Grab failed", "Notify when a grab fails, such as no suitable match or a yt-dlp error. The message includes the reason.", draft.notify_failure === "on", (v) => setDraft("notify_failure", v ? "on" : "off")))),
    h("p", { class: "hint" }, "Batches and Sync now send one summary instead of one message per title."));

  /* ── Boot ────────────────────────────────────────────────────────── */
  api.get("/settings").then((s) => { if (stopped) return; server = s; draft = { ...s.settings }; paintSection(); })
    .catch((e) => replace(bannerEl, notice("danger", e.message)));
  paintNav();
  return () => { stopped = true; clearInterval(nextTimer); };
}
