/* =====================================================================
   15_meta.sql: rule metadata. Tailoring a client is a data change here, not a code edit.
   Seeded from rules/catalog.yaml (meta.RuleCatalog) and clients/<client>/rules/<name>.yaml (meta.RuleOverride).
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('meta.Client') IS NULL
CREATE TABLE meta.Client (
    ClientId       varchar(20)   NOT NULL CONSTRAINT PK_meta_Client PRIMARY KEY,
    Name           nvarchar(100) NOT NULL,
    ConversionDate date          NULL
);
IF OBJECT_ID('meta.RuleCatalog') IS NULL
CREATE TABLE meta.RuleCatalog (
    RuleId        varchar(60)    NOT NULL CONSTRAINT PK_meta_RuleCatalog PRIMARY KEY,
    Module        varchar(30)    NOT NULL,
    Severity      char(1)        NOT NULL,            -- E = record skipped at load, W = loads, goes on the fix list
    Enabled       bit            NOT NULL CONSTRAINT DF_meta_Rule_Enabled DEFAULT 1,
    LegacyText    nvarchar(400)  NOT NULL,            -- text reviewer's validation scripts wrote into [message]
    Description   nvarchar(800)  NOT NULL CONSTRAINT DF_meta_Rule_Description DEFAULT N'',
    LegacySource  nvarchar(200)  NOT NULL CONSTRAINT DF_meta_Rule_LegacySource DEFAULT N'',
    AnswerKeyRule varchar(60)    NULL,
    RuleKind      varchar(20)    NOT NULL CONSTRAINT DF_meta_Rule_Kind DEFAULT 'cross',  -- simple = single-table predicate run generically
    GoldTable     sysname        NULL,                -- gold table the rule flags
    ConditionSql  nvarchar(1000) NULL                 -- simple rules only: predicate on GoldTable (from rules/catalog.yaml)
);
-- seeded in full from the specs on every run, so a table with an older column set is simply recreated
IF OBJECT_ID('meta.RuleOverride') IS NOT NULL AND COL_LENGTH('meta.RuleOverride', 'AppliesTo') IS NULL DROP TABLE meta.RuleOverride;
IF OBJECT_ID('meta.RuleOverride') IS NULL
CREATE TABLE meta.RuleOverride (
    ClientId          varchar(20)   NOT NULL,
    RuleId            varchar(60)   NOT NULL,
    Enabled           bit           NULL,             -- NULL = keep the catalog value
    Severity          char(1)       NULL,
    ExpectedWhen      nvarchar(400) NULL,             -- the by-design exclusion's condition in SQL (applied in the rule)
    AppliesTo         nvarchar(400) NULL,             -- the same condition in plain English (people and the triage agent)
    Reason            nvarchar(400) NOT NULL,
    CONSTRAINT PK_meta_RuleOverride PRIMARY KEY (ClientId, RuleId)
);
IF OBJECT_ID('meta.LengthRule') IS NULL
CREATE TABLE meta.LengthRule (                      -- generic "too long" rules: one row per rule, one procedure for all
    RuleId      varchar(60) NOT NULL CONSTRAINT PK_meta_LengthRule PRIMARY KEY,
    GoldTable   sysname     NOT NULL,
    ColumnName  sysname     NOT NULL,
    MaxLength   int         NOT NULL
);
IF OBJECT_ID('meta.Allowance') IS NULL
CREATE TABLE meta.Allowance (                       -- differences from the answer key that are explained and approved
    ClientId    varchar(20)   NOT NULL,
    Module      varchar(30)   NOT NULL,
    Metric      varchar(100)  NOT NULL,             -- e.g. issues.ADDR_SMARTY_NO_MATCH
    Reason      nvarchar(800) NOT NULL,
    ApprovedBy  nvarchar(100) NOT NULL,
    CONSTRAINT PK_meta_Allowance PRIMARY KEY (ClientId, Module, Metric)
);
GO

CREATE OR ALTER VIEW meta.v_EffectiveRule
AS
/* Purpose: the rule settings a client actually runs with (catalog + client override). */
SELECT c.ClientId, r.RuleId, r.Module,
       COALESCE(o.Severity, r.Severity) AS Severity,
       CAST(COALESCE(o.Enabled, r.Enabled) AS bit) AS Enabled,
       r.LegacyText, o.ExpectedWhen, o.Reason AS OverrideReason
FROM meta.RuleCatalog r
CROSS JOIN meta.Client c
LEFT JOIN meta.RuleOverride o ON o.ClientId = c.ClientId AND o.RuleId = r.RuleId;
GO
