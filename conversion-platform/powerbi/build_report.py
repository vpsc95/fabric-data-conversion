"""Build the Conversion Run report (PBIR) from the approved design contract.

  python build_report.py

Reads the `Design Brief:` YAML in _brief/report-spec.md (the approved, canonical contract) and the model's
TMDL (to tell measures from columns), then writes ConversionRun.Report: the custom theme and its registration,
the live binding to the deployed model, and the four pages with their visuals. Deterministic: page, visual,
filter and theme names derive from their content, so a rebuild with no changes writes identical files.

Afterwards: powerbi-report-author validate ConversionRun.Report, then preview and review screenshots.

Implementation choices where the contract leaves room (all within the powerbi-report-cli authoring rules):
- Module-level tables that mix dimensions and measures are matrices (pivotTable); record-level lists are
  tables (tableEx) of columns only.
- KPI cards carry their context line as a measure-bound title (documented data-bound title.text); a card
  referenceLabel bound to a measure rendered blank in the service preview.
- Status cards colour their value text with a colour measure (value.fontColor), next to a text status.
- The footer freshness card shows one text measure (Take[Freshness]) so it fits the 64 px footer row.
- Tables with long text pin every column width (COLUMN_WIDTHS; one flexible column takes the rest) and wrap,
  so nothing hides off to the right.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPORT = HERE / "ConversionRun.Report"
TABLES = HERE / "ConversionRun.SemanticModel" / "definition" / "tables"
SPEC = HERE / "_brief" / "report-spec.md"
WS = json.loads((HERE.parent / "fabric" / "workspace.json").read_text(encoding="utf-8"))
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json"
THEME_BASE = HERE / "theme-base.json"
THEME_NAME = "CogsdaleConversion"

INK, TEXT, MUTED, LINE, PAGE, WHITE = "#0F172A", "#334155", "#475569", "#E2E8F0", "#F1F5F9", "#FFFFFF"
NEUTRAL_ACCENT = "#475569"

CARD_LABELS = {
    "kpi_received": "Records received", "kpi_loaded": "Records loaded", "kpi_failed": "Records failed",
    "kpi_load_pct": "Load %", "kpi_actionable": "Actionable failures", "kpi_answer_key": "Go-live integrity report",
    "kpi_to_fix": "Records to fix", "kpi_client": "Client fixes", "kpi_cogsdale": "Cogsdale fixes",
    "kpi_agent": "Agent agrees with the rules", "card_pass": "Checks passed", "card_result": "Go-live outcome",
    "card_allowed": "Allowed (explained)", "card_reviewed": "Reviewed (not in key)", "card_new": "New (to review)", "card_failed": "Failed",
    "tile_steps": "SQL steps failed", "tile_pii": "Calls blocked by the PII gate", "tile_reshape": "Fill-down mismatches",
    "tile_tokens": "AI input tokens",
}
SLICER_HEADERS = {"take_slicer": "Take", "module_slicer": "Module", "owner_slicer": "Owner", "status_slicer": "Check status"}
DISPLAY_NAMES = {"Module Name": "Module", "Group Records": "Records", "Rows Affected": "Rows", "Seconds": "Seconds",
                 "Input Token Count": "Input tokens", "Output Token Count": "Output tokens", "Latency Ms": "Latency (ms)",
                 "Metric Label": "Metric", "Approved By": "Approved by", "Agent vs Rules": "Agent vs rules",
                 "Records Loaded": "Loaded", "Expected Failures": "Expected by design", "Actionable Failures": "Actionable",
                 "Records Received": "Received", "Records Failed": "Failed",
                 "Expected Issue Records": "Expected by design", "Actionable Issue Records": "Actionable",
                 "Go-live Value": "Go-live", "This Take Value": "This take", "Rows Kept": "Data rows kept",
                 "Artifacts Removed": "Layout rows removed", "Records to Fix": "Records to fix", "Step Seconds": "Seconds"}
# Pinned table column widths (page px), so long text wraps inside the visual instead of scrolling sideways.
# None takes what is left of the visual's width. Pin every column: in fixed-width mode an unpinned column gets 90 px.
COLUMN_WIDTHS = {
    "triage_table": {"Triage[Group]": None, "Triage[Records]": 60, "Triage[Severity]": 64, "Triage[Agent Label]": 76,
                     "Triage[Agent vs Rules]": 72, "Triage[Final Owner]": 64, "Triage[Final Category]": 136,
                     "Triage[Decision Status]": 68, "Triage[Confidence]": 84, "Triage[Group Key]": 132},
    "fix_list": {"'Fix List'[Account]": 80, "'Fix List'[Title]": 200, "'Fix List'[Owner]": 56, "'Fix List'[Severity]": 64,
                 "'Fix List'[Client Message]": None},
    "answer_key_queue": {"'Answer Key'[Status]": 88, "Module[Module Name]": 152, "'Answer Key'[Metric Label]": 256,
                         "'Answer Key'[Expected]": 80, "'Answer Key'[Actual]": 80, "'Answer Key'[Difference]": 88,
                         "'Answer Key'[Reason]": None, "'Answer Key'[Approved By]": 232},
    "ai_calls_table": {"'AI Calls'[Call Id]": 52, "'AI Calls'[Agent]": 52, "'AI Calls'[Deployment]": 92, "'AI Calls'[Region]": 84,
                       "'AI Calls'[PII Check]": 68, "'AI Calls'[Status]": 76, "'AI Calls'[Items Sent]": 64,
                       "'AI Calls'[Input Token Count]": 72, "'AI Calls'[Output Token Count]": 76, "'AI Calls'[Latency Ms]": 76,
                       "'AI Calls'[Created At]": None},
}
TABLE_CHROME = 44   # 2 x 8 px padding, the vertical scrollbar and borders


# ---------------------------------------------------------------- model inventory and expressions
def model_inventory() -> dict[tuple[str, str], str]:
    kinds = {}
    for f in TABLES.glob("*.tmdl"):
        text = f.read_text(encoding="utf-8")
        table = re.search(r"^table (.+)$", text, re.M).group(1).strip().strip("'")
        for kind, name in re.findall(r"^\t(measure|column) ('[^']+'|[^ =\n]+)", text, re.M):
            kinds[(table, name.strip("'"))] = "Measure" if kind == "measure" else "Column"
    return kinds


KINDS = model_inventory()


def ref(s: str) -> tuple[str, str]:
    m = re.fullmatch(r"'?([^'\[]+)'?\[(.+)\]", s.strip())
    if not m or (m.group(1), m.group(2)) not in KINDS:
        raise SystemExit(f"field {s!r} is not in the model")
    return m.group(1), m.group(2)


def expr(s: str, source: str | None = None) -> dict:
    table, prop = ref(s)
    src = {"Source": source} if source else {"Entity": table}
    return {KINDS[(table, prop)]: {"Expression": {"SourceRef": src}, "Property": prop}}


def proj(s: str, display: str | None = None) -> dict:
    table, prop = ref(s)
    p = {"field": expr(s), "queryRef": f"{table}.{prop}", "nativeQueryRef": prop}
    if display or prop in DISPLAY_NAMES:
        p["displayName"] = display or DISPLAY_NAMES[prop]
    return p


def query_ref(s: str) -> str:
    return "{}.{}".format(*ref(s))


def lit(v) -> dict:
    if isinstance(v, bool):
        v = "true" if v else "false"
    elif isinstance(v, (int, float)):
        v = f"{v}D"
    return {"expr": {"Literal": {"Value": v}}}


def text(s: str) -> dict:
    return lit("'" + s.replace("'", "''") + "'")


def integer(n: int) -> dict:
    return lit(f"{n}L")


def color(hex_: str) -> dict:
    return {"solid": {"color": lit(f"'{hex_}'")}}


def color_measure(s: str) -> dict:
    return {"solid": {"color": {"expr": expr(s)}}}


def hexid(*parts: str, n: int = 20) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:n]


# ---------------------------------------------------------------- geometry
def region_box(canvas: dict, grid: dict, r: list[int]) -> tuple[int, int, int, int]:
    W, H, M, G = canvas["width"], canvas["height"], canvas["margin"], canvas["gutter"]
    cw = (W - 2 * M - (grid["columns"] - 1) * G) / grid["columns"]
    rh = (H - 2 * M - (grid["rows"] - 1) * G) / grid["rows"]
    snap = lambda v: int(round(v / canvas["snap"]) * canvas["snap"])
    c1, r1, c2, r2 = r
    x0, x1 = snap(M + (c1 - 1) * (cw + G)), snap(M + (c2 - 1) * (cw + G) - G)
    y0, y1 = snap(M + (r1 - 1) * (rh + G)), snap(M + (r2 - 1) * (rh + G) - G)
    return x0, y0, x1 - x0, y1 - y0


def slot_box(box, slot: int | None, of: int | None, gap: int = 16):
    x, y, w, h = box
    if not slot:
        return box
    snap = lambda v: int(round(v / 8) * 8)
    if w >= h:
        sw = (w - (of - 1) * gap) / of
        x0, x1 = snap(x + (slot - 1) * (sw + gap)), snap(x + (slot - 1) * (sw + gap) + sw)
        return x0, y, x1 - x0, h
    sh = (h - (of - 1) * gap) / of
    y0, y1 = snap(y + (slot - 1) * (sh + gap)), snap(y + (slot - 1) * (sh + gap) + sh)
    return x, y0, w, y1 - y0


def card_height(canvas_h: int, reference_line: bool) -> int:
    value = min(28, max(12, math.floor(canvas_h * 0.028)))
    label = min(14, max(8, math.floor(value * 0.55)))
    content = 2 * 8 + 2 * 8 + 2 + math.ceil(value * 1.5) + math.ceil(max(label, 12) * 1.5) + (16 if reference_line else 0)
    return int(math.ceil(content / 8) * 8)


# ---------------------------------------------------------------- shared formatting
def vco(alt: str, title: str | None = None, frame: bool = True, header: bool = False, pad: int = 8,
        title_measure: str | None = None) -> dict:
    v = {
        "background": [{"properties": {"show": lit(frame), **({"color": color(WHITE), "transparency": lit(0)} if frame else {})}}],
        "border": [{"properties": {"show": lit(frame), **({"color": color(LINE), "radius": lit(8)} if frame else {})}}],
        "padding": [{"properties": {k: lit(pad) for k in ("top", "bottom", "left", "right")}}],
        "visualHeader": [{"properties": {"show": lit(header)}}],
        "general": [{"properties": {"altText": text(alt)}}],
    }
    if title:
        v["title"] = [{"properties": {"show": lit(True), "text": text(title), "fontSize": lit(12), "bold": lit(True),
                                      "fontColor": color(INK)}}]
        v["subTitle"] = [{"properties": {"show": lit(False)}}]
    elif title_measure:                                         # documented data-bound title: the card's context line
        v["title"] = [{"properties": {"show": lit(True), "text": {"expr": expr(title_measure)}, "fontSize": lit(10),
                                      "bold": lit(False), "fontColor": color(MUTED)}}]
        v["subTitle"] = [{"properties": {"show": lit(False)}}]
    else:
        v["title"] = [{"properties": {"show": lit(False)}}]
    return v


def container(name: str, box, order: int, visual: dict, filters: list | None = None) -> dict:
    x, y, w, h = box
    c = {"$schema": VC_SCHEMA, "name": name,
         "position": {"x": x, "y": y, "z": order * 1000, "height": h, "width": w, "tabOrder": order * 1000},
         "visual": visual}
    if filters:
        c["filterConfig"] = {"filters": filters}
    return c


def sort_def(*fields: tuple[str, str]) -> dict:
    return {"sort": [{"field": expr(f), "direction": d} for f, d in fields], "isDefaultSort": False}


# ---------------------------------------------------------------- filters
def topn_filter(name: str, category: str, rank_column: str, n: int) -> dict:
    table, prop = ref(category)
    _, rank_prop = ref(rank_column)
    col = lambda p: {"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": p}}
    return {"name": "Filter" + hexid("filter", name, n=24), "field": expr(category), "type": "TopN",
            "filter": {"Version": 2,
                       "From": [{"Name": "subquery", "Type": 2, "Expression": {"Subquery": {"Query": {
                           "Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
                           "Select": [{**col(prop), "Name": "field"}],
                           "OrderBy": [{"Direction": 2, "Expression": {"Aggregation": {"Expression": col(rank_prop), "Function": 0}}}],
                           "Top": n}}}},
                                {"Name": "t", "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [col(prop)], "Table": {"SourceRef": {"Source": "subquery"}}}}}]},
            "howCreated": "User"}


def starts_with_filter(name: str, column: str, prefix: str) -> dict:
    table, prop = ref(column)
    return {"name": "Filter" + hexid("filter", name, n=24), "field": expr(column), "type": "Advanced",
            "filter": {"Version": 2, "From": [{"Name": "a", "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"StartsWith": {"Left": {"Column": {"Expression": {"SourceRef": {"Source": "a"}}, "Property": prop}},
                                                               "Right": {"Literal": {"Value": f"'{prefix}'"}}}}}]},
            "howCreated": "User"}


def in_filter(name: str, column: str, values: list[str]) -> dict:
    table, prop = ref(column)
    return {"name": "Filter" + hexid("filter", name, n=24), "field": expr(column), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "s", "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": prop}}],
                                                       "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}]},
            "howCreated": "User"}


# ---------------------------------------------------------------- visuals
def textbox(value: str, alt: str) -> dict:
    return {"visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": value, "textStyle": {
                "fontFamily": "Segoe UI Semibold", "fontSize": "24px", "color": INK}}], "horizontalTextAlignment": "left"}]}}]},
            "visualContainerObjects": vco(alt, frame=False, pad=0)}


def slicer(field: str, header: str, single: bool, sync: str | None, alt: str) -> dict:
    objects = {"data": [{"properties": {"mode": text("Dropdown")}}],
               "header": [{"properties": {"show": lit(True), "text": text(header)}}]}
    if single:
        objects["selection"] = [{"properties": {"singleSelect": lit(True), "strictSingleSelect": lit(True)}}]
    v = {"visualType": "slicer", "query": {"queryState": {"Values": {"projections": [proj(field)]}}},
         "objects": objects, "visualContainerObjects": vco(alt)}
    if sync:
        v["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
    return v


def card(value: str, label: str | None, alt: str, accent: str | None, reference: str | None = None,
         value_color: str | None = None, value_size: int = 28, label_size: int = 14, frame: bool = True) -> dict:
    sel = {"id": "default"}
    objects = {
        "value": [{"properties": {"fontSize": lit(value_size), "bold": lit(value_size >= 20),
                                  "fontColor": color_measure(value_color) if value_color else color(INK if value_size >= 20 else MUTED)},
                   "selector": sel}],
        "label": [{"properties": {"show": lit(bool(label)), **({"text": text(label), "fontSize": lit(label_size), "fontColor": color(MUTED)} if label else {})},
                   "selector": sel}],
        "padding": [{"properties": {"paddingSelection": text("Custom"), "paddingIndividual": lit(True), "topMargin": integer(8),
                                    "bottomMargin": integer(8), "leftMargin": integer(12 if accent else 8), "rightMargin": integer(8)},
                     "selector": sel}],
        "layout": [{"properties": {"paddingUniform": integer(0)}, "selector": sel}],
        "outline": [{"properties": {"show": lit(False)}, "selector": sel}],
    }
    if accent:
        objects["accentBar"] = [{"properties": {"show": lit(True), "position": text("Left"), "width": lit(4), "color": color(accent)},
                                 "selector": sel}]
    objects["value"][0]["properties"]["labelDisplayUnits"] = lit(1)      # exact numbers: a reconciliation report must not round
    # The context line (go-live figure, share, what's pending) is a measure-bound title: a card referenceLabel bound to a
    # measure left the card blank in the service preview, while data-bound title.text is documented.
    return {"visualType": "cardVisual", "query": {"queryState": {"Data": {"projections": [proj(value)]}}},
            "objects": objects, "visualContainerObjects": vco(alt, frame=frame, title_measure=reference)}


def bar(kind: str, category: str, ys: list[str], title: str, alt: str, colors: dict[str, str] | None = None,
        series: str | None = None, series_colors: dict[str, str] | None = None, tooltips: list[str] | None = None,
        sort: list[tuple[str, str]] | None = None, legend: bool = True, single_color: str | None = None) -> dict:
    qs = {"Category": {"projections": [{**proj(category), "active": True}]}, "Y": {"projections": [proj(y) for y in ys]}}
    if series:
        qs["Series"] = {"projections": [proj(series)]}
    if tooltips:
        qs["Tooltips"] = {"projections": [proj(t) for t in tooltips]}
    if single_color:
        data_point = [{"properties": {"defaultColor": color(single_color)}}]
    elif series_colors:
        data_point = [{"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
            "ComparisonKind": 0, "Left": expr(series), "Right": {"Literal": {"Value": f"'{v}'"}}}}}]}}
                      for v, c in series_colors.items()]
    else:
        data_point = [{"properties": {"fill": color(colors[y])}, "selector": {"metadata": query_ref(y)}} for y in ys]
    stacked = kind == "hundredPercentStackedBarChart" or (kind in ("barChart", "columnChart") and (len(ys) > 1 or bool(series)))
    objects = {
        "dataPoint": data_point,
        # stacked segments carry their labels inside the bar, so white; single bars put them outside, so slate
        "labels": [{"properties": {"show": lit(True), "fontSize": lit(9), "color": color(WHITE if stacked else TEXT)}}],
        "categoryAxis": [{"properties": {"show": lit(True), "fontSize": lit(10), "labelColor": color(TEXT), "showAxisTitle": lit(False),
                                         "innerPadding": lit(10), "preferredCategoryWidth": lit(8)}}],
        "valueAxis": [{"properties": {"show": lit(False)}}],
        "legend": [{"properties": {"show": lit(legend), **({"position": text("Top"), "fontSize": lit(10), "labelColor": color(TEXT)} if legend else {})}}],
    }
    q = {"queryState": qs}
    if sort:
        q["sortDefinition"] = sort_def(*sort)
    return {"visualType": kind, "query": q, "objects": objects, "visualContainerObjects": vco(alt, title=title, header=True)}


def table(fields: list[str], title: str, alt: str, sort: list[tuple[str, str]] | None, wrap: bool = False,
          widths: dict[str, int] | None = None) -> dict:
    q = {"queryState": {"Values": {"projections": [proj(f) for f in fields]}}}
    if sort:
        q["sortDefinition"] = sort_def(*sort)
    sizing = {"columnAdjustment": text("fixedWidth"), "autoSizeColumnWidth": lit(False)} if widths else \
             {"columnAdjustment": text("growToFit"), "autoSizeColumnWidth": lit(True)}
    objects = {
        "columnHeaders": [{"properties": {**sizing, "fontSize": lit(10),
                                          "bold": lit(True), "fontColor": color(INK), "backColor": color(PAGE), "wordWrap": lit(True)}}],
        "values": [{"properties": {"fontSize": lit(10), "fontColorPrimary": color(TEXT), "fontColorSecondary": color(TEXT),
                                   "backColorPrimary": color(WHITE), "backColorSecondary": color("#F8FAFC"), "wordWrap": lit(wrap)}}],
    }
    if widths:
        objects["columnWidth"] = [{"properties": {"value": lit(int(widths[f]))}, "selector": {"metadata": query_ref(f)}} for f in fields]
    return {"visualType": "tableEx", "query": q, "objects": objects, "visualContainerObjects": no_preset(vco(alt, title=title, header=True))}


def pinned_widths(placement_id: str, fields: list[str], box_width: int) -> dict[str, int] | None:
    spec = COLUMN_WIDTHS.get(placement_id)
    if not spec:
        return None
    if set(spec) != set(fields):
        raise SystemExit(f"{placement_id}: COLUMN_WIDTHS must pin exactly the table's fields "
                         f"(missing {sorted(set(fields) - set(spec))}, extra {sorted(set(spec) - set(fields))})")
    fill = box_width - TABLE_CHROME - sum(w for w in spec.values() if w)
    if fill < 120:
        raise SystemExit(f"{placement_id}: pinned widths leave {fill} px for the flexible column")
    return {f: (w or fill) for f, w in spec.items()}


def no_preset(v: dict) -> dict:
    # style preset None: the object-level formatting is the only table styling. (Faint table text in headless
    # preview captures is capture timing, not styling: the capture fires on the rendered event while tables are
    # still fading in; a settled capture shows the exact colours.)
    v["stylePreset"] = [{"properties": {"name": text("None")}}]
    return v


def matrix(rows: str, values: list[str], title: str, alt: str) -> dict:
    q = {"queryState": {"Rows": {"projections": [proj(rows)]}, "Values": {"projections": [proj(v) for v in values]}}}
    objects = {
        "columnHeaders": [{"properties": {"columnAdjustment": text("growToFit"), "autoSizeColumnWidth": lit(True), "fontSize": lit(10),
                                          "bold": lit(True), "fontColor": color(INK), "backColor": color(PAGE), "wordWrap": lit(True)}}],
        "values": [{"properties": {"fontSize": lit(11), "fontColorPrimary": color(TEXT), "fontColorSecondary": color(TEXT),
                                   "backColorPrimary": color(WHITE), "backColorSecondary": color("#F8FAFC")}}],
        "rowHeaders": [{"properties": {"fontColor": color(TEXT), "fontSize": lit(11)}}],
        "rowTotal": [{"properties": {"fontColor": color(INK), "bold": lit(True)}}],
    }
    return {"visualType": "pivotTable", "query": q, "objects": objects, "visualContainerObjects": no_preset(vco(alt, title=title, header=True))}


def page_navigator(alt: str) -> dict:
    def states(obj_static: dict, default: dict, selected: dict) -> list:
        return [{"properties": obj_static}, {"properties": default, "selector": {"id": "default"}},
                {"properties": selected, "selector": {"id": "selected"}}]
    objects = {
        "fill": states({"show": lit(True)}, {"fillColor": color(WHITE), "transparency": lit(0)}, {"fillColor": color("#0F766E"), "transparency": lit(0)}),
        "text": states({"show": lit(True)}, {"fontColor": color(TEXT), "fontSize": lit(11)}, {"fontColor": color(WHITE), "bold": lit(True)}),
        "outline": states({"show": lit(True)}, {"lineColor": color("#CBD5E1")}, {"lineColor": color("#0F766E")}),
    }
    return {"visualType": "pageNavigator", "objects": objects, "visualContainerObjects": vco(alt, frame=False, pad=0)}


# ---------------------------------------------------------------- build
def theme() -> tuple[str, dict]:
    t = json.loads(THEME_BASE.read_text(encoding="utf-8"))
    t.update({"dataColors": ["#0F766E", "#64748B", "#B45309", "#2563EB", "#DC2626", "#0E7490", "#4F46E5", "#475569"],
              "good": "#0F766E", "neutral": "#B45309", "bad": "#DC2626", "maximum": "#0F766E", "center": "#B45309", "minimum": "#CCFBF1"})
    for cls, size, face, col in (("callout", 28, "Segoe UI Semibold", INK), ("title", 12, "Segoe UI Semibold", INK),
                                 ("header", 11, "Segoe UI Semibold", TEXT), ("label", 10, "Segoe UI", TEXT)):
        t["textClasses"][cls] = {"fontSize": size, "fontFace": face, "color": col}
    star = t["visualStyles"]["*"]["*"]
    star["border"] = [{"show": True, "color": {"solid": {"color": LINE}}, "radius": 8}]
    star["background"] = [{"show": True, "color": {"solid": {"color": WHITE}}, "transparency": 0}]
    star["visualHeader"] = [{"show": False}]
    for typ in ("tableEx", "pivotTable"):
        t["visualStyles"][typ]["*"]["columnHeaders"][0].update({"backColor": {"solid": {"color": PAGE}}, "fontColor": {"solid": {"color": INK}}})
        t["visualStyles"][typ]["*"]["values"][0].update({"backColorSecondary": {"solid": {"color": "#F8FAFC"}},
                                                         "fontColorPrimary": {"solid": {"color": TEXT}}, "fontColorSecondary": {"solid": {"color": TEXT}}})
    # container border, spacing and padding for cards are set per visual (they don't validate as cardVisual theme keys)
    for key in ("border", "spacing", "padding"):
        t["visualStyles"]["cardVisual"]["*"].pop(key, None)
    for typ in ("slicer",):
        for obj in ("header", "items", "date"):
            for entry in t["visualStyles"][typ]["*"][obj]:
                entry["fontColor"] = {"solid": {"color": TEXT}}
    body = json.dumps(t, sort_keys=True)
    name = f"{THEME_NAME}-{hashlib.sha1(body.encode()).hexdigest()[:8]}.json"
    t["name"] = name
    return name, t


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def remove_tree(path: Path, attempts: int = 10) -> None:
    # OneDrive can hold a handle on a folder for a moment after its files change; retry instead of failing
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(3)


def build() -> dict:
    spec = yaml.safe_load(re.search(r"```yaml\n(.*?)```", SPEC.read_text(encoding="utf-8"), re.S).group(1))["Design Brief"]
    cmap = {c["measure"]: c["color"] for c in spec["color_map"]}
    sem = spec["semantic_colors"]
    defn = REPORT / "definition"
    page_schema = json.loads(next((defn / "pages").glob("*/page.json")).read_text(encoding="utf-8"))["$schema"] \
        if any((defn / "pages").glob("*/page.json")) else \
        "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
    pages_meta = json.loads((defn / "pages" / "pages.json").read_text(encoding="utf-8"))
    keep = {}                                                   # page id -> visual ids written this run

    counts, order_ids = {}, []
    for page in spec["pages"]:
        lc, display = page["layout_contract"], page["display_name"]
        pid = hexid("page", display)
        order_ids.append(pid)
        canvas, grid = lc["canvas"], lc["grid"]
        vids, interactions = {}, []
        for order, pl in enumerate(lc["placements"], 1):
            box = slot_box(region_box(canvas, grid, grid["regions"][pl["region"]]), pl.get("slot"), pl.get("of"))
            kind, fb, vid = pl["kind"], pl.get("field_bindings"), hexid("visual", display, pl["id"])
            vids[pl["id"]] = vid
            alt = (pl.get("title") or pl.get("text") or CARD_LABELS.get(pl["id"]) or pl.get("label") or pl["id"]) + ". " + (pl.get("purpose") or "")
            filters = []
            if kind == "textbox":
                visual = textbox(pl["text"], alt.strip())
            elif kind == "slicer":
                x, y, w, _ = box
                box = (x, y, w, 80)                                   # dropdown: 60 + 8/8 padding, snapped
                visual = slicer(fb, SLICER_HEADERS[pl["id"]], bool(pl.get("single_select")), pl.get("sync_group"),
                                f"{SLICER_HEADERS[pl['id']]} slicer")
            elif kind == "pageNavigator":
                visual = page_navigator("Page tabs: Processed items, Exceptions and triage, Reconciliation, Run audit")
            elif kind == "cardVisual" and pl["id"] == "freshness_card":
                visual = card("Take[Freshness]", None, "When this take was last published and where the report reads from",
                              accent=None, value_size=11, frame=False)
            elif kind == "cardVisual":
                strategy = pl.get("color_strategy")
                accent = cmap.get(fb["value"]) if strategy == "measure_match" else NEUTRAL_ACCENT
                label = CARD_LABELS.get(pl["id"]) or pl.get("label")
                x, y, w, _ = box
                box = (x, y, w, card_height(canvas["height"], True))   # one height per strip: every card reserves the reference line
                visual = card(fb["value"], label, alt, accent, fb.get("reference_label"), fb.get("accent_color"))
            elif kind in ("hundredPercentStackedBarChart", "barChart", "clusteredBarChart", "columnChart"):
                ys = fb["Y"] if isinstance(fb["Y"], list) else [fb["Y"]]
                legend_field = fb.get("Legend")
                series_colors = None
                if legend_field:
                    series_colors = sem["owner"] if "Owner" in legend_field else sem["status"]
                sort = None
                pid_ = pl["id"]
                if pl.get("sort_policy") == "category_asc":
                    sort = [(fb["Category"], "Ascending")]
                elif pid_ == "rule_split":
                    sort = [("'Rule Issues'[Issue Records]", "Descending")]
                elif pl.get("sort_policy") == "value_desc":
                    sort = [(ys[-1] if pid_ == "control_totals_pair" else ys[0], "Descending")]
                single = cmap.get(ys[0]) if (len(ys) == 1 and not legend_field) else None
                visual = bar(kind, fb["Category"], ys, pl["title"], alt, colors=cmap, series=legend_field, series_colors=series_colors,
                             tooltips=["'Rule Issues'[Issue Records]"] if pid_ == "rule_split" else None, sort=sort,
                             legend=len(ys) > 1 or bool(legend_field), single_color=single)
                if pid_ == "top_groups":
                    filters.append(topn_filter(f"{display}/{pid_}", fb["Category"], "Triage[Fix Records]", pl.get("top_n", 10)))
                if pid_ == "rule_split":
                    filters.append(topn_filter(f"{display}/{pid_}", fb["Category"], "'Rule Issues'[Records]", pl.get("top_n", 10)))
                if pid_ == "step_durations":
                    filters.append(topn_filter(f"{display}/{pid_}", fb["Category"], "'Run Steps'[Seconds]", pl.get("top_n", 10)))
                if pid_ == "control_totals_pair":
                    filters.append(starts_with_filter(f"{display}/{pid_}", "'Answer Key'[Metric]", "control_totals."))
                if pid_ == "reshape_rows":
                    filters.append(in_filter(f"{display}/{pid_}", "'Step Metrics'[Step]", ["reshape"]))
            elif kind == "tableEx" and pl["id"] == "integrity_table":
                visual = matrix(fb[0], fb[1:], pl["title"], alt)
            elif kind == "tableEx":
                fields, sort, wrap = list(fb), None, False
                if pl["id"] == "triage_table":
                    fields = [f.replace("Triage[Group Records]", "Triage[Records]") for f in fields]
                    sort = [("Triage[Agent vs Rules]", "Descending"), ("Triage[Records]", "Descending")]
                elif pl["id"] == "fix_list":
                    sort, wrap = [("'Fix List'[Account]", "Ascending")], True
                elif pl["id"] == "answer_key_queue":
                    sort, wrap = [("'Answer Key'[Status]", "Ascending"), ("Module[Module Name]", "Ascending")], True
                elif pl["id"] == "steps_table":
                    fields = [{"'Run Steps'[Step Rows]": "'Run Steps'[Rows Affected]", "'Run Steps'[Step Seconds]": "'Run Steps'[Seconds]"}.get(f, f) for f in fields]
                    sort = [("'Run Steps'[Started At]", "Ascending")]
                elif pl["id"] == "ai_calls_table":
                    swap = {"'AI Calls'[Input Tokens]": "'AI Calls'[Input Token Count]", "'AI Calls'[Output Tokens]": "'AI Calls'[Output Token Count]",
                            "'AI Calls'[Avg Latency (s)]": "'AI Calls'[Latency Ms]"}
                    fields = [swap.get(f, f) for f in fields]
                    sort = [("'AI Calls'[Created At]", "Descending")]
                widths = pinned_widths(pl["id"], fields, box[2])
                visual = table(fields, pl["title"], alt, sort, wrap or bool(widths), widths)
            else:
                raise SystemExit(f"{display}: no builder for {kind} ({pl['id']})")
            write(defn / "pages" / pid / "visuals" / vid / "visual.json", container(vid, box, order, visual, filters))
            keep.setdefault(pid, set()).add(vid)
            counts[display] = counts.get(display, 0) + 1

        # visual interactions from the contract's cross-filter rules
        def no(src, *targets):
            for t in targets:
                if src in vids and t in vids:
                    interactions.append({"source": vids[src], "target": vids[t], "type": "NoFilter"})
        def hl(src, *targets):
            for t in targets:
                if src in vids and t in vids:
                    interactions.append({"source": vids[src], "target": vids[t], "type": "HighlightFilter"})
        hl("outcome_by_module", "integrity_table")
        no("owner_slicer", "rule_split")
        no("checks_by_module", "card_pass", "card_allowed", "card_reviewed", "card_new", "card_failed", "card_result")
        page_json = {"$schema": page_schema, "name": pid, "displayName": display, "displayOption": "FitToPage",
                     "height": canvas["height"], "width": canvas["width"],
                     "objects": {"background": [{"properties": {"color": color(PAGE), "transparency": lit(0)}}],
                                 "outspace": [{"properties": {"color": color(LINE), "transparency": lit(0)}}]}}
        if interactions:
            page_json["visualInteractions"] = interactions
        write(defn / "pages" / pid / "page.json", page_json)

    pages_meta.update({"pageOrder": order_ids, "activePageName": order_ids[0]})
    write(defn / "pages" / "pages.json", pages_meta)
    for d in (defn / "pages").iterdir():                        # drop pages and visuals this contract no longer has
        if d.is_dir() and d.name not in keep:
            remove_tree(d)
        elif d.is_dir() and (d / "visuals").is_dir():
            for v in (d / "visuals").iterdir():
                if v.name not in keep[d.name]:
                    remove_tree(v)

    # theme: register as RegisteredResources (name == path == file name, .json included)
    name, t = theme()
    reg = REPORT / "StaticResources" / "RegisteredResources"
    write(reg / name, t)
    for old in reg.glob(f"{THEME_NAME}-*.json"):
        if old.name != name:
            old.unlink()
    report = json.loads((defn / "report.json").read_text(encoding="utf-8"))
    base_import = report["themeCollection"]["baseTheme"]["reportVersionAtImport"]
    report["themeCollection"]["customTheme"] = {"name": name, "reportVersionAtImport": base_import, "type": "RegisteredResources"}
    report["resourcePackages"] = [p for p in report["resourcePackages"] if p["name"] != "RegisteredResources"] + [
        {"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": name, "path": name, "type": "CustomTheme"}]}]
    report["objects"] = {"outspacePane": [{"properties": {"visible": lit(False), "expanded": lit(False)}}]}   # slicers carry the filters
    write(defn / "report.json", report)

    # live binding to the deployed model (Form 2): workspace name, model name, model id
    pbir = json.loads((REPORT / "definition.pbir").read_text(encoding="utf-8"))
    pbir["datasetReference"] = {"byConnection": {"connectionString":
        f"Data Source=powerbi://api.powerbi.com/v1.0/myorg/{WS['workspace']};Initial Catalog={WS['semantic_model']};"
        f"Integrated Security=ClaimsToken;semanticModelId={WS['semantic_model_id']}"}}
    write(REPORT / "definition.pbir", pbir)
    return {"pages": counts, "theme": name}


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
