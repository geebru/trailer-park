import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { store } from "../store.js";
import { api } from "../api.js";
import { number, timeAgo } from "../format.js";
import { describeActivity } from "../activity.js";
import { pageHeading, notice } from "./common.js";

export const title = "Overview";

function stat({ iconName, label, value, detail, accent, action }) {
  return h("div", { class: "stat" },
    h("div", { class: `stat__icon${accent ? " tone-warning" : " stat__icon--accent"}` }, icon(iconName)),
    h("div", { class: "stat__body" },
      h("div", { class: "stat__head" },
        h("div", { class: "stat__label" }, label),
        action),
      h("div", { class: "stat__value mono" }, value),
      h("div", { class: "stat__detail" }, detail)));
}

function activityRow(entry) {
  const d = describeActivity(entry);
  return h("li", { class: "activity-row" },
    h("div", { class: "activity-row__what" }, icon(d.icon, `icon tone-${d.tone}`), h("span", {}, d.title)),
    h("div", { class: "activity-row__detail" }, d.sub),
    h("time", { class: "activity-row__time mono", datetime: entry.ts || "" }, timeAgo(entry.ts)));
}

export function mount(container, { navigate }) {
  const heading = pageHeading("Overview");
  const statsEl = h("div", { class: "stats" });
  const bannerEl = h("div", { class: "banners" });
  const activityEl = h("ul", { class: "activity-list" });
  const panel = h("section", { class: "panel", "aria-labelledby": "recent-activity" },
    h("div", { class: "panel__head" },
      h("h2", { class: "panel__title", id: "recent-activity" }, "Recent activity"),
      h("a", { class: "btn btn--tertiary btn--sm", href: "/activity" }, "View all")),
    h("div", { class: "activity-head", "aria-hidden": "true" }, h("span", {}, "Activity"), h("span", {}, "Details"), h("span", {}, "Time")),
    activityEl);
  container.append(h("div", { class: "page" }, heading, bannerEl, statsEl, h("div", { class: "page__section" }, panel)));

  function render(o) {
    if (!o) {
      replace(statsEl, h("p", { class: "muted" }, "Loading…"));
      return;
    }
    const t = o.totals;
    const pctMissing = t.all ? ((t.missing / t.all) * 100).toFixed(1) : "0.0";
    replace(statsEl,
      stat({ iconName: "film", label: "Total media", value: number(t.all), detail: `${number(t.movies)} movies · ${number(t.series)} series` }),
      stat({ iconName: "triangle-exclamation", label: "Missing trailers", value: number(t.missing), detail: `${pctMissing}% of all titles`, accent: true,
        action: t.missing ? h("a", { class: "btn btn--tertiary btn--sm stat__action", href: "/trailers?status=missing" }, "Review", icon("arrow-right")) : null }),
      stat({ iconName: "tower-broadcast", label: "Coverage", value: `${Number(t.coverage).toFixed(1)}%`, detail: `${number(t.present)} trailers available` }));

    const banners = [];
    if (o.scan && o.scan.state !== "ready") {
      banners.push(notice("info", `Scanning your libraries… ${number(o.scan.done)} of ${number(o.scan.total)} titles. Numbers will settle when it finishes.`));
    }
    for (const e of o.errors || []) {
      const name = (o.connections.find((c) => c.id === e.connection_id) || {}).name || "A connection";
      banners.push(notice("warning", h("strong", {}, name), ` can't be read: ${e.message}`));
    }
    replace(bannerEl, banners);

    replace(activityEl, o.activity.length
      ? o.activity.map(activityRow)
      : h("li", { class: "activity-empty" }, "Nothing has happened yet. Grabs, renames and syncs will show up here."));
  }

  render(store.get("overview"));
  const off = store.subscribe("overview", render);
  // Fresh numbers on arrival even if the shell's last poll is a few seconds old.
  api.get("/overview").then((o) => store.set("overview", o)).catch(() => {});
  return off;
}
