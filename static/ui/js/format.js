/** Compact relative time: "now", "2m", "3h", "5d"; older than 30 days shows the date. */
export function timeAgo(iso, now = Date.now()) {
  const then = Date.parse(iso || "");
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 45) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  if (days <= 30) return `${days}d`;
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** Time until a future ISO timestamp: "<1m", "18m", "2h 5m". Empty string if unknown. */
export function timeUntil(iso, now = Date.now()) {
  const then = Date.parse(iso || "");
  if (Number.isNaN(then)) return "";
  const minutes = Math.ceil((then - now) / 60000);
  if (minutes <= 0) return "<1m";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

export const number = (n) => Number(n || 0).toLocaleString();
export const plural = (n, one, many = `${one}s`) => `${number(n)} ${n === 1 ? one : many}`;

/** "http://192.168.1.12:7878/x" -> "192.168.1.12:7878" */
export function hostOf(url) {
  try { return new URL(url).host; } catch { return String(url || ""); }
}
