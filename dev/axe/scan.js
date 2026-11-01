// Accessibility scan for the page open in the browser pane. Paste the whole file into the page's JS (the
// Browser pane's javascript tool), with the helper server from dev/axe/README.md running on port 8090.
// Rules: WCAG 2.0/2.1/2.2 A and AA. Returns a compact summary; the page is not modified.
(async () => {
  if (!window.axe) {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "http://127.0.0.1:8090/axe.min.js";
      script.onload = resolve;
      script.onerror = () => reject(new Error("Could not load axe.min.js. Is the server on port 8090 running?"));
      document.head.append(script);
    });
  }
  const results = await axe.run(document, {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
  });
  return {
    page: location.pathname + location.search,
    width: innerWidth,
    axe: axe.version,
    violations: results.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      count: v.nodes.length,
      targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
    })),
    needsReview: results.incomplete.map((v) => v.id),
  };
})();
