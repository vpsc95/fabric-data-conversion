"""SQL plumbing shared by the laptop runner and the Fabric notebooks.

connect_localdb()  SQL Server LocalDB (dev / CI, Mode B rehearsal)
connect_token()    Fabric SQL database (or Azure SQL) with an Entra access token; retries while an
                   auto-paused database resumes
deploy()           run the numbered scripts in sql/ (batches split on GO)
load_table()       replace one take's rows in an slv table (fast_executemany, length-checked)
"""
from __future__ import annotations

import re
import struct
import time
from pathlib import Path

import pyodbc

DRIVER = "ODBC Driver 18 for SQL Server"
GO = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


def connect_localdb(database: str = "CogsConv") -> pyodbc.Connection:
    base = f"Driver={{{DRIVER}}};Server=(localdb)\\MSSQLLocalDB;Trusted_Connection=yes;Encrypt=no"
    with pyodbc.connect(base + ";Database=master", autocommit=True) as m:
        m.execute(f"IF DB_ID(N'{database}') IS NULL CREATE DATABASE [{database}] COLLATE SQL_Latin1_General_CP1_CI_AS")
    return pyodbc.connect(base + f";Database={database}", autocommit=True)


def connect_token(server: str, database: str, token: str, retries: int = 10) -> pyodbc.Connection:
    raw = token.encode("utf-16-le")
    attrs = {1256: struct.pack(f"<I{len(raw)}s", len(raw), raw)}          # SQL_COPT_SS_ACCESS_TOKEN
    server = server.split(",")[0]
    cs = f"Driver={{{DRIVER}}};Server=tcp:{server},1433;Database={database};Encrypt=yes;TrustServerCertificate=no"
    for attempt in range(retries):
        try:
            return pyodbc.connect(cs, attrs_before=attrs, timeout=60, autocommit=True)
        except pyodbc.Error as e:
            if attempt < retries - 1 and ("not currently available" in str(e) or "40613" in str(e) or "timeout" in str(e).lower()):
                time.sleep(15)
                continue
            raise
    raise RuntimeError("unreachable")


def _drain(cur) -> None:
    while True:
        try:
            if not cur.nextset():
                break
        except pyodbc.ProgrammingError:
            break


def run_sql(cn: pyodbc.Connection, sql: str, label: str = "sql") -> None:
    cur = cn.cursor()
    for i, batch in enumerate([b for b in GO.split(sql) if b.strip()], 1):
        try:
            cur.execute(batch)
            _drain(cur)
        except pyodbc.Error as e:
            raise RuntimeError(f"{label} batch {i} failed: {e}\n--- batch start ---\n{batch[:600]}") from e


def deploy(cn: pyodbc.Connection, sql_dir: str | Path) -> list[str]:
    done = []
    for p in sorted(Path(sql_dir).glob("[0-9][0-9]_*.sql")):
        run_sql(cn, p.read_text(encoding="utf-8"), p.name)
        done.append(p.name)
    return done


def table_columns(cn: pyodbc.Connection, table: str) -> dict[str, tuple[str, int]]:
    schema, name = table.split(".")
    rows = cn.cursor().execute(
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION", schema, name).fetchall()
    return {r[0]: (r[1], r[2] or 0) for r in rows}


def load_table(cn: pyodbc.Connection, table: str, data: dict[str, list], take_id: str, batch: int = 10000,
               method: str = "json") -> int:
    """Replace one take's rows in an slv table. data: column -> values (silver names; _take_id/_row are lineage).
    Only the table's columns are loaded; every value is checked against the column width first, so a
    too-narrow column fails loudly instead of truncating.
    method="json" sends each batch as one JSON document and inserts it with OPENJSON (one round trip per
    batch; fast against Fabric SQL database / Azure SQL); "rows" uses pyodbc fast_executemany."""
    cols = table_columns(cn, table)
    if not cols:
        raise RuntimeError(f"{table} does not exist; deploy the SQL first")
    by_upper = {k.upper(): k for k in data}
    mapping = []
    for c, (dtype, width) in cols.items():
        src = "_take_id" if c == "TakeId" else "_row" if c == "SourceRow" else by_upper.get(c.upper())
        if src is None:
            raise RuntimeError(f"{table}.{c} has no matching silver column")
        if width and width > 0:
            longest = max((len(v) for v in data[src] if isinstance(v, str)), default=0)
            if longest > width:
                raise RuntimeError(f"{table}.{c} is {dtype}({width}) but silver has values of length {longest}")
        mapping.append((c, src, dtype, width))
    n = len(next(iter(data.values()))) if data else 0
    rows = [[data[src][i] for _, src, _, _ in mapping] for i in range(n)]
    cur = cn.cursor()
    cur.execute(f"DELETE {table} WHERE TakeId = ?", take_id)
    names = ", ".join(f"[{c}]" for c, _, _, _ in mapping)
    if method == "json":
        import json as _json
        typed = ", ".join(f"[{c}] {t}{'(' + (str(w) if w > 0 else 'max') + ')' if t in ('nvarchar', 'varchar', 'char', 'nchar') else ''} '$[{i}]'"
                          for i, (c, _, t, w) in enumerate(mapping))
        sql = f"INSERT {table} ({names}) SELECT {names} FROM OPENJSON(?) WITH ({typed});"
        for i in range(0, n, batch):
            cur.execute(sql, _json.dumps(rows[i:i + batch], ensure_ascii=False))
    else:
        cur.fast_executemany = True
        sql = f"INSERT {table} ({names}) VALUES ({', '.join('?' * len(mapping))})"
        for i in range(0, n, batch):
            cur.executemany(sql, [tuple(r) for r in rows[i:i + batch]])
    return n


def query(cn: pyodbc.Connection, sql: str, *params) -> list[dict]:
    cur = cn.cursor().execute(sql, *params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def exec_proc(cn: pyodbc.Connection, sql: str, *params) -> None:
    """Run a procedure call and consume every result, so errors raised late in the procedure surface here."""
    cur = cn.cursor()
    cur.execute(sql, *params)
    _drain(cur)


def save_answer_key_check(cn: pyodbc.Connection, client: str, take: str, rows: list[dict]) -> int:
    cur = cn.cursor()
    cur.execute("DELETE run.AnswerKeyCheck WHERE ClientId = ? AND TakeId = ?", client, take)
    for r in rows:
        cur.execute("INSERT run.AnswerKeyCheck (ClientId, TakeId, Module, Metric, Expected, Actual, Status, Reason, ApprovedBy) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", client, take, r["module"], r["metric"], r["expected"][:40], r["actual"][:40],
                    r["status"], r["reason"][:1000], r["approved_by"][:200])
    return len(rows)
