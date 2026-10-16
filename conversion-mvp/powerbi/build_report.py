"""Build the Conversion MVP report (PBIR) from the approved contract in _brief/report-spec.md.

  python build_report.py
  powerbi-report-author validate ConversionMVP.Report

Reuses the PBIR helpers of the full build's generator (../../conversion-platform/powerbi/build_report.py: cards, bars,
tables, slicer, page navigator, theme), which validated with 0 errors and 0 warnings there, so both reports share one
design system. Deterministic: page and visual names derive from their content.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
FULL = HERE.parents[1] / "conversion-platform" / "powerbi"
_spec = importlib.util.spec_from_file_location("full_report_builder", FULL / "build_report.py")
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)

WS = json.loads((HERE.parent / "workspace.json").read_text(encoding="utf-8"))
MODEL_ID = WS["semantic_model_id"]                     # resolved by listing the workspace's semantic models (deploy_model.py)
REPORT = HERE / "ConversionMVP.Report"
SPEC = HERE / "_brief" / "report-spec.md"

# point the shared helpers at this model and report
br.TABLES = HERE / "ConversionMVP.SemanticModel" / "definition" / "tables"
br.KINDS = br.model_inventory()
br.REPORT = REPORT
br.DISPLAY_NAMES.update({"Passes Rules": "Passes the rules", "Expected by Design": "Expected by design", "Needs Action": "Needs action",
                         "Rule Id": "ID", "Go-live Ticket": "Go-live ticket", "Check (SQL)": "Check (SQL)", "AI Verdict": "AI verdict",
                         "AI Owner": "Who fixes it", "Message to Client": "Message to the client", "AI Reason": "Why",
                         "Approved At": "Approved at (UTC)", "Records Loaded": "Loaded", "Records Held Back": "Held back",
                         "Balance Received at Approval": "Balance received", "Balance Loaded at Approval": "Balance loaded"})
br.COLUMN_WIDTHS = {
    "rules_table": {"Rules[Rule Id]": 76, "Rules[Rule]": None, "Rules[Go-live Ticket]": 96, "Rules[Active]": 60, "Rules[Check (SQL)]": 300},
    "ai_proposals_table": {"'Issue Groups'[AI Verdict]": 104, "'Issue Groups'[Records]": 76, "'Issue Groups'[Rule]": 300,
                           "'Issue Groups'[Group]": 220, "'Issue Groups'[AI Owner]": 92, "'Issue Groups'[Message to Client]": None,
                           "'Issue Groups'[AI Reason]": 380},
}
SORTS = {"rules_table": [("Rules[Rule Id]", "Ascending")],
         "ai_proposals_table": [("'Issue Groups'[AI Verdict]", "Descending"), ("'Issue Groups'[Records]", "Descending")],
         "approvals_table": [("Approvals[Approved At]", "Descending")],
         "outcome_by_module": [("Module[Module]", "Ascending")]}
PAGE_SCHEMA = json.loads(next((FULL / "ConversionRun.Report" / "definition" / "pages").glob("*/page.json")).read_text(encoding="utf-8"))["$schema"]


def scaffold() -> None:
    """The report's fixed parts: item metadata, binding, report settings and the base theme (copied from the full report)."""
    src = FULL / "ConversionRun.Report"
    (REPORT / "definition" / "pages").mkdir(parents=True, exist_ok=True)
    br.write(REPORT / ".platform", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.1.0/schema.json",
                                    "metadata": {"type": "Report", "displayName": "Conversion MVP"},
                                    "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-000000000000"}})
    br.write(REPORT / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json", "version": "4.0",
        "datasetReference": {"byConnection": {"connectionString":     # local-dev form; the publish step swaps in semanticmodelid=<id>
            f"Data Source=powerbi://api.powerbi.com/v1.0/myorg/{WS['workspace']};Initial Catalog={WS['semantic_model']};"
            f"Integrated Security=ClaimsToken;semanticModelId={MODEL_ID}"}}})
    shutil.copyfile(src / "definition" / "version.json", REPORT / "definition" / "version.json")
    base = src / "StaticResources" / "SharedResources" / "BaseThemes"
    (REPORT / "StaticResources" / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
    for f in base.glob("*.json"):
        shutil.copyfile(f, REPORT / "StaticResources" / "SharedResources" / "BaseThemes" / f.name)
    report = json.loads((src / "definition" / "report.json").read_text(encoding="utf-8"))
    name, theme = br.theme()
    reg = REPORT / "StaticResources" / "RegisteredResources"
    reg.mkdir(parents=True, exist_ok=True)
    for old in reg.glob("*.json"):
        old.unlink()
    br.write(reg / name, theme)
    report["themeCollection"]["customTheme"]["name"] = name
    report["resourcePackages"] = [p for p in report["resourcePackages"] if p["name"] != "RegisteredResources"] + [
        {"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": name, "path": name, "type": "CustomTheme"}]}]
    br.write(REPORT / "definition" / "report.json", report)
    (HERE / "ConversionMVP.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
        "artifacts": [{"report": {"path": "ConversionMVP.Report"}}], "settings": {"enableAutoRecovery": True}}, indent=2) + "\n", encoding="utf-8")


def build() -> dict:
    contract = yaml.safe_load(re.search(r"```yaml\n(.*?)```", SPEC.read_text(encoding="utf-8"), re.S).group(1))["Design Brief"]
    cmap = {c["measure"]: c["color"] for c in contract["color_map"]}
    scaffold()
    pages_dir = REPORT / "definition" / "pages"
    order, counts, keep = [], {}, {}
    for page in contract["pages"]:
        lc, display = page["layout_contract"], page["display_name"]
        pid = br.hexid("page", display)
        order.append(pid)
        canvas, grid = lc["canvas"], lc["grid"]
        vids, interactions = {}, []
        for n, pl in enumerate(lc["placements"], 1):
            box = br.slot_box(br.region_box(canvas, grid, grid["regions"][pl["region"]]), pl.get("slot"), pl.get("of"))
            kind, fb, vid = pl["kind"], pl.get("field_bindings"), br.hexid("visual", display, pl["id"])
            vids[pl["id"]] = vid
            alt = ((pl.get("title") or pl.get("text") or pl.get("label") or pl["id"]) + ". " + (pl.get("purpose") or "")).strip()
            if kind == "textbox":
                visual = br.textbox(pl["text"], alt)
            elif kind == "slicer":
                box = (box[0], box[1], box[2], 80)
                visual = br.slicer(fb, "Take", bool(pl.get("single_select")), pl.get("sync_group"), "Take slicer: choose one take")
            elif kind == "pageNavigator":
                visual = br.page_navigator("Page tabs: Take overview, AI triage and approval")
            elif kind == "cardVisual" and pl["region"] == "footer":
                visual = br.card(fb["value"], None, "Which take this page shows", accent=None, value_size=11, frame=False)
            elif kind == "cardVisual":
                box = (box[0], box[1], box[2], br.card_height(canvas["height"], True))
                visual = br.card(fb["value"], pl.get("label"), alt, cmap.get(fb["value"], br.NEUTRAL_ACCENT), fb.get("reference_label"))
            elif kind == "barChart":
                visual = br.bar(kind, fb["Category"], fb["Y"], pl["title"], alt, colors=cmap, sort=SORTS.get(pl["id"]), legend=True)
            elif kind == "tableEx":
                widths = br.pinned_widths(pl["id"], list(fb), box[2])
                visual = br.table(list(fb), pl["title"], alt, SORTS.get(pl["id"]), bool(widths), widths)
            else:
                raise SystemExit(f"{display}: no builder for {kind} ({pl['id']})")
            br.write(pages_dir / pid / "visuals" / vid / "visual.json", br.container(vid, box, n, visual))
            keep.setdefault(pid, set()).add(vid)
            counts[display] = counts.get(display, 0) + 1
        if "outcome_by_module" in vids and "rules_table" in vids:        # contract: the rules table is not filtered by the chart
            interactions.append({"source": vids["outcome_by_module"], "target": vids["rules_table"], "type": "NoFilter"})
        page_json = {"$schema": PAGE_SCHEMA, "name": pid, "displayName": display, "displayOption": "FitToPage",
                     "height": canvas["height"], "width": canvas["width"],
                     "objects": {"background": [{"properties": {"color": br.color(br.PAGE), "transparency": br.lit(0)}}],
                                 "outspace": [{"properties": {"color": br.color(br.LINE), "transparency": br.lit(0)}}]}}
        if interactions:
            page_json["visualInteractions"] = interactions
        br.write(pages_dir / pid / "page.json", page_json)
    br.write(pages_dir / "pages.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
                                        "pageOrder": order, "activePageName": order[0]})
    for d in pages_dir.iterdir():                                   # drop pages and visuals this contract no longer has
        if d.is_dir() and d.name not in keep:
            br.remove_tree(d)
        elif d.is_dir() and (d / "visuals").is_dir():
            for v in (d / "visuals").iterdir():
                if v.name not in keep[d.name]:
                    br.remove_tree(v)
    return {"pages": counts}


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
