"""Minimal HTTP viewer for ViFinQA OCR reports (raw OCR only).

Routes:
  /                          index — list reports grouped by ticker → year
  /report/<report_id>        report detail — raw OCR + inline HTML tables

Run:
  .venv_bge/bin/python scripts/viewer.py [--port 8080]

Then open http://localhost:8080/ in your browser.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import _bootstrap  # noqa: F401

from finance_qa.core.paths import (
    CODE_STOCK_PATH,
    FINANCIAL_STATEMENTS_DIR,
    TABLE_METADATA_PATH,
)


STATEMENTS_DIR = FINANCIAL_STATEMENTS_DIR
INDEX_PATH = TABLE_METADATA_PATH

TABLE_PATTERN = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
PAGE_PATTERN = re.compile(r"(={3,}\s*PAGE\s+\d+\s*={3,})", re.IGNORECASE)


# -------- Data loading --------


def load_tables_index() -> dict[str, list[dict]]:
    by_report: dict[str, list[dict]] = defaultdict(list)
    with INDEX_PATH.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            by_report[rec["report_id"]].append(rec)
    for records in by_report.values():
        records.sort(key=lambda r: r["table_pos"])
    return by_report


def load_ticker_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if not CODE_STOCK_PATH.exists():
        return names
    with CODE_STOCK_PATH.open(encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            names[row["Mã CK"].strip()] = row["Tên công ty"].strip()
    return names


def scan_reports() -> list[tuple[str, str, str, Path]]:
    """Return list of (ticker, year, report_id, ocr_path), sorted."""
    results: list[tuple[str, str, str, Path]] = []
    for path in STATEMENTS_DIR.glob("*/*/*/*_extracted.txt"):
        parts = path.relative_to(STATEMENTS_DIR).parts
        # parts = [ticker, year, doc_folder, filename]
        if len(parts) != 4:
            continue
        ticker, year, _, filename = parts
        report_id = filename.removesuffix("_extracted.txt")
        results.append((ticker, year, report_id, path))
    results.sort()
    return results


# -------- Rendering --------


CSS = """
:root {
  --border: #d0d7de;
  --bg: #ffffff;
  --panel: #f6f8fa;
  --muted: #57606a;
  --accent: #0969da;
  --danger: #cf222e;
  --ok: #1a7f37;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, "Segoe UI", "Noto Sans", Roboto, sans-serif;
  background: var(--bg);
  color: #1f2328;
  line-height: 1.5;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.topbar {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  display: flex; align-items: center; gap: 16px;
  position: sticky; top: 0; z-index: 10;
}
.topbar h1 { font-size: 16px; margin: 0; font-weight: 600; }
.topbar .meta { color: var(--muted); font-size: 13px; margin-left: auto; }
.container { display: flex; }
.sidebar {
  width: 320px; border-right: 1px solid var(--border);
  height: calc(100vh - 51px); overflow-y: auto;
  padding: 12px; font-size: 13px;
}
.main {
  flex: 1; padding: 20px 28px;
  height: calc(100vh - 51px); overflow-y: auto;
}
.ticker-group { margin-bottom: 8px; }
.ticker-group > summary {
  cursor: pointer; padding: 4px 6px; font-weight: 600;
  border-radius: 4px;
}
.ticker-group > summary:hover { background: var(--panel); }
.year-group { margin: 4px 0 4px 12px; }
.year-group > summary { cursor: pointer; padding: 2px 6px; color: var(--muted); }
.report-link { display: block; padding: 3px 20px; color: #1f2328; }
.report-link:hover { background: var(--panel); text-decoration: none; }
.report-link.small { font-size: 12px; }
.tbl-list { list-style: none; padding: 0; margin: 0; }
.tbl-list li { padding: 2px 0; }
.tbl-list .badge {
  display: inline-block; min-width: 32px; padding: 0 6px;
  background: var(--panel); border-radius: 3px; margin-right: 6px;
  font-family: monospace; font-size: 11px; color: var(--muted);
}
.page-marker {
  margin: 20px 0 8px; padding: 4px 10px;
  background: #eef4ff; border-left: 3px solid var(--accent);
  font-family: monospace; font-size: 12px; color: var(--muted);
}
pre.ocr-text {
  white-space: pre-wrap; word-wrap: break-word;
  font-family: "SF Mono", "Menlo", monospace; font-size: 13px;
  margin: 0; padding: 0;
}
.raw table { border-collapse: collapse; margin: 10px 0; }
.raw table td, .raw table th { border: 1px solid var(--border); padding: 4px 8px; }
.search {
  padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px;
  width: 100%; margin-bottom: 8px; font-size: 13px;
}
"""


def render_index(reports: list[tuple[str, str, str, Path]], ticker_names: dict[str, str], tables_index: dict[str, list[dict]]) -> str:
    """Render the index page."""
    by_ticker: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for ticker, year, report_id, _ in reports:
        by_ticker[ticker][year].append((report_id, report_id))

    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<title>ViFinQA — Trình xem báo cáo</title>
<style>{CSS}</style>
</head><body>
<div class="topbar">
  <h1>ViFinQA — Trình xem báo cáo</h1>
  <span class="meta">{len(reports):,} báo cáo · {sum(len(v) for v in tables_index.values()):,} bảng</span>
</div>
<div class="main" style="height: auto;">
<p>Chọn mã chứng khoán để duyệt báo cáo. Bảng và text render trực tiếp từ HTML OCR gốc.</p>
""")

    for ticker in sorted(by_ticker):
        name = ticker_names.get(ticker, "")
        parts.append(f'<details class="ticker-group"><summary>{html.escape(ticker)} — <span style="font-weight:400;color:#57606a">{html.escape(name)}</span></summary>')
        for year in sorted(by_ticker[ticker]):
            parts.append(f'<details class="year-group"><summary>{html.escape(year)}</summary>')
            for report_id, label in sorted(by_ticker[ticker][year]):
                n_tables = len(tables_index.get(report_id, []))
                parts.append(
                    f'<a class="report-link small" href="/report/{html.escape(report_id)}">'
                    f'{html.escape(label)} <span style="color:#57606a">({n_tables} bảng)</span></a>'
                )
            parts.append('</details>')
        parts.append('</details>')

    parts.append('</div></body></html>')
    return "".join(parts)


def linkify_page_markers(escaped_text: str) -> str:
    return PAGE_PATTERN.sub(
        lambda m: f'<div class="page-marker">{html.escape(m.group(1).strip())}</div>',
        escaped_text,
    )


def render_report(report_id: str, ocr_path: Path, tables: list[dict]) -> str:
    text = ocr_path.read_text(encoding="utf-8", errors="replace")

    # Split into segments alternating: text, table, text, table, ...
    segments: list[tuple[str, str]] = []  # ("text"|"table", content)
    last = 0
    for m in TABLE_PATTERN.finditer(text):
        if m.start() > last:
            segments.append(("text", text[last:m.start()]))
        segments.append(("table", m.group(0)))
        last = m.end()
    if last < len(text):
        segments.append(("text", text[last:]))

    parts: list[str] = []
    table_pos = 0

    for kind, content in segments:
        if kind == "text":
            escaped = html.escape(content)
            escaped = linkify_page_markers(escaped)
            html_parts = []
            cursor = 0
            for m in re.finditer(r'<div class="page-marker">.*?</div>', escaped):
                pre_text = escaped[cursor:m.start()]
                if pre_text.strip():
                    html_parts.append(f'<pre class="ocr-text">{pre_text}</pre>')
                html_parts.append(m.group(0))
                cursor = m.end()
            if cursor < len(escaped):
                tail = escaped[cursor:]
                if tail.strip():
                    html_parts.append(f'<pre class="ocr-text">{tail}</pre>')
            parts.append("".join(html_parts))
        else:  # table — render raw HTML from OCR as-is
            table_pos += 1
            parts.append(f'<div class="raw" id="tbl-{table_pos}">{content}</div>')

    body_html = "".join(parts)

    # Sidebar: list all tables in this report.
    sidebar_items = []
    for rec in tables:
        preview = rec["header_preview"] or "(rỗng)"
        if len(preview) > 60:
            preview = preview[:60] + "…"
        sidebar_items.append(
            f'<li><a href="#tbl-{rec["table_pos"]}">'
            f'<span class="badge">#{rec["table_pos"]}</span>{html.escape(preview)}</a></li>'
        )
    sidebar_html = f'<ul class="tbl-list">{"".join(sidebar_items)}</ul>' if sidebar_items else '<p>Không có bảng nào.</p>'

    return f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<title>{html.escape(report_id)}</title>
<style>{CSS}</style>
</head><body>
<div class="topbar">
  <a href="/" style="text-decoration:none;color:inherit">← Trang chủ</a>
  <h1>{html.escape(report_id)}</h1>
  <span class="meta">{len(tables)} bảng · OCR gốc</span>
</div>
<div class="container">
  <aside class="sidebar">
    <div style="font-weight:600;margin-bottom:6px">Danh sách bảng</div>
    {sidebar_html}
  </aside>
  <main class="main">
    {body_html}
  </main>
</div>
</body></html>
"""


# -------- HTTP server --------


class ViewerHandler(BaseHTTPRequestHandler):
    reports_index: list[tuple[str, str, str, Path]] = []
    reports_by_id: dict[str, Path] = {}
    tables_index: dict[str, list[dict]] = {}
    ticker_names: dict[str, str] = {}

    def log_message(self, fmt: str, *args) -> None:
        # Quieter logging.
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/" or path == "/index.html":
            body = render_index(self.reports_index, self.ticker_names, self.tables_index)
            self._send_html(body)
            return

        if path.startswith("/report/"):
            report_id = path[len("/report/"):]
            ocr_path = self.reports_by_id.get(report_id)
            if ocr_path is None:
                self._send_html(f"<h1>Not found</h1><p>{html.escape(report_id)}</p>", status=404)
                return
            tables = self.tables_index.get(report_id, [])
            body = render_report(report_id, ocr_path, tables)
            self._send_html(body)
            return

        self._send_html("<h1>Not found</h1>", status=404)

    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print("Loading tables index...")
    ViewerHandler.tables_index = load_tables_index()
    print(f"  {sum(len(v) for v in ViewerHandler.tables_index.values()):,} tables in {len(ViewerHandler.tables_index):,} reports")

    print("Scanning reports...")
    reports = scan_reports()
    ViewerHandler.reports_index = reports
    ViewerHandler.reports_by_id = {rid: path for _, _, rid, path in reports}
    print(f"  {len(reports):,} reports")

    print("Loading ticker names...")
    ViewerHandler.ticker_names = load_ticker_names()
    print(f"  {len(ViewerHandler.ticker_names):,} tickers")

    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    print(f"\nViewer running at http://{args.host}:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
