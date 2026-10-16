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

# # Step 2 · Run the validation rules
# **Before:** a validation script per module, run one at a time; tailoring a client meant commenting code out.
#
# **Now:** the rules are rows in the table `mvp.ValidationRule` in the Fabric SQL database. One procedure,
# `mvp.usp_RunRules`, runs every active rule, holds back the records that break one, and groups the issues by
# rule and code for the AI agent. Add a rule = add a row.

# PARAMETERS CELL ********************

take_id = "go-live"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

import json
import struct

import pyodbc

SQL_SERVER = "{{sql_server}}"
SQL_DATABASE = "{{sql_database_name}}"


def connect():
    """Fabric SQL database, signed in with the notebook's Entra ID token: no passwords anywhere."""
    token = notebookutils.credentials.getToken("https://database.windows.net/").encode("utf-16-le")
    return pyodbc.connect("Driver={ODBC Driver 18 for SQL Server};Server=tcp:" + SQL_SERVER + ",1433;Database=" + SQL_DATABASE
                          + ";Encrypt=yes", attrs_before={1256: struct.pack(f"<I{len(token)}s", len(token), token)}, autocommit=True)


def query(cn, sql, *params):
    cur = cn.execute(sql, *params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


cn = connect()
cn.execute("EXEC mvp.usp_RunRules @TakeId = ?", take_id)

status = query(cn, "SELECT Module, Status, COUNT(*) AS Records FROM mvp.Record WHERE TakeId = ? GROUP BY Module, Status "
                   "ORDER BY Module, Status", take_id)
for r in status:
    print(f"{r['Module']:10} {r['Status']:10} {r['Records']:>8,}")
groups = query(cn, "SELECT RuleId, GroupValue, Records FROM mvp.IssueGroup WHERE TakeId = ? ORDER BY Records DESC", take_id)
print(f"\n{sum(g['Records'] for g in groups):,} issues in {len(groups)} groups:")
for g in groups:
    print(f"  {g['RuleId']:8} {g['GroupValue'] or '-':38} {g['Records']:>7,}")
notebookutils.notebook.exit(json.dumps({"take_id": take_id, "groups": len(groups),
                                        "status": {f"{r['Module']} {r['Status']}": r["Records"] for r in status}}))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
