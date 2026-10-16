#!/usr/bin/env python3
"""
lint_tsql.py: heuristic linter for the Cogsdale conversion platform's T-SQL house rules.

It checks the rules in ../SKILL.md that can be detected from text alone. It's a
safety net for reviews, not a parser: when a finding is intentional, add an inline
suppression on the same line or the line above:  -- lint-ignore: E005

Usage:
  python lint_tsql.py path/to/file.sql [more files or folders ...]
  python lint_tsql.py sql/ --min-version 2016 --format github
  python lint_tsql.py sql/ --strict          # warnings also fail the run

Exit code: 0 = clean (or warnings only), 1 = errors found (or warnings with --strict).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass

VERSION_FEATURES = [
    # (regex on code, minimum SQL Server major version label, name)
    (r"\bSTRING_AGG\s*\(", 2017, "STRING_AGG"),
    (r"\bCONCAT_WS\s*\(", 2017, "CONCAT_WS"),
    (r"(?<![\w.])TRIM\s*\(", 2017, "TRIM"),
    (r"\bGREATEST\s*\(", 2022, "GREATEST"),
    (r"\bLEAST\s*\(", 2022, "LEAST"),
    (r"\bDATETRUNC\s*\(", 2022, "DATETRUNC"),
    (r"\bIS\s+(NOT\s+)?DISTINCT\s+FROM\b", 2022, "IS [NOT] DISTINCT FROM"),
    (r"\bGENERATE_SERIES\s*\(", 2022, "GENERATE_SERIES"),
]
VERSION_ORDER = {"2016": 2016, "2017": 2017, "2019": 2019, "2022": 2022, "2025": 2025, "fabric": 9999}


@dataclass
class Finding:
    path: str
    line: int
    col: int
    severity: str  # E, W, I
    code: str
    message: str


def split_sql(text: str):
    """Return (code, strings, comments).
    code: text with comments and string literals blanked (positions and newlines kept).
    strings/comments: lists of (start_offset, content)."""
    out = list(text)
    strings, comments = [], []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            j = text.find("\n", i)
            j = n if j == -1 else j
            comments.append((i, text[i:j]))
            for k in range(i, j):
                out[k] = " "
            i = j
        elif ch == "/" and nxt == "*":
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            comments.append((i, text[i:j]))
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif ch == "'" or (ch in "Nn" and nxt == "'" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"))):
            start = i
            j = i + (2 if ch in "Nn" else 1)
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            strings.append((start, text[start:j]))
            for k in range(start, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif ch == "[":
            j = text.find("]", i)
            i = n if j == -1 else j + 1
        else:
            i += 1
    return "".join(out), strings, comments


def line_col(text: str, offset: int):
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col


def suppressed(lines, line_no, code):
    for ln in (line_no, line_no - 1):
        if 1 <= ln <= len(lines):
            m = re.search(r"lint-ignore:\s*([A-Z0-9 ,]+)", lines[ln - 1])
            if m and code in [c.strip() for c in m.group(1).split(",")]:
                return True
    return False


def proc_spans(code: str):
    """Yield (name, start, end) for each CREATE [OR ALTER] PROC[EDURE] up to the next GO or CREATE."""
    heads = [(m.start(), m.group(2)) for m in re.finditer(
        r"\bCREATE\s+(OR\s+ALTER\s+)?PROC(?:EDURE)?\s+([\w.\[\]]+)", code, re.I)]
    for idx, (start, name) in enumerate(heads):
        go = re.compile(r"^\s*GO\s*$", re.I | re.M).search(code, start)
        nxt = heads[idx + 1][0] if idx + 1 < len(heads) else len(code)
        end = min(go.start() if go else len(code), nxt)
        yield name.replace("[", "").replace("]", ""), start, end


def lint_text(path: str, text: str, min_version: int, loader_hint: str):
    code, strings, comments = split_sql(text)
    lines = text.splitlines()
    findings: list[Finding] = []

    def add(offset, sev, rule, msg):
        ln, col = line_col(text, offset)
        if not suppressed(lines, ln, rule):
            findings.append(Finding(path, ln, col, sev, rule, msg))

    # E001 three- or four-part names after table-ish keywords, and the DB..table form
    for m in re.finditer(r"\b(FROM|JOIN|INTO|UPDATE|EXEC(?:UTE)?|MERGE|TABLE|APPLY)\s+((?:\[?\w+\]?\.){2,3}\[?\w+\]?)", code, re.I):
        add(m.start(2), "E", "E001", f"Three-part name '{m.group(2)}': Fabric SQL database can't query other databases. Copy the reference data in and use two-part names.")
    for m in re.finditer(r"\b\w+\.\.\w+", code):
        add(m.start(), "E", "E001", f"Database-qualified name '{m.group(0)}': copy the data into this database instead.")

    # E002 server/OS-level features
    for m in re.finditer(r"\b(xp_cmdshell|sp_OACreate|sp_configure|msdb\.dbo\.sp_\w+|sp_start_job)\b", code, re.I):
        add(m.start(), "E", "E002", f"'{m.group(1)}' is a server-level feature that isn't available in Fabric SQL database. Use a pipeline step.")
    for m in re.finditer(r"\bBULK\s+INSERT\b", code, re.I):
        add(m.start(), "E", "E002", "BULK INSERT from a server path isn't portable. Land files in OneLake and load with the pipeline or OPENROWSET over OneLake.")

    # E003 hard-coded file paths in literals
    for off, s in strings:
        if re.search(r"'(?:[A-Za-z]:\\|\\\\[\w.-]+\\)", s):
            add(off, "E", "E003", "Hard-coded file path. File names and locations come from the take's Variable library or pipeline parameters.")

    # E004 triggers
    for m in re.finditer(r"\bCREATE\s+(OR\s+ALTER\s+)?TRIGGER\b", code, re.I):
        add(m.start(), "E", "E004", "Trigger in conversion-platform code. Make the logic an explicit, logged pipeline step (use temporal tables for audit history).")

    # E005 cursors only inside a loader procedure
    spans = list(proc_spans(code))
    for m in re.finditer(r"\bDECLARE\s+(\w+)\s+CURSOR\b", code, re.I):
        owner = next((nm for nm, s, e in spans if s <= m.start() < e), "")
        if loader_hint.lower() not in owner.lower():
            add(m.start(), "E", "E005", f"Cursor outside a loader procedure ({owner or 'no procedure'}). Rewrite set-based; cursors are only for calling CSM business-logic procedures row by row.")
        elif not re.search(r"CURSOR\s+LOCAL\s+FAST_FORWARD", code[m.start():m.start() + 200], re.I):
            add(m.start(), "W", "W106", "Loader cursor should be declared LOCAL FAST_FORWARD.")

    # E006 MERGE without HOLDLOCK
    for m in re.finditer(r"\bMERGE\b(?!\s*JOIN)", code, re.I):
        head = code[m.start(): m.start() + 300]
        using = re.search(r"\bUSING\b", head, re.I)
        segment = head[: using.start()] if using else head
        if not re.search(r"\bHOLDLOCK\b|\bSERIALIZABLE\b", segment, re.I):
            add(m.start(), "E", "E006", "MERGE without WITH (HOLDLOCK) on the target. Add it, make the source unique on the key, or use UPDATE then INSERT.")

    # E007 dynamic SQL executed with EXEC(...) on variables or concatenation
    for m in re.finditer(r"\bEXEC(?:UTE)?\s*\(\s*@", code, re.I):
        add(m.start(), "E", "E007", "EXEC(@sql) on a variable. Use sys.sp_executesql with parameters and QUOTENAME for identifiers.")
    for m in re.finditer(r"\bEXEC(?:UTE)?\s*\(([^)]*)\+", code, re.I):
        add(m.start(), "E", "E007", "EXEC(...) with string concatenation. Use sys.sp_executesql with parameters.")

    # E008 silent truncation switched on
    for m in re.finditer(r"\bSET\s+ANSI_WARNINGS\s+OFF\b", code, re.I):
        add(m.start(), "E", "E008", "ANSI_WARNINGS OFF truncates silently. Flag over-length values with a rule and truncate explicitly with LEFT().")

    # W101 legacy error handling
    for m in re.finditer(r"@@ERROR\b", code, re.I):
        add(m.start(), "W", "W101", "@@ERROR checks: use TRY/CATCH with THROW.")
    # W102 NOLOCK
    for m in re.finditer(r"\bNOLOCK\b|\bREADUNCOMMITTED\b", code, re.I):
        add(m.start(), "W", "W102", "NOLOCK / READ UNCOMMITTED can read rows twice or not at all. Remove it.")
    # W103 hard-coded dates (allow GP blank date)
    for off, s in strings:
        if re.fullmatch(r"N?'(\d{4}-\d{2}-\d{2}|\d{8}|\d{1,2}/\d{1,2}/\d{4})'", s) and s.strip("N'") not in ("1900-01-01", "19000101"):
            add(off, "W", "W103", f"Hard-coded date {s}: take and conversion dates come from parameters or the Variable library.")
    # W104 MAX()+1 id generation
    for m in re.finditer(r"\bMAX\s*\([^)]*\)\s*\+\s*1\b", code, re.I):
        add(m.start(), "W", "W104", "MAX()+1 for IDs: use the crosswalk + sequence pattern so IDs are stable across takes.")
    # W105 procedures: transactions without TRY, data changes without XACT_ABORT
    for name, s, e in spans:
        body = code[s:e]
        if re.search(r"\bBEGIN\s+TRAN", body, re.I) and not re.search(r"\bBEGIN\s+TRY\b", body, re.I):
            add(s, "W", "W105", f"{name}: explicit transaction without TRY/CATCH.")
        modifies = re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b", body, re.I)
        if modifies and not re.search(r"\bSET\s+XACT_ABORT\s+(ON|OFF)\b", body, re.I):
            add(s, "W", "W105", f"{name}: modifies data without SET XACT_ABORT ON.")
    # W107 imprecise money types
    for m in re.finditer(r"\b(float|real|money|smallmoney)\b", code, re.I):
        add(m.start(), "W", "W107", f"'{m.group(1)}' type: GP amounts are numeric(19,5).")
    # W108 DATALENGTH for length rules
    for m in re.finditer(r"\bDATALENGTH\s*\(", code, re.I):
        add(m.start(), "I", "I108", "DATALENGTH counts trailing spaces and bytes. Length rules use LEN().")
    # W109 commented-out code
    for off, c in comments:
        body = c[2:] if c.startswith("--") else c[2:-2]
        if re.search(r"(?i)\bexample\b|e\.g\.", body):
            continue
        for cl in body.splitlines():
            if re.match(r"\s*(SELECT\s+.+\bFROM\b|UPDATE\s+\w+.*\bSET\b|INSERT\s+(INTO\s+)?\w+|DELETE\s+(FROM\s+)?\w+|EXEC(UTE)?\s+[\w.]+\s|IF\s+.+\bBEGIN\b)", cl, re.I):
                add(off, "W", "W109", "Commented-out code: turn tailoring into a rule toggle in meta.RuleSetting, or delete it.")
                break
    # W110 SELECT * into staging
    for m in re.finditer(r"\bINSERT\s+(INTO\s+)?[\w.\[\]]+\s+SELECT\s+\*", code, re.I):
        add(m.start(), "W", "W110", "INSERT ... SELECT *: list the columns so a source change can't shift data silently.")
    # W111 NULL literal written into gold staging
    for m in re.finditer(r"\bINSERT\s+(INTO\s+)?gold\.[\w\[\]]+[^;]*?\bNULL\b", code, re.I | re.S):
        if not re.search(r"\bIS\s+(NOT\s+)?NULL\b|\bNULLIF\b", code[m.start():m.end()], re.I):
            add(m.start(), "W", "W111", "NULL written into a gold (GP-bound) table: use '' / 0 / '1900-01-01'.")
    # W112 version-sensitive features
    for rx, ver, name in VERSION_FEATURES:
        if ver > min_version:
            for m in re.finditer(rx, code, re.I):
                add(m.start(), "W", "W112", f"{name} needs SQL Server {ver}+; target minimum is {min_version}. Avoid it in code that also runs on client servers.")
    return findings


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "bin", "obj")]
                for f in files:
                    if f.lower().endswith(".sql"):
                        yield os.path.join(root, f)
        elif os.path.isfile(p):
            yield p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--min-version", default="2016", choices=list(VERSION_ORDER))
    ap.add_argument("--loader-hint", default="load", help="substring that marks a loader procedure name")
    ap.add_argument("--format", default="text", choices=["text", "github"])
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    a = ap.parse_args(argv)

    all_findings = []
    for f in iter_files(a.paths):
        with open(f, encoding="utf-8-sig", errors="replace") as fh:
            all_findings += lint_text(f, fh.read(), VERSION_ORDER[a.min_version], a.loader_hint)

    for x in sorted(all_findings, key=lambda z: (z.path, z.line, z.col)):
        if a.format == "github":
            kind = {"E": "error", "W": "warning", "I": "notice"}[x.severity]
            print(f"::{kind} file={x.path},line={x.line},col={x.col}::{x.code} {x.message}")
        else:
            print(f"{x.path}:{x.line}:{x.col}: {x.severity} {x.code} {x.message}")
    errors = sum(1 for x in all_findings if x.severity == "E")
    warnings = sum(1 for x in all_findings if x.severity == "W")
    print(f"\n{errors} error(s), {warnings} warning(s), {len(all_findings) - errors - warnings} note(s)", file=sys.stderr)
    return 1 if errors or (a.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
