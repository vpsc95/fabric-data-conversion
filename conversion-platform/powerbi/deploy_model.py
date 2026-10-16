"""Deploy the Direct Lake semantic model in powerbi/<name>.SemanticModel to the conversion workspace.

  python deploy_model.py                 # create or update "Conversion Run", then reframe (refresh)
  python deploy_model.py --no-refresh

- The workspace comes from fabric/workspace.json (ID from when it was created); the lakehouse is resolved by name.
- Creates the model with its definition when it doesn't exist; otherwise sends the FULL definition to
  updateDefinition (the API replaces everything, so every part goes, and never .platform).
- Long-running operations are polled to the end. Fabric API calls carry the x-ms-fabric-skill header.
- Then asks Power BI to refresh the model: for Direct Lake that's a reframe onto the latest Delta versions.
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
WS = json.loads((HERE.parent / "fabric" / "workspace.json").read_text(encoding="utf-8"))
FABRIC = "https://api.fabric.microsoft.com/v1"
PBI = "https://api.powerbi.com/v1.0/myorg"
SKILL = "powerbi-authoring-cli"


class Api:
    def __init__(self):
        cred = AzureCliCredential(tenant_id=WS["tenant_id"])
        self.fabric = requests.Session()
        self.fabric.headers.update({"Authorization": f"Bearer {cred.get_token('https://api.fabric.microsoft.com/.default').token}",
                                    "Content-Type": "application/json", "x-ms-fabric-skill": SKILL})
        self.pbi = requests.Session()
        self.pbi.headers.update({"Authorization": f"Bearer {cred.get_token('https://analysis.windows.net/powerbi/api/.default').token}",
                                 "Content-Type": "application/json"})

    def lro(self, r: requests.Response) -> dict:
        """Follow a 202 to its terminal state; return the result body (or {})."""
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:1500]}")
        if r.status_code != 202:
            return r.json() if r.content else {}
        url, wait = r.headers["Location"], int(r.headers.get("Retry-After", 5))
        while True:
            time.sleep(wait)
            st = self.fabric.get(url)
            st.raise_for_status()
            body = st.json()
            if body.get("status") in ("Succeeded", "Failed", "Undefined"):
                break
        if body.get("status") != "Succeeded":
            raise RuntimeError(f"operation {body.get('status')}: {json.dumps(body.get('error'))[:1500]}")
        res = self.fabric.get(url.rstrip("/") + "/result")
        return res.json() if res.ok and res.content else {}


def parts(model_dir: Path, lakehouse_id: str) -> list[dict]:
    out = []
    for f in sorted(model_dir.rglob("*")):
        if not f.is_file() or f.name == ".platform":
            continue
        rel = f.relative_to(model_dir).as_posix()
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".tmdl":
            in_dax = False
            for n, ln in enumerate(text.splitlines(), 1):
                if ln.count("```") % 2:
                    in_dax = not in_dax
                if not in_dax and re.match(r"^ +\S", ln):
                    raise SystemExit(f"{rel}:{n}: TMDL needs tab indentation, found spaces")
        text = text.replace("{{workspace_id}}", WS["workspace_id"]).replace("{{lakehouse_id}}", lakehouse_id)
        out.append({"path": rel, "payload": base64.b64encode(text.encode("utf-8")).decode(), "payloadType": "InlineBase64"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", default=str(HERE / "ConversionRun.SemanticModel"))
    ap.add_argument("--name", default="Conversion Run")
    ap.add_argument("--no-refresh", action="store_true")
    a = ap.parse_args(argv)

    api, ws = Api(), WS["workspace_id"]
    info = api.fabric.get(f"{FABRIC}/workspaces/{ws}")
    info.raise_for_status()
    if not info.json().get("capacityId"):
        raise SystemExit("the workspace has no capacity; Direct Lake needs one")
    lh = api.fabric.get(f"{FABRIC}/workspaces/{ws}/items", params={"type": "Lakehouse"})
    lh.raise_for_status()
    lakehouse_id = next(i["id"] for i in lh.json()["value"] if i["displayName"] == WS["lakehouse"])
    definition = {"format": "TMDL", "parts": parts(Path(a.model_dir), lakehouse_id)}
    print(f"definition: {len(definition['parts'])} parts; lakehouse {WS['lakehouse']} ({lakehouse_id})")

    models = api.fabric.get(f"{FABRIC}/workspaces/{ws}/semanticModels")
    models.raise_for_status()
    model_id = next((m["id"] for m in models.json()["value"] if m["displayName"] == a.name), None)
    if model_id:
        api.lro(api.fabric.post(f"{FABRIC}/workspaces/{ws}/semanticModels/{model_id}/updateDefinition",
                                data=json.dumps({"definition": definition})))
        print(f"updated: {a.name} ({model_id})")
    else:
        api.lro(api.fabric.post(f"{FABRIC}/workspaces/{ws}/semanticModels",
                                data=json.dumps({"displayName": a.name, "description": "Conversion take results, triage and answer-key check "
                                                 "(Direct Lake on lh_conversion rpt_* tables).", "definition": definition})))
        models = api.fabric.get(f"{FABRIC}/workspaces/{ws}/semanticModels")
        model_id = next(m["id"] for m in models.json()["value"] if m["displayName"] == a.name)
        print(f"created: {a.name} ({model_id})")

    if not a.no_refresh:
        r = api.pbi.post(f"{PBI}/groups/{ws}/datasets/{model_id}/refreshes", data=json.dumps({"notifyOption": "NoNotification"}))
        if r.status_code not in (200, 202):
            raise SystemExit(f"refresh request failed: HTTP {r.status_code} {r.text[:800]}")
        while True:
            time.sleep(5)
            h = api.pbi.get(f"{PBI}/groups/{ws}/datasets/{model_id}/refreshes", params={"$top": 1}).json()["value"][0]
            if h.get("status") not in ("Unknown", "NotStarted", "InProgress"):
                break
        print(f"refresh: {h.get('status')} {h.get('serviceExceptionJson', '')[:800]}")
        if h.get("status") != "Completed":
            return 1
    print(json.dumps({"semantic_model_id": model_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
