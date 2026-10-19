#!/usr/bin/env python3
"""
PDF Page Splitter - Splits PDFs into page chunks for reading.

This script splits a PDF into smaller PDF chunks that can be read directly
by Claude (which has native PDF reading capability). This preserves all
formatting, spacing, and layout perfectly.

Usage:
    {{ research_python_path }} pdf_chunker.py \
        <pdf_path> [--pages-per-chunk N] [--output-dir DIR]

Output:
    Creates PDF chunks: <output_dir>/<pdf_name>_chunk_001.pdf, etc.
    Also creates a manifest: <output_dir>/<pdf_name>_manifest.txt

Dependencies:
    uv add --project {{ research_env_dir }} pypdf
"""

import argparse
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    print("Error: pypdf is required.")
    print("Install with: uv add --project {{ research_env_dir }} pypdf")
    exit(1)


def split_pdf(pdf_path: str, pages_per_chunk: int = 1, output_dir: str = None) -> str:
    """
    Split a PDF into chunk PDFs.

    Args:
        pdf_path: Path to the PDF file
        pages_per_chunk: Number of pages per chunk (default: 1)
        output_dir: Output directory (default: <pdf_dir>/pages)

    Returns:
        Path to the manifest file
    """
    pdf_path = Path(pdf_path)

    if output_dir is None:
        output_dir = pdf_path.parent / "pages"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_name = pdf_path.stem

    print(f"Splitting PDF: {pdf_path}")

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)

    print(f"Total pages: {total_pages}")
    print(f"Pages per chunk: {pages_per_chunk}")

    manifest_lines = [
        f"PDF: {pdf_path}",
        f"Total pages: {total_pages}",
        f"Pages per chunk: {pages_per_chunk}",
        "",
        "Chunks:",
    ]

    chunk_num = 0
    for start_idx in range(0, total_pages, pages_per_chunk):
        chunk_num += 1
        end_idx = min(start_idx + pages_per_chunk, total_pages)

        chunk_filename = f"{pdf_name}_chunk_{chunk_num:03d}.pdf"
        chunk_path = output_dir / chunk_filename

        writer = PdfWriter()
        for page_idx in range(start_idx, end_idx):
            writer.add_page(reader.pages[page_idx])

        with open(chunk_path, "wb") as f:
            writer.write(f)

        page_range = f"page {start_idx + 1}" if end_idx == start_idx + 1 else f"pages {start_idx + 1}-{end_idx}"
        manifest_lines.append(f"  {chunk_filename}: {page_range}")

    # Write manifest
    manifest_path = output_dir / f"{pdf_name}_manifest.txt"
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("\n".join(manifest_lines))

    print(f"Created {chunk_num} chunk files in: {output_dir}")
    print(f"Manifest: {manifest_path}")

    return str(manifest_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Split PDF into chunk files for reading"
    )
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument(
        "--pages-per-chunk", type=int, default=1,
        help="Number of pages per chunk (default: 1)"
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory (default: <pdf_dir>/pages)"
    )

    args = parser.parse_args()
    split_pdf(args.pdf_path, args.pages_per_chunk, args.output_dir)
