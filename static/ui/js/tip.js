import { h } from "./dom.js";

/* Disabled actions that say why.
   A native disabled button cannot be focused or clicked, so keyboard, touch and screen-reader users never reach a
   reason. These buttons use aria-disabled instead: they stay focusable, initTips() blocks their clicks, and the
   reason shows on hover, focus and tap, and is read as the button's description. */

const BLOCKED = '[aria-disabled="true"][data-why]';
const ids = new Map();    // reason text -> id of its hidden description
let reasons, bubble, current;

function describedBy(reason) {
  if (!ids.has(reason)) {
    reasons ||= document.body.appendChild(h("div", { hidden: true }));
    const id = `why-${ids.size + 1}`;
    reasons.append(h("span", { id }, reason));
    ids.set(reason, id);
  }
  return ids.get(reason);
}

/** Disable a button with a reason, or enable it when the reason is empty. Returns the button. */
export function setDisabled(el, reason) {
  if (reason) {
    el.setAttribute("aria-disabled", "true");
    el.dataset.why = reason;
    el.setAttribute("aria-describedby", describedBy(reason));
  } else {
    el.removeAttribute("aria-disabled");
    delete el.dataset.why;
    el.removeAttribute("aria-describedby");
  }
  if (el === current) reason ? show(el) : hide();
  return el;
}

function show(el) {
  // A popover sits in the top layer, so it also shows above an open <dialog>.
  bubble ||= document.body.appendChild(h("div", { class: "tip", role: "tooltip", popover: "manual" }));
  bubble.textContent = el.dataset.why;
  if (!bubble.matches(":popover-open")) bubble.showPopover();
  current = el;
  const gap = 8;
  const r = el.getBoundingClientRect();
  const t = bubble.getBoundingClientRect();
  const above = r.top - t.height - gap;
  bubble.style.top = `${above >= gap ? above : r.bottom + gap}px`;
  bubble.style.left = `${Math.min(Math.max(gap, r.left + (r.width - t.width) / 2), innerWidth - t.width - gap)}px`;
}

function hide() {
  current = null;
  if (bubble?.matches(":popover-open")) bubble.hidePopover();
}

export function initTips() {
  const hit = (e) => e.target.closest?.(BLOCKED);
  // Capture phase, so the button's own handler never runs. A tap or click also reveals the reason.
  document.addEventListener("click", (e) => {
    const el = hit(e);
    if (!el) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    show(el);
  }, true);
  document.addEventListener("pointerover", (e) => { const el = hit(e); if (el) show(el); else if (current) hide(); });
  document.addEventListener("pointerdown", (e) => { if (!hit(e)) hide(); });
  document.addEventListener("focusin", (e) => { const el = hit(e); if (el) show(el); else hide(); });
  document.addEventListener("focusout", hide);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  addEventListener("scroll", hide, true);
  // The sidebar and dialogs re-render; do not leave a reason behind for a button that is gone.
  new MutationObserver(() => { if (current && !current.isConnected) hide(); }).observe(document.body, { childList: true, subtree: true });
}
