#!/usr/bin/env python3
"""
check_answer_key.py: compare a run's outcome with a conversion answer key
(for example, the SAMPLE go-live integrity report).

Usage:
  python check_answer_key.py --results run-results.json
  python check_answer_key.py --results run-results.json --allow allowances.json
  python check_answer_key.py --results r.json --key ../references/sample-answer-key.json --modules UM00300,UM01900

run-results.json has the same shape as the key:
  {"modules": {"UM00300": {"received": 20037, "loaded": 12918, "failed": 7119,
                           "actionable_total": 439,
                           "issues": {"CONN_DUPLICATE": 6, ...},     # a number or {"count": n}
                           "control_totals": {"RESI-DEP": 158690.00}}}}

allowances.json lists approved, intended differences (each needs a reason and an approver):
  [{"module": "UM00300", "metric": "issues.CONN_DUPLICATE", "reason": "Duplicate rule fixed to ignore blank meters",
    "approved_by": "reviewer"}]

Exit code 0 when every check passes or is allowed, 1 otherwise. Rules in the results that
aren't in the key are listed as NEW; they don't fail the run, but somebody should look at them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_KEY = Path(__file__).resolve().parent.parent / "references" / "sample-answer-key.json"


def count_of(v):
    if isinstance(v, dict):
        return v.get("count")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True)
    ap.add_argument("--key", default=str(DEFAULT_KEY))
    ap.add_argument("--allow", help="JSON list of approved differences")
    ap.add_argument("--modules", help="comma-separated subset of modules to check")
    ap.add_argument("--amount-tolerance", type=float, default=0.005)
    ap.add_argument("--json-out", help="also write the comparison rows as JSON (for run.AnswerKeyCheck / Power BI)")
    a = ap.parse_args(argv)

    key = json.loads(Path(a.key).read_text(encoding="utf-8"))["modules"]
    res = json.loads(Path(a.results).read_text(encoding="utf-8")).get("modules", {})
    allow = {}
    if a.allow:
        for row in json.loads(Path(a.allow).read_text(encoding="utf-8")):
            if not row.get("reason") or not row.get("approved_by"):
                sys.exit(f"allowance {row} needs a reason and approved_by")
            allow[(row["module"], row["metric"])] = row
    wanted = set(a.modules.split(",")) if a.modules else set(key)

    rows, failed = [], 0

    def check(module, metric, expected, actual, is_amount=False):
        nonlocal failed
        if actual is None:
            ok = False
        elif is_amount:
            ok = abs(float(expected) - float(actual)) <= a.amount_tolerance
        else:
            ok = int(expected) == int(actual)
        status = "PASS" if ok else ("ALLOWED" if (module, metric) in allow else "FAIL")
        if status == "FAIL":
            failed += 1
        rows.append((module, metric, expected, "missing" if actual is None else actual, status))

    for module in sorted(wanted):
        if module not in key:
            rows.append((module, "(module)", "not in key", "", "FAIL"))
            failed += 1
            continue
        k, r = key[module], res.get(module)
        if r is None:
            rows.append((module, "(module)", "present", "missing", "ALLOWED" if (module, "(module)") in allow else "FAIL"))
            failed += 0 if (module, "(module)") in allow else 1
            continue
        for metric in ("received", "loaded", "failed", "actionable_total"):
            if metric in k:
                check(module, metric, k[metric], r.get(metric))
        for rule, spec in (k.get("issues") or {}).items():
            check(module, f"issues.{rule}", count_of(spec), count_of((r.get("issues") or {}).get(rule)))
        for name, amount in (k.get("control_totals") or {}).items():
            check(module, f"control_totals.{name}", amount, (r.get("control_totals") or {}).get(name), is_amount=True)
        for rule, v in (r.get("issues") or {}).items():
            if rule not in (k.get("issues") or {}):
                # a rule the key doesn't list: NEW until someone records a review of it in the allowances file
                metric = f"issues.{rule}"
                rows.append((module, metric, "-", count_of(v), "REVIEWED" if (module, metric) in allow else "NEW"))

    w = [max(len(str(x[i])) for x in rows + [("module", "metric", "expected", "actual", "status")]) for i in range(5)]
    header = ("module", "metric", "expected", "actual", "status")
    print("  ".join(str(h).ljust(w[i]) for i, h in enumerate(header)))
    print("  ".join("-" * w[i] for i in range(5)))
    for row in rows:
        print("  ".join(str(v).ljust(w[i]) for i, v in enumerate(row)))
    passed = sum(1 for x in rows if x[4] == "PASS")
    allowed = sum(1 for x in rows if x[4] == "ALLOWED")
    new = sum(1 for x in rows if x[4] == "NEW")
    reviewed = sum(1 for x in rows if x[4] == "REVIEWED")
    print(f"\n{passed} pass, {allowed} allowed, {failed} fail, {new} new rule(s), {reviewed} reviewed new rule(s)")
    status_of = {(x[0], x[1]): x[4] for x in rows}
    for (m, metric), row in allow.items():
        label = "reviewed" if status_of.get((m, metric)) == "REVIEWED" else "allowed"
        print(f"  {label} {m} {metric}: {row['reason']} (by {row['approved_by']})")
    if a.json_out:
        out = [{"module": m, "metric": metric, "expected": str(e), "actual": str(act), "status": s,
                "reason": allow.get((m, metric), {}).get("reason", ""), "approved_by": allow.get((m, metric), {}).get("approved_by", "")}
               for m, metric, e, act, s in rows]
        Path(a.json_out).write_text(json.dumps({"summary": {"pass": passed, "allowed": allowed, "fail": failed, "new": new,
                                                            "reviewed": reviewed}, "rows": out}, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
