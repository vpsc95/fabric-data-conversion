"""Gate 3: a person's decisions on triage proposals, kept in Git (clients/<client>/triage/decisions.yaml).

A decision is keyed by the group's signature hash, so it applies to the same pattern on every later take:
an approved "expected" group becomes a deterministic exclusion (rules.usp_ApplyTriageDecisions) and stops
reaching the agent. Decisions are seeded into meta.TriageDecision by seed.py.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from .sqlio import query

HEADER = ("# Triage decisions (gate 3). Each entry is a person's decision on one issue group proposed by the triage agent.\n"
          "# Keyed by group_key, the hash of the group's signature (module + failed rules + code-level features), so a decision\n"
          "# applies to the same pattern on later takes. Edit with `run_local.py decide`, review by pull request.\n")


def path_for(client_dir: str | Path) -> Path:
    return Path(client_dir) / "triage" / "decisions.yaml"


def load(client_dir: str | Path) -> dict:
    p = path_for(client_dir)
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def save(client_dir: str | Path, client: str, decisions: list[dict]) -> Path:
    p = path_for(client_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"kind": "triage_decisions", "version": 1, "client": client,
           "decisions": sorted(decisions, key=lambda d: (d["module"], d["group_key"]))}
    p.write_text(HEADER + yaml.safe_dump(doc, sort_keys=False, width=140, allow_unicode=True), encoding="utf-8")
    return p


def seed(cn, client: str, client_dir: str | Path) -> int:
    doc = load(client_dir)
    cur = cn.cursor()
    cur.execute("DELETE meta.TriageDecision WHERE ClientId = ?", client)
    n = 0
    for d in doc.get("decisions", []) or []:
        cur.execute("INSERT meta.TriageDecision (ClientId, GroupKey, Module, Decision, Label, Owner, Category, Note, DecidedBy, DecidedOn) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", client, d["group_key"], d["module"], d["decision"], d["label"], d["owner"],
                    d["category"], d.get("note") or "", d["decided_by"], str(d["decided_on"]))
        n += 1
    return n


def record(cn, client: str, take: str, client_dir: str | Path, *, by: str, approve: list[str] = (), approve_all: bool = False,
           reject: list[str] = (), change: str | None = None, label: str | None = None, owner: str | None = None,
           category: str | None = None, note: str = "") -> dict:
    """Record decisions on this take's proposals (approve as proposed, change, or reject) and re-seed the database."""
    props = {p["GroupKey"].strip(): p for p in query(cn, "SELECT * FROM run.TriageProposal WHERE ClientId = ? AND TakeId = ?", client, take)}
    current = {d["group_key"]: d for d in (load(client_dir).get("decisions") or [])}
    today = dt.date.today().isoformat()
    targets = list(approve)
    if approve_all:
        targets += [k for k in props if k not in current]
    unknown = [k for k in targets + list(reject) + ([change] if change else []) if k not in props]
    if unknown:
        raise KeyError(f"no proposal for group(s) {unknown} in take {take}; run triage first")

    def entry(k, decision, lab, own, cat):
        p = props[k]
        return {"group_key": k, "module": p["Module"], "signature": f"{p['RuleSet']} | {p['Features']}", "title": p["Title"],
                "decision": decision, "label": lab, "owner": own, "category": cat, "note": note, "decided_by": by, "decided_on": today}

    for k in targets:
        p = props[k]
        current[k] = entry(k, "approved", p["AgentLabel"], p["Owner"], p["Category"])
    for k in reject:
        current[k] = entry(k, "rejected", "investigate", props[k]["Owner"], "needs_decision")
    if change:
        p = props[change]
        current[change] = entry(change, "changed", label or p["AgentLabel"], owner or p["Owner"], category or p["Category"])
    path = save(client_dir, client, list(current.values()))
    seeded = seed(cn, client, client_dir)
    return {"file": str(path), "decisions": seeded, "approved": len(targets), "rejected": len(reject), "changed": 1 if change else 0}
