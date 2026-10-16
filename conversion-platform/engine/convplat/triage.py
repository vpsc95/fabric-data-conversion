"""Triage agent: labels issue groups (expected / actionable / investigate) and writes the fix wording.

Design rules (architecture section 5):
- The agent reads ONLY recon.v_TriageContext (codes and counts) plus rule metadata and the approved
  exclusions. It never sees records, names, addresses, account numbers or meter numbers.
- A PII gate checks the exact prompt before it leaves; anything that looks like personal data blocks the
  call (fix the context builder, don't redact by hand).
- Output is JSON validated against a schema and stored as proposals (run.TriageProposal). Nothing is
  applied until a person decides (meta.TriageDecision, from clients/<client>/triage/decisions.yaml).
  Until then the approved rules decide what is on the fix list; a proposal that disagrees with them is
  flagged for review first (recon.v_Triage.AgentVsRules).
- Numbers never come from the model: record counts are joined from SQL.
- Every call is audited in run.AiCall (endpoint, deployment, region, prompt hash and size, PII result,
  tokens, latency) - metadata only.
- Quality: precision and recall of the agent's labels against what the approved rules say (RuleClass).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .sqlio import query

MODULE_NAMES = {"UMRM0101": "Customer", "UMRM0111": "Customer address", "UM00600": "Location", "UM00600H": "Location history",
                "UM00400": "Equipment (meter)", "UM00300": "Connection (a service at a location)", "UM20400": "Beginning balance",
                "UM01900": "Deposit", "UM30300": "Historical meter read"}
LABELS = ["expected", "actionable", "investigate"]
OWNERS = ["client", "cogsdale", "none"]
CATEGORIES = ["expected_by_design", "fix_in_source", "fix_in_mapping", "fix_in_setup", "needs_decision"]
ROOT_CAUSES = ["excluded by an approved exclusion", "source data", "conversion logic", "CSM setup", "business decision needed", "unclear"]

SYSTEM = """You are the triage agent of a data-conversion platform for a utility billing system (Cogsdale CSM on Microsoft Dynamics GP).
Validation rules have run on the staged records of one conversion take. You receive issue GROUPS: records of one module that failed
the same set of rules and share the same code-level features. You never see individual records.

For EVERY group return exactly one entry, filling the fields in this order:
- group: the group id you were given (G01, G02, ...).
- observation: one sentence on what the failed rules and features show.
- excluded_by: for each rule in the group's exclusions_to_check, read that exclusion's applies_to in approved_exclusions. When
  applies_to describes the group, put that rule id here. Otherwise an empty string; a group whose exclusions_to_check is empty is
  never excluded.
- root_cause: one of the listed values.
- label: "expected" when excluded_by is not empty (left out of the conversion on purpose). "actionable" when someone must fix source
  data, mapping or CSM setup. "investigate" when the information given isn't enough to decide.
- owner: "client" (fix in the client's source system or extract), "cogsdale" (mapping, crosswalk, CSM setup or conversion rule), or
  "none" (expected).
- category: expected_by_design, fix_in_source, fix_in_mapping, fix_in_setup or needs_decision.
- title: plain English, at most 12 words.
- action: what the owner should do, concretely.
- client_message: one or two plain-English sentences the client can act on, with no rule ids or codes they wouldn't know; empty when
  the owner isn't the client.
- rationale: why, citing the failed rules and the features.
- confidence: 0 to 1.

Policies:
- A record that fails a rule that is excluded by design is excluded by design; its other issues are expected too.
- Use csm_setup when you need to know which service types or rates exist in CSM.
- precedents are corrections people made to earlier proposals; follow them for groups with the same rules and similar features.
- Severity E means the record is skipped at load. Severity W is a warning: the record still loads, but the client should fix it.
- Do not state counts or numbers of records; the platform adds them from its own data.
- Use only the codes and facts in the input. Don't invent setup values or rules.

Choosing owner and category:
- client + fix_in_source: the source system's data is wrong or incomplete (blank or invalid values, a meter missing from the AMI export,
  a value too long for CSM, an account without a premise or location).
- cogsdale + fix_in_mapping: the conversion lost or mis-derived data that the extract does contain (a value read from the wrong column,
  a derivation that leaves a field blank, a rule that should treat a case differently).
- cogsdale + fix_in_setup: a code the mapping produces is not set up in CSM.
- needs_decision: a business decision is needed first (for example whether a service type should be converted at all).
- none + expected_by_design: excluded by an approved exclusion."""

FEATURE_NOTES = {
    "service": "legacy service code and description from the services report (first 3 digits are the code)",
    "serviceType / rate / tariff": "values the mapping derived for CSM; rate WR or WC alone means no meter size was found for the meter",
    "rateTable": "legacy rate-table code of the service",
    "meterInRateTableColumn": "yes when the printed report put this service's meter number (or PULLED) in the rate-table column; "
                              "the conversion reads the meter from the separate meter column",
    "slot": "1 or 2: the report shows up to two services side by side per line",
    "meter": "blank = no meter on the connection; 'not in equipment' = the meter isn't in the AMI meter export the equipment is built from",
    "readDate": "shape of the reading date (9 = digit); blank = no date in the AMI export",
    "accountStatus": "status of the legacy account in the CUSTOMERS extract",
    "customer / location": "whether the read, balance or deposit could be tied to a converted customer and location",
}

OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["groups"],
    "properties": {"groups": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        # reasoning fields come first on purpose: the model writes them before it commits to a label
        "required": ["group", "observation", "excluded_by", "root_cause", "label", "owner", "category", "title", "action",
                     "client_message", "rationale", "confidence"],
        "properties": {
            "group": {"type": "string"},
            "observation": {"type": "string"},
            "excluded_by": {"type": "string"},
            "root_cause": {"type": "string", "enum": ROOT_CAUSES},
            "label": {"type": "string", "enum": LABELS},
            "owner": {"type": "string", "enum": OWNERS},
            "category": {"type": "string", "enum": CATEGORIES},
            "title": {"type": "string"},
            "action": {"type": "string"},
            "client_message": {"type": "string"},
            "rationale": {"type": "string"},
            "confidence": {"type": "number"}}}}}}
BATCHES = [["UM00300"], ["UM30300"]]          # everything else goes in one more batch

# --- context -------------------------------------------------------------------------------------------------

def build_context(cn, client: str, take: str) -> tuple[dict, dict]:
    """Returns (context sent to the model, mapping G01 -> group row kept locally)."""
    groups = query(cn, "SELECT GroupKey, Module, RuleSet, Features, Severity, Records FROM recon.v_TriageContext "
                       "WHERE ClientId = ? AND TakeId = ? ORDER BY Module, Records DESC, GroupKey", client, take)
    rule_ids = sorted({r for g in groups for r in g["RuleSet"].split("+")})
    exclusions = [{"rule": r["RuleId"], "applies_to": r["AppliesTo"] or r["ExpectedWhen"], "condition_sql": r["ExpectedWhen"], "reason": r["Reason"]}
                  for r in query(cn, "SELECT RuleId, ExpectedWhen, AppliesTo, Reason FROM meta.RuleOverride "
                                     "WHERE ClientId = ? AND ExpectedWhen IS NOT NULL ORDER BY RuleId", client)]
    excluded_rules = {e["rule"] for e in exclusions}
    local, sent = {}, []
    for i, g in enumerate(groups, 1):
        gid = f"G{i:02d}"
        local[gid] = g
        failed = g["RuleSet"].split("+")
        # the approved exclusions on rules this group failed, next to the group: the model checks them here instead of
        # cross-referencing a long list (a run that skipped that lookup mislabelled 11 groups)
        sent.append({"group": gid, "module": f"{g['Module']} {MODULE_NAMES.get(g['Module'], '')}".strip(),
                     "failed_rules": failed, "exclusions_to_check": [r for r in failed if r in excluded_rules],
                     "features": g["Features"], "severity": g["Severity"], "records": int(g["Records"])})
    rules = []
    if rule_ids:
        marks = ",".join("?" * len(rule_ids))
        for r in query(cn, f"SELECT e.RuleId, e.Module, e.Severity, c.LegacyText, c.Description FROM meta.v_EffectiveRule e "
                           f"JOIN meta.RuleCatalog c ON c.RuleId = e.RuleId WHERE e.ClientId = ? AND e.RuleId IN ({marks}) ORDER BY e.RuleId",
                       client, *rule_ids):
            rules.append({"rule": r["RuleId"], "module": r["Module"], "severity": r["Severity"],
                          "message": r["LegacyText"], "description": r["Description"]})
    setup = {}
    for r in query(cn, "SELECT SetupTable, Code FROM ref.SetupValue WHERE ClientId = ? AND SetupTable IN ('UM41000', 'UM41301') "
                       "ORDER BY SetupTable, Code", client):
        setup.setdefault({"UM41000": "UM41000 service types", "UM41301": "UM41301 tariffs and rates"}[r["SetupTable"]], []).append(r["Code"].strip())
    # decisions people already made on earlier proposals: precedents, so a correction made once carries over to similar groups
    precedents = [{"module": d["Module"], "failed_rules": d["RuleSet"].split("+"), "features": d["Features"], "decision": d["Decision"],
                   "label": d["Label"], "owner": d["Owner"], "category": d["Category"], "note": d["Note"]}
                  for d in query(cn, "SELECT d.Module, d.Decision, d.Label, d.Owner, d.Category, d.Note, MAX(p.RuleSet) AS RuleSet, "
                                     "MAX(p.Features) AS Features FROM meta.TriageDecision d JOIN run.TriageProposal p "
                                     "ON p.ClientId = d.ClientId AND p.GroupKey = d.GroupKey WHERE d.ClientId = ? AND d.Decision <> 'approved' "
                                     "GROUP BY d.Module, d.Decision, d.Label, d.Owner, d.Category, d.Note", client)]
    context = {"client": client, "take": take, "approved_exclusions": exclusions, "csm_setup": setup, "feature_notes": FEATURE_NOTES,
               "precedents": precedents, "rules": rules, "groups": sent}
    return context, local


# --- PII gate --------------------------------------------------------------------------------------------------

GATE = [("account number", re.compile(r"\b\d{2}-\d{4}-\d{2}\b")), ("long number (account or meter id)", re.compile(r"\d{7,}")),
        ("email", re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")), ("phone", re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"))]


def pii_gate(text: str, scanner_path: str | Path | None = None) -> list[str]:
    """Names of the detectors that fired (empty = clean). Uses the pii-guard skill's detectors when available."""
    fired = [name for name, rx in GATE if rx.search(text)]
    if scanner_path and Path(scanner_path).exists():
        spec = importlib.util.spec_from_file_location("scan_for_pii", scanner_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name, severity, rx, validator in mod.DETECTORS:
            if severity in ("high", "medium") and name != "HARDCODED_PERSON_VALUE":
                for m in rx.finditer(text):
                    if validator is None or validator(m.group(0)):
                        fired.append(name)
                        break
    return sorted(set(fired))


# --- model call ------------------------------------------------------------------------------------------------

def call_model(cfg: dict, token: str, messages: list[dict], attempts: int = 4) -> tuple[dict, dict]:
    url = f"{cfg['endpoint'].rstrip('/')}/openai/deployments/{cfg['deployment']}/chat/completions?api-version={cfg['api_version']}"
    body = json.dumps({"messages": messages, "temperature": 0, "seed": 7, "max_tokens": 16000,
                       "response_format": {"type": "json_schema",
                                           "json_schema": {"name": "triage_proposals", "strict": True, "schema": OUTPUT_SCHEMA}}}).encode()
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                resp = json.loads(r.read())
            return json.loads(resp["choices"][0]["message"]["content"]), resp.get("usage", {})
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(int(e.headers.get("Retry-After", 10 * (attempt + 1))))
                continue
            raise RuntimeError(f"model call failed: HTTP {e.code} {detail}") from e
    raise RuntimeError("unreachable")


# --- run -------------------------------------------------------------------------------------------------------

def _log_call(cn, client, take, cfg, prompt, items, pii, status, usage=None, ms=None, message="") -> int:
    cur = cn.cursor()
    cur.execute("INSERT run.AiCall (ClientId, TakeId, Agent, Endpoint, Deployment, Region, PromptSha256, PromptChars, ItemsSent, PiiCheck, "
                "Status, InputTokens, OutputTokens, LatencyMs, Message) OUTPUT INSERTED.CallId VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                client, take, "triage", cfg["endpoint"][:200], cfg["deployment"], cfg["region"], hashlib.sha256(prompt.encode()).hexdigest(),
                len(prompt), items, pii, status, (usage or {}).get("prompt_tokens"), (usage or {}).get("completion_tokens"), ms, message[:2000])
    return int(cur.fetchone()[0])


def run_triage(cn, client: str, take: str, cfg: dict, token_provider, out_dir: str | Path, scanner_path=None) -> dict:
    """Build the context, gate it, call the model per module batch, validate and store proposals. Returns a summary."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    context, local = build_context(cn, client, take)
    prompt = json.dumps(context, ensure_ascii=False, indent=1)
    (out / "triage-context.json").write_text(prompt, encoding="utf-8")      # everything that is sent: metadata only
    fired = pii_gate(SYSTEM + prompt, scanner_path)
    if fired:
        _log_call(cn, client, take, cfg, prompt, len(local), "blocked", "blocked", message="PII gate: " + ", ".join(fired))
        raise PermissionError(f"PII gate blocked the triage prompt ({', '.join(fired)}); fix the context builder")

    # one call per module batch: a small model keeps its attention on fewer groups
    batches, rest = [], [g for g in context["groups"]]
    for mods in BATCHES:
        part = [g for g in rest if g["module"].split()[0] in mods]
        rest = [g for g in rest if g["module"].split()[0] not in mods]
        if part:
            batches.append(part)
    if rest:
        batches.append(rest)
    token = token_provider()
    rows, problems, usage, ms = [], [], {"prompt_tokens": 0, "completion_tokens": 0}, 0
    for part in batches:
        rule_ids = {r for g in part for r in g["failed_rules"]}
        sub = {**context, "rules": [r for r in context["rules"] if r["rule"] in rule_ids], "groups": part}
        sub_prompt = json.dumps(sub, ensure_ascii=False, indent=1)
        t0 = time.time()
        try:
            result, u = call_model(cfg, token, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": sub_prompt}])
        except Exception as e:
            _log_call(cn, client, take, cfg, sub_prompt, len(part), "passed", "failed", ms=int((time.time() - t0) * 1000), message=str(e))
            raise
        call_ms = int((time.time() - t0) * 1000)
        ms += call_ms
        for k in usage:
            usage[k] += u.get(k) or 0
        ids, batch_problems = {g["group"] for g in part}, []
        seen = set()
        for p in result.get("groups", []):
            gid = p.get("group")
            if gid not in ids or gid in seen:
                batch_problems.append(f"unexpected or repeated group id {gid!r}")
                continue
            seen.add(gid)
            if p["excluded_by"] and p["label"] != "expected":
                batch_problems.append(f"{gid}: names exclusion {p['excluded_by']} but labels it {p['label']}")
            rows.append((gid, p))
        for gid in sorted(ids - seen):
            batch_problems.append(f"no proposal for {gid}")
            rows.append((gid, {"label": "investigate", "owner": "cogsdale", "category": "needs_decision", "title": "No proposal returned",
                               "action": "Review this group by hand.", "client_message": "", "rationale": "The model returned no entry for this group.",
                               "confidence": 0}))
        call_id = _log_call(cn, client, take, cfg, sub_prompt, len(part), "passed", "succeeded", u, call_ms, "; ".join(batch_problems))
        rows = [(gid, p | {"_call": p.get("_call", call_id)}) for gid, p in rows]
        problems += batch_problems
    call_id = max(p["_call"] for _, p in rows)

    classes = {r["GroupKey"]: r["RuleClass"] for r in query(cn, "SELECT GroupKey, RuleClass FROM recon.v_IssueGroup WHERE ClientId = ? AND TakeId = ?", client, take)}
    cur = cn.cursor()
    cur.execute("DELETE run.TriageProposal WHERE ClientId = ? AND TakeId = ?", client, take)
    stored = []
    for gid, p in rows:
        g = local[gid]
        conf = min(max(float(p.get("confidence") or 0), 0.0), 1.0)
        rec = (client, take, g["GroupKey"], g["Module"], g["RuleSet"][:400], g["Features"][:400], g["Severity"], int(g["Records"]),
               classes.get(g["GroupKey"], "actionable"), p["label"], p["owner"], p["category"], p["title"][:200], p["action"][:1000],
               p["client_message"][:1000], p["rationale"][:1000], round(conf, 3), p["_call"],
               (p.get("observation") or "")[:500], (p.get("root_cause") or "unclear")[:40], (p.get("excluded_by") or "")[:60])
        cur.execute("INSERT run.TriageProposal (ClientId, TakeId, GroupKey, Module, RuleSet, Features, Severity, Records, RuleClass, AgentLabel, "
                    "Owner, Category, Title, Action, ClientMessage, Rationale, Confidence, CallId, Observation, RootCause, ExcludedBy) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", *rec)
        stored.append(dict(zip(["ClientId", "TakeId", "GroupKey", "Module", "RuleSet", "Features", "Severity", "Records", "RuleClass", "AgentLabel",
                                "Owner", "Category", "Title", "Action", "ClientMessage", "Rationale", "Confidence", "CallId", "Observation",
                                "RootCause", "ExcludedBy"], rec)) | {"group": gid})

    quality = score(stored)
    cur.execute("DELETE run.StepMetric WHERE ClientId = ? AND TakeId = ? AND Step = 'triage'", client, take)
    for metric, value in quality.items():
        cur.execute("INSERT run.StepMetric (ClientId, TakeId, Step, Item, Metric, Value) VALUES (?, ?, 'triage', 'triage-agent', ?, ?)",
                    client, take, metric, value)
    (out / "triage-proposals.json").write_text(json.dumps({"call_id": call_id, "usage": usage, "latency_ms": ms, "problems": problems,
                                                           "quality": quality, "proposals": stored}, indent=1, default=str), encoding="utf-8")
    (out / "triage-proposals.md").write_text(render_markdown(stored, quality, client, take), encoding="utf-8")
    return {"call_id": call_id, "groups": len(stored), "problems": problems, "quality": quality, "usage": usage, "latency_ms": ms}


def score(proposals: list[dict]) -> dict:
    """Agreement with the approved rules, weighted by records. 'Not expected' = actionable or investigate."""
    tot = sum(p["Records"] for p in proposals) or 1
    agent_ne = sum(p["Records"] for p in proposals if p["AgentLabel"] != "expected")
    rule_ne = sum(p["Records"] for p in proposals if p["RuleClass"] != "expected")
    both_ne = sum(p["Records"] for p in proposals if p["AgentLabel"] != "expected" and p["RuleClass"] != "expected")
    agree = sum(p["Records"] for p in proposals if (p["AgentLabel"] == "expected") == (p["RuleClass"] == "expected"))
    return {"groups": len(proposals), "records": tot, "agreement_pct": round(100 * agree / tot, 2),
            "actionable_precision_pct": round(100 * both_ne / agent_ne, 2) if agent_ne else 100.0,
            "actionable_recall_pct": round(100 * both_ne / rule_ne, 2) if rule_ne else 100.0,
            "groups_investigate": sum(1 for p in proposals if p["AgentLabel"] == "investigate"),
            "groups_disagree": sum(1 for p in proposals if (p["AgentLabel"] == "expected") != (p["RuleClass"] == "expected"))}


def render_markdown(proposals: list[dict], quality: dict, client: str, take: str) -> str:
    lines = [f"# Triage proposals: {client} / {take}", "",
             f"Agreement with the approved rules: {quality['agreement_pct']}% of records; actionable precision "
             f"{quality['actionable_precision_pct']}%, recall {quality['actionable_recall_pct']}%. "
             f"{quality['groups_disagree']} group(s) disagree, {quality['groups_investigate']} need investigation.", "",
             "Proposals only: nothing changes until a person records a decision (run_local.py decide).", ""]
    for mod in sorted({p["Module"] for p in proposals}):
        lines += [f"## {mod} {MODULE_NAMES.get(mod, '')}", "", "| Group | Records | Rules say | Agent | Owner | Title | Action |", "|---|---:|---|---|---|---|---|"]
        for p in sorted((p for p in proposals if p["Module"] == mod), key=lambda p: -p["Records"]):
            flag = "" if (p["AgentLabel"] == "expected") == (p["RuleClass"] == "expected") else " ⚠"
            lines.append(f"| `{p['GroupKey']}` | {p['Records']:,} | {p['RuleClass']} | {p['AgentLabel']}{flag} | {p['Owner']} | "
                         f"{p['Title']} | {p['Action'].replace('|', '/')} |")
        lines.append("")
    return "\n".join(lines)
