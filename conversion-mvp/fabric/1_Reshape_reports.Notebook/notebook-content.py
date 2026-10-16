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

# # Step 1 · Reshape the client's report extracts
# **Before:** the client and Cogsdale fixed the printed reports by hand in Excel every take: fill the account number down,
# remove page headers, split the two services printed side by side. Then SmartConnect maps 01-05 loaded pre-staging.
#
# **Now:** this notebook does it in seconds, the same way every take, and writes clean rows to the Fabric SQL database.
# The files stay in OneLake exactly as received.

# PARAMETERS CELL ********************

take_id = "go-live"
take_note = ""          # optional description of the take, shown in the report
take_folder = ""        # empty = the take's folder in the lakehouse: Files/landing/<take_id>

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

import datetime as dt
import glob
import json
import os
import re
import struct

import pandas as pd
import pyodbc

SQL_SERVER = "{{sql_server}}"
SQL_DATABASE = "{{sql_database_name}}"
ACCOUNT = r"^\d{2}-\d{4}-\d{2}$"          # an SAMPLE account number, e.g. 12-3456-01
folder = take_folder or f"/lakehouse/default/Files/landing/{take_id}"


def connect():
    """Fabric SQL database, signed in with the notebook's Entra ID token: no passwords anywhere."""
    token = notebookutils.credentials.getToken("https://database.windows.net/").encode("utf-16-le")
    return pyodbc.connect("Driver={ODBC Driver 18 for SQL Server};Server=tcp:" + SQL_SERVER + ",1433;Database=" + SQL_DATABASE
                          + ";Encrypt=yes", attrs_before={1256: struct.pack(f"<I{len(token)}s", len(token), token)}, autocommit=True)


def read_report(pattern):
    """Read one extract exactly as the client sent it: every column as text, column names trimmed."""
    path = glob.glob(os.path.join(folder, pattern))[0]
    df = pd.read_excel(path, sheet_name=0, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    return df.apply(lambda col: col.str.strip()), os.path.basename(path)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# ## Customers: already a table, so just keep the columns CSM needs

# CELL ********************

cus, customers_file = read_report("CUSTOMERS*.xlsx")
cus = cus[cus["INCODE ACCT"].str.match(ACCOUNT)]          # drops blank lines and repeated headers
customers = pd.DataFrame({
    "SourceRow": cus.index + 2,                         # the row number in the client's Excel file
    "Account": cus["INCODE ACCT"], "LastName": cus["LAST NAME"], "FirstName": cus["FIRST NAME"],
    "DriversLicense": cus["DRIVERS LICENSE"], "DlState": cus["DL ST"], "Zip": cus["ZIP"],
    "CustomerClass": cus["CUSTOMER CLASS"], "CustomerStatus": cus["CUSTOMER STATUS"]})
print(f"{customers_file}: {len(customers):,} customers")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# ## Services report: the printed report becomes one row per service
# 1. Keep the service lines (they start with a 3-digit service code); page headers, footers and separators go.
# 2. Fill the account number down: the report prints it on an account's first line only.
# 3. Unpivot: the report prints two services side by side, so each line becomes one or two rows.

# CELL ********************

svc, services_file = read_report("UB Services Report*.xlsx")
svc["Account"] = svc["ACCOUNT #"].where(svc["ACCOUNT #"].str.match(ACCOUNT)).ffill()          # step 2: fill down
lines = svc[svc["DESCRIPTION"].str.match(r"^\d{3} - ") & svc["Account"].notna()]               # step 1: service lines only

first = pd.DataFrame({"SourceRow": lines.index + 2, "Slot": 1, "Account": lines["Account"], "ServiceText": lines["DESCRIPTION"],
                      "Status": lines["STATUS"], "RateTable": lines["TABLE"], "Meter": lines["METER"]})
two = lines[lines["DESCRIPTION2"].str.match(r"^\d{3} - ")]
second = pd.DataFrame({"SourceRow": two.index + 2, "Slot": 2, "Account": two["Account"], "ServiceText": two["DESCRIPTION2"],
                       "Status": two["STATUS2"], "RateTable": two["TABLE2"], "Meter": two["METER2"]})
services = pd.concat([first, second], ignore_index=True)                                          # step 3: unpivot
services.insert(3, "ServiceCode", services["ServiceText"].str[:3])

removed = len(svc) - len(lines)
print(f"{services_file}: {len(svc):,} report lines -> {len(lines):,} service lines ({removed:,} layout lines removed) "
      f"-> {len(services):,} services")
same = int((lines["ACCT"] == lines["Account"]).sum()) if "ACCT" in lines else 0
if "ACCT" in lines:                         # the client's own fill-down, typed by hand in Excel: compare, don't trust
    print(f"Fill-down vs the client's hand-built ACCT column: same account on {same:,} lines; "
          f"on {len(lines) - same:,} lines the hand-built column has no account number")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# ## Balances report: keep the account lines (they carry the balance; the lines below hold the mailing address)

# CELL ********************

bal, balances_file = read_report("UB Account Balances*.xlsx")
acct_lines = bal[bal["ACCOUNT #"].str.match(ACCOUNT)]
balances = pd.DataFrame({"SourceRow": acct_lines.index + 2, "Account": acct_lines["ACCOUNT #"], "AccountStatus": acct_lines["STATUS"],
                         "Balance": pd.to_numeric(acct_lines["BALANCE"].str.replace(",", ""), errors="coerce").fillna(0).round(2)})
print(f"{balances_file}: {len(bal):,} report lines -> {len(balances):,} balances, total ${balances['Balance'].sum():,.2f}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# ## Write the clean rows to the Fabric SQL database (staging), replacing this take's rows

# CELL ********************

def replace_take_rows(cn, table, df):
    """Delete this take's rows, then insert the new ones. Each batch of 5,000 rows travels as one JSON document
    (one round trip), and SQL converts the text to each column's type."""
    cn.execute(f"DELETE {table} WHERE TakeId = ?", take_id)
    df = df.assign(TakeId=take_id).astype(str)
    cols = ", ".join(df.columns)
    insert = (f"INSERT {table} ({cols}) SELECT {cols} FROM OPENJSON(?) "
              f"WITH ({', '.join(c + ' nvarchar(400)' for c in df.columns)})")
    for i in range(0, len(df), 5000):
        cn.execute(insert, df.iloc[i:i + 5000].to_json(orient="records", force_ascii=False))
    return len(df)


date = re.search(r"(\d{2})(\d{2})(\d{4})", customers_file)            # the take date is in the file names, e.g. 07172026 (pii-scan: ignore)
take_date = dt.date(int(date.group(3)), int(date.group(1)), int(date.group(2)))
cn = connect()
cn.execute("DELETE mvp.Take WHERE TakeId = ?", take_id)
cn.execute("INSERT mvp.Take (TakeId, TakeDate, Description) VALUES (?, ?, ?)", take_id, take_date,
           take_note or f"Client extracts dated {take_date:%B %d, %Y}")
written = {t: replace_take_rows(cn, t, df) for t, df in (("mvp.Customer", customers), ("mvp.Service", services),
                                                         ("mvp.Balance", balances))}
print("staged:", {k: f"{v:,}" for k, v in written.items()})
notebookutils.notebook.exit(json.dumps({"take_id": take_id, "take_date": str(take_date), "staged": written,
                                        "layout_lines_removed": removed, "fill_down_same_as_hand": same,
                                        "hand_column_without_account": (len(lines) - same) if "ACCT" in lines else None}))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
