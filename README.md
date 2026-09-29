# Google Maps Business Scraper

Turn a Google Maps search like `dentists in Austin TX` into a spreadsheet of
leads: **name, category, address, phone, website, rating, review count,
coordinates and email addresses**. It then visits each business's own website to
find their email addresses.

Use it from a **local web UI** (type searches, watch results arrive, download a
sheet) or from the **command line**. Run it on your laptop, or deploy it for a
team with Docker behind a password.

- **Two backends:** free headless-browser scraping, or the official Google Places API
- **Email discovery:** homepage and contact pages, `mailto:` links, schema.org
  data, Cloudflare-protected addresses and `name (at) domain (dot) com` text
- **More than ~100 results per search:** a wide-area sweep searches a grid of map
  views around a location
- **CSV, Excel or JSON output:** duplicates are removed across all your queries
- **Stop at any time and keep what's been found:** the web UI's Stop button or
  `Ctrl-C` on the command line

> **Before you use it:** scraping Google Maps breaks Google's Terms of Service,
> and the emails it collects are personal data covered by GDPR, CAN-SPAM and
> similar laws. Read [Responsible use](#responsible-use).

---

## Contents

- [Quick start](#quick-start)
- [Installation](#installation)
- [Using the web UI](#using-the-web-ui)
- [Using the command line](#using-the-command-line)
- [Output](#output)
- [Choosing a backend](#choosing-a-backend)
- [Getting more than ~100 results](#getting-more-than-100-results)
- [How email finding works](#how-email-finding-works)
- [Deploying for a team](#deploying-for-a-team)
- [Configuration reference](#configuration-reference)
- [HTTP API](#http-api)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Contributing](#contributing)
- [Responsible use](#responsible-use)
- [License](#license)

---

## Quick start

```bash
git clone https://github.com/Abhisharma08/gmaps-scraper.git
cd gmaps-scraper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python run_web.py          # opens http://127.0.0.1:8000
```

Or skip the UI:

```bash
python scrape.py "dentists in Austin TX" -n 30 -o dentists.xlsx
```

## Installation

**Requirements**

- Python 3.9 or newer
- About 500 MB of disk space for Playwright's Chromium (browser backend only)
- A Google Cloud API key, but only if you use the Places API backend

**Steps**

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # skip if you'll only use --source api
```

**Optional: create a settings file.** Settings are read from environment
variables or from a `.env` file in the project folder:

```bash
cp .env.example .env
```

For local use you only need `GOOGLE_MAPS_API_KEY`, and only for the API backend.
Every setting is listed in the [Configuration reference](#configuration-reference).

## Using the web UI

```bash
python run_web.py
```

This starts a local server and opens <http://127.0.0.1:8000> in your browser.

1. Type one search per line into **Search queries**, e.g. `plumbers in Round Rock TX`.
2. Set **Results per query**.
3. Optionally tick **Search a wide area** and enter a **Location**, **Grid** and
   **Area half-width (km)**. See [Getting more than ~100 results](#getting-more-than-100-results).
4. Press **Start scraping**. Rows appear in the table as listings are read, the
   **Activity log** shows progress, and emails fill in once the email lookup runs.
5. Download the results with **Download CSV**, **Download Excel** or **Download JSON**.

Other controls:

| Control | What it does |
|---|---|
| **Stop** | Halts the run, including the email lookup, and keeps everything found so far |
| **Source** | *Browser (free)* or *Places API (key)*. With the API, paste a key unless the server already has one |
| **Find emails on websites** | Turn off for a much faster run without emails |
| **Only keep rows with an email** | Drops listings where no email was found |
| **Show browser window** | Runs Chromium visibly so you can watch it work |
| **Advanced** | Parallel site fetches, pages checked per site, request timeout |

Server options:

```bash
python run_web.py --port 9000          # different port
python run_web.py --no-browser         # don't open a tab automatically
python run_web.py --host 0.0.0.0       # reachable from your network - needs APP_PASSWORD
```

By default the server only listens on `127.0.0.1`, so nothing is reachable from
outside your machine. It refuses to listen on any other address unless
`APP_PASSWORD` is set.

## Using the command line

```bash
python scrape.py [QUERY ...] [options]
# or: python -m gmaps_scraper [QUERY ...] [options]
```

**Examples**

```bash
# One search, 60 results, CSV
python scrape.py "dentists in Austin TX" -n 60 -o dentists.csv

# Several searches into one spreadsheet
python scrape.py "plumbers in Austin TX" "electricians in Austin TX" -o leads.xlsx

# Searches from a file (one per line, lines starting with # are ignored)
python scrape.py -f queries.example.txt -n 100 -o leads.xlsx --workers 12

# Official Places API instead of the browser
python scrape.py "cafes in Berlin" --source api -o cafes.csv

# Wide-area sweep past Google's ~100 cap
python scrape.py "restaurants" --near "Denver CO" --grid 3 --radius 10 -n 300 -o denver.xlsx

# Map data only, no website visits (fast)
python scrape.py "gyms in Mumbai" --no-emails -o gyms.csv

# Watch the browser (useful when something breaks)
python scrape.py "gyms in Mumbai" --no-headless -n 5
```

**All options**

| Flag | Default | Meaning |
|---|---|---|
| `QUERY ...` | – | One or more searches |
| `-f, --queries-file FILE` | – | File with one search per line; combined with any `QUERY` arguments |
| `-n, --max-results N` | 50 | Listings per query. With `--near`, the total across the whole sweep |
| `-o, --output PATH` | `results.csv` | Output file; the format comes from the extension: `.csv`, `.xlsx`, `.json` |
| `-s, --source` | `browser` | `browser` (free scraping) or `api` (Google Places API) |
| `--api-key KEY` | `$GOOGLE_MAPS_API_KEY` | Places API key |
| `--near LOCATION` | – | Turns on the wide-area sweep around this place. Browser only |
| `--grid N` | 3 | With `--near`: an N×N grid of map views |
| `--radius KM` | 10 | With `--near`: half-width of the area, so 10 means a 20×20 km square |
| `--no-emails` | off | Skip the website email lookup |
| `--emails-only` | off | Drop listings with no email |
| `--workers N` | 8 | Websites fetched in parallel during email lookup |
| `--max-pages N` | 3 | Pages checked per website: the homepage plus up to N−1 contact pages |
| `--timeout SECS` | 12 | Timeout for each website request |
| `--no-headless` | off | Show the browser window |
| `-q, --quiet` | off | Print only the final summary |

Pressing `Ctrl-C` during a run still saves everything collected so far.

## Output

Every format has the same columns, in this order:

| Column | Example | Notes |
|---|---|---|
| `name` | Sample Dental Studio | |
| `category` | Dentist | Google's primary category |
| `address` | 100 Main St, Austin, TX 78701 | |
| `phone` | +1 512-555-0100 | |
| `website` | https://sampledental.example/ | Blank if the listing has none |
| `emails` | info@sampledental.example | Comma-separated in CSV/XLSX, a list in JSON. The business's own domain comes first |
| `rating` | 4.8 | |
| `reviews` | 312 | |
| `latitude`, `longitude` | 30.2468, -97.7702 | The listing's map pin |
| `maps_url` | https://www.google.com/maps/place/... | |
| `query` | dentists in Austin TX | The search that found it. Sweeps show `restaurants near Denver CO` |

- **Duplicates:** listings are matched by Maps URL (or by name and address), so
  overlapping searches don't repeat a business. The first query to find a
  business is the one recorded.
- **CSV:** saved as UTF-8 with a byte-order mark, so Excel shows accented
  characters correctly.
- **Excel:** has a bold, frozen header row and sized columns.

## Choosing a backend

| | `browser` (default) | `api` |
|---|---|---|
| How | Headless Chromium drives maps.google.com | Official [Places API (New)](https://developers.google.com/maps/documentation/places/web-service/text-search) |
| Cost | Free | Billed per request, roughly $17–32 per 1,000 results. Check Google's current pricing |
| Speed | ~2 s per listing | Fast |
| Results per query | ~100 (more with `--near`) | 60 maximum |
| Reliability | Breaks when Google changes its page layout; blocked from datacenter IPs | Stable |
| Terms of Service | Against Google's ToS | Allowed |

**Setting up the API backend**

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project
   and turn on billing.
2. Enable **Places API (New)**.
3. Create an API key and restrict it to the Places API. Setting a budget
   alert or quota cap is strongly recommended.
4. Put it in `.env` as `GOOGLE_MAPS_API_KEY=...`, pass `--api-key`, or paste it
   into the web UI.

The API backend doesn't support the wide-area sweep.

## Getting more than ~100 results

**Google stops every search at about 100 listings.** Scroll further and the list
says *"You've reached the end of the list"*: we measured 99 for
`restaurants in Denver CO`. Running the same search again returns the same
listings. This is how Google works, not a bug in the scraper, and more scrolling
won't get past it.

**Each map view gets its own ~100, though.** Wide-area mode splits a square around
a location into a grid, searches each part of the map separately, and merges the
results:

```bash
python scrape.py "restaurants" --near "Denver CO" --grid 3 --radius 10 -n 500
```

In the web UI, tick **Search a wide area**.

That run returned 300 unique Denver restaurants, three times the single-search
limit, and stopped only because it reached `-n 300`.

**Use a bare term:** `restaurants`, not `restaurants in Denver`. If the search
names a place, Google treats it as a text search and returns nearly the same
listings in every part of the grid. The CLI and UI both reject queries containing
" in " when a location is set.

**How the sweep works**

1. The location is looked up on Google Maps to find its centre.
2. A square, 2 × `radius` wide, is split into `grid` × `grid` cells. The
   zoom level is chosen so each map view roughly covers one cell (zoom 11–16).
3. The middle cell is searched first. Each next cell is the one farthest from
   every cell already searched. If the run hits `-n` early, the area is still
   covered evenly rather than just one side of it.
4. Google sometimes adds listings from wherever your IP address is when an area
   has few results. Anything more than 1.5 × `radius` from the centre is thrown out
   as it's collected, so these never count toward `-n`.
5. Each remaining listing is opened for its details.

**Sizing a sweep:** `grid²` searches, each up to ~100 listings, then about
2 seconds per listing. A 3×3 sweep capped at 300 results takes about 10 minutes.
10 km suits a metro area; 3–5 km suits a single town.

Splitting searches by suburb or postcode also works, and can be combined with
everything above:

```
dentists in Round Rock TX
dentists in Cedar Park TX
dentists in 78704
```

## How email finding works

Google Maps never shows email addresses, so they come from each business's
website. For every listing with a website:

1. **Homepage first.** It's fetched with an ordinary browser user-agent.
2. **Contact pages only if needed.** If the homepage has no email, up to
   `--max-pages − 1` pages from the same site are tried. They're picked by the words in their links, in this order:
   *contact, kontakt, impressum, reach-us, get-in-touch, connect, about*. Shorter
   paths come first. The search stops at the first page with an email.
3. **Where it looks on each page:**
   - `mailto:` links
   - visible page text
   - schema.org structured data (`"email"` fields)
   - Cloudflare-protected addresses (`data-cfemail`, `/cdn-cgi/l/email-protection`)
   - simple disguises like `name (at) domain (dot) co (dot) uk`
4. **What gets filtered out:** image filenames that look like emails
   (`logo@2x.png`), website-builder and tracking addresses (Wix, Sentry,
   Squarespace…), placeholder domains (`example.com`), `noreply@` addresses, and
   long hex codes left by build tools.
5. **Ranking.** Addresses on the business's own domain come first, so a web
   designer's footer address doesn't end up as the main contact.
6. **Blocked sites.** Sites that refuse ordinary requests (HTTP 401, 403, 405, 406, 429 or 503)
   get a second try in a real headless browser, which gets into most of them.

Expect emails for roughly **40–60%** of listings that have a website. Some
businesses only offer a contact form, or show their email as an image.

## Deploying for a team

### Read this first: Google blocks datacenter IPs

The `browser` backend works from your laptop because you're on a home internet
connection. From AWS, GCP, Render, Fly, Hetzner or any VPS, Google Maps shows
CAPTCHAs and consent pages to those IP ranges, often within hours. A deployed
copy should use the **API backend** (`DEFAULT_SOURCE=api`). Email lookup works
from anywhere, since it only visits ordinary business websites.

To use the free browser backend for a team, run it on a machine with a home
connection (an office PC, a mini PC). Expose it through a Cloudflare Tunnel
rather than hosting it in a datacenter.

### Run with Docker

```bash
cp .env.example .env
# at minimum:
#   APP_PASSWORD=<shared team password>
#   APP_SECRET=<output of: openssl rand -hex 32>
#   DEFAULT_SOURCE=api
#   GOOGLE_MAPS_API_KEY=<key>
docker compose up -d --build
```

The app runs on port 8000 behind a login page. Put it behind a reverse proxy
with HTTPS (Caddy, nginx, or your platform's built-in HTTPS), then set
`COOKIE_SECURE=true`.

Two safety checks stop you deploying it open to the internet by mistake. The
compose file won't start without `APP_PASSWORD` and `APP_SECRET`. The image sets
`REQUIRE_AUTH=1`, so the server itself also refuses to start without a password.

### Sizing and limits

- **Memory:** allow 2 GB. Each browser job runs its own Chromium (0.5–1 GB).
  512 MB free tiers run out of memory partway through a scrape.
- **One instance only.** Jobs are kept in memory. A second copy of the app, or
  extra uvicorn workers, would answer half the progress checks with "unknown job".
- **Restarts lose jobs.** Running jobs and finished results aren't saved to disk,
  so ask people to download their results when a run finishes.
- **Avoid platforms that sleep idle apps**; they kill jobs partway through.
- **Concurrency:** `MAX_CONCURRENT_JOBS` (default 2) caps how many jobs run at
  once. Extra jobs wait their turn.

### Before giving it to clients

Everyone shares one password. There are no per-user accounts, no audit log and no
rate limits beyond the concurrency cap. That's fine for a small internal team.
If outsiders get access, or a leaked password could run up your Places API bill,
add proper accounts and per-user quotas first.

## Configuration reference

All settings are environment variables, and can also go in `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | – | Places API key used by the `api` backend, so users don't need their own |
| `APP_PASSWORD` | – | Shared web UI password. Leave blank only on localhost |
| `APP_SECRET` | random each boot | Signs login cookies. If unset, everyone is signed out on every restart. Generate with `openssl rand -hex 32` |
| `COOKIE_SECURE` | `false` | Set `true` once served over HTTPS |
| `MAX_CONCURRENT_JOBS` | `2` | Jobs that can run at once; the rest wait |
| `DEFAULT_SOURCE` | `browser` | Backend selected in the UI by default: `browser` or `api` |
| `REQUIRE_AUTH` | unset (`1` in Docker) | Refuse to start the server without `APP_PASSWORD` |

Logins last 7 days.

## HTTP API

The web UI runs on a small JSON API that you can also script against.
Interactive docs are at `/api/docs`. When `APP_PASSWORD` is set, first sign in
with `POST /login` (form field `password`) and send the `gms_session` cookie
it returns with each request.

| Method & path | Purpose |
|---|---|
| `GET /api/config` | Whether a server-side API key exists, whether login is on, the default source, the concurrency cap |
| `POST /api/scrape` | Start a job (JSON body below). Returns `{"job_id", "queries"}` |
| `GET /api/jobs/{id}?since_log=N&since_rows=N` | Progress: `status`, `phase`, log lines and rows added since the given counts, `stats`, `version` |
| `GET /api/jobs/{id}/rows` | Every row, plus `version`. Fetch this again when `version` changes, since emails are filled in after rows first appear |
| `POST /api/jobs/{id}/cancel` | Stop the job and keep its results |
| `GET /api/jobs/{id}/download?fmt=csv\|xlsx\|json` | Download the results |

```bash
curl -X POST http://127.0.0.1:8000/api/scrape \
  -H 'Content-Type: application/json' \
  -d '{"queries": "dentists in Austin TX", "max_results": 20}'
```

Request body fields for `POST /api/scrape`, all optional except `queries`:

| Field | Default | |
|---|---|---|
| `queries` | – | Searches, one per line |
| `max_results` | 50 | 1–2000 |
| `source` | `browser` | `browser` or `api` |
| `near`, `grid`, `radius` | `""`, 3, 10 | Wide-area sweep; grid 1–8, radius 0.5–100 km |
| `api_key` | `""` | Overrides `GOOGLE_MAPS_API_KEY` |
| `find_emails`, `emails_only` | `true`, `false` | |
| `workers`, `max_pages`, `timeout` | 8, 3, 12 | workers 1–32, max_pages 1–10 |
| `headless` | `true` | |

A job's `status` is `running`, `done`, `cancelled` or `error`. Its `phase` is
`queued`, `scraping`, `emails` or `finished`. The server keeps the 20 most recent jobs.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Browser backend returns nothing, or `no results panel` | Google changed its page layout, or is showing a consent page or CAPTCHA. Run with `--no-headless` to see what's happening. The page selectors are at the top of `gmaps_scraper/sources/playwright_source.py` |
| Works on your laptop, fails on a server | Google blocks datacenter IPs. Use `--source api`, or a machine on a home connection |
| `Playwright is not installed` or browser launch errors | Run `pip install -r requirements.txt` then `playwright install chromium` |
| `Places API error 403` | The API isn't enabled, billing is off, or the key is restricted to other APIs |
| Always about 100 results | Google's per-search limit. Use `--near` with a bare term |
| Wide-area sweep returns the same few listings | The query names a place. Use `restaurants`, not `restaurants in Denver` |
| `could not locate '…' on the map` | Make the location more specific, e.g. `Springfield IL` |
| Few emails found | Many small businesses only have contact forms. Try raising `--max-pages` or `--timeout` |
| "Unknown job" in the web UI | The server restarted, which clears all jobs |
| Everyone signed out after a redeploy | Set `APP_SECRET` |
| Container exits with `REQUIRE_AUTH is set but APP_PASSWORD is empty` | Set `APP_PASSWORD` in `.env` |

## Project layout

```
scrape.py                     CLI entry point
run_web.py                    Web UI entry point (local server)
gmaps_scraper/
  cli.py                      Argument parsing, run loop, summary
  models.py                   Business dataclass and column order
  email_finder.py             Website crawl and email extraction
  exporter.py                 CSV / XLSX / JSON writers
  sources/
    playwright_source.py      Browser scraping and wide-area sweep
    places_api.py             Google Places API (New)
webapp/
  server.py                   FastAPI routes
  jobs.py                     Background job runner and progress tracking
  auth.py                     Shared-password login
  static/index.html           The whole frontend, one file
  static/login.html           Login page
Dockerfile, docker-compose.yml
```

Both backends produce `Business` objects one at a time. The CLI and the web job
runner remove duplicates, fill in emails with `email_finder.enrich()`, and
export the results with `exporter.write()`.

## Contributing

Issues and pull requests are welcome.

```bash
git clone https://github.com/Abhisharma08/gmaps-scraper.git
cd gmaps-scraper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
python run_web.py
```

- **Selector fixes** are the most common need, because Google changes the Maps
  page layout from time to time. Please say which country and language you tested
  from; Google serves different markup to different regions.
- **Email extraction** is plain Python with no network access once a page is
  fetched. `email_finder._extract(html)` is easy to test with sample HTML.
- **Playwright version:** the version in `requirements.txt` must match the
  Dockerfile's base image tag. Update both together.
- Keep pull requests focused, and describe how you tested them.

## Responsible use

- **Google's Terms of Service** don't allow scraping Google Maps. The `api`
  backend is the permitted route. If you use `browser`, you do so at your own
  risk, so keep volumes modest.
- **Personal data.** Business emails, especially named people's addresses, are
  personal data under GDPR and similar laws. Sending them unsolicited mail is
  regulated under GDPR, CAN-SPAM, CASL and others. Make sure you have a lawful
  basis and honour opt-outs.
- **Be polite to websites.** The defaults fetch at most a few pages per site.
  Don't raise `--workers` and `--max-pages` far beyond them.

This software is provided as-is, and you're responsible for how you use it.

## License

[MIT](LICENSE) © 2026 Abhisharma08
