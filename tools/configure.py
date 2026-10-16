"""Validate user-supplied settings and write ignored workspace configuration."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "mvp": ROOT / "conversion-mvp" / "workspace.json",
    "full": ROOT / "conversion-platform" / "fabric" / "workspace.json",
}


def validate(config, profile):
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    ws = {**config[profile], "tenant_id": config["tenant_id"], "foundry": config["foundry"]}
    for key in ("tenant_id", "workspace_id", "lakehouse_id", "sql_database_id"):
        if UUID(ws[key]).int == 0:
            raise ValueError(f"{key} must identify your resource, not an empty GUID")
    for key in ("workspace", "lakehouse", "sql_database", "sql_server", "sql_database_name", "semantic_model", "report"):
        val = ws[key]
        if not isinstance(val, str) or not val.strip() or any(c in val for c in "<>{}\r\n;"):
            raise ValueError(f"Set a valid {key} for {profile}")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", ws["sql_server"]):
        raise ValueError("sql_server must be a hostname without tcp:, port, or connection-string settings")
    foundry = ws["foundry"]
    url = urlparse(foundry["endpoint"])
    if (url.scheme != "https" or not url.hostname or "<" in url.hostname
            or not url.hostname.endswith(".cognitiveservices.azure.com")
            or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("Use the HTTPS Azure OpenAI resource endpoint, not an API key or project URL")
    for key in ("deployment", "region", "api_version"):
        if not foundry.get(key) or any(c in foundry[key] for c in "<>{}\r\n"):
            raise ValueError(f"Set foundry.{key}")
    if "global" in foundry.get("deployment_type", "").lower():
        raise ValueError("This example requires a regional model deployment")
    ws.update({"semantic_model_id": "", "report_id": "",
               "description": "Recipient-owned deployment; no customer data supplied by the repository."})
    return ws


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=ROOT / "deployment.json")
    ap.add_argument("--profile", choices=["mvp", "full", "both"], default="both")
    ap.add_argument("--check", action="store_true", help="Validate without writing")
    args = ap.parse_args()
    if not args.config.is_file():
        ap.error("Copy deployment.example.json to deployment.json and fill in your own resource settings")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    profiles = list(PROFILES) if args.profile == "both" else [args.profile]
    # Validate every selected profile before modifying any file.
    validated = {p: validate(config, p) for p in profiles}
    for p, settings in validated.items():
        if not args.check:
            target = PROFILES[p]
            if target.exists():
                old = json.loads(target.read_text(encoding="utf-8"))
                if old.get("workspace_id") == settings["workspace_id"]:
                    settings.update({k: old.get(k, "") for k in ("semantic_model_id", "report_id")})
            target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        print(f"{p}: configuration {'valid' if args.check else 'written to ignored workspace.json'}")


if __name__ == "__main__":
    main()
