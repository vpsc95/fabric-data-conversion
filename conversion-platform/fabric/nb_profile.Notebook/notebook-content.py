# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "jupyter",
# META     "jupyter_kernel_name": "python3.11"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "{{lakehouse_id}}",
# META       "default_lakehouse_name": "lh_conversion",
# META       "default_lakehouse_workspace_id": "{{workspace_id}}"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # 0 · Profile the take: chain of custody, conformance and drift (gate 1)
# Every received file is hashed (SHA-256) before anything reads it; step 1 re-checks the hashes, so the take is
# processed exactly as received. Column statistics are metadata only (types, blanks, lengths, value shapes, and
# code sets for short code columns). The take is checked against what the approved specs need and against the
# client's previous take. A blocking finding opens gate 1 and stops the run: the spec change is approved first.

# PARAMETERS CELL ********************

client = "sample"
take_id = ""          # empty = clients/<client>/take.yaml; else clients/<client>/takes/<take_id>.yaml
deploy_sql = False    # True = (re)deploy the platform SQL objects first

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

import json, os, sys, time, traceback
PLATFORM = "/lakehouse/default/Files/platform"
ERRORS = "/lakehouse/default/Files/runs/_errors"
sys.path.insert(0, f"{PLATFORM}/engine")


def fail(step):
    os.makedirs(ERRORS, exist_ok=True)
    with open(f"{ERRORS}/{step}.txt", "w") as f:
        f.write(traceback.format_exc())

SLV = {"customers": "slv.Customers", "services": "slv.Services", "balances": "slv.Balances", "deposits": "slv.Deposits", "reads": "slv.Reads"}
try:
    from convplat import gates, sqlio
    from convplat import profile as prof
    from convplat.specs import ClientSpecs
    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = specs.take_id
    run_dir = f"/lakehouse/default/Files/runs/{client}/{take}"
    os.makedirs(run_dir, exist_ok=True)
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))
    landing = f"/lakehouse/default/Files/landing/{client}/{take}"
    if deploy_sql:
        print("deployed:", ", ".join(sqlio.deploy(cn, f"{PLATFORM}/sql")))
    files = prof.manifest(landing)
    p = prof.profile_take(specs, landing, files)
    slv = {f"silver.{n}": list(sqlio.table_columns(cn, t)) for n, t in SLV.items()}
    needed = prof.needed_columns(specs, slv, landing)
    prev_take, prev = prof.previous_profile(cn, client, take, str(specs.take.get("conversion_date") or "") or None)
    findings = prof.conformance(p, needed, files) + [dict(f, compared_to=prev_take) for f in prof.drift(p, prev)]
    summary = prof.summarize(findings)
    for name, obj in (("manifest", files), ("profile", p), ("drift", {"summary": summary, "compared_to": prev_take, "findings": findings})):
        with open(f"{run_dir}/{name}.json", "w") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
    prof.save(cn, client, take, files, p, findings, {s["source"]["file"]: s["id"] for s in specs.file_reshapes(landing)},
              take_date=str(specs.take.get("conversion_date") or ""), simulated=bool(specs.take.get("simulated")))
    gates.open_gate(cn, client, take, 1, gates.evidence_gate1(summary, findings, prev_take), needed=summary["gate1_required"])
    for x in findings:
        if x["severity"] != "info":
            print(f"{x['severity']:8} {x['kind']:20} {x.get('file') or ''} {x.get('column') or ''}: {x['detail']}")
    print(f"{len(files)} files hashed; compared to {prev_take or 'the approved specs only'}; {summary}")
    if summary["gate1_required"]:
        raise RuntimeError("gate 1 (spec change) is required: the approved specs no longer fit this take")
    out = {"take_id": take, "files": len(files), "compared_to": prev_take, "drift": summary}
except Exception:
    fail("nb_profile")
    raise

notebookutils.notebook.exit(json.dumps(out))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
