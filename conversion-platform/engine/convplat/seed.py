"""Seed the platform database from the specs: rules, client overrides, crosswalks, CSM setup.

Everything here is metadata from Git (reviewed by pull request); no client data.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .specs import ClientSpecs
from .sqlio import table_columns

GOLD_TABLE = {"UMRM0101": "gold.UM_Customer", "UMRM0111": "gold.UM_Customer", "UM00600": "gold.UM_Location",
              "UM00400": "gold.UM_Equipment", "UM00300": "gold.UM_Connection", "UM20400": "gold.UM_BegBalance",
              "UM01900": "gold.UM_Deposit", "UM30300": "gold.UM_HistMR"}
# Corrections to catalog entries found while porting (each one documented in the rule's Description).
CONDITION_FIX = {
    "BAL_AMOUNT_NUMERIC": "TRY_CAST(BBAmount AS numeric(19,5)) IS NULL",   # legacy reviewer 20260128 replaced ISNUMERIC
}
FORCE_KIND = {"CONN_DUPLICATE": "cross",             # needs the duplicate join, in rules.usp_Validate_Connection
              "ADDR_SMARTY_NO_MATCH": "external"}    # needs SmartyStreets output (not in the extracts)
SQL_WORDS = {"LEN", "ISNUMERIC", "ISDATE", "NOT", "IN", "AND", "OR", "IS", "NULL", "TRY_CAST", "AS", "NUMERIC", "CONVERT",
             "SMALLINT", "ISNULL", "LTRIM", "RTRIM", "LEFT", "RIGHT", "UPPER"}


def _status(r: dict) -> str:
    s = r.get("legacy_status")
    return s.get("status", "active") if isinstance(s, dict) else (s or "active")


def _columns_in(cond: str) -> set[str]:
    cond = re.sub(r"'[^']*'", "", cond)
    return {w for w in re.findall(r"\[?([A-Za-z_][A-Za-z0-9_]*)\]?", cond) if w.upper() not in SQL_WORDS and not w.isdigit()}


def seed(cn, platform_dir: str | Path, client_dir: str | Path) -> dict:
    platform_dir, specs = Path(platform_dir), ClientSpecs(client_dir)
    client = specs.client
    cur = cn.cursor()
    counts = {}

    # client
    cur.execute("DELETE meta.Client WHERE ClientId = ?", client)
    cur.execute("INSERT meta.Client (ClientId, Name, ConversionDate) VALUES (?, ?, ?)",
                client, client.upper(), specs.take.get("conversion_date"))

    # rules (global catalog)
    catalog = yaml.safe_load((platform_dir / "rules" / "catalog.yaml").read_text(encoding="utf-8"))["rules"]
    gold_cols = {t: {c.upper() for c in table_columns(cn, t)} for t in set(GOLD_TABLE.values())}
    cur.execute("DELETE meta.RuleCatalog")
    rows = []
    for r in catalog:
        gold = GOLD_TABLE.get(r["module"])
        cond = CONDITION_FIX.get(r["id"], str(r.get("condition_sql") or ""))
        kind = "cross" if (re.search(r"(?i)\bselect\b|\bjoin\b|\bexists\b", cond) or r.get("cross_entity")) else "simple"
        kind = FORCE_KIND.get(r["id"], kind)
        note = ""
        if gold is None:
            kind, note = "external", "no staging table in this platform version"
        elif kind == "simple" and not {c.upper() for c in _columns_in(cond)} <= gold_cols[gold]:
            kind, note = "external", "column not staged"
        desc = (r.get("description") or "") + (f" [{note}]" if note else "") + (" [condition corrected while porting]" if r["id"] in CONDITION_FIX else "")
        rows.append((r["id"], r["module"], r["severity"], 1 if _status(r) == "active" else 0, r.get("legacy_issue_text") or r["id"],
                     desc[:800], str(r.get("source") or "")[:200], r.get("answer_key_rule"), kind, gold, cond if kind == "simple" else None))
    cur.fast_executemany = True
    cur.executemany("INSERT meta.RuleCatalog (RuleId, Module, Severity, Enabled, LegacyText, Description, LegacySource, AnswerKeyRule, "
                    "RuleKind, GoldTable, ConditionSql) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    counts["rules"] = len(rows)
    counts["rules_simple"] = sum(1 for x in rows if x[8] == "simple")

    # client overrides
    cur.fast_executemany = False
    cur.execute("DELETE meta.RuleOverride WHERE ClientId = ?", client)
    n = 0
    for p in sorted((Path(client_dir) / "rules").glob("*.yaml")):
        for o in yaml.safe_load(p.read_text(encoding="utf-8")).get("overrides", []):
            ex = o.get("expected_exclusion") or {}
            # the exclusion's own reason is the specific one (e.g. the Jira ticket); the override reason is a summary
            cur.execute("INSERT meta.RuleOverride (ClientId, RuleId, Enabled, Severity, ExpectedWhen, AppliesTo, Reason) VALUES (?,?,?,?,?,?,?)",
                        client, o["rule"], o.get("enabled"), o.get("severity"), ex.get("when"), ex.get("applies_to"),
                        ex.get("reason") or o.get("reason") or "")
            n += 1
    counts["overrides"] = n

    # crosswalks
    cur.execute("DELETE xref.CrosswalkValue WHERE ClientId = ?", client)
    rows = []
    for cw_id, cw in specs.crosswalks.items():
        for v in cw.get("values", []):
            inc, reason = 1 if v.get("include", True) else 0, str(v.get("reason") or "")
            for attr, val in v.items():
                if attr in ("legacy_code", "include", "reason"):
                    continue
                rows.append((client, cw_id, str(v["legacy_code"]), attr, "" if val is None else str(val), inc, reason[:400]))
    cur.fast_executemany = True
    cur.executemany("INSERT xref.CrosswalkValue (ClientId, CrosswalkId, LegacyCode, Attribute, Value, Include, Reason) VALUES (?,?,?,?,?,?,?)", rows)
    counts["crosswalk_values"] = len(rows)

    # CSM setup (provisional or snapshot)
    cur.execute("DELETE ref.SetupValue WHERE ClientId = ?", client)
    rows = []
    for p in sorted((Path(client_dir) / "setup").glob("*.yaml")):
        s = yaml.safe_load(p.read_text(encoding="utf-8"))
        for table, values in s.get("tables", {}).items():
            for v in values:
                rows.append((client, table, v["code"], v["source"], (v.get("note") or "")[:400]))
    if rows:
        cur.executemany("INSERT ref.SetupValue (ClientId, SetupTable, Code, Source, Note) VALUES (?,?,?,?,?)", rows)
    counts["setup_values"] = len(rows)

    # gate-3 triage decisions (clients/<client>/triage/decisions.yaml)
    from . import decisions
    cur.fast_executemany = False
    counts["triage_decisions"] = decisions.seed(cn, client, client_dir)
    return counts
