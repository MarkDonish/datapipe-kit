"""Unit and CLI integration tests for DataPipe Kit."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from datapipe.cleaner import CleanConfig, clean_records, normalize_price, normalize_url, read_records
from datapipe.cli import main
from datapipe.extractor import extract_from_html
from datapipe.reporter import build_html_report

SAMPLE_HTML = Path(__file__).resolve().parent.parent / "examples" / "sample_catalog.html"


class ExtractorTests(unittest.TestCase):
    def test_extracts_title_meta_links_table_and_json_ld(self) -> None:
        html_text = SAMPLE_HTML.read_text(encoding="utf-8")
        page = extract_from_html(html_text, url="https://example.com/catalog/index.html")

        self.assertEqual(page.title, "SaaS Vendor Directory — Q4 Benchmark")
        self.assertIn("description", page.meta)
        self.assertEqual(len(page.tables), 1)
        self.assertEqual(len(page.tables[0]), 6)
        self.assertEqual(page.links[0]["href"], "https://example.com/pricing")
        self.assertEqual(page.json_ld[0]["@type"], "Dataset")


class CleanerTests(unittest.TestCase):
    def test_normalizers_handle_currency_and_urls(self) -> None:
        self.assertEqual(normalize_price("$1,250.50"), 1250.5)
        self.assertEqual(normalize_price("HK$380"), 380.0)
        self.assertIsNone(normalize_price("N/A"))
        self.assertEqual(normalize_url("AcmeCloud.io/"), "https://acmecloud.io/")

    def test_clean_records_dedupes_and_filters_invalid(self) -> None:
        html_text = SAMPLE_HTML.read_text(encoding="utf-8")
        rows = extract_from_html(html_text).tables[0]
        cfg = CleanConfig(
            dedupe_by=["Vendor"],
            required_fields=["Vendor"],
            price_fields=["Monthly Price"],
            email_fields=["Contact Email"],
            url_fields=["Website"],
            drop_invalid_emails=True,
        )
        cleaned, stats = clean_records(rows, cfg)
        self.assertEqual(stats.input_count, 6)
        self.assertEqual(stats.dropped_missing_required, 1)
        self.assertEqual(stats.dropped_invalid_email, 1)
        self.assertEqual(stats.dropped_duplicates, 1)
        self.assertEqual(stats.output_count, 3)
        self.assertEqual(cleaned[0]["Monthly Price"], 1250.0)
        self.assertTrue(cleaned[0]["Contact Email_valid"])


class ReporterAndCliTests(unittest.TestCase):
    def test_report_escapes_script_breakouts(self) -> None:
        doc = build_html_report(
            [{"Name": "<script>alert(1)</script>", "Amount": 42.5}],
            title="Test <Title>",
        )
        self.assertIn("Test &lt;Title&gt;", doc)
        self.assertNotIn("<script>alert(1)</script>", doc)
        self.assertIn("<\\/script>", doc)

    def test_cli_pipeline_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            code = main([
                "pipeline",
                str(SAMPLE_HTML),
                "--out-dir",
                str(out_dir),
                "--required",
                "Vendor",
                "--dedupe-by",
                "Vendor",
                "--price-fields",
                "Monthly Price",
                "--email-fields",
                "Contact Email",
                "--url-fields",
                "Website",
                "--drop-invalid-emails",
            ])
            self.assertEqual(code, 0)
            csv_path = out_dir / "cleaned.csv"
            json_path = out_dir / "cleaned.json"
            html_path = out_dir / "report.html"

            self.assertTrue(csv_path.exists())
            self.assertTrue(json_path.exists())
            self.assertTrue(html_path.exists())

            loaded = read_records(csv_path)
            self.assertEqual(len(loaded), 3)
            with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
                self.assertEqual(rows[1]["Vendor"], "VectorFlow AI")
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 3)
            self.assertIn("PulseMetric", html_path.read_text(encoding="utf-8"))

    def test_python_dash_m_datapipe_entrypoint(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "datapipe", "--help"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("DataPipe Kit CLI", proc.stdout)


if __name__ == "__main__":
    unittest.main()
