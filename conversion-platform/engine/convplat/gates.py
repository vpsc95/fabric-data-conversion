"""The six human gates of a take (tables and procedures in sql/14_gates.sql).

  open_gate(cn, client, take, gate, evidence, needed)   pending (or not_needed) with the evidence the approver sees
  decide(cn, client, take, gate, decision, by, note)    a person approves or rejects a pending gate
  wait(cn, client, take, gate, ...)                     hold a pipeline step until the gate is decided
  status(cn, client, take)                              the six gates and their state

Evidence is metadata only (counts, rule codes, findings), the same rule as for the AI agents. A demo run may
auto-approve gates 4 and 5; the decision is then recorded as auto_approved by the pipeline parameter, never as a
person's approval.
"""
from __future__ import annotations

import json
import time

from . import sqlio

GATES = {1: "Spec change", 2: "Low-confidence fixes", 3: "Triage", 4: "Load go / no-go", 5: "Publish", 6: "Take acceptance"}
PASSED = ("approved", "auto_approved", "not_needed")


class GateRejected(RuntimeError):
    pass


def open_gate(cn, client: str, take: str, gate: int, evidence: dict, needed: bool = True, actor: str = "platform") -> str:
    status = "pending" if needed else "not_needed"
    sqlio.exec_proc(cn, "EXEC run.usp_OpenGate ?, ?, ?, ?, ?, ?", client, take, gate,
                    json.dumps(evidence, ensure_ascii=False, default=str), status, actor)
    return status


def decide(cn, client: str, take: str, gate: int, decision: str, by: str, note: str = "") -> None:
    sqlio.exec_proc(cn, "EXEC run.usp_DecideGate ?, ?, ?, ?, ?, ?", client, take, gate, decision, by, note or None)


def gate_status(cn, client: str, take: str, gate: int) -> str | None:
    row = cn.cursor().execute("SELECT Status FROM run.Gate WHERE ClientId = ? AND TakeId = ? AND Gate = ?", client, take, gate).fetchone()
    return row[0] if row else None


def wait(cn, client: str, take: str, gate: int, timeout_s: int = 3600, poll_s: int = 20, auto_approve: bool = False) -> str:
    """Return once the gate has passed; raise GateRejected or TimeoutError otherwise."""
    st = gate_status(cn, client, take, gate)
    if st is None:
        raise RuntimeError(f"gate {gate} ({GATES[gate]}) was never opened for {client}/{take}")
    if st == "pending" and auto_approve:
        decide(cn, client, take, gate, "auto_approved", "pipeline (auto_approve parameter)",
               "Demo run: no person decided this gate; the run continued because auto_approve was set.")
        return "auto_approved"
    deadline = time.time() + timeout_s
    while True:
        st = gate_status(cn, client, take, gate)
        if st in PASSED:
            return st
        if st == "rejected":
            raise GateRejected(f"gate {gate} ({GATES[gate]}) was rejected for {client}/{take}")
        if time.time() >= deadline:
            raise TimeoutError(f"gate {gate} ({GATES[gate]}) still pending after {timeout_s} s for {client}/{take}")
        time.sleep(poll_s)


def status(cn, client: str, take: str) -> list[dict]:
    return sqlio.query(cn, "SELECT Gate, GateName, DecidedByRole, Status, OpenedAt, DecidedBy, DecidedAt, Note FROM run.v_Gate "
                           "WHERE ClientId = ? AND TakeId = ? ORDER BY Gate", client, take)


# ---------------------------------------------------------------------------------------------- evidence
def evidence_gate1(summary: dict, findings: list[dict], compared_to: str | None) -> dict:
    return {"what": "Do the approved specs still fit what the client sent?", "compared_to": compared_to or "approved specs (first take)",
            "blocking": summary["blocking"], "warnings": summary["warning"], "info": summary["info"],
            "findings": [{k: x.get(k) for k in ("severity", "kind", "file", "column", "detail")}
                         for x in findings if x["severity"] != "info"][:50]}


def evidence_gate3(cn, client: str, take: str) -> dict:
    row = sqlio.query(cn, "SELECT COUNT(*) AS Groups, SUM(CASE WHEN DecisionStatus = 'pending' THEN 1 ELSE 0 END) AS Pending, "
                          "SUM(CASE WHEN AgentVsRules = 'disagrees' THEN 1 ELSE 0 END) AS Disagree, "
                          "SUM(CASE WHEN FinalLabel <> 'expected' THEN Records ELSE 0 END) AS RecordsToFix "
                          "FROM recon.v_Triage WHERE ClientId = ? AND TakeId = ?", client, take)[0]
    return {"what": "Approve, edit or reject the triage proposals; then the fix-in-source list goes to the client.",
            "issue_groups": row["Groups"], "pending_decisions": row["Pending"] or 0,
            "agent_disagrees_with_rules": row["Disagree"] or 0, "records_to_fix": row["RecordsToFix"] or 0}


def evidence_gate4(cn, client: str, take: str) -> dict:
    mods = sqlio.query(cn, "SELECT Module, Received, Loaded, Failed FROM recon.v_ModuleSummary WHERE ClientId = ? AND TakeId = ? ORDER BY Module",
                       client, take)
    key = sqlio.query(cn, "SELECT Status, COUNT(*) AS n FROM run.AnswerKeyCheck WHERE ClientId = ? AND TakeId = ? GROUP BY Status", client, take)
    return {"what": "Pre-load reconciliation: go or no-go for the load into CSM.",
            "modules": mods, "answer_key": {r["Status"]: r["n"] for r in key},
            "will_load": sum(m["Loaded"] or 0 for m in mods), "will_not_load": sum(m["Failed"] or 0 for m in mods),
            "backups": "simulated in the prototype (no GP server); production backs up CONV through the gateway first"}
