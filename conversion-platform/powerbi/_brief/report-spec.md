# Report Spec

Canonical handoff file: `conversion-platform/powerbi/_brief/report-spec.md` (carried by absolute path in every
authoring step). Status: **awaiting approval**.

## Report identity
- Report name: Conversion Run
- Semantic model: Conversion Run (Direct Lake on `lh_conversion` `rpt_*` tables, written by the pipeline's Publish step)
- Audience: Cogsdale conversion consultants (reviewer and the conversion team) working a take; the client's data steward reading the fix list; Cogsdale and Microsoft stakeholders at the Oct 9 demo
- Primary purpose: show, for one take, what loaded and what failed; whether each failure is expected by design or needs a fix and by whom; the triage agent's proposals waiting for a person; and proof that the take reproduces the go-live integrity report
- Delivery target: publish to the Fabric workspace "Cogsdale Conversion Prototype", bound to the "Conversion Run" semantic model; PBIP kept in `conversion-platform/powerbi/` for Git

## Semantic model binding
- Entry mode:          Local Model for the definition (TMDL in `conversion-platform/powerbi/ConversionRun.SemanticModel`, source of truth in Git, deployed to Fabric by `powerbi/deploy_model.py` and checked with `powerbi/check_model.py`); the report binds to the deployed model, because the local TMDL keeps the OneLake workspace and lakehouse IDs as deploy-time placeholders
- Workspace name:      Cogsdale Conversion Prototype
- Workspace ID:        {{workspace_id}} (resolved by listing workspaces; re-resolved at publish time)
- Model name:          Conversion Run
- Model ID:            {{semantic_model_id}} (resolved by listing semantic models; re-resolved at publish time)
- connectionString:    byConnection to the Fabric model (Desktop preview and publish); the authoring mode assembles it from the names and IDs above

## User decisions and constraints
- Scope: one report, four pages (Processed items, Exceptions & triage, Reconciliation, Run audit). Inferred from the agreed prototype plan; no drillthrough or tooltip pages in this build.
- Page count: 4
- Interactivity: Page Navigator in every page's footer (primary model). Take slicer on every page (single select, synced, defaults to the published take); Module slicer synced on Exceptions and Reconciliation; Owner slicer on Exceptions; Status slicer on Reconciliation. Selecting a triage group filters the record-level fix list. No bookmarks.
- Design direction: Corporate Cool tone with the three-state outcome colour code as the signature (see Design identity).
- Publishing: yes, after local validation and screenshots, to the existing workspace.
- Tooling: `powerbi-report-author` 0.5.0 (installed); Power BI Desktop 2.158 (x64 under emulation on Arm64; needs sign-in to the MngEnv tenant for preview, otherwise service preview); Node 24; model changes as TMDL edits deployed through the Fabric REST API (`deploy_model.py`) and checked with DAX (`check_model.py`, currently 51 measures, all checks pass).
- Model edit permissions: yes, the model is ours (TMDL in Git).
- Accessibility: WCAG AA contrast on every text pair, alt text on every visual, colour never the only cue (text labels and icons on every status), tab order = reading order.
- Data caveats: the SAMPLE data is a de-identified copy (accounts and meters are tokens); one take (go-live) so far; amounts are doubles in Delta and shown with 2 decimals; the answer key's expected values are text in the source and parsed to numbers where they are numbers; the F64 capacity is paused between work sessions, so the report shows data only while it runs.

## Narrative
- Core story: the platform replays the SAMPLE go-live from extracts with no hand-work, reproduces every number in the go-live integrity report, separates by-design exclusions from real problems, and hands the real problems to the right owner with wording the client can act on, while the AI only proposes and a person decides.
- Audience promise: in 10 seconds, know whether the take is good; in 2 minutes, know what to fix and who fixes it.
- Key questions answered:
  1. Did every module receive and load what go-live did? (Processed items)
  2. Which failures are by design and which need action, by whom? (Processed items, Exceptions)
  3. What does the triage agent propose, where does it disagree with the rules, and what is still waiting for a decision? (Exceptions)
  4. Does every checked number match the go-live report, and is every difference explained and approved? (Reconciliation)
  5. Did every step succeed, what did the reshape remove, and what did the AI see and cost? (Run audit)

## Design identity (from the `design` mode Step 1)
- Tone: Corporate Cool, operational edition (cool-grey surface, white cards, slate type, colour reserved for outcome states)
- Signature: three-state outcome code (Loaded teal, Expected by design slate, Actionable amber) on KPI accent bars, stacked bars and table status icons on every page; red only for a failed answer-key check
- Brownfield delta: n/a (greenfield)

## Page plan (archetypes from the `design` mode Step 3)
1. Processed items: "What loaded, what failed, and does it match the go-live?"
   - Archetype: Executive Summary
   - Layout variant (A/B/C): B (KPI-Strip): six KPIs of comparable weight and no single hero metric
   - Purpose: the 10-second answer, in the shape of the integrity report
   - Visuals: 6 KPI cards with go-live references; 100% stacked bar of loaded / expected / actionable by module; integrity table by module; freshness card; page navigator
   - Fields/measures: Module Results measures; Answer Key go-live references; Module[Module Name]
   - Slicers/interactions: Take (synced)
2. Exceptions & triage: "Which failures need a fix, and who owns them?"
   - Archetype: Analytical Canvas
   - Layout variant (A/B/C): B (Inline-Slicers): three slicers fit inline, content keeps full width
   - Purpose: work the exception list; review the agent's proposals, disagreements first
   - Visuals: 4 KPI cards; top issue groups by records to fix (by owner); expected vs actionable by rule; triage group table; record-level fix list
   - Fields/measures: Triage, Rule Issues, Fix List measures and columns
   - Slicers/interactions: Take, Module (synced), Owner; group table selection filters the fix list
3. Reconciliation: "Every number checked against the go-live integrity report"
   - Archetype: Operational Monitor
   - Layout variant (A/B/C): C (Incident-First): the answer-key check is an exception queue to clear, FAIL and NEW first
   - Purpose: prove the replay; show each explained difference with its reason and approver
   - Visuals: 6 status cards; answer-key queue table; checks by module and status; control totals go-live vs this take
   - Fields/measures: Answer Key measures and columns
   - Slicers/interactions: Take, Module (synced), Status
4. Run audit: "Run audit: every step, the report clean-up and every AI call"
   - Archetype: Operational Monitor
   - Layout variant (A/B/C): A (4-Up Status): four health signals with tiles and detail tables (variant C is used by Reconciliation)
   - Purpose: show that the run is healthy and the AI is governed (PII gate, region, tokens)
   - Visuals: 4 status tiles; SQL step durations; reshape rows kept vs removed; run steps table; AI calls table
   - Fields/measures: Run Steps, Step Metrics, AI Calls measures
   - Slicers/interactions: Take (synced)

## Design system summary
- Theme name + base palette: "Cogsdale Conversion - Corporate Cool", adapted from `references/design/assets/base.json`; page `#F1F5F9`, cards `#FFFFFF` with 1px `#E2E8F0` border and 8px radius, text `#334155`, titles `#0F172A`.
- Color semantics: Loaded / PASS / healthy = teal `#0F766E`; Expected by design / REVIEWED / owner none = slate `#64748B`; Actionable / NEW = amber `#B45309`; ALLOWED = blue `#2563EB`; FAIL = red `#DC2626` (only); owners: client = cyan `#0E7490`, Cogsdale = indigo `#4F46E5`; go-live baseline = dark slate `#475569`; neutral counts = slate `#334155`.
- Typography pairing: Segoe UI Semibold (page title 20pt, visual titles 12pt, KPI values 28pt) + Segoe UI (body 10-11pt, minimum 9pt axis labels); numbers right-aligned in tables.
- Layout pattern: FHD 1920 x 1080, 12 x 12 grid, 32px margin, 24px gutter, 8px snap; header band (title left, slicers right), 2-row KPI strip, content, footer row (freshness + page navigator).
- Accessibility commitments: AA contrast (measured: every palette colour is 4.7:1 or better on the white cards; coloured text never sits directly on the grey page), alt text per visual, status always shown as text plus icon, tab order by reading order, slicer targets at least 24px.

## Model requirements
- Existing measures: Records Received, Records Loaded, Records Failed, Load %, Expected Failures, Actionable Failures, Actionable %; Issue Records, Expected Issue Records, Actionable Issue Records, Rules Fired; Issue Groups, Group Records, Groups Pending, Groups Decided, Records to Fix, Agent Agreement %, Agent Disagreements, Groups to Review First, Agent Confidence; Records on Fix List, Accounts on Fix List, Client Fixes, Cogsdale Fixes; Checks, Checks Passed / Allowed / Reviewed / Failed / New, Answer Key Result, Answer Key Summary, Answer Key Color; Control Amount, Control Records; Metric Value, Rows Read, Rows Kept, Artifacts Removed, Fill-down Mismatches; Step Seconds, Step Rows, Steps Failed, Steps Color; # AI Calls, Calls Blocked by PII Gate, Input Tokens, Output Tokens, Avg Latency (s), PII Gate Color; Last Published.
- New measures (added after approval, validated with DAX):
  - Answer Key: `Go-live Received`, `Go-live Loaded`, `Go-live Failed` (expected value of the metric), `Go-live Value`, `This Take Value` (sum of expected / actual value), `Checks Context` ("N checks against the go-live report").
  - Module Results: `Received vs Go-live`, `Loaded vs Go-live`, `Failed vs Go-live` (text: "go-live 17,974 · Δ 0"), `Actionable Context` ("x% of failed records need a fix"), `Load Context` ("loaded ÷ (loaded + failed)").
  - Triage / Fix List: `Records to Fix Context` ("in N issue groups"), `Client Share Context`, `Cogsdale Share Context` ("x% of the fix list"), `Review Context` ("N to review first · N pending").
  - Run audit: `Steps Context`, `PII Context`, `Fill-down Context`, `Token Context`.
- New calculated columns: none (Direct Lake). New source column: `rpt_answer_key.MetricLabel` (readable metric name, e.g. "Control total: RESI-DEP") added in `convplat/publish.py`.
- Relationship/sort requirements: in place: Module and Take to every fact; Fix List to Triage on Group Id (Module and Take reach the fix list through Triage); Module Name sorted by Sort Order; Answer Key Status sorted by Status Order (FAIL, NEW, ALLOWED, REVIEWED, PASS). Every relationship assumes referential integrity, so Direct Lake adds no blank "unknown member" and slicers show no "(Blank)" entry; the Publish step refuses to write report tables whose keys would break a relationship.

## Canonical design contract

```yaml
Design Brief:
  generated_by: powerbi-report-cli
  contract_version: 1
  mode: greenfield
  design_identity:
    tone: "Corporate Cool, operational edition: cool-grey #F1F5F9 surface, white cards with 1px #E2E8F0 border and 8px radius, slate #334155 text, Segoe UI Semibold headings; colour is reserved for outcome states, never decoration"
    signature: "Three-state outcome code: every record count is split into Loaded (teal #0F766E), Expected by design (slate #64748B) and Actionable (amber #B45309), with the same colours and words on KPI accent bars, stacked bars and table status icons on every page; red #DC2626 appears only for a failed answer-key check"
  archetype: Executive
  navigation_model: page_navigator
  color_map:
    - measure: "'Module Results'[Records Loaded]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "'Module Results'[Load %]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "'Module Results'[Expected Failures]"
      color: "#64748B"
      tint: "#E2E8F0"
    - measure: "'Module Results'[Actionable Failures]"
      color: "#B45309"
      tint: "#FEF3C7"
    - measure: "'Module Results'[Records Received]"
      color: "#334155"
      tint: "#E2E8F0"
    - measure: "'Module Results'[Records Failed]"
      color: "#334155"
      tint: "#E2E8F0"
    - measure: "'Rule Issues'[Expected Issue Records]"
      color: "#64748B"
      tint: "#E2E8F0"
    - measure: "'Rule Issues'[Actionable Issue Records]"
      color: "#B45309"
      tint: "#FEF3C7"
    - measure: "Triage[Records to Fix]"
      color: "#B45309"
      tint: "#FEF3C7"
    - measure: "Triage[Agent Agreement %]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "'Fix List'[Client Fixes]"
      color: "#0E7490"
      tint: "#CFFAFE"
    - measure: "'Fix List'[Cogsdale Fixes]"
      color: "#4F46E5"
      tint: "#E0E7FF"
    - measure: "'Answer Key'[Checks Passed]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "'Answer Key'[Checks Allowed]"
      color: "#2563EB"
      tint: "#DBEAFE"
    - measure: "'Answer Key'[Checks Reviewed]"
      color: "#64748B"
      tint: "#E2E8F0"
    - measure: "'Answer Key'[Checks Failed]"
      color: "#DC2626"
      tint: "#FEE2E2"
    - measure: "'Answer Key'[Checks New]"
      color: "#B45309"
      tint: "#FEF3C7"
    - measure: "'Answer Key'[Go-live Value]"
      color: "#475569"
      tint: "#E2E8F0"
    - measure: "'Answer Key'[This Take Value]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "'Run Steps'[Step Seconds]"
      color: "#334155"
      tint: "#E2E8F0"
    - measure: "'Step Metrics'[Rows Kept]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "'Step Metrics'[Artifacts Removed]"
      color: "#64748B"
      tint: "#E2E8F0"
    - measure: "'Step Metrics'[Fill-down Mismatches]"
      color: "#0F766E"
      tint: "#CCFBF1"
    - measure: "'AI Calls'[Input Tokens]"
      color: "#334155"
      tint: "#E2E8F0"
  semantic_colors:
    status:   { PASS: "#0F766E", ALLOWED: "#2563EB", REVIEWED: "#64748B", NEW: "#B45309", FAIL: "#DC2626" }
    label:    { expected: "#64748B", actionable: "#B45309", investigate: "#7C3AED" }
    owner:    { client: "#0E7490", cogsdale: "#4F46E5", none: "#64748B" }
    health:   { good: "#0F766E", warning: "#B45309", critical: "#DC2626" }
  pages:
    - name: "What loaded, what failed, and does it match the go-live?"
      display_name: "Processed items"
      role: landing
      archetype: Executive
      layout_variant: B
      variant_rationale: "Six KPIs of comparable weight (received, loaded, failed, load %, actionable, answer key) and no single hero metric, so the KPI strip is the message (variant B)."
      navigation:
        - element: page_navigator
          action: PageNavigation
          target: "Processed items, Exceptions & triage, Reconciliation, Run audit"
          label: "Page names as tabs"
      page_background: "#F1F5F9"
      layout_summary: "Title with the take slicer; six KPI cards each with a go-live reference; module outcome composition beside the integrity table; footer with freshness and page navigator."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header:    [1, 1, 8, 2]
            filters:   [8, 1, 13, 2]
            kpis:      [1, 2, 13, 4]
            outcome:   [1, 4, 7, 12]
            integrity: [7, 4, 13, 12]
            footer:    [1, 12, 13, 13]
        placements:
          - id: page_title
            region: header
            kind: textbox
            text: "What loaded, what failed, and does it match the go-live?"
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
            purpose: "How many rows did the extracts deliver, and is it the go-live number?"
            field_bindings: { value: "'Module Results'[Records Received]", reference_label: "'Module Results'[Received vs Go-live]" }
            insight_basis: "Delta against the go-live integrity report's received count."
            color_strategy: measure_match
            slot: 1
            of: 6
          - id: kpi_loaded
            region: kpis
            kind: cardVisual
            purpose: "How many records load into CSM, against go-live?"
            field_bindings: { value: "'Module Results'[Records Loaded]", reference_label: "'Module Results'[Loaded vs Go-live]" }
            insight_basis: "Delta against the go-live loaded count."
            color_strategy: measure_match
            slot: 2
            of: 6
          - id: kpi_failed
            region: kpis
            kind: cardVisual
            purpose: "How many records are skipped at load, against go-live?"
            field_bindings: { value: "'Module Results'[Records Failed]", reference_label: "'Module Results'[Failed vs Go-live]" }
            insight_basis: "Delta against the go-live failed count."
            color_strategy: measure_match
            slot: 3
            of: 6
          - id: kpi_load_pct
            region: kpis
            kind: cardVisual
            purpose: "What share of the records the conversion tried to load actually loads?"
            field_bindings: { value: "'Module Results'[Load %]", reference_label: "'Module Results'[Load Context]" }
            insight_basis: "Ratio of loaded to attempted records."
            color_strategy: measure_match
            slot: 4
            of: 6
          - id: kpi_actionable
            region: kpis
            kind: cardVisual
            purpose: "How many failed records need someone to fix something?"
            field_bindings: { value: "'Module Results'[Actionable Failures]", reference_label: "'Module Results'[Actionable Context]" }
            insight_basis: "Share of failed records that are actionable rather than expected by design."
            color_strategy: measure_match
            slot: 5
            of: 6
          - id: kpi_answer_key
            region: kpis
            kind: cardVisual
            purpose: "Does this take reproduce the go-live integrity report?"
            field_bindings: { value: "'Answer Key'[Answer Key Result]", reference_label: "'Answer Key'[Answer Key Summary]", accent_color: "'Answer Key'[Answer Key Color]" }
            insight_basis: "Composite status: result word, pass/allowed/reviewed/fail/new counts and a status-coloured accent bar."
            color_strategy: semantic
            slot: 6
            of: 6
          - id: outcome_by_module
            region: outcome
            kind: hundredPercentStackedBarChart
            purpose: "Where do failures sit, and how much of each module's failure is by design?"
            field_bindings: { Category: "Module[Module Name]", Y: ["'Module Results'[Records Loaded]", "'Module Results'[Expected Failures]", "'Module Results'[Actionable Failures]"] }
            sort_policy: category_asc
            sort_note: "Module Name sorts by Sort Order, the CSM load order."
            color_strategy: measure_match
            title: "Outcome by module: loaded, expected by design, actionable"
          - id: integrity_table
            region: integrity
            kind: tableEx
            purpose: "What did each module receive, load and fail, and how much of it is actionable?"
            field_bindings: ["Module[Module Name]", "'Module Results'[Records Received]", "'Module Results'[Records Loaded]", "'Module Results'[Records Failed]", "'Module Results'[Expected Failures]", "'Module Results'[Actionable Failures]", "'Module Results'[Load %]"]
            sort_policy: category_asc
            color_strategy: measure_match
            formatting_note: "Amber data bars on Actionable Failures; totals row on; numbers right-aligned."
            title: "Integrity report by module"
          - id: freshness_card
            region: footer
            kind: cardVisual
            purpose: "How fresh is this view?"
            field_bindings: { value: "Take[Last Published]" }
            color_strategy: none
            label: "Last published (UTC) · source lh_conversion rpt_* tables"
            slot: 1
            of: 2
          - id: page_nav
            region: footer
            kind: pageNavigator
            purpose: "Move between the four pages."
            field_bindings: "report pages"
            slot: 2
            of: 2
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: outcome, pct_of_content: 36 }
          balance_rationale: "The KPI strip carries the headline; the composition chart and the integrity table split the body evenly because together they explain the strip (where failures are, and the exact numbers); the footer holds freshness and navigation."
    - name: "Which failures need a fix, and who owns them?"
      display_name: "Exceptions & triage"
      role: detail
      archetype: Analytical
      layout_variant: B
      variant_rationale: "Three slicers (take, module, owner) fit inline with the title, so a filter rail would sit mostly empty and the content keeps full width (variant B)."
      navigation:
        - element: page_navigator
          action: PageNavigation
          target: "Processed items, Exceptions & triage, Reconciliation, Run audit"
          label: "Page names as tabs"
      page_background: "#F1F5F9"
      layout_summary: "Title with three slicers; four KPI cards; top issue groups by owner beside the expected-vs-actionable split by rule; triage group table beside the record-level fix list; footer."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header:  [1, 1, 8, 2]
            filters: [8, 1, 13, 2]
            kpis:    [1, 2, 13, 4]
            hero:    [1, 4, 8, 8]
            rules:   [8, 4, 13, 8]
            groups:  [1, 8, 8, 12]
            records: [8, 8, 13, 12]
            footer:  [1, 12, 13, 13]
        placements:
          - id: page_title
            region: header
            kind: textbox
            text: "Which failures need a fix, and who owns them?"
            purpose: "State the page question."
          - id: take_slicer
            region: filters
            kind: slicer
            field_bindings: "Take[Take Id]"
            slicer_type: dropdown
            single_select: true
            sync_group: take
            slot: 1
            of: 3
          - id: module_slicer
            region: filters
            kind: slicer
            field_bindings: "Module[Module Name]"
            slicer_type: dropdown
            sync_group: module
            slot: 2
            of: 3
          - id: owner_slicer
            region: filters
            kind: slicer
            field_bindings: "Triage[Final Owner]"
            slicer_type: dropdown
            slot: 3
            of: 3
          - id: kpi_to_fix
            region: kpis
            kind: cardVisual
            purpose: "How many issue records still need a fix?"
            field_bindings: { value: "Triage[Records to Fix]", reference_label: "Triage[Records to Fix Context]" }
            insight_basis: "Share of the issue records in the selected groups."
            color_strategy: measure_match
            slot: 1
            of: 4
          - id: kpi_client
            region: kpis
            kind: cardVisual
            purpose: "How many records does the client fix in the source system?"
            field_bindings: { value: "'Fix List'[Client Fixes]", reference_label: "'Fix List'[Client Share Context]" }
            insight_basis: "Client share of the fix list."
            color_strategy: measure_match
            slot: 2
            of: 4
          - id: kpi_cogsdale
            region: kpis
            kind: cardVisual
            purpose: "How many records does Cogsdale fix in mapping or setup?"
            field_bindings: { value: "'Fix List'[Cogsdale Fixes]", reference_label: "'Fix List'[Cogsdale Share Context]" }
            insight_basis: "Cogsdale share of the fix list."
            color_strategy: measure_match
            slot: 3
            of: 4
          - id: kpi_agent
            region: kpis
            kind: cardVisual
            purpose: "How often does the agent agree with the approved rules, and what is waiting for a person?"
            field_bindings: { value: "Triage[Agent Agreement %]", reference_label: "Triage[Review Context]" }
            insight_basis: "Records-weighted agreement plus the count of disagreements to review first and proposals pending."
            color_strategy: measure_match
            slot: 4
            of: 4
          - id: top_groups
            region: hero
            kind: barChart
            purpose: "Which issue groups hold the most records to fix, and who owns each?"
            field_bindings: { Category: "Triage[Group]", Y: "Triage[Records to Fix]", Legend: "Triage[Final Owner]" }
            sort_policy: value_desc
            top_n: 10
            color_strategy: semantic
            title: "Top 10 issue groups by records to fix"
          - id: rule_split
            region: rules
            kind: barChart
            purpose: "Which rules fire most, and how much of each is expected by design?"
            field_bindings: { Category: "'Rule Issues'[Rule]", Y: ["'Rule Issues'[Expected Issue Records]", "'Rule Issues'[Actionable Issue Records]"] }
            stacking: stacked
            sort_policy: value_desc
            top_n: 10
            color_strategy: measure_match
            title: "Records by rule: expected by design vs actionable"
          - id: triage_table
            region: groups
            kind: tableEx
            purpose: "What does the agent propose for each group, and which proposals disagree with the rules?"
            field_bindings: ["Triage[Group]", "Triage[Group Records]", "Triage[Severity]", "Triage[Agent Label]", "Triage[Agent vs Rules]", "Triage[Final Owner]", "Triage[Final Category]", "Triage[Decision Status]", "Triage[Confidence]", "Triage[Group Key]"]
            sort_policy: value_desc
            sort_note: "Agent vs Rules = disagrees first, then Group Records descending."
            color_strategy: semantic
            formatting_note: "Amber warning icon when Agent vs Rules = disagrees; owner text coloured by owner semantic; Group Key shown for `run_local.py decide`."
            title: "Triage proposals (a person decides)"
          - id: fix_list
            region: records
            kind: tableEx
            purpose: "Which accounts are on the fix list for the selected group, and what do we tell the client?"
            field_bindings: ["'Fix List'[Account]", "'Fix List'[Title]", "'Fix List'[Owner]", "'Fix List'[Severity]", "'Fix List'[Client Message]"]
            sort_policy: category_asc
            color_strategy: semantic
            title: "Fix list (records)"
          - id: freshness_card
            region: footer
            kind: cardVisual
            purpose: "How fresh is this view?"
            field_bindings: { value: "Take[Last Published]" }
            color_strategy: none
            label: "Last published (UTC)"
            slot: 1
            of: 2
          - id: page_nav
            region: footer
            kind: pageNavigator
            purpose: "Move between the four pages."
            field_bindings: "report pages"
            slot: 2
            of: 2
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: hero, pct_of_content: 21 }
          balance_rationale: "Analytical density: two charts and two tables at comparable size (21% / 15% each) so the ranking, the rule split, the proposals and the records stay readable together; the wider left column holds the group-level views the reviewer works from."
    - name: "Every number checked against the go-live integrity report"
      display_name: "Reconciliation"
      role: detail
      archetype: Operational
      layout_variant: C
      variant_rationale: "The answer-key check is an exception queue: the reviewer clears FAIL and NEW results first, so the queue is the working surface (variant C, Incident-First)."
      navigation:
        - element: page_navigator
          action: PageNavigation
          target: "Processed items, Exceptions & triage, Reconciliation, Run audit"
          label: "Page names as tabs"
      page_background: "#F1F5F9"
      layout_summary: "Title with three slicers; status strip of six cards; full-width answer-key queue worst first; checks by module and status beside the control totals go-live vs this take; footer."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header:  [1, 1, 8, 2]
            filters: [8, 1, 13, 2]
            status:  [1, 2, 13, 4]
            queue:   [1, 4, 13, 9]
            modules: [1, 9, 7, 12]
            money:   [7, 9, 13, 12]
            footer:  [1, 12, 13, 13]
        placements:
          - id: page_title
            region: header
            kind: textbox
            text: "Every number checked against the go-live integrity report"
            purpose: "State what the page proves."
          - id: take_slicer
            region: filters
            kind: slicer
            field_bindings: "Take[Take Id]"
            slicer_type: dropdown
            single_select: true
            sync_group: take
            slot: 1
            of: 3
          - id: module_slicer
            region: filters
            kind: slicer
            field_bindings: "Module[Module Name]"
            slicer_type: dropdown
            sync_group: module
            slot: 2
            of: 3
          - id: status_slicer
            region: filters
            kind: slicer
            field_bindings: "'Answer Key'[Status]"
            slicer_type: dropdown
            slot: 3
            of: 3
          - id: card_pass
            region: status
            kind: cardVisual
            purpose: "How many checks match go-live exactly?"
            field_bindings: { value: "'Answer Key'[Checks Passed]", reference_label: "'Answer Key'[Checks Context]" }
            insight_basis: "Share of all checks."
            color_strategy: measure_match
            slot: 1
            of: 6
          - id: card_allowed
            region: status
            kind: cardVisual
            purpose: "How many differences are explained and approved?"
            field_bindings: { value: "'Answer Key'[Checks Allowed]" }
            label: "Allowed (explained, with approver)"
            color_strategy: measure_match
            slot: 2
            of: 6
          - id: card_reviewed
            region: status
            kind: cardVisual
            purpose: "How many rules outside the key were reviewed with evidence?"
            field_bindings: { value: "'Answer Key'[Checks Reviewed]" }
            label: "Reviewed (not in the key)"
            color_strategy: measure_match
            slot: 3
            of: 6
          - id: card_new
            region: status
            kind: cardVisual
            purpose: "How many rules outside the key still need review?"
            field_bindings: { value: "'Answer Key'[Checks New]" }
            label: "New (needs review)"
            color_strategy: measure_match
            slot: 4
            of: 6
          - id: card_failed
            region: status
            kind: cardVisual
            purpose: "How many checks fail?"
            field_bindings: { value: "'Answer Key'[Checks Failed]" }
            label: "Failed"
            color_strategy: measure_match
            slot: 5
            of: 6
          - id: card_result
            region: status
            kind: cardVisual
            purpose: "Is the go-live outcome reproduced?"
            field_bindings: { value: "'Answer Key'[Answer Key Result]", accent_color: "'Answer Key'[Answer Key Color]" }
            insight_basis: "Composite status word with a status-coloured accent bar; the counts sit in the five cards beside it."
            color_strategy: semantic
            slot: 6
            of: 6
          - id: answer_key_queue
            region: queue
            kind: tableEx
            purpose: "Which checks differ from go-live, why, and who approved it?"
            field_bindings: ["'Answer Key'[Status]", "Module[Module Name]", "'Answer Key'[Metric Label]", "'Answer Key'[Expected]", "'Answer Key'[Actual]", "'Answer Key'[Difference]", "'Answer Key'[Reason]", "'Answer Key'[Approved By]"]
            sort_policy: category_asc
            sort_note: "Status sorts by Status Order (FAIL, NEW, ALLOWED, REVIEWED, PASS), then module load order."
            color_strategy: semantic
            formatting_note: "Status icon + text per semantic_colors.status; Reason wraps; numbers right-aligned."
            title: "Answer-key check, worst first"
          - id: checks_by_module
            region: modules
            kind: columnChart
            purpose: "Which modules carry explained differences, and does any module fail?"
            field_bindings: { Category: "Module[Module Name]", Y: "'Answer Key'[Checks]", Legend: "'Answer Key'[Status]" }
            stacking: stacked
            sort_policy: category_asc
            color_strategy: semantic
            title: "Checks by module and status"
          - id: control_totals_pair
            region: money
            kind: clusteredBarChart
            purpose: "Does the money that loads match go-live, type by type?"
            field_bindings: { Category: "'Answer Key'[Metric Label]", Y: ["'Answer Key'[Go-live Value]", "'Answer Key'[This Take Value]"] }
            visual_filter: "'Answer Key'[Metric] starts with 'control_totals.'"
            sort_policy: value_desc
            comparison_basis: "Go-live integrity report control totals."
            color_strategy: measure_match
            title: "Control totals: go-live vs this take"
          - id: freshness_card
            region: footer
            kind: cardVisual
            purpose: "How fresh is this view?"
            field_bindings: { value: "Take[Last Published]" }
            color_strategy: none
            label: "Last published (UTC)"
            slot: 1
            of: 2
          - id: page_nav
            region: footer
            kind: pageNavigator
            purpose: "Move between the four pages."
            field_bindings: "report pages"
            slot: 2
            of: 2
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: queue, pct_of_content: 45 }
          balance_rationale: "Variant C makes the queue the hero (45%): it is the working surface and needs room for reasons and approvers; the two supporting charts keep 6 x 3 cells each, above the 3 x 3 floor."
    - name: "Run audit: every step, the report clean-up and every AI call"
      display_name: "Run audit"
      role: detail
      archetype: Operational
      layout_variant: A
      variant_rationale: "Desk-side review of four health signals (SQL steps, PII gate, reshape checks, AI usage) needing both status tiles and detail tables (variant A, 4-Up Status); the Reconciliation page uses variant C."
      navigation:
        - element: page_navigator
          action: PageNavigation
          target: "Processed items, Exceptions & triage, Reconciliation, Run audit"
          label: "Page names as tabs"
      page_background: "#F1F5F9"
      layout_summary: "Title with the take slicer; four health tiles; step durations beside reshape rows kept vs removed; run steps table beside the AI calls audit table; footer."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header:    [1, 1, 8, 2]
            filters:   [8, 1, 13, 2]
            tiles:     [1, 2, 13, 4]
            durations: [1, 4, 7, 8]
            reshape:   [7, 4, 13, 8]
            steps:     [1, 8, 7, 12]
            ai:        [7, 8, 13, 12]
            footer:    [1, 12, 13, 13]
        placements:
          - id: page_title
            region: header
            kind: textbox
            text: "Run audit: every step, the report clean-up and every AI call"
            purpose: "State what the page audits."
          - id: take_slicer
            region: filters
            kind: slicer
            field_bindings: "Take[Take Id]"
            slicer_type: dropdown
            single_select: true
            sync_group: take
            slot: 3
            of: 3
          - id: tile_steps
            region: tiles
            kind: cardVisual
            purpose: "Did every SQL step succeed?"
            field_bindings: { value: "'Run Steps'[Steps Failed]", reference_label: "'Run Steps'[Steps Context]", accent_color: "'Run Steps'[Steps Color]" }
            insight_basis: "Threshold: 0 is healthy (teal), anything else critical (red)."
            color_strategy: semantic
            slot: 1
            of: 4
          - id: tile_pii
            region: tiles
            kind: cardVisual
            purpose: "Did the PII gate have to stop any AI call?"
            field_bindings: { value: "'AI Calls'[Calls Blocked by PII Gate]", reference_label: "'AI Calls'[PII Context]", accent_color: "'AI Calls'[PII Gate Color]" }
            insight_basis: "Threshold: 0 blocked is healthy; a block means the context builder needs a fix."
            color_strategy: semantic
            slot: 2
            of: 4
          - id: tile_reshape
            region: tiles
            kind: cardVisual
            purpose: "Did any filled-down value disagree with what the report printed?"
            field_bindings: { value: "'Step Metrics'[Fill-down Mismatches]", reference_label: "'Step Metrics'[Fill-down Context]" }
            insight_basis: "Threshold: 0 mismatches; context shows the layout rows removed."
            color_strategy: measure_match
            slot: 3
            of: 4
          - id: tile_tokens
            region: tiles
            kind: cardVisual
            purpose: "What did the AI cost in tokens and time?"
            field_bindings: { value: "'AI Calls'[Input Tokens]", reference_label: "'AI Calls'[Token Context]" }
            insight_basis: "Output tokens and average latency beside input tokens."
            color_strategy: measure_match
            slot: 4
            of: 4
          - id: step_durations
            region: durations
            kind: barChart
            purpose: "Which SQL build and validation steps take the longest?"
            field_bindings: { Category: "'Run Steps'[Step Name]", Y: "'Run Steps'[Step Seconds]" }
            sort_policy: value_desc
            top_n: 10
            color_strategy: measure_match
            title: "Top 10 SQL steps by duration (seconds)"
          - id: reshape_rows
            region: reshape
            kind: clusteredBarChart
            purpose: "How much printed-report layout did the reshape strip from each extract?"
            field_bindings: { Category: "'Step Metrics'[Item]", Y: ["'Step Metrics'[Rows Kept]", "'Step Metrics'[Artifacts Removed]"] }
            sort_policy: value_desc
            color_strategy: measure_match
            title: "Reshape: data rows kept vs layout rows removed"
          - id: steps_table
            region: steps
            kind: tableEx
            purpose: "What did each step do, and did it succeed?"
            field_bindings: ["'Run Steps'[Step Name]", "'Run Steps'[Status]", "'Run Steps'[Step Rows]", "'Run Steps'[Step Seconds]", "'Run Steps'[Started At]"]
            sort_policy: category_asc
            sort_note: "Started At ascending (execution order)."
            color_strategy: semantic
            title: "Run steps"
          - id: ai_calls_table
            region: ai
            kind: tableEx
            purpose: "What did each AI call send, where, and did it pass the PII gate?"
            field_bindings: ["'AI Calls'[Call Id]", "'AI Calls'[Agent]", "'AI Calls'[Deployment]", "'AI Calls'[Region]", "'AI Calls'[PII Check]", "'AI Calls'[Status]", "'AI Calls'[Items Sent]", "'AI Calls'[Input Tokens]", "'AI Calls'[Output Tokens]", "'AI Calls'[Avg Latency (s)]", "'AI Calls'[Created At]"]
            sort_policy: category_asc
            sort_note: "Created At descending (latest first)."
            color_strategy: semantic
            title: "AI calls (metadata only)"
          - id: freshness_card
            region: footer
            kind: cardVisual
            purpose: "How fresh is this view?"
            field_bindings: { value: "Take[Last Published]" }
            color_strategy: none
            label: "Last published (UTC)"
            slot: 1
            of: 2
          - id: page_nav
            region: footer
            kind: pageNavigator
            purpose: "Move between the four pages."
            field_bindings: "report pages"
            slot: 2
            of: 2
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: tiles, pct_of_content: 18 }
          balance_rationale: "The tile strip and four equal quadrants (18% each), one per health signal pair (timing, reshape, steps, AI), so no signal hides another."
  interaction_pattern:
    drill_targets: []
    cross_filter_rules:
      - "Processed items: outcome_by_module -> integrity_table Highlight; KPI cards Filter."
      - "Exceptions & triage: top_groups -> triage_table and fix_list Filter; triage_table -> fix_list Filter; owner_slicer -> rule_split None (Rule Issues has no owner)."
      - "Reconciliation: checks_by_module -> answer_key_queue Filter; status cards None."
      - "Run audit: default Highlight."
    sync_slicers:
      take: ["Processed items", "Exceptions & triage", "Reconciliation", "Run audit"]
      module: ["Exceptions & triage", "Reconciliation"]
  accessibility:
    alt_text_strategy: "Headline + finding per visual (for example: 'Integrity table: 9 modules; 10,443 failed records, 382 actionable'); DAX-driven alt text where the finding depends on filters; cards: measure + reference label."
    contrast_notes: "Measured WCAG ratios on the white cards: #0F766E 5.47, #64748B 4.76, #B45309 5.02, #2563EB 5.17, #DC2626 4.83, #0E7490 5.36, #4F46E5 6.29, #475569 7.58, #7C3AED 5.70, all AA for text. On the #F1F5F9 page, #64748B (4.34) and #DC2626 (4.41) fall below 4.5:1, so coloured text sits only on white cards; text on the page itself is #334155 (9.45) or #0F172A (16.3). FAIL red vs NEW amber can merge under deuteranopia, so status is always text plus icon."
  theme:
    base: "references/design/assets/base.json adapted (keep textbox, cardVisual, table and visual-header safeguards); name 'Cogsdale Conversion - Corporate Cool'; dataColors starting #0F766E, #64748B, #B45309, #2563EB, #DC2626, #0E7490, #4F46E5, #475569"
    user_overrides: "none (no brand guidelines provided)"
```

## Implementation notes

- Model changes: add the new measures listed above to the TMDL (tabs), redeploy with `powerbi/deploy_model.py`, validate each with DAX; add `MetricLabel` to `rpt_answer_key` in `convplat/publish.py` and the TMDL, then re-run the Publish step.
- PBIR/report authoring: scaffold `conversion-platform/powerbi/ConversionRun.Report` bound byConnection to the deployed "Conversion Run" model; theme from base.json; generate pages from this contract with the `powerbi-report-author` CLI as the schema source; validate each batch.
- Validation: CLI validation per batch; all JSON parses; page and visual counts match this contract.
- Desktop screenshot verification: Desktop preview needs sign-in to the MngEnv tenant; if that isn't available, preview in the service after publish and screenshot there.
- Publishing boundary: publish to "Cogsdale Conversion Prototype" only, rebinding byConnection to the "Conversion Run" model; every Fabric call carries `x-ms-fabric-skill: powerbi-report-cli`.
- Risks: Direct Lake framing must pick up the new columns (re-run Publish before the model refresh); the Take slicer must default to the published take; Desktop on Arm64 runs under emulation (slower screenshots).
- Refinements after screenshot review (Oct 7): KPI context lines are measure-bound card titles (a card reference label bound to a measure rendered blank); the module-level integrity table is a matrix (pivotTable) and record lists are tables of columns only, per the authoring pitfalls; tables use style preset None so the object-level formatting is the only styling; cards show exact numbers; the three ranked bar charts show the top 10 so every bar is readable without scrolling; the triage table drops the Module column (the group label starts with the module code); the footer freshness card shows one text measure (Take[Freshness]).
- Second review (Oct 7): faint table text in the headless captures turned out to be capture timing, not styling (the preview captures on the rendered event while tables are still fading in; a settled capture of the same page shows the exact ink and text colours). The triage, fix-list, answer-key and AI-call tables pin their column widths and wrap long text (group labels, reasons, client messages, approvals), so nothing hides off to the right. "Checks by module and status" is a stacked column chart so all nine modules show without scrolling: horizontal bars need about 20 px per module, and that region has room for six. The records-to-fix context line splits the number into failed records plus warnings (3,706 + 249 on the go-live replay), so it reconciles with Actionable failures on the first page.
- Advisory design warnings (accepted, not blocking): Reconciliation shows 7 cards (6 status cards plus the footer freshness card), one over the 6-card guideline, because the status board needs one card per answer-key status; Exceptions & triage and Reconciliation have 14-15 objects including slicers, title and navigator (9-10 data visuals), within the analytical density budget.

## Proposed extension: full-process pages (awaiting the report owner's approval; not built)

The model now carries the full process: 9 more tables and 31 measures, deployed and DAX-checked. The four approved pages
stay exactly as they are. The three pages below are proposed only. Building them, and overwriting the published report,
needs an explicit go-ahead.

5. Take control: "Is this take safe to load, and where is it waiting?"
   - Archetype: Operational Monitor, variant A (4-Up Status)
   - Visuals:
     - a gate strip of six cards (status word plus icon; auto-approved shown as such, never as a person);
     - chain of custody (`Files Landed`, `Landed MB`, file table with SHA-256);
     - drift findings, blocking first;
     - cleansing proposals by rule (high, low, pending);
     - the CSM load by module (expected, loaded, failed, variance) with the control-total variance;
     - runbook progress by block (done, simulated, eliminated, waiting).
   - Fields: Gates, Landing Files, Drift Findings, Cleansing, CSM Load and Runbook measures and columns.
   - Interaction: Take slicer (synced). Option, later: translytical Approve and Reject buttons per gate, using a Fabric User Data Function that calls `run.usp_DecideGate` with the signed-in user (DataFunction buttons).
6. Client validation: "Do the converted accounts look right?"
   - Archetype: Analytical Canvas, variant B
   - Visuals:
     - `Sample Accounts`, `Field Differences` and `Field Match %` cards;
     - a stratum slicer;
     - the side-by-side table (account, field, legacy value, converted value), differences flagged with text plus icon.
   - Audience: the client's validators. Row-level security by client in production, because the table holds record values.
7. Take over take: "What changed since the last take?"
   - Archetype: Analytical Canvas, variant B
   - Visuals:
     - `Groups New`, `Groups Resolved`, `Groups Grown` and `Groups Shrunk` cards;
     - the issue-group table in status order (new, grown, shrunk, resolved);
     - records fixed since the last take, newly flagged, still flagged;
     - the drift warnings that explain new groups (for example a new service code).
   - Take slicer shows Take Date and labels simulated takes.
