"""CLI for deterministic DOCX/HTML/PDF data integrity reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
PLATFORM = ENGINE.parent
sys.path.insert(0, str(ENGINE))

from convplat import integrity_report, sqlio  # noqa: E402


def connect(args):
    if args.target != "localdb":
        raise SystemExit("integrity_report.py currently supports --target localdb for the local prototype")
    return sqlio.connect_localdb(args.database)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=["localdb"], default="localdb")
    ap.add_argument("--database", default="CogsConvReport")
    ap.add_argument("--client-dir", default=str(PLATFORM / "clients" / "sample"))
    ap.add_argument("--take", default="go-live")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    cn = connect(args)
    res = integrity_report.generate(cn, args.client_dir, args.take, args.work, args.out)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
