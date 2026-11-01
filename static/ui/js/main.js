import { h } from "./dom.js";
import { defineRoutes, startRouter } from "./router.js";
import { buildShell, setActiveRoute, startPolling, closeMenu } from "./shell.js";
import { initTips } from "./tip.js";

initTips();
const root = document.getElementById("shell");
buildShell(root);

const main = h("main", { id: "main", class: "main", tabindex: "-1" });
root.append(main);

defineRoutes([
  { name: "overview", paths: ["/"], load: () => import("./pages/overview.js") },
  { name: "trailers", paths: ["/trailers"], load: () => import("./pages/trailers.js") },
  { name: "settings", paths: ["/settings"], load: () => import("./pages/settings.js") },
  { name: "activity", paths: ["/activity"], load: () => import("./pages/activity.js") },
  { name: "notfound", paths: [], fallback: true, load: () => import("./pages/notfound.js") },
], main, (name) => { setActiveRoute(name); closeMenu(); });

startPolling();
startRouter();
