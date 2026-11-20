"""DataPipe Kit: Zero-dependency extraction, cleaning, and HTML reporting."""

from .cleaner import CleanConfig, CleanStats, clean_records, read_records, write_csv, write_json
from .extractor import ExtractedPage, extract_from_html, fetch_html
from .reporter import build_html_report

__all__ = [
    "CleanConfig",
    "CleanStats",
    "ExtractedPage",
    "build_html_report",
    "clean_records",
    "extract_from_html",
    "fetch_html",
    "read_records",
    "write_csv",
    "write_json",
]

__version__ = "1.0.0"
