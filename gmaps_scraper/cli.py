"""Command line entry point for the Google Maps business scraper."""

import argparse
import sys
from typing import Dict, List

from . import email_finder, exporter
from .models import Business


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmaps-scraper",
        description="Scrape business name, address, phone, website and email "
        "from Google Maps search results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  gmaps-scraper "dentists in Austin TX" -n 60 -o dentists.csv
  gmaps-scraper -f queries.txt -n 100 -o leads.xlsx --workers 12
  gmaps-scraper "plumbers in Delhi" --source api --api-key $KEY -o out.csv
  gmaps-scraper "cafes in Berlin" --no-headless        # watch it work
""",
    )
    parser.add_argument("query", nargs="*", help="one or more search queries")
    parser.add_argument(
        "-f",
        "--queries-file",
        help="file with one search query per line (combined with any positional queries)",
    )
    parser.add_argument(
        "-n",
        "--max-results",
        type=int,
        default=50,
        help="max listings per query (default: 50; the API caps at 60)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="results.csv",
        help="output file; .csv, .xlsx or .json (default: results.csv)",
    )
    parser.add_argument(
        "--near",
        metavar="LOCATION",
        help="area sweep: search each QUERY as a bare term (e.g. \"dentists\") "
        "across a grid of map viewports around LOCATION. This is how you get "
        "past Google's ~100-per-search ceiling",
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=3,
        help="with --near: grid is GRID x GRID tiles (default: 3, so 9 searches)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=10.0,
        help="with --near: half-width of the area in km (default: 10, a 20km square)",
    )
    parser.add_argument(
        "-s",
        "--source",
        choices=["browser", "api"],
        default="browser",
        help="browser = Playwright scraping (free); api = Google Places API "
        "(needs a key). Default: browser",
    )
    parser.add_argument(
        "--api-key",
        help="Google Places API key (or set GOOGLE_MAPS_API_KEY)",
    )
    parser.add_argument(
        "--no-emails",
        action="store_true",
        help="skip visiting business websites to look for emails",
    )
    parser.add_argument(
        "--emails-only",
        action="store_true",
        help="drop listings where no email was found",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="parallel website fetches during email lookup (default: 8)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="per-request timeout in seconds for website fetches (default: 12)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="pages per website to check for emails (default: 3)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="show the browser window (browser source only)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="only print the final summary"
    )
    return parser


def collect_queries(args) -> List[str]:
    queries = list(args.query)
    if args.queries_file:
        with open(args.queries_file, encoding="utf-8") as fh:
            queries += [
                line.strip()
                for line in fh
                if line.strip() and not line.startswith("#")
            ]
    # Preserve order while dropping duplicates.
    return list(dict.fromkeys(queries))


def main(argv=None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    log = (lambda *a, **k: None) if args.quiet else print

    queries = collect_queries(args)
    if not queries:
        build_parser().print_help()
        return 1

    if args.near and args.source == "api":
        print("--near is browser-only; the Places API has no viewport sweep.")
        return 1
    if args.near and any(" in " in q for q in queries):
        print(
            "With --near, use a bare term ('dentists', not 'dentists in Denver').\n"
            "Naming a city makes Google repeat the same listings for every tile."
        )
        return 1

    results: Dict[str, Business] = {}

    for query in queries:
        log("\n> {}".format(query))
        try:
            if args.near:
                from .sources import playwright_source

                stream = playwright_source.scrape_area(
                    query,
                    args.near,
                    max_results=args.max_results,
                    grid=args.grid,
                    radius_km=args.radius,
                    headless=not args.no_headless,
                    log=log,
                )
            elif args.source == "api":
                from .sources import places_api

                stream = places_api.scrape(
                    query, args.max_results, api_key=args.api_key, log=log
                )
            else:
                from .sources import playwright_source

                stream = playwright_source.scrape(
                    query,
                    args.max_results,
                    headless=not args.no_headless,
                    log=log,
                )

            for biz in stream:
                results.setdefault(biz.key(), biz)
        except KeyboardInterrupt:
            log("\nInterrupted - writing what we have so far.")
            break

    businesses = list(results.values())
    if not businesses:
        print("No results found.")
        return 1

    if not args.no_emails:
        try:
            email_finder.enrich(
                businesses,
                workers=args.workers,
                log=log,
                timeout=args.timeout,
                max_pages=args.max_pages,
            )
        except KeyboardInterrupt:
            log("\nEmail lookup interrupted - writing what we have so far.")

    if args.emails_only:
        businesses = [b for b in businesses if b.emails]

    path = exporter.write(businesses, args.output)

    with_phone = sum(1 for b in businesses if b.phone)
    with_email = sum(1 for b in businesses if b.emails)
    with_site = sum(1 for b in businesses if b.website)
    print(
        "\nSaved {} businesses to {}\n"
        "  phone:   {}\n"
        "  website: {}\n"
        "  email:   {}".format(
            len(businesses), path, with_phone, with_site, with_email
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
