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
# META       "default_lakehouse_name": "{{lakehouse}}",
# META       "default_lakehouse_workspace_id": "{{workspace_id}}"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # Step 3 · AI triage: expected by design, or needs action?
# **Before:** reviewer read thousands of failures in GP SmartLists, separated the expected exclusions from the real problems,
# and wrote the notes and Jira tickets by hand (7,119 connection failures at go-live; about 439 needed action).
#
# **Now:** an Azure AI Foundry model (gpt-4.1-mini, Canada East) reads the issue *groups* (rule, code and count, never
# a customer's data) with the approved go-live decisions, and proposes for each group: expected or needs action, who
# fixes it, and a message the client can act on. A PII check runs on the exact prompt first. Nothing is applied: a
# person reviews the proposals in Power BI and approves the load (pipeline `Approve_and_load`).

# PARAMETERS CELL ********************

take_id = "go-live"
log_folder = ""         # empty = Files/runs/<take_id> in the lakehouse: what was sent and received, for audit

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

import json
import os
import re
import struct

import pyodbc
import requests

SQL_SERVER = "{{sql_server}}"
SQL_DATABASE = "{{sql_database_name}}"
FOUNDRY = "{{foundry_endpoint}}"                 # regional Azure AI Foundry resource (Canada East), Entra ID only
DEPLOYMENT, API_VERSION = "{{foundry_deployment}}", "{{foundry_api_version}}"


def connect():
    """Fabric SQL database, signed in with the notebook's Entra ID token: no passwords anywhere."""
    token = notebookutils.credentials.getToken("https://database.windows.net/").encode("utf-16-le")
    return pyodbc.connect("Driver={ODBC Driver 18 for SQL Server};Server=tcp:" + SQL_SERVER + ",1433;Database=" + SQL_DATABASE
                          + ";Encrypt=yes", attrs_before={1256: struct.pack(f"<I{len(token)}s", len(token), token)}, autocommit=True)


def query(cn, sql, *params):
    cur = cn.execute(sql, *params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# ## What the model sees: the issue groups and the approved decisions (codes and counts only)

# CELL ********************

cn = connect()
groups = query(cn, "SELECT g.RuleId, g.GroupValue, g.Module, g.RuleText, g.Records, v.Ticket FROM mvp.IssueGroup AS g "
                   "JOIN mvp.ValidationRule AS v ON v.RuleId = g.RuleId WHERE g.TakeId = ? ORDER BY g.Module, g.RuleId, g.GroupValue",
               take_id)
decisions = [f"Service code {r['ServiceCode']}: {r['Reason']}"
             for r in query(cn, "SELECT ServiceCode, Reason FROM mvp.ServiceCode WHERE Reason <> '' ORDER BY ServiceCode")]
context = {"approved_go_live_decisions": decisions,
           "issue_groups": [{"id": i, "module": g["Module"], "rule": g["RuleText"], "go_live_ticket": g["Ticket"],
                             "group": g["GroupValue"], "records": g["Records"]} for i, g in enumerate(groups, 1)]}
prompt = json.dumps(context, indent=1)
print(prompt)

# PII check on the exact prompt: long numbers (account, meter, licence), emails or phone numbers stop the call
found = re.findall(r"\d{7,}|[\w.+-]+@[\w-]+\.\w+|\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}", prompt)
if found:
    raise RuntimeError(f"PII check failed: {len(found)} value(s) look like personal data; nothing was sent")
print(f"\nPII check passed: {len(groups)} groups, {len(prompt):,} characters, codes and counts only")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# ## Ask the model, with a strict answer format

# CELL ********************

SYSTEM = """You triage data-conversion issues for a utility moving to Cogsdale CSM (customer billing on Dynamics GP).
For each issue group decide:
- verdict: "Expected" when an approved go-live decision explains it (by design, nothing to fix), otherwise "Needs action".
- owner: "Client" when the client must correct its source data, "Cogsdale" when the mapping or CSM setup must change,
  "None" when the verdict is Expected.
- action: one short sentence for the conversion team.
- client_message: one plain-English sentence the client can act on (empty unless owner is Client).
- reason: one short sentence naming the decision or evidence you used.
Use only the information given. Answer for every group id."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["groups"], "properties": {"groups": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["id", "verdict", "owner", "action", "client_message", "reason"],
    "properties": {"id": {"type": "integer"}, "verdict": {"type": "string", "enum": ["Expected", "Needs action"]},
                   "owner": {"type": "string", "enum": ["Client", "Cogsdale", "None"]}, "action": {"type": "string"},
                   "client_message": {"type": "string"}, "reason": {"type": "string"}}}}}}

token = notebookutils.credentials.getToken("https://cognitiveservices.azure.com")
response = requests.post(
    f"{FOUNDRY.rstrip('/')}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}",
    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    json={"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], "temperature": 0, "seed": 7,
          "response_format": {"type": "json_schema", "json_schema": {"name": "triage", "strict": True, "schema": SCHEMA}}},
    timeout=180)
response.raise_for_status()
answer = json.loads(response.json()["choices"][0]["message"]["content"])["groups"]
usage = response.json().get("usage", {})
print(f"{len(answer)} proposals; tokens: {usage.get('prompt_tokens')} in, {usage.get('completion_tokens')} out")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# ## Save the proposals next to the issues (the report shows them), and log what was sent

# CELL ********************

by_id = {a["id"]: a for a in answer}
for i, g in enumerate(groups, 1):
    a = by_id.get(i)
    if a is None:
        raise RuntimeError(f"the model returned no proposal for group {i}")
    cn.execute("UPDATE mvp.IssueGroup SET AiVerdict = ?, AiOwner = ?, AiAction = ?, AiClientMessage = ?, AiReason = ?, AiModel = ? "
               "WHERE TakeId = ? AND RuleId = ? AND GroupValue = ?",
               a["verdict"], a["owner"], a["action"][:300], a["client_message"][:400], a["reason"][:400], DEPLOYMENT,
               take_id, g["RuleId"], g["GroupValue"])
    print(f"{a['verdict']:13} {a['owner']:9} {g['Records']:>6,}  {g['RuleId']} {g['GroupValue'] or ''}")

folder = log_folder or f"/lakehouse/default/Files/runs/{take_id}"
os.makedirs(folder, exist_ok=True)
with open(os.path.join(folder, "ai_triage.json"), "w", encoding="utf-8") as f:
    json.dump({"model": DEPLOYMENT, "endpoint": FOUNDRY, "sent": context, "received": answer, "usage": usage}, f, indent=1)
expected = sum(g["Records"] for i, g in enumerate(groups, 1) if by_id[i]["verdict"] == "Expected")
needs = sum(g["Records"] for g in groups) - expected
print(f"\nExpected by design: {expected:,} records · Needs action: {needs:,} records")
notebookutils.notebook.exit(json.dumps({"take_id": take_id, "groups": len(groups), "expected_records": expected,
                                        "needs_action_records": needs,
                                        "tokens": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}}))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
