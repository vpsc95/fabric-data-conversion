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

# # 4 · Triage agent (proposals for the human gate)
# Groups this take's issue records by module, rule set and features (`recon.v_TriageContext`: codes and counts
# only) and asks the regional Foundry deployment in `fabric/workspace.json` to label each group expected,
# actionable or investigate, with the owner, the fix and the wording for the client.
# - A PII gate checks the exact prompt first; a hit blocks the call and is logged in `run.AiCall`.
# - Proposals go to `run.TriageProposal`. Nothing changes until a person decides (gate 3:
#   `run_local.py decide`, recorded in `clients/<client>/triage/decisions.yaml`).
# - Quality against the approved rules goes to `run.StepMetric` (Step = 'triage').
#
# If the notebook can't get a token for the Foundry endpoint, triage is skipped (not failed) unless
# `require_ai` is True; the reviewer can run it from the console with `run_local.py triage --target fabric`.

# PARAMETERS CELL ********************

client = "sample"
take_id = ""          # empty = clients/<client>/take.yaml; else clients/<client>/takes/<take_id>.yaml
require_ai = False    # True = fail the step when the model can't be reached

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
    from convplat import gates, sqlio, triage
    from convplat.specs import ClientSpecs

    specs = ClientSpecs(f"{PLATFORM}/clients/{client}", take_id or None)
    take = take_id or specs.take_id
    ws = json.load(open(f"{PLATFORM}/fabric/workspace.json"))
    cn = sqlio.connect_token(ws["sql_server"], ws["sql_database_name"], notebookutils.credentials.getToken("https://database.windows.net/"))

    token, reason = None, ""
    try:
        token = notebookutils.credentials.getToken("https://cognitiveservices.azure.com")
    except Exception as e:
        reason = f"no token for the Foundry endpoint: {type(e).__name__}: {str(e)[:300]}"

    if token is None:
        if require_ai:
            raise RuntimeError(reason)
        summary = {"take_id": take, "status": "skipped", "reason": reason}
        print("triage skipped:", reason)
    else:
        out_dir = f"/lakehouse/default/Files/runs/{client}/{take}/triage"
        res = triage.run_triage(cn, client, take, ws["foundry"], lambda: token, out_dir, f"{PLATFORM}/tools/scan_for_pii.py")
        print(f"call {res['call_id']}: {res['groups']} groups, {res['latency_ms']} ms, tokens {res['usage']}")
        print("quality:", res["quality"])
        for p in res["problems"]:
            print("problem:", p)
        summary = {"take_id": take, "status": "succeeded", "groups": res["groups"], "quality": res["quality"],
                   "problems": len(res["problems"])}
        gates.open_gate(cn, client, take, 3, gates.evidence_gate3(cn, client, take))   # a person approves, edits or rejects
except Exception:
    fail("nb_triage")
    raise

notebookutils.notebook.exit(json.dumps(summary))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
