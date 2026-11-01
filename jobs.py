"""Job registry and runner (SPEC section 5).

A job is one grab / replace / force run for one item. Requests return 202 immediately; the work
happens on a small thread pool, output is kept in a ring buffer, and the UI polls
GET /api/jobs/<id>?after=<seq>. Closing a dialog never stops a job; only cancel() does.

Jobs live in memory. They do not survive a restart, which is fine: the results that matter
(trailer files, Activity entries, cache rows) are persisted by the engine.

engine.py never imports this module. We bind a JobSink to the worker thread and the engine's
log_step() writes to it.
"""
import collections
import re
import threading
import time
import uuid

import engine as E
import library_cache as cache

LOG_LINES = 500                 # ring buffer per job
KEEP_SECONDS = 3600             # finished jobs are kept this long...
KEEP_COUNT = 50                 # ...or until more than this many finished jobs exist
MAX_WORKERS = 4                 # hard cap; the real concurrency limit is the download slot

KINDS = ("grab", "replace", "force")
ACTIVE = ("queued", "running")

_lock = threading.RLock()
_jobs = {}                      # id -> Job
_executor = None


def _now():
    return E.utc_now()


class Job:
    def __init__(self, kind, connection_id, item_id, title, year, params, batch=None):
        self.id = f"job-{uuid.uuid4().hex[:6]}"
        self.kind = kind
        self.connection_id = connection_id
        self.item_id = item_id
        self.item_key = f"{connection_id}:{item_id}"
        self.title = f"{title} ({year})" if year else str(title)
        self.params = params
        self.batch = batch
        self.suppress_notifications = batch is not None
        self.status = "queued"
        self.waiting = False            # waiting for a download slot
        self.progress = None            # 0-100 while yt-dlp is downloading
        self.result = None
        self.created_at = _now()
        self.started_at = None
        self.finished_at = None
        self.finished_mono = None
        self.cancel_requested = False
        self.process = None
        self.last_seq = 0
        self.lines = collections.deque(maxlen=LOG_LINES)
        self._last_progress_logged = -100.0

    # ── sink interface used by engine.log_step / download ────────────────
    def line(self, stream, text):
        match = E.PROGRESS_RE.match(text) if stream == "yt-dlp" else None
        with _lock:
            if match:
                pct = float(match.group(1))
                self.progress = pct
                # yt-dlp prints a line per update with --newline; keep the log readable.
                if pct < 100 and pct - self._last_progress_logged < 10:
                    return
                self._last_progress_logged = pct
            self.last_seq += 1
            self.lines.append({"seq": self.last_seq, "ts": _now(), "stream": stream, "text": text})

    def is_cancelled(self):
        return self.cancel_requested

    def attach_process(self, proc):
        with _lock:
            self.process = proc
        if proc is not None and self.cancel_requested:
            _terminate(proc)

    def set_waiting(self, waiting):
        with _lock:
            self.waiting = waiting
            if self.status in ACTIVE:
                self.status = "queued" if waiting else "running"

    # ── views ────────────────────────────────────────────────────────────
    def summary(self):
        return {
            "id": self.id, "kind": self.kind, "item_key": self.item_key,
            "connection_id": self.connection_id, "item_id": self.item_id,
            "title": self.title, "status": self.status, "progress": self.progress,
            "result": self.result, "batch_id": self.batch.id if self.batch else None,
            "created_at": self.created_at,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested, "last_seq": self.last_seq,
        }


def _terminate(proc):
    try:
        proc.terminate()
    except OSError:
        pass


def _get_executor():
    global _executor
    with _lock:
        if _executor is None:
            import concurrent.futures
            _executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=MAX_WORKERS, thread_name_prefix="job")
        return _executor


def _prune():
    """Called with _lock held."""
    finished = sorted((j for j in _jobs.values() if j.status not in ACTIVE),
                      key=lambda j: j.finished_mono or 0, reverse=True)
    cutoff = time.monotonic() - KEEP_SECONDS
    for index, job in enumerate(finished):
        if index >= KEEP_COUNT or (job.finished_mono or 0) < cutoff:
            _jobs.pop(job.id, None)


# ── Running ───────────────────────────────────────────────────────────────

def _status_to_result(payload, code):
    status = payload.get("status", "")
    if status == "downloaded":
        return "succeeded", {"outcome": "downloaded", "saved_to": payload.get("saved_to"),
                             "trailer": payload.get("trailer")}
    if status == "cancelled":
        return "cancelled", {"outcome": "cancelled"}
    if status == "exists":      # batch child whose title got a trailer since the cache was read
        return "succeeded", {"outcome": "exists"}
    error = payload.get("error")
    message = (payload.get("reason") or (E.short_ytdlp_error(error) if error else "")
               or {
                   "media_missing": "The media folder is missing or has no file yet.",
                   "no_tmdb_match": "No TMDB match for this title.",
                   "folder_missing": "The media folder does not exist.",
                   "exists": "A trailer already exists.",
                   "connection_missing": "The Arr connection no longer exists.",
               }.get(status) or f"Finished with status '{status or code}'.")
    return "failed", {"outcome": status or "failed", "message": str(message)[:500]}


def _run(job):
    E.bind_sink(job)
    with _lock:
        if job.cancel_requested:
            _finish(job, "cancelled", {"outcome": "cancelled"})
            return
        job.status = "running"
        job.started_at = _now()
    try:
        E.log_step(f"{job.kind.capitalize()} started: {job.title}")
        if job.kind == "force":
            payload, code = E.force_connection_item(
                job.connection_id, job.item_id, job.params["youtube_id"], trigger="Web UI")
        else:
            payload, code = E.grab_connection_item(
                job.connection_id, job.item_id, trigger="Web UI",
                replace=(job.kind == "replace"), skip_existing=job.batch is not None)
        status, result = _status_to_result(payload, code)
        if status == "succeeded":
            # Refresh before reporting success so the UI never shows a stale row (SPEC 4.3).
            try:
                cache.refresh_item(job.connection_id, job.item_id)
            except Exception as e:      # noqa: BLE001 - never turn a good download into a failure
                E.log_step(f"Cache refresh failed: {e}", level=30)
            E.log_step("Done.")
        elif status == "cancelled":
            E.log_step("Cancelled.")
        else:
            E.log_step(result["message"], level=40)
        _finish(job, status, result)
    except E.JobCancelled:
        E.log_step("Cancelled.")
        _finish(job, "cancelled", {"outcome": "cancelled"})
    except Exception as e:              # noqa: BLE001
        E.log.exception(f"Job {job.id} crashed")
        E.log_step(f"Unexpected error: {e}", level=40)
        _finish(job, "failed", {"outcome": "error", "message": str(e)[:500]})
    finally:
        E.bind_sink(None)
        with _lock:
            job.process = None


def _finish(job, status, result):
    with _lock:
        job.status = status
        job.waiting = False
        job.result = result
        job.finished_at = _now()
        job.finished_mono = time.monotonic()
        if status == "succeeded":
            job.progress = 100.0
        _prune()


# ── Public API ────────────────────────────────────────────────────────────

class Conflict(Exception):
    def __init__(self, job):
        super().__init__("A job is already active for this item.")
        self.job = job


def submit(kind, connection_id, item_id, title, year, batch=None, **params):
    if kind not in KINDS:
        raise ValueError("unknown job kind")
    with _lock:
        key = f"{connection_id}:{item_id}"
        for job in _jobs.values():
            if job.item_key == key and job.status in ACTIVE:
                raise Conflict(job)
        job = Job(kind, connection_id, item_id, title, year, params, batch)
        _jobs[job.id] = job
        _prune()
    _get_executor().submit(_run, job)
    return job


def get(job_id):
    with _lock:
        return _jobs.get(job_id)


def active_for_item(connection_id, item_id):
    key = f"{connection_id}:{item_id}"
    with _lock:
        for job in _jobs.values():
            if job.item_key == key and job.status in ACTIVE:
                return job
    return None


def list_jobs(active_only=False):
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.summary() for j in jobs if not active_only or j.status in ACTIVE]


def view(job, after=0):
    """Summary plus the lines with seq > after."""
    with _lock:
        data = job.summary()
        data["lines"] = [dict(l) for l in job.lines if l["seq"] > after]
        # A client that fell behind the ring buffer is told so it can show a gap.
        oldest = job.lines[0]["seq"] if job.lines else job.last_seq + 1
        data["truncated"] = after + 1 < oldest and job.last_seq > 0
        return data


def cancel(job):
    """Returns True if the job was active and cancellation was requested."""
    with _lock:
        if job.status not in ACTIVE:
            return False
        job.cancel_requested = True
        proc = job.process
    if proc is not None:
        _terminate(proc)
    E.log.info(f"Cancel requested for {job.id} ({job.title})")
    job.line("app", "Cancel requested…")
    return True


# ── Batches (SPEC section 5.4) ────────────────────────────────────────────
#
# A batch is a parent record plus one ordinary child job per item. Children are fed to the
# pool max_concurrent_downloads at a time, only one batch runs at once, and the children's
# Discord notifications are suppressed in favour of one summary when the batch ends.

_batch = None           # the running batch, or the most recent finished one
BATCH_FAILURES_SHOWN = 10


class Batch:
    def __init__(self, scope, items):
        self.id = f"batch-{uuid.uuid4().hex[:6]}"
        self.scope = scope
        self.items = items
        self.total = len(items)
        self.succeeded = self.failed = self.cancelled = 0
        self.status = "running"            # running | finished | cancelled
        self.cancel_requested = False
        self.in_flight = {}                # job id -> Job
        self.failures = []
        self.created_at = _now()
        self.finished_at = None

    @property
    def done(self):
        return self.succeeded + self.failed + self.cancelled

    def summary(self):
        with _lock:
            return {
                "id": self.id, "scope": self.scope, "status": self.status,
                "total": self.total, "done": self.done, "succeeded": self.succeeded,
                "failed": self.failed, "cancelled": self.cancelled,
                "cancel_requested": self.cancel_requested,
                "active": [{"job_id": j.id, "title": j.title, "progress": j.progress}
                           for j in self.in_flight.values()],
                "last_error": self.failures[-1] if self.failures else "",
                "created_at": self.created_at, "finished_at": self.finished_at,
            }


class BatchBusy(Exception):
    pass


def start_batch(scope, items):
    """items: list of {connection_id, id, title, year}. Raises BatchBusy."""
    global _batch
    with _lock:
        if _batch is not None and _batch.status == "running":
            raise BatchBusy()
        batch = _batch = Batch(scope, list(items))
    threading.Thread(target=_batch_worker, args=(batch,), daemon=True, name=batch.id).start()
    return batch


def current_batch():
    with _lock:
        return _batch


def cancel_batch():
    with _lock:
        batch = _batch
        if batch is None or batch.status != "running":
            return None
        batch.cancel_requested = True
        children = list(batch.in_flight.values())
    for child in children:
        cancel(child)
    E.log.info(f"Batch cancellation requested: {batch.scope}")
    return batch


def _record_child(batch, job):
    with _lock:
        batch.in_flight.pop(job.id, None)
        if job.status == "succeeded":
            batch.succeeded += 1
        elif job.status == "cancelled":
            batch.cancelled += 1
        else:
            batch.failed += 1
            reason = (job.result or {}).get("message") or "failed"
            batch.failures.append(f"{job.title}: {reason}")


def _batch_worker(batch):
    items = iter(batch.items)
    exhausted = False
    try:
        while True:
            with _lock:
                for job in [j for j in batch.in_flight.values() if j.status not in ACTIVE]:
                    _record_child(batch, job)
                stopping = batch.cancel_requested
                room = len(batch.in_flight) < E.max_concurrent_downloads()
                busy = bool(batch.in_flight)
            if stopping:
                if not busy:
                    break
            elif room and not exhausted:
                item = next(items, None)
                if item is None:
                    exhausted = True
                else:
                    try:
                        job = submit("grab", item["connection_id"], item["id"],
                                     item["title"], item["year"], batch=batch)
                        with _lock:
                            batch.in_flight[job.id] = job
                    except Conflict:
                        with _lock:
                            batch.failed += 1
                            batch.failures.append(
                                f"{item['title']} ({item['year']}): a job is already running")
                continue
            elif exhausted and not busy:
                break
            time.sleep(0.3)
    except Exception:                      # noqa: BLE001
        E.log.exception("Batch worker crashed")
    finally:
        with _lock:
            was_cancelled = batch.cancel_requested
            batch.cancelled += max(0, batch.total - batch.done)   # never started
            batch.status = "cancelled" if was_cancelled else "finished"
            batch.finished_at = _now()
        _batch_report(batch)


def _batch_report(batch):
    s = batch.summary()
    if batch.status == "cancelled":
        E.record_activity({
            "kind": "batch", "status": "warning", "action": "Batch cancelled",
            "source": "Web UI", "title": batch.scope,
            "detail": f"Batch cancelled after {s['succeeded'] + s['failed']} completed task(s). "
                      f"{s['cancelled']} were not finished."})
    if s["succeeded"] + s["failed"] == 0:
        return
    counts = (f"{s['succeeded']} downloaded, {s['failed']} failed"
              + (f", {s['cancelled']} cancelled" if s["cancelled"] else "")
              + f" (of {s['total']}).")
    if batch.status != "cancelled":
        E.record_activity({
            "kind": "batch", "status": "success" if not s["failed"] else "warning",
            "action": "Batch finished", "source": "Web UI", "title": batch.scope,
            "year": "", "detail": counts})
    failures = [f"• {f}" for f in batch.failures[:BATCH_FAILURES_SHOWN]]
    if len(batch.failures) > BATCH_FAILURES_SHOWN:
        failures.append(f"…and {len(batch.failures) - BATCH_FAILURES_SHOWN} more. See Activity.")
    icon = "✅" if not s["failed"] else "⚠️"
    E.notify_summary(
        f"{icon} Batch {batch.status} — {batch.scope}",
        [f"{s['succeeded']} downloaded."] if s["succeeded"] else [],
        ([f"{s['failed']} failed."] + failures) if s["failed"] else [])
