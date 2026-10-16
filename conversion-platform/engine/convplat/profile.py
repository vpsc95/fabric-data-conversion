"""Take profiling: chain of custody, column statistics (metadata only), spec conformance and drift.

  manifest(landing)                       every landed file with size, SHA-256 and sheets (chain of custody)
  verify(landing, manifest)               files whose bytes changed since they were recorded
  profile_take(specs, landing, files)     per-file, per-sheet column statistics; no record values
  conformance(specs, profile, needed)     what the approved specs need (files, sheets, columns) but did not arrive
  drift(profile, previous)                changes against the client's previous take

Statistics are metadata only: inferred type, blank count, distinct count, min/max length, value shapes
('99-9999-99', 'Aaaa'), and the code set only for short low-cardinality columns whose names do not suggest
personal data (status, class and service codes). Nothing else from a record leaves this module.

Blocking findings mean the approved specs no longer fit what the client sent: gate 1 (a spec change, approved
by pull request) is required before the take can run. Warnings and information are shown to the reviewer.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path

import polars as pl

from .reshape import sanitize
from .sources import list_sheets, read_grid
from .specs import ClientSpecs

DATA_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".txt"}
LINEAGE = {"TAKEID", "SOURCEROW"}
PERSONAL = re.compile(r"(?i)NAME|ADDR|STREET|PHONE|CELL|HOME|EMAIL|SOCIAL|SSN|\bSIN\b|DRIVER|LICEN|\bDL|BANK|ROUTING|BIRTH|DOB|"
                      r"ACCT|ACCOUNT|METER|SERIAL|_SN$|ENDPOINT|LAT|LON|GPS|RECEIPT|\bID\b|ZIP|POSTAL|POSTCODE")
NOT_A_CODE = re.compile(r"\d[/:]\d|\d{4}-\d{2}-\d{2}|^-?\$?[\d,]*\.\d+$")   # dates, times and amounts are not code sets
NOT_A_CODE_NAME = re.compile(r"(?i)DATE|TIME|AMOUNT|AMT|APPLIED|BALANCE|\bBAL|RECEIVED|UNBILLED|INTEREST|READ\b|FLOW|CONSUMPTION")
TYPES = [("integer", r"^-?\d+$"), ("decimal", r"^-?\$?[\d,]*\.\d+$"), ("date", r"^\d{1,2}/\d{1,2}/\d{2,4}$|^\d{4}-\d{2}-\d{2}$"),
         ("datetime", r"^(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})[ T]\d{1,2}:\d{2}"), ("boolean", r"^(?i:true|false|y|n|yes|no)$")]
CODE_MAX_DISTINCT, CODE_MAX_LEN = 25, 16          # 16: service descriptions arrive truncated to 14 characters


# ---------------------------------------------------------------------------------------------- custody
def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def manifest(landing: str | Path) -> list[dict]:
    """Chain of custody for every file in the take folder."""
    out = []
    for p in sorted(Path(landing).iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        st = p.stat()
        sheets = []
        if p.suffix.lower() in DATA_SUFFIXES:
            try:
                sheets = [{"sheet": s, "rows": r, "columns": c} for s, r, c in list_sheets(p)]
            except Exception as e:                                   # unreadable workbook: custody still recorded
                sheets = [{"sheet": "", "rows": 0, "columns": 0, "error": type(e).__name__}]
        out.append({"file": p.name, "size": st.st_size, "sha256": sha256(p),
                    "modified_utc": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sheets": sheets})
    return out


def verify(landing: str | Path, recorded: list[dict], only: set[str] | None = None) -> list[str]:
    """Files that changed (or vanished) since the manifest was recorded."""
    changed = []
    for m in recorded:
        if only is not None and m["file"] not in only:
            continue
        p = Path(landing) / m["file"]
        if not p.exists():
            changed.append(f"{m['file']}: missing")
        elif p.stat().st_size != m["size"] or sha256(p) != m["sha256"]:
            changed.append(f"{m['file']}: content changed since it was received")
    return changed


# ---------------------------------------------------------------------------------------------- statistics
def shape_expr(col: str) -> pl.Expr:
    # digits become '#' (not '9'), so a shape such as '###-###-####' can never read as a real phone or account number
    return (pl.col(col).str.replace_all(r"[0-9]", "#").str.replace_all(r"[A-Z]", "A").str.replace_all(r"[a-z]", "a")
            .str.slice(0, 24))


def column_stats(df: pl.DataFrame, original: list[str], sanitized: list[str]) -> list[dict]:
    stats = []
    n = df.height
    for pos, (orig, name) in enumerate(zip(original, sanitized), start=1):
        s = df.get_column(name).fill_null("").str.strip_chars()
        filled = s.filter(s != "")
        blank = n - filled.len()
        entry = {"position": pos, "name": orig, "sanitized": name, "rows": n, "blank": blank,
                 "distinct": filled.n_unique() if filled.len() else 0,
                 "min_len": int(filled.str.len_chars().min()) if filled.len() else 0,
                 "max_len": int(filled.str.len_chars().max()) if filled.len() else 0, "type": "empty", "shapes": [], "codes": None}
        if filled.len():
            entry["type"] = "text"
            for t, rx in TYPES:
                if filled.str.contains(rx).mean() >= 0.98:
                    entry["type"] = t
                    break
            shapes = (pl.DataFrame({"v": filled}).select(shape_expr("v").alias("shape"))
                      .group_by("shape").len().sort(["len", "shape"], descending=[True, False]).head(3))
            entry["shapes"] = [[r["shape"], round(r["len"] / filled.len(), 3)] for r in shapes.iter_rows(named=True)]
            if entry["distinct"] <= CODE_MAX_DISTINCT and entry["max_len"] <= CODE_MAX_LEN and not PERSONAL.search(orig) \
                    and not PERSONAL.search(name) and not NOT_A_CODE_NAME.search(orig) and entry["type"] not in ("date", "datetime"):
                vc = pl.DataFrame({"v": filled}).group_by("v").len().sort(["len", "v"], descending=[True, False])
                codes = [[r["v"], r["len"]] for r in vc.iter_rows(named=True)]
                if not any(NOT_A_CODE.search(v) for v, _ in codes):
                    entry["codes"] = codes
        stats.append(entry)
    return stats


def read_frame(path: Path, sheet: str | None, header_row: int) -> tuple[list[str], list[str], pl.DataFrame]:
    if path.suffix.lower() in (".csv", ".txt"):
        df = pl.read_csv(path, infer_schema=False, encoding="utf8-lossy", skip_rows=header_row, truncate_ragged_lines=True)
        original = [c.lstrip("\ufeff") for c in df.columns]
    else:
        grid = read_grid(path, sheet)
        original = [str(h) for h in grid[header_row]] if len(grid) > header_row else []
        body = grid[header_row + 1:]
        width = len(original)
        df = pl.DataFrame({f"c{i}": [r[i] if i < len(r) else "" for r in body] for i in range(width)}, schema={f"c{i}": pl.Utf8 for i in range(width)})
    sanitized = sanitize(original)
    df.columns = [f"_{i}" for i in range(len(df.columns))]
    df = df.rename({f"_{i}": s for i, s in enumerate(sanitized)})
    return original, sanitized, df


def profile_take(specs: ClientSpecs, landing: str | Path, files: list[dict]) -> dict:
    """Column statistics for every readable data file; spec files use the spec's sheet and header row."""
    landing = Path(landing)
    by_file = {s["source"]["file"]: s for s in specs.file_reshapes(landing)}
    out = []
    for m in files:
        p = landing / m["file"]
        if p.suffix.lower() not in DATA_SUFFIXES:
            continue
        spec = by_file.get(m["file"])
        sheets = [spec["source"].get("sheet")] if spec else ([s["sheet"] for s in m["sheets"]] or [None])
        header_row = int(spec["source"].get("header_row") or 0) if spec else 0
        entry = {"file": m["file"], "spec": spec["id"] if spec else None, "sheets": []}
        for sh in sheets:
            original, sanitized, df = read_frame(p, sh or None, header_row)
            entry["sheets"].append({"sheet": sh or "", "header_row": header_row, "rows": df.height,
                                    "columns": column_stats(df, original, sanitized)})
        out.append(entry)
    return {"client": specs.client, "take_id": specs.take_id, "files": out}


# ---------------------------------------------------------------------------------------------- conformance and drift
def needed_columns(specs: ClientSpecs, slv_columns: dict[str, list[str]], landing: str | Path) -> dict[str, dict]:
    """Per file spec: the columns downstream SQL needs (required) and those used only to cross-check (optional).
    slv_columns: reshape target ('silver.services') -> columns of the matching slv table."""
    out = {}
    for s in specs.reshapes:
        cols = slv_columns.get(s.get("target", ""))
        if not cols or "source" not in s:
            continue
        derived, check_only, prefixes = set(), set(), []
        for step in s.get("steps", []):
            kind, body = next(iter(step.items()))
            if kind == "fill_down":
                derived |= {c.upper() for c in body.get("as", [])}
                check_only |= {c.upper() for c in body.get("check_against", [])}
            elif kind == "parse_address":
                prefixes.append(body.get("prefix", "").upper())
            elif kind == "rename":
                derived |= {str(v).upper() for v in body.values()}
        required, optional = [], []
        for c in cols:
            u = c.upper()
            if u in LINEAGE or u in derived or any(p and u.startswith(p) for p in prefixes):
                continue
            (optional if u in check_only else required).append(c)
        out[s["id"]] = {"file": s["source"]["file"], "sheet": s["source"].get("sheet"), "required": required, "optional": optional}
    return out


def conformance(profile: dict, needed: dict[str, dict], files: list[dict]) -> list[dict]:
    present = {m["file"] for m in files}
    prof = {f["file"]: f for f in profile["files"]}
    findings = []
    for spec_id, need in needed.items():
        f = need["file"]
        if f not in present:
            findings.append({"kind": "file_missing", "severity": "blocking", "file": f, "column": None,
                             "detail": f"spec {spec_id} expects this file in the take"})
            continue
        sheets = {s["sheet"]: s for s in prof.get(f, {}).get("sheets", [])}
        sheet = sheets.get(need["sheet"] or "") or (next(iter(sheets.values())) if not need["sheet"] and sheets else None)
        if sheet is None:
            findings.append({"kind": "sheet_missing", "severity": "blocking", "file": f, "column": None,
                             "detail": f"spec {spec_id} reads sheet '{need['sheet']}'"})
            continue
        have = {c["sanitized"].upper() for c in sheet["columns"]}
        for c in need["required"]:
            if c.upper() not in have:
                findings.append({"kind": "column_missing", "severity": "blocking", "file": f, "column": c,
                                 "detail": f"spec {spec_id} and the conversion SQL need this column"})
        for c in need["optional"]:
            if c.upper() not in have:
                findings.append({"kind": "check_column_missing", "severity": "info", "file": f, "column": c,
                                 "detail": "client helper column used only to cross-check the platform's fill-down; not needed"})
    for f in profile["files"]:
        if f["spec"] is None:
            findings.append({"kind": "file_not_in_spec", "severity": "info", "file": f["file"], "column": None,
                             "detail": "received but no reshape spec reads it (reference or new extract)"})
    return findings


def _file_key(f: dict) -> str:
    """Files are matched across takes by the spec that reads them, else by name with the take date masked
    (file names change every take: 'UB Services Report 07172026.xlsx' -> 'ub services report {date}.xlsx')."""
    return f"spec:{f['spec']}" if f.get("spec") else re.sub(r"\d{6,8}", "{date}", f["file"].lower())


def drift(profile: dict, previous: dict | None) -> list[dict]:
    """Changes against the previous take's profile (same client)."""
    if not previous:
        return [{"kind": "baseline", "severity": "info", "file": None, "column": None,
                 "detail": "first profiled take for this client: it becomes the baseline for drift checks"}]
    findings = []
    prev_files = {_file_key(f): f for f in previous["files"]}
    cur_files = {_file_key(f): f for f in profile["files"]}
    for k, f in cur_files.items():
        if k not in prev_files:
            findings.append({"kind": "file_new", "severity": "info", "file": f["file"], "column": None, "detail": "not in the previous take"})
    for k, f in prev_files.items():
        if k not in cur_files:
            findings.append({"kind": "file_gone", "severity": "warning", "file": f["file"], "column": None, "detail": "was in the previous take"})
    for k, f in cur_files.items():
        pf = prev_files.get(k)
        if not pf:
            continue
        psheets = {s["sheet"]: s for s in pf["sheets"]}
        for sh in f["sheets"]:
            ps = psheets.get(sh["sheet"])
            if not ps:
                continue
            pcols = {c["sanitized"]: c for c in ps["columns"]}
            ccols = {c["sanitized"]: c for c in sh["columns"]}
            for name in ccols.keys() - pcols.keys():
                findings.append({"kind": "column_new", "severity": "info", "file": f["file"], "column": name, "detail": "new column"})
            for name in pcols.keys() - ccols.keys():
                findings.append({"kind": "column_gone", "severity": "warning", "file": f["file"], "column": name, "detail": "column no longer delivered"})
            for name in ccols.keys() & pcols.keys():
                c, p = ccols[name], pcols[name]
                if c["type"] != p["type"] and "empty" not in (c["type"], p["type"]):
                    findings.append({"kind": "type_change", "severity": "warning", "file": f["file"], "column": name,
                                     "detail": f"{p['type']} -> {c['type']}"})
                cb, pb = c["blank"] / max(c["rows"], 1), p["blank"] / max(p["rows"], 1)
                if abs(cb - pb) >= 0.2:
                    findings.append({"kind": "blank_share", "severity": "warning", "file": f["file"], "column": name,
                                     "detail": f"blank share {pb:.0%} -> {cb:.0%}"})
                if c["max_len"] > p["max_len"] and p["max_len"]:
                    findings.append({"kind": "longer_values", "severity": "info", "file": f["file"], "column": name,
                                     "detail": f"max length {p['max_len']} -> {c['max_len']}"})
                if c["codes"] is not None and p["codes"] is not None:
                    new_codes = sorted({v for v, _ in c["codes"]} - {v for v, _ in p["codes"]})
                    if new_codes:
                        findings.append({"kind": "new_codes", "severity": "warning", "file": f["file"], "column": name,
                                         "detail": f"{len(new_codes)} code value(s) not seen before: check the crosswalks"})
    return findings


def summarize(findings: list[dict]) -> dict:
    sev = {"blocking": 0, "warning": 0, "info": 0}
    for f in findings:
        sev[f["severity"]] += 1
    return {**sev, "gate1_required": sev["blocking"] > 0}


# ---------------------------------------------------------------------------------------------- persistence
def previous_profile(cn, client: str, take: str, take_date: str | None = None) -> tuple[str | None, dict | None]:
    """The client's previous take by take date (run.Take), with its profile; (None, None) for the earliest take."""
    import json
    if take_date:
        row = cn.cursor().execute(
            "SELECT TOP (1) p.TakeId, p.ProfileJson FROM run.TakeProfile AS p "
            "JOIN run.Take AS t ON t.ClientId = p.ClientId AND t.TakeId = p.TakeId "
            "WHERE p.ClientId = ? AND p.TakeId <> ? AND t.TakeDate < ? ORDER BY t.TakeDate DESC", client, take, take_date).fetchone()
    else:
        row = cn.cursor().execute("SELECT TOP (1) TakeId, ProfileJson FROM run.TakeProfile WHERE ClientId = ? AND TakeId <> ? "
                                  "ORDER BY CreatedAt DESC", client, take).fetchone()
    return (row[0], json.loads(row[1])) if row else (None, None)


def save(cn, client: str, take: str, files: list[dict], profile: dict, findings: list[dict], spec_by_file: dict[str, str],
         take_date: str | None = None, simulated: bool = False) -> None:
    import json
    cur = cn.cursor()
    if take_date:                                                  # take registry: take-over-take order
        # @@ROWCOUNT inside one batch: cursor.rowcount is -1 when the session has NOCOUNT ON (the SQL deploy scripts set it)
        cur.execute("UPDATE run.Take SET TakeDate = ?, Simulated = ? WHERE ClientId = ? AND TakeId = ?; "
                    "IF @@ROWCOUNT = 0 INSERT run.Take (ClientId, TakeId, TakeDate, Simulated) VALUES (?, ?, ?, ?);",
                    take_date, int(simulated), client, take, client, take, take_date, int(simulated))
    for t in ("run.LandingFile", "run.ColumnProfile", "run.TakeProfile", "run.DriftFinding"):
        cur.execute(f"DELETE {t} WHERE ClientId = ? AND TakeId = ?", client, take)
    for m in files:
        sheets = "; ".join(f"{s['sheet'] or '(csv)'} {s['rows']}x{s['columns']}" for s in m["sheets"])[:1000]
        cur.execute("INSERT run.LandingFile (ClientId, TakeId, FileName, SizeBytes, Sha256, ModifiedUtc, SpecId, Sheets) VALUES (?,?,?,?,?,?,?,?)",
                    client, take, m["file"], m["size"], m["sha256"], m["modified_utc"].replace("T", " ").rstrip("Z"),
                    spec_by_file.get(m["file"]), sheets)
    for f in profile["files"]:
        for sh in f["sheets"]:
            for c in sh["columns"]:
                cur.execute("INSERT run.ColumnProfile (ClientId, TakeId, FileName, SheetName, Position, ColumnName, Sanitized, InferredType, "
                            "RowsRead, BlankCount, DistinctCount, MinLen, MaxLen, Shapes, CodeCount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            client, take, f["file"], sh["sheet"], c["position"], c["name"][:128], c["sanitized"][:128], c["type"],
                            c["rows"], c["blank"], c["distinct"], c["min_len"], c["max_len"],
                            ", ".join(f"{s} {v:.0%}" for s, v in c["shapes"])[:400], len(c["codes"]) if c["codes"] is not None else None)
    cur.execute("INSERT run.TakeProfile (ClientId, TakeId, ProfileJson) VALUES (?,?,?)", client, take, json.dumps(profile, ensure_ascii=False))
    for x in findings:
        cur.execute("INSERT run.DriftFinding (ClientId, TakeId, Kind, Severity, FileName, ColumnName, Detail, ComparedTo) VALUES (?,?,?,?,?,?,?,?)",
                    client, take, x["kind"], x["severity"], x.get("file"), x.get("column"), x["detail"][:1000], x.get("compared_to"))
