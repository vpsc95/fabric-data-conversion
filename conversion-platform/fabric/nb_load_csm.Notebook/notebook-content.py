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

# # 6 · Load to CSM: the metadata-driven loader (CONV emulator in the prototype)
# After gate 4, every valid row goes through the CSM procedure for its module (the names, parameters and outputs of
# Cogsdale's business-logic procedures), in the recommended order, one call per row with its status recorded, so a
# rerun retries only what didn't load. Historical reads use the set-based fast path only after an automatic
# equivalence check. The prototype loads a CONV emulator (shadow mode); production goes through the gateway.
# The post-load reconciliation opens gate 5.

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
    from convplat import gates, sqlio
    from convplat.specs import ClientSpecs
    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = specs.take_id
    run_dir = f"/lakehouse/default/Files/runs/{client}/{take}"
    os.makedirs(run_dir, exist_ok=True)
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))
    t0 = time.time()
    sqlio.exec_proc(cn, "EXEC load.usp_PrepareTake ?, ?", client, take)
    sqlio.exec_proc(cn, "EXEC load.usp_LoadAll ?, ?", client, take)
    rows = sqlio.query(cn, "SELECT Module, ExpectedToLoad, Loaded, Failed, Variance, ControlName, AmountVariance FROM recon.v_PostLoad "
                           "WHERE ClientId = ? AND TakeId = ? ORDER BY Module, ControlName", client, take)
    for r in rows:
        print(f"{r['Module']:9} {r['ControlName'] or '':12} expected={r['ExpectedToLoad']} loaded={r['Loaded']} failed={r['Failed']} variance={r['Variance']}")
    variance = sum(abs(int(r["Variance"] or 0)) for r in rows) + sum(int(r["Failed"] or 0) for r in rows)
    amounts = sum(abs(float(r["AmountVariance"] or 0)) for r in rows if r["ControlName"])
    gates.open_gate(cn, client, take, 5, {"what": "Post-load reconciliation: publish to TEST and TRAIN?", "modules": rows,
                                          "record_variance": variance, "amount_variance": amounts,
                                          "target": "CONV emulator (shadow mode): no GP/CSM server in the prototype"})
    out = {"take_id": take, "seconds": round(time.time() - t0, 1), "record_variance": variance, "amount_variance": amounts,
           "loaded": sum(int(r["Loaded"] or 0) for r in rows if not r["ControlName"])}
    if variance or amounts >= 0.005:
        raise RuntimeError(f"post-load variance: {variance} records, {amounts:.2f} in control totals")
except Exception:
    fail("nb_load_csm")
    raise

notebookutils.notebook.exit(json.dumps(out, default=str))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
