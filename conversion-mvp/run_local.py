"""Run one MVP notebook on this laptop, against the real Fabric SQL database and Foundry (for testing before deploying).

  python run_local.py 1_Reshape_reports take_id=go-live
  python run_local.py 3_AI_triage take_id=take-2

The notebook file runs as is: identifiers are filled in from workspace.json, `notebookutils` is replaced by a small
stand-in that gets tokens from `az login`, and lakehouse paths point to the local de-identified copies.
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

from deploy import HERE, TAKES, credential, fill, placeholders

MARKER = "# PARAMETERS CELL ********************"


class Exit(Exception):
    pass


def stand_in() -> types.ModuleType:
    nu = types.ModuleType("notebookutils")
    cred = credential()
    nu.credentials = types.SimpleNamespace(getToken=lambda audience: cred.get_token(audience.rstrip("/") + "/.default").token)

    def exit_(value=""):
        raise Exit(value)
    nu.notebook = types.SimpleNamespace(exit=exit_)
    return nu


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    name, params = args[0], dict(a.split("=", 1) for a in args[1:])
    take = params.setdefault("take_id", "go-live")
    params.setdefault("take_folder", str(TAKES[take]))
    params.setdefault("log_folder", str(Path(tempfile.gettempdir()) / "cogs-mvp-runs" / take))
    source = fill((HERE / "fabric" / f"{name}.Notebook" / "notebook-content.py").read_text(encoding="utf-8"), placeholders())
    head, tail = source.split(MARKER, 1)
    cell, rest = tail.split("# METADATA", 1)
    overrides = "".join(f"{k} = {v!r}\n" for k, v in params.items())
    code = head + MARKER + cell + overrides + "# METADATA" + rest
    try:
        exec(compile(code, f"{name}.py", "exec"), {"notebookutils": stand_in(), "__name__": "__main__"})
    except Exit as done:
        print(f"\n[{name}] exit value: {done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
