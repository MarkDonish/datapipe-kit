"""Record cleaning, normalization, deduplication, and CSV/JSON export."""

from __future__ import annotations

import csv
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PRICE_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


@dataclass
class CleanConfig:
    """Rules controlling how tabular records are cleaned and deduplicated."""

    dedupe_by: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    price_fields: list[str] = field(default_factory=list)
    email_fields: list[str] = field(default_factory=list)
    url_fields: list[str] = field(default_factory=list)
    drop_invalid_emails: bool = False


@dataclass
class CleanStats:
    """Audit metrics emitted for every cleaning run."""

    input_count: int
    output_count: int
    dropped_missing_required: int
    dropped_duplicates: int
    dropped_invalid_email: int


def normalize_whitespace(value: Any) -> str:
    """Convert any scalar value to a whitespace-collapsed string."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def normalize_price(value: Any) -> float | None:
    """Extract numeric float from currency strings like '$1,299.50' or 'HK$380'."""
    text = normalize_whitespace(value)
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def normalize_email(value: Any) -> tuple[str, bool]:
    """Normalize email casing/spacing and report regex validity."""
    email = normalize_whitespace(value).lower()
    if not email:
        return "", False
    return email, bool(_EMAIL_RE.match(email))


def normalize_url(value: Any) -> str:
    """Normalize HTTP/HTTPS URL strings, adding https:// when scheme is omitted."""
    raw = normalize_whitespace(value)
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if not parsed.scheme and "." in raw and " " not in raw:
        parsed = urllib.parse.urlsplit(f"https://{raw}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw
    clean_path = parsed.path or "/"
    return urllib.parse.urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        clean_path.rstrip("/") or "/",
        parsed.query,
        "",
    ))


def clean_records(
    records: list[dict[str, Any]],
    config: CleanConfig | None = None,
) -> tuple[list[dict[str, Any]], CleanStats]:
    """Normalize, validate, and deduplicate a list of flat dictionaries."""
    cfg = config or CleanConfig()
    seen_keys: set[tuple[str, ...]] = set()
    cleaned: list[dict[str, Any]] = []
    dropped_req = 0
    dropped_dup = 0
    dropped_email = 0

    for row in records:
        item = {
            str(k).strip(): normalize_whitespace(v) if not isinstance(v, (int, float, bool)) else v
            for k, v in row.items()
        }

        if any(normalize_whitespace(item.get(req, "")) == "" for req in cfg.required_fields):
            dropped_req += 1
            continue

        invalid_email = False
        for ef in cfg.email_fields:
            if ef in item and normalize_whitespace(item[ef]) != "":
                norm_email, ok = normalize_email(item[ef])
                item[ef] = norm_email
                if not ok:
                    invalid_email = True
                    item[f"{ef}_valid"] = False
                else:
                    item[f"{ef}_valid"] = True
        if invalid_email and cfg.drop_invalid_emails:
            dropped_email += 1
            continue

        for pf in cfg.price_fields:
            if pf in item:
                parsed_price = normalize_price(item[pf])
                if parsed_price is not None:
                    item[pf] = parsed_price

        for uf in cfg.url_fields:
            if uf in item:
                item[uf] = normalize_url(item[uf])

        if cfg.dedupe_by:
            key = tuple(normalize_whitespace(item.get(field, "")).lower() for field in cfg.dedupe_by)
            if any(key) and key in seen_keys:
                dropped_dup += 1
                continue
            seen_keys.add(key)

        cleaned.append(item)

    stats = CleanStats(
        input_count=len(records),
        output_count=len(cleaned),
        dropped_missing_required=dropped_req,
        dropped_duplicates=dropped_dup,
        dropped_invalid_email=dropped_email,
    )
    return cleaned, stats


def read_records(path: Path) -> list[dict[str, Any]]:
    """Load records from JSON, JSONL, or CSV files."""
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, list):
            return [dict(r) for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict) and "tables" in payload and payload["tables"]:
            return [dict(r) for r in payload["tables"][0]]
        raise ValueError(f"Unsupported JSON root structure in {path}")
    if suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    raise ValueError(f"Unsupported input format: {path.suffix}")


def write_csv(records: list[dict[str, Any]], path: Path, excel_bom: bool = True) -> None:
    """Write normalized records to CSV (with optional UTF-8 BOM for Excel compatibility)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in records:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    encoding = "utf-8-sig" if excel_bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_json(records: list[dict[str, Any]], path: Path) -> None:
    """Write normalized records to formatted UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
