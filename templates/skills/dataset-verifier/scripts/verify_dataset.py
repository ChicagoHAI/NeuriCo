#!/usr/bin/env python3
"""
Dataset existence verifier.

Pre-flight check that a dataset id or URL is reachable before download.
Supports HuggingFace Hub, Kaggle, and generic URLs.

Usage:
    python verify_dataset.py <id_or_url>

Output: JSON to stdout with {id, exists, url, error}.
Exit code: 0 if exists, 1 otherwise.
"""

import sys
import json
import re
import argparse


def _resolve_url(identifier: str) -> tuple[str, str, str]:
    """Normalize to (id, web_url, check_url).

    web_url is what the user visits; check_url is what we GET for existence.
    For HuggingFace, check_url uses the API endpoint because some legacy
    canonical dataset names (e.g. 'wikitext') 404 on the web URL but exist
    via the API and through load_dataset().
    """
    s = identifier.strip()

    m = re.match(r"^(?:hf|huggingface)://(?:datasets/)?(.+)$", s)
    if m:
        ds = m.group(1).strip("/")
        return ds, f"https://huggingface.co/datasets/{ds}", f"https://huggingface.co/api/datasets/{ds}"

    m = re.match(r"^kaggle://(.+)$", s)
    if m:
        ds = m.group(1).strip("/")
        web = f"https://www.kaggle.com/datasets/{ds}"
        return ds, web, web

    if s.startswith(("http://", "https://")):
        m = re.search(r"huggingface\.co/datasets/([^?#]+)", s)
        if m:
            slug = m.group(1).rstrip("/")
            return s, s, f"https://huggingface.co/api/datasets/{slug}"
        return s, s, s

    if re.match(r"^[a-zA-Z0-9_\-/]+$", s):
        return s, f"https://huggingface.co/datasets/{s}", f"https://huggingface.co/api/datasets/{s}"

    return s, s, s


def verify(identifier: str) -> dict:
    ds_id, web_url, check_url = _resolve_url(identifier)
    try:
        import httpx
    except ImportError:
        return {"id": ds_id, "exists": False, "url": web_url, "error": "httpx not installed"}

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            with client.stream("GET", check_url) as response:
                status = response.status_code
    except httpx.RequestError as e:
        return {"id": ds_id, "exists": False, "url": web_url, "error": f"network error: {type(e).__name__}"}

    if 200 <= status < 300:
        return {"id": ds_id, "exists": True, "url": web_url, "error": None}
    return {"id": ds_id, "exists": False, "url": web_url, "error": f"HTTP {status}"}


def main():
    parser = argparse.ArgumentParser(description="Verify dataset existence")
    parser.add_argument("identifier", help="Dataset id, hf:// URL, kaggle:// URL, or generic HTTPS URL")
    args = parser.parse_args()

    result = verify(args.identifier)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["exists"] else 1)


if __name__ == "__main__":
    main()
