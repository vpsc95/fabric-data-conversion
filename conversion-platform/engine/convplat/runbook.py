"""Runbook metadata and prototype execution for conversion process P12.

The legacy SAMPLE report carried a printed 54-step execution sequence. This module loads the
generalized YAML form and records, for one take, which steps the prototype actually performed,
which legacy infrastructure steps are simulated, and which approval gates are waiting.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import yaml

from . import sqlio

VALID_STATUS = {"done", "simulated", "eliminated", "waiting", "skipped", "failed"}


def load_runbook(client_dir: str | Path) -> dict[str, Any]:
    path = Path(client_dir) / "runbook.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    if len(steps) != 54:
        raise ValueError(f"{path} must contain 54 steps; found {len(steps)}")
    seen = set()
    for step in steps:
        no = int(step["number"])
        if no in seen:
            raise ValueError(f"duplicate runbook step {no}")
        seen.add(no)
    if seen != set(range(1, 55)):
        raise ValueError("runbook steps must be numbered 1 through 54")
    return data


def ensure_schema(cn, platform_dir: str | Path) -> None:
    sqlio.run_sql(cn, (Path(platform_dir) / "sql" / "18_runbook.sql").read_text(encoding="utf-8"), "18_runbook.sql")


def seed_steps(cn, client_dir: str | Path) -> int:
    rb = load_runbook(client_dir)
    client = rb["client"]
    cur = cn.cursor()
    cur.execute("DELETE meta.RunbookStep WHERE ClientId = ?", client)
    for s in rb["steps"]:
        cur.execute(
            "INSERT meta.RunbookStep (ClientId, StepNo, Block, Title, Kind, Executor, PrototypeMode) VALUES (?,?,?,?,?,?,?)",
            client,
            int(s["number"]),
            s["block"],
            s["title"][:220],
            s["kind"],
            s["target_executor"][:220],
            s["prototype_mode"],
        )
    return len(rb["steps"])


def _one(cn, sql: str, *params) -> dict[str, Any] | None:
    rows = sqlio.query(cn, sql, *params)
    return rows[0] if rows else None


def _table_exists(cn, name: str) -> bool:
    return bool(sqlio.query(cn, "SELECT 1 AS ok WHERE OBJECT_ID(?) IS NOT NULL", name))


def _gate_status(cn, client: str, take: str, gate: int) -> tuple[str, str]:
    if not _table_exists(cn, "run.Gate"):
        return "waiting", f"Gate {gate} table not present in this prototype database."
    rows = sqlio.query(cn, "SELECT TOP (1) Status, DecidedBy, DecidedAt FROM run.Gate WHERE ClientId = ? AND TakeId = ? AND Gate = ? ORDER BY DecidedAt DESC", client, take, gate)
    if not rows:
        return "waiting", f"Gate {gate} has no decision row."
    row = rows[0]
    status = str(row["Status"])
    if status in ("approved", "auto_approved"):
        return "done", f"Gate {gate} {status} by {row.get('DecidedBy') or 'system'} at {row.get('DecidedAt')}."
    if status == "rejected":
        return "failed", f"Gate {gate} rejected by {row.get('DecidedBy') or 'approver'}."
    return "waiting", f"Gate {gate} status is {status}."


def _latest_runlog(cn, client: str, take: str, pattern: str) -> dict[str, Any] | None:
    return _one(
        cn,
        "SELECT TOP (1) StepName, StartedAt, EndedAt, RowsAffected, Status, Message FROM run.RunLog "
        "WHERE ClientId = ? AND TakeId = ? AND StepName LIKE ? ORDER BY RunLogId DESC",
        client,
        take,
        pattern,
    )


def _metric_summary(cn, client: str, take: str) -> str:
    rows = sqlio.query(
        cn,
        "SELECT COUNT(*) AS MetricRows, SUM(CASE WHEN Metric = 'rows_kept' THEN Value ELSE 0 END) AS RowsKept "
        "FROM run.StepMetric WHERE ClientId = ? AND TakeId = ? AND Step = 'reshape'",
        client,
        take,
    )
    if not rows:
        return "No reshape metrics were found."
    return f"{int(rows[0]['MetricRows'] or 0)} reshape metrics; {int(rows[0]['RowsKept'] or 0)} silver rows kept."


def _module_summary(cn, client: str, take: str, module: str) -> str:
    rows = sqlio.query(cn, "SELECT Received, Loaded, Failed FROM recon.v_ModuleSummary WHERE ClientId = ? AND TakeId = ? AND Module = ?", client, take, module)
    if not rows:
        return f"No reconciliation row for {module}."
    r = rows[0]
    return f"{module}: received {int(r['Received'])}, loaded {int(r['Loaded'])}, failed {int(r['Failed'])}."


def _answer_key_summary(cn, client: str, take: str) -> str:
    rows = sqlio.query(cn, "SELECT Status, COUNT(*) AS Cnt FROM run.AnswerKeyCheck WHERE ClientId = ? AND TakeId = ? GROUP BY Status", client, take)
    if not rows:
        return "Answer-key comparison has not been recorded."
    counts = {str(r["Status"]).upper(): int(r["Cnt"]) for r in rows}
    return ", ".join(f"{counts.get(status, 0)} {status}" for status in ("PASS", "ALLOWED", "REVIEWED", "FAIL", "NEW"))


def _status_for_step(cn, client: str, take: str, step: dict[str, Any]) -> tuple[str, dt.datetime | None, dt.datetime | None, str, str]:
    no = int(step["number"])
    mode = step["prototype_mode"]
    params = step.get("parameters") or {}
    if step.get("kind") == "approval":
        status, msg = _gate_status(cn, client, take, int(params.get("gate", 0) or 0))
        return status, None, None, "run.Gate", msg
    if mode == "eliminated":
        return "eliminated", None, None, "Runbook metadata", "Legacy Excel/file-prep work is eliminated by file variables, text landing, and reshape specs."
    if no == 12:
        return "done", None, None, "run.StepMetric", _metric_summary(cn, client, take)
    if no == 13:
        r = _latest_runlog(cn, client, take, "gold.%")
        if r:
            return "done" if r["Status"] == "Succeeded" else "failed", r["StartedAt"], r["EndedAt"], "run.RunLog gold.*", f"Latest build step {r['StepName']} affected {r['RowsAffected']} rows."
        return "failed", None, None, "run.RunLog", "No gold build run-log rows found."
    module = params.get("module")
    if module and str(module).startswith("UM"):
        msg = _module_summary(cn, client, take, module)
        if mode == "implemented":
            # the loader writes recon.v_PostLoad: the step is done when everything expected loaded with no variance
            post = _one(cn, "SELECT ExpectedToLoad, Loaded, Failed, Variance FROM recon.v_PostLoad "
                            "WHERE ClientId = ? AND TakeId = ? AND Module = ? AND ControlName IS NULL", client, take, module) \
                if _table_exists(cn, "load.RowStatus") else None
            if post is None or not post["ExpectedToLoad"]:
                return "waiting", None, None, "recon.v_PostLoad", msg + " Validated; waiting for gate 4 and the loader."
            ok = int(post["Failed"] or 0) == 0 and int(post["Variance"] or 0) == 0
            return ("done" if ok else "failed"), None, None, "recon.v_PostLoad", \
                msg + f" Loaded {int(post['Loaded'])} of {int(post['ExpectedToLoad'])} into the CONV emulator (shadow mode); " \
                      f"failed {int(post['Failed'] or 0)}, variance {int(post['Variance'] or 0)}."
        return "simulated", None, None, "recon.v_ModuleSummary", msg + " Loader execution is simulated because GP/CSM infrastructure is not connected."
    if mode == "simulated":
        return "simulated", None, None, "Parameterized command", json.dumps(params, sort_keys=True)
    if mode == "manual":
        return "waiting", None, None, "Manual checklist", "Manual GP/SQL Server verification remains outside the prototype."
    return "skipped", None, None, "Runbook metadata", "No prototype action mapped."


def execute(cn, client_dir: str | Path, take: str) -> dict[str, int]:
    rb = load_runbook(client_dir)
    client = rb["client"]
    cur = cn.cursor()
    cur.execute("DELETE run.RunbookStepRun WHERE ClientId = ? AND TakeId = ?", client, take)
    counts: dict[str, int] = {}
    for step in rb["steps"]:
        status, started, ended, evidence, message = _status_for_step(cn, client, take, step)
        if status not in VALID_STATUS:
            raise ValueError(status)
        cur.execute(
            "INSERT run.RunbookStepRun (ClientId, TakeId, StepNo, Status, StartedAt, EndedAt, Evidence, Message) VALUES (?,?,?,?,?,?,?,?)",
            client,
            take,
            int(step["number"]),
            status,
            started,
            ended,
            evidence[:1000],
            message[:1000],
        )
        counts[status] = counts.get(status, 0) + 1
    counts["steps"] = len(rb["steps"])
    counts["answer_key_rows"] = sum(int(r["Cnt"]) for r in sqlio.query(cn, "SELECT COUNT(*) AS Cnt FROM run.AnswerKeyCheck WHERE ClientId = ? AND TakeId = ?", client, take))
    counts["answer_key_summary"] = _answer_key_summary(cn, client, take)  # type: ignore[assignment]
    return counts
