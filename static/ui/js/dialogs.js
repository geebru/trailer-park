import { h, replace } from "./dom.js";
import { icon } from "./icons.js";
import { api, ApiError } from "./api.js";
import { createDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { number } from "./format.js";
import { store } from "./store.js";
import { setDisabled } from "./tip.js";

const btn = (cls, label, onclick, ic, extra = {}) =>
  h("button", { type: "button", class: `btn ${cls}`, onclick, ...extra }, ic ? icon(ic) : null, label);
const inlineError = (el, message) => replace(el, message ? h("div", { class: "notice notice--danger", role: "alert" }, icon("triangle-exclamation", "icon notice__icon"), h("div", { class: "notice__body" }, message)) : null);

export function bytes(n) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

/* ── Job log ───────────────────────────────────────────────────────── */

const TERMINAL = ["succeeded", "failed", "cancelled"];

/** Live log for a job. `onDone` runs once when the job reaches a final state. */
export function openJob(jobSummary, { manual = false, onDone } = {}) {
  let after = 0;
  let timer = null;
  let closed = false;
  let finished = false;
  let cancelling = false;
  const logEl = h("pre", { class: "joblog", role: "log", "aria-label": "Download output", tabindex: "0" });
  const bar = h("span", {});
  const barWrap = h("div", { class: "progress joblog__bar", role: "progressbar", "aria-label": "Download progress", "aria-valuemin": "0", "aria-valuemax": "100" }, bar);
  const resultEl = h("div", { class: "joblog__result" });
  const dlg = createDialog({ title: manual ? "Downloading trailer" : "Finding best trailer", subtitle: jobSummary.title, size: "lg", onClose: () => { closed = true; clearTimeout(timer); } });
  const pct = h("span", { class: "mono joblog__pct" });
  dlg.body.append(resultEl, logEl, h("div", { class: "joblog__progress" }, barWrap, pct));
  const status = h("span", { class: "muted dialog__status" }, icon("terminal"), "Live output");
  const actions = h("div", { class: "dialog__actions" });
  dlg.footer.append(status, actions);

  function paintActions() {
    replace(actions, finished
      ? btn("btn--secondary", "Close", dlg.close)
      : [btn("btn--secondary", "Run in background", dlg.close),
         setDisabled(btn("btn--tertiary btn--danger", cancelling ? "Cancelling…" : "Cancel", cancel), cancelling && "Cancel already requested")]);
  }
  async function cancel() {
    cancelling = true; paintActions();
    try { await api.post(`/jobs/${jobSummary.id}/cancel`, {}); } catch (e) { toast(e.message, "danger"); cancelling = false; paintActions(); }
  }
  function setProgress(p) {
    const known = typeof p === "number";
    barWrap.hidden = pct.hidden = !known;
    if (known) { bar.style.width = `${p}%`; barWrap.setAttribute("aria-valuenow", String(Math.round(p))); pct.textContent = `${p.toFixed(1)}%`; }
  }
  function appendLines(lines) {
    if (!lines.length) return;
    const near = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
    for (const l of lines) {
      logEl.append(h("span", { class: `joblog__line joblog__line--${l.stream}` }, l.text, "\n"));
    }
    if (near) logEl.scrollTop = logEl.scrollHeight;
  }
  function conclude(job) {
    finished = true;
    const r = job.result || {};
    const infoOutcome = ["no_trailer", "no_tmdb_match"].includes(r.outcome);
    let tone, heading, ic, text;
    if (job.status === "succeeded") {
      tone = "success"; ic = "circle-check"; heading = r.outcome === "exists" ? "Trailer already exists" : "Trailer downloaded";
      text = r.saved_to ? h("span", { class: "mono" }, r.saved_to) : null;
    } else if (job.status === "cancelled") {
      tone = "neutral"; ic = "circle-xmark"; heading = "Download cancelled"; text = "Partial files were removed. You can start this again at any time.";
    } else if (infoOutcome) {
      tone = "info"; ic = "circle-info"; heading = "No suitable match"; text = r.message || "No file was downloaded.";
    } else {
      tone = "danger"; ic = "circle-xmark"; heading = "Download failed"; text = r.message || "See the output below.";
    }
    dlg.setHeading(heading, jobSummary.title, icon(ic, `icon tone-${tone}`));
    replace(resultEl, h("div", { class: `result result--${tone}`, role: tone === "danger" ? "alert" : "status" }, h("div", { class: "result__title" }, heading), text ? h("div", { class: "result__text" }, text) : null));
    replace(status, icon("terminal"), "Output");
    setProgress(job.status === "succeeded" ? 100 : null);
    paintActions();
    onDone?.(job);
  }
  async function tick() {
    if (closed) return;
    try {
      const job = await api.get(`/jobs/${jobSummary.id}?after=${after}`);
      if (job.truncated) appendLines([{ stream: "app", text: "… earlier output not shown …" }]);
      appendLines(job.lines);
      if (job.lines.length) after = job.lines[job.lines.length - 1].seq;
      if (job.status === "queued") replace(status, icon("terminal"), "Waiting to start");
      setProgress(typeof job.progress === "number" ? job.progress : null);
      if (TERMINAL.includes(job.status)) { conclude(job); return; }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { finished = true; replace(resultEl, h("div", { class: "result result--neutral" }, "This job has expired. Check Activity for the outcome.")); paintActions(); return; }
    }
    timer = setTimeout(tick, 1000);
  }
  dlg.setHeading(manual ? "Downloading trailer" : "Finding best trailer", jobSummary.title, h("span", { class: "dot dot--pulse" }));
  setProgress(null); paintActions(); tick();
  return dlg;
}

/** POST that starts a job, then opens its log. A 409 for an already-running item opens that job instead. */
export async function startJob(path, body, opts = {}) {
  try {
    const { job } = await api.post(path, body);
    store.set("jobs", [...(store.get("jobs") || []).filter((j) => j.id !== job.id), job]);
    return openJob(job, opts);
  } catch (e) {
    if (e.code === "job_active" && e.data?.error?.job) return openJob(e.data.error.job, opts);
    toast(e.message, "danger", 8000);
    return null;
  }
}

/* ── Manual grab ───────────────────────────────────────────────────── */

const NEEDS_VIDEO = "Enter a YouTube link or video ID first";

export function openManual(item, { onDone } = {}) {
  const hasTrailer = item.presence === "present";
  const err = h("div", {});
  const input = h("input", { class: "input input--mono", autofocus: true, autocomplete: "off", spellcheck: "false", id: "manual-video",
    placeholder: "https://youtu.be/dQw4w9WgXcQ or dQw4w9WgXcQ", oninput: () => { setDisabled(go, !input.value.trim() && NEEDS_VIDEO); } });
  const dlg = createDialog({ title: "Manual trailer grab", subtitle: item.title, size: "sm" });
  const go = setDisabled(btn("btn--primary", hasTrailer ? "Replace trailer" : "Download trailer", submit, "download"), NEEDS_VIDEO);
  dlg.body.append(
    h("label", { class: "label", for: "manual-video" }, "YouTube link or video ID"), input,
    h("p", { class: "hint" }, "Paste a full YouTube URL or the 11-character video ID. Either format works."),
    hasTrailer ? h("p", { class: "flag tone-warning flag--block" }, icon("triangle-exclamation"), "This will replace the existing trailer.") : null, err);
  dlg.footer.append(h("span", {}), h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", dlg.close), go));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && input.value.trim()) submit(); });
  input.focus();
  async function submit() {
    setDisabled(go, "Starting the download…"); inlineError(err);
    try {
      const { job } = await api.post(`/items/${item.connection_id}/${item.id}/force`, { video: input.value.trim() });
      store.set("jobs", [...(store.get("jobs") || []).filter((j) => j.id !== job.id), job]);
      dlg.close(); openJob(job, { manual: true, onDone });
    } catch (e) {
      if (e.code === "job_active" && e.data?.error?.job) { dlg.close(); openJob(e.data.error.job, { onDone }); return; }
      inlineError(err, e.message); setDisabled(go, null);
    }
  }
}

/* ── Files ─────────────────────────────────────────────────────────── */

export function openFiles(item, { onChange } = {}) {
  const dlg = createDialog({ title: "Trailer files", subtitle: item.title, size: "xl" });
  const err = h("div", { class: "files__error" });
  const list = h("ul", { class: "files" });
  const chips = h("span", { class: "dialog__chips" });
  dlg.body.append(err, list);
  dlg.footer.append(h("span", {}), h("div", { class: "dialog__actions" }, btn("btn--secondary", "Done", dlg.close)));
  replace(list, h("li", { class: "files__loading muted" }, "Loading…"));
  let changed = false;

  function render(detail) {
    const files = detail.files || [];
    dlg.setHeading("Trailer files", `${detail.title} · ${files.length} ${files.length === 1 ? "file" : "files"} found`);
    replace(chips, detail.name_differs ? h("span", { class: "status status--warning" }, "Name mismatch") : null,
      files.length > 1 ? h("span", { class: "status status--info" }, "Multiple found") : null);
    dlg.el.querySelector(".dialog__titlerow").append(chips);
    replace(list, files.length ? files.map((f) => h("li", { class: "file" },
      h("div", { class: "file__icon" }, icon("file-video")),
      h("div", { class: "file__main" },
        h("div", { class: "file__name mono" }, f.path),
        h("div", { class: "file__meta" }, h("span", { class: "mono muted" }, bytes(f.size)),
          h("span", { class: `status ${f.metadata ? "status--success" : ""}` }, f.metadata ? "Downloaded by Trailer Park" : "Found on disk"),
          f.matches ? null : h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), "Name mismatch"))),
      h("div", { class: "file__actions" },
        files.length > 1 ? btn("btn--tertiary btn--sm", "Keep only this", () => run("keep", f.path), null) : null,
        f.matches ? null : btn("btn--tertiary btn--sm", "Rename", () => run("rename", f.path), null),
        btn("btn--tertiary btn--sm btn--danger", "Delete", () => confirmDelete(f.path), null))))
      : h("li", { class: "files__loading muted" }, "No trailer files remain."));
  }
  async function run(action, path) {
    inlineError(err);
    try { render(await api.post(`/items/${item.connection_id}/${item.id}/files/${action}`, { path })); changed = true; onChange?.(); }
    catch (e) { inlineError(err, e.message); }
  }
  function confirmDelete(path) {
    const c = createDialog({ title: "Delete this file?", size: "sm", role: "alertdialog", tone: "danger" });
    c.body.append(h("p", { class: "hint" }, "This can't be undone."), h("p", { class: "mono pathbox" }, path));
    c.footer.append(h("span", {}), h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", c.close),
      btn("btn--danger-solid", "Delete", async () => { c.close(); await run("delete", path); })));
  }
  api.get(`/items/${item.connection_id}/${item.id}`).then(render).catch((e) => { replace(list); inlineError(err, e.message); });
}

/* ── Bulk rename ───────────────────────────────────────────────────── */

export function openRename(scope, { onChange } = {}) {
  const dlg = createDialog({ title: "Rename mismatched files", subtitle: "Apply the current naming template to single-file titles.", size: "lg" });
  const err = h("div", {});
  const list = h("div", { class: "rename-list" }, h("p", { class: "muted" }, "Checking…"));
  const count = h("span", { class: "muted" });
  const go = setDisabled(btn("btn--primary", "Rename", apply), "Checking the files first…");
  dlg.body.append(err, list, h("p", { class: "hint" }, "Every destination is checked before renaming. A rename that would overwrite another file is skipped and nothing is changed."));
  dlg.footer.append(count, h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", dlg.close), go));
  const body = { ...scope };
  let ready = [];

  api.post("/items/rename-all", { ...body, dry_run: true }).then((r) => {
    ready = r.ready;
    const item = (e, blocked) => h("div", { class: "rename-item" },
      h("div", { class: "rename-item__head" },
        h("div", { class: "rename-item__text" }, h("div", { class: "rename-item__title" }, e.title), e.from ? h("div", { class: "mono rename-item__file" }, `${e.from} → ${e.to}`) : null),
        h("span", { class: `status status--${blocked ? "danger" : "success"}` }, blocked ? "Blocked" : "Ready")),
      blocked ? h("div", { class: "rename-item__why" }, icon("triangle-exclamation"), e.reason) : null);
    replace(list, [...r.ready.map((e) => item(e, false)), ...r.blocked.map((e) => item(e, true))]);
    if (!r.ready.length && !r.blocked.length) replace(list, h("p", { class: "muted" }, "Nothing to rename."));
    count.textContent = `${number(r.ready.length)} of ${number(r.ready.length + r.blocked.length)} ready`;
    go.textContent = `Rename ${number(r.ready.length)}`; setDisabled(go, !r.ready.length && "No files can be renamed");
  }).catch((e) => { replace(list); inlineError(err, e.message); setDisabled(go, "The files could not be checked"); });

  async function apply() {
    setDisabled(go, "Renaming…");
    try {
      const r = await api.post("/items/rename-all", body);
      toast(`Renamed ${number(r.renamed.length)} trailer${r.renamed.length === 1 ? "" : "s"}${r.skipped.length ? `, skipped ${number(r.skipped.length)}` : ""}.`, r.skipped.length ? "info" : "success");
      dlg.close(); onChange?.();
    } catch (e) { inlineError(err, e.message); setDisabled(go, null); }
  }
}

/* ── Grab selected ─────────────────────────────────────────────────── */

/** Shown only when a selection includes titles that already have a trailer. Resolves via onChoose(replace). */
export function openGrabSelected({ missing, present, onChoose } = {}) {
  const total = missing + present;
  const dlg = createDialog({ title: `Grab ${number(total)} selected title${total === 1 ? "" : "s"}?`, size: "sm", role: "alertdialog" });
  const plural = (n, one, many) => `${number(n)} ${n === 1 ? one : many}`;
  const choose = (replaceExisting) => () => { dlg.close(); onChoose(replaceExisting); };
  dlg.body.append(
    h("ul", { class: "grab-counts" },
      h("li", {}, h("strong", {}, plural(missing, "title has", "titles have")), " no trailer and will be grabbed."),
      h("li", {}, h("strong", {}, plural(present, "title already has", "titles already have")), " a trailer.")),
    h("p", { class: "hint" }, "Grabbing all replaces those trailers: the old files are deleted once the new download succeeds, including trailers you chose with Manual or added yourself."));
  const missingOnly = btn("btn--primary", `Grab ${number(missing)} missing only`, choose(false), "download");
  setDisabled(missingOnly, !missing && "None of the selected titles are missing a trailer");
  dlg.footer.append(h("span", {}), h("div", { class: "dialog__actions" },
    btn("btn--tertiary", "Cancel", dlg.close), missingOnly,
    btn("btn--secondary btn--danger", `Grab all ${number(total)}`, choose(true), "download")));
  // The dialog is already open, so autofocus no longer applies: put focus on the safe choice.
  (missing ? missingOnly : dlg.footer.querySelector(".btn--tertiary")).focus();
}

/* ── Grab all missing ──────────────────────────────────────────────── */

export function openGrabAll(scope, { count, skipped = 0, label, onChange } = {}) {
  const dlg = createDialog({ title: `Grab ${number(count)} missing trailer${count === 1 ? "" : "s"}?`, size: "sm" });
  const err = h("div", {});
  const go = btn("btn--primary", "Start grab", start, "wand-magic-sparkles");
  dlg.body.append(h("p", { class: "hint hint--lead" }, "Trailer Park will search for every missing trailer in ", h("strong", {}, label), ". Titles are downloaded one after another; progress shows in the sidebar."),
    skipped ? h("p", { class: "hint" }, `${number(skipped)} unmonitored title${skipped === 1 ? " is" : "s are"} skipped (Settings → Automation). You can still grab ${skipped === 1 ? "it" : "them"} one at a time.`) : null,
    err);
  dlg.footer.append(h("span", {}), h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", dlg.close), go));
  async function start() {
    setDisabled(go, "Starting the grab…");
    try {
      const { batch } = await api.post("/batches", scope);
      store.set("batch", batch);
      toast(`Started grabbing ${number(batch.total)} trailers.`, "success");
      dlg.close(); onChange?.();
    } catch (e) { inlineError(err, e.message); setDisabled(go, null); }
  }
}
