"""Offline structural and privacy checks over exactly the tracked source files."""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_SUFFIXES = {".xlsx", ".xls", ".csv", ".parquet", ".bak", ".pbix", ".docx", ".pptx", ".pfx", ".pem", ".key"}
ALLOWED_BINARY = {"docs/architecture.png", "docs/architecture.pdf"}


def tracked_files():
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True, capture_output=True)
    names = result.stdout.decode("utf-8").split("\0")
    return [ROOT / n for n in names if n]


def main():
    files = tracked_files()
    if not files:
        raise RuntimeError("Stage the release first: git add . (ignored inputs and local settings remain excluded)")
    failures, text_files = [], []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if p.name in ("workspace.json", "deployment.json") or p.suffix in BLOCKED_SUFFIXES or any(part in (".local", ".pbi", "__pycache__") for part in p.parts):
            failures.append(f"{rel}: local configuration or data must not be tracked")
            continue
        if rel in ALLOWED_BINARY:
            continue
        try:
            text = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            failures.append(f"{rel}: unexpected binary file")
            continue
        text_files.append(p)
        try:
            if p.suffix == ".py":
                ast.parse(text, filename=rel)
            elif p.suffix in (".json", ".platform", ".pbir", ".pbip", ".pbism"):
                json.loads(text)
            elif p.suffix in (".yaml", ".yml"):
                yaml.safe_load(text)
        except (SyntaxError, ValueError, yaml.YAMLError) as ex:
            failures.append(f"{rel}: {ex}")
        patterns = {
            "personal filesystem path": r"[A-Za-z]:[/\\]Users[/\\](?!<local-user>)[^/\\\s]+",
            "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY",
            "embedded credential": r"(?i)(?:api_key|password|client_secret)\s*[:=]\s*[\"'][A-Za-z0-9_+/\-=]{16,}[\"']",
            "GitHub token": r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b",
        }
        for reason, pattern in patterns.items():
            if re.search(pattern, text):
                failures.append(f"{rel}: {reason}")
    scanner = ROOT / ".github" / "skills" / "pii-guard" / "scripts" / "scan_for_pii.py"
    for offset in range(0, len(text_files), 80):
        result = subprocess.run([sys.executable, str(scanner), "--fail-on", "medium",
                                 *map(str, text_files[offset:offset+80])], capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            failures.append(result.stdout + result.stderr)
    if failures:
        print("\n".join(failures))
        return 1
    print(f"PASS: {len(files)} tracked files; syntax, configuration exclusion, secret patterns and PII scan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
