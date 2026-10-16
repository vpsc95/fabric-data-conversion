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

# # 3 · Reconcile against the answer key (golden master)
# Reads the `recon` views (received / loaded / failed per module, issues by rule split into expected and
# actionable, control totals) and checks them against the known outcome: for SAMPLE, the go-live data
# integrity report. Every difference is PASS, ALLOWED (reason + approver in `clients/<client>/allowances.json`)
# or FAIL; rules that aren't in the key are NEW. Results go to `Files/runs/<client>/<take>/` and to
# `run.AnswerKeyCheck` for the Power BI reconciliation page. Any FAIL fails the pipeline.

# PARAMETERS CELL ********************

client = "sample"
take_id = ""          # empty = clients/<client>/take.yaml; else clients/<client>/takes/<take_id>.yaml
answer_key = "auto"   # auto = the take's answer_key (take file); a file in Files/platform/tools; empty = no outcome check

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

import json, os, subprocess, sys, traceback
PLATFORM = "/lakehouse/default/Files/platform"
ERRORS = "/lakehouse/default/Files/runs/_errors"
sys.path.insert(0, f"{PLATFORM}/engine")


def fail(step):
    os.makedirs(ERRORS, exist_ok=True)
    with open(f"{ERRORS}/{step}.txt", "w") as f:
        f.write(traceback.format_exc())


try:
    from convplat import gates, recon, sqlio
    from convplat.specs import ClientSpecs

    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = take_id or specs.take_id
    run_dir = f"/lakehouse/default/Files/runs/{client}/{take}"
    os.makedirs(run_dir, exist_ok=True)
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))

    res = recon.results(cn, client, take)
    with open(f"{run_dir}/run-results.json", "w") as f:
        json.dump(res, f, indent=1)
    for mod, m in res["modules"].items():
        print(f"{mod:9} received={m.get('received')} loaded={m.get('loaded')} failed={m.get('failed')} "
              f"actionable_records={m.get('actionable_failed_records', 0)} totals={m.get('control_totals', {})}")

    summary = {"take_id": take}
    key = specs.take.get("answer_key", "") if answer_key == "auto" else answer_key
    failed = None
    if key:
        cmd = [sys.executable, f"{PLATFORM}/tools/check_answer_key.py", "--results", f"{run_dir}/run-results.json",
               "--key", f"{PLATFORM}/tools/{key}", "--json-out", f"{run_dir}/answer-key-check.json"]
        allow = f"{PLATFORM}/clients/{client}/allowances.json"
        if os.path.exists(allow):
            cmd += ["--allow", allow]
        p = subprocess.run(cmd, capture_output=True, text=True)
        print(p.stdout[-6000:], p.stderr[-2000:])
        check = json.load(open(f"{run_dir}/answer-key-check.json"))
        sqlio.save_answer_key_check(cn, client, take, check["rows"])
        summary["answer_key"] = check["summary"]
        if p.returncode != 0:
            failed = f"answer-key check failed: {check['summary']}"
    else:
        print("no answer key for this take: reconciliation only")
    # gate 4: the pre-load reconciliation is what the load go / no-go decision looks at
    gates.open_gate(cn, client, take, 4, gates.evidence_gate4(cn, client, take))
    if failed:
        raise RuntimeError(failed)
except Exception:
    fail("nb_reconcile")
    raise

notebookutils.notebook.exit(json.dumps(summary))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
