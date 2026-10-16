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

# # P1 · Mapping agent (draft Field Info mapping for gate 1)
# Run on demand when a client is onboarded or its extracts change shape; it is not a step of the take pipeline.
# Reads the take's profile from step 0 (`Files/runs/<client>/<take>/profile.json`: column names, types, blanks,
# lengths, value shapes and short code sets; never row values) and the CSM target catalog, and asks the regional
# Foundry deployment in `fabric/workspace.json` for one proposal per target field.
# - The target side is template text only: the lead's client-specific notes and hand mapping are never sent.
# - A PII gate checks each exact prompt first; a hit blocks the call. Every call is logged in `run.AiCall`.
# - Output: `Files/runs/<client>/<take>/mapping-draft/` (draft JSON and Markdown, a Field Info workbook for the
#   gate 1 review, and the evaluation when the catalog carries the lead's mapping). Nothing is applied: a person
#   turns approved proposals into `clients/<client>/mapping/*.yaml` through the spec change gate.
# - Blind by default. `with_client_hints` adds `clients/<client>/mapping-hints.yaml` (institutional knowledge);
#   a score obtained with hints written from the same client's mapping is labelled as tuned.

# PARAMETERS CELL ********************

client = "sample"
take_id = ""               # empty = clients/<client>/take.yaml; else clients/<client>/takes/<take_id>.yaml
modules = ""               # comma-separated UM modules, empty = every module in the catalog
with_client_hints = False

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

import json, os, sys, traceback
PLATFORM = "/lakehouse/default/Files/platform"
ERRORS = "/lakehouse/default/Files/runs/_errors"
sys.path.insert(0, f"{PLATFORM}/engine")


def fail(step):
    os.makedirs(ERRORS, exist_ok=True)
    with open(f"{ERRORS}/{step}.txt", "w") as f:
        f.write(traceback.format_exc())


try:
    from convplat import sqlio
    from convplat.mapping_agent import evaluate, load_workspace_config, run_mapping_agent
    from convplat.specs import ClientSpecs

    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = specs.take_id
    run_dir = f"/lakehouse/default/Files/runs/{client}/{take}"
    profile = f"{run_dir}/profile.json"
    if not os.path.exists(profile):
        raise FileNotFoundError(f"{profile} not found: run nb_profile (pipeline step 0) for this take first")
    catalog = f"{PLATFORM}/catalog/cogsdale-csm-gp/catalog.{client}.json"
    hints = f"{PLATFORM}/clients/{client}/mapping-hints.yaml" if with_client_hints else None
    out_dir = f"{run_dir}/mapping-draft-hints" if hints else f"{run_dir}/mapping-draft"
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))
    token = notebookutils.credentials.getToken("https://cognitiveservices.azure.com")
    draft = run_mapping_agent(cn, catalog, profile, load_workspace_config(f"{PLATFORM}/fabric/workspace.json"), lambda: token, out_dir,
                              [m.strip() for m in modules.split(",") if m.strip()] or None, f"{PLATFORM}/tools/scan_for_pii.py",
                              client=client, take=take, hints_path=hints)
    try:
        from convplat.fieldinfo_xlsx import write_workbook
        write_workbook(draft, f"{out_dir}/FieldInfo_mapping_draft.xlsx")
    except ImportError as e:                    # openpyxl missing: the JSON and Markdown drafts are still written
        print("workbook skipped:", e)
    out = {"take_id": take, "mode": draft["mode"], "fields": len(draft["mappings"]), "usage": draft["usage"]}
    if any((r.get("source_field") or "").strip() for r in json.load(open(catalog, encoding="utf-8"))):
        o = evaluate(draft, catalog, out_dir, profile)["overall"]
        out["evaluation"] = {k: o[k] for k in ("lead_mapped", "source_column_matches", "source_column_accuracy_pct",
                                               "expression_matches", "expression_accuracy_pct", "partial_matches")}
    print(json.dumps(out, indent=1))
except Exception:
    fail("nb_map_draft")
    raise

notebookutils.notebook.exit(json.dumps(out))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
