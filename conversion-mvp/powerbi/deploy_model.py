"""Deploy the Conversion MVP semantic model (Direct Lake on the Fabric SQL database, mirrored to OneLake), reframe it,
and check its numbers with DAX.

  python deploy_model.py            create or update "Conversion MVP", reframe, check
  python deploy_model.py --check    only the DAX check

Fabric API calls carry the x-ms-fabric-skill header (powerbi-authoring-cli).
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

import requests
from azure.identity import AzureCliCredential

HERE = Path(__file__).resolve().parent
WS = json.loads((HERE.parent / "workspace.json").read_text(encoding="utf-8"))
MODEL_DIR = HERE / "ConversionMVP.SemanticModel"
FABRIC, PBI = "https://api.fabric.microsoft.com/v1", "https://api.powerbi.com/v1.0/myorg"


def sessions():
    cred = AzureCliCredential(tenant_id=WS["tenant_id"], process_timeout=60)
    fab, pbi = requests.Session(), requests.Session()
    fab.headers.update({"Authorization": "Bearer " + cred.get_token("https://api.fabric.microsoft.com/.default").token,
                        "Content-Type": "application/json", "x-ms-fabric-skill": "powerbi-authoring-cli"})
    pbi.headers.update({"Authorization": "Bearer " + cred.get_token("https://analysis.windows.net/powerbi/api/.default").token,
                        "Content-Type": "application/json"})
    return fab, pbi


def lro(fab, r) -> None:
    if r.status_code not in (200, 201, 202):
        raise SystemExit(f"HTTP {r.status_code}: {r.text[:1500]}")
    if r.status_code == 202:
        url = r.headers["Location"]
        while True:
            time.sleep(int(r.headers.get("Retry-After", 5)))
            body = fab.get(url).json()
            if body.get("status") in ("Succeeded", "Failed", "Undefined"):
                break
        if body.get("status") != "Succeeded":
            raise SystemExit(f"operation {body.get('status')}: {json.dumps(body.get('error'))[:1500]}")


def parts() -> list[dict]:
    out = []
    for f in sorted(MODEL_DIR.rglob("*")):
        if not f.is_file() or f.name == ".platform":
            continue
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".tmdl" and re.search(r"^ +\S", text, re.M):
            raise SystemExit(f"{f.name}: TMDL needs tab indentation")
        text = text.replace("{{workspace_id}}", WS["workspace_id"]).replace("{{sql_database_id}}", WS["sql_database_id"])
        out.append({"path": f.relative_to(MODEL_DIR).as_posix(), "payload": base64.b64encode(text.encode("utf-8")).decode(),
                    "payloadType": "InlineBase64"})
    return out


def model_id(fab) -> str | None:
    r = fab.get(f"{FABRIC}/workspaces/{WS['workspace_id']}/semanticModels")
    r.raise_for_status()
    return next((m["id"] for m in r.json()["value"] if m["displayName"] == WS["semantic_model"]), None)


def dax(pbi, mid: str, query: str) -> list[dict]:
    r = pbi.post(f"{PBI}/groups/{WS['workspace_id']}/datasets/{mid}/executeQueries",
                 data=json.dumps({"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}}))
    if not r.ok:
        raise SystemExit(f"DAX failed: HTTP {r.status_code} {r.text[:1500]}")
    res = r.json()["results"][0]
    if "error" in res:
        raise SystemExit(json.dumps(res["error"])[:1500])
    return [{k.split("[")[-1].rstrip("]"): v for k, v in row.items()} for row in res["tables"][0]["rows"]]


def check(pbi, mid: str) -> int:
    rows = dax(pbi, mid, """
        EVALUATE ADDCOLUMNS(VALUES(Take[Take Id]),
            "Received", [Records Received], "Ready", [Ready to Load], "HeldBack", [Held Back], "Loaded", [Loaded],
            "Issues", [Issues], "Expected", [Expected by Design], "NeedsAction", [Needs Action], "Groups", [Issue Group Count],
            "BalanceReceived", [Balance Received], "BalanceLoaded", [Balance Loaded], "Status", [Approval Status],
            "Reconciliation", [Reconciliation])""")
    fails = 0
    for r in rows:
        print(json.dumps(r, default=str))
        if r["Received"] != (r["Ready"] or 0) + (r["HeldBack"] or 0) + (r["Loaded"] or 0):
            print("  FAIL: received <> ready + held back + loaded"); fails += 1
        if r["Issues"] and r["Expected"] + r["NeedsAction"] != r["Issues"]:
            print("  FAIL: AI verdicts don't cover every issue"); fails += 1
    measures = dax(pbi, mid, "EVALUATE SELECTCOLUMNS(INFO.VIEW.MEASURES(), \"Name\", [Name])")
    row = ", ".join(f"\"{m['Name']}\", [{m['Name']}]" for m in measures)
    values = dax(pbi, mid, f"EVALUATE ROW({row})")[0]
    print(f"{len(values)} of {len(measures)} measures evaluate" + ("" if len(values) == len(measures) else "  FAIL"))
    print("ALL PASS" if not fails and len(values) == len(measures) else "FAILED")
    return 1 if fails or len(values) != len(measures) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only run the DAX check")
    a = ap.parse_args(argv)
    fab, pbi = sessions()
    mid = model_id(fab)
    if not a.check:
        definition = {"format": "TMDL", "parts": parts()}
        if mid:
            lro(fab, fab.post(f"{FABRIC}/workspaces/{WS['workspace_id']}/semanticModels/{mid}/updateDefinition",
                              data=json.dumps({"definition": definition})))
            print(f"updated: {WS['semantic_model']} ({mid})")
        else:
            lro(fab, fab.post(f"{FABRIC}/workspaces/{WS['workspace_id']}/semanticModels", data=json.dumps(
                {"displayName": WS["semantic_model"], "description": "Conversion MVP: Direct Lake on the Fabric SQL database (mirrored to OneLake).",
                 "definition": definition})))
            mid = model_id(fab)
            print(f"created: {WS['semantic_model']} ({mid})")
        r = pbi.post(f"{PBI}/groups/{WS['workspace_id']}/datasets/{mid}/refreshes", data=json.dumps({"notifyOption": "NoNotification"}))
        if r.status_code not in (200, 202):
            raise SystemExit(f"reframe request failed: HTTP {r.status_code} {r.text[:800]}")
        while True:
            time.sleep(5)
            h = pbi.get(f"{PBI}/groups/{WS['workspace_id']}/datasets/{mid}/refreshes", params={"$top": 1}).json()["value"][0]
            if h.get("status") not in ("Unknown", "NotStarted", "InProgress"):
                break
        print(f"reframe: {h.get('status')} {h.get('serviceExceptionJson', '')[:1200]}")
        if h.get("status") != "Completed":
            return 1
    return check(pbi, mid)


if __name__ == "__main__":
    sys.exit(main())
