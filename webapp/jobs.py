"""In-memory job registry: runs a scrape on a worker thread and tracks progress.

Playwright's sync API refuses to run on a thread with a live asyncio loop, so
every job gets its own plain thread rather than the server's event loop.
"""

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from gmaps_scraper import email_finder
from gmaps_scraper.models import Business

# Each browser job holds a Chromium instance (~0.5-1GB). Cap how many run at
# once so a few simultaneous users can't exhaust a small box; the rest queue.
MAX_CONCURRENT = max(1, int(os.environ.get("MAX_CONCURRENT_JOBS", "2")))
_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)


@dataclass
class Job:
    id: str
    queries: List[str]
    options: dict
    status: str = "running"  # running | done | cancelled | error
    phase: str = "queued"  # queued | scraping | emails | finished
    log: List[str] = field(default_factory=list)
    businesses: List[Business] = field(default_factory=list)
    error: str = ""
    version: int = 0  # bumped when existing rows change (email enrichment)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append_log(self, *parts) -> None:
        line = " ".join(str(p) for p in parts).rstrip()
        with self._lock:
            self.log.append(line)
            # Keep memory bounded on very long runs.
            if len(self.log) > 5000:
                del self.log[:1000]

    def snapshot(self, since_log: int = 0, since_rows: int = 0) -> dict:
        with self._lock:
            log_tail = self.log[since_log:]
            log_count = len(self.log)
            rows = [b.to_row() for b in self.businesses[since_rows:]]
            row_count = len(self.businesses)
        return {
            "id": self.id,
            "status": self.status,
            "phase": self.phase,
            "error": self.error,
            "version": self.version,
            "log": log_tail,
            "log_count": log_count,
            "rows": rows,
            "row_count": row_count,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
            "stats": self.stats(),
        }

    def all_rows(self) -> List[dict]:
        with self._lock:
            return [b.to_row() for b in self.businesses]

    def stats(self) -> dict:
        with self._lock:
            items = list(self.businesses)
        return {
            "total": len(items),
            "phone": sum(1 for b in items if b.phone),
            "website": sum(1 for b in items if b.website),
            "email": sum(1 for b in items if b.emails),
        }


JOBS: Dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def get(job_id: str) -> Optional[Job]:
    with _JOBS_LOCK:
        return JOBS.get(job_id)


def start(queries: List[str], options: dict) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], queries=queries, options=options)
    with _JOBS_LOCK:
        JOBS[job.id] = job
        # Drop the oldest finished jobs so a long-lived server doesn't grow
        # without bound.
        if len(JOBS) > 20:
            for old_id, old in sorted(JOBS.items(), key=lambda kv: kv[1].started_at):
                if old.status != "running" and len(JOBS) > 20:
                    del JOBS[old_id]

    thread = threading.Thread(target=_run, args=(job,), daemon=True)
    thread.start()
    return job


def _run(job: Job) -> None:
    if not _SLOTS.acquire(blocking=False):
        job.append_log(
            "Waiting for a free slot ({} jobs already running)...".format(MAX_CONCURRENT)
        )
        _SLOTS.acquire()
    try:
        _scrape(job)
    finally:
        _SLOTS.release()


def _scrape(job: Job) -> None:
    opts = job.options
    seen = set()

    try:
        job.phase = "scraping"
        for query in job.queries:
            if job.cancel.is_set():
                break
            job.append_log("> {}".format(query))

            if opts.get("near"):
                from gmaps_scraper.sources import playwright_source

                stream = playwright_source.scrape_area(
                    query,
                    opts["near"],
                    max_results=opts["max_results"],
                    grid=opts.get("grid", 3),
                    radius_km=opts.get("radius", 10.0),
                    headless=opts.get("headless", True),
                    log=job.append_log,
                    should_stop=job.cancel.is_set,
                )
            elif opts["source"] == "api":
                from gmaps_scraper.sources import places_api

                stream = places_api.scrape(
                    query,
                    opts["max_results"],
                    api_key=opts.get("api_key") or None,
                    log=job.append_log,
                    should_stop=job.cancel.is_set,
                )
            else:
                from gmaps_scraper.sources import playwright_source

                stream = playwright_source.scrape(
                    query,
                    opts["max_results"],
                    headless=opts.get("headless", True),
                    log=job.append_log,
                    should_stop=job.cancel.is_set,
                )

            for biz in stream:
                if job.cancel.is_set():
                    stream.close()
                    break
                key = biz.key()
                if key in seen:
                    continue
                seen.add(key)
                with job._lock:
                    job.businesses.append(biz)

        if opts.get("find_emails", True) and not job.cancel.is_set():
            job.phase = "emails"
            email_finder.enrich(
                job.businesses,
                workers=opts.get("workers", 8),
                log=job.append_log,
                timeout=opts.get("timeout", 12.0),
                max_pages=opts.get("max_pages", 3),
                should_stop=job.cancel.is_set,
            )
            job.version += 1  # rows now carry emails; client refetches

        if opts.get("emails_only"):
            with job._lock:
                job.businesses = [b for b in job.businesses if b.emails]
            job.version += 1

        job.status = "cancelled" if job.cancel.is_set() else "done"
        job.append_log(
            "Finished: {} businesses.".format(len(job.businesses))
            if job.status == "done"
            else "Stopped early: kept {} businesses.".format(len(job.businesses))
        )
    except BaseException as exc:  # SystemExit from missing API key lands here too
        job.status = "error"
        job.error = str(exc) or exc.__class__.__name__
        job.append_log("ERROR: {}".format(job.error))
    finally:
        job.phase = "finished"
        job.finished_at = time.time()
