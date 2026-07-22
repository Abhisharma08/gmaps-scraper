"""FastAPI server backing the local web UI.

Run with:  python run_web.py
"""

import os
import tempfile
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from gmaps_scraper import exporter
from gmaps_scraper.models import Business

from . import jobs

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Google Maps Scraper", docs_url="/api/docs")


class ScrapeRequest(BaseModel):
    queries: str = Field(..., description="one query per line")
    max_results: int = 50
    source: str = "browser"
    api_key: str = ""
    find_emails: bool = True
    emails_only: bool = False
    workers: int = 8
    max_pages: int = 3
    timeout: float = 12.0
    headless: bool = True


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
        return fh.read()


@app.get("/api/config")
def config() -> dict:
    """Tell the UI whether an API key is already available server-side."""
    return {"has_api_key": bool(os.environ.get("GOOGLE_MAPS_API_KEY"))}


@app.post("/api/scrape")
def start_scrape(req: ScrapeRequest) -> dict:
    queries: List[str] = []
    for line in req.queries.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in queries:
            queries.append(line)

    if not queries:
        raise HTTPException(400, "Enter at least one search query.")
    if req.source not in ("browser", "api"):
        raise HTTPException(400, "source must be 'browser' or 'api'.")
    if req.source == "api" and not (req.api_key or os.environ.get("GOOGLE_MAPS_API_KEY")):
        raise HTTPException(
            400, "The Places API needs a key. Paste one, or set GOOGLE_MAPS_API_KEY."
        )

    job = jobs.start(
        queries,
        {
            "max_results": max(1, min(req.max_results, 500)),
            "source": req.source,
            "api_key": req.api_key.strip(),
            "find_emails": req.find_emails,
            "emails_only": req.emails_only,
            "workers": max(1, min(req.workers, 32)),
            "max_pages": max(1, min(req.max_pages, 10)),
            "timeout": req.timeout,
            "headless": req.headless,
        },
    )
    return {"job_id": job.id, "queries": queries}


def _job_or_404(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job - the server may have restarted.")
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, since_log: int = 0, since_rows: int = 0) -> dict:
    return _job_or_404(job_id).snapshot(since_log, since_rows)


@app.get("/api/jobs/{job_id}/rows")
def job_rows(job_id: str) -> dict:
    job = _job_or_404(job_id)
    return {"rows": job.all_rows(), "version": job.version}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = _job_or_404(job_id)
    job.cancel.set()
    job.append_log("Stopping after the current listing...")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str, fmt: str = "csv") -> FileResponse:
    job = _job_or_404(job_id)
    if fmt not in ("csv", "xlsx", "json"):
        raise HTTPException(400, "fmt must be csv, xlsx or json.")
    if not job.businesses:
        raise HTTPException(400, "This job has no results to download.")

    slug = "".join(
        c if c.isalnum() or c in "-_" else "-" for c in (job.queries[0][:40] or "results")
    ).strip("-")
    filename = "{}.{}".format(slug or "results", fmt)
    path = os.path.join(tempfile.gettempdir(), "gmaps-{}-{}".format(job.id, filename))

    with job._lock:
        rows: List[Business] = list(job.businesses)
    exporter.write(rows, path)

    return FileResponse(path, filename=filename, media_type="application/octet-stream")
