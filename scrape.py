#!/usr/bin/env python3
"""Convenience wrapper: python scrape.py "dentists in Austin TX" -o out.csv"""

import sys

from gmaps_scraper.cli import main

if __name__ == "__main__":
    sys.exit(main())
