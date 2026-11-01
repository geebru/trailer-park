/** Shared state with subscriptions, so the sidebar and pages never poll the same endpoint twice. */
const state = { overview: null, jobs: [], batch: null };
const listeners = new Map();

export const store = {
  get: (key) => state[key],
  set(key, value) {
    state[key] = value;
    for (const fn of listeners.get(key) || []) fn(value);
  },
  subscribe(key, fn) {
    if (!listeners.has(key)) listeners.set(key, new Set());
    listeners.get(key).add(fn);
    return () => listeners.get(key).delete(fn);
  },
};
