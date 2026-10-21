#!/usr/bin/env python3
"""
Citation Verification Tool

Extracts and verifies citations from markdown documents.
Checks for valid DOIs and finds potential issues.

Usage:
    python verify_citations.py literature_review.md
    python verify_citations.py literature_review.md --check-dois
"""

import argparse
import os
import re
import sys
import urllib.request
import urllib.error
from typing import List, Dict, Tuple, Optional
import time

# Per-attempt HTTP deadline (NEURICO_HTTP_TIMEOUT, seconds; 0 = none). A deadline is only
# acceptable because the call is retried: a slow or flaky resolver gets three attempts with
# backoff before a citation is reported unverified.
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


def extract_citations(content: str) -> List[Dict]:
    """Extract citation-like patterns from markdown content."""
    citations = []

    # Pattern for DOIs
    doi_pattern = re.compile(r'10\.\d{4,}/[^\s\)\]]+')

    # Pattern for arXiv IDs
    arxiv_pattern = re.compile(r'arXiv[:\s]*(\d{4}\.\d{4,5})', re.IGNORECASE)

    # Pattern for URL citations
    url_pattern = re.compile(r'https?://(?:arxiv\.org/abs/|doi\.org/|aclanthology\.org/|papers\.nips\.cc/)([^\s\)]+)')

    # Pattern for inline citations like (Author et al., 2024)
    inline_pattern = re.compile(r'\(([A-Z][a-z]+(?:\s+et\s+al\.)?(?:,?\s+\d{4}))\)')

    # Pattern for paper titles in quotes
    title_pattern = re.compile(r'"([^"]{20,})"')

    # Extract DOIs
    for match in doi_pattern.finditer(content):
        doi = match.group(0).rstrip('.,;:')
        citations.append({
            'type': 'doi',
            'value': doi,
            'position': match.start()
        })

    # Extract arXiv IDs
    for match in arxiv_pattern.finditer(content):
        arxiv_id = match.group(1)
        citations.append({
            'type': 'arxiv',
            'value': arxiv_id,
            'position': match.start()
        })

    # Extract URLs
    for match in url_pattern.finditer(content):
        url = match.group(0)
        citations.append({
            'type': 'url',
            'value': url,
            'position': match.start()
        })

    # Extract inline citations
    for match in inline_pattern.finditer(content):
        citation = match.group(1)
        citations.append({
            'type': 'inline',
            'value': citation,
            'position': match.start()
        })

    return citations


def verify_doi(doi: str) -> Tuple[bool, Optional[str]]:
    """Verify a DOI exists using the doi.org resolver."""
    url = f"https://doi.org/api/handles/{doi}"

    try:
        request = urllib.request.Request(url)
        with _urlopen_retrying(request) as response:
            return True, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "DOI not found"
        return False, f"HTTP error {e.code}"
    except Exception as e:
        return False, str(e)


def verify_arxiv(arxiv_id: str) -> Tuple[bool, Optional[str]]:
    """Verify an arXiv ID exists."""
    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"

    try:
        request = urllib.request.Request(url)
        with _urlopen_retrying(request) as response:
            content = response.read().decode()
            if '<entry>' in content:
                return True, None
            return False, "arXiv ID not found"
    except Exception as e:
        return False, str(e)


def analyze_document(content: str) -> Dict:
    """Analyze a document for citation patterns and potential issues."""
    citations = extract_citations(content)
    lines = content.split('\n')

    analysis = {
        'total_citations': len(citations),
        'by_type': {},
        'issues': [],
        'suggestions': []
    }

    # Count by type
    for citation in citations:
        ctype = citation['type']
        analysis['by_type'][ctype] = analysis['by_type'].get(ctype, 0) + 1

    # Check for common issues

    # Issue: No DOIs found
    if analysis['by_type'].get('doi', 0) == 0:
        analysis['suggestions'].append(
            "No DOIs found. Consider adding DOIs for easier citation management."
        )

    # Issue: Inline citations without corresponding details
    inline_count = analysis['by_type'].get('inline', 0)
    doi_count = analysis['by_type'].get('doi', 0) + analysis['by_type'].get('arxiv', 0)
    if inline_count > doi_count * 2:
        analysis['suggestions'].append(
            f"Found {inline_count} inline citations but only {doi_count} DOIs/arXiv IDs. "
            "Consider adding identifiers for all cited papers."
        )

    # Look for potential duplicate citations
    seen_dois = {}
    for citation in citations:
        if citation['type'] == 'doi':
            doi = citation['value'].lower()
            if doi in seen_dois:
                analysis['issues'].append(f"Duplicate DOI: {doi}")
            seen_dois[doi] = True

    return analysis


def main():
    parser = argparse.ArgumentParser(description="Verify citations in markdown documents")
    parser.add_argument("file", help="Markdown file to analyze")
    parser.add_argument("--check-dois", action="store_true",
                        help="Verify DOIs exist (requires internet)")
    parser.add_argument("--check-arxiv", action="store_true",
                        help="Verify arXiv IDs exist (requires internet)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show all citations found")
    args = parser.parse_args()

    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    citations = extract_citations(content)
    analysis = analyze_document(content)

    print(f"Citation Analysis: {args.file}")
    print("=" * 50)
    print(f"\nTotal citations found: {analysis['total_citations']}")

    print("\nBy type:")
    for ctype, count in sorted(analysis['by_type'].items()):
        print(f"  {ctype}: {count}")

    if args.verbose:
        print("\nAll citations:")
        for citation in citations:
            print(f"  [{citation['type']}] {citation['value']}")

    # Verify DOIs if requested
    if args.check_dois:
        print("\nVerifying DOIs...")
        dois = [c for c in citations if c['type'] == 'doi']
        for citation in dois:
            valid, error = verify_doi(citation['value'])
            status = "OK" if valid else f"FAIL: {error}"
            print(f"  {citation['value']}: {status}")

    # Verify arXiv IDs if requested
    if args.check_arxiv:
        print("\nVerifying arXiv IDs...")
        arxivs = [c for c in citations if c['type'] == 'arxiv']
        for citation in arxivs:
            valid, error = verify_arxiv(citation['value'])
            status = "OK" if valid else f"FAIL: {error}"
            print(f"  {citation['value']}: {status}")

    # Show issues and suggestions
    if analysis['issues']:
        print("\nIssues found:")
        for issue in analysis['issues']:
            print(f"  - {issue}")

    if analysis['suggestions']:
        print("\nSuggestions:")
        for suggestion in analysis['suggestions']:
            print(f"  - {suggestion}")

    print()


if __name__ == "__main__":
    main()
