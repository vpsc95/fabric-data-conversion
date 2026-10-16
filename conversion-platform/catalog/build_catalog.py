#!/usr/bin/env python3
"""
build_catalog.py: build the UM* target catalog from the mapping templates' "Field Info" sheets.

The templates are rights-protected Excel files, so export them first with
export_templates.ps1 (it opens each workbook through Excel under your identity and
writes the Field Info sheet plus the staging-layout header row as CSV). Then:

  python build_catalog.py --src <export folder>/sample --set sample --out cogsdale-csm-gp/catalog.sample.json

Output: a JSON list with one entry per staging field. lint_spec.py --catalog reads
module/field/length/required; the loader and the mapping agent use the rest:
  module, variant, template, field (staging column / Friendly Name), gp_field, gp_type,
  length, storage_length, required, required_raw, description, notes, source_system,
  source_table, source_field, source_type, source_length, cleansing_rule,
  transformation_rule, remarks, sc_param (the CSM procedure parameter from "SC Node"),
  layout_position (column position in the staging layout sheet)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

HEADER_KEYS = {
    "required_raw": r"required",
    "field": r"friendly\s*name",
    "description": r"^\s*description",
    "gp_field": r"gp\s*field\s*name",
    "notes": r"^\s*notes",
    "gp_type": r"gp\s*field\s*type",
    "length": r"gp\s*field\s*length",
    "storage_length": r"storage\s*length",
    "source_system": r"source\s*system",
    "source_table": r"source\s*table",
    "source_field": r"source\s*field",
    "source_type": r"source\s*type",
    "source_length": r"source\s*length",
    "cleansing_rule": r"cleansing",
    "transformation_rule": r"transformation",
    "remarks": r"remarks",
    "sc_param": r"sc\s*node",
}


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def to_int(s: str):
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None


def parse_template(fieldinfo: Path, layout: Path | None, set_name: str):
    name = fieldinfo.name.replace(".fieldinfo.csv", "")
    m = re.match(r"([A-Z]{2,}[A-Z0-9]*)\s+(.*)$", name)
    module, title = (m.group(1), m.group(2)) if m else (name, name)
    variant = None
    vm = re.search(r"\(CSM\)\s*(.+)$|\b(OESP)\b", title)
    if vm:
        variant = clean(vm.group(1) or vm.group(2)) or None

    rows = list(csv.reader(fieldinfo.open(encoding="utf-8")))
    hdr_idx = next(i for i, r in enumerate(rows) if sum(1 for c in r if clean(c)) >= 6)
    header = [clean(c).lower() for c in rows[hdr_idx]]
    col = {}
    for key, rx in HEADER_KEYS.items():
        for j, h in enumerate(header):
            if re.search(rx, h, re.I) and j not in col.values():
                col[key] = j
                break
    missing = [k for k in ("field", "required_raw", "length") if k not in col]
    if missing:
        sys.exit(f"{fieldinfo.name}: header columns not found: {missing}")

    layout_cols = []
    if layout and layout.exists():
        layout_cols = [clean(c) for c in next(csv.reader(layout.open(encoding="utf-8")), [])]

    out = []
    for r in rows[hdr_idx + 1:]:
        def get(k):
            return clean(r[col[k]]) if k in col and col[k] < len(r) else ""
        field = get("field")
        if not field or field.lower() == "friendly name":
            continue
        req_raw = get("required_raw")
        out.append({
            "set": set_name,
            "module": module,
            "variant": variant,
            "template": name,
            "field": field,
            "gp_field": get("gp_field"),
            "gp_type": get("gp_type"),
            "length": to_int(get("length")),
            "storage_length": to_int(get("storage_length")),
            "required": req_raw.upper().startswith("Y"),
            "required_raw": req_raw,
            "description": get("description"),
            "notes": get("notes"),
            "source_system": get("source_system"),
            "source_table": get("source_table"),
            "source_field": get("source_field"),
            "source_type": get("source_type"),
            "source_length": get("source_length"),
            "cleansing_rule": get("cleansing_rule"),
            "transformation_rule": get("transformation_rule"),
            "remarks": get("remarks"),
            "sc_param": get("sc_param"),
            "layout_position": (layout_cols.index(field) + 1) if field in layout_cols else None,
        })
    extra_layout = [c for c in layout_cols if c and c not in {e["field"] for e in out}]
    return module, variant, out, extra_layout


def parse_staging_columns(sql_dir: Path, table_map: dict) -> dict:
    """Return {module: [columns]} from the INSERT INTO <table> (...) lists in staging scripts."""
    found = {}
    for f in sorted(sql_dir.glob("*.sql")):
        text = f.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"--[^\n]*", "", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for m in re.finditer(r"INSERT\s+INTO\s+([\w.\[\]]+)\s*\(", text, re.I):
            table = m.group(1).replace("[", "").replace("]", "").split(".")[-1]
            module = table_map.get(table.upper())
            if not module:
                continue
            depth, i = 1, m.end()
            while i < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[i], 0)
                i += 1
            cols = [c.strip().strip("[]").strip() for c in text[m.end():i - 1].split(",")]
            cols = [c for c in cols if re.fullmatch(r"[A-Za-z_#][\w#]*", c)]
            found.setdefault(module, [])
            for c in cols:
                if c.lower() not in {x.lower() for x in found[module]}:
                    found[module].append(c)
    return found


DEFAULT_TABLE_MAP = {
    "UM_CUSTOMER": "UMRM0101", "UM_LOCATIONS": "UM00600", "UM_EQUIPMENT": "UM00400",
    "UM_CONNECTIONS": "UM00300", "UM_BEGBALANCES": "UM20400", "UM_DEPOSITS": "UM01900",
    "UM_HISTMR": "UM30300",
}


def merge_staging(catalog: list, staging: dict, set_name: str) -> list:
    """Flag template fields that exist in the staging table and add staging-only columns."""
    for e in catalog:
        cols = staging.get(e["module"])
        e["in_template"] = True
        e["in_staging_table"] = None if cols is None else e["field"].lower() in {c.lower() for c in cols}
    for module, cols in staging.items():
        known = {e["field"].lower() for e in catalog if e["module"] == module}
        for pos, c in enumerate(cols, 1):
            if c.lower() in known:
                continue
            catalog.append({
                "set": set_name, "module": module, "variant": None, "template": None, "field": c,
                "gp_field": "", "gp_type": "", "length": None, "storage_length": None,
                "required": False, "required_raw": "", "description": "", "notes": "",
                "source_system": "", "source_table": "", "source_field": "", "source_type": "",
                "source_length": "", "cleansing_rule": "", "transformation_rule": "", "remarks": "",
                "sc_param": "", "layout_position": None, "in_template": False, "in_staging_table": True,
                "catalog_note": "Column exists in the COGS_STAGING table (staging script INSERT list) "
                                "but not in the mapping template.",
            })
    return catalog


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="folder with *.fieldinfo.csv and *.layout.csv exports")
    ap.add_argument("--set", required=True, help="template set name, e.g. sample or sample")
    ap.add_argument("--out", required=True)
    ap.add_argument("--staging-sql", help="folder of staging scripts whose INSERT INTO lists show the real "
                                          "COGS_STAGING columns (use a PII-redacted copy)")
    a = ap.parse_args(argv)

    src = Path(a.src)
    catalog, summary = [], []
    for fi in sorted(src.glob("*.fieldinfo.csv")):
        layout = fi.with_name(fi.name.replace(".fieldinfo.csv", ".layout.csv"))
        _module, _variant, entries, extra = parse_template(fi, layout, a.set)
        catalog += entries
        summary.append((fi.name.replace(".fieldinfo.csv", ""), len(entries),
                        sum(e["required"] for e in entries),
                        sum(1 for e in entries if e["source_field"] or e["source_table"]),
                        sum(1 for e in entries if e["sc_param"]),
                        len(extra)))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    staging_note = ""
    if a.staging_sql:
        staging = parse_staging_columns(Path(a.staging_sql), DEFAULT_TABLE_MAP)
        catalog = merge_staging(catalog, staging, a.set)
        only_staging = sum(1 for e in catalog if not e.get("in_template"))
        tmpl_not_in_staging = sum(1 for e in catalog if e.get("in_staging_table") is False)
        req_not_in_staging = sorted(f"{e['module']}.{e['field']}" for e in catalog
                                    if e.get("in_staging_table") is False and e["required"])
        staging_note = (f"staging tables parsed: {len(staging)}; staging-only columns added: {only_staging}; "
                        f"template fields missing from staging tables: {tmpl_not_in_staging} "
                        f"(required: {', '.join(req_not_in_staging) or 'none'})")
    Path(a.out).write_text(json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"{'template':45} {'fields':>6} {'required':>8} {'source':>6} {'sc_param':>8} {'layout-only':>11}")
    for t, n, req, srcd, scp, extra in summary:
        print(f"{t[:45]:45} {n:6} {req:8} {srcd:6} {scp:8} {extra:11}")
    tot = [sum(x[i] for x in summary) for i in range(1, 6)]
    print(f"{'TOTAL':45} {tot[0]:6} {tot[1]:8} {tot[2]:6} {tot[3]:8} {tot[4]:11}")
    if staging_note:
        print(staging_note)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
