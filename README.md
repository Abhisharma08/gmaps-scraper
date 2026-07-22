# Google Maps Business Scraper

Pulls business **name, category, address, phone, website, rating, reviews and
coordinates** from Google Maps search results, then visits each business's
website to find **email addresses**. Exports to CSV, XLSX or JSON.

Two interchangeable backends:

| `--source` | How it works | Cost | Limits |
|---|---|---|---|
| `browser` (default) | Headless Chromium drives maps.google.com | Free | Slower (~2s/listing); depends on Google's DOM |
| `api` | Official Google Places API (New) | ~$17–32 / 1000 results | 60 results max per query, needs an API key |

> Google Maps never exposes email addresses. Emails come from the business's own
> website — the homepage first, then contact/about pages if the homepage has none.
> Expect a 40–60% hit rate.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium      # only needed for --source browser
```

For the API backend, copy `.env.example` to `.env` and fill in a key from
Google Cloud (enable *Places API (New)* + billing):

```bash
cp .env.example .env
```

## The web UI (easiest way to use it)

```bash
python run_web.py
```

That starts a local server and opens <http://127.0.0.1:8000> in your browser.
Type your searches (one per line), press **Start scraping**, and watch results
fill in live. When it finishes, download CSV, Excel or JSON with one click.

The page has a **Stop** button that halts mid-run and keeps whatever was found,
an **Advanced** section for the email-crawl settings, and a **Show browser
window** toggle so you can watch Chromium work.

Nothing leaves your machine — the server is local and bound to 127.0.0.1.
Use `python run_web.py --port 9000` to change the port, or `--host 0.0.0.0` to
reach it from another device on your network.

## Usage from the command line

```bash
python scrape.py "dentists in Austin TX" -n 60 -o dentists.csv
```

Multiple queries at once, into a spreadsheet:

```bash
python scrape.py "plumbers in Austin TX" "electricians in Austin TX" -o leads.xlsx
```

From a file of queries (one per line, `#` comments allowed — see
`queries.example.txt`):

```bash
python scrape.py -f queries.txt -n 100 -o leads.xlsx --workers 12
```

Official API instead of scraping:

```bash
python scrape.py "cafes in Berlin" --source api -o cafes.csv
```

Watch the browser work (useful when a selector breaks):

```bash
python scrape.py "gyms in Mumbai" --no-headless -n 10
```

### Options

| Flag | Default | Meaning |
|---|---|---|
| `-n, --max-results` | 50 | Listings per query |
| `-o, --output` | results.csv | Output path; format from the extension (`.csv`/`.xlsx`/`.json`) |
| `-s, --source` | browser | `browser` or `api` |
| `--api-key` | `$GOOGLE_MAPS_API_KEY` | Places API key |
| `-f, --queries-file` | – | File with one query per line |
| `--no-emails` | off | Skip the website email lookup entirely (much faster) |
| `--emails-only` | off | Drop listings where no email was found |
| `--workers` | 8 | Parallel website fetches |
| `--max-pages` | 3 | Pages per website to check for emails |
| `--timeout` | 12 | Per-request timeout, seconds |
| `--no-headless` | off | Show the browser window |
| `-q, --quiet` | off | Only print the final summary |

Results are de-duplicated across queries by Maps URL, so overlapping searches are
safe. `Ctrl-C` mid-run writes whatever has been collected so far.

## Getting more results

Google caps any single search at ~120 listings (60 via the API). To cover a city
properly, split the query by neighbourhood or postcode and let the de-duplication
merge them:

```
dentists in Round Rock TX
dentists in Cedar Park TX
dentists in 78704
```

## Layout

```
scrape.py                  CLI entry point
run_web.py                 web UI entry point
gmaps_scraper/
  cli.py                   argument parsing, run loop, summary
  models.py                Business dataclass + column order
  email_finder.py          website crawl + email extraction
  exporter.py              CSV / XLSX / JSON writers
  sources/
    playwright_source.py   browser scraping
    places_api.py          Google Places API (New)
webapp/
  server.py                FastAPI routes
  jobs.py                  background job runner + progress tracking
  static/index.html        the whole frontend, one file
```

## Notes

- Scraping Google Maps is against Google's Terms of Service. The `api` backend is
  the sanctioned route; use `browser` at your own risk and keep volumes modest.
- Emails harvested this way are personal data. Sending unsolicited mail to them
  is regulated under GDPR, CAN-SPAM and similar laws — make sure you have a
  lawful basis before using the output for outreach.
- If the browser backend suddenly returns nothing, Google likely changed their
  markup. Run with `--no-headless` to see what's happening; the selectors are all
  at the top of `sources/playwright_source.py`.
- Some sites block automated clients outright (HTTP 403). Those get a second pass
  in a real browser, which recovers most of them — but a few block headless
  Chromium too and simply can't be read.
