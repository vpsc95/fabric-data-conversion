"""Generate invented, small inputs for both demos. Never reads customer data."""
import argparse
import csv
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]


def workbook(path, sheet, columns, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(columns)
    for row in rows:
        ws.append([row.get(c, "") for c in columns])
    wb.properties.creator = "Synthetic demo generator"
    wb.properties.lastModifiedBy = "Synthetic demo generator"
    wb.save(path)
    wb.close()


def generate(output):
    customer_cols = ["INCODE ACCT", "SERVICEADDRESS", "FIRST NAME", "LAST NAME", "SOCIAL", "DOB",
                     "DRIVERS LICENSE", "DL ST", "ADDRESS1", "ADDRESS2", "ADDRESSATTN", "CITY", "ST", "ZIP",
                     "EMAIL", "PHONE NUMBER", "CELL NUMBER", "HOME NUMBER", "CUSTOMER CLASS", "START DATE", "CUSTOMER STATUS"]
    service_cols = ["ACCOUNT #", "START DATE", "DESCRIPTION", "STATUS", "TABLE", "METER",
                    "DESCRIPTION2", "STATUS2", "TABLE2", "METER2", "ACCT", "STDATE"]
    balance_cols = ["ACCOUNT #", "STATUS", "BALANCE", "SVC1", "BAL1", "SVC2", "BAL2", "SVC3", "BAL3", "ACCT"]
    deposit_cols = ["ACCOUNT", "ID", "RECEIPT", "DEPOSIT CODE", "DEPDATE", "RECEIVED", "UNBILLED", "INTEREST APPLIED", "TARGET DATE", "REFDATE"]
    read_cols = ["Account_ID", "Meter_ID", "Meter_SN", "Endpoint_SN", "Read_Time", "Read", "Flow",
                 "Account_Full_Name", "Service_Point_Class_Code", "Meter_Manufacturer", "Meter_Model", "Meter_Size",
                 "Meter_Size_Desc", "Dials"]
    for take, date, second in [("go-live", "01012026", False), ("sim-take2", "02012026", True)]:
        folder = output / take
        folder.mkdir(parents=True, exist_ok=True)
        customers, services, balances, deposits, reads = [], [], [], [], []
        services.append({"ACCOUNT #": "REPORT HEADER"})
        for i in range(1, 11):
            account = f"90-{i:04d}-01"
            meter = f"DEMO{i:04d}"
            customers.append({
                "INCODE ACCT": account, "FIRST NAME": "SYNTHETIC", "LAST NAME": f"ACCOUNT{i:02d}",
                "SERVICEADDRESS": f"{i} Example" + " Way", "ADDRESS1": f"DEMO LOCATION {i}",
                "CITY": "EXAMPLE", "ST": "TX", "ZIP": "00000", "DRIVERS LICENSE": "DEMO",
                "DL ST": "ExampleState" if i == 1 and not second else "TX", "CUSTOMER CLASS": "RES",
                "START DATE": "01/01/2025", "CUSTOMER STATUS": "ACTIVE"})
            services.append({
                "ACCOUNT #": account, "START DATE": "01/01/2025", "ACCT": account, "STDATE": "01/01/2025",
                "DESCRIPTION": "410 - DEMO NEW" if second and i == 3 else "100 - WATER",
                "STATUS": "ON", "TABLE": "WR35", "METER": "" if i == 2 else meter,
                "DESCRIPTION2": "200 - SEWER", "STATUS2": "ON", "TABLE2": "SWR", "METER2": meter})
            balances.append({"ACCOUNT #": account, "STATUS": "ACTIVE", "BALANCE": "10.00",
                             "SVC1": "100", "BAL1": "10.00", "ACCT": account})
            deposits.append({"ACCOUNT": account, "ID": "1", "RECEIPT": f"DEMO{i}", "DEPOSIT CODE": "RESI",
                             "DEPDATE": "01/01/2025", "RECEIVED": "5.00", "UNBILLED": "0", "INTEREST APPLIED": "0"})
            for month in (11, 12):
                reads.append({"Account_ID": account, "Meter_ID": meter, "Meter_SN": meter, "Endpoint_SN": meter,
                              "Read_Time": f"2025-{month}-01", "Read": str(month * 10), "Flow": "100",
                              "Account_Full_Name": "SYNTHETIC ACCOUNT", "Service_Point_Class_Code": "W",
                              "Meter_Manufacturer": "DEMO", "Meter_Model": "DEMO", "Meter_Size": "0.75",
                              "Meter_Size_Desc": '3/4"', "Dials": "6"})
        workbook(folder / f"CUSTOMERS {date}.xlsx", "USEXTF", customer_cols, customers)
        workbook(folder / f"UB Services Report {date}.xlsx", "US Services Report", service_cols, services)
        workbook(folder / f"UB Account Balances {date}.xlsx", "Sheet3", balance_cols, balances)
        workbook(folder / f"UB Deposit Listing {date}.xlsx", "Sheet1", deposit_cols, deposits)
        with (folder / f"Meters and Readings {date}.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=read_cols)
            writer.writeheader()
            writer.writerows(reads)
        print(f"{take}: 10 invented accounts, 20 services, 10 balances, 10 deposits, 20 readings")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "synthetic")
    generate(parser.parse_args().output)
