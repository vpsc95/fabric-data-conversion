# Reshape component library

These are the "Lego bricks" the reshape engine knows. A reshape spec chooses components and sets their parameters. Each component replaces a manual Excel step that clients currently repeat every take.

Components run in the order they're listed. Every value is read as text: typing happens later with `cast` or in the mapping.

| Component | What it does | Replaces (sample evidence) |
|---|---|---|
| `strip_artifacts` | Drops page headers, separator lines, report titles, repeated column headings and, optionally, blank rows | Header and separator text inside the services, balances and deposit reports |
| `fill_down` | Carries the last non-blank value of key columns down to continuation lines | *"Use Formula to copy in Excel to blank rows"* (ACCT, STDATE) |
| `stitch_pages` | Joins a record that breaks across a page, ignoring the page footer and header in between | Services that continue on the next page |
| `unpivot` | Turns side-by-side repeating groups into rows | DESCRIPTION/DESCRIPTION2 and METER/METER2; SVC1–3/BAL1–3; names across three fields (upcoming client) |
| `derive` | Adds columns from short expressions | `LEFT(DESCRIPTION, 3)` → ServiceCode; `LEFT(ACCT, 2)` → RouteID; RECEIVED+UNBILLED; Flow/100 |
| `filter` | Keeps rows that match a condition. A `reason` is mandatory. | *"Only import where REFDATE is Empty"*; ACCOUNTNUM numeric; first line per Meter_ID |
| `dedupe` | Keeps the first or last row per key | 17,974 account rows → 14,306 customers |
| `split` | Splits one column into several | Compound fields |
| `concat_limited` | Concatenates within a length limit | Driver's licence + state → AlternateID (≤ 15) |
| `cast` | Converts types with explicit formats | Dates as MM/dd/yyyy; balances as text → numeric |
| `rename` / `select` | Tidy the output columns | — |
| `parse_address` | Splits a one-line street address into number, direction, street name, USPS suffix and unit | The SmartyStreets parse that fed the location street-name rule |

Implemented in `conversion-platform/engine/convplat/reshape.py` today: `strip_artifacts`, `fill_down`, `rename`, `select`, `parse_address`. The rest of the logic for sample (unpivot of service slots, derives, filters, dedupe) runs in the gold SQL procedures, ported from the legacy scripts. Column names are sanitized on read: `#` becomes `NUM`, other non-alphanumerics are removed, and a blank header becomes `COL<n>`. So `ACCOUNT #` becomes `ACCOUNTNUM`.

## Parameters and examples

### strip_artifacts
```yaml
- strip_artifacts:
    patterns: ["^-{6,}", "^={6,}", "S E R V", "^DESCRIPTION", "^STATUS", "^PAGE\\s+\\d+"]
    blank_rows: true        # drop rows where every cell is blank
    header_repeats: true    # drop rows identical to the header row
```
Patterns are regular expressions tested against the row's cells joined with a single space.

For printed reports, `keep_when` is usually simpler and safer. A row is data when any listed column matches the pattern. Every other row is an artifact and is classified for the run report as blank, page break, header repeat, separator, title, footer or other. Dropped rows are never lost: they go to `silver_<extract>_artifacts` with their row number and reason.
```yaml
- strip_artifacts:
    keep_when:
      columns: [ACCOUNTNUM, ACCT]
      pattern: '^\d{2}-\d{4}-\d{2}$'
```

### fill_down
```yaml
- fill_down:
    columns: ["ACCOUNT #", "START DATE"]
    as: [ACCT, STDATE]      # optional new names; default is the same names
    reset_on: PAGE_BREAK    # optional column; the fill stops when it changes
    check_against: [ACCT, STDATE]   # optional: compare with helper columns built by hand; mismatches are reported
```
With `check_against`, the platform proves it can retire a manual Excel step. On the sample go-live take there were 0 mismatches over 11,986 service lines and 10,797 balance lines.

### parse_address
```yaml
- parse_address:
    column: SERVICEADDRESS
    prefix: SA_             # adds SA_NUMBER, SA_PREDIR, SA_NAME, SA_SUFFIX, SA_POSTDIR, SA_UNIT
```

### unpivot
```yaml
- unpivot:
    groups:
      - [DESCRIPTION, STATUS, TABLE, METER]
      - [DESCRIPTION2, STATUS2, TABLE2, METER2]
    as: [DESCRIPTION, STATUS, TABLE, METER]
    index_as: ServiceSlot   # 1, 2, ... so the source position is never lost
    drop_empty: true        # drop slots where every column in the group is blank
```
Balances use the same component: `groups: [[SVC1, BAL1], [SVC2, BAL2], [SVC3, BAL3]]`, `as: [SVC, BAL]`.

### derive
```yaml
- derive:
    ServiceCode: "LEFT(DESCRIPTION, 3)"
    RouteID: "LEFT(ACCT, 2)"
    DepositAmount: "RECEIVED + UNBILLED"
    Consumption: "Flow / 100"
    IsLowFlowRegister: "RIGHT(Meter_ID, 1) = '-'"   # compound meter: trailing dash = low-flow register
```
Allowed functions: `LEFT`, `RIGHT`, `SUBSTRING`, `UPPER`, `LOWER`, `TRIM`, `CONCAT`, `COALESCE`, `NULLIF`, `LEN`, `REPLACE` and `xref`, plus the operators `+ - * /` and comparisons. Anything bigger is a new component; propose it in a pull request to this file.

### filter
```yaml
- filter:
    where: "REFDATE = ''"
    reason: "Only deposits not yet refunded are converted (sample deposits template)."
```

### dedupe
```yaml
- dedupe:
    keys: [Meter_ID]
    keep: first
    order_by: [ReadDate]
```

### concat_limited
```yaml
- concat_limited:
    columns: [DL_NUMBER, DL_STATE2]
    sep: ""
    max_length: 15
    as: AlternateID
```
Overflow becomes a **warning** issue (sample: 192 "AlternateID too long") instead of being cut silently.

### cast
```yaml
- cast:
    STDATE: {type: date, format: "MM/dd/yyyy"}
    BAL: {type: number}
```

## Adding a component
1. Find at least two clients (or two files) that need it. One-offs belong in a Dataflow Gen2 "custom brick", not the library.
2. Write the component's spec first: purpose, parameters, an example and edge cases. Then implement it in the engine with tests.
3. Add it to `spec.schema.json` (`reshapeStep`) and to this table in the same pull request.
