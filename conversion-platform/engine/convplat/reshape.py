"""Reshape engine: turn a received extract (often a printed report saved to Excel) into clean rows.

bronze = every row of the selected sheet, as text, with lineage (file, sheet, row number).
silver = the data rows only, after the spec's steps; every dropped row is kept in an artifacts
         list with the reason it was dropped, so nothing disappears silently.

Implemented components (see .github/skills/conversion-spec/references/components.md):
strip_artifacts (patterns, blank_rows, header_repeats, keep_when), fill_down (as, reset_on,
check_against), rename, select, parse_address (number / direction / street name / USPS suffix / unit). Column names are sanitized on read: '#' -> 'NUM', other
non-alphanumerics removed, blank -> COL<n>, so 'ACCOUNT #' -> ACCOUNTNUM, 'INCODE ACCT' -> INCODEACCT.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .sources import list_sheets, read_grid

PAGE_BREAK = ("\f", "\u240c")          # form feed, or the control picture the de-identified copy stores
SEPARATOR = re.compile(r"^[-=_*.~\s]+$")
FORMULA_ZERO = re.compile(r"^(0|12/30/1899)$")   # helper formulas copied onto blank lines
SPACED_TITLE = re.compile(r"^(?:[A-Z&#]\s){2,}[A-Z&#]?$")
TITLE_WORDS = re.compile(r"(?i)\b(report|page\s*:|print seq|zone\s*:|include\b|run date|as of)")
TOTAL_WORDS = re.compile(r"(?i)\b(total|count|grand|records?\s+printed|end of report)\b|\*{3,}")


def sanitize(headers: list[str]) -> list[str]:
    out, seen = [], Counter()
    for i, h in enumerate(headers, 1):
        n = re.sub(r"[^0-9A-Za-z_]", "", h.replace("#", "NUM"))
        n = n or f"COL{i}"
        if n[0].isdigit():
            n = "C" + n
        seen[n.upper()] += 1
        out.append(n if seen[n.upper()] == 1 else f"{n}_{seen[n.upper()]}")
    return out


def classify_artifact(row: list[str], header_words: set[str]) -> str:
    cells = [c.strip() for c in row if c and c.strip()]
    if not cells:
        return "blank"
    joined = " ".join(cells)
    if any(ch in joined for ch in PAGE_BREAK):
        return "page_break"
    if sum(c.upper() in header_words for c in cells) >= 2:
        return "header_repeat"
    if all(SEPARATOR.match(c) or FORMULA_ZERO.match(c) or re.fullmatch(r"-?\d{6,}", c) for c in cells) and any(SEPARATOR.match(c) for c in cells):
        return "separator"
    if all(FORMULA_ZERO.match(c) for c in cells):
        return "helper_formula_only"
    if any(SPACED_TITLE.match(c) for c in cells) or TITLE_WORDS.search(joined):
        return "report_title"
    if TOTAL_WORDS.search(joined):
        return "footer_or_total"
    return "other"


@dataclass
class ReshapeResult:
    spec_id: str
    target: str
    source_file: str
    sheet: str
    bronze_columns: list[str]
    bronze_rows: list[list[str]]
    silver_columns: list[str]
    silver_rows: list[list[str]]
    silver_row_numbers: list[int]
    artifacts: list[tuple[int, str]] = field(default_factory=list)   # (row number, reason) - no values
    report: dict = field(default_factory=dict)


def run_reshape(spec: dict, landing: str | Path) -> ReshapeResult:
    src = spec["source"]
    path = Path(landing) / src["file"]
    sheets = list_sheets(path)
    sheet = src.get("sheet")
    grid = read_grid(path, sheet, src.get("delimiter", ","), src.get("encoding", "utf-8-sig"))
    h = int(src.get("header_row", 0))
    raw_header = [c.strip() for c in grid[h]]
    cols = sanitize(raw_header)
    body = grid[h + 1:]
    header_words = {c.upper() for c in raw_header if c} | {"ACCOUNT #", "DESCRIPTION", "STATUS", "TABLE", "METER"}

    rows = [list(r) for r in body]
    numbers = list(range(1, len(rows) + 1))          # 1-based data row number = Excel row - header row - 1
    artifacts: list[tuple[int, str]] = []
    checks: dict = {}
    idx = {c.upper(): i for i, c in enumerate(cols)}

    def col(name: str) -> int:
        if name.upper() not in idx:
            raise KeyError(f"{spec['id']}: column {name!r} not in {cols}")
        return idx[name.upper()]

    for step in spec["steps"]:
        (kind, p), = step.items()
        if kind == "strip_artifacts":
            pats = [re.compile(x) for x in p.get("patterns", [])]
            keep = p.get("keep_when")
            kcols = [col(c) for c in keep["columns"]] if keep else []
            krx = re.compile(keep["pattern"]) if keep else None
            new_rows, new_nums = [], []
            for r, n in zip(rows, numbers):
                if keep:
                    is_data = any(krx.match(r[i].strip()) for i in kcols)
                else:
                    blank = not any(c.strip() for c in r)
                    is_data = not (blank and p.get("blank_rows", True)) and not any(rx.search(c) for rx in pats for c in r)
                    if is_data and p.get("header_repeats", True) and sum(c.strip().upper() in header_words for c in r if c.strip()) >= 2:
                        is_data = False
                if is_data:
                    new_rows.append(r)
                    new_nums.append(n)
                else:
                    artifacts.append((n, classify_artifact(r, header_words)))
            rows, numbers = new_rows, new_nums
        elif kind == "fill_down":
            names = p["columns"]
            outs = p.get("as", names)
            reset = col(p["reset_on"]) if p.get("reset_on") else None
            for name, out in zip(names, outs):
                ci = col(name)
                if out.upper() not in idx:
                    cols.append(out)
                    idx[out.upper()] = len(cols) - 1
                    for r in rows:
                        r.append("")
                oi = idx[out.upper()]
                last, last_reset = "", None
                for r in rows:
                    if reset is not None and r[reset] != last_reset:
                        last, last_reset = "", r[reset]
                    if r[ci].strip():
                        last = r[ci]
                    r[oi] = last
            for out, chk in zip(outs, p.get("check_against", [])):
                oi, ki = idx[out.upper()], col(chk)
                bad = [n for r, n in zip(rows, numbers) if r[oi].strip() != r[ki].strip()]
                checks[f"{out} vs {chk}"] = {"rows": len(rows), "mismatches": len(bad), "first_mismatch_rows": bad[:10]}
        elif kind == "rename":
            for old, new in p.items():
                i = col(old)
                del idx[old.upper()]
                cols[i] = new
                idx[new.upper()] = i
        elif kind == "select":
            keep_i = [col(c) for c in p]
            cols = [cols[i] for i in keep_i]
            rows = [[r[i] for i in keep_i] for r in rows]
            idx = {c.upper(): i for i, c in enumerate(cols)}
        elif kind == "parse_address":
            from .address import parse_street
            ci, prefix = col(p["column"]), p.get("prefix", p["column"] + "_")
            parts = ["number", "predir", "name", "suffix", "postdir", "unit"]
            for part in parts:
                cols.append(f"{prefix}{part.upper()}")
                idx[cols[-1].upper()] = len(cols) - 1
            for r in rows:
                parsed = parse_street(r[ci])
                r.extend(parsed[part] for part in parts)
        else:
            raise NotImplementedError(f"{spec['id']}: reshape component {kind!r} runs in the gold SQL for now")

    bronze_cols = sanitize(raw_header)
    report = {
        "spec": spec["id"], "file": src["file"], "sheet": sheet if sheet is not None else (sheets[0][0] if sheets else ""),
        "sheets_in_file": [{"sheet": s, "rows": r, "cols": c, "used": (s == sheet) or (sheet is None and i == 0)} for i, (s, r, c) in enumerate(sheets)],
        "rows_read": len(body), "rows_kept": len(rows), "artifacts": dict(Counter(a[1] for a in artifacts)),
        "fill_down_checks": checks, "target": spec["target"],
    }
    exp = spec.get("expect", {})
    if "min_rows" in exp:
        report["expect_min_rows_ok"] = len(rows) >= exp["min_rows"]
    if "max_rows" in exp:
        report["expect_max_rows_ok"] = len(rows) <= exp["max_rows"]
    return ReshapeResult(spec["id"], spec["target"], src["file"], report["sheet"], bronze_cols,
                         [list(r[:len(bronze_cols)]) for r in body], cols, rows, numbers, artifacts, report)


def to_columns(columns: list[str], rows: list[list[str]], numbers: list[int], take_id: str, source_file: str, sheet: str) -> dict:
    """Column-oriented dict (for polars / SQL bulk load) with lineage columns first."""
    data = {"_take_id": [take_id] * len(rows), "_source_file": [source_file] * len(rows),
            "_sheet": [sheet or ""] * len(rows), "_row": numbers}
    for i, c in enumerate(columns):
        data[c] = [r[i] if i < len(r) else "" for r in rows]
    return data
