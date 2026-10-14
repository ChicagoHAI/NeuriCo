#!/usr/bin/env python3
"""
Paper Finder Helper Script

Calls the paper-finder API if available, otherwise returns graceful fallback.
This script lives in .claude/skills/paper-finder/scripts/ when copied to workspaces.

Usage:
    python .claude/skills/paper-finder/scripts/find_papers.py "query about papers"
    python .claude/skills/paper-finder/scripts/find_papers.py "query" --mode diligent
"""

import sys
import json
import os
import re
import argparse
from datetime import datetime


def find_papers(query: str, mode: str = "fast", url: str = "http://localhost:8000/api/2/rounds"):
    """Call paper-finder API and return formatted results."""
    try:
        import httpx
    except ImportError:
        return {"error": "httpx not installed. Install with: pip install httpx", "fallback": True}

    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(url, json={
                "paper_description": query,
                "operation_mode": mode,
                "read_results_from_cache": True
            })
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        error_type = type(e).__name__
        if "ConnectError" in error_type or "Connection" in str(e):
            return {
                "error": "Paper-finder service not running at localhost:8000",
                "fallback": True,
                "message": "Proceeding with manual search (arXiv, Semantic Scholar, Papers with Code)"
            }
        result = {"error": str(e), "fallback": True}
        # The service explains failures (e.g. an exhausted API key) in the body.
        response = getattr(e, "response", None)
        if response is not None:
            try:
                detail = response.json().get("error") or response.text
            except Exception:
                detail = response.text
            if detail:
                result["detail"] = str(detail)[:500]
                result["message"] = "Proceeding with manual search (arXiv, Semantic Scholar, Papers with Code)"
        return result

    # Format results
    docs = data.get('doc_collection', {}).get('documents', [])
    results = {
        "success": True,
        "total": len(docs),
        "papers": []
    }

    for doc in docs:
        rel = doc.get('relevance_judgement', {}).get('relevance', 0)
        authors = doc.get('authors', [])
        author_str = ', '.join([a.get('name', '') for a in authors])

        results["papers"].append({
            "title": doc.get('title', 'Unknown'),
            "year": doc.get('year'),
            "authors": author_str,
            "url": doc.get('url', ''),
            "relevance": rel,
            "abstract": (doc.get('abstract') or ''),
            "citations": doc.get('citation_count', 0) or 0
        })

    return results


def save_results_jsonl(results, query: str, output_dir: str = "paper_search_results"):
    """Save paper results to a JSONL file, one paper per line."""
    os.makedirs(output_dir, exist_ok=True)

    sanitized = re.sub(r'[^\w\s-]', '', query).strip()
    sanitized = re.sub(r'[\s]+', '_', sanitized)[:80]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{sanitized}_{timestamp}.jsonl"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w') as f:
        for paper in results.get('papers', []):
            f.write(json.dumps(paper) + '\n')

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Find academic papers")
    parser.add_argument("query", help="Paper search query")
    parser.add_argument("--mode", default="fast", choices=["fast", "diligent"],
                        help="Search mode: fast (~30s) or diligent (~3min)")
    parser.add_argument("--url", default="http://localhost:8000/api/2/rounds",
                        help="Paper-finder API URL")
    parser.add_argument("--format", default="json", choices=["text", "json"],
                        help="Output format")
    args = parser.parse_args()

    results = find_papers(args.query, args.mode, args.url)

    if args.format == "json":
        print(json.dumps(results, indent=2))
        filepath = save_results_jsonl(results, args.query)
        print(f"\nResults saved to: {filepath}", file=sys.stderr)
        return

    # Text format
    if results.get("fallback"):
        print(f"Paper-finder unavailable: {results.get('error', 'Unknown error')}")
        print(f"{results.get('message', 'Use manual search instead.')}")
        print()
        print("Manual search sources:")
        print("  - arXiv: https://arxiv.org")
        print("  - Semantic Scholar: https://www.semanticscholar.org")
        print("  - Papers with Code: https://paperswithcode.com")
        sys.exit(1)

    print(f"Found {results['total']} papers")
    print("=" * 70)

    for i, paper in enumerate(results['papers'], 1):
        print(f"\n{i}. {paper['title']}")
        print(f"   Relevance: {paper['relevance']}/3 | Year: {paper['year']} | Citations: {paper['citations']}")
        print(f"   Authors: {paper['authors']}")
        print(f"   URL: {paper['url']}")
        if paper['abstract']:
            print(f"   Abstract: {paper['abstract']}")

    filepath = save_results_jsonl(results, args.query)
    print(f"\nResults saved to: {filepath}")


if __name__ == "__main__":
    main()
