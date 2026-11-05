/** Turns an /api/activity entry into display text. Kind and status come from the server; this
 *  only chooses words and icons. */
const titleYear = (e) => (e.title ? `${e.title}${e.year ? ` (${e.year})` : ""}` : "");
const clip = (text, max = 170) => {
  const line = String(text || "").split("\n")[0].trim();
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
};
const basename = (path) => String(path).split(/[\\/]/).pop();

function savedFile(detail) {
  const match = /downloaded to (.+?)(?: — |\.$|$)/.exec(detail || "");
  return match ? basename(match[1]) : "";
}

export function describeActivity(e) {
  const subject = titleYear(e);
  const join = (...parts) => parts.filter(Boolean).join(" · ");
  const tone = e.status === "success" ? "success" : e.status === "warning" ? "warning" : e.status === "error" ? "danger" : "neutral";

  switch (e.kind) {
    case "grab": {
      if (e.status === "success") {
        const manual = e.action === "force";
        return { icon: "download", tone, title: manual ? "Manual trailer downloaded" : "Trailer downloaded",
                 sub: join(subject, savedFile(e.detail)) };
      }
      if (e.status === "warning") return { icon: "triangle-exclamation", tone, title: "No suitable match found", sub: join(subject, clip(e.detail)) };
      return { icon: "circle-xmark", tone, title: "Trailer download failed", sub: join(subject, clip(e.detail)) };
    }
    case "rename": {
      const bulk = /rename to current naming/i.test(e.title || "");
      return { icon: "pencil", tone, title: bulk ? "Trailers renamed" : "Trailer renamed",
               sub: bulk ? join(e.title.split(":")[0], clip(e.detail)) : join(subject, clip(e.detail)) };
    }
    case "delete":
      return { icon: "trash", tone, title: "Trailer files removed", sub: join(subject, clip(e.detail)) };
    case "batch":
      return { icon: "list-check", tone, title: /cancel/i.test(e.action || "") ? "Batch cancelled" : "Batch finished", sub: join(e.title, clip(e.detail)) };
    case "sync":
      return { icon: e.status === "error" ? "circle-xmark" : "arrows-rotate", tone,
               title: e.status === "error" ? "Sync failed" : "Sync checked", sub: join(e.title, clip(e.detail)) };
    case "ytdlp":
      return { icon: "terminal", tone: "neutral", title: "yt-dlp updated", sub: clip(e.detail) };
    case "cleanup":
      return { icon: "broom", tone: "neutral", title: "Maintenance", sub: clip(e.detail) };
    default:
      return { icon: "circle-info", tone: "info", title: e.action ? e.action[0].toUpperCase() + e.action.slice(1) : "Activity", sub: join(subject, clip(e.detail)) };
  }
}
