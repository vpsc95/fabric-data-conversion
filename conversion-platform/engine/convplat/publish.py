"""Publish: snapshot one take's reconciliation, triage and run metadata into report tables (rpt_*).

The Power BI semantic model reads these in Direct Lake mode, which needs physical Delta tables (views don't
qualify), so each run copies the views' current state. Tables hold every take: a run replaces only its own
client and take, so takes can be compared.

`collect` reads the SQL database and returns one polars frame per table with an explicit schema (an
all-NULL column still gets its SQL type). Writing is the caller's job: the Fabric notebook writes to the
lakehouse, a local test can write anywhere.

Contents: codes, counts, rule texts, the agent's proposals and decisions, and (rpt_fix_list) the record
keys of the de-identified or client data the fix list is for. rpt_validation holds the client's validation
sample side by side (legacy vs converted values for about 50 accounts): data for the client's own validators,
row-level secured in production. Nothing here is sent to a model.
"""
from __future__ import annotations

import datetime as dt
import decimal

import polars as pl

from .triage import MODULE_NAMES

MODULE_ORDER = ["UMRM0101", "UMRM0111", "UM00600", "UM00600H", "UM00400", "UM00300", "UM20400", "UM01900", "UM30300"]
MODULE_AREA = {"UMRM0101": "Customers", "UMRM0111": "Customers", "UM00600": "Locations", "UM00600H": "Locations",
               "UM00400": "Equipment", "UM00300": "Connections", "UM20400": "Money", "UM01900": "Money", "UM30300": "Reads"}

QUERIES = {
    "rpt_module_summary": """
        SELECT s.ClientId, s.TakeId, s.Module, s.Received, s.ReceivedDistinct, s.Loaded, s.Failed,
               ISNULL(f.FailedRecords, 0) AS FailedRecords, ISNULL(f.ActionableFailedRecords, 0) AS ActionableFailedRecords,
               ISNULL(f.FailedRecords, 0) - ISNULL(f.ActionableFailedRecords, 0) AS ExpectedFailedRecords
        FROM recon.v_ModuleSummary s
        LEFT JOIN recon.v_FailedRecords f ON f.ClientId = s.ClientId AND f.TakeId = s.TakeId AND f.Module = s.Module
        WHERE s.ClientId = ? AND s.TakeId = ?""",
    "rpt_issue_summary": """
        SELECT s.ClientId, s.TakeId, s.Module, s.RuleId, s.Severity, CASE s.Severity WHEN 'E' THEN 'Error' ELSE 'Warning' END AS SeverityName, s.Records, s.Expected, s.Actionable,
               s.AnswerKeyRule, r.LegacyText, r.Description, o.AppliesTo AS ExpectedWhen, o.Reason AS ExpectedReason
        FROM recon.v_IssueSummary s
        LEFT JOIN meta.RuleCatalog r ON r.RuleId = s.RuleId
        LEFT JOIN meta.RuleOverride o ON o.ClientId = s.ClientId AND o.RuleId = s.RuleId
        WHERE s.ClientId = ? AND s.TakeId = ?""",
    "rpt_triage": """
        SELECT ClientId, TakeId, Module, GroupKey, CONCAT(ClientId, '/', TakeId, '/', GroupKey) AS GroupId,
               CONCAT(Module, ' · ', LEFT(COALESCE(Title, RuleSet), 70), ' [', LEFT(GroupKey, 4), ']') AS GroupLabel,
               RuleSet, Features, Severity, CASE Severity WHEN 'E' THEN 'Error' ELSE 'Warning' END AS SeverityName, Records, RuleClass, AgentLabel,
               ProposedOwner, ProposedCategory, Title, Action, ClientMessage, Rationale, CAST(Confidence AS float) AS Confidence,
               CallId, Observation, RootCause, ExcludedBy, AgentVsRules, DecisionStatus, FinalLabel, FinalOwner, FinalCategory,
               CASE WHEN FinalLabel <> 'expected' THEN Records END AS RecordsToFix,
               DecisionNote, DecidedBy, DecidedOn
        FROM recon.v_Triage WHERE ClientId = ? AND TakeId = ?""",
    "rpt_fix_list": """
        SELECT ClientId, TakeId, Module, Account, RowId, Severity, CASE Severity WHEN 'E' THEN 'Error' ELSE 'Warning' END AS SeverityName, RuleSet,
               Messages, GroupKey, CONCAT(ClientId, '/', TakeId, '/', GroupKey) AS GroupId, Title, ClientMessage,
               FinalLabel, FinalOwner, FinalCategory, DecisionStatus
        FROM recon.v_FixList WHERE ClientId = ? AND TakeId = ?""",
    "rpt_answer_key": """
        SELECT ClientId, TakeId, Module, Metric,
               CASE WHEN Metric LIKE 'issues.%' THEN CONCAT('Rule ', SUBSTRING(Metric, 8, 100))
                    WHEN Metric LIKE 'control[_]totals.%' THEN CONCAT('Control total ', SUBSTRING(Metric, 16, 100))
                    WHEN Metric = 'actionable_total' THEN 'Actionable total'
                    ELSE CONCAT(UPPER(LEFT(Metric, 1)), SUBSTRING(Metric, 2, 100)) END AS MetricLabel,
               Expected, Actual, Status,
               CASE Status WHEN 'FAIL' THEN 1 WHEN 'NEW' THEN 2 WHEN 'ALLOWED' THEN 3 WHEN 'REVIEWED' THEN 4 ELSE 5 END AS StatusOrder,
               TRY_CONVERT(float, REPLACE(REPLACE(Expected, ',', ''), '$', '')) AS ExpectedValue,
               TRY_CONVERT(float, REPLACE(REPLACE(Actual, ',', ''), '$', '')) AS ActualValue,
               TRY_CONVERT(float, REPLACE(REPLACE(Actual, ',', ''), '$', '')) - TRY_CONVERT(float, REPLACE(REPLACE(Expected, ',', ''), '$', '')) AS Difference,
               Reason, ApprovedBy, CheckedAt
        FROM run.AnswerKeyCheck WHERE ClientId = ? AND TakeId = ?""",
    "rpt_control_total": """
        SELECT ClientId, TakeId, Module, Name, Records, CAST(Amount AS float) AS Amount
        FROM recon.v_ControlTotal WHERE ClientId = ? AND TakeId = ?""",
    "rpt_step_metric": """
        SELECT ClientId, TakeId, Step, Item, Metric, CAST(Value AS float) AS Value, At
        FROM run.StepMetric WHERE ClientId = ? AND TakeId = ?""",
    "rpt_run_step": """
        SELECT l.ClientId, l.TakeId, l.RunLogId, l.StepName, l.StartedAt, l.EndedAt,
               CAST(DATEDIFF(millisecond, l.StartedAt, l.EndedAt) / 1000.0 AS float) AS Seconds, l.RowsAffected, l.Status,
               LEFT(ISNULL(l.Message, N''), 400) AS Message
        FROM run.RunLog l
        WHERE l.RunLogId IN (SELECT MAX(RunLogId) FROM run.RunLog WHERE ClientId = ? AND TakeId = ? GROUP BY StepName)""",
    "rpt_ai_call": """
        SELECT ClientId, TakeId, CallId, Agent, Deployment, Region, PromptSha256, PromptChars, ItemsSent, PiiCheck, Status,
               InputTokens, OutputTokens, LatencyMs, Message, CreatedAt
        FROM run.AiCall WHERE ClientId = ? AND TakeId = ?""",
    # --- full process: gates, custody and drift, loader, runbook, client validation, take over take, cleansing
    "rpt_gate": """
        SELECT ClientId, TakeId, CAST(Gate AS int) AS Gate, CONCAT(Gate, ' · ', GateName) AS GateLabel, GateName, DecidedByRole, Status,
               OpenedAt, DecidedBy, DecidedAt, Note, IsPassed
        FROM run.v_Gate WHERE ClientId = ? AND TakeId = ?""",
    "rpt_landing_file": """
        SELECT ClientId, TakeId, FileName, SizeBytes, Sha256, ModifiedUtc, SpecId, Sheets, RecordedAt
        FROM run.LandingFile WHERE ClientId = ? AND TakeId = ?""",
    "rpt_drift": """
        SELECT ClientId, TakeId, FindingId, Kind, Severity, CASE Severity WHEN 'blocking' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END AS SeverityOrder,
               FileName, ColumnName, Detail, ComparedTo, CreatedAt
        FROM run.DriftFinding WHERE ClientId = ? AND TakeId = ?""",
    "rpt_post_load": """
        SELECT ClientId, TakeId, Module, ModuleName, ExpectedToLoad, Loaded, Failed, EmulatorRows, Variance, ControlName,
               CAST(AmountVariance AS float) AS AmountVariance
        FROM recon.v_PostLoad WHERE ClientId = ? AND TakeId = ?""",
    "rpt_runbook": """
        SELECT r.ClientId, r.TakeId, s.StepNo, s.Block, s.Title, s.Kind, s.Executor, s.PrototypeMode, r.Status, r.Evidence, r.Message
        FROM run.RunbookStepRun r
        JOIN meta.RunbookStep s ON s.ClientId = r.ClientId AND s.StepNo = r.StepNo
        WHERE r.ClientId = ? AND r.TakeId = ?""",
    "rpt_validation": """
        SELECT ClientId, TakeId, LegacyAcctNo, Stratum, CAST(StratumOrder AS int) AS StratumOrder, Reason, FieldOrder, Field, CompareAs,
               LegacyValue, ConvertedValue, Matches
        FROM recon.v_ValidationSideBySide WHERE ClientId = ? AND TakeId = ?""",
    "rpt_take_diff": """
        SELECT ClientId, TakeId, PrevTakeId, Module, GroupKey, RuleSet, Features, RuleClass, PrevRecords, Records, Change, Status,
               CASE Status WHEN 'new' THEN 1 WHEN 'grown' THEN 2 WHEN 'shrunk' THEN 3 WHEN 'resolved' THEN 4 ELSE 5 END AS StatusOrder
        FROM recon.v_TakeDiffGroup WHERE ClientId = ? AND TakeId = ?""",
    "rpt_take_diff_record": """
        SELECT ClientId, TakeId, PrevTakeId, Module, Status, Records
        FROM recon.v_TakeDiffRecord WHERE ClientId = ? AND TakeId = ?""",
    "rpt_cleanse": """
        SELECT ClientId, TakeId, Module, RuleId, Proposals, High, Low, Approved, Rejected, Pending
        FROM recon.v_CleanseSummary WHERE ClientId = ? AND TakeId = ?""",
}

_TYPES = {str: pl.Utf8, int: pl.Int64, float: pl.Float64, bool: pl.Boolean, decimal.Decimal: pl.Float64,
          dt.datetime: pl.Datetime("us"), dt.date: pl.Date, bytes: pl.Binary}


def _frame(cur) -> pl.DataFrame:
    names = [d[0] for d in cur.description]
    schema = {n: _TYPES.get(d[1], pl.Utf8) for n, d in zip(names, cur.description)}
    rows = cur.fetchall()
    data = {n: [(float(v) if isinstance(v, decimal.Decimal) else v) for v in (r[i] for r in rows)] for i, n in enumerate(names)}
    return _with_take_key(pl.DataFrame(data, schema=schema))


def _with_take_key(df: pl.DataFrame) -> pl.DataFrame:
    # one key column for the Take relationship (a semantic model can't relate on ClientId + TakeId)
    if {"ClientId", "TakeId"} <= set(df.columns):
        return df.with_columns(TakeKey=pl.col("ClientId") + "/" + pl.col("TakeId"))
    return df


def collect(cn, client: str, take: str, published_at: dt.datetime | None = None) -> dict[str, pl.DataFrame]:
    out = {}
    for name, sql in QUERIES.items():
        cur = cn.cursor()
        cur.execute(sql, client, take)
        out[name] = _frame(cur)
    out["rpt_module"] = pl.DataFrame({"Module": MODULE_ORDER, "ModuleName": [MODULE_NAMES[m] for m in MODULE_ORDER],
                                      "Area": [MODULE_AREA[m] for m in MODULE_ORDER],
                                      "SortOrder": list(range(1, len(MODULE_ORDER) + 1))},
                                     schema={"Module": pl.Utf8, "ModuleName": pl.Utf8, "Area": pl.Utf8, "SortOrder": pl.Int64})
    cur = cn.cursor()
    cur.execute("SELECT Name, ConversionDate FROM meta.Client WHERE ClientId = ?", client)
    row = cur.fetchone()
    cur.execute("SELECT TakeDate, Simulated FROM run.Take WHERE ClientId = ? AND TakeId = ?", client, take)
    tk = cur.fetchone()
    out["rpt_run"] = _with_take_key(pl.DataFrame({"ClientId": [client], "TakeId": [take], "ClientName": [row[0] if row else client],
                                                  "ConversionDate": [row[1] if row else None],
                                                  "TakeDate": [tk[0] if tk else None], "Simulated": [bool(tk[1]) if tk else False],
                                                  "PublishedAt": [published_at or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)]},
                                                 schema={"ClientId": pl.Utf8, "TakeId": pl.Utf8, "ClientName": pl.Utf8,
                                                         "ConversionDate": pl.Date, "TakeDate": pl.Date, "Simulated": pl.Boolean,
                                                         "PublishedAt": pl.Datetime("us")}))
    check_keys(out)
    return out


def check_keys(frames: dict[str, pl.DataFrame]) -> None:
    """The semantic model's relationships assume referential integrity (Direct Lake then joins with inner-join
    semantics and adds no blank member), so a fact row whose key has no dimension row would silently drop out of
    every visual. Refuse to publish instead."""
    modules, takes = set(MODULE_ORDER), set(frames["rpt_run"]["TakeKey"])
    groups = set(frames["rpt_triage"]["GroupId"])
    problems = []
    for name, df in frames.items():
        if "Module" in df.columns and name != "rpt_module":
            bad = set(df["Module"]) - modules
            if bad:
                problems.append(f"{name}: modules not in rpt_module: {sorted(bad)}")
        if "TakeKey" in df.columns and name != "rpt_run":
            bad = set(df["TakeKey"]) - takes
            if bad:
                problems.append(f"{name}: takes not in rpt_run: {sorted(bad)}")
    bad = set(frames["rpt_fix_list"]["GroupId"]) - groups
    if bad:
        problems.append(f"rpt_fix_list: {len(bad)} group(s) not in rpt_triage")
    if problems:
        raise ValueError("report tables would break the model's relationships: " + "; ".join(problems))


def merge_take(existing: pl.DataFrame | None, new: pl.DataFrame, client: str, take: str) -> pl.DataFrame:
    """Other takes' rows from the existing table plus this take's new rows. Shared tables (no ClientId) are replaced."""
    if existing is None or "ClientId" not in new.columns or set(existing.columns) != set(new.columns):
        return new
    keep = existing.filter(~((pl.col("ClientId") == client) & (pl.col("TakeId") == take)))
    return pl.concat([keep.select(new.columns).cast(new.schema), new]) if keep.height else new
