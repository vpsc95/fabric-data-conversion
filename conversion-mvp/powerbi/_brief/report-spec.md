# Report Spec

Canonical handoff file: `conversion-mvp/powerbi/_brief/report-spec.md`. Status: **approved by delegation**. On Oct 8 the approval question went unanswered: the user was away and asked for autonomous work with good decisions. The report is a new item in the MVP workspace (nothing existing is changed) and can be deleted if not wanted.

## Report identity
- Report name: Conversion MVP
- Semantic model: Conversion MVP (Direct Lake on the Fabric SQL database `Conversion_DB`, mirrored to OneLake; no copy step)
- Audience: Cogsdale leadership and the conversion team at the Oct 9 demo; later, the conversion lead working a take
- Primary purpose: show in two pages how one take moves from the client's files to CSM on Microsoft: what came in, what passes the rules, what the AI says about the rest (expected by design or needs action, and who fixes it), and who approved the load
- Delivery target: publish to the Fabric workspace "Cogsdale Conversion MVP" as a new report (the full build's "Conversion Run" report is not touched)

## Semantic model binding
- Entry mode:          Local Model for the definition (TMDL in `conversion-mvp/powerbi/ConversionMVP.SemanticModel`, deployed by `deploy_model.py`); the report binds to the deployed model
- Workspace name:      Cogsdale Conversion MVP
- Workspace ID:        {{workspace_id}} (resolved by listing workspaces; re-resolved at publish time)
- Model name:          Conversion MVP
- Model ID:            {{semantic_model_id}} (resolved by listing semantic models; re-resolved at publish time)
- connectionString:    byConnection to the Fabric model (Data Source=powerbi://api.powerbi.com/v1.0/myorg/Cogsdale Conversion MVP;Initial Catalog=Conversion MVP;Integrated Security=ClaimsToken;semanticModelId={{semantic_model_id}})

## User decisions and constraints
- Scope: a simple MVP that showcases the platform, not the full business logic (user, Oct 8). Two pages.
- Page count: 2
- Interactivity: page navigator in the footer of both pages; one Take slicer (single select, synced, first take selected by default); no drillthrough, no bookmarks.
- Design direction: same visual language as the full build's report (Corporate Cool, outcome colour code), simplified.
- Publishing: new report item in the MVP workspace after validation and screenshot review.
- Tooling: `powerbi-report-author` CLI for validation and service preview; generator script reusing the full build's PBIR helpers; model changes as TMDL deployed through the Fabric REST API and checked with DAX.
- Model edit permissions: yes (the model is ours).
- Accessibility: WCAG AA contrast, alt text on every visual, status always shown as text, tab order = reading order.
- Data caveats: de-identified SAMPLE data; take-2 is simulated; simplified rules, so numbers differ from the go-live report on purpose; the capacity is paused between sessions.

## Narrative
- Core story: the client's files go in; a notebook reshapes them; rules (rows in a table) hold back what CSM can't take; an AI agent explains that almost all of it is expected by design and writes the client's to-do list for the rest; a person approves; the load reconciles to the record and the dollar.
- Audience promise: in 10 seconds, see what came in and what is ready; in 1 minute, see what needs a fix, who fixes it, and who approved the load.
- Key questions answered:
  1. What came in, what passes the rules, what was held back, and does it reconcile? (Take overview)
  2. Which checks run, and how are they defined? (Take overview: rules table)
  3. Of the records held back, which are expected by design and which need action, by whom, with what message? (AI triage and approval)
  4. Who approved the load, and what did it load? (AI triage and approval)

## Design identity
- Tone: Corporate Cool, operational edition (as the full build's report)
- Signature: three-state outcome code: Passes the rules (teal #0F766E), Expected by design (slate #64748B), Needs action (amber #B45309), on card accent bars and the stacked bars; owners cyan (client) and indigo (Cogsdale)
- Brownfield delta: n/a (new report, same design system as "Conversion Run")

## Page plan
1. Take overview: "One take, from the client's files to CSM"
   - Archetype: Executive Summary, variant B (KPI strip): five numbers of comparable weight
   - Purpose: the 10-second answer, plus the rules as data
   - Visuals: 5 KPI cards with context lines; stacked bar of passes / expected by design / needs action by module; rules table; footer with take description and page navigator
   - Slicers: Take (synced)
2. AI triage and approval: "What the AI found, who fixes it, and who approved the load"
   - Archetype: Operational Monitor, variant C (incident-first): the AI's proposals are a queue a person reviews before approving
   - Purpose: show the AI's proposals with their reasons and the approval record
   - Visuals: 5 KPI cards; AI proposals table (needs action first); approvals table; footer
   - Slicers: Take (synced)

## Design system summary
- Theme: "Cogsdale Conversion - Corporate Cool" (same as the full build): page #F1F5F9, white cards with 1px #E2E8F0 border, text #334155, titles #0F172A.
- Colour semantics: passes and loaded teal #0F766E; expected by design slate #64748B; needs action amber #B45309; client cyan #0E7490; Cogsdale indigo #4F46E5; neutral counts #334155.
- Typography: Segoe UI Semibold titles and values, Segoe UI body; numbers right-aligned.
- Layout: FHD 1920 x 1080, 12 x 12 grid, 32 px margin, 24 px gutter, 8 px snap; title and slicer band, KPI strip, body, footer.
- Accessibility: AA contrast on white cards for every colour above (measured for the full build: teal 5.47, slate 4.76, amber 5.02, cyan 5.36, indigo 6.29); alt text per visual.

## Model requirements
- Existing measures: Records Received, Ready to Load, Held Back, Loaded, Pass Rate, Balance Received, Balance Loaded, Balance Held Back, Reconciliation; Issues, Expected by Design, Needs Action, Client Fixes, Cogsdale Fixes, Issue Group Count, Needs Action Share; Approved By, Approval Status; Active Rules.
- New measures (after approval, validated with DAX): Records[Passes Rules] = Ready + Loaded; Records[Pass Rate Context]; Records[Held Back Context] ("8,108 expected by design · 225 need action"); Records[Balance Context]; Issue Groups[Groups Context]; Issue Groups[Expected Context]; Issue Groups[Needs Action Context]; Issue Groups[Client Fixes Context] and Issue Groups[Cogsdale Fixes Context] (added after the first screenshot review so all five cards on page 2 line up); Take[Take Context] (description and date for the footer).
- Relationships: in place (Take and Module to every fact, referential integrity assumed); Module sorted by Sort Order.

## Canonical design contract

```yaml
Design Brief:
  generated_by: powerbi-report-cli
  contract_version: 1
  mode: greenfield
  design_identity:
    tone: "Corporate Cool, operational edition: cool-grey #F1F5F9 surface, white cards with 1px #E2E8F0 border and 8px radius, slate #334155 text, Segoe UI Semibold headings; colour is reserved for outcome states"
    signature: "Three-state outcome code: Passes the rules (teal #0F766E), Expected by design (slate #64748B), Needs action (amber #B45309) on card accent bars and stacked bars on both pages"
  archetype: Executive
  navigation_model: page_navigator
  color_map:
    - measure: "Records[Records Received]"
      color: "#334155"
      tint: "#E2E8F0"
    - measure: "Records[Passes Rules]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "Records[Held Back]"
      color: "#64748B"
      tint: "#E2E8F0"
    - measure: "Records[Loaded]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "Records[Balance Received]"
      color: "#334155"
      tint: "#E2E8F0"
    - measure: "'Issue Groups'[Issues]"
      color: "#334155"
      tint: "#E2E8F0"
    - measure: "'Issue Groups'[Expected by Design]"
      color: "#64748B"
      tint: "#E2E8F0"
    - measure: "'Issue Groups'[Needs Action]"
      color: "#B45309"
      tint: "#FEF3C7"
    - measure: "'Issue Groups'[Client Fixes]"
      color: "#0E7490"
      tint: "#CFFAFE"
    - measure: "'Issue Groups'[Cogsdale Fixes]"
      color: "#4F46E5"
      tint: "#E0E7FF"
  semantic_colors:
    verdict: { "Expected": "#64748B", "Needs action": "#B45309" }
    owner:   { "Client": "#0E7490", "Cogsdale": "#4F46E5", "None": "#64748B" }
  pages:
    - name: "One take, from the client's files to CSM"
      display_name: "Take overview"
      role: landing
      archetype: Executive
      layout_variant: B
      variant_rationale: "Five numbers of comparable weight (received, passes, held back, loaded, balance) and no single hero metric, so the KPI strip is the message (variant B)."
      navigation:
        - element: page_navigator
          action: PageNavigation
          target: "Take overview, AI triage and approval"
          label: "Page names as tabs"
      page_background: "#F1F5F9"
      layout_summary: "Title with the take slicer; five KPI cards with context lines; outcome by module beside the rules table; footer with the take description and page navigator."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header:  [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            kpis:    [1, 2, 13, 4]
            outcome: [1, 4, 7, 12]
            rules:   [7, 4, 13, 12]
            footer:  [1, 12, 13, 13]
        placements:
          - id: page_title
            region: header
            kind: textbox
            text: "One take, from the client's files to CSM"
            purpose: "State the page question before any number."
          - id: take_slicer
            region: filters
            kind: slicer
            field_bindings: "Take[Take Id]"
            slicer_type: dropdown
            single_select: true
            sync_group: take
            slot: 3
            of: 3
          - id: kpi_received
            region: kpis
            kind: cardVisual
            label: "Records received"
            purpose: "How many records did the client's files deliver, and does the count reconcile?"
            field_bindings: { value: "Records[Records Received]", reference_label: "Records[Reconciliation]" }
            insight_basis: "Received = ready (or loaded) + held back."
            color_strategy: measure_match
            slot: 1
            of: 5
          - id: kpi_passes
            region: kpis
            kind: cardVisual
            label: "Pass every rule"
            purpose: "How many records CSM can take as they are?"
            field_bindings: { value: "Records[Passes Rules]", reference_label: "Records[Pass Rate Context]" }
            insight_basis: "Share of the received records that pass every rule."
            color_strategy: measure_match
            slot: 2
            of: 5
          - id: kpi_held_back
            region: kpis
            kind: cardVisual
            label: "Held back"
            purpose: "How many records broke a rule, and how many of them actually need a fix?"
            field_bindings: { value: "Records[Held Back]", reference_label: "Records[Held Back Context]" }
            insight_basis: "Split of the held-back records into expected by design and needs action (AI verdicts)."
            color_strategy: measure_match
            slot: 3
            of: 5
          - id: kpi_loaded
            region: kpis
            kind: cardVisual
            label: "Loaded to CSM"
            purpose: "Has a person approved the load, and what loaded?"
            field_bindings: { value: "Records[Loaded]", reference_label: "Approvals[Approval Status]" }
            insight_basis: "Waiting for approval, or who approved and when."
            color_strategy: measure_match
            slot: 4
            of: 5
          - id: kpi_balance
            region: kpis
            kind: cardVisual
            label: "Balance control total"
            purpose: "Do the dollars reconcile?"
            field_bindings: { value: "Records[Balance Received]", reference_label: "Records[Balance Context]" }
            insight_basis: "Balance received against loaded and held back."
            color_strategy: measure_match
            slot: 5
            of: 5
          - id: outcome_by_module
            region: outcome
            kind: barChart
            title: "Outcome by module: passes the rules, expected by design, needs action"
            purpose: "Where do the held-back records sit, and how much of them needs a fix?"
            field_bindings: { Category: "Module[Module]", Y: ["Records[Passes Rules]", "'Issue Groups'[Expected by Design]", "'Issue Groups'[Needs Action]"] }
            sort_policy: category_asc
            sort_note: "Module sorts by Sort Order: Customers, Services, Balances."
            color_strategy: measure_match
          - id: rules_table
            region: rules
            kind: tableEx
            title: "The rules: one row per check (add a row to add a check)"
            purpose: "What does the conversion check, and how is each check written?"
            field_bindings: ["Rules[Rule Id]", "Rules[Rule]", "Rules[Go-live Ticket]", "Rules[Active]", "Rules[Check (SQL)]"]
            sort_policy: rule_id_asc
            color_strategy: none
            formatting_note: "Pinned column widths; long text wraps."
          - id: take_card
            region: footer
            kind: cardVisual
            purpose: "Which take is this?"
            field_bindings: { value: "Take[Take Context]" }
            color_strategy: none
            slot: 1
            of: 2
          - id: page_nav
            region: footer
            kind: pageNavigator
            purpose: "Move between the two pages."
            field_bindings: "report pages"
            slot: 2
            of: 2
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: outcome, pct_of_content: 36 }
          balance_rationale: "The KPI strip carries the headline; the outcome chart and the rules table split the body evenly because together they explain it (where records are held back, and the checks that hold them); the footer holds the take and navigation."
    - name: "What the AI found, who fixes it, and who approved the load"
      display_name: "AI triage and approval"
      role: detail
      archetype: Operational
      layout_variant: C
      variant_rationale: "The AI's proposals are a short queue a person reviews before approving (incident-first, variant C): the queue is the hero; the approval record sits below it."
      navigation:
        - element: page_navigator
          action: PageNavigation
          target: "Take overview, AI triage and approval"
          label: "Page names as tabs"
      page_background: "#F1F5F9"
      layout_summary: "Title with the take slicer; five KPI cards; full-width AI proposals table, needs action first; approvals table; footer."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header:    [1, 1, 9, 2]
            filters:   [9, 1, 13, 2]
            kpis:      [1, 2, 13, 4]
            triage:    [1, 4, 13, 9]
            approvals: [1, 9, 13, 12]
            footer:    [1, 12, 13, 13]
        placements:
          - id: page_title
            region: header
            kind: textbox
            text: "What the AI found, who fixes it, and who approved the load"
            purpose: "State the page question before any number."
          - id: take_slicer
            region: filters
            kind: slicer
            field_bindings: "Take[Take Id]"
            slicer_type: dropdown
            single_select: true
            sync_group: take
            slot: 3
            of: 3
          - id: kpi_issues
            region: kpis
            kind: cardVisual
            label: "Issues found"
            purpose: "How many records broke a rule, in how many groups?"
            field_bindings: { value: "'Issue Groups'[Issues]", reference_label: "'Issue Groups'[Groups Context]" }
            insight_basis: "Groups of rule and code the AI reviewed."
            color_strategy: measure_match
            slot: 1
            of: 5
          - id: kpi_expected
            region: kpis
            kind: cardVisual
            label: "Expected by design"
            purpose: "How much needs no fix because an approved go-live decision explains it?"
            field_bindings: { value: "'Issue Groups'[Expected by Design]", reference_label: "'Issue Groups'[Expected Context]" }
            insight_basis: "Share of the issues the AI explains with an approved decision."
            color_strategy: measure_match
            slot: 2
            of: 5
          - id: kpi_needs_action
            region: kpis
            kind: cardVisual
            label: "Needs action"
            purpose: "How much needs a fix before go-live?"
            field_bindings: { value: "'Issue Groups'[Needs Action]", reference_label: "'Issue Groups'[Needs Action Context]" }
            insight_basis: "Share of the issues that need a fix."
            color_strategy: measure_match
            slot: 3
            of: 5
          - id: kpi_client
            region: kpis
            kind: cardVisual
            label: "Client fixes in its source"
            purpose: "How many records does the client correct?"
            field_bindings: { value: "'Issue Groups'[Client Fixes]", reference_label: "'Issue Groups'[Client Fixes Context]" }
            color_strategy: measure_match
            slot: 4
            of: 5
          - id: kpi_cogsdale
            region: kpis
            kind: cardVisual
            label: "Cogsdale fixes in mapping or setup"
            purpose: "How many records does Cogsdale fix?"
            field_bindings: { value: "'Issue Groups'[Cogsdale Fixes]", reference_label: "'Issue Groups'[Cogsdale Fixes Context]" }
            color_strategy: measure_match
            slot: 5
            of: 5
          - id: ai_proposals_table
            region: triage
            kind: tableEx
            title: "The AI's proposals, needs action first (a person approves before anything loads)"
            purpose: "For each group of issues: expected or needs action, who fixes it, the message for the client, and why."
            field_bindings: ["'Issue Groups'[AI Verdict]", "'Issue Groups'[Records]", "'Issue Groups'[Rule]", "'Issue Groups'[Group]", "'Issue Groups'[AI Owner]", "'Issue Groups'[Message to Client]", "'Issue Groups'[AI Reason]"]
            sort_policy: verdict_then_records_desc
            color_strategy: none
            formatting_note: "Pinned column widths; long text wraps; verdict shown as text."
          - id: approvals_table
            region: approvals
            kind: tableEx
            title: "Approvals: who approved the load, and the reconciliation at that moment (empty until a person approves the take)"
            purpose: "Who approved, when, and what loaded."
            field_bindings: ["Approvals[Approver]", "Approvals[Approved At]", "Approvals[Records Loaded]", "Approvals[Records Held Back]", "Approvals[Balance Received at Approval]", "Approvals[Balance Loaded at Approval]"]
            sort_policy: approved_at_desc
            color_strategy: none
          - id: take_card
            region: footer
            kind: cardVisual
            purpose: "Which take is this?"
            field_bindings: { value: "Take[Take Context]" }
            color_strategy: none
            slot: 1
            of: 2
          - id: page_nav
            region: footer
            kind: pageNavigator
            purpose: "Move between the two pages."
            field_bindings: "report pages"
            slot: 2
            of: 2
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: triage, pct_of_content: 45 }
          balance_rationale: "Variant C makes the AI's proposals the hero (45%): they carry the messages and reasons a person reads before approving; the approvals table needs 3 rows for a short history; the KPI strip states the split."
  interaction_pattern:
    drill_targets: []
    cross_filter_rules:
      - "Take overview: outcome_by_module -> rules_table None (rules are not per take); KPI cards Filter."
      - "AI triage and approval: default Highlight."
    sync_slicers:
      take: ["Take overview", "AI triage and approval"]
  accessibility:
    alt_text_strategy: "Headline + finding per visual; cards: measure + context line."
    contrast_notes: "Teal #0F766E 5.47, slate #64748B 4.76, amber #B45309 5.02, cyan #0E7490 5.36, indigo #4F46E5 6.29 on white cards (AA); coloured text never sits on the #F1F5F9 page."
  theme:
    base: "The full build's theme 'Cogsdale Conversion - Corporate Cool' (references/design/assets/base.json adapted, safeguards kept)"
    user_overrides: "none"
```

## Implementation notes

- Model changes: add the new measures above to the TMDL, redeploy with `conversion-mvp/powerbi/deploy_model.py`, DAX-check.
- PBIR authoring: `conversion-mvp/powerbi/build_report.py` generates `ConversionMVP.Report` from this contract, reusing the full build's PBIR helpers (validated 0 errors, 0 warnings there); `powerbi-report-author validate` after each build.
- Preview: service preview against the deployed model, screenshots of both pages, fix and re-verify.
- Publishing boundary: a new report "Conversion MVP" in "Cogsdale Conversion MVP" only; every Fabric call carries `x-ms-fabric-skill: powerbi-report-cli`.
- Risks: the Take slicer must open on one take (strict single select); the AI proposals table needs pinned widths so long messages wrap.
