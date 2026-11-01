/** Minimal client-side router on the History API. Routes are the four page addresses; the server serves the same shell for each. */
const routes = [];
let current = null;
let outlet = null;
let onChange = () => {};

export function defineRoutes(table, mountPoint, changed) {
  routes.splice(0, routes.length, ...table);
  outlet = mountPoint;
  onChange = changed || onChange;
}

function match(pathname) {
  const clean = pathname.replace(/\/+$/, "") || "/";
  return routes.find((r) => r.paths.includes(clean)) || routes.find((r) => r.fallback);
}

async function show(pathname, search, { focus }) {
  const route = match(pathname);
  if (current?.cleanup) { try { current.cleanup(); } catch { /* page teardown must not block navigation */ } }
  const page = await route.load();
  outlet.replaceChildren();
  const query = new URLSearchParams(search);
  const cleanup = page.mount(outlet, { query, navigate });
  current = { route, cleanup };
  document.title = `${page.title} · Trailarr Parrk`;
  onChange(route.name);
  if (focus) outlet.querySelector("h1")?.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

export function navigate(href, { replace = false } = {}) {
  const url = new URL(href, location.origin);
  if (url.pathname + url.search === location.pathname + location.search) return Promise.resolve();
  history[replace ? "replaceState" : "pushState"]({}, "", url.pathname + url.search);
  return show(url.pathname, url.search, { focus: true });
}

export function startRouter() {
  window.addEventListener("popstate", () => show(location.pathname, location.search, { focus: false }));
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest("a[href]");
    if (!link || link.target || link.hasAttribute("download")) return;
    const url = new URL(link.href, location.origin);
    if (url.origin !== location.origin || !routes.some((r) => r.paths.includes(url.pathname.replace(/\/+$/, "") || "/"))) return;
    event.preventDefault();
    navigate(url.pathname + url.search);
  });
  return show(location.pathname, location.search, { focus: false });
}
