import { h } from "./dom.js";
import { icon } from "./icons.js";

let region = null;

/** Short status message in a polite live region. tone: success | danger | info. */
export function toast(message, tone = "info", ms = 5000) {
  if (!region) {
    region = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(region);
  }
  const el = h("div", { class: `toast toast--${tone}` },
    icon(tone === "success" ? "circle-check" : tone === "danger" ? "circle-xmark" : "circle-info", `icon tone-${tone}`),
    h("span", {}, message),
    h("button", { type: "button", class: "toast__close", "aria-label": "Dismiss", onclick: () => el.remove() }, icon("xmark")));
  region.append(el);
  setTimeout(() => el.remove(), ms);
}
