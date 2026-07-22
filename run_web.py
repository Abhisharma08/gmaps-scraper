#!/usr/bin/env python3
"""Start the local web UI:  python run_web.py  ->  http://127.0.0.1:8000"""

import argparse
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Maps Scraper web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="don't open a tab")
    args = parser.parse_args()

    url = "http://{}:{}".format(
        "127.0.0.1" if args.host in ("0.0.0.0", "127.0.0.1") else args.host, args.port
    )
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print("\n  Google Maps Scraper UI -> {}\n  Ctrl-C to stop.\n".format(url))

    import uvicorn

    uvicorn.run("webapp.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
