#!/usr/bin/env python3
"""
DOI to BibTeX Converter

Converts DOIs to properly formatted BibTeX entries using CrossRef API.

Usage:
    python doi_to_bibtex.py "10.1234/example.doi"
    python doi_to_bibtex.py --file dois.txt --output references.bib
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from typing import Optional

# Per-attempt HTTP deadline (NEURICO_HTTP_TIMEOUT, seconds; 0 = none). A deadline is only
# acceptable because the call is retried: CrossRef gets three attempts with backoff.
_HTTP_TIMEOUT = float(os.environ.get("NEURICO_HTTP_TIMEOUT") or 0) or None
_HTTP_ATTEMPTS = 3


def _urlopen_retrying(request: urllib.request.Request):
    """Open the URL; retry timeouts, connection errors and 429/5xx with backoff. 4xx raises at once."""
    delay = 2.0
    for attempt in range(1, _HTTP_ATTEMPTS + 1):
        try:
            return urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == _HTTP_ATTEMPTS:
                raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == _HTTP_ATTEMPTS:
                raise
        time.sleep(delay)
        delay *= 2


def fetch_crossref_metadata(doi: str) -> Optional[dict]:
    """Fetch metadata from CrossRef API for a given DOI."""
    url = f"https://api.crossref.org/works/{doi}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "citation-manager/1.0 (mailto:research@example.com)"
    }

    try:
        request = urllib.request.Request(url, headers=headers)
        with _urlopen_retrying(request) as response:
            data = json.loads(response.read().decode())
            return data.get("message", {})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"DOI not found: {doi}", file=sys.stderr)
        else:
            print(f"HTTP error {e.code} for DOI {doi}: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error fetching DOI {doi}: {e}", file=sys.stderr)
        return None


def generate_citation_key(metadata: dict) -> str:
    """Generate a citation key from metadata."""
    # Get first author's last name
    authors = metadata.get("author", [])
    if authors:
        author = authors[0]
        last_name = author.get("family", "unknown").lower()
        # Remove special characters
        last_name = re.sub(r'[^a-z]', '', last_name)
    else:
        last_name = "unknown"

    # Get year
    date_parts = metadata.get("published-print", {}).get("date-parts", [[]])
    if not date_parts or not date_parts[0]:
        date_parts = metadata.get("published-online", {}).get("date-parts", [[]])
    if not date_parts or not date_parts[0]:
        date_parts = metadata.get("created", {}).get("date-parts", [[]])

    year = date_parts[0][0] if date_parts and date_parts[0] else "0000"

    # Get keyword from title
    title = metadata.get("title", [""])[0] if metadata.get("title") else ""
    words = re.findall(r'[a-zA-Z]+', title.lower())
    # Skip common words
    skip_words = {'a', 'an', 'the', 'of', 'and', 'or', 'for', 'in', 'on', 'to', 'with', 'is', 'are'}
    keyword = next((w for w in words if w not in skip_words and len(w) > 3), "paper")

    return f"{last_name}{year}{keyword}"


def format_authors(authors: list) -> str:
    """Format author list for BibTeX."""
    formatted = []
    for author in authors:
        family = author.get("family", "")
        given = author.get("given", "")
        if family and given:
            formatted.append(f"{family}, {given}")
        elif family:
            formatted.append(family)
    return " and ".join(formatted)


def metadata_to_bibtex(metadata: dict, doi: str) -> str:
    """Convert CrossRef metadata to BibTeX entry."""
    entry_type = metadata.get("type", "article")

    # Map CrossRef types to BibTeX types
    type_map = {
        "journal-article": "article",
        "proceedings-article": "inproceedings",
        "book": "book",
        "book-chapter": "incollection",
        "posted-content": "misc",  # preprints
    }
    bibtex_type = type_map.get(entry_type, "misc")

    key = generate_citation_key(metadata)
    title = metadata.get("title", [""])[0] if metadata.get("title") else ""
    authors = format_authors(metadata.get("author", []))

    # Get year
    date_parts = metadata.get("published-print", {}).get("date-parts", [[]])
    if not date_parts or not date_parts[0]:
        date_parts = metadata.get("published-online", {}).get("date-parts", [[]])
    year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""

    # Build entry
    lines = [f"@{bibtex_type}{{{key},"]
    lines.append(f"  title     = {{{title}}},")
    lines.append(f"  author    = {{{authors}}},")

    if bibtex_type == "article":
        journal = metadata.get("container-title", [""])[0] if metadata.get("container-title") else ""
        if journal:
            lines.append(f"  journal   = {{{journal}}},")
        if year:
            lines.append(f"  year      = {{{year}}},")
        volume = metadata.get("volume", "")
        if volume:
            lines.append(f"  volume    = {{{volume}}},")
        issue = metadata.get("issue", "")
        if issue:
            lines.append(f"  number    = {{{issue}}},")
        pages = metadata.get("page", "")
        if pages:
            lines.append(f"  pages     = {{{pages}}},")

    elif bibtex_type == "inproceedings":
        booktitle = metadata.get("container-title", [""])[0] if metadata.get("container-title") else ""
        if booktitle:
            lines.append(f"  booktitle = {{{booktitle}}},")
        if year:
            lines.append(f"  year      = {{{year}}},")
        pages = metadata.get("page", "")
        if pages:
            lines.append(f"  pages     = {{{pages}}},")

    else:
        if year:
            lines.append(f"  year      = {{{year}}},")

    lines.append(f"  doi       = {{{doi}}},")
    lines.append("}")

    return "\n".join(lines)


def doi_to_bibtex(doi: str) -> Optional[str]:
    """Convert a single DOI to BibTeX."""
    # Clean DOI
    doi = doi.strip()
    # Remove URL prefix if present
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi)

    metadata = fetch_crossref_metadata(doi)
    if not metadata:
        return None

    return metadata_to_bibtex(metadata, doi)


def main():
    parser = argparse.ArgumentParser(description="Convert DOI to BibTeX")
    parser.add_argument("doi", nargs="?", help="DOI to convert")
    parser.add_argument("--file", "-f", help="File with DOIs (one per line)")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()

    if not args.doi and not args.file:
        parser.print_help()
        sys.exit(1)

    results = []

    if args.doi:
        bibtex = doi_to_bibtex(args.doi)
        if bibtex:
            results.append(bibtex)

    if args.file:
        try:
            with open(args.file, 'r') as f:
                dois = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except FileNotFoundError:
            print(f"File not found: {args.file}", file=sys.stderr)
            sys.exit(1)

        for doi in dois:
            print(f"Processing: {doi}", file=sys.stderr)
            bibtex = doi_to_bibtex(doi)
            if bibtex:
                results.append(bibtex)

    output = "\n\n".join(results)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Written {len(results)} entries to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
