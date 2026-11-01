import { h } from "../dom.js";
import { pageHeading } from "./common.js";

export const title = "Not found";

export function mount(container) {
  container.append(h("div", { class: "page" }, pageHeading("Page not found"),
    h("p", { class: "page__section muted" }, "There is nothing at this address. ", h("a", { class: "link", href: "/" }, "Go to Overview"), ".")));
}
