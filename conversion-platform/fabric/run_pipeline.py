"""Run the take-replay pipeline in Fabric and wait for it, printing each activity's result.

  python run_pipeline.py                          # sample / go-live, defaults from the pipeline
  python run_pipeline.py --take go-live --deploy-sql --require-ai --auto-approve
  python run_pipeline.py --take sim-take2 --gate-timeout-minutes 30      # gates 4 and 5 wait for a person
  python run_pipeline.py --notebook nb_publish    # one step only
  python run_pipeline.py --notebook nb_map_draft --param modules=UM20400 # P1 mapping agent, on demand

Identifiers come from fabric/workspace.json; auth from `az login` in the target tenant.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests
from azure.identity import AzureCliCredential

HERE = Path(__file__).resolve().parent
WS = json.loads((HERE / "workspace.json").read_text(encoding="utf-8"))
API = "https://api.fabric.microsoft.com/v1"


def session() -> requests.Session:
    s = requests.Session()
    tok = AzureCliCredential(tenant_id=WS["tenant_id"]).get_token("https://api.fabric.microsoft.com/.default").token
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


def item_id(s: requests.Session, name: str, kind: str) -> str:
    r = s.get(f"{API}/workspaces/{WS['workspace_id']}/items", params={"type": kind})
    r.raise_for_status()
    return next(i["id"] for i in r.json()["value"] if i["displayName"] == name)


def run_notebook(s: requests.Session, name: str, client: str, take: str, extra: dict | None = None) -> int:
    """Run one notebook step on its own (for example nb_publish after a model or report change, or nb_map_draft)."""
    ws = WS["workspace_id"]
    nid = item_id(s, name, "Notebook")
    params = {"client": {"value": client, "type": "string"}, "take_id": {"value": take, "type": "string"}}
    for k, v in (extra or {}).items():
        params[k] = {"value": v, "type": "bool" if isinstance(v, bool) else "int" if isinstance(v, int) else "string"}
    r = s.post(f"{API}/workspaces/{ws}/items/{nid}/jobs/instances", params={"jobType": "RunNotebook"},
               data=json.dumps({"executionData": {"parameters": params}}))
    r.raise_for_status()
    url, started = r.headers["Location"], time.time()
    while True:
        time.sleep(15)
        j = s.get(url).json()
        if j.get("status") in ("Completed", "Failed", "Cancelled", "Deduped"):
            break
    print(f"{name}: {j.get('status')} in {int(time.time() - started)}s {json.dumps(j.get('failureReason'))[:600] if j.get('failureReason') else ''}")
    return 0 if j.get("status") == "Completed" else 1


def parse_param(text: str):
    key, _, raw = text.partition("=")
    value = {"true": True, "false": False}.get(raw.lower(), raw)
    if isinstance(value, str) and value.lstrip("-").isdigit():
        value = int(value)
    return key, value


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pipeline", default="pl_take_replay")
    ap.add_argument("--notebook", help="run only this notebook (e.g. nb_publish) instead of the pipeline")
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="extra notebook parameter (with --notebook)")
    ap.add_argument("--client", default="sample")
    ap.add_argument("--take", default="go-live")
    ap.add_argument("--deploy-sql", action="store_true")
    ap.add_argument("--require-ai", action="store_true")
    ap.add_argument("--auto-approve", action="store_true", help="unattended run: gates 4 and 5 are recorded as auto_approved")
    ap.add_argument("--gate-timeout-minutes", type=int, default=60, help="how long gates 4 and 5 wait for a person")
    a = ap.parse_args(argv)

    s = session()
    if a.notebook:
        return run_notebook(s, a.notebook, a.client, a.take, dict(parse_param(p) for p in a.param))
    ws = WS["workspace_id"]
    pid = item_id(s, a.pipeline, "DataPipeline")
    params = {"client": a.client, "take_id": a.take, "deploy_sql": a.deploy_sql, "require_ai": a.require_ai,
              "auto_approve": a.auto_approve, "gate_timeout_minutes": a.gate_timeout_minutes}
    started = dt.datetime.now(dt.timezone.utc)
    r = s.post(f"{API}/workspaces/{ws}/items/{pid}/jobs/instances", params={"jobType": "Pipeline"},
               data=json.dumps({"executionData": {"parameters": params}}))
    r.raise_for_status()
    job_url = r.headers["Location"]
    job_id = job_url.rstrip("/").split("/")[-1]
    print(f"{a.pipeline} started: job {job_id} {params}")

    status = "NotStarted"
    while status not in ("Completed", "Failed", "Cancelled", "Deduped"):
        time.sleep(20)
        if (dt.datetime.now(dt.timezone.utc) - started).seconds > 3000:
            s = session()                                  # refresh the token on long runs
        j = s.get(job_url).json()
        if j.get("status") != status:
            status = j.get("status")
            print(f"  {dt.datetime.now():%H:%M:%S} {status}")
    took = (dt.datetime.now(dt.timezone.utc) - started).seconds

    body = {"filters": [], "orderBy": [{"orderBy": "ActivityRunStart", "order": "ASC"}],
            "lastUpdatedAfter": (started - dt.timedelta(minutes=5)).isoformat(),
            "lastUpdatedBefore": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat()}
    runs = s.post(f"{API}/workspaces/{ws}/datapipelines/pipelineruns/{job_id}/queryactivityruns", data=json.dumps(body))
    if runs.ok:
        for act in runs.json().get("value", []):
            out = act.get("output") or {}
            exit_value = (out.get("result") or {}).get("exitValue") if isinstance(out, dict) else None
            err = (act.get("error") or {}).get("message", "")
            print(f"  {act['activityName']:28} {act['status']:10} {round((act.get('durationInMs') or 0) / 1000)}s "
                  f"{(exit_value or err or '')[:300]}")
    else:
        print(f"  (activity runs unavailable: HTTP {runs.status_code})")
    if status != "Completed":
        print("  failure:", json.dumps(j.get("failureReason"))[:600])
    print(f"{a.pipeline}: {status} in {took // 60}m {took % 60}s")
    return 0 if status == "Completed" else 1


if __name__ == "__main__":
    sys.exit(main())
