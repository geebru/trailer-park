import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { api } from "../api.js";
import { timeAgo } from "../format.js";
import { describeActivity } from "../activity.js";
import { setDisabled } from "../tip.js";
import { pageHeading, notice } from "./common.js";

export const title = "Activity";
const PER_PAGE = 25;

export function mount(container, { query, navigate }) {
  let page = Math.max(1, parseInt(query.get("page") || "1", 10) || 1);
  const listEl = h("ul", { class: "activity-list" });
  const pagerEl = h("div", { class: "pager" });
  const msgEl = h("div", { class: "banners" });
  container.append(h("div", { class: "page" }, pageHeading("Activity"), msgEl,
    h("div", { class: "page__section" },
      h("section", { class: "panel", "aria-label": "Activity log" },
        h("div", { class: "activity-head", "aria-hidden": "true" }, h("span", {}, "Activity"), h("span", {}, "Details"), h("span", {}, "Time")),
        listEl, pagerEl))));

  async function load() {
    try {
      const data = await api.get(`/activity?per_page=${PER_PAGE}&page=${page}`);
      replace(msgEl);
      replace(listEl, data.items.length ? data.items.map((e) => {
        const d = describeActivity(e);
        return h("li", { class: "activity-row" },
          h("div", { class: "activity-row__what" }, icon(d.icon, `icon tone-${d.tone}`), h("span", {}, d.title)),
          h("div", { class: "activity-row__detail" }, d.sub),
          h("time", { class: "activity-row__time mono", datetime: e.ts || "", title: e.ts ? new Date(e.ts).toLocaleString() : "" }, timeAgo(e.ts)));
      }) : h("li", { class: "activity-empty" }, "No activity yet."));
      replace(pagerEl, data.pages > 1 && [
        setDisabled(h("button", { class: "btn btn--tertiary btn--sm", type: "button", onclick: () => go(page - 1) }, icon("chevron-left"), "Newer"), page <= 1 && "This is the newest page"),
        h("span", { class: "muted" }, `Page ${data.page} of ${data.pages} · ${data.total} entries`),
        setDisabled(h("button", { class: "btn btn--tertiary btn--sm", type: "button", onclick: () => go(page + 1) }, "Older", icon("chevron-right")), page >= data.pages && "This is the oldest page"),
      ]);
    } catch (err) {
      replace(msgEl, notice("danger", err.message));
    }
  }
  function go(next) { page = next; navigate(`/activity?page=${next}`); }
  load();
}
