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

# # 2 · Stage, build and validate in the SQL database
# 1. (optional) deploy the platform SQL (`Files/platform/sql`), the same scripts that run on a client's SQL Server;
# 2. seed metadata from the specs: rule catalog, client rule overrides, crosswalks, CSM setup;
# 3. copy the silver tables into `slv` (text, lineage kept; widths checked, never truncated);
# 4. `gold.usp_Build_All`: UM staging, ported from the legacy `sp_Load_UM_*` procedures;
# 5. `rules.usp_Validate_All`: the validation rules, writing `isvalid`/`message` and one `run.Issue` row per issue.

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
SLV = {"customers": "slv.Customers", "services": "slv.Services", "balances": "slv.Balances", "deposits": "slv.Deposits", "reads": "slv.Reads"}
timings = {}


def fail(step):
    os.makedirs(ERRORS, exist_ok=True)
    with open(f"{ERRORS}/{step}.txt", "w") as f:
        f.write(traceback.format_exc())


def timed(name, fn, *args):
    t0 = time.time()
    out = fn(*args)
    timings[name] = round(time.time() - t0, 1)
    print(f"{name}: {timings[name]}s {out if out is not None else ''}")
    return out


try:
    from deltalake import DeltaTable
    from convplat import cleanse, gates, seed, sqlio
    from convplat.specs import ClientSpecs

    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = take_id or specs.take_id
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    tables = f"abfss://{ws['workspace_id']}@onelake.dfs.fabric.microsoft.com/{ws['lakehouse_id']}/Tables/dbo"
    storage = {"bearer_token": notebookutils.credentials.getToken("storage"), "use_fabric_endpoint": "true"}
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))

    if deploy_sql:
        timed("deploy", sqlio.deploy, cn, f"{PLATFORM}/sql")
    timed("seed", seed.seed, cn, PLATFORM, f"{PLATFORM}/clients/{client}")

    def load_all():
        counts = {}
        for name, table in SLV.items():
            t = DeltaTable(f"{tables}/silver_{name}", storage_options=storage).to_pyarrow_table()
            counts[table] = sqlio.load_table(cn, table, {c: t.column(c).to_pylist() for c in t.column_names}, take)
        return counts

    timed("load_slv", load_all)

    # reshape metrics for the run report / Power BI
    report = json.load(open(f"/lakehouse/default/Files/runs/{client}/{take}/reshape-report.json"))
    cur = cn.cursor()
    cur.execute("DELETE run.StepMetric WHERE ClientId = ? AND TakeId = ? AND Step = 'reshape'", client, take)
    for r in report["reshapes"]:
        metrics = [("rows_read", r["rows_read"]), ("rows_kept", r["rows_kept"])] + [(f"artifacts.{k}", v) for k, v in r["artifacts"].items()] \
            + [(f"fill_down_mismatch.{k}", v["mismatches"]) for k, v in r["fill_down_checks"].items()]
        for metric, value in metrics:
            cur.execute("INSERT run.StepMetric (ClientId, TakeId, Step, Item, Metric, Value) VALUES (?, ?, 'reshape', ?, ?, ?)",
                        client, take, r["spec"], metric, value)

    timed("gold_build", sqlio.exec_proc, cn, "EXEC gold.usp_Build_All ?, ?", client, take)
    timed("validate", sqlio.exec_proc, cn, "EXEC rules.usp_Validate_All ?, ?", client, take)
    # P7: deterministic cleansing proposals (stored, never applied in a replay); low-confidence ones open gate 2
    timed("cleanse", lambda: cleanse.run(cn, client, take)["generated"])
    ev2 = cleanse.gate2_evidence(cn, client, take)
    gates.open_gate(cn, client, take, 2, ev2, needed=ev2["pending_low"] > 0)
    print(f"gate 2: {ev2['low']} low-confidence proposals ({ev2['pending_low']} awaiting review)")

    steps = sqlio.query(cn, "SELECT StepName, RowsAffected, Status FROM run.RunLog WHERE RunLogId IN (SELECT MAX(RunLogId) FROM run.RunLog "
                            "WHERE ClientId = ? AND TakeId = ? GROUP BY StepName) ORDER BY RunLogId", client, take)
    for s in steps:
        print(f"  {s['StepName']:34} rows={s['RowsAffected']} {s['Status']}")
    failed = [s["StepName"] for s in steps if s["Status"] not in ("Succeeded", "Running")]
    if failed:
        raise RuntimeError(f"SQL steps failed: {failed}")
except Exception:
    fail("nb_sql_steps")
    raise

notebookutils.notebook.exit(json.dumps({"take_id": take, "timings_s": timings}))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
