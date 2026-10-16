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

# # Step 4 · Approve and load into CSM
# **Before:** SmartConnect maps 08-16 pushed staging into the CSM business-logic procedures (slow on meter reads,
# licence-capped), then counts and control totals were checked by hand for the integrity report.
#
# **Now:** a person reviews the Power BI report and runs the pipeline `Approve_and_load` with their name. The load
# writes the ready records (here: stand-in CSM tables; in production: the CSM procedures through the on-premises
# gateway), and records who approved it with the reconciliation: received = loaded + held back, in records and dollars.

# PARAMETERS CELL ********************

take_id = "go-live"
approved_by = ""        # required: the person who approves this load

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


if not approved_by.strip():
    raise ValueError("Who approves this load? Run the pipeline with the parameter approved_by set to your name.")
cn = connect()
cn.execute("EXEC mvp.usp_LoadToCsm @TakeId = ?, @ApprovedBy = ?", take_id, approved_by.strip())

cur = cn.execute("SELECT TOP (1) ApprovedBy, ApprovedAt, RecordsLoaded, RecordsHeldBack, BalanceReceived, BalanceLoaded, BalanceHeldBack "
                 "FROM mvp.ApprovalLog WHERE TakeId = ? ORDER BY ApprovalId DESC", take_id)
log = dict(zip([d[0] for d in cur.description], cur.fetchone()))
received = cn.execute("SELECT COUNT(*) FROM mvp.Record WHERE TakeId = ?", take_id).fetchone()[0]
ok_records = received == log["RecordsLoaded"] + log["RecordsHeldBack"]
ok_dollars = abs(log["BalanceReceived"] - log["BalanceLoaded"] - log["BalanceHeldBack"]) < 0.005
print(f"Approved by {log['ApprovedBy']} at {log['ApprovedAt']:%Y-%m-%d %H:%M} UTC")
print(f"Records:  {received:,} received = {log['RecordsLoaded']:,} loaded + {log['RecordsHeldBack']:,} held back -> "
      + ("reconciles" if ok_records else "DOES NOT RECONCILE"))
print(f"Balances: ${log['BalanceReceived']:,.2f} received = ${log['BalanceLoaded']:,.2f} loaded + ${log['BalanceHeldBack']:,.2f} held back -> "
      + ("reconciles" if ok_dollars else "DOES NOT RECONCILE"))
if not (ok_records and ok_dollars):
    raise RuntimeError("the load does not reconcile")
notebookutils.notebook.exit(json.dumps({"take_id": take_id, "approved_by": log["ApprovedBy"], "loaded": log["RecordsLoaded"],
                                        "held_back": log["RecordsHeldBack"], "balance_loaded": float(log["BalanceLoaded"])}))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
