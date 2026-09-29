# Microsoft's Playwright image already carries Chromium and every system
# library it needs - building on plain python:slim means chasing ~40 apt
# packages by hand. Keep this tag in step with the playwright pin in
# requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

# REQUIRE_AUTH makes the server refuse to start without APP_PASSWORD, since
# this image always listens on all interfaces.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    REQUIRE_AUTH=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gmaps_scraper/ ./gmaps_scraper/
COPY webapp/ ./webapp/
COPY run_web.py scrape.py ./

# Chromium refuses to run as root without --no-sandbox; the base image ships a
# non-root user for exactly this.
USER pwuser

EXPOSE 8000

# Single worker on purpose: job state lives in memory, so a second worker would
# serve "unknown job" to half the polls.
CMD ["python", "-m", "uvicorn", "webapp.server:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--log-level", "warning"]
