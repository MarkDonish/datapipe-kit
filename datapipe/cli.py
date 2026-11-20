"""Unified CLI for DataPipe Kit (`extract`, `clean`, `report`, `pipeline`)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cleaner import CleanConfig, clean_records, read_records, write_csv, write_json
from .extractor import extract_from_html, fetch_html
from .reporter import build_html_report


def _load_html_source(source: str) -> tuple[str, str]:
    if source.startswith(("http://", "https://")):
        return fetch_html(source), source
    path = Path(source)
    return path.read_text(encoding="utf-8"), str(path)


def _cmd_extract(args: argparse.Namespace) -> int:
    html_text, label = _load_html_source(args.source)
    page = extract_from_html(html_text, url=label if label.startswith("http") else "")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(page.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Extracted title='{page.title}' tables={len(page.tables)} "
        f"links={len(page.links)} json_ld={len(page.json_ld)} -> {out_path}"
    )
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    records = read_records(Path(args.input))
    cfg = CleanConfig(
        dedupe_by=args.dedupe_by or [],
        required_fields=args.required or [],
        price_fields=args.price_fields or [],
        email_fields=args.email_fields or [],
        url_fields=args.url_fields or [],
        drop_invalid_emails=args.drop_invalid_emails,
    )
    cleaned, stats = clean_records(records, cfg)
    out_path = Path(args.output)
    if out_path.suffix.lower() == ".csv":
        write_csv(cleaned, out_path)
    else:
        write_json(cleaned, out_path)
    print(
        f"Cleaned {stats.input_count} -> {stats.output_count} rows "
        f"(dropped req={stats.dropped_missing_required}, "
        f"dup={stats.dropped_duplicates}, email={stats.dropped_invalid_email}) -> {out_path}"
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    records = read_records(Path(args.input))
    html_doc = build_html_report(records, title=args.title, source_label=args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"Generated HTML report ({len(records)} rows) -> {out_path}")
    return 0


def _cmd_pipeline(args: argparse.Namespace) -> int:
    html_text, label = _load_html_source(args.source)
    page = extract_from_html(html_text, url=label if label.startswith("http") else "")
    if not page.tables:
        raise SystemExit(f"No HTML tables found in {args.source}")
    idx = args.table_index
    if idx < 0 or idx >= len(page.tables):
        raise SystemExit(f"Table index {idx} out of range (found {len(page.tables)} tables)")

    cfg = CleanConfig(
        dedupe_by=args.dedupe_by or [],
        required_fields=args.required or [],
        price_fields=args.price_fields or [],
        email_fields=args.email_fields or [],
        url_fields=args.url_fields or [],
        drop_invalid_emails=args.drop_invalid_emails,
    )
    cleaned, stats = clean_records(page.tables[idx], cfg)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_csv(cleaned, out_dir / "cleaned.csv")
    write_json(cleaned, out_dir / "cleaned.json")
    report_html = build_html_report(
        cleaned,
        title=args.title or page.title or "DataPipe Report",
        source_label=label,
    )
    (out_dir / "report.html").write_text(report_html, encoding="utf-8")
    print(
        f"Pipeline done: {stats.input_count} -> {stats.output_count} rows; "
        f"wrote cleaned.csv, cleaned.json, report.html in {out_dir}"
    )
    return 0


def _add_clean_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dedupe-by", nargs="*", default=[], help="Columns used as deduplication key")
    parser.add_argument("--required", nargs="*", default=[], help="Required non-empty columns")
    parser.add_argument("--price-fields", nargs="*", default=[], help="Currency columns to parse as floats")
    parser.add_argument("--email-fields", nargs="*", default=[], help="Email columns to validate")
    parser.add_argument("--url-fields", nargs="*", default=[], help="URL columns to normalize")
    parser.add_argument("--drop-invalid-emails", action="store_true", help="Drop rows with invalid emails")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datapipe", description="DataPipe Kit CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ext = sub.add_parser("extract", help="Extract tables, links, meta, and JSON-LD from HTML/URL")
    p_ext.add_argument("source", help="Local HTML file path or http(s) URL")
    p_ext.add_argument("-o", "--output", required=True, help="Output JSON file path")
    p_ext.set_defaults(func=_cmd_extract)

    p_clean = sub.add_parser("clean", help="Clean, normalize, and deduplicate CSV/JSON/JSONL records")
    p_clean.add_argument("input", help="Input CSV/JSON/JSONL file path")
    p_clean.add_argument("-o", "--output", required=True, help="Output CSV or JSON file path")
    _add_clean_flags(p_clean)
    p_clean.set_defaults(func=_cmd_clean)

    p_rep = sub.add_parser("report", help="Generate standalone interactive HTML report")
    p_rep.add_argument("input", help="Input CSV/JSON/JSONL file path")
    p_rep.add_argument("-o", "--output", required=True, help="Output HTML file path")
    p_rep.add_argument("--title", default="DataPipe Kit — Dataset Report", help="Report heading")
    p_rep.set_defaults(func=_cmd_report)

    p_pipe = sub.add_parser("pipeline", help="Run extract -> clean -> CSV/JSON/HTML report end-to-end")
    p_pipe.add_argument("source", help="Local HTML file path or http(s) URL")
    p_pipe.add_argument("--out-dir", required=True, help="Output directory for cleaned.csv, cleaned.json, report.html")
    p_pipe.add_argument("--table-index", type=int, default=0, help="Zero-based HTML table index to extract")
    p_pipe.add_argument("--title", default="", help="Custom HTML report title")
    _add_clean_flags(p_pipe)
    p_pipe.set_defaults(func=_cmd_pipeline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
