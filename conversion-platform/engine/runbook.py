"""CLI for the conversion runbook prototype executor."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
PLATFORM = ENGINE.parent
sys.path.insert(0, str(ENGINE))

from convplat import runbook, sqlio  # noqa: E402


def connect(args):
    if args.target != "localdb":
        raise SystemExit("runbook.py currently supports --target localdb for the local prototype")
    return sqlio.connect_localdb(args.database)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=["localdb"], default="localdb")
    ap.add_argument("--database", default="CogsConvReport")
    ap.add_argument("--client-dir", default=str(PLATFORM / "clients" / "sample"))
    ap.add_argument("--take", default="go-live")
    args = ap.parse_args(argv)
    cn = connect(args)
    runbook.ensure_schema(cn, PLATFORM)
    seeded = runbook.seed_steps(cn, args.client_dir)
    counts = runbook.execute(cn, args.client_dir, args.take)
    print(json.dumps({"seeded_steps": seeded, "run": counts}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
