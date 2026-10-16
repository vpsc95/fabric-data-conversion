"""Publish the bundled semantic model and report to a recipient-owned workspace."""
import argparse
import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from azure.identity import AzureCliCredential

from configure import PROFILES, ROOT

FABRIC = "https://api.fabric.microsoft.com/v1"
PBI = "https://api.powerbi.com/v1.0/myorg"


class Api:
    def __init__(self, tenant):
        self.credential = AzureCliCredential(tenant_id=tenant, process_timeout=60)
        self.session = requests.Session()

    def request(self, method, url, **kwargs):
        host = urlparse(url).hostname
        if host not in ("api.fabric.microsoft.com", "api.powerbi.com") or not url.startswith("https://"):
            raise ValueError("Refusing to send a service token outside the Fabric or Power BI API")
        audience = "https://api.fabric.microsoft.com/.default" if host == "api.fabric.microsoft.com" else "https://analysis.windows.net/powerbi/api/.default"
        token = self.credential.get_token(audience).token
        response = self.session.request(method, url, headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json",
            "x-ms-fabric-skill": "powerbi-authoring-cli"}, timeout=120, **kwargs)
        response.raise_for_status()
        return response

    def operation(self, response):
        if response.status_code != 202:
            return response.json() if response.content else {}
        location = response.headers["Location"]
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            time.sleep(min(60, max(1, int(response.headers.get("Retry-After", "5")))))
            response = self.request("GET", location)
            state = response.json()
            if state["status"] == "Succeeded":
                result = self.request("GET", location.rstrip("/") + "/result")
                return result.json() if result.content else {}
            if state["status"] in ("Failed", "Cancelled", "Undefined"):
                raise RuntimeError(f"Fabric operation failed: {state.get('error', state['status'])}")
        raise TimeoutError("Fabric operation did not finish within 30 minutes")

    def items(self, workspace, kind):
        items, url = [], f"{FABRIC}/workspaces/{workspace}/items?type={kind}"
        while url:
            body = self.request("GET", url).json()
            items.extend(body["value"])
            url = body.get("continuationUri")
        return items


def definition_parts(folder, settings, model_id=None):
    values = {k: v for k, v in settings.items() if isinstance(v, str)}
    parts = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name.startswith(".") or any(x.startswith(".") for x in p.relative_to(folder).parts):
            continue
        relative = p.relative_to(folder).as_posix()
        text = p.read_text(encoding="utf-8")
        if relative == "definition.pbir":
            pbir = json.loads(text)
            if not model_id:
                raise ValueError("A deployed semantic model ID is required for report binding")
            pbir["datasetReference"] = {"byConnection": {"connectionString": f"semanticmodelid={model_id}"}}
            text = json.dumps(pbir)
        for k, v in values.items():
            text = text.replace("{{" + k + "}}", v)
        remaining = re.findall(r"\{\{[a-z_]+\}\}", text)
        if remaining:
            raise ValueError(f"Unresolved deployment placeholders in {relative}: {remaining}")
        parts.append({"path": relative, "payload": base64.b64encode(text.encode()).decode(), "payloadType": "InlineBase64"})
    if not parts:
        raise ValueError(f"No definition files in {folder}")
    return parts


def publish(api, settings, kind, collection, name, definition, update):
    matches = [i for i in api.items(settings["workspace_id"], kind) if i["displayName"] == name]
    if len(matches) > 1:
        raise ValueError(f"Multiple {kind} items named {name}; resolve the ambiguity first")
    base = f"{FABRIC}/workspaces/{settings['workspace_id']}/{collection}"
    if matches:
        if not update:
            raise ValueError(f"{name} already exists. Use --update-existing only for your own demo items")
        item_id = matches[0]["id"]
        api.operation(api.request("POST", f"{base}/{item_id}/updateDefinition", json={"definition": definition}))
    else:
        api.operation(api.request("POST", base, json={"displayName": name, "definition": definition}))
        matches = [i for i in api.items(settings["workspace_id"], kind) if i["displayName"] == name]
        if len(matches) != 1:
            raise RuntimeError(f"Created {kind} could not be resolved by its unique name")
        item_id = matches[0]["id"]
    print(f"{kind}: {name} published")
    return item_id


def reframe(api, settings, mid):
    base = f"{PBI}/groups/{settings['workspace_id']}/datasets/{mid}/refreshes"
    api.request("POST", base, json={"notifyOption": "NoNotification"})
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        time.sleep(5)
        values = api.request("GET", base, params={"$top": 1}).json()["value"]
        if not values:
            continue
        status = values[0]["status"]
        if status == "Completed":
            print("Direct Lake model refresh completed")
            return
        if status not in ("Unknown", "NotStarted", "InProgress"):
            raise RuntimeError(f"Model refresh failed: {values[0].get('serviceExceptionJson', status)}")
    raise TimeoutError("Model refresh did not complete within 15 minutes")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile", choices=PROFILES)
    ap.add_argument("--update-existing", action="store_true")
    ap.add_argument("--no-refresh", action="store_true", help="Only for definition validation; data must already exist for a working report")
    args = ap.parse_args()
    config_path = PROFILES[args.profile]
    if not config_path.exists():
        ap.error("Run tools/configure.py first")
    ws = json.loads(config_path.read_text(encoding="utf-8"))
    prefix = "ConversionMVP" if args.profile == "mvp" else "ConversionRun"
    directory = ROOT / ("conversion-mvp" if args.profile == "mvp" else "conversion-platform") / "powerbi"
    api = Api(ws["tenant_id"])
    mid = publish(api, ws, "SemanticModel", "semanticModels", ws["semantic_model"],
                  {"format": "TMDL", "parts": definition_parts(directory / f"{prefix}.SemanticModel", ws)},
                  args.update_existing)
    ws["semantic_model_id"] = mid
    config_path.write_text(json.dumps(ws, indent=2) + "\n", encoding="utf-8")
    if not args.no_refresh:
        reframe(api, ws, mid)
    rid = publish(api, ws, "Report", "reports", ws["report"],
                  {"format": "PBIR", "parts": definition_parts(directory / f"{prefix}.Report", ws, mid)},
                  args.update_existing)
    ws["report_id"] = rid
    config_path.write_text(json.dumps(ws, indent=2) + "\n", encoding="utf-8")
    print(f"Open https://app.powerbi.com/groups/{ws['workspace_id']}/reports/{rid}")


if __name__ == "__main__":
    main()
