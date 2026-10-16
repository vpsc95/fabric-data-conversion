"""Run the metadata-driven CSM loader against a local shadow CSM emulator.

Example:
  python engine/load_csm.py --target localdb --database CogsConvLoad --client sample --take go-live --fresh
  python engine/load_csm.py --target localdb --database CogsConvLoad --client sample --take go-live --fresh --all-fast
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
from convplat import sqlio  # noqa: E402


def connect(args):
    if args.target != "localdb":
        raise SystemExit("load_csm.py prototype supports --target localdb only; do not use Fabric for this shadow loader.")
    return sqlio.connect_localdb(args.database)


def ensure_prepared(cn, client: str, take: str) -> None:
    rows = sqlio.query(cn, "SELECT COUNT(*) AS n FROM load.RowStatus WHERE ClientId = ? AND TakeId = ?", client, take)
    if not rows or rows[0]["n"] == 0:
        sqlio.exec_proc(cn, "EXEC load.usp_PrepareTake ?, ?", client, take)


def print_recon(cn, client: str, take: str) -> None:
    rows = sqlio.query(
        cn,
        "SELECT Module, ModuleName, ExpectedToLoad, Loaded, Failed, EmulatorRows, Variance, "
        "ControlName, GoldAmount, EmulatorAmount, AmountVariance "
        "FROM recon.v_PostLoad WHERE ClientId = ? AND TakeId = ? ORDER BY Module, ControlName",
        client,
        take,
    )
    print("post-load reconciliation")
    for r in rows:
        if r["ControlName"]:
            print(
                f"  {r['Module']:8} {r['ControlName']:12} "
                f"gold={r['GoldAmount']} emulator={r['EmulatorAmount']} variance={r['AmountVariance']}"
            )
        else:
            print(
                f"  {r['Module']:8} expected={r['ExpectedToLoad']:>7} loaded={r['Loaded']:>7} "
                f"failed={r['Failed']:>5} emulator={r['EmulatorRows']:>7} variance={r['Variance']:>5}"
            )


def modules(cn, requested: str | None) -> list[str]:
    if requested:
        return [requested]
    rows = sqlio.query(cn, "SELECT Module FROM load.ProcMap ORDER BY LoadOrder")
    return [r["Module"] for r in rows]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=["localdb"], default="localdb")
    ap.add_argument("--database", required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--take", required=True)
    ap.add_argument("--module")
    ap.add_argument("--max-rows", type=int)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--all-fast", action="store_true", help="Opt in to shadow-only set-based shortcuts for all modules; default is row-by-row except reads.")
    args = ap.parse_args(argv)

    cn = connect(args)
    if args.fresh:
        t0 = time.time()
        sqlio.exec_proc(cn, "EXEC load.usp_PrepareTake ?, ?", args.client, args.take)
        print(f"prepare {time.time() - t0:.1f}s")
    else:
        ensure_prepared(cn, args.client, args.take)

    for mod in modules(cn, args.module):
        t0 = time.time()
        mode = "fast" if args.all_fast else "row"
        sqlio.exec_proc(cn, "EXEC load.usp_LoadModule ?, ?, ?, ?, ?", args.client, args.take, mod, args.max_rows, mode)
        elapsed = time.time() - t0
        row = sqlio.query(
            cn,
            "SELECT SUM(CASE WHEN Status = 'loaded' THEN 1 ELSE 0 END) AS Loaded, "
            "SUM(CASE WHEN Status = 'failed' THEN 1 ELSE 0 END) AS Failed, "
            "SUM(CASE WHEN Status = 'pending' THEN 1 ELSE 0 END) AS Pending "
            "FROM load.RowStatus WHERE ClientId = ? AND TakeId = ? AND Module = ?",
            args.client,
            args.take,
            mod,
        )[0]
        print(f"{mod:8} {elapsed:7.1f}s loaded={row['Loaded']} failed={row['Failed']} pending={row['Pending']}")

    print_recon(cn, args.client, args.take)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
