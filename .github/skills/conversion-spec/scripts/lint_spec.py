#!/usr/bin/env python3
"""
lint_spec.py: validate Cogsdale conversion specs (YAML) against the schema and
cross-check them.

Usage:
  python lint_spec.py clients/sample
  python lint_spec.py clients/sample --catalog catalog.json
  python lint_spec.py path/to/one.yaml another.yaml

catalog.json (optional) is a list of {"module": "UM00300", "field": "ServiceType",
"length": 10, "required": true}. It's generated from the Field Info templates.

Exit code 1 when any error is found. Needs: pyyaml, jsonschema (both are in the
project virtual environment).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover
    sys.exit("lint_spec.py needs pyyaml and jsonschema: pip install pyyaml jsonschema "
             "(or run it with the project's virtual environment).")

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references" / "spec.schema.json"
ALLOWED_FUNCS = {"LEFT", "RIGHT", "SUBSTRING", "UPPER", "LOWER", "TRIM", "CONCAT", "COALESCE",
                 "NULLIF", "LEN", "REPLACE", "XREF"}
PLACEHOLDERS = {"take_date", "take_id", "conversion_date", "client"}
MAPPING_KEYS = ("from", "expr", "const", "default_from_class")
XREF_RX = re.compile(r"xref\(\s*([a-z][a-z0-9_]*)\s*,\s*([^,)]+?)\s*(?:,\s*([A-Za-z_][A-Za-z0-9_]*)\s*)?\)", re.I)
FUNC_RX = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class Report:
    def __init__(self):
        self.items = []

    def add(self, sev, path, msg):
        self.items.append((sev, str(path), msg))

    def errors(self):
        return sum(1 for s, _, _ in self.items if s == "E")

    def warnings(self):
        return sum(1 for s, _, _ in self.items if s == "W")


def iter_yaml(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                # pii-guard de-identification policies live next to the specs but aren't specs; deidentify.py checks them
                if f.suffix.lower() in (".yaml", ".yml") and f.is_file() and "deidentify" not in f.parent.name.lower():
                    yield f
        elif p.is_file():
            yield p


def walk_strings(obj, trail=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{trail}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{trail}/{i}")
    elif isinstance(obj, str):
        yield trail, obj


def check_functions(expr, path, where, rep):
    for name in FUNC_RX.findall(expr):
        if name.upper() not in ALLOWED_FUNCS:
            rep.add("W", path, f"{where}: function '{name}' isn't in the allowed list; propose a reshape component instead.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--catalog", help="catalog.json generated from the Field Info templates")
    a = ap.parse_args(argv)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    rep = Report()
    docs = []  # (path, doc)

    for f in iter_yaml(a.paths):
        try:
            loaded = list(yaml.safe_load_all(f.read_text(encoding="utf-8")))
        except yaml.YAMLError as e:
            rep.add("E", f, f"YAML parse error: {e}")
            continue
        loaded = [d for d in loaded if d is not None]
        if len(loaded) != 1:
            rep.add("E", f, f"expected exactly one YAML document, found {len(loaded)}")
            continue
        doc = loaded[0]
        if not isinstance(doc, dict) or "kind" not in doc:
            rep.add("E", f, "missing 'kind' (take, reshape, mapping, crosswalk, rules, load)")
            continue
        kind = doc["kind"]
        if kind not in schema["$defs"] or kind in ("field", "reshapeStep"):
            rep.add("E", f, f"unknown kind '{kind}'")
            continue
        # field-level clarity before the schema's generic oneOf message
        if kind == "mapping":
            for i, fld in enumerate(doc.get("fields") or []):
                present = [k for k in MAPPING_KEYS if isinstance(fld, dict) and k in fld]
                if len(present) != 1:
                    rep.add("E", f, f"fields[{i}] '{fld.get('target', '?') if isinstance(fld, dict) else '?'}': use exactly one of {', '.join(MAPPING_KEYS)} (found {present or 'none'})")
        sub = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{kind}"}
        for err in sorted(Draft202012Validator(sub, format_checker=FormatChecker()).iter_errors(doc), key=lambda e: list(e.path)):
            where = "/".join(str(x) for x in err.path) or "(root)"
            if "is not valid under any of the given schemas" in err.message and "fields" in where:
                continue  # already reported clearly above
            rep.add("E", f, f"{where}: {err.message}")
        docs.append((f, doc))

    by_client = defaultdict(list)
    for f, d in docs:
        by_client[d.get("client", "?")].append((f, d))

    catalog = None
    if a.catalog:
        # Keys are lower-cased: SQL Server and GP column names are case-insensitive.
        catalog = defaultdict(dict)
        for row in json.loads(Path(a.catalog).read_text(encoding="utf-8")):
            catalog[row["module"]][row["field"].lower()] = row

    open_q = defaultdict(list)
    assumed_q = defaultdict(list)
    for client, items in by_client.items():
        takes = [(f, d) for f, d in items if d["kind"] == "take"]
        # One default take (clients/<client>/take.yaml); later takes live in takes/<take_id>.yaml. Ids are unique.
        defaults = [(f, d) for f, d in takes if Path(f).parent.name.lower() != "takes"]
        if len(defaults) > 1:
            rep.add("E", defaults[1][0], f"client '{client}' has more than one default take.yaml; put later takes in takes/<take_id>.yaml")
        seen_ids = {}
        for f, d in takes:
            tid = d.get("take_id")
            if tid in seen_ids:
                rep.add("E", f, f"take_id '{tid}' is already used by {seen_ids[tid]}")
            seen_ids.setdefault(tid, Path(f).name)
            if Path(f).parent.name.lower() == "takes" and Path(f).stem != tid:
                rep.add("E", f, f"a take in takes/ must be named <take_id>.yaml ('{tid}.yaml')")
        take = (defaults or takes)[0][1] if takes else None
        if not takes:
            rep.add("W", f"client:{client}", "no take.yaml found; placeholders can't be resolved")

        xwalks = {}
        for f, d in items:
            if d["kind"] == "crosswalk":
                codes = [v.get("legacy_code") for v in d.get("values", [])]
                dups = sorted({c for c in codes if codes.count(c) > 1})
                if dups:
                    rep.add("E", f, f"crosswalk '{d['id']}': duplicate legacy_code {dups}")
                attrs = set()
                for v in d.get("values", []):
                    attrs |= set(v) - {"legacy_code", "include", "reason"}
                xwalks[d["id"]] = attrs

        mapped = {}  # module -> set(targets)
        for f, d in items:
            if d["kind"] != "mapping":
                continue
            targets = [x.get("target") for x in d.get("fields", []) if isinstance(x, dict)]
            dups = sorted({t for t in targets if targets.count(t) > 1})
            if dups:
                rep.add("E", f, f"duplicate target field(s) {dups}")
            mapped[d["module"]] = set(t for t in targets if t)
            for x in d.get("fields", []):
                if not isinstance(x, dict) or "expr" not in x:
                    continue
                check_functions(x["expr"], f, f"field '{x.get('target')}'", rep)
                for xid, _col, attr in XREF_RX.findall(x["expr"]):
                    if xid not in xwalks:
                        rep.add("E", f, f"field '{x.get('target')}': xref '{xid}' has no crosswalk file")
                    elif attr and attr != "target" and attr not in xwalks[xid]:
                        rep.add("E", f, f"field '{x.get('target')}': crosswalk '{xid}' has no attribute '{attr}'")
            if catalog is not None:
                cat = catalog.get(d["module"])
                if not cat:
                    rep.add("W", f, f"module {d['module']} isn't in the catalog")
                else:
                    mapped_lower = {t.lower() for t in mapped[d["module"]]}
                    for t in sorted(mapped[d["module"]]):
                        if t.lower() not in cat:
                            rep.add("E", f, f"target '{t}' isn't a field of {d['module']} in the catalog")
                    for key, row in cat.items():
                        if not row.get("required") or key in mapped_lower:
                            continue
                        if row.get("in_staging_table") is False:
                            # The template marks it required, but the real staging table has no such column.
                            rep.add("W", f, f"template marks '{row['field']}' of {d['module']} required, but the "
                                            f"staging table has no such column; confirm with Cogsdale")
                        else:
                            rep.add("E", f, f"required field '{row['field']}' of {d['module']} isn't mapped "
                                            f"(map it or mark default_from_class)")
                    for x in d.get("fields", []):
                        tgt = x.get("target", "").lower() if isinstance(x, dict) else ""
                        if isinstance(x, dict) and isinstance(x.get("const"), str) and tgt in cat:
                            if len(x["const"]) > int(cat[tgt].get("length") or 10**6):
                                rep.add("W", f, f"constant for '{x['target']}' is longer than the CSM field")

        for f, d in items:
            if d["kind"] == "reshape":
                for i, step in enumerate(d.get("steps", [])):
                    if not isinstance(step, dict):
                        continue
                    for comp, params in step.items():
                        if comp == "strip_artifacts":
                            for pat in (params or {}).get("patterns", []):
                                try:
                                    re.compile(pat)
                                except re.error as e:
                                    rep.add("E", f, f"steps[{i}] strip_artifacts: bad regex {pat!r}: {e}")
                        if comp == "derive":
                            for col, expr in (params or {}).items():
                                check_functions(expr, f, f"steps[{i}] derive '{col}'", rep)
            if d["kind"] in ("load", "rules"):
                targets = mapped.get(d.get("module"))
                if targets is None:
                    rep.add("W", f, f"no mapping for module {d.get('module')} in this client folder; field checks skipped")
                elif d["kind"] == "load":
                    for col in list(d.get("order_by", [])) + ([d["partition_by"]] if d.get("partition_by") else []):
                        if col not in targets:
                            rep.add("E", f, f"'{col}' (order_by/partition_by) isn't a mapped target of {d['module']}")
                    for param, col in (d.get("parameters") or {}).items():
                        if col not in targets:
                            rep.add("E", f, f"parameter {param} -> '{col}' isn't a mapped target of {d['module']}")
                    if d.get("partition_by") and d.get("order_by") and d["partition_by"] != d["order_by"][0]:
                        rep.add("W", f, "partition_by isn't the first order_by column; rows of one partition key may load out of order")
            allowed = PLACEHOLDERS | (set(d.get("take_variables") or []) | set(d.get("environment_variables") or [])
                                      if d["kind"] == "runbook" else set())
            for where, s in walk_strings(d):
                for ph in re.findall(r"\{([a-zA-Z_]+)\}", s):
                    if ph not in allowed:
                        rep.add("E", f, f"{where}: unknown placeholder {{{ph}}} (allowed: {sorted(allowed)})")
                    elif take is not None and ph in ("take_date", "conversion_date", "take_id") and not take.get(ph):
                        rep.add("E", f, f"{where}: placeholder {{{ph}}} has no value in take.yaml")
            for q in d.get("open_questions", []) or []:
                if not isinstance(q, dict):
                    continue
                status = q.get("status", "open")
                if status == "open":
                    open_q[q.get("owner", "?")].append(f"{q.get('id')}: {q.get('text')}  [{f.name}]")
                elif status == "assumed":
                    # an assumption stands in for an answer, so it must say what was assumed and why it's believed
                    if not q.get("assumption") or not q.get("evidence"):
                        rep.add("E", f, f"{q.get('id')}: status 'assumed' needs both 'assumption' and 'evidence'")
                    assumed_q[q.get("owner", "?")].append(f"{q.get('id')}: {q.get('assumption')}  [{f.name}]")

    for sev, path, msg in rep.items:
        print(f"{sev} {path}: {msg}")
    if open_q:
        print("\nOpen questions by owner:")
        for owner in sorted(open_q):
            print(f"  {owner} ({len(open_q[owner])})")
            for line in open_q[owner]:
                print(f"    - {line}")
    if assumed_q:
        print("\nWorking assumptions by owner (confirm when the owner can; each one carries its evidence in the spec):")
        for owner in sorted(assumed_q):
            print(f"  {owner} ({len(assumed_q[owner])})")
            for line in assumed_q[owner]:
                print(f"    - {line}")
    print(f"\n{len(docs)} spec file(s): {rep.errors()} error(s), {rep.warnings()} warning(s)", file=sys.stderr)
    return 1 if rep.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
