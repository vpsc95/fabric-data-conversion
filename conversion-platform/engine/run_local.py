"""Run conversion steps locally (laptop / CI) on a de-identified take, against LocalDB or Fabric.

  python run_local.py profile  --target ... --landing <take folder> --work <work folder>   custody hashes, column profile, drift (gate 1)
  python run_local.py map-draft --target ... --work <work folder> [--with-client-hints] [--modules ...]   mapping agent (P1, Foundry, metadata only)
  python run_local.py reshape  --landing <take folder> --work <work folder>
  python run_local.py db       --target localdb|fabric             deploy sql/ and seed metadata from the specs
  python run_local.py load     --target ... --work <work folder>   silver parquet -> slv tables
  python run_local.py build    --target ...                        gold.usp_Build_All
  python run_local.py validate --target ...                        rules.usp_Validate_All
  python run_local.py recon    --target ... --work <work folder>   run-results.json + answer-key check
  python run_local.py triage   --target ... --work <work folder>   triage agent (Foundry, metadata only) -> proposals
  python run_local.py decide   --target ... --by <name> --approve <group> ... | --approve-all | --reject ... | --change ...
  python run_local.py approve  --target ... --gate <1-6> --by <name> [--note ...]   a person approves a gate (reject: same arguments)
  python run_local.py gates    --target ...                        the six gates of the take and their state
  python run_local.py cleanse  --target ...                        cleansing proposals (never applied in a replay); gate 2
  python run_local.py load-csm --target ... [--auto-approve]       gate 4, metadata-driven loader (CONV emulator), post-load recon; gate 5
  python run_local.py publish-take --target ... --work ... [--auto-approve]   gate 5, runbook, validation sample, integrity report; gate 6
  python run_local.py all      --target ... --landing ... --work ... [--auto-approve]

Defaults: --client-dir clients/sample next to this engine folder. The same engine code runs in the
Fabric notebooks (nb_reshape, nb_load_slv); the SQL is identical on LocalDB and Fabric SQL database.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import polars as pl

ENGINE = Path(__file__).resolve().parent
PLATFORM = ENGINE.parent
sys.path.insert(0, str(ENGINE))
from convplat import recon, seed, sqlio  # noqa: E402
from convplat.reshape import run_reshape, to_columns  # noqa: E402
from convplat.specs import ClientSpecs  # noqa: E402

SLV_TABLES = {"customers": "slv.Customers", "services": "slv.Services", "balances": "slv.Balances",
              "deposits": "slv.Deposits", "reads": "slv.Reads"}
ANSWER_KEY_CHECK = PLATFORM.parent / ".github" / "skills" / "golden-master-test" / "scripts" / "check_answer_key.py"
PII_SCANNER = PLATFORM.parent / ".github" / "skills" / "pii-guard" / "scripts" / "scan_for_pii.py"


def frame(data: dict) -> pl.DataFrame:
    return pl.DataFrame({k: pl.Series(k, v, dtype=pl.Int32 if k == "_row" else pl.Utf8) for k, v in data.items()})


def connect(a):
    if a.target == "localdb":
        return sqlio.connect_localdb(a.database)
    ws = json.loads((PLATFORM / "fabric" / "workspace.json").read_text(encoding="utf-8"))
    from azure.identity import AzureCliCredential
    token = AzureCliCredential(tenant_id=ws["tenant_id"]).get_token("https://database.windows.net/.default").token
    return sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], token)


def step(name):
    def wrap(fn):
        def run(a, *args):
            t0 = time.time()
            out = fn(a, *args)
            print(f"[{name}] done in {time.time() - t0:.1f}s")
            return out
        return run
    return wrap


@step("map-draft")
def cmd_map_draft(a) -> int:
    """P1: the mapping agent drafts the Field Info mapping from the take's profile (metadata only: column names, shapes,
    short code sets; never row values). Output is a proposal for gate 1; when the client's catalog carries the lead's hand
    mapping it is also scored. Blind by default; --with-client-hints adds clients/<client>/mapping-hints.yaml."""
    from convplat.fieldinfo_xlsx import write_workbook
    from convplat.mapping_agent import evaluate, load_workspace_config, run_mapping_agent
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    profile = Path(a.work) / "profile.json"
    if not profile.exists():
        raise SystemExit("map-draft needs the take's profile: run `profile` first")
    catalog = PLATFORM / "catalog" / "cogsdale-csm-gp" / f"catalog.{specs.client}.json"
    hints = Path(a.client_dir) / "mapping-hints.yaml" if a.with_client_hints else None
    out = Path(a.work) / ("mapping-draft-hints" if hints else "mapping-draft")
    ws = json.loads((PLATFORM / "fabric" / "workspace.json").read_text(encoding="utf-8"))
    draft = run_mapping_agent(cn, catalog, profile, load_workspace_config(PLATFORM / "fabric" / "workspace.json"),
                              lambda: foundry_token(ws), out, a.modules, PII_SCANNER, client=specs.client, take=specs.take_id,
                              hints_path=hints)
    write_workbook(draft, out / "FieldInfo_mapping_draft.xlsx")
    u = draft["usage"]
    print(f"  [{draft['mode']}] {len(draft['mappings'])} target fields drafted; tokens {u['prompt_tokens']} in / {u['completion_tokens']} out")
    if any((r.get("source_field") or "").strip() for r in json.loads(catalog.read_text(encoding="utf-8"))):
        o = evaluate(draft, catalog, out, profile)["overall"]
        print(f"  vs the lead's mapping: strict {o['source_column_matches']}/{o['lead_mapped']} = {o['source_column_accuracy_pct']}%, "
              f"same source columns {o['expression_matches']}/{o['lead_mapped']} = {o['expression_accuracy_pct']}% (+{o['partial_matches']} partial)")
    print(f"  workbook for gate 1 review: {out / 'FieldInfo_mapping_draft.xlsx'}")
    return 0


@step("profile")
def cmd_profile(a) -> int:
    """Chain of custody (SHA-256 per landed file), column statistics, conformance with the approved specs and drift
    against the previous take. Exit code 2 = blocking findings: gate 1 (spec change) is required."""
    from convplat import profile as prof
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    out = Path(a.work)
    out.mkdir(parents=True, exist_ok=True)
    files = prof.manifest(a.landing)
    p = prof.profile_take(specs, a.landing, files)
    slv = {f"silver.{name}": list(sqlio.table_columns(cn, table)) for name, table in SLV_TABLES.items()}
    needed = prof.needed_columns(specs, slv, a.landing)
    prev_take, prev = prof.previous_profile(cn, specs.client, specs.take_id, str(specs.take.get("conversion_date") or "") or None)
    findings = prof.conformance(p, needed, files) + [dict(f, compared_to=prev_take) for f in prof.drift(p, prev)]
    summary = prof.summarize(findings)
    (out / "manifest.json").write_text(json.dumps(files, indent=1), encoding="utf-8")
    (out / "profile.json").write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "drift.json").write_text(json.dumps({"summary": summary, "compared_to": prev_take, "findings": findings}, indent=1), encoding="utf-8")
    prof.save(cn, specs.client, specs.take_id, files, p, findings, {s["source"]["file"]: s["id"] for s in specs.file_reshapes(a.landing)},
              take_date=str(specs.take.get("conversion_date") or ""), simulated=bool(specs.take.get("simulated")))
    if _gates_ready(cn):
        from convplat import gates
        gates.open_gate(cn, specs.client, specs.take_id, 1, gates.evidence_gate1(summary, findings, prev_take), needed=summary["gate1_required"])
    print(f"  {len(files)} files hashed; {sum(len(s['columns']) for f in p['files'] for s in f['sheets'])} columns profiled; "
          f"compared to {prev_take or 'the approved specs only (first take)'}")
    for x in findings:
        if x["severity"] != "info":
            print(f"  {x['severity']:8} {x['kind']:20} {x.get('file') or ''} {x.get('column') or ''}: {x['detail']}")
    print(f"  blocking={summary['blocking']} warning={summary['warning']} info={summary['info']} -> "
          + ("GATE 1 REQUIRED: a spec change must be approved before this take runs" if summary["gate1_required"] else "specs fit this take"))
    return 2 if summary["gate1_required"] else 0


@step("reshape")
def cmd_reshape(a) -> int:
    specs = ClientSpecs(a.client_dir, a.take)
    out = Path(a.work)
    manifest = out / "manifest.json"
    if manifest.exists():                       # chain of custody: process the files exactly as received
        from convplat import profile as prof
        changed = prof.verify(a.landing, json.loads(manifest.read_text(encoding="utf-8")),
                              only={s["source"]["file"] for s in specs.file_reshapes(a.landing)})
        if changed:
            raise SystemExit("custody check failed, re-run `profile` to record the new files: " + "; ".join(changed))
        print("  custody: every spec file matches its recorded SHA-256")
    (out / "bronze").mkdir(parents=True, exist_ok=True)
    (out / "silver").mkdir(parents=True, exist_ok=True)
    reports = []
    for spec in specs.file_reshapes(a.landing):
        r = run_reshape(spec, a.landing)
        name = r.target.split(".", 1)[1]
        frame(to_columns(r.bronze_columns, r.bronze_rows, list(range(1, len(r.bronze_rows) + 1)), specs.take_id, r.source_file, r.sheet)) \
            .write_parquet(out / "bronze" / f"{name}.parquet")
        frame(to_columns(r.silver_columns, r.silver_rows, r.silver_row_numbers, specs.take_id, r.source_file, r.sheet)) \
            .write_parquet(out / "silver" / f"{name}.parquet")
        pl.DataFrame({"_row": [n for n, _ in r.artifacts], "reason": [x for _, x in r.artifacts]},
                     schema={"_row": pl.Int32, "reason": pl.Utf8}).write_parquet(out / "silver" / f"{name}_artifacts.parquet")
        reports.append(r.report)
        print(f"  {r.spec_id:18} read={r.report['rows_read']:>7} kept={r.report['rows_kept']:>7} "
              f"artifacts={sum(r.report['artifacts'].values()):>6} fill-down mismatches="
              f"{sum(v['mismatches'] for v in r.report['fill_down_checks'].values())}")
    (out / "reshape-report.json").write_text(json.dumps({"client": specs.client, "take_id": specs.take_id, "reshapes": reports}, indent=1), encoding="utf-8")
    return 0


@step("db")
def cmd_db(a) -> int:
    cn = connect(a)
    print("  deployed:", ", ".join(sqlio.deploy(cn, PLATFORM / "sql")))
    print("  seeded:", seed.seed(cn, PLATFORM, a.client_dir))
    return 0


@step("load")
def cmd_load(a) -> int:
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    for name, table in SLV_TABLES.items():
        df = pl.read_parquet(Path(a.work) / "silver" / f"{name}.parquet")
        n = sqlio.load_table(cn, table, {c: df[c].to_list() for c in df.columns}, specs.take_id)
        print(f"  {table:14} {n:>7} rows")
    report = json.loads((Path(a.work) / "reshape-report.json").read_text(encoding="utf-8"))
    cur = cn.cursor()
    cur.execute("DELETE run.StepMetric WHERE ClientId = ? AND TakeId = ? AND Step = 'reshape'", specs.client, specs.take_id)
    for r in report["reshapes"]:
        metrics = [("rows_read", r["rows_read"]), ("rows_kept", r["rows_kept"])] + [(f"artifacts.{k}", v) for k, v in r["artifacts"].items()] \
            + [(f"fill_down_mismatch.{k}", v["mismatches"]) for k, v in r["fill_down_checks"].items()]
        for metric, value in metrics:
            cur.execute("INSERT run.StepMetric (ClientId, TakeId, Step, Item, Metric, Value) VALUES (?, ?, 'reshape', ?, ?, ?)",
                        specs.client, specs.take_id, r["spec"], metric, value)
    return 0


@step("build")
def cmd_build(a) -> int:
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    sqlio.exec_proc(cn, "EXEC gold.usp_Build_All ?, ?", specs.client, specs.take_id)
    for r in sqlio.query(cn, "SELECT StepName, RowsAffected, Status, DATEDIFF(ms, StartedAt, EndedAt) AS ms FROM run.RunLog "
                             "WHERE RunLogId IN (SELECT MAX(RunLogId) FROM run.RunLog WHERE ClientId = ? AND TakeId = ? AND StepName LIKE 'gold.%' GROUP BY StepName) "
                             "ORDER BY RunLogId", specs.client, specs.take_id):
        print(f"  {r['StepName']:32} rows={r['RowsAffected']} {r['Status']} {r['ms']} ms")
    return 0


@step("validate")
def cmd_validate(a) -> int:
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    sqlio.exec_proc(cn, "EXEC rules.usp_Validate_All ?, ?", specs.client, specs.take_id)
    return 0


@step("recon")
def cmd_recon(a) -> int:
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    res = recon.results(cn, specs.client, specs.take_id)
    out = Path(a.work) / "run-results.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    for mod, m in res["modules"].items():
        extra = f" distinct={m['received_distinct']}" if "received_distinct" in m else ""
        print(f"  {mod:9} received={m.get('received')}{extra} loaded={m.get('loaded')} failed={m.get('failed')} "
              f"actionable_total={m.get('actionable_total')} totals={m.get('control_totals', {})}")
        for rule, v in sorted(m["issues"].items()):
            print(f"      {rule:38} {v['severity']} records={v['count']:>6} expected={v['expected']:>6} actionable={v['actionable']:>6}")
    rc = 0
    key = specs.take.get("answer_key")        # an outcome to reproduce (the go-live integrity report); most takes have none
    if key:
        allow = Path(a.client_dir) / "allowances.json"
        cmd = [sys.executable, str(ANSWER_KEY_CHECK), "--results", str(out), "--key", str(ANSWER_KEY_CHECK.parent.parent / "references" / key),
               "--json-out", str(Path(a.work) / "answer-key-check.json")] + (["--allow", str(allow)] if allow.exists() else [])
        rc = subprocess.call(cmd)
        check = json.loads((Path(a.work) / "answer-key-check.json").read_text(encoding="utf-8"))
        sqlio.save_answer_key_check(cn, specs.client, specs.take_id, check["rows"])
    else:
        print("  no answer key for this take: reconciliation only")
    if _gates_ready(cn):                       # gate 4: the pre-load reconciliation is what the go / no-go decision looks at
        from convplat import gates
        gates.open_gate(cn, specs.client, specs.take_id, 4, gates.evidence_gate4(cn, specs.client, specs.take_id))
        print("  gate 4 (load go / no-go) opened with the pre-load reconciliation")
    return rc


def foundry_token(ws: dict) -> str:
    from azure.identity import AzureCliCredential
    return AzureCliCredential(tenant_id=ws["tenant_id"]).get_token("https://cognitiveservices.azure.com/.default").token


@step("triage")
def cmd_triage(a) -> int:
    from convplat import triage
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    ws = json.loads((PLATFORM / "fabric" / "workspace.json").read_text(encoding="utf-8"))
    res = triage.run_triage(cn, specs.client, specs.take_id, ws["foundry"], lambda: foundry_token(ws), Path(a.work) / "triage", PII_SCANNER)
    print(f"  call {res['call_id']}: {res['groups']} groups, {res['latency_ms']} ms, tokens {res['usage'].get('prompt_tokens')} in / "
          f"{res['usage'].get('completion_tokens')} out; quality {res['quality']}")
    for p in res["problems"]:
        print("  problem:", p)
    print(f"  proposals: {Path(a.work) / 'triage' / 'triage-proposals.md'}")
    if _gates_ready(cn):                       # gate 3: a person approves, edits or rejects the proposals
        from convplat import gates
        gates.open_gate(cn, specs.client, specs.take_id, 3, gates.evidence_gate3(cn, specs.client, specs.take_id))
        print("  gate 3 (triage) opened")
    return 0


def _gates_ready(cn) -> bool:
    return cn.cursor().execute("SELECT OBJECT_ID('run.Gate')").fetchone()[0] is not None


@step("cleanse")
def cmd_cleanse(a) -> int:
    """P7: deterministic cleansing proposals (stored, never applied in a replay); low-confidence ones open gate 2."""
    from convplat import cleanse, gates
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    cleanse.run(cn, specs.client, specs.take_id)
    ev = cleanse.gate2_evidence(cn, specs.client, specs.take_id)
    print(f"  {ev['proposals']} proposals: {ev['high']} high confidence, {ev['low']} low ({ev['pending_low']} awaiting review)")
    if _gates_ready(cn):
        gates.open_gate(cn, specs.client, specs.take_id, 2, ev, needed=ev["pending_low"] > 0)
        print(f"  gate 2 (low-confidence fixes) {'opened' if ev['pending_low'] else 'not needed'}")
    return 0


@step("load-csm")
def cmd_load_csm(a) -> int:
    """P11: after gate 4, the metadata-driven loader calls the CSM procedures (the CONV emulator in the prototype),
    then the post-load reconciliation opens gate 5."""
    from convplat import gates
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    print(f"  gate 4: {gates.wait(cn, specs.client, specs.take_id, 4, timeout_s=a.gate_timeout, auto_approve=a.auto_approve)}")
    sqlio.exec_proc(cn, "EXEC load.usp_PrepareTake ?, ?", specs.client, specs.take_id)
    sqlio.exec_proc(cn, "EXEC load.usp_LoadAll ?, ?", specs.client, specs.take_id)
    rows = sqlio.query(cn, "SELECT Module, ExpectedToLoad, Loaded, Failed, Variance, ControlName, AmountVariance FROM recon.v_PostLoad "
                           "WHERE ClientId = ? AND TakeId = ? ORDER BY Module, ControlName", specs.client, specs.take_id)
    for r in rows:
        print(f"  {r['Module']:9} {r['ControlName'] or '':12} expected={r['ExpectedToLoad']} loaded={r['Loaded']} failed={r['Failed']} "
              f"variance={r['Variance']}" + (f" amount variance={r['AmountVariance']}" if r["ControlName"] else ""))
    variance = sum(abs(int(r["Variance"] or 0)) for r in rows) + sum(int(r["Failed"] or 0) for r in rows)
    amounts = sum(abs(float(r["AmountVariance"] or 0)) for r in rows if r["ControlName"])
    gates.open_gate(cn, specs.client, specs.take_id, 5, {
        "what": "Post-load reconciliation: publish to TEST and TRAIN?", "modules": rows, "record_variance": variance,
        "amount_variance": amounts, "target": "CONV emulator (shadow mode): no GP/CSM server in the prototype"})
    print(f"  post-load variance {variance} records, {amounts:.2f} in control totals -> gate 5 (publish) opened")
    return 0 if variance == 0 and amounts < 0.005 else 1


@step("publish-take")
def cmd_publish_take(a) -> int:
    """P12, P15, P14: after gate 5, the runbook steps (simulated where GP infrastructure is needed), the client's
    validation sample and the generated integrity report; gate 6 (take acceptance) opens with them."""
    from convplat import gates, integrity_report, runbook
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    print(f"  gate 5: {gates.wait(cn, specs.client, specs.take_id, 5, timeout_s=a.gate_timeout, auto_approve=a.auto_approve)}")
    runbook.seed_steps(cn, a.client_dir)
    rb = runbook.execute(cn, a.client_dir, specs.take_id)
    print(f"  runbook: {', '.join(f'{k} {v}' for k, v in rb.items() if k not in ('answer_key_summary', 'answer_key_rows'))}")
    sqlio.exec_proc(cn, "EXEC recon.usp_BuildValidationSample ?, ?", specs.client, specs.take_id)
    sample = sqlio.query(cn, "SELECT COUNT(*) AS n FROM run.ValidationSample WHERE ClientId = ? AND TakeId = ?", specs.client, specs.take_id)[0]["n"]
    out = Path(a.work) / "report"
    rep = integrity_report.generate(cn, a.client_dir, specs.take_id, a.work, out)
    fix = sqlio.query(cn, "SELECT FinalOwner, COUNT(*) AS n FROM recon.v_FixList WHERE ClientId = ? AND TakeId = ? GROUP BY FinalOwner",
                      specs.client, specs.take_id)
    gates.open_gate(cn, specs.client, specs.take_id, 6, {
        "what": "Take acceptance: sign the integrity report (e-signature in production).", "validation_sample_accounts": sample,
        "open_fix_items_by_owner": {r["FinalOwner"]: r["n"] for r in fix}, "integrity_report": {k: str(v) for k, v in rep.items() if "path" in k or k in ("html", "docx", "pdf")}})
    print(f"  validation sample: {sample} accounts; integrity report: {out}; gate 6 (take acceptance) opened")
    return 0


@step("approve")
def cmd_approve(a) -> int:
    from convplat import gates
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    decision = "rejected" if a.cmd == "reject" else "approved"
    gates.decide(cn, specs.client, specs.take_id, a.gate, decision, a.by, a.note or "")
    print(f"  gate {a.gate} ({gates.GATES[a.gate]}) {decision} by {a.by}")
    return 0


@step("gates")
def cmd_gates(a) -> int:
    from convplat import gates
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    rows = {r["Gate"]: r for r in gates.status(cn, specs.client, specs.take_id)}
    for g, name in gates.GATES.items():
        r = rows.get(g)
        print(f"  {g} {name:22} {r['Status'] if r else 'not opened':14} {(r or {}).get('DecidedBy') or ''}")
    return 0


@step("decide")
def cmd_decide(a) -> int:
    from convplat import decisions
    specs, cn = ClientSpecs(a.client_dir, a.take), connect(a)
    res = decisions.record(cn, specs.client, specs.take_id, a.client_dir, by=a.by, approve=a.approve or [], approve_all=a.approve_all,
                           reject=a.reject or [], change=a.change, label=a.label, owner=a.owner, category=a.category, note=a.note or "")
    print("  ", res)
    print("  re-run `validate` (or the pipeline) to apply approved 'expected' decisions to the take")
    return 0


def cmd_all(a) -> int:
    """One take end to end. Gates 4 and 5 hold the run unless --auto-approve (unattended runs: CI, demos);
    triage needs the model, so it runs separately (`triage`, then `decide` / `approve --gate 3`)."""
    cmd_db(a)
    if cmd_profile(a) == 2:
        print("  stopped: gate 1 (spec change) is required before this take can run")
        return 2
    for fn in (cmd_reshape, cmd_load, cmd_build, cmd_validate, cmd_cleanse):
        fn(a)
    rc = cmd_recon(a)
    if rc:
        return rc
    rc = cmd_load_csm(a)
    return rc or cmd_publish_take(a)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["profile", "map-draft", "reshape", "db", "load", "build", "validate", "cleanse", "recon", "triage", "decide",
                                    "approve", "reject", "gates", "load-csm", "publish-take", "all"])
    ap.add_argument("--client-dir", default=str(PLATFORM / "clients" / "sample"))
    ap.add_argument("--landing", help="folder with the take's files (reshape, all)")
    ap.add_argument("--work", help="work folder for parquet and reports (outside OneDrive)")
    ap.add_argument("--take", help="take id: clients/<client>/takes/<take>.yaml (default: clients/<client>/take.yaml)")
    ap.add_argument("--target", choices=["localdb", "fabric"], default="localdb")
    ap.add_argument("--database", default="CogsConv", help="LocalDB database name")
    g = ap.add_argument_group("decide (gate 3)")
    g.add_argument("--by", help="who decides (recorded in the decisions file)")
    g.add_argument("--approve", nargs="+", metavar="GROUP_KEY", help="approve these proposals as proposed")
    g.add_argument("--approve-all", action="store_true", help="approve every proposal that has no decision yet")
    g.add_argument("--reject", nargs="+", metavar="GROUP_KEY", help="reject: the group needs investigation")
    g.add_argument("--change", metavar="GROUP_KEY", help="record a different label / owner / category for one group")
    g.add_argument("--label", choices=["expected", "actionable", "investigate"])
    g.add_argument("--owner", choices=["client", "cogsdale", "none"])
    g.add_argument("--category", choices=["expected_by_design", "fix_in_source", "fix_in_mapping", "fix_in_setup", "needs_decision"])
    g.add_argument("--note")
    g3 = ap.add_argument_group("gates 4 and 5 (load-csm, publish-take, all)")
    g3.add_argument("--auto-approve", action="store_true", help="unattended run: record gates 4 and 5 as auto_approved instead of waiting")
    g3.add_argument("--gate-timeout", type=int, default=3600, help="seconds to wait for a person's decision (default 3600)")
    g2 = ap.add_argument_group("approve / reject (gates 1-6)")
    g2.add_argument("--gate", type=int, choices=range(1, 7), help="1 spec change, 2 low-confidence fixes, 3 triage, 4 load, 5 publish, 6 acceptance")
    g4 = ap.add_argument_group("map-draft (P1)")
    g4.add_argument("--with-client-hints", action="store_true", help="add clients/<client>/mapping-hints.yaml to the prompt (default: blind)")
    g4.add_argument("--modules", nargs="+", help="UM modules to draft (default: all in the catalog)")
    a = ap.parse_args(argv)
    if a.cmd in ("decide", "approve", "reject") and not a.by:
        ap.error(f"{a.cmd} needs --by <name>: every decision records who made it")
    if a.cmd in ("approve", "reject") and not a.gate:
        ap.error(f"{a.cmd} needs --gate <1-6>")
    fn = {"profile": cmd_profile, "map-draft": cmd_map_draft, "reshape": cmd_reshape, "db": cmd_db, "load": cmd_load, "build": cmd_build,
          "validate": cmd_validate,
          "cleanse": cmd_cleanse, "recon": cmd_recon, "triage": cmd_triage, "decide": cmd_decide, "approve": cmd_approve,
          "reject": cmd_approve, "gates": cmd_gates, "load-csm": cmd_load_csm, "publish-take": cmd_publish_take, "all": cmd_all}[a.cmd]
    return fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
