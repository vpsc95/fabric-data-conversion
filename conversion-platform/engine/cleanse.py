"""CLI for deterministic cleansing proposals.

Example:
  python engine/cleanse.py --target localdb --database CogsConvClean --client-dir clients/sample --take go-live
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ENGINE = Path(__file__).resolve().parent
PLATFORM = ENGINE.parent
sys.path.insert(0, str(ENGINE))

from convplat import cleanse, sqlio  # noqa: E402


def connect(args):
    if args.target == "localdb":
        return sqlio.connect_localdb(args.database)
    raise SystemExit("cleanse.py currently supports --target localdb for the prototype")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Generate deterministic cleansing proposals for a take.")
    p.add_argument("--target", choices=["localdb"], required=True)
    p.add_argument("--database", default="CogsConvClean")
    p.add_argument("--client-dir", required=True)
    p.add_argument("--take", required=True)
    p.add_argument("--threshold", type=float, default=0.90)
    p.add_argument("--json", action="store_true", help="print count-only JSON summary")
    args = p.parse_args(argv)

    client, take = cleanse.client_take(args.client_dir, args.take)
    cn = connect(args)
    result = cleanse.run(cn, client, take, args.threshold)
    if args.json:
        print(json.dumps(result, indent=1, default=str))
    else:
        print(f"generated={result['generated']} inserted_pending={result['inserted_pending']}")
        for row in result["summary"]:
            print(f"{row['Module']} {row['RuleId']} {row['Band']} proposals={row['Proposals']} approved={row['Approved'] or 0} rejected={row['Rejected'] or 0} pending={row['Pending'] or 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
