"""Structured HTML, table, metadata, link, and JSON-LD extraction using stdlib."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any


@dataclass
class ExtractedPage:
    """Structured content parsed from a single HTML document."""

    url: str
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    headings: list[dict[str, str]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[dict[str, str]]] = field(default_factory=list)
    json_ld: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return asdict(self)


class _StructuredHTMLParser(HTMLParser):
    """Single-pass HTML parser collecting title, meta, headings, links, tables, and JSON-LD."""

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.meta: dict[str, str] = {}
        self.headings: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.tables: list[list[dict[str, str]]] = []
        self.json_ld: list[dict[str, Any]] = []

        self._in_title = False
        self._title_parts: list[str] = []

        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []

        self._in_anchor = False
        self._anchor_href = ""
        self._anchor_parts: list[str] = []

        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

        self._in_table = False
        self._current_rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._in_cell = False
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if tag_l == "title":
            self._in_title = True
            self._title_parts = []
        elif tag_l == "meta":
            key = attr_map.get("name") or attr_map.get("property") or ""
            content = attr_map.get("content", "").strip()
            if key and content:
                self.meta[key] = content
        elif tag_l in {"h1", "h2", "h3"}:
            self._heading_tag = tag_l
            self._heading_parts = []
        elif tag_l == "a":
            href = attr_map.get("href", "").strip()
            if href and not href.startswith(("javascript:", "#")):
                self._in_anchor = True
                self._anchor_href = (
                    urllib.parse.urljoin(self.base_url, href) if self.base_url else href
                )
                self._anchor_parts = []
        elif tag_l == "script" and attr_map.get("type", "").lower().startswith("application/ld+json"):
            self._in_json_ld = True
            self._json_ld_parts = []
        elif tag_l == "table" and not self._in_table:
            self._in_table = True
            self._current_rows = []
        elif self._in_table and tag_l == "tr":
            self._current_row = []
        elif self._in_table and self._current_row is not None and tag_l in {"th", "td"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()

        if tag_l == "title" and self._in_title:
            self._in_title = False
            self.title = _collapse_ws("".join(self._title_parts))
        elif tag_l == self._heading_tag:
            text = _collapse_ws("".join(self._heading_parts))
            if text:
                self.headings.append({"level": tag_l, "text": text})
            self._heading_tag = None
        elif tag_l == "a" and self._in_anchor:
            self._in_anchor = False
            self.links.append({
                "text": _collapse_ws("".join(self._anchor_parts)),
                "href": self._anchor_href,
            })
        elif tag_l == "script" and self._in_json_ld:
            self._in_json_ld = False
            self._append_json_ld("".join(self._json_ld_parts))
        elif self._in_table and tag_l in {"th", "td"} and self._in_cell:
            self._in_cell = False
            if self._current_row is not None:
                self._current_row.append(_collapse_ws("".join(self._cell_parts)))
        elif self._in_table and tag_l == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self._current_rows.append(self._current_row)
            self._current_row = None
        elif self._in_table and tag_l == "table":
            self._in_table = False
            parsed_table = _rows_to_records(self._current_rows)
            if parsed_table:
                self.tables.append(parsed_table)
            self._current_rows = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._heading_tag:
            self._heading_parts.append(data)
        if self._in_anchor:
            self._anchor_parts.append(data)
        if self._in_json_ld:
            self._json_ld_parts.append(data)
        if self._in_cell:
            self._cell_parts.append(data)

    def _append_json_ld(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        _collect_json_ld_objects(payload, self.json_ld)


def _collapse_ws(value: str) -> str:
    return " ".join(value.split())


def _collect_json_ld_objects(payload: Any, dest: list[dict[str, Any]]) -> None:
    if isinstance(payload, list):
        for item in payload:
            _collect_json_ld_objects(item, dest)
    elif isinstance(payload, dict):
        if "@graph" in payload and isinstance(payload["@graph"], list):
            for node in payload["@graph"]:
                if isinstance(node, dict):
                    dest.append(node)
        else:
            dest.append(payload)


def _rows_to_records(rows: list[list[str]]) -> list[dict[str, str]]:
    if len(rows) < 2:
        return []
    raw_headers = rows[0]
    headers = [
        h if h else f"col_{idx + 1}" for idx, h in enumerate(raw_headers)
    ]
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        record: dict[str, str] = {}
        for idx, header in enumerate(headers):
            record[header] = row[idx] if idx < len(row) else ""
        if len(row) > len(headers):
            for extra_idx in range(len(headers), len(row)):
                record[f"col_{extra_idx + 1}"] = row[extra_idx]
        records.append(record)
    return records


def extract_from_html(html_text: str, url: str = "") -> ExtractedPage:
    """Parse an HTML string into structured page data."""
    parser = _StructuredHTMLParser(base_url=url)
    parser.feed(html_text)
    parser.close()
    return ExtractedPage(
        url=url,
        title=parser.title,
        meta=parser.meta,
        headings=parser.headings,
        links=parser.links,
        tables=parser.tables,
        json_ld=parser.json_ld,
    )


def fetch_html(
    url: str,
    timeout: float = 15.0,
    retries: int = 2,
    backoff_seconds: float = 1.0,
    user_agent: str = "DataPipeKit/1.0 (+https://github.com)",
) -> str:
    """Fetch a public HTML/XML URL with polite retries and exponential backoff."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(backoff_seconds * (2 ** attempt))
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")
