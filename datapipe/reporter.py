"""Self-contained interactive HTML report generator with search, sort, and CSV export."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any


def build_html_report(
    records: list[dict[str, Any]],
    title: str = "DataPipe Kit — Dataset Report",
    source_label: str = "Local Pipeline",
) -> str:
    """Render a standalone, interactive HTML report for tabular records."""
    columns: list[str] = []
    seen: set[str] = set()
    for row in records:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)

    numeric_cols = _detect_numeric_columns(records, columns)
    stats = _compute_summary(records, columns, numeric_cols)

    safe_title = html.escape(title)
    safe_source = html.escape(source_label)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = json.dumps(
        {"columns": columns, "rows": records, "numericCols": numeric_cols},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    kpi_cards = _render_kpi_cards(len(records), len(columns), stats)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{safe_title}</title>
  <style>
    :root {{
      --bg: #0b0f17;
      --panel: #131a26;
      --border: #233046;
      --text: #e6edf7;
      --muted: #8b9bb4;
      --accent: #38bdf8;
      --accent-soft: rgba(56, 189, 248, 0.14);
      --ok: #34d399;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 28px;
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-end;
      gap: 16px;
      margin-bottom: 24px;
    }}
    h1 {{ margin: 0; font-size: 1.65rem; letter-spacing: -0.02em; }}
    .meta {{ color: var(--muted); font-size: 0.875rem; margin-top: 4px; }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }}
    input[type="search"] {{
      background: var(--panel);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 8px;
      min-width: 260px;
      font-size: 0.92rem;
      outline: none;
    }}
    input[type="search"]:focus {{ border-color: var(--accent); }}
    button {{
      background: var(--accent);
      color: #06131f;
      font-weight: 600;
      border: none;
      padding: 10px 16px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.9rem;
    }}
    button:hover {{ opacity: 0.92; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 14px;
      margin-bottom: 22px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
    }}
    .kpi .label {{ color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .kpi .val {{ font-size: 1.45rem; font-weight: 700; margin-top: 4px; color: var(--text); }}
    .table-box {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: auto;
      max-height: 68vh;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    thead th {{
      position: sticky;
      top: 0;
      background: #172030;
      color: var(--muted);
      text-align: left;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}
    thead th:hover {{ color: var(--accent); }}
    tbody td {{
      padding: 11px 14px;
      border-bottom: 1px solid rgba(35, 48, 70, 0.55);
      vertical-align: top;
      max-width: 360px;
      word-break: break-word;
    }}
    tbody tr:hover {{ background: var(--accent-soft); }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.78rem;
      background: rgba(52, 211, 153, 0.14);
      color: var(--ok);
    }}
    .empty {{ padding: 36px; text-align: center; color: var(--muted); }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>{safe_title}</h1>
        <div class="meta">Source: {safe_source} · Generated: {generated_at} · <span id="matchCount">{len(records)}</span> rows shown</div>
      </div>
      <div class="controls">
        <input id="searchBox" type="search" placeholder="Filter rows across all columns..." />
        <button id="exportBtn" type="button">Download Filtered CSV</button>
      </div>
    </header>
    <section class="kpis">{kpi_cards}</section>
    <section class="table-box">
      <table>
        <thead><tr id="headRow"></tr></thead>
        <tbody id="bodyRows"></tbody>
      </table>
      <div id="emptyMsg" class="empty" style="display:none;">No matching records.</div>
    </section>
  </div>
  <script>
    const DATA = {payload};
    let sortCol = null;
    let sortAsc = true;
    let filtered = [...DATA.rows];

    const headRow = document.getElementById("headRow");
    const bodyRows = document.getElementById("bodyRows");
    const searchBox = document.getElementById("searchBox");
    const matchCount = document.getElementById("matchCount");
    const emptyMsg = document.getElementById("emptyMsg");

    function esc(v) {{
      return String(v ?? "").replace(/[&<>"']/g, (ch) => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }}[ch]));
    }}

    function renderHead() {{
      headRow.innerHTML = DATA.columns.map((col) => {{
        const arrow = sortCol === col ? (sortAsc ? " ▲" : " ▼") : "";
        return `<th data-col="${{esc(col)}}">${{esc(col)}}${{arrow}}</th>`;
      }}).join("");
      headRow.querySelectorAll("th").forEach((th) => {{
        th.addEventListener("click", () => {{
          const col = th.dataset.col;
          if (sortCol === col) sortAsc = !sortAsc;
          else {{ sortCol = col; sortAsc = true; }}
          applyFilterAndSort();
        }});
      }});
    }}

    function renderBody() {{
      matchCount.textContent = String(filtered.length);
      if (!filtered.length || !DATA.columns.length) {{
        bodyRows.innerHTML = "";
        emptyMsg.style.display = "block";
        return;
      }}
      emptyMsg.style.display = "none";
      bodyRows.innerHTML = filtered.map((row) => {{
        const cells = DATA.columns.map((col) => {{
          const val = row[col];
          if (typeof val === "boolean") {{
            return `<td><span class="badge">${{val ? "true" : "false"}}</span></td>`;
          }}
          return `<td>${{esc(val)}}</td>`;
        }}).join("");
        return `<tr>${{cells}}</tr>`;
      }}).join("");
    }}

    function applyFilterAndSort() {{
      const q = searchBox.value.trim().toLowerCase();
      filtered = DATA.rows.filter((row) => {{
        if (!q) return true;
        return DATA.columns.some((col) => String(row[col] ?? "").toLowerCase().includes(q));
      }});
      if (sortCol) {{
        const isNum = DATA.numericCols.includes(sortCol);
        filtered.sort((a, b) => {{
          const va = a[sortCol] ?? "";
          const vb = b[sortCol] ?? "";
          if (isNum) {{
            const diff = (Number(va) || 0) - (Number(vb) || 0);
            return sortAsc ? diff : -diff;
          }}
          return sortAsc
            ? String(va).localeCompare(String(vb))
            : String(vb).localeCompare(String(va));
        }});
      }}
      renderHead();
      renderBody();
    }}

    document.getElementById("exportBtn").addEventListener("click", () => {{
      const lines = [DATA.columns.map((c) => `"${{String(c).replace(/"/g, '""')}}"`).join(",")];
      for (const row of filtered) {{
        lines.push(DATA.columns.map((c) => `"${{String(row[c] ?? "").replace(/"/g, '""')}}"`).join(","));
      }}
      const blob = new Blob(["\\uFEFF" + lines.join("\\r\\n")], {{ type: "text/csv;charset=utf-8;" }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "filtered_report.csv";
      a.click();
      URL.revokeObjectURL(url);
    }});

    searchBox.addEventListener("input", applyFilterAndSort);
    applyFilterAndSort();
  </script>
</body>
</html>
"""


def _detect_numeric_columns(records: list[dict[str, Any]], columns: list[str]) -> list[str]:
    numeric: list[str] = []
    for col in columns:
        vals = [r.get(col) for r in records if r.get(col) not in (None, "")]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            numeric.append(col)
    return numeric


def _compute_summary(
    records: list[dict[str, Any]],
    columns: list[str],
    numeric_cols: list[str],
) -> list[tuple[str, str]]:
    summary: list[tuple[str, str]] = []
    if numeric_cols:
        col = numeric_cols[0]
        nums = [float(r[col]) for r in records if isinstance(r.get(col), (int, float))]
        if nums:
            summary.append((f"Total {col}", f"{sum(nums):,.2f}"))
            summary.append((f"Avg {col}", f"{(sum(nums) / len(nums)):,.2f}"))
    if columns:
        first_col = columns[0]
        uniq = {str(r.get(first_col, "")).strip() for r in records if r.get(first_col)}
        summary.append((f"Unique {first_col}", str(len(uniq))))
    return summary


def _render_kpi_cards(row_count: int, col_count: int, extra: list[tuple[str, str]]) -> str:
    cards = [
        ("Total Records", str(row_count)),
        ("Fields / Columns", str(col_count)),
        *extra,
    ]
    return "\n".join(
        f'<div class="kpi"><div class="label">{html.escape(k)}</div>'
        f'<div class="val">{html.escape(v)}</div></div>'
        for k, v in cards
    )
