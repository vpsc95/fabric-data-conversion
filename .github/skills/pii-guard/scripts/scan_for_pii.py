#!/usr/bin/env python3
"""
scan_for_pii.py: scan code, SQL, specs and documents for personal data before they are
shared with an AI assistant, committed to Git, or sent to a partner.

Conversion scripts often carry real values: an account number in a WHERE clause, a
customer's name in a comment, a phone number in a test. This finds them. It prints
masked snippets only, never the full value.

Usage:
  python scan_for_pii.py <files or folders>
  python scan_for_pii.py sql/ specs/ --ner              # also look for person names with Presidio (slower)
  python scan_for_pii.py . --fail-on medium --format github

Exit code 1 when a finding at or above --fail-on (default: high) exists.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

TEXT_EXT = {".sql", ".py", ".ps1", ".yaml", ".yml", ".json", ".md", ".txt", ".csv", ".ipynb", ".cs", ".js",
            ".ts", ".kql", ".m", ".pq", ".tmdl", ".xml", ".config", ".ini", ".env"}
SKIP_DIRS = {".git", "node_modules", "bin", "obj", ".venv", "venv", "__pycache__", ".idea", ".vscode"}
SEV_ORDER = {"low": 0, "medium": 1, "high": 2}


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


CODE_COLUMN = re.compile(r"(?:status|stat|type|class|category|flag|kind)$", re.I)
TECH_NAME = re.compile(r"(?:step|file|table|sheet|column|object|schema|server|database|host|proc|procedure|rule|module|job|item)name$", re.I)


def human_value(match_text: str, line: str = "", start: int = 0) -> bool:
    """True when the quoted literal in a predicate looks like personal data, not an identifier or pattern."""
    if line[:start].count("'") % 2:                     # the "column" is itself inside a string literal, e.g. CONCAT('; customer=', ...)
        return False
    col = re.match(r"\s*(\w+)", match_text)
    if col and (CODE_COLUMN.search(col.group(1)) or TECH_NAME.search(col.group(1))):   # CustomerStatus = 'ACTIVE', StepName LIKE 'gold.%'
        return False
    m = re.search(r"'([^']*)'", match_text)
    if not m:
        return False
    v = m.group(1)
    if re.fullmatch(r"[%_\s]*", v) or "_" in v:          # LIKE wildcards, object names such as IX_Issue_Take
        return False
    return bool(re.search(r"[A-Za-z]{2,}|\d{3}", v))


def card_like(s: str) -> bool:
    """Luhn-valid, 13-19 digits, a major-network first digit (2-6) and not one repeated digit: the all-zero
    logicalId GUIDs in Fabric .platform files pass Luhn but are not card numbers."""
    d = re.sub(r"\D", "", s)
    return len(d) >= 13 and d[0] in "23456" and len(set(d)) > 1 and luhn_ok(d)


DETECTORS = [
    # (name, severity, regex, validator)
    ("US_SSN", "high", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), None),
    ("CA_SIN", "high", re.compile(r"\b\d{3}[- ]\d{3}[- ]\d{3}\b"), lambda s: luhn_ok(re.sub(r"\D", "", s))),
    ("CREDIT_CARD", "high", re.compile(r"\b(?:\d[ -]?){13,19}\b"), card_like),
    ("EMAIL", "high", re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("PHONE_NA", "medium", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"), None),
    ("STREET_ADDRESS", "medium", re.compile(
        r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+"
        r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard|Ct|Court|Way|Pl|Place|Cir|Circle|Pkwy|Hwy|Trl)\b\.?",
        re.I), None),
    ("GPS_PAIR", "medium", re.compile(r"-?\d{1,3}\.\d{5,}\s*,\s*-?\d{1,3}\.\d{5,}"), None),
    ("HARDCODED_PERSON_VALUE", "medium", re.compile(
        r"\b(?:\w*name|first\w*|last\w*|customer\w*|owner\w*|addr\w*|street\w*|email\w*|phone\w*)\s*(?:=|LIKE|IN\s*\()\s*N?'([^']{3,})'",
        re.I), human_value),
    ("LONG_NUMBER", "low", re.compile(r"(?<![\w.])\d{8,}(?![\w.])"), None),
]


def mask(s: str) -> str:
    s = s.strip()
    if len(s) <= 4:
        return "*" * len(s)
    return s[0] + re.sub(r"[A-Za-z0-9]", "*", s[1:-1]) + s[-1]


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in files:
                    if os.path.splitext(f)[1].lower() in TEXT_EXT:
                        yield os.path.join(root, f)
        elif os.path.isfile(p):
            yield p


def scan_file(path, use_ner, analyzer, allow):
    findings = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as e:
        return [(path, 0, 0, "ERROR", "high", str(e))]
    for ln, line in enumerate(lines, 1):
        if "pii-scan: ignore" in line:
            continue
        for name, sev, rx, ok in DETECTORS:
            for m in rx.finditer(line):
                text = m.group(0)
                if ok and not (ok(text, line, m.start()) if ok is human_value else ok(text)):
                    continue
                if any(re.search(a, text) for a in allow):
                    continue
                findings.append((path, ln, m.start() + 1, name, sev, mask(text)))
        if use_ner and analyzer is not None:
            for comment in re.findall(r"(?:--|#|//)\s?(.*)$", line):
                for r in analyzer.analyze(text=comment, language="en", entities=["PERSON"], score_threshold=0.7):
                    findings.append((path, ln, 1, "PERSON_IN_COMMENT", "medium", mask(comment[r.start:r.end])))
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--ner", action="store_true", help="also detect person names in comments with Presidio")
    ap.add_argument("--fail-on", default="high", choices=list(SEV_ORDER))
    ap.add_argument("--allow", action="append", default=[], help="regex for known-safe values (repeatable)")
    ap.add_argument("--format", default="text", choices=["text", "github"])
    a = ap.parse_args(argv)

    analyzer = None
    if a.ner:
        from presidio_analyzer import AnalyzerEngine
        analyzer = AnalyzerEngine()

    findings = []
    for f in iter_files(a.paths):
        findings += scan_file(f, a.ner, analyzer, a.allow)
    for path, ln, col, name, sev, snippet in findings:
        if a.format == "github":
            kind = "error" if SEV_ORDER.get(sev, 2) >= SEV_ORDER[a.fail_on] else "warning"
            print(f"::{kind} file={path},line={ln},col={col}::{name} ({sev}) {snippet}")
        else:
            print(f"{path}:{ln}:{col}: {sev.upper():6} {name:24} {snippet}")
    worst = max((SEV_ORDER.get(f[4], 2) for f in findings), default=-1)
    counts = {s: sum(1 for f in findings if f[4] == s) for s in SEV_ORDER}
    print(f"\n{len(findings)} finding(s): {counts}. Suppress a known-safe line with the comment 'pii-scan: ignore'.",
          file=sys.stderr)
    return 1 if worst >= SEV_ORDER[a.fail_on] else 0


if __name__ == "__main__":
    sys.exit(main())
