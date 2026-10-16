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

# # Gate · hold the run until a person decides (gates 4 and 5)
# The platform opened the gate with the evidence the approver needs. A person decides in the workbench or with
# `run_local.py approve --target fabric --gate N --by <name>`; this step waits, polling every 20 seconds. A demo run
# may set auto_approve: the decision is then recorded as auto_approved by the pipeline parameter, never as a person's.

# PARAMETERS CELL ********************

client = "sample"
take_id = ""          # empty = clients/<client>/take.yaml; else clients/<client>/takes/<take_id>.yaml
gate = 4              # 4 load go / no-go, 5 publish
auto_approve = False  # demo runs only: record the gate as auto_approved instead of waiting
timeout_minutes = 60

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
    status = gates.wait(cn, client, take, int(gate), timeout_s=int(timeout_minutes) * 60, poll_s=20, auto_approve=bool(auto_approve))
    print(f"gate {gate} ({gates.GATES[int(gate)]}): {status}")
    out = {"take_id": take, "gate": int(gate), "status": status}
except Exception:
    fail(f"nb_gate_{gate}")
    raise

notebookutils.notebook.exit(json.dumps(out))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
