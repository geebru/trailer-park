import { h } from "./dom.js";
import { icon } from "./icons.js";

/** Modal built on the native <dialog>: focus trap, Escape, inert page and focus return come from the browser.
 *  Returns {el, body, footer, close, setHeading(title, sub)}. Clicking the backdrop closes it. */
let counter = 0;
export function createDialog({ title, subtitle, size = "md", role = "dialog", onClose, tone } = {}) {
  const id = `dlg-${++counter}`;
  const titleEl = h("h2", { id: `${id}-title`, class: "dialog__title" }, title);
  const subEl = h("p", { class: "dialog__sub" }, subtitle);
  const lead = h("span", { class: "dialog__lead" });
  const body = h("div", { class: "dialog__body", tabindex: "0" });
  const footer = h("div", { class: "dialog__footer" });
  const closeBtn = h("button", { type: "button", class: "btn btn--tertiary btn--square btn--sm dialog__close", "aria-label": "Close dialog", onclick: () => close() }, icon("xmark"));
  const el = h("dialog", { class: `dialog dialog--${size}${tone ? ` dialog--${tone}` : ""}`, "aria-labelledby": `${id}-title`, role },
    h("header", { class: "dialog__head" }, h("div", { class: "dialog__heading" }, h("div", { class: "dialog__titlerow" }, lead, titleEl), subtitle ? subEl : null), closeBtn),
    body, footer);
  el.addEventListener("click", (e) => { if (e.target === el) close(); });
  el.addEventListener("close", () => { el.remove(); onClose?.(); });
  function close() { if (el.open) el.close(); else el.remove(); }
  document.body.append(el);
  el.showModal();
  return {
    el, body, footer, close,
    setHeading(t, s, leadNode) { titleEl.textContent = t; if (s != null) subEl.textContent = s; lead.replaceChildren(...(leadNode ? [leadNode] : [])); },
  };
}
