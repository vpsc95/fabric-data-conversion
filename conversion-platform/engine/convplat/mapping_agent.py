
"""Metadata-only mapping agent for process P1 (discovery and mapping).

The agent sees target-side template metadata and the statistical source profile only. It never receives the
conversion lead's source/mapping columns, nor the lead's client-specific notes (only target text that is shared with
another client's catalog, i.e. Cogsdale template text, is sent). Its output is a draft proposal for gate 1, not an
approved mapping.

Blind mode (default) uses generic, client-agnostic guidance only, so its evaluation against a client's hand mapping
measures what the agent would do on a new client. Client hints (clients/<client>/mapping-hints.yaml) are opt-in
institutional knowledge; a score obtained with hints written after seeing that client's mapping is not a measure of
accuracy and is labelled as tuned.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .llm import chat_json, log_ai_call, pii_gate
from .reshape import sanitize

ANSWER_COLUMNS = {
    "source_system", "source_table", "source_field", "source_type", "source_length", "cleansing_rule",
    "transformation_rule", "remarks", "sc_param", "layout_position", "in_template", "in_staging_table",
}
TARGET_COLUMNS = ["module", "template", "field", "gp_field", "gp_type", "length", "required", "description", "notes"]
DERIVATIONS = ["direct", "derived", "constant", "lookup/crosswalk", "not in extract", "needs decision"]
SENSITIVE_CODE_HINTS = re.compile(r"(?i)(name|address|phone|email|social|ssn|sin|dob|birth|license|licence|account|acct|meter|serial|receipt|id$|_id)")

SYSTEM = """You are the mapping agent for a utility-billing data conversion into Cogsdale CSM on Microsoft Dynamics GP.
You draft a Field Info mapping from metadata only, before the client workshop.

You receive:
- target_fields: target-side catalog metadata only (field names, GP type/length, required flag, descriptions and notes);
- source_profile: files, sheets and source columns with statistics, value shapes and short low-cardinality codes.

Rules:
- Use only the supplied metadata. You do not see any row values or the conversion lead's hand mapping.
- Return exactly one proposal for every target field, in the same module.
- Prefer direct mappings when a source column name, type, length and description clearly line up.
- The source_column may name a single source column or a compact source expression when the source profile shows repeated
  slots, for example `X / X2` or `LEFT n of X`.
- Use derived for simple expressions such as taking a service code from the left side of a description, concatenating address parts, or deriving route/location keys.
- Use lookup/crosswalk for legacy service/status/class/rate codes that must be translated to CSM values.
- Use constant when the target is a fixed conversion default.
- Use not in extract when the target field appears to be absent and is likely filled later by CSM/business logic.
- Use needs decision when the correct source or default is a business decision.
- Keep transformation short and implementation-oriented. Do not invent data values.
- Confidence reflects metadata evidence only: high for exact/near-exact column matches, medium for plausible derivations, low for unknowns.
- If confidence is below 0.70 or the derivation is needs decision/not in extract, include an open_question.
"""

GENERIC_GUIDANCE = [
    # Client-agnostic CSM conversion knowledge, written without reference to any client's hand mapping.
    "Each source file in source_profile carries the reshape spec that read it (spec) and its file name. Map a target module "
    "from the extract that describes the same business object: customer and location targets from the customer extract, "
    "connection/service targets from the service extract, beginning balances from the balance extract, deposits from the "
    "deposit extract, equipment and read history from the meter and read extracts.",
    "Prefer a column from the extract that feeds the target module over a similarly named column in another extract.",
    "Report-style extracts often print a repeating group of columns side by side (for example X and X2, or X1, X2, X3). "
    "When a target is filled once per slot, propose an expression that names every slot, for example `X / X2`.",
    "Columns that a printed report shows only on the first line of a group (high blank_pct before reshape) identify the "
    "rows below them; they are keys, not attributes.",
    "When a target needs a code that a source column carries at the start of a longer text (value shapes such as "
    "`### - text`), propose a derived expression such as `LEFT n of X`; mark it lookup/crosswalk when the code must "
    "become a CSM code.",
]

OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["fields"],
    "properties": {"fields": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["field", "source_file", "source_column", "derivation", "transformation", "confidence", "open_question"],
        "properties": {
            "field": {"type": "string"},
            "source_file": {"type": ["string", "null"]},
            "source_column": {"type": ["string", "null"]},
            "derivation": {"type": "string", "enum": DERIVATIONS},
            "transformation": {"type": "string"},
            "confidence": {"type": "number"},
            "open_question": {"type": ["string", "null"]},
        }}}}
}


def load_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_workspace_config(path: str | Path) -> dict:
    ws = load_json(path)
    cfg = dict(ws["foundry"])
    cfg.setdefault("region", cfg.get("location", ""))
    return cfg


def patch_endpoint_dns(endpoint: str) -> None:
    """Work around intermittent Python getaddrinfo failures observed on Windows for the Foundry endpoint.

    PowerShell/nslookup can resolve the host while Python sometimes returns 11002. urllib still uses the
    original host name for TLS/SNI; only the address lookup is patched for this process.
    """
    host = urllib.parse.urlparse(endpoint).hostname
    if not host:
        return
    try:
        socket.getaddrinfo(host, 443)
        return
    except OSError:
        pass
    try:
        cp = subprocess.run(["nslookup", host], capture_output=True, text=True, timeout=20)
    except Exception:
        return
    ips = re.findall(r"Address:\s+(\d+\.\d+\.\d+\.\d+)", cp.stdout)
    if not ips:
        return
    ip = ips[-1]
    original = socket.getaddrinfo

    def patched(name, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        if name == host:
            return original(ip, port, family, type, proto, flags)
        return original(name, port, family, type, proto, flags)

    socket.getaddrinfo = patched


def shared_target_text(catalog_path: str | Path) -> dict | None:
    """(module, field, column) -> values that appear in another client's catalog next to this one, i.e. Cogsdale
    template text rather than the lead's client-specific annotations. None when no other catalog exists."""
    here = Path(catalog_path)
    others = [p for p in here.parent.glob("catalog.*.json") if p.resolve() != here.resolve()]
    if not others:
        return None
    shared: dict = defaultdict(set)
    for p in others:
        for r in load_json(p):
            for col in ("description", "notes"):
                v = (r.get(col) or "").strip()
                if v:
                    shared[(r.get("module"), r.get("field"), col)].add(v)
    return shared


def safe_target(row: dict, shared: dict | None = None) -> dict:
    """Return the target-side catalog row: never the answer-key columns, and description/notes only when they are
    template text (shared with another client's catalog). With no other catalog, notes are withheld."""
    out = {k: row.get(k) for k in TARGET_COLUMNS}
    out["length"] = row.get("length") or row.get("storage_length")
    out["required"] = bool(row.get("required"))
    for col in ("description", "notes"):
        v = (row.get(col) or "").strip()
        if not v:
            continue
        if shared is None:
            keep = col == "description"
        else:
            keep = v in shared.get((row.get("module"), row.get("field"), col), set())
        out[col] = v if keep else ""
    return out


def safe_name(value: str | None) -> str | None:
    """Keep metadata names useful while removing long digit runs that trip the PII gate."""
    if value is None:
        return None
    return re.sub(r"\d{7,}", "{digits}", str(value))


def compact_profile(profile: dict) -> dict:
    """Keep metadata only and suppress code samples from likely identifier/PII columns."""
    files = []
    for f in profile.get("files", []):
        pf = {"file": safe_name(f.get("file")), "spec": f.get("spec"), "sheets": []}
        for s in f.get("sheets", []):
            cols = []
            rows = int(s.get("rows") or 0)
            for c in s.get("columns", []):
                blank = int(c.get("blank") or 0)
                item = {
                    "position": c.get("position"),
                    "name": c.get("name"),
                    "sanitized": c.get("sanitized"),
                    "type": c.get("type"),
                    "rows": c.get("rows"),
                    "blank": blank,
                    "blank_pct": round(blank * 100 / rows, 2) if rows else None,
                    "distinct": c.get("distinct"),
                    "min_len": c.get("min_len"),
                    "max_len": c.get("max_len"),
                    "shapes": (c.get("shapes") or [])[:5],
                }
                codes = c.get("codes")
                if codes and not SENSITIVE_CODE_HINTS.search(" ".join(str(x or "") for x in (c.get("name"), c.get("sanitized")))):
                    item["codes"] = codes[:12]
                cols.append(item)
            pf["sheets"].append({"sheet": safe_name(s.get("sheet")), "header_row": s.get("header_row"), "rows": rows, "columns": cols})
        files.append(pf)
    return {"client": profile.get("client"), "take_id": profile.get("take_id"), "files": files}


def build_context(catalog_rows: list[dict], profile: dict, module: str, hints: list[str] | None = None,
                  shared: dict | None = None) -> dict:
    targets = [safe_target(r, shared) for r in catalog_rows if r.get("module") == module]
    return {
        "client": profile.get("client", "sample"),
        "take_id": profile.get("take_id", "go-live"),
        "module": module,
        "guidance": GENERIC_GUIDANCE + list(hints or []),
        "target_fields": targets,
        "source_profile": compact_profile(profile),
    }


def _fallback(field: str, reason: str = "No model proposal returned") -> dict:
    return {"field": field, "source_file": None, "source_column": None, "derivation": "needs decision", "transformation": reason,
            "confidence": 0.0, "open_question": f"Confirm the source or default for {field}."}


def validate_module_result(module: str, target_fields: list[str], result: dict) -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    by_field = {f: _fallback(f) for f in target_fields}
    seen: set[str] = set()
    for p in result.get("fields", []):
        f = p.get("field")
        if f not in by_field:
            problems.append(f"{module}: unexpected field {f!r}")
            continue
        if f in seen:
            problems.append(f"{module}: duplicate field {f!r}; kept first proposal")
            continue
        seen.add(f)
        q = dict(p)
        q["confidence"] = round(max(0.0, min(float(q.get("confidence") or 0.0), 1.0)), 3)
        if q["derivation"] in ("not in extract", "needs decision", "constant"):
            q["source_column"] = None
            if q["derivation"] != "constant":
                q["source_file"] = None
        if not q.get("source_column") and q["derivation"] in ("direct", "derived", "lookup/crosswalk"):
            problems.append(f"{module}.{f}: {q['derivation']} without a source column")
        if q["confidence"] < 0.70 and not q.get("open_question"):
            q["open_question"] = f"Confirm the proposed source and rule for {f}."
        by_field[f] = q
    missing = sorted(set(target_fields) - seen)
    for f in missing:
        problems.append(f"{module}: no proposal for {f!r}")
    return [by_field[f] for f in target_fields], problems


def load_hints(path: str | Path | None) -> tuple[list[str], bool]:
    """Client hints file -> (hints, tuned_on_answer_key)."""
    if not path:
        return [], False
    import yaml
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [str(h) for h in doc.get("hints") or []], bool(doc.get("tuned_on_answer_key"))


def run_mapping_agent(cn, catalog_path: str | Path, profile_path: str | Path, cfg: dict, token_provider: Callable[[], str], out_dir: str | Path,
                      modules: list[str] | None = None, scanner_path: str | Path | None = None,
                      client: str = "sample", take: str = "go-live", hints_path: str | Path | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = load_json(catalog_path)
    profile = load_json(profile_path)
    hints, tuned = load_hints(hints_path)
    shared = shared_target_text(catalog_path)
    all_modules = list(dict.fromkeys(r["module"] for r in catalog))
    selected = [m for m in all_modules if not modules or m in modules]
    if not selected:
        raise ValueError("No matching modules selected")

    patch_endpoint_dns(cfg["endpoint"])
    token = token_provider()
    records, problems = [], []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    total_ms = 0
    module_summaries = {}
    for module in selected:
        context = build_context(catalog, profile, module, hints, shared)
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(context, ensure_ascii=False, indent=1)}]
        prompt_text = json.dumps({"messages": messages}, ensure_ascii=False, indent=1)
        (out / f"context-{module}.json").write_text(prompt_text, encoding="utf-8")
        fired = pii_gate(prompt_text, scanner_path)
        if fired:
            log_ai_call(cn, client, take, "mapping", cfg, prompt_text, len(context["target_fields"]), "blocked", "blocked",
                        message="PII gate: " + ", ".join(fired))
            raise PermissionError(f"PII gate blocked {module} prompt ({', '.join(fired)})")
        t0 = time.time()
        try:
            last_error = None
            for attempt in range(5):
                try:
                    result, usage = chat_json(cfg, token, messages, OUTPUT_SCHEMA, "mapping_proposals")
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt == 4:
                        raise
                    time.sleep(10 * (attempt + 1))
            status = "succeeded"
            message = ""
        except Exception as e:
            result, usage = {"fields": []}, {}
            status = "failed"
            message = str(e)
        ms = int((time.time() - t0) * 1000)
        total_ms += ms
        for k in total_usage:
            total_usage[k] += usage.get(k) or 0
        log_ai_call(cn, client, take, "mapping", cfg, prompt_text, len(context["target_fields"]), "passed", status, usage, ms, message)
        if status != "succeeded":
            raise RuntimeError(f"Mapping model call failed for {module}: {message}")
        target_fields = [r["field"] for r in context["target_fields"]]
        props, probs = validate_module_result(module, target_fields, result)
        problems.extend(probs)
        by_target = {r["field"]: r for r in context["target_fields"]}
        for p in props:
            records.append({"module": module, "target": by_target[p["field"]], **p})
        module_summaries[module] = {
            "fields": len(props),
            "mapped": sum(1 for p in props if p.get("source_column")),
            "high_confidence": sum(1 for p in props if p.get("confidence", 0) >= 0.80),
            "open_questions": sum(1 for p in props if p.get("open_question")),
        }

    mode = "blind" if not hints else ("with client hints (tuned on this client's answer key)" if tuned else "with client hints")
    draft = {"client": client, "take": take, "generated_at": datetime.now(timezone.utc).isoformat(), "modules": selected,
             "mode": mode, "client_hints": len(hints), "tuned_on_answer_key": tuned,
             "usage": total_usage, "latency_ms": total_ms, "problems": problems, "summary": module_summaries, "mappings": records}
    (out / "draft-mapping.json").write_text(json.dumps(draft, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "draft-mapping.md").write_text(render_markdown(draft), encoding="utf-8")
    return draft


def render_markdown(draft: dict) -> str:
    lines = [f"# Draft mapping: {draft['client']} / {draft['take']}", "", "Metadata-only proposal for gate 1. Human approval is required before use.",
             f"Mode: **{draft.get('mode', 'unrecorded')}**.", ""]
    total = len(draft["mappings"])
    mapped = sum(1 for r in draft["mappings"] if r.get("source_column"))
    oq = sum(1 for r in draft["mappings"] if r.get("open_question"))
    lines += [f"Overall: {mapped}/{total} fields have a proposed source column; {oq} open questions.", ""]
    for module in draft["modules"]:
        rows = [r for r in draft["mappings"] if r["module"] == module]
        s = draft["summary"][module]
        lines += [f"## {module}", "", f"Mapped {s['mapped']}/{s['fields']} fields; high confidence {s['high_confidence']}; open questions {s['open_questions']}.", "",
                  "| Field | Source file | Source column | Derivation | Confidence | Open question |",
                  "|---|---|---|---|---:|---|"]
        for r in rows:
            q = (r.get("open_question") or "").replace("|", "/")
            lines.append(f"| `{r['field']}` | {r.get('source_file') or ''} | {r.get('source_column') or ''} | {r['derivation']} | {r['confidence']:.2f} | {q} |")
        lines.append("")
    if draft.get("problems"):
        lines += ["## Validation notes", ""] + [f"- {p}" for p in draft["problems"]] + [""]
    return "\n".join(lines)


def norm_source(value: str | None) -> str:
    if not value:
        return ""
    return sanitize([str(value).strip()])[0].upper()


def norm_file(value: str | None) -> str:
    if not value:
        return ""
    s = re.sub(r"\.[A-Za-z0-9]+$", "", str(value)).upper()
    return re.sub(r"[^A-Z0-9]+", "", s.replace("#", "NUM"))


def _squash(value: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", value.upper())


def expression_columns(expr: str, columns: set[str]) -> set[str]:
    """The real source columns a source expression uses, e.g. 'First 2 digits of ACCT' -> {ACCT},
    'BAL#' -> {BAL1, BAL2, BAL3} (# = repeating group), 'METER / METER2' -> {METER, METER2},
    'DRIVERS LICENSE + DLST' -> {DRIVERSLICENSE, DLST}. Longest match wins: 'INCODE ACCT' -> {INCODEACCT}, not ACCT."""
    words = re.findall(r"[0-9A-Za-z_]+#?", expr or "")
    found, used = set(), set()
    for n in (3, 2, 1):                                   # longest spans first
        for i in range(len(words) - n + 1):
            span = range(i, i + n)
            if used & set(span):
                continue
            joined = "".join(w.rstrip("#") for w in words[i:i + n])
            if words[i + n - 1].endswith("#"):            # repeating group: BAL# -> BAL1, BAL2, ...
                group = {c for c in columns if re.fullmatch(_squash(joined) + r"\d+", c)}
                if group:
                    found |= group
                    used |= set(span)
                continue
            if _squash(joined) in columns:
                found.add(_squash(joined))
                used |= set(span)
    return found


def evaluate(draft: dict, catalog_path: str | Path, out_dir: str | Path, profile_path: str | Path | None = None) -> dict:
    catalog = load_json(catalog_path)
    columns = set()
    if profile_path and Path(profile_path).exists():      # real source column names, for the expression-aware score
        prof = load_json(profile_path)
        columns = {_squash(c["sanitized"]) for f in prof["files"] for s in f["sheets"] for c in s["columns"]}
    actual = {(r["module"], r["field"]): r for r in draft["mappings"]}
    rows = []
    per = defaultdict(lambda: {"lead_mapped": 0, "source_column_matches": 0, "expression_matches": 0, "partial_matches": 0,
                               "source_file_compared": 0, "source_file_matches": 0, "agent_mapped_lead_blank": 0,
                               "agent_blank_lead_mapped": 0, "fields": 0})
    for c in catalog:
        key = (c["module"], c["field"])
        if key not in actual:
            continue
        a = actual[key]
        mod = c["module"]
        per[mod]["fields"] += 1
        lead_col = (c.get("source_field") or "").strip()
        agent_col = (a.get("source_column") or "").strip()
        lead_file = (c.get("source_table") or "").strip()
        agent_file = (a.get("source_file") or "").strip()
        rec = {"module": mod, "field": c["field"], "lead_source_field": lead_col, "agent_source_column": agent_col,
               "source_column_match": False, "expression_match": False, "partial_match": False, "source_file_match": None}
        if lead_col:
            per[mod]["lead_mapped"] += 1
            rec["source_column_match"] = norm_source(lead_col) == norm_source(agent_col)
            lead_uses, agent_uses = expression_columns(lead_col, columns), expression_columns(agent_col, columns)
            rec["expression_match"] = rec["source_column_match"] or (bool(lead_uses) and lead_uses == agent_uses)
            rec["partial_match"] = not rec["expression_match"] and bool(lead_uses & agent_uses)
            if rec["source_column_match"]:
                per[mod]["source_column_matches"] += 1
            if rec["expression_match"]:
                per[mod]["expression_matches"] += 1
            if rec["partial_match"]:
                per[mod]["partial_matches"] += 1
            if not agent_col:
                per[mod]["agent_blank_lead_mapped"] += 1
        elif agent_col:
            per[mod]["agent_mapped_lead_blank"] += 1
        if lead_file and agent_file:
            lf, af = norm_file(lead_file), norm_file(agent_file)
            # meaningful when names share at least one substantial token or one contains the other after normalization
            rec["source_file_match"] = bool(lf and af and (lf in af or af in lf or len(set(re.findall(r"[A-Z]{3,}", lead_file.upper())) & set(re.findall(r"[A-Z]{3,}", agent_file.upper()))) > 0))
            per[mod]["source_file_compared"] += 1
            if rec["source_file_match"]:
                per[mod]["source_file_matches"] += 1
        rows.append(rec)
    modules = {}
    overall = {"fields": 0, "lead_mapped": 0, "source_column_matches": 0, "expression_matches": 0, "partial_matches": 0,
               "source_file_compared": 0, "source_file_matches": 0, "agent_mapped_lead_blank": 0, "agent_blank_lead_mapped": 0}
    for mod in draft["modules"]:
        m = dict(per[mod])
        m["source_column_accuracy_pct"] = round(100 * m["source_column_matches"] / m["lead_mapped"], 2) if m["lead_mapped"] else None
        m["expression_accuracy_pct"] = round(100 * m["expression_matches"] / m["lead_mapped"], 2) if m["lead_mapped"] else None
        m["source_file_accuracy_pct"] = round(100 * m["source_file_matches"] / m["source_file_compared"], 2) if m["source_file_compared"] else None
        modules[mod] = m
        for k in overall:
            overall[k] += per[mod][k]
    overall["source_column_accuracy_pct"] = round(100 * overall["source_column_matches"] / overall["lead_mapped"], 2) if overall["lead_mapped"] else None
    overall["expression_accuracy_pct"] = round(100 * overall["expression_matches"] / overall["lead_mapped"], 2) if overall["lead_mapped"] else None
    overall["source_file_accuracy_pct"] = round(100 * overall["source_file_matches"] / overall["source_file_compared"], 2) if overall["source_file_compared"] else None
    examples = {
        "matches": [r for r in rows if r["source_column_match"]][:10],
        "wrong": [r for r in rows if r["lead_source_field"] and r["agent_source_column"] and not r["source_column_match"]][:10],
        "agent_extra": [r for r in rows if not r["lead_source_field"] and r["agent_source_column"]][:10],
        "agent_blank": [r for r in rows if r["lead_source_field"] and not r["agent_source_column"]][:10],
    }
    ev = {"mode": draft.get("mode", "unrecorded"), "overall": overall, "modules": modules, "examples": examples, "rows": rows}
    out = Path(out_dir)
    (out / "evaluation.json").write_text(json.dumps(ev, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "evaluation.md").write_text(render_evaluation_markdown(ev), encoding="utf-8")
    return ev


def render_evaluation_markdown(ev: dict) -> str:
    o = ev["overall"]
    lines = ["# Mapping draft evaluation", "", f"Mode: **{ev.get('mode', 'unrecorded')}**.", ""]
    if "tuned" in ev.get("mode", ""):
        lines += ["> **Not an accuracy measure.** The prompt contained hints written after seeing this client's hand mapping, "
                  "so this score is tuned to the answer key. Use the blind-mode score to judge the agent on a new client.", ""]
    lines += ["Compared agent `source_column` to the conversion lead's `source_field` answer key after reshape-style normalization.", "",
             f"Overall source-column accuracy (strict text match): **{o['source_column_matches']}/{o['lead_mapped']} = {o['source_column_accuracy_pct']}%**.",
             f"Same source columns (both expressions resolve to the same real source columns, e.g. 'LEFT 2 of ACCT' for "
             f"'First 2 digits of ACCT', 'BAL1 / BAL2 / BAL3' for 'BAL#'; transforms such as '/100' are not scored): "
             f"**{o['expression_matches']}/{o['lead_mapped']} = {o['expression_accuracy_pct']}%**, "
             f"plus {o['partial_matches']} partial (overlapping but incomplete column set, e.g. 'RECEIVED' for 'RECEIVED+UNBILLED').",
             f"Agent mapped {o['agent_mapped_lead_blank']} field(s) the lead left blank; agent left blank {o['agent_blank_lead_mapped']} field(s) the lead mapped.",
             f"Source file/table agreement where compared: {o['source_file_matches']}/{o['source_file_compared']} = {o['source_file_accuracy_pct']}%.", "",
             "| Module | Fields | Lead mapped | Strict matches | Strict % | Same columns | Same columns % | Partial | Agent extra | Agent blank | File matches |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for mod, m in ev["modules"].items():
        lines.append(f"| {mod} | {m['fields']} | {m['lead_mapped']} | {m['source_column_matches']} | {m['source_column_accuracy_pct']}% | "
                     f"{m['expression_matches']} | {m['expression_accuracy_pct']}% | {m['partial_matches']} | "
                     f"{m['agent_mapped_lead_blank']} | {m['agent_blank_lead_mapped']} | {m['source_file_matches']}/{m['source_file_compared']} |")
    for title, key in [("Representative matches", "matches"), ("Representative wrong source-column proposals", "wrong"),
                       ("Agent mapped but lead left blank", "agent_extra"), ("Agent left blank but lead mapped", "agent_blank")]:
        lines += ["", f"## {title}", "", "| Module | Field | Lead source | Agent source |", "|---|---|---|---|"]
        for r in ev["examples"][key][:8]:
            lines.append(f"| {r['module']} | `{r['field']}` | `{r['lead_source_field']}` | `{r['agent_source_column']}` |")
    lines.append("")
    return "\n".join(lines)
