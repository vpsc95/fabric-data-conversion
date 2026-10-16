/* =====================================================================
   85_triage.sql: triage of validation issues, with a person in the loop (gate 3).

   - recon.v_IssueRecordLive one row per gold record that has issues: its rule set, severity, whether every
                             issue is expected by design, and code-level features (service, rate, meter state,
                             date shape, account status). The account is in its own column for the fix list;
                             it is never part of a feature or signature. Stored per take in run.IssueRecord by
                             recon.usp_BuildIssueRecords (grouping over the live view directly plans badly).
   - recon.v_TriageContext   the ONLY view the triage agent reads: issue groups (same module, rule set and
                             features) with record counts. Codes and counts only - no names, addresses,
                             account numbers or meter numbers - and no answer (RuleClass) to copy from.
   - run.TriageProposal      what the agent proposed per group: label, owner, category, wording, confidence.
   - meta.TriageDecision     what a person decided (seeded from clients/<client>/triage/decisions.yaml).
   - rules.usp_ApplyTriageDecisions  an approved "expected" decision marks that group's issues expected on
                             every take, so it stops reaching the agent: rules handle repetition, agents
                             handle what's new.
   - run.AiCall              audit of every model call (prompt hash and size, PII check, tokens; no content).
   Fabric-only reporting code: uses TRANSLATE and STRING_AGG (SQL Server 2017+), never runs as Mode B pushdown.
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('recon.v_IssueRecord') IS NOT NULL DROP VIEW recon.v_IssueRecord;   -- renamed to recon.v_IssueRecordLive
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Issue_Row' AND object_id = OBJECT_ID('run.Issue'))
    CREATE INDEX IX_Issue_Row ON run.Issue (ClientId, TakeId, Module, RowId) INCLUDE (RuleId, Severity, IsExpected);
IF OBJECT_ID('run.AiCall') IS NULL
CREATE TABLE run.AiCall (
    CallId       bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_AiCall PRIMARY KEY,
    ClientId     varchar(20)    NOT NULL,
    TakeId       varchar(20)    NOT NULL,
    Agent        varchar(30)    NOT NULL,
    Endpoint     varchar(200)   NOT NULL,
    Deployment   varchar(60)    NOT NULL,
    Region       varchar(40)    NOT NULL,
    PromptSha256 char(64)       NOT NULL,
    PromptChars  int            NOT NULL,
    ItemsSent    int            NOT NULL,
    PiiCheck     varchar(20)    NOT NULL,           -- passed / blocked
    Status       varchar(20)    NOT NULL,           -- succeeded / blocked / failed
    InputTokens  int            NULL,
    OutputTokens int            NULL,
    LatencyMs    int            NULL,
    Message      nvarchar(2000) NOT NULL CONSTRAINT DF_AiCall_Message DEFAULT N'',
    CreatedAt    datetime2(3)   NOT NULL CONSTRAINT DF_AiCall_CreatedAt DEFAULT SYSUTCDATETIME()
);
-- proposals are regenerated every run, so a table with an older column set is simply recreated
IF OBJECT_ID('run.TriageProposal') IS NOT NULL AND COL_LENGTH('run.TriageProposal', 'RootCause') IS NULL DROP TABLE run.TriageProposal;
IF OBJECT_ID('run.TriageProposal') IS NULL
CREATE TABLE run.TriageProposal (
    ClientId      varchar(20)    NOT NULL,
    TakeId        varchar(20)    NOT NULL,
    GroupKey      char(16)       NOT NULL,
    Module        varchar(30)    NOT NULL,
    RuleSet       varchar(400)   NOT NULL,
    Features      nvarchar(400)  NOT NULL,
    Severity      char(1)        NOT NULL,
    Records       int            NOT NULL,           -- from SQL, never from the model
    RuleClass     varchar(12)    NOT NULL,           -- expected / actionable / mixed, from the approved rules
    AgentLabel    varchar(12)    NOT NULL,           -- expected / actionable / investigate
    Owner         varchar(12)    NOT NULL,           -- client / cogsdale / none
    Category      varchar(24)    NOT NULL,           -- expected_by_design / fix_in_source / fix_in_mapping / fix_in_setup / needs_decision
    Title         nvarchar(200)  NOT NULL,
    Action        nvarchar(1000) NOT NULL,
    ClientMessage nvarchar(1000) NOT NULL,
    Rationale     nvarchar(1000) NOT NULL,
    Confidence    decimal(4,3)   NOT NULL,
    CallId        bigint         NOT NULL,
    Observation   nvarchar(500)  NOT NULL CONSTRAINT DF_TriageProposal_Observation DEFAULT N'',
    RootCause     varchar(40)    NOT NULL CONSTRAINT DF_TriageProposal_RootCause DEFAULT 'unclear',
    ExcludedBy    varchar(60)    NOT NULL CONSTRAINT DF_TriageProposal_ExcludedBy DEFAULT '',   -- approved exclusion the agent cited
    CreatedAt     datetime2(3)   NOT NULL CONSTRAINT DF_TriageProposal_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_TriageProposal PRIMARY KEY (ClientId, TakeId, GroupKey)
);
IF OBJECT_ID('run.IssueRecord') IS NULL
CREATE TABLE run.IssueRecord (
    ClientId    varchar(20)    NOT NULL,
    TakeId      varchar(20)    NOT NULL,
    Module      varchar(30)    NOT NULL,
    RowId       bigint         NOT NULL,
    Account     nvarchar(30)   NULL,                -- for the fix list only; never part of the signature
    Severity    char(1)        NOT NULL,
    AllExpected bit            NOT NULL,
    RuleSet     varchar(400)   NOT NULL,
    Features    nvarchar(400)  NOT NULL,
    Messages    nvarchar(2000) NOT NULL,
    GroupKey    char(16)       NOT NULL,
    CONSTRAINT PK_IssueRecord PRIMARY KEY (ClientId, TakeId, Module, RowId)
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_IssueRecord_Group' AND object_id = OBJECT_ID('run.IssueRecord'))
    CREATE INDEX IX_IssueRecord_Group ON run.IssueRecord (ClientId, TakeId, GroupKey) INCLUDE (Severity, AllExpected);
IF OBJECT_ID('meta.TriageDecision') IS NULL
CREATE TABLE meta.TriageDecision (
    ClientId   varchar(20)    NOT NULL,
    GroupKey   char(16)       NOT NULL,
    Module     varchar(30)    NOT NULL,
    Decision   varchar(12)    NOT NULL,              -- approved (as proposed) / changed (person's label) / rejected
    Label      varchar(12)    NOT NULL,              -- the label that applies: expected / actionable / investigate
    Owner      varchar(12)    NOT NULL,
    Category   varchar(24)    NOT NULL,
    Note       nvarchar(1000) NOT NULL CONSTRAINT DF_TriageDecision_Note DEFAULT N'',
    DecidedBy  nvarchar(200)  NOT NULL,
    DecidedOn  date           NOT NULL,
    CONSTRAINT PK_TriageDecision PRIMARY KEY (ClientId, GroupKey)
);
GO

CREATE OR ALTER VIEW recon.v_IssueRecordLive
AS
/* Purpose: computes one row per gold record that has issues, with its signature (module + rule set + features).
   Read it only through recon.usp_BuildIssueRecords, which stores the result in run.IssueRecord (fast to query).
   Severity is E when any issue is an error ('E' sorts before 'W'). AllExpected = 1 when every issue on
   the record is expected by design. Features hold code values only. */
WITH r AS (
    SELECT i.ClientId, i.TakeId, i.Module, i.RowId,
           MIN(i.Severity) AS Severity,
           MIN(CAST(i.IsExpected AS int)) AS AllExpected,
           -- lint-ignore: W112 (Fabric-only reporting code; see the header)
           CAST(STRING_AGG(CAST(i.RuleId AS varchar(max)), '+') WITHIN GROUP (ORDER BY i.RuleId) AS varchar(400)) AS RuleSet
    FROM run.Issue i
    GROUP BY i.ClientId, i.TakeId, i.Module, i.RowId
), f AS (
    SELECT r.ClientId, r.TakeId, r.Module, r.RowId, r.Severity, r.AllExpected, r.RuleSet, c.LegacyAcctNo AS Account, c.message AS Messages,
           CONCAT('service=', c.Legacy_Service, '; serviceType=', c.ServiceType, '; rate=', NULLIF(c.CTAR11, ''),
                  '; tariff=', NULLIF(c.TariffID, ''),
                  -- the printed report merges TABLE and METER for the second service: keep only the rate-table code,
                  -- and say (yes/no) whether a meter number or PULLED sits in that column - never the number itself
                  '; rateTable=', NULLIF(CASE WHEN c.flat_rate LIKE '%[0-9][0-9][0-9][0-9][0-9]%' OR c.flat_rate LIKE '% PULLED'
                                              THEN LEFT(c.flat_rate, CHARINDEX(' ', c.flat_rate + ' ') - 1) ELSE c.flat_rate END, ''),
                  '; meterInRateTableColumn=', CASE WHEN c.flat_rate LIKE '%[0-9][0-9][0-9][0-9][0-9]%' THEN 'yes (a number)'
                                                    WHEN c.flat_rate LIKE '% PULLED' THEN 'yes (PULLED)' ELSE 'no' END,
                  '; slot=', c.ServiceSlot, '; meter=',
                  CASE WHEN c.EquipmentID IS NULL THEN 'none (sewer at a location without a water meter)'
                       WHEN c.EquipmentID = '' AND c.flat_rate LIKE '%[0-9][0-9][0-9][0-9][0-9]%'
                            THEN 'blank on the connection, although the extract has a meter number for this service in the rate-table column'
                       WHEN c.EquipmentID = '' AND c.flat_rate LIKE '% PULLED' THEN 'blank; the extract marks this meter PULLED in the rate-table column'
                       WHEN c.EquipmentID = '' AND c.ServiceType LIKE 'SWR%' AND c.flat_rate IN ('COM', 'FLT')
                            THEN 'blank: the conversion deliberately does not copy the water meter to flat-rate (COM/FLT) sewer'
                       WHEN c.EquipmentID = '' THEN 'blank'
                       WHEN EXISTS (SELECT 1 FROM gold.UM_Equipment e WHERE e.ClientId = c.ClientId AND e.TakeId = c.TakeId
                                    AND e.EquipmentID = c.EquipmentID AND e.isvalid <> 0) THEN 'in equipment'
                       WHEN EXISTS (SELECT 1 FROM gold.UM_Equipment e WHERE e.ClientId = c.ClientId AND e.TakeId = c.TakeId
                                    AND e.EquipmentID = c.EquipmentID) THEN 'in equipment but failed'
                       ELSE 'not in equipment (not in the AMI meter export)' END) AS Features
    FROM r JOIN gold.UM_Connection c ON r.Module = 'UM00300' AND c.RowId = r.RowId
    UNION ALL
    SELECT r.ClientId, r.TakeId, r.Module, r.RowId, r.Severity, r.AllExpected, r.RuleSet, h.LegacyAcctNo, h.message,
           CONCAT('readDate=', CASE WHEN h.ReadingDate = '' THEN 'blank' ELSE TRANSLATE(h.ReadingDate, '0123456789', '9999999999') END,
                  '; accountStatus=', ISNULL(cu.New_Existing, 'not in CUSTOMERS extract'),
                  '; customer=', CASE WHEN h.CustomerID IS NULL THEN 'none' ELSE 'known' END,
                  '; location=', CASE WHEN h.LocationID IS NULL THEN 'none' WHEN h.LocationID = '0' THEN 'not assigned' ELSE 'known' END,
                  '; meterSuffix=', CASE WHEN h.EquipmentID LIKE '%[A-Za-z]' THEN RIGHT(h.EquipmentID, 1) ELSE 'digits only' END,
                  '; meterInEquipment=', CASE WHEN EXISTS (SELECT 1 FROM gold.UM_Equipment e WHERE e.ClientId = h.ClientId
                                              AND e.TakeId = h.TakeId AND e.EquipmentID = h.EquipmentID AND e.isvalid <> 0) THEN 'yes' ELSE 'no' END)
    FROM r JOIN gold.UM_HistMR h ON r.Module = 'UM30300' AND h.RowId = r.RowId
    OUTER APPLY (SELECT TOP (1) c.New_Existing FROM gold.UM_Customer c
                 WHERE c.ClientId = h.ClientId AND c.TakeId = h.TakeId AND c.LegacyAcctNo = h.LegacyAcctNo) cu
    UNION ALL
    SELECT r.ClientId, r.TakeId, r.Module, r.RowId, r.Severity, r.AllExpected, r.RuleSet, b.LegacyAcctNo, b.message,
           CONCAT('accountStatus=', ISNULL(cu.New_Existing, 'not in CUSTOMERS extract'),
                  '; customer=', CASE WHEN b.CustomerID IS NULL THEN 'none' ELSE 'known' END,
                  '; location=', CASE WHEN b.LocationID IS NULL THEN 'none' WHEN b.LocationID = '0' THEN 'not assigned' ELSE 'known' END)
    FROM r JOIN gold.UM_BegBalance b ON r.Module = 'UM20400' AND b.RowId = r.RowId
    OUTER APPLY (SELECT TOP (1) c.New_Existing FROM gold.UM_Customer c
                 WHERE c.ClientId = b.ClientId AND c.TakeId = b.TakeId AND c.LegacyAcctNo = b.LegacyAcctNo) cu
    UNION ALL
    SELECT r.ClientId, r.TakeId, r.Module, r.RowId, r.Severity, r.AllExpected, r.RuleSet, d.LegacyAcctNo, d.message,
           CONCAT('accountStatus=', ISNULL(cu.New_Existing, 'not in CUSTOMERS extract'), '; depositType=', d.DepositID,
                  '; customer=', CASE WHEN d.CustomerID IS NULL THEN 'none' ELSE 'known' END,
                  '; location=', CASE WHEN d.LocationID IS NULL THEN 'none' WHEN d.LocationID = '0' THEN 'not assigned' ELSE 'known' END)
    FROM r JOIN gold.UM_Deposit d ON r.Module = 'UM01900' AND d.RowId = r.RowId
    OUTER APPLY (SELECT TOP (1) c.New_Existing FROM gold.UM_Customer c
                 WHERE c.ClientId = d.ClientId AND c.TakeId = d.TakeId AND c.LegacyAcctNo = d.LegacyAcctNo) cu
    UNION ALL
    SELECT r.ClientId, r.TakeId, r.Module, r.RowId, r.Severity, r.AllExpected, r.RuleSet, e.LegacyAcctNo, e.message,
           CONCAT('meterSize=', NULLIF(e.Diameter, ''), '; equipmentClass=', e.EquClassID)
    FROM r JOIN gold.UM_Equipment e ON r.Module = 'UM00400' AND e.RowId = r.RowId
    UNION ALL
    SELECT r.ClientId, r.TakeId, r.Module, r.RowId, r.Severity, r.AllExpected, r.RuleSet, c.LegacyAcctNo, c.message,
           CONCAT('driversLicenceState=', CASE LEN(LTRIM(RTRIM(s.DLST))) WHEN 0 THEN 'blank' WHEN 2 THEN '2-letter code'
                                               ELSE 'longer than 2 characters' END,
                  '; customerType=', CASE c.Individual WHEN 1 THEN 'person' ELSE 'business' END)
    FROM r JOIN gold.UM_Customer c ON r.Module IN ('UMRM0101', 'UMRM0111') AND c.RowId = r.RowId
    LEFT JOIN slv.Customers s ON s.TakeId = c.TakeId AND s.SourceRow = c.SourceRow
    UNION ALL
    SELECT r.ClientId, r.TakeId, r.Module, r.RowId, r.Severity, r.AllExpected, r.RuleSet, l.Legacy_Loc_ID, l.message,
           CONCAT('locationClass=', NULLIF(l.LocationClass, ''), '; billTo=', CASE WHEN l.CustomerID = 'VACANT' THEN 'vacant' ELSE 'customer' END)   -- pii-scan: ignore (code values, not personal data)
    FROM r JOIN gold.UM_Location l ON r.Module = 'UM00600' AND l.RowId = r.RowId
)
SELECT f.*, CONVERT(char(16), HASHBYTES('SHA2_256', CONCAT(f.Module, N'|', f.RuleSet, N'|', f.Features)), 2) AS GroupKey
FROM f;
GO

CREATE OR ALTER PROCEDURE recon.usp_BuildIssueRecords @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: store this take's issue records with their signatures (run.IssueRecord). Runs after the rules. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DELETE run.IssueRecord WHERE ClientId = @ClientId AND TakeId = @TakeId;
    INSERT run.IssueRecord (ClientId, TakeId, Module, RowId, Account, Severity, AllExpected, RuleSet, Features, Messages, GroupKey)
    SELECT ClientId, TakeId, Module, RowId, Account, Severity, AllExpected, RuleSet, Features, ISNULL(Messages, N''), GroupKey
    FROM recon.v_IssueRecordLive
    WHERE ClientId = @ClientId AND TakeId = @TakeId;
END;
GO

CREATE OR ALTER VIEW recon.v_IssueGroup
AS
/* Purpose: issue groups - records with the same module, rule set and features. RuleClass is what the
   approved rules say (expected / actionable / mixed); the agent never sees it. */
SELECT ClientId, TakeId, Module, GroupKey, RuleSet, Features,
       MIN(Severity) AS Severity, COUNT(*) AS Records,
       CASE WHEN MIN(CAST(AllExpected AS int)) = 1 THEN 'expected' WHEN MAX(CAST(AllExpected AS int)) = 0 THEN 'actionable' ELSE 'mixed' END AS RuleClass
FROM run.IssueRecord
GROUP BY ClientId, TakeId, Module, GroupKey, RuleSet, Features;
GO

CREATE OR ALTER VIEW recon.v_TriageContext
AS
/* Purpose: the approved context view for the triage agent. Codes and counts only. */
SELECT ClientId, TakeId, GroupKey, Module, RuleSet, Features, Severity, Records
FROM recon.v_IssueGroup;
GO

CREATE OR ALTER VIEW recon.v_Triage
AS
/* Purpose: each issue group with the agent's proposal and the person's decision.
   Authority: a person's decision wins; until then the approved rules decide (RuleClass), because an unreviewed
   AI proposal must not move records on or off the fix list. The agent's label is advisory: AgentVsRules flags
   proposals that disagree with the rules so a person reviews them first. A rejected proposal needs investigation. */
SELECT g.ClientId, g.TakeId, g.Module, g.GroupKey, g.RuleSet, g.Features, g.Severity, g.Records, g.RuleClass,
       p.AgentLabel, p.Owner AS ProposedOwner, p.Category AS ProposedCategory, p.Title, p.Action, p.ClientMessage,
       p.Rationale, p.Confidence, p.CallId, p.Observation, p.RootCause, p.ExcludedBy,
       CASE WHEN p.GroupKey IS NULL THEN 'not triaged'
            WHEN (p.AgentLabel = 'expected' AND g.RuleClass = 'expected') OR (p.AgentLabel <> 'expected' AND g.RuleClass <> 'expected') THEN 'agrees'
            ELSE 'disagrees' END AS AgentVsRules,
       CASE WHEN d.GroupKey IS NULL THEN CASE WHEN p.GroupKey IS NULL THEN 'not triaged' ELSE 'pending' END ELSE d.Decision END AS DecisionStatus,
       CASE WHEN d.Decision IN ('approved', 'changed') THEN d.Label WHEN d.Decision = 'rejected' THEN 'investigate'
            WHEN g.RuleClass = 'expected' THEN 'expected' ELSE 'actionable' END AS FinalLabel,
       CASE WHEN d.Decision IN ('approved', 'changed') THEN d.Owner WHEN g.RuleClass = 'expected' THEN 'none'
            WHEN p.Owner IN ('client', 'cogsdale') THEN p.Owner ELSE 'cogsdale' END AS FinalOwner,   -- pii-scan: ignore (code values, not personal data)
       CASE WHEN d.Decision IN ('approved', 'changed') THEN d.Category WHEN g.RuleClass = 'expected' THEN 'expected_by_design'
            WHEN p.Category IS NOT NULL AND p.Category <> 'expected_by_design' THEN p.Category ELSE 'needs_decision' END AS FinalCategory,
       d.Note AS DecisionNote, d.DecidedBy, d.DecidedOn
FROM recon.v_IssueGroup g
LEFT JOIN run.TriageProposal p ON p.ClientId = g.ClientId AND p.TakeId = g.TakeId AND p.GroupKey = g.GroupKey
LEFT JOIN meta.TriageDecision d ON d.ClientId = g.ClientId AND d.GroupKey = g.GroupKey;
GO

CREATE OR ALTER VIEW recon.v_FixList
AS
/* Purpose: every record that still needs action, with who fixes it and the wording for the client.
   Expected-by-design records are left out. This is data for the people fixing it; it never goes to a model. */
SELECT r.ClientId, r.TakeId, r.Module, r.Account, r.RowId, r.Severity, r.RuleSet, r.Messages, r.GroupKey,
       t.Title, t.ClientMessage, t.FinalLabel, t.FinalOwner, t.FinalCategory, t.DecisionStatus
FROM run.IssueRecord r
JOIN recon.v_Triage t ON t.ClientId = r.ClientId AND t.TakeId = r.TakeId AND t.GroupKey = r.GroupKey
WHERE t.FinalLabel <> 'expected';
GO

CREATE OR ALTER PROCEDURE rules.usp_ApplyTriageDecisions @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: turn approved "expected" triage decisions into exclusions for this take: every issue in such a
   group becomes expected, with who decided it and when. Runs at the end of rules.usp_Validate_All. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF NOT EXISTS (SELECT 1 FROM meta.TriageDecision WHERE ClientId = @ClientId AND Decision IN ('approved', 'changed') AND Label = 'expected')
        RETURN;
    UPDATE i SET IsExpected = 1,
                 Detail = LEFT(i.Detail + CASE WHEN LEN(i.Detail) > 0 THEN N'; ' ELSE N'' END
                               + N'expected by triage decision of ' + d.DecidedBy + N' on ' + CONVERT(nvarchar(10), d.DecidedOn, 23), 400)
    FROM run.Issue i
    JOIN run.IssueRecord r ON r.ClientId = i.ClientId AND r.TakeId = i.TakeId AND r.Module = i.Module AND r.RowId = i.RowId
    JOIN meta.TriageDecision d ON d.ClientId = r.ClientId AND d.GroupKey = r.GroupKey
    WHERE i.ClientId = @ClientId AND i.TakeId = @TakeId AND i.IsExpected = 0
      AND d.Decision IN ('approved', 'changed') AND d.Label = 'expected';

    UPDATE r SET AllExpected = x.AllExpected            -- keep the stored records in step with the issues
    FROM run.IssueRecord r
    JOIN (SELECT Module, RowId, CAST(MIN(CAST(IsExpected AS int)) AS bit) AS AllExpected FROM run.Issue
          WHERE ClientId = @ClientId AND TakeId = @TakeId GROUP BY Module, RowId) x ON x.Module = r.Module AND x.RowId = r.RowId
    WHERE r.ClientId = @ClientId AND r.TakeId = @TakeId AND r.AllExpected <> x.AllExpected;
END;
GO
