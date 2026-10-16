"""Smoke-test the "Conversion Run" semantic model with read-only DAX (Power BI executeQueries API).

  python check_model.py                 # metadata + every measure + reconciliation checks for sample/go-live
  python check_model.py --take go-live --client sample

Checks:
- tables, relationships and measures are there (INFO.VIEW.*), and every measure evaluates without an error;
- the model's numbers agree with each other and with the answer key: module received/loaded/failed equal the
  answer-key actuals, the fix list equals the records to fix, the answer-key status counts add up.
Exit code 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests
from azure.identity import AzureCliCredential

HERE = Path(__file__).resolve().parent
WS = json.loads((HERE.parent / "fabric" / "workspace.json").read_text(encoding="utf-8"))
PBI = "https://api.powerbi.com/v1.0/myorg"


class Model:
    def __init__(self, name: str):
        cred = AzureCliCredential(tenant_id=WS["tenant_id"])
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {cred.get_token('https://analysis.windows.net/powerbi/api/.default').token}",
                               "Content-Type": "application/json"})
        r = self.s.get(f"{PBI}/groups/{WS['workspace_id']}/datasets")
        r.raise_for_status()
        self.id = next(d["id"] for d in r.json()["value"] if d["name"] == name)

    def query(self, dax: str) -> list[dict]:
        r = self.s.post(f"{PBI}/groups/{WS['workspace_id']}/datasets/{self.id}/executeQueries",
                        data=json.dumps({"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}))
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:1200]}")
        res = r.json()["results"][0]
        if "error" in res:
            raise RuntimeError(json.dumps(res["error"])[:1200])
        return [{k.split("[")[-1].rstrip("]"): v for k, v in row.items()} for row in res["tables"][0]["rows"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="Conversion Run")
    ap.add_argument("--client", default="sample")
    ap.add_argument("--take", default="go-live")
    a = ap.parse_args(argv)
    m, fails = Model(a.model), []
    take = f"{a.client}/{a.take}"

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name} {detail}")
        if not ok:
            fails.append(name)

    print(f"model {a.model} ({m.id}), take {take}")
    tables = m.query("EVALUATE SELECTCOLUMNS(INFO.VIEW.TABLES(), \"Name\", [Name])")
    rels = m.query("EVALUATE SELECTCOLUMNS(INFO.VIEW.RELATIONSHIPS(), \"Name\", [Name], \"Active\", [IsActive])")
    measures = m.query("EVALUATE SELECTCOLUMNS(INFO.VIEW.MEASURES(), \"Table\", [Table], \"Name\", [Name])")
    check("tables", len(tables) == 20, f"({len(tables)})")
    check("relationships active", len(rels) == 27 and all(r["Active"] for r in rels), f"({len(rels)})")
    print(f"  measures: {len(measures)}")
    # relationships assume referential integrity, so dimensions must not carry Direct Lake's blank "unknown member"
    blanks = m.query("EVALUATE ROW(\"Module\", COUNTROWS(VALUES(Module[Module Code])) - COUNTROWS(Module), "
                     "\"Take\", COUNTROWS(VALUES(Take[Take Key])) - COUNTROWS(Take), "
                     "\"Triage\", COUNTROWS(VALUES(Triage[Group Id])) - COUNTROWS(Triage))")[0]
    check("no blank member in dimensions", not any(blanks.values()), f"({blanks})")

    # every measure evaluates (no DAX error) in the take's filter context
    row = ", ".join(f"\"{x['Name']}\", [{x['Name']}]" for x in measures)
    values = m.query(f"EVALUATE CALCULATETABLE(ROW({row}), Take[Take Key] = \"{take}\")")[0]
    check("every measure evaluates", len(values) == len(measures), f"({len(values)} values)")
    for k in ("Records Received", "Records Loaded", "Records Failed", "Load %", "Expected Failures", "Actionable Failures",
              "Answer Key Result", "Answer Key Summary", "Records to Fix", "Records to Fix Context", "Records on Fix List", "Agent Agreement %",
              "Groups to Review First", "Steps Failed", "Calls Blocked by PII Gate", "# AI Calls", "Fill-down Mismatches", "Last Published"):
        print(f"      {k:28} {values.get(k)}")

    # cross-checks between tables
    per_module = m.query(f"""
        EVALUATE CALCULATETABLE(
            ADDCOLUMNS(VALUES(Module[Module Code]),
                "Received", [Records Received], "Loaded", [Records Loaded], "Failed", [Records Failed],
                "KeyReceived", CALCULATE(SUM('Answer Key'[Actual Value]), 'Answer Key'[Metric] = "received"),
                "KeyLoaded", CALCULATE(SUM('Answer Key'[Actual Value]), 'Answer Key'[Metric] = "loaded"),
                "KeyFailed", CALCULATE(SUM('Answer Key'[Actual Value]), 'Answer Key'[Metric] = "failed")),
            Take[Take Key] = "{take}")""")
    bad = [r["Module Code"] for r in per_module
           if (r["Received"], r["Loaded"], r["Failed"]) != (r["KeyReceived"], r["KeyLoaded"], r["KeyFailed"])]
    check("module counts = answer-key actuals", not bad and len(per_module) == 9, f"(mismatch: {bad})" if bad else "(9 modules)")
    check("fix list = records to fix", values["Records on Fix List"] == values["Records to Fix"],
          f"({values['Records on Fix List']} vs {values['Records to Fix']})")
    check("client + cogsdale fixes = fix list", values["Client Fixes"] + values["Cogsdale Fixes"] == values["Records on Fix List"])
    status_sum = sum(values[k] for k in ("Checks Passed", "Checks Allowed", "Checks Reviewed", "Checks Failed", "Checks New"))
    check("answer-key statuses add up", status_sum == values["Checks"], f"({status_sum} of {values['Checks']})")
    check("failed = expected + actionable", values["Records Failed"] == values["Expected Failures"] + values["Actionable Failures"])
    # the fix list also carries warnings (records that loaded); its errors must be exactly the actionable failures
    split = m.query(f"""
        EVALUATE CALCULATETABLE(
            ROW("FixErrors", CALCULATE([Records to Fix], Triage[Severity] = "Error") + 0, "Actionable", [Actionable Failures]),
            Take[Take Key] = "{take}")""")[0]
    check("fix-list errors = actionable failures", split["FixErrors"] == split["Actionable"],
          f"({split['FixErrors']} vs {split['Actionable']})")
    by_group = m.query(f"""
        EVALUATE CALCULATETABLE(
            FILTER(ADDCOLUMNS(VALUES(Triage[Group Id]), "Fix", [Records on Fix List], "ToFix", [Records to Fix]), [Fix] <> [ToFix]),
            Take[Take Key] = "{take}")""")
    check("fix list filtered through triage groups", not by_group, f"({len(by_group)} groups differ)" if by_group else "")

    # full process: custody, gates, the load through the CSM procedures, runbook, client validation, take over take
    for k in ("Files Landed", "Findings", "Blocking Findings", "Gates Opened", "Gates Passed", "Gates Waiting", "Gates Auto-Approved",
              "Loaded to CSM", "Load Variance", "Control Amount Variance", "Runbook Steps", "Runbook Done", "Runbook Simulated",
              "Sample Accounts", "Fields Compared", "Field Differences", "Field Match %", "Cleansing Proposals", "Low-Confidence Proposals",
              "Groups New", "Groups Resolved", "Records Fixed Since Last Take", "Records Newly Flagged"):
        print(f"      {k:28} {values.get(k)}")
    if values.get("Runbook Steps"):                       # the take went through the load and publish steps
        check("load reconciles (records)", values["Load Variance"] == 0, f"({values['Load Variance']})")
        check("load reconciles (control totals)", abs(values["Control Amount Variance"] or 0) < 0.005, f"({values['Control Amount Variance']})")
        per_load = m.query(f"""
            EVALUATE CALCULATETABLE(
                FILTER(ADDCOLUMNS(VALUES(Module[Module Code]), "ToCsm", [Loaded to CSM], "Loaded", [Records Loaded]), [ToCsm] <> [Loaded]),
                Take[Take Key] = "{take}")""")
        check("loaded to CSM = records loaded, per module", not per_load, f"({per_load})" if per_load else "")
        check("runbook has every step", values["Runbook Steps"] == 54, f"({values['Runbook Steps']})")
        if values.get("Fields Compared"):
            same = round(values["Fields Compared"] * values["Field Match %"])
            check("validation sample adds up (same + different = compared)", same + values["Field Differences"] == values["Fields Compared"],
                  f"({same} + {values['Field Differences']} vs {values['Fields Compared']})")
    check("chain of custody recorded", (values.get("Files Landed") or 0) > 0, f"({values.get('Files Landed')} files)")
    check("no blocking drift", values.get("Blocking Findings") == 0)
    print(f"{'ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
