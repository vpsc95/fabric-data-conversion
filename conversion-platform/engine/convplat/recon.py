"""Reconciliation: turn the recon views into run-results.json (same shape as the answer key)."""
from __future__ import annotations

from .sqlio import query


def results(cn, client: str, take: str) -> dict:
    mods: dict = {}
    for r in query(cn, "SELECT * FROM recon.v_ModuleSummary WHERE ClientId = ? AND TakeId = ?", client, take):
        m = mods.setdefault(r["Module"], {"issues": {}})
        m.update(received=int(r["Received"]), loaded=int(r["Loaded"]), failed=int(r["Failed"]))
        if r["Module"] == "UMRM0101":
            m["received_distinct"] = int(r["ReceivedDistinct"])
    for r in query(cn, "SELECT * FROM recon.v_IssueSummary WHERE ClientId = ? AND TakeId = ?", client, take):
        m = mods.setdefault(r["Module"], {"issues": {}})
        m["issues"][r["RuleId"]] = {"count": int(r["Records"]), "severity": r["Severity"],
                                    "expected": int(r["Expected"]), "actionable": int(r["Actionable"])}
    for m in mods.values():
        m["actionable_total"] = sum(v["actionable"] for v in m["issues"].values() if v["severity"] == "E")
    for r in query(cn, "SELECT * FROM recon.v_FailedRecords WHERE ClientId = ? AND TakeId = ?", client, take):
        m = mods.setdefault(r["Module"], {"issues": {}})
        m["actionable_failed_records"] = int(r["ActionableFailedRecords"])
    for r in query(cn, "SELECT * FROM recon.v_ControlTotal WHERE ClientId = ? AND TakeId = ?", client, take):
        mods.setdefault(r["Module"], {"issues": {}}).setdefault("control_totals", {})[r["Name"].strip()] = round(float(r["Amount"] or 0), 2)
    return {"client": client, "take_id": take, "modules": mods}
