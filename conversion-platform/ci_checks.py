"""Pre-merge checks for the conversion platform. Run locally before a pull request; CI runs the same script.

  python conversion-platform/ci_checks.py
      compile    every Python file parses, also with the Fabric runtime's grammar (Python 3.11; set COGS_PY_FABRIC)
      sql-lint   gp-csm-sql-conventions lint over conversion-platform/sql (errors fail)
      spec-lint  conversion-spec lint per client, against the client's target catalog (errors fail)
      artefacts  notebooks have .platform + content; every {{nb_*}} in a pipeline has a notebook; JSON and YAML parse
      pii-scan   pii-guard scan of every file that may be committed (high severity fails)

  python conversion-platform/ci_checks.py --golden-master <de-identified go-live landing> [--database CogsConvCI]
      also replays the take end to end on SQL Server LocalDB (run_local.py all --auto-approve): the answer key must
      pass and the post-load variance must be 0. Needs the de-identified data, so it runs on a developer machine or a
      self-hosted runner, never on a hosted runner (the data doesn't go to GitHub).

Exit code 1 when any check fails. With GITHUB_ACTIONS set, findings are printed as annotations.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent
REPO = PLATFORM.parent
SKILLS = REPO / ".github" / "skills"
CI = bool(os.environ.get("GITHUB_ACTIONS"))
SKIP_PARTS = {"__pycache__", ".git", "preview", ".venv", "node_modules"}
RESTRICTED_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".csv", ".parquet", ".bak"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".abf", ".pbix", ".zip", ".pyc", ".woff", ".woff2"}


def _git_files(*git_args: str) -> list[Path]:
    out = subprocess.run(["git", *git_args, "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    return [REPO / p for p in out.splitlines() if p and (REPO / p).is_file()]


def committable_files() -> list[Path]:
    """The files a commit may contain, by git's own reading of .gitignore. Outside a repository a throwaway git dir
    is used, so the project folder itself never gets a .git folder."""
    try:
        if (REPO / ".git").exists():
            return _git_files()
        with tempfile.TemporaryDirectory(prefix="cogs-ci-git-") as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True)
            return _git_files(f"--git-dir={tmp}/.git", f"--work-tree={REPO}")
    except (OSError, subprocess.CalledProcessError):
        pass
    files = [p for p in REPO.glob("*") if p.is_file() and p.suffix.lower() not in RESTRICTED_SUFFIXES]   # no git: same rules by hand
    for top in (PLATFORM, REPO / ".github"):
        files += [p for p in top.rglob("*") if p.is_file() and not (SKIP_PARTS & set(p.parts))
                  and p.suffix.lower() not in RESTRICTED_SUFFIXES and not p.name.endswith(".pyc")]
    return files


def run(cmd: list[str], **kw) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    return r.returncode, (r.stdout + r.stderr).strip()


PARSE_SNIPPET = ("import ast, json, sys\nbad = []\nfor f in json.load(sys.stdin):\n    try:\n        ast.parse(open(f, encoding='utf-8').read(), f)\n"
                 "    except SyntaxError as e:\n        bad.append(f + ':' + str(e.lineno) + ': ' + e.msg)\nprint(json.dumps(bad))\n")


def _fabric_python() -> list[str] | None:
    """An interpreter with the Fabric notebook runtime's grammar (Python 3.11) or older: newer Pythons accept syntax
    that Fabric rejects (e.g. backslashes in f-string expressions), and ast's feature_version doesn't catch it."""
    if sys.version_info[:2] <= (3, 11):
        return [sys.executable]
    if os.environ.get("COGS_PY_FABRIC"):
        return [os.environ["COGS_PY_FABRIC"]]
    for v in ("3.11", "3.10"):
        try:
            if subprocess.run(["py", f"-{v}", "-c", "pass"], capture_output=True).returncode == 0:
                return ["py", f"-{v}"]
        except OSError:
            break
    return None


def check_compile() -> tuple[bool, str]:
    files = [p for p in list(PLATFORM.rglob("*.py")) + list(SKILLS.rglob("scripts/*.py"))
             if "__pycache__" not in p.parts and "preview" not in p.parts]
    bad = []
    for f in files:
        try:
            ast.parse(f.read_text(encoding="utf-8"), str(f))
        except SyntaxError as e:
            bad.append(f"{f.relative_to(REPO)}:{e.lineno}: {e.msg}")
    old = _fabric_python()
    note = ""
    if old and old != [sys.executable]:
        r = subprocess.run([*old, "-c", PARSE_SNIPPET], input=json.dumps([str(f) for f in files]), capture_output=True, text=True, encoding="utf-8")
        bad += [f"{b} (Fabric runtime grammar)" for b in (json.loads(r.stdout) if r.returncode == 0 else [r.stderr[-300:]])]
        note = f"; also parsed with {' '.join(old)} (Fabric runtime grammar)"
    elif not old:
        note = "; Fabric runtime grammar NOT checked (no Python 3.11 or older found; set COGS_PY_FABRIC)"
    return not bad, f"{len(files)} files parsed{note}" + ("".join(f"\n  {b}" for b in bad))


def check_sql_lint() -> tuple[bool, str]:
    cmd = [sys.executable, str(SKILLS / "gp-csm-sql-conventions" / "scripts" / "lint_tsql.py"), str(PLATFORM / "sql")]
    rc, out = run(cmd + (["--format", "github"] if CI else []))
    return rc == 0, out.splitlines()[-1] if out else ""


def check_spec_lint() -> tuple[bool, str]:
    ok, lines = True, []
    for cdir in sorted(p for p in (PLATFORM / "clients").iterdir() if p.is_dir()):
        cmd = [sys.executable, str(SKILLS / "conversion-spec" / "scripts" / "lint_spec.py"), str(cdir)]
        catalog = PLATFORM / "catalog" / "cogsdale-csm-gp" / f"catalog.{cdir.name}.json"
        if catalog.exists():
            cmd += ["--catalog", str(catalog)]
        rc, out = run(cmd)
        summary = next((ln for ln in out.splitlines() if re.match(r"^\d+ spec file", ln)), out[-200:])
        errors = [ln for ln in out.splitlines() if ln.startswith("E ")]
        lines.append(f"{cdir.name}: {summary}" + "".join(f"\n  {e}" for e in errors[:20]))
        ok &= rc == 0
    return ok, "\n".join(lines)


def check_artefacts() -> tuple[bool, str]:
    import yaml
    problems = []
    notebooks = {p.name.rsplit(".", 1)[0]: p for p in (PLATFORM / "fabric").glob("*.Notebook")}
    for name, folder in notebooks.items():
        for part in (".platform", "notebook-content.py"):
            if not (folder / part).exists():
                problems.append(f"{folder.name}: missing {part}")
    for pipe in (PLATFORM / "fabric").glob("*.DataPipeline"):
        text = (pipe / "pipeline-content.json").read_text(encoding="utf-8")
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            problems.append(f"{pipe.name}: invalid JSON: {e}")
        for ph in sorted(set(re.findall(r"\{\{(nb_[a-z_]+)\}\}", text)) - set(notebooks)):
            problems.append(f"{pipe.name}: {{{{{ph}}}}} has no {ph}.Notebook folder")
    for f in (PLATFORM / "fabric").rglob(".platform"):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{f.relative_to(REPO)}: invalid JSON: {e}")
    for f in (PLATFORM / "clients").rglob("*.yaml"):
        try:
            yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            problems.append(f"{f.relative_to(REPO)}: invalid YAML: {str(e)[:120]}")
    return not problems, f"{len(notebooks)} notebooks, pipelines and specs checked" + "".join(f"\n  {p}" for p in problems)


def check_pii() -> tuple[bool, str]:
    files = committable_files()
    restricted = [f for f in files if f.suffix.lower() in RESTRICTED_SUFFIXES]
    text_files = [f for f in files if f.suffix.lower() not in BINARY_SUFFIXES | RESTRICTED_SUFFIXES]
    scanner = SKILLS / "pii-guard" / "scripts" / "scan_for_pii.py"
    rc_all, findings = 0, []
    for i in range(0, len(text_files), 200):                 # keep command lines short on Windows
        rc, out = run([sys.executable, str(scanner), *map(str, text_files[i:i + 200])] + (["--format", "github"] if CI else []))
        rc_all |= rc
        findings += [ln for ln in out.splitlines() if re.search(r":\d+:\d+: (HIGH|MEDIUM)|^::error", ln)]
    msg = (f"{len(files)} committable files, {len(text_files)} text files scanned; {len(findings)} high or medium finding(s)"
           + "".join(f"\n  {f}" for f in findings[:30]))
    if restricted:
        msg += "".join(f"\n  restricted file type would be committed: {f.relative_to(REPO)}" for f in restricted)
    return rc_all == 0 and not restricted, msg


def check_golden_master(landing: str, database: str) -> tuple[bool, str]:
    work = Path(tempfile.mkdtemp(prefix="cogs-gm-"))
    t0 = time.time()
    rc, out = run([sys.executable, str(PLATFORM / "engine" / "run_local.py"), "all", "--target", "localdb", "--database", database,
                   "--landing", landing, "--work", str(work), "--auto-approve"],
                  env={**os.environ, "PYTHONIOENCODING": "utf-8", "POLARS_SKIP_CPU_CHECK": "1"})
    akc = work / "answer-key-check.json"
    summary = ""
    if akc.exists():
        s = json.loads(akc.read_text(encoding="utf-8")).get("summary") or {}
        summary = f"answer key {s}; "
    variance = [ln.strip() for ln in out.splitlines() if "post-load variance" in ln]
    tail = "\n".join(out.splitlines()[-12:]) if rc else ""
    return rc == 0, f"{summary}{variance[-1] if variance else ''} ({time.time() - t0:.0f}s, work {work})" + (f"\n{tail}" if tail else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=["compile", "sql-lint", "spec-lint", "artefacts", "pii-scan"])
    ap.add_argument("--golden-master", metavar="LANDING", help="de-identified go-live landing folder: replay and check the answer key")
    ap.add_argument("--database", default="CogsConvCI", help="LocalDB database for the golden-master replay")
    a = ap.parse_args(argv)
    checks = {"compile": check_compile, "sql-lint": check_sql_lint, "spec-lint": check_spec_lint, "artefacts": check_artefacts,
              "pii-scan": check_pii}
    failed = []
    for name, fn in checks.items():
        if a.only and name not in a.only:
            continue
        ok, msg = fn()
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {msg}")
        if not ok:
            failed.append(name)
    if a.golden_master:
        ok, msg = check_golden_master(a.golden_master, a.database)
        print(f"[{'PASS' if ok else 'FAIL'}] golden-master: {msg}")
        if not ok:
            failed.append("golden-master")
    print("all checks passed" if not failed else f"FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
