"""Deploy the conversion platform to the Fabric workspace in fabric/workspace.json.

  python deploy.py bundle      upload engine, specs, SQL and tools to <lakehouse>/Files/platform (OneLake, Entra auth)
  python deploy.py notebooks   import fabric/*.Notebook folders (Fabric CLI)
  python deploy.py pipeline    import fabric/*.DataPipeline folders, wiring notebook IDs (Fabric CLI)
  python deploy.py all
  python deploy.py landing <folder> [client] [take]   upload a take's de-identified extracts to Files/landing/<client>/<take>
  python deploy.py drop-tables <prefix> [prefix ...] delete tables (history included), e.g. bronze_ silver_, before a re-reshape

Identifiers only; no secrets. Auth comes from `az login` / `fab auth login` in the target tenant.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLATFORM = HERE.parent
REPO = PLATFORM.parent
WS = json.loads((HERE / "workspace.json").read_text(encoding="utf-8"))
WS_PATH = f"{WS['workspace']}.Workspace"


def bundle_files(client: str = "sample"):
    yield REPO / "requirements-fabric.txt", "requirements-fabric.txt"
    for p in sorted((PLATFORM / "engine" / "convplat").glob("*.py")):
        yield p, f"engine/convplat/{p.name}"
    yield PLATFORM / "engine" / "run_local.py", "engine/run_local.py"
    cdir = PLATFORM / "clients" / client
    for sub in ("reshape", "crosswalks", "rules", "setup", "triage", "mapping", "takes"):
        for p in sorted((cdir / sub).glob("*.yaml")):
            yield p, f"clients/{client}/{sub}/{p.name}"
    for name in ("take.yaml", "allowances.json", "runbook.yaml", "jira-refs.yaml", "mapping-hints.yaml"):
        if (cdir / name).exists():
            yield cdir / name, f"clients/{client}/{name}"
    for p in sorted((PLATFORM / "catalog" / "cogsdale-csm-gp").glob("catalog.*.json")):   # mapping agent (P1) target catalog
        yield p, f"catalog/cogsdale-csm-gp/{p.name}"
    yield PLATFORM / "rules" / "catalog.yaml", "rules/catalog.yaml"
    for p in sorted((PLATFORM / "sql").glob("*.sql")):
        yield p, f"sql/{p.name}"
    yield HERE / "workspace.json", "fabric/workspace.json"
    gm = REPO / ".github" / "skills" / "golden-master-test"
    yield gm / "scripts" / "check_answer_key.py", "tools/check_answer_key.py"
    for key in (gm / "references").glob("*-answer-key.json"):
        yield key, f"tools/{key.name}"
    yield REPO / ".github" / "skills" / "pii-guard" / "scripts" / "scan_for_pii.py", "tools/scan_for_pii.py"   # triage PII gate


def upload_bundle() -> None:
    fs = _onelake()
    base = f"{WS['lakehouse_id']}/Files/platform"
    n = 0
    for local, rel in bundle_files():
        fs.get_file_client(f"{base}/{rel}").upload_data(local.read_bytes(), overwrite=True)
        n += 1
    print(f"bundle: uploaded {n} files to {WS['lakehouse']}/Files/platform")


def _onelake():
    from azure.identity import AzureCliCredential
    from azure.storage.filedatalake import DataLakeServiceClient
    svc = DataLakeServiceClient("https://onelake.dfs.fabric.microsoft.com", credential=AzureCliCredential(tenant_id=WS["tenant_id"]))
    return svc.get_file_system_client(WS["workspace_id"])


def upload_landing(folder: str, client: str, take: str) -> None:
    """Upload a take's (de-identified) extract files to Files/landing/<client>/<take>, replacing what is there."""
    src = Path(folder)
    if not src.is_dir():
        raise SystemExit(f"not a folder: {src}")
    fs = _onelake()
    base = f"{WS['lakehouse_id']}/Files/landing/{client}/{take}"
    names = {p.name for p in src.iterdir() if p.is_file()}
    from azure.core.exceptions import ResourceNotFoundError
    try:
        existing = [p for p in fs.get_paths(base, recursive=False) if not p.is_directory]
    except ResourceNotFoundError:                                # a new take: nothing landed yet
        existing = []
    for path in existing:
        if path.name.rsplit("/", 1)[-1] not in names:
            fs.get_file_client(path.name).delete_file()          # a file the new take doesn't have
    for p in sorted(src.iterdir()):
        if p.is_file():
            with p.open("rb") as fh:
                fs.get_file_client(f"{base}/{p.name}").upload_data(fh, overwrite=True, length=p.stat().st_size)
            print(f"landing: {p.name} ({p.stat().st_size:,} bytes)")
    print(f"landing: {len(names)} files in {WS['lakehouse']}/Files/landing/{client}/{take}")


def fab(*args: str) -> str:
    r = subprocess.run(["fab", *args], capture_output=True, text=True, shell=sys.platform == "win32")
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0 or "[" in out and "Error" in out:
        raise RuntimeError(f"Fabric CLI failed: {out}")
    return out


def import_notebooks() -> dict:
    ids = {}
    for folder in sorted(HERE.glob("*.Notebook")):
        name = folder.name.rsplit(".", 1)[0]
        stage = Path.home() / ".cogs-deploy" / folder.name
        stage.mkdir(parents=True, exist_ok=True)
        source = (folder / "notebook-content.py").read_text(encoding="utf-8")
        source = source.replace('"default_lakehouse_name": "lh_conversion"', '"default_lakehouse_name": "{{lakehouse}}"')
        for key in ("workspace_id", "lakehouse_id", "lakehouse"):
            source = source.replace("{{" + key + "}}", WS[key])
        dependency_cell = '''
import importlib.util
import subprocess
import sys
_modules = ("polars", "pyarrow", "deltalake", "yaml", "openpyxl", "pyodbc", "docx", "requests")
if any(importlib.util.find_spec(module) is None for module in _modules):
    subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                    "/lakehouse/default/Files/platform/requirements-fabric.txt"], check=True)
'''
        marker = "# CELL ********************"
        source = source.replace(marker, marker + "\n" + dependency_cell, 1)
        (stage / "notebook-content.py").write_text(source, encoding="utf-8")
        (stage / ".platform").write_text((folder / ".platform").read_text(encoding="utf-8"), encoding="utf-8")
        fab("import", f"{WS_PATH}/{folder.name}", "-i", str(stage), "--format", ".py", "-f")
        ids[name] = fab("get", f"{WS_PATH}/{folder.name}", "-q", "id").splitlines()[-1].strip()
        print(f"notebook: {name} -> {ids[name]}")
    return ids


def import_pipelines(ids: dict) -> None:
    for folder in sorted(HERE.glob("*.DataPipeline")):
        content = (folder / "pipeline-content.json").read_text(encoding="utf-8")
        for name, nid in ids.items():
            content = content.replace("{{" + name + "}}", nid)
        content = content.replace("{{workspace_id}}", WS["workspace_id"])
        stage = Path.home() / ".cogs-deploy" / folder.name
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "pipeline-content.json").write_text(content, encoding="utf-8")
        (stage / ".platform").write_text((folder / ".platform").read_text(encoding="utf-8"), encoding="utf-8")
        fab("import", f"{WS_PATH}/{folder.name}", "-i", str(stage), "-f")
        print(f"pipeline: {folder.name} imported")


def drop_tables(prefixes: list[str]) -> None:
    """Delete lakehouse tables whose name starts with a prefix, history included, so the next reshape recreates
    them at version 0. Use when a take's landing files are replaced (for example by a corrected de-identified copy):
    old versions, and the column statistics in their Delta log, would otherwise keep the earlier data."""
    fs = _onelake()
    base = f"{WS['lakehouse_id']}/Tables/dbo"
    names = sorted(p.name.rsplit("/", 1)[-1] for p in fs.get_paths(base, recursive=False) if p.is_directory)
    for name in (n for n in names if any(n.startswith(x) for x in prefixes)):
        fs.get_directory_client(f"{base}/{name}").delete_directory()
        print(f"dropped: {name}")
    print("re-run the reshape step (nb_reshape or the pipeline) to recreate them")


def main(argv=None) -> int:
    args = argv or sys.argv[1:] or ["all"]
    cmd = args[0]
    if cmd == "drop-tables":
        if len(args) < 2:
            raise SystemExit("usage: deploy.py drop-tables <prefix> [prefix ...]   e.g. bronze_ silver_")
        drop_tables(args[1:])
        return 0
    if cmd == "landing":
        if len(args) < 2:
            raise SystemExit("usage: deploy.py landing <folder> [client] [take]")
        upload_landing(args[1], args[2] if len(args) > 2 else "sample", args[3] if len(args) > 3 else "go-live")
        return 0
    if cmd in ("bundle", "all"):
        upload_bundle()
    ids = import_notebooks() if cmd in ("notebooks", "pipeline", "all") else {}
    if cmd in ("pipeline", "all"):
        import_pipelines(ids)
    return 0


if __name__ == "__main__":
    sys.exit(main())
