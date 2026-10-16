"""Exercise MVP preparation, SQL rules, approval rejection and loading on isolated LocalDB."""
import ast
import json
import sys
import tempfile
import types
import uuid
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conversion-platform" / "engine"))
from convplat import sqlio
from generate_sample import generate


def main():
    database = "ConversionSmoke_" + uuid.uuid4().hex[:12]
    cn = sqlio.connect_localdb(database)
    try:
        sqlio.run_sql(cn, (ROOT / "conversion-mvp" / "sql" / "mvp.sql").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="mvp-synthetic-") as tmp:
            generate(Path(tmp))
            for take, folder in (("go-live", "go-live"), ("take-2", "sim-take2")):
                source = ROOT / "conversion-mvp" / "fabric" / "1_Reshape_reports.Notebook" / "notebook-content.py"
                tree = ast.parse(source.read_text(encoding="utf-8"))
                # Run the notebook's actual transformation and write code; replace only Fabric authentication.
                tree.body = [node for node in tree.body if not (
                    isinstance(node, ast.FunctionDef) and node.name == "connect")]
                overrides = {"take_id": take, "take_note": "Invented local smoke test",
                             "take_folder": str(Path(tmp) / folder)}
                for node in tree.body:
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id in overrides:
                                node.value = ast.Constant(overrides[target.id])
                ast.fix_missing_locations(tree)
                exits = []
                namespace = {"connect": lambda: cn, "notebookutils": types.SimpleNamespace(
                    notebook=types.SimpleNamespace(exit=lambda value: exits.append(json.loads(value))))}
                exec(compile(tree, str(source), "exec"), namespace)
                assert exits[0]["staged"] == {"mvp.Customer": 10, "mvp.Service": 20, "mvp.Balance": 10}
                sqlio.exec_proc(cn, "EXEC mvp.usp_RunRules ?", take)
                count = cn.execute("SELECT COUNT(*) FROM mvp.Record WHERE TakeId=?", take).fetchval()
                assert count == 40, count
                try:
                    sqlio.exec_proc(cn, "EXEC mvp.usp_LoadToCsm ?, ?", take, "")
                except pyodbc.Error as error:
                    if "approv" not in str(error).lower():
                        raise
                else:
                    raise AssertionError("Load accepted an empty approver")
                sqlio.exec_proc(cn, "EXEC mvp.usp_LoadToCsm ?, ?", take, "synthetic-reviewer")
                row = cn.execute("SELECT RecordsLoaded,RecordsHeldBack,BalanceReceived,BalanceLoaded,BalanceHeldBack "
                                 "FROM mvp.ApprovalLog WHERE TakeId=?", take).fetchone()
                assert row[0] + row[1] == 40
                assert row[2] == row[3] + row[4] == 100
                print(f"{take}: approval gate enforced; 40 records and balance 100 reconcile")
    finally:
        cn.close()
        with pyodbc.connect("Driver={ODBC Driver 18 for SQL Server};Server=(localdb)\\MSSQLLocalDB;"
                            "Database=master;Trusted_Connection=yes;Encrypt=no", autocommit=True) as admin:
            # Only the unique database created by this invocation is removed.
            admin.execute(f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            admin.execute(f"DROP DATABASE [{database}]")


if __name__ == "__main__":
    main()
