"""Deploy the Conversion MVP to its Fabric workspace (identifiers in workspace.json; auth from `az login` and `fab auth login`).

  python deploy.py sql                      create the tables, rules and procedures in the Fabric SQL database
  python deploy.py files [take ...]         upload a take's 3 de-identified extracts to Files/landing/<take> (default: go-live take-2)
  python deploy.py notebooks                import the 4 notebooks (identifiers filled in)
  python deploy.py pipelines                import Prepare_take and Approve_and_load (notebook IDs filled in)
  python deploy.py run <pipeline> [k=v ...] run a pipeline and wait, e.g. run Prepare_take take_id=go-live
  python deploy.py all                      sql, files, notebooks, pipelines

The semantic model and report: powerbi/deploy_model.py and powerbi/build_report.py.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = json.loads((HERE / "workspace.json").read_text(encoding="utf-8"))
WS_PATH = f"{WS['workspace']}.Workspace"
API = "https://api.fabric.microsoft.com/v1"
DEID = Path(os.environ.get("CONVERSION_SAMPLE_ROOT", str(HERE.parent / ".local" / "synthetic")))
TAKES = {"go-live": DEID / "go-live", "take-2": DEID / "sim-take2"}          # take-2 is simulated (see README)
EXTRACTS = ("CUSTOMERS *.xlsx", "UB Services Report *.xlsx", "UB Account Balances *.xlsx")
STAGE = Path.home() / ".cogs-deploy-mvp"


def placeholders() -> dict[str, str]:
    f = WS["foundry"]
    return {"workspace_id": WS["workspace_id"], "lakehouse_id": WS["lakehouse_id"], "lakehouse": WS["lakehouse"],
            "sql_server": WS["sql_server"], "sql_database_name": WS["sql_database_name"], "foundry_endpoint": f["endpoint"],
            "foundry_deployment": f["deployment"], "foundry_api_version": f["api_version"]}


def fill(text: str, values: dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    left = sorted(set(re.findall(r"\{\{([a-z0-9_]+)\}\}", text)))
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    return text


def credential():
    from azure.identity import AzureCliCredential
    return AzureCliCredential(tenant_id=WS["tenant_id"], process_timeout=60)


def sql_connection():
    import struct
    import pyodbc
    token = credential().get_token("https://database.windows.net/.default").token.encode("utf-16-le")
    return pyodbc.connect("Driver={ODBC Driver 18 for SQL Server};Server=tcp:" + WS["sql_server"] + ",1433;Database="
                          + WS["sql_database_name"] + ";Encrypt=yes", attrs_before={1256: struct.pack(f"<I{len(token)}s", len(token), token)},
                          autocommit=True, timeout=60)


def deploy_sql() -> None:
    cn = sql_connection()
    batches = [b for b in re.split(r"^\s*GO\s*$", (HERE / "sql" / "mvp.sql").read_text(encoding="utf-8"), flags=re.M | re.I) if b.strip()]
    for i, batch in enumerate(batches, 1):
        cur = cn.cursor()
        cur.execute(batch)
        while cur.nextset():
            pass
    rules = cn.execute("SELECT COUNT(*), SUM(CAST(IsActive AS int)) FROM mvp.ValidationRule").fetchone()
    print(f"sql: {len(batches)} batches; {rules[0]} rules ({rules[1]} active)")


def fab(*args: str) -> str:
    r = subprocess.run(["fab", *args], capture_output=True, text=True, shell=sys.platform == "win32")
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise SystemExit(f"fab {' '.join(args)} failed:\n{out}")
    return out


def upload_files(takes: list[str]) -> None:
    from azure.storage.filedatalake import DataLakeServiceClient
    fs = DataLakeServiceClient("https://onelake.dfs.fabric.microsoft.com", credential=credential()).get_file_system_client(WS["workspace_id"])
    requirements = HERE.parent / "requirements-fabric.txt"
    fs.get_file_client(f"{WS['lakehouse_id']}/Files/platform/requirements-fabric.txt").upload_data(requirements.read_bytes(), overwrite=True)
    for take in takes:
        for pattern in EXTRACTS:
            matches = list(TAKES[take].glob(pattern))
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one {pattern} in {TAKES[take]}; run tools/generate_sample.py first")
            src = matches[0]
            with src.open("rb") as fh:
                fs.get_file_client(f"{WS['lakehouse_id']}/Files/landing/{take}/{src.name}").upload_data(fh, overwrite=True, length=src.stat().st_size)
            print(f"files: {take}/{src.name} ({src.stat().st_size:,} bytes)")


def import_notebooks() -> dict[str, str]:
    ids, values = {}, placeholders()
    for folder in sorted((HERE / "fabric").glob("*.Notebook")):
        stage = STAGE / folder.name
        stage.mkdir(parents=True, exist_ok=True)
        source = fill((folder / "notebook-content.py").read_text(encoding="utf-8"), values)
        dependencies = '''
import importlib.util
import subprocess
import sys
if any(importlib.util.find_spec(module) is None for module in ("pandas", "openpyxl", "pyodbc", "requests")):
    subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                    "/lakehouse/default/Files/platform/requirements-fabric.txt"], check=True)
'''
        marker = "# CELL ********************"
        source = source.replace(marker, marker + "\n" + dependencies, 1)
        (stage / "notebook-content.py").write_text(source, encoding="utf-8")
        (stage / ".platform").write_text((folder / ".platform").read_text(encoding="utf-8"), encoding="utf-8")
        fab("import", f"{WS_PATH}/{folder.name}", "-i", str(stage), "--format", ".py", "-f")
        ids[folder.stem] = fab("get", f"{WS_PATH}/{folder.name}", "-q", "id").splitlines()[-1].strip()
        print(f"notebook: {folder.stem} -> {ids[folder.stem]}")
    return ids


def import_pipelines(ids: dict[str, str]) -> None:
    values = {**placeholders(), **ids}
    for folder in sorted((HERE / "fabric").glob("*.DataPipeline")):
        stage = STAGE / folder.name
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "pipeline-content.json").write_text(fill((folder / "pipeline-content.json").read_text(encoding="utf-8"), values), encoding="utf-8")
        (stage / ".platform").write_text((folder / ".platform").read_text(encoding="utf-8"), encoding="utf-8")
        fab("import", f"{WS_PATH}/{folder.name}", "-i", str(stage), "-f")
        print(f"pipeline: {folder.stem} imported")


def notebook_ids() -> dict[str, str]:
    return {f.stem: fab("get", f"{WS_PATH}/{f.name}", "-q", "id").splitlines()[-1].strip() for f in sorted((HERE / "fabric").glob("*.Notebook"))}


def run_pipeline(name: str, params: dict[str, str]) -> int:
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + credential().get_token("https://api.fabric.microsoft.com/.default").token,
                      "Content-Type": "application/json"})
    items = s.get(f"{API}/workspaces/{WS['workspace_id']}/items", params={"type": "DataPipeline"}).json()["value"]
    pid = next(i["id"] for i in items if i["displayName"] == name)
    r = s.post(f"{API}/workspaces/{WS['workspace_id']}/items/{pid}/jobs/instances", params={"jobType": "Pipeline"},
               data=json.dumps({"executionData": {"parameters": params}}))
    r.raise_for_status()
    url, t0 = r.headers["Location"], time.time()
    print(f"{name} started {params}")
    status = ""
    while status not in ("Completed", "Failed", "Cancelled", "Deduped"):
        time.sleep(15)
        status = s.get(url).json().get("status", "")
    job = s.get(url).json()
    print(f"{name}: {status} in {int(time.time() - t0)}s" + (f" {json.dumps(job.get('failureReason'))[:600]}" if status != "Completed" else ""))
    return 0 if status == "Completed" else 1


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "all"
    if cmd in ("sql", "all"):
        deploy_sql()
    if cmd in ("files", "all"):
        upload_files(args[1:] if cmd == "files" and len(args) > 1 else list(TAKES))
    ids = import_notebooks() if cmd in ("notebooks", "all") else None
    if cmd in ("pipelines", "all"):
        import_pipelines(ids or notebook_ids())
    if cmd == "run":
        return run_pipeline(args[1], dict(a.split("=", 1) for a in args[2:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
