import { h } from "../dom.js";
import { icon } from "../icons.js";
import { openMenu } from "../shell.js";

/** H1 row with the mobile menu button. The h1 is focusable so route changes can move focus to it. */
export function pageHeading(title, actions) {
  return h("div", { class: "page-heading" },
    h("div", { class: "page-heading__title" },
      h("button", { type: "button", class: "btn btn--tertiary btn--square menu-button", "aria-label": "Open menu", onclick: openMenu }, icon("bars")),
      h("h1", { tabindex: "-1" }, title)),
    actions ? h("div", { class: "page-heading__actions" }, actions) : null);
}

export function notice(tone, ...children) {
  return h("div", { class: `notice notice--${tone}`, role: tone === "danger" ? "alert" : "status" },
    icon(tone === "danger" || tone === "warning" ? "triangle-exclamation" : "circle-info", "icon notice__icon"),
    h("div", { class: "notice__body" }, children));
}
