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

# # 5 · Publish report tables (Power BI)
# Copies this take's reconciliation, answer-key check, triage (proposals + decisions), fix list and run
# metadata from the SQL database into lakehouse Delta tables `rpt_*`. The semantic model reads them in
# Direct Lake mode, so the report shows the new take as soon as this step ends; no import refresh.
# Each table keeps the other takes' rows, so takes can be compared.

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
    import polars as pl
    from convplat import publish, sqlio
    from convplat.specs import ClientSpecs

    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = take_id or specs.take_id
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    tables = f"abfss://{ws['workspace_id']}@onelake.dfs.fabric.microsoft.com/{ws['lakehouse_id']}/Tables/dbo"
    storage = {"bearer_token": notebookutils.credentials.getToken("storage"), "use_fabric_endpoint": "true"}
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))

    t0 = time.time()
    frames = publish.collect(cn, client, take)
    written = {}
    for name, df in frames.items():
        try:
            existing = pl.read_delta(f"{tables}/{name}", storage_options=storage)
        except Exception:
            existing = None                      # first publish
        out = publish.merge_take(existing, df, client, take)
        out.write_delta(f"{tables}/{name}", mode="overwrite", storage_options=storage,
                        delta_write_options={"schema_mode": "overwrite"})
        written[name] = {"take_rows": df.height, "table_rows": out.height}
        print(f"{name:20} take rows={df.height:>6} table rows={out.height:>6}")
    summary = {"take_id": take, "seconds": round(time.time() - t0, 1), "tables": written}
except Exception:
    fail("nb_publish")
    raise

notebookutils.notebook.exit(json.dumps(summary))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
