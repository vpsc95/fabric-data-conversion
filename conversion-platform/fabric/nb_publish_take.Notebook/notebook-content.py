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

# # 8 · Publish the take: runbook, client validation sample, integrity report (gate 6)
# After gate 5: the 54 runbook steps are recorded (done with evidence where the platform runs them, simulated where
# they need GP or SQL Server infrastructure, eliminated where the platform made them unnecessary), the client's
# validation sample is drawn, and the data integrity report is generated from the run (HTML and Word here; the PDF
# copy is rendered on a workstation). Gate 6 (take acceptance, an e-signature in production) opens with them.

# PARAMETERS CELL ********************

client = "sample"
take_id = ""          # empty = clients/<client>/take.yaml; else clients/<client>/takes/<take_id>.yaml

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

try:
    try:
        import docx  # noqa: F401  (python-docx writes the Word copy of the integrity report)
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "python-docx"])
    from convplat import gates, integrity_report, runbook, sqlio
    from convplat.specs import ClientSpecs
    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = specs.take_id
    run_dir = f"/lakehouse/default/Files/runs/{client}/{take}"
    os.makedirs(run_dir, exist_ok=True)
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))
    client_dir = f"{PLATFORM}/clients/{client}"
    runbook.seed_steps(cn, client_dir)
    rb = runbook.execute(cn, client_dir, take)
    print("runbook:", {k: v for k, v in rb.items() if k != "answer_key_summary"})
    sqlio.exec_proc(cn, "EXEC recon.usp_BuildValidationSample ?, ?", client, take)
    sample = sqlio.query(cn, "SELECT COUNT(*) AS n FROM run.ValidationSample WHERE ClientId = ? AND TakeId = ?", client, take)[0]["n"]
    rep = integrity_report.generate(cn, client_dir, take, run_dir, f"{run_dir}/report", pdf=False)
    fix = sqlio.query(cn, "SELECT FinalOwner, COUNT(*) AS n FROM recon.v_FixList WHERE ClientId = ? AND TakeId = ? GROUP BY FinalOwner", client, take)
    gates.open_gate(cn, client, take, 6, {"what": "Take acceptance: sign the integrity report (e-signature in production).",
                                          "validation_sample_accounts": sample, "open_fix_items_by_owner": {r["FinalOwner"]: r["n"] for r in fix},
                                          "integrity_report": {"html": rep["html"], "docx": rep["docx"]}})
    out = {"take_id": take, "runbook": {k: v for k, v in rb.items() if k not in ("answer_key_summary",)}, "validation_sample": sample,
           "report": {"html": rep["html"], "docx": rep["docx"], "checks": rep["checks"]}}
except Exception:
    fail("nb_publish_take")
    raise

notebookutils.notebook.exit(json.dumps(out, default=str))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
