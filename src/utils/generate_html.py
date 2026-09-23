"""
HTML Generator
Converts REPORT.md + figures into a self-contained styled HTML blog post.

Usage:
    python generate_html.py <workspace_dir>
    python generate_html.py <path/to/REPORT.md>
    python generate_html.py <workspace_dir> --output REPORT.html --title "My Experiment"
"""

import argparse
import base64
import mimetypes
import re
import sys
from datetime import datetime
from pathlib import Path


# Dependency check
def _check_deps():
    missing = []
    try:
        import markdown  # noqa: F401
    except ImportError:
        missing.append("markdown")
    try:
        import pygments  # noqa: F401
    except ImportError:
        missing.append("pygments")
    if missing:
        print(f"[ERROR] Missing dependencies: {', '.join(missing)}")
        print(f"Install with:  pip install {' '.join(missing)}")
        sys.exit(1)

_check_deps()

import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from markdown.extensions.toc import TocExtension
from pygments.formatters import HtmlFormatter


# Figure discovery
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
FIGURE_DIRS = [".", "results", "figures", "paper_draft/figures", "plots", "output"]


def _find_figure(name: str, base: Path) -> Path | None:
    """Resolve an image reference relative to base, checking common figure dirs."""
    candidate = (base / name).resolve()
    if candidate.exists():
        return candidate
    for d in FIGURE_DIRS:
        candidate = (base / d / Path(name).name).resolve()
        if candidate.exists():
            return candidate
    return None


def _embed_image(path: Path) -> str:
    """Return a data URI for the given image file."""
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def _replace_image_refs(md_text: str, base: Path) -> str:
    """Replace file-based image src attributes with base64 data URIs."""
    def replacer(m):
        alt, src = m.group(1), m.group(2)
        if src.startswith("http://") or src.startswith("https://") or src.startswith("data:"):
            return m.group(0)
        resolved = _find_figure(src, base)
        if resolved:
            return f"![{alt}]({_embed_image(resolved)})"
        return m.group(0)  # leave unchanged if not found

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replacer, md_text)


# md -> HTML
def _ensure_blank_line_before_tables(text: str) -> str:
    """Insert a blank line before table rows that aren't already preceded by one.

    The nl2br extension prevents the tables extension from detecting pipe-table
    syntax unless the table block is separated from the preceding text by a blank
    line.  This pre-pass normalises the markdown without touching the source file.
    """
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.startswith("|") and i > 0 and out and out[-1].strip() != "":
            # Only insert if the previous non-empty line is not itself a table row
            prev = out[-1]
            if not prev.startswith("|"):
                out.append("")
        out.append(line)
    return "\n".join(out)


def _convert_markdown(text: str) -> tuple[str, str]:
    """Return (body_html, toc_html)."""
    text = _ensure_blank_line_before_tables(text)
    toc_ext = TocExtension(permalink=True, title="Contents")
    hilite_ext = CodeHiliteExtension(guess_lang=False, linenums=False)
    md = markdown.Markdown(
        extensions=[
            toc_ext,
            hilite_ext,
            FencedCodeExtension(),
            TableExtension(),
            "meta",
            "nl2br",
            "sane_lists",
            "smarty",
        ]
    )
    body = md.convert(text)
    toc = md.toc  # type: ignore[attr-defined]
    return body, toc

# Metadata extraction
def _extract_title(md_text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def _extract_meta(workspace: Path) -> dict:
    """Pull experiment metadata from idea.yaml if present."""
    meta: dict = {}
    idea_path = workspace / ".neurico" / "idea.yaml"
    if not idea_path.exists():
        return meta
    try:
        import yaml
        data = yaml.safe_load(idea_path.read_text())
        if isinstance(data, dict):
            meta["domain"] = data.get("domain", "")
            meta["author"] = data.get("author", "")
    except Exception:
        pass
    return meta


# CSS / HTML template
def _pygments_css() -> str:
    return HtmlFormatter(style="github-dark").get_style_defs(".codehilite")


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    /* ── Reset & tokens ─────────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:        #0f1117;
      --surface:   #1a1d27;
      --border:    #2a2d3e;
      --accent:    #6e7cff;
      --accent2:   #a78bfa;
      --text:      #e2e4f0;
      --muted:     #8b8fa8;
      --code-bg:   #161820;
      --radius:    8px;
      --sidebar-w: 260px;
      --content-w: 780px;
      font-size: 16px;
    }}

    /* ── Layout ─────────────────────────────────────────────────────────── */
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.7;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }}

    .site-header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 0 2rem;
      display: flex;
      align-items: center;
      gap: 1rem;
      height: 56px;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .site-header .logo {{
      font-weight: 700;
      font-size: 1.1rem;
      color: var(--accent);
      letter-spacing: 0.04em;
      text-decoration: none;
    }}
    .site-header .badge {{
      background: color-mix(in srgb, var(--accent) 15%, transparent);
      border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
      color: var(--accent);
      border-radius: 99px;
      padding: 2px 10px;
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}

    .layout {{
      display: flex;
      flex: 1;
      justify-content: center;
      margin: 0 auto;
      width: 100%;
      padding: 2rem 1.5rem;
      gap: 2.5rem;
      align-items: flex-start;
    }}

    /* ── Sidebar TOC ─────────────────────────────────────────────────────── */
    .sidebar {{
      flex: 0 0 var(--sidebar-w);
      width: var(--sidebar-w);
      position: sticky;
      top: 72px;
      max-height: calc(100vh - 80px);
      overflow-y: auto;
      transition: width .2s ease, flex-basis .2s ease;
    }}
    .sidebar.collapsed {{
      flex-basis: 28px;
      width: 28px;
      overflow: hidden;
    }}
    .sidebar-mirror {{
      flex: 0 0 var(--sidebar-w);
      transition: flex-basis .2s ease;
      pointer-events: none;
    }}
    .layout:has(.sidebar.collapsed) .sidebar-mirror {{
      flex-basis: 28px;
    }}
    .sidebar-header {{
      display: flex;
      align-items: center;
      flex-direction: row-reverse;
      justify-content: flex-end;
      gap: 0.5rem;
      margin-bottom: 0.75rem;
    }}
    .sidebar-title {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      white-space: nowrap;
    }}
    .toc-toggle {{
      background: none;
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--muted);
      cursor: pointer;
      width: 22px;
      height: 22px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: color .15s, border-color .15s;
      padding: 0;
      line-height: 1;
    }}
    .toc-toggle:hover {{ color: var(--text); border-color: var(--accent); }}
    .toc-toggle svg {{ transition: transform .2s ease; }}
    .sidebar.collapsed .toc-toggle svg {{ transform: rotate(180deg); }}
    .sidebar-content {{
      transition: opacity .15s ease;
    }}
    .sidebar.collapsed .sidebar-content {{ opacity: 0; pointer-events: none; }}
    .sidebar .toc {{
      font-size: 0.82rem;
      line-height: 1.5;
    }}
    .sidebar .toc ul {{ list-style: none; padding-left: 0.8rem; }}
    .sidebar .toc > ul {{ padding-left: 0; }}
    .sidebar .toc a {{
      color: var(--muted);
      text-decoration: none;
      display: block;
      padding: 2px 0;
      transition: color .15s;
      border-left: 2px solid transparent;
      padding-left: 6px;
    }}
    .sidebar .toc a:hover {{ color: var(--text); border-left-color: var(--accent); }}

    /* ── Article ─────────────────────────────────────────────────────────── */
    .article {{
      min-width: 0;
      flex: 1;
      max-width: var(--content-w);
    }}

    .article-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      margin-bottom: 2rem;
      font-size: 0.82rem;
      color: var(--muted);
      align-items: center;
    }}
    .article-meta .pill {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 99px;
      padding: 3px 10px;
    }}
    .article-meta .pill.domain {{
      border-color: color-mix(in srgb, var(--accent2) 40%, transparent);
      color: var(--accent2);
    }}

    /* ── Typography ──────────────────────────────────────────────────────── */
    .article h1 {{
      font-size: 2rem;
      font-weight: 800;
      line-height: 1.25;
      background: linear-gradient(135deg, #fff 30%, var(--accent2));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 0.5rem;
    }}
    .article h2 {{
      font-size: 1.35rem;
      font-weight: 700;
      color: var(--text);
      margin-top: 2.5rem;
      margin-bottom: 0.75rem;
      padding-bottom: 0.4rem;
      border-bottom: 1px solid var(--border);
    }}
    .article h3 {{
      font-size: 1.05rem;
      font-weight: 600;
      margin-top: 1.75rem;
      margin-bottom: 0.5rem;
      color: var(--accent2);
    }}
    .article h4, .article h5, .article h6 {{
      font-size: 0.95rem;
      font-weight: 600;
      margin-top: 1.25rem;
      margin-bottom: 0.4rem;
      color: var(--muted);
    }}

    /* Anchor permalinks from TocExtension */
    .article .headerlink {{
      color: var(--muted);
      text-decoration: none;
      margin-left: 0.4em;
      font-size: 0.8em;
      opacity: 0;
      transition: opacity .2s;
    }}
    .article :is(h1,h2,h3,h4):hover .headerlink {{ opacity: 1; }}

    .article p {{ margin-bottom: 1rem; }}
    .article a {{ color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }}
    .article a:hover {{ color: var(--accent2); }}

    .article ul, .article ol {{
      margin: 0.5rem 0 1rem 1.5rem;
    }}
    .article li {{ margin-bottom: 0.25rem; }}

    /* ── Code ────────────────────────────────────────────────────────────── */
    .article code {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 5px;
      font-size: 0.88em;
      font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
    }}
    .article pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.1rem 1.25rem;
      overflow-x: auto;
      margin: 1rem 0 1.5rem;
      font-size: 0.85em;
      line-height: 1.6;
    }}
    .article pre code {{
      background: none;
      border: none;
      padding: 0;
      font-size: inherit;
    }}
    .codehilite {{ background: var(--code-bg) !important; border-radius: var(--radius); }}
    {pygments_css}

    /* ── Tables ──────────────────────────────────────────────────────────── */
    .article table {{
      border-collapse: collapse;
      width: 100%;
      margin: 1rem 0 1.5rem;
      font-size: 0.88rem;
      overflow-x: auto;
      display: block;
    }}
    .article th {{
      background: var(--surface);
      color: var(--text);
      font-weight: 600;
      text-align: left;
      padding: 0.6rem 0.9rem;
      border: 1px solid var(--border);
    }}
    .article td {{
      padding: 0.5rem 0.9rem;
      border: 1px solid var(--border);
      vertical-align: top;
    }}
    .article tr:nth-child(even) td {{ background: color-mix(in srgb, var(--surface) 40%, transparent); }}

    /* ── Figures ─────────────────────────────────────────────────────────── */
    .article img {{
      max-width: 100%;
      height: auto;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      display: block;
      margin: 1.25rem auto;
    }}

    /* ── Blockquote ──────────────────────────────────────────────────────── */
    .article blockquote {{
      border-left: 3px solid var(--accent);
      padding: 0.6rem 1.2rem;
      color: var(--muted);
      margin: 1rem 0;
      background: color-mix(in srgb, var(--accent) 6%, transparent);
      border-radius: 0 var(--radius) var(--radius) 0;
    }}

    /* ── HR ──────────────────────────────────────────────────────────────── */
    .article hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 2.5rem 0;
    }}

    /* ── Footer ──────────────────────────────────────────────────────────── */
    footer {{
      text-align: center;
      font-size: 0.78rem;
      color: var(--muted);
      padding: 1.5rem;
      border-top: 1px solid var(--border);
    }}

    /* ── Responsive ──────────────────────────────────────────────────────── */
    @media (max-width: 900px) {{
      .sidebar, .sidebar-mirror {{ display: none; }}
      .layout {{ padding: 1.25rem 1rem; }}
    }}

    /* ── Print ───────────────────────────────────────────────────────────── */
    @media print {{
      :root {{ --bg: #fff; --surface: #f5f5f5; --text: #111; --muted: #555;
               --border: #ddd; --code-bg: #f0f0f0; --accent: #4f46e5; --accent2: #7c3aed; }}
      .site-header, .sidebar, .sidebar-mirror {{ display: none; }}
      .article h1 {{ -webkit-text-fill-color: var(--text); }}
    }}
  </style>
</head>
<body>

<header class="site-header">
  <a class="logo" href="#">NeuriCo</a>
  <span class="badge">Research Report</span>
</header>

<div class="layout">
  <nav class="sidebar" id="toc-sidebar" aria-label="Table of contents">
    <div class="sidebar-header">
      <div class="sidebar-title">On this page</div>
      <button class="toc-toggle" id="toc-toggle" aria-label="Toggle table of contents">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M8 2L4 6L8 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
    <div class="sidebar-content">
      {toc}
    </div>
  </nav>

  <main class="article">
    <div class="article-meta">
      {meta_pills}
    </div>
    {body}
  </main>
  <div class="sidebar-mirror" aria-hidden="true"></div>
</div>

<!----- MathJax for rendering any LaTeX math in the markdown ----------------------------------------->
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@4/tex-mml-chtml.js"></script>
<script>
  (function() {{
    var sidebar = document.getElementById('toc-sidebar');
    var btn = document.getElementById('toc-toggle');
    var STORAGE_KEY = 'toc-collapsed';
    if (localStorage.getItem(STORAGE_KEY) === '1') sidebar.classList.add('collapsed');
    btn.addEventListener('click', function() {{
      var collapsed = sidebar.classList.toggle('collapsed');
      localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
    }});
  }})();
</script>
</body>
</html>
"""


# Main logic
def _build_meta_pills(title: str, workspace: Path, extra_meta: dict, date_str: str) -> str:
    pills = []
    if extra_meta.get("domain"):
        pills.append(f'<span class="pill domain">{extra_meta["domain"]}</span>')
    if extra_meta.get("author"):
        pills.append(f'<span class="pill">{extra_meta["author"]}</span>')
    pills.append(f'<span class="pill">{date_str}</span>')
    if workspace.name:
        pills.append(f'<span class="pill">{workspace.name}</span>')
    return "\n      ".join(pills)


def generate(report_path: Path, output_path: Path | None = None, title_override: str | None = None):
    if report_path.is_dir():
        report_path = report_path / "REPORT.md"

    if not report_path.exists():
        print(f"[ERROR] File not found: {report_path}")
        sys.exit(1)

    workspace = report_path.parent
    md_text = report_path.read_text(encoding="utf-8")

    # Embed images
    md_text = _replace_image_refs(md_text, workspace)

    # Determine title
    title = title_override or _extract_title(md_text, report_path.stem)

    # Remove the leading # heading from body (it renders via h1 in the gradient style)
    # We keep it so TocExtension can still index it; the heading will appear in the HTML.

    # Convert
    body_html, toc_html = _convert_markdown(md_text)

    # Metadata
    extra_meta = _extract_meta(workspace)
    date_str = datetime.now().strftime("%B %d, %Y")
    meta_pills = _build_meta_pills(title, workspace, extra_meta, date_str)

    # Render
    html = _HTML_TEMPLATE.format(
        title=title,
        pygments_css=_pygments_css(),
        toc=toc_html,
        meta_pills=meta_pills,
        body=body_html,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    # Output
    if output_path is None:
        output_path = workspace / "REPORT.html"

    output_path.write_text(html, encoding="utf-8")
    print(f"[OK] Report written to: {output_path}")
    return output_path


# CLI
def main():
    parser = argparse.ArgumentParser(
        description="Convert NeuriCo REPORT.md + figures into a styled HTML blog post.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        help="Path to REPORT.md file or workspace directory containing it",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output HTML file path (default: REPORT.html next to REPORT.md)",
    )
    parser.add_argument(
        "--title", "-t",
        help="Override the page title (default: first H1 in REPORT.md)",
    )
    args = parser.parse_args()

    report_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else None

    generate(report_path, output_path, args.title)


if __name__ == "__main__":
    main()
