/** Calls fn() repeatedly, waiting getDelay() ms between runs. Pauses while the tab is hidden and
 *  refreshes straight away when it becomes visible again. Returns {stop, now}. */
export function poll(fn, getDelay) {
  let timer = null;
  let stopped = false;
  let running = false;

  async function tick() {
    clearTimeout(timer);
    if (stopped || document.hidden || running) return;
    running = true;
    try { await fn(); } catch { /* callers surface their own errors */ }
    running = false;
    if (!stopped) timer = setTimeout(tick, getDelay());
  }
  const onVisible = () => { if (!document.hidden) tick(); };
  document.addEventListener("visibilitychange", onVisible);
  tick();

  return {
    now: tick,
    stop() {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    },
  };
}
