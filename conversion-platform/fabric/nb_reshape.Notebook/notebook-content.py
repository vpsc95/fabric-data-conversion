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

# # 1 · Reshape the take (landing → bronze → silver)
# Reads every extract of the take **as text**, exactly as received, and writes:
# - `bronze_<extract>`: every row of the sheet with lineage (file, sheet, row number);
# - `silver_<extract>`: data rows only, after the spec's reshape steps (report artifacts removed, platform fill-down checked against the client's hand-built helper columns, service address parsed);
# - `silver_<extract>_artifacts`: every dropped row with the reason, so nothing disappears silently;
# - `Files/runs/<client>/<take>/reshape-report.json`: counts only.
#
# Behaviour comes from `clients/<client>/reshape/*.yaml`; the engine is `Files/platform/engine/convplat`.

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
    from convplat.specs import ClientSpecs
    from convplat.reshape import run_reshape, to_columns

    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = take_id or specs.take_id
    landing = f"/lakehouse/default/Files/landing/{client}/{take}"
    run_dir = f"/lakehouse/default/Files/runs/{client}/{take}"
    os.makedirs(run_dir, exist_ok=True)
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    tables = f"abfss://{ws['workspace_id']}@onelake.dfs.fabric.microsoft.com/{ws['lakehouse_id']}/Tables/dbo"
    storage = {"bearer_token": notebookutils.credentials.getToken("storage"), "use_fabric_endpoint": "true"}
    if os.path.exists(f"{run_dir}/manifest.json"):   # chain of custody: reshape exactly what step 0 recorded
        from convplat import profile as prof
        changed = prof.verify(landing, json.load(open(f"{run_dir}/manifest.json")),
                              only={s["source"]["file"] for s in specs.file_reshapes(landing)})
        if changed:
            raise RuntimeError("custody check failed (re-run step 0): " + "; ".join(changed))
        print("custody: every spec file matches its recorded SHA-256")

    def frame(data):
        return pl.DataFrame({k: pl.Series(k, v, dtype=pl.Int32 if k == "_row" else pl.Utf8) for k, v in data.items()})

    def write(df, name):
        df.write_delta(f"{tables}/{name}", mode="overwrite", storage_options=storage)

    reports = []
    for spec in specs.file_reshapes(landing):
        t0 = time.time()
        r = run_reshape(spec, landing)
        name = r.target.split(".", 1)[1]
        write(frame(to_columns(r.bronze_columns, r.bronze_rows, list(range(1, len(r.bronze_rows) + 1)), take, r.source_file, r.sheet)), f"bronze_{name}")
        write(frame(to_columns(r.silver_columns, r.silver_rows, r.silver_row_numbers, take, r.source_file, r.sheet)), f"silver_{name}")
        write(pl.DataFrame({"_take_id": [take] * len(r.artifacts), "_row": [n for n, _ in r.artifacts], "reason": [x for _, x in r.artifacts]},
                           schema={"_take_id": pl.Utf8, "_row": pl.Int32, "reason": pl.Utf8}), f"silver_{name}_artifacts")
        r.report["seconds"] = round(time.time() - t0, 1)
        reports.append(r.report)
        print(f"{r.spec_id:18} read={r.report['rows_read']:>7} kept={r.report['rows_kept']:>7} artifacts={r.report['artifacts']} "
              f"fill-down mismatches={ {k: v['mismatches'] for k, v in r.report['fill_down_checks'].items()} } ({r.report['seconds']}s)")

    with open(f"{run_dir}/reshape-report.json", "w") as f:
        json.dump({"client": client, "take_id": take, "reshapes": reports}, f, indent=1)
    summary = {"take_id": take, "extracts": len(reports), "rows_kept": {r["spec"]: r["rows_kept"] for r in reports}}
except Exception:
    fail("nb_reshape")
    raise

notebookutils.notebook.exit(json.dumps(summary))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
