/* =====================================================================
   10_run.sql: run log, issues and step metrics.
   Platform tables (not GP tables), so NULL is allowed where a value doesn't exist yet.
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('run.RunLog') IS NULL
CREATE TABLE run.RunLog (
    RunLogId     bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_RunLog PRIMARY KEY,
    ClientId     varchar(20)    NOT NULL,
    TakeId       varchar(20)    NOT NULL,
    StepName     varchar(128)   NOT NULL,
    StartedAt    datetime2(3)   NOT NULL CONSTRAINT DF_RunLog_StartedAt DEFAULT SYSUTCDATETIME(),
    EndedAt      datetime2(3)   NULL,
    RowsAffected int            NULL,
    Status       varchar(20)    NOT NULL CONSTRAINT DF_RunLog_Status DEFAULT 'Running',
    Message      nvarchar(4000) NULL
);
IF OBJECT_ID('run.Issue') IS NULL
CREATE TABLE run.Issue (
    IssueId    bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_Issue PRIMARY KEY,
    ClientId   varchar(20)   NOT NULL,
    TakeId     varchar(20)   NOT NULL,
    Module     varchar(30)   NOT NULL,              -- e.g. UM00300
    RowId      bigint        NOT NULL,              -- gold row the issue belongs to
    RecordKey  nvarchar(200) NOT NULL,              -- natural key, stable across takes (e.g. account|slot|service)
    RuleId     varchar(60)   NOT NULL,              -- e.g. CONN_INVALID_SERVICE_TYPE
    Severity   char(1)       NOT NULL CONSTRAINT CK_Issue_Severity CHECK (Severity IN ('E','W')),
    IsExpected bit           NOT NULL CONSTRAINT DF_Issue_IsExpected DEFAULT 0,  -- excluded by design (crosswalk / override)
    Detail     nvarchar(400) NOT NULL CONSTRAINT DF_Issue_Detail DEFAULT N'',
    CreatedAt  datetime2(3)  NOT NULL CONSTRAINT DF_Issue_CreatedAt DEFAULT SYSUTCDATETIME()
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Issue_Take' AND object_id = OBJECT_ID('run.Issue'))
CREATE INDEX IX_Issue_Take ON run.Issue (ClientId, TakeId, Module, RuleId) INCLUDE (RowId, Severity, IsExpected);
IF OBJECT_ID('run.StepMetric') IS NULL
CREATE TABLE run.StepMetric (
    StepMetricId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_StepMetric PRIMARY KEY,
    ClientId     varchar(20)    NOT NULL,
    TakeId       varchar(20)    NOT NULL,
    Step         varchar(60)    NOT NULL,           -- reshape, slv-load, gold, rules, ...
    Item         varchar(128)   NOT NULL,           -- e.g. services-report
    Metric       varchar(60)    NOT NULL,           -- e.g. rows_kept, artifacts.page_break
    Value        decimal(19,5)  NOT NULL,
    Note         nvarchar(400)  NOT NULL CONSTRAINT DF_StepMetric_Note DEFAULT N'',
    At           datetime2(3)   NOT NULL CONSTRAINT DF_StepMetric_At DEFAULT SYSUTCDATETIME()
);
IF OBJECT_ID('run.AnswerKeyCheck') IS NULL
CREATE TABLE run.AnswerKeyCheck (                   -- golden-master outcome check (golden-master-test skill)
    ClientId    varchar(20)    NOT NULL,
    TakeId      varchar(20)    NOT NULL,
    Module      varchar(30)    NOT NULL,
    Metric      varchar(100)   NOT NULL,
    Expected    nvarchar(40)   NOT NULL,
    Actual      nvarchar(40)   NOT NULL,
    Status      varchar(10)    NOT NULL,            -- PASS / ALLOWED / FAIL / NEW
    Reason      nvarchar(1000) NOT NULL CONSTRAINT DF_AKC_Reason DEFAULT N'',
    ApprovedBy  nvarchar(200)  NOT NULL CONSTRAINT DF_AKC_ApprovedBy DEFAULT N'',
    CheckedAt   datetime2(3)   NOT NULL CONSTRAINT DF_AKC_CheckedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_AnswerKeyCheck PRIMARY KEY (ClientId, TakeId, Module, Metric)
);
GO

CREATE OR ALTER PROCEDURE run.usp_LogStart
    @ClientId varchar(20), @TakeId varchar(20), @StepName varchar(128), @RunLogId bigint OUTPUT
AS
/* Purpose: open a run-log row for one step. Pair with run.usp_LogEnd. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    INSERT run.RunLog (ClientId, TakeId, StepName) VALUES (@ClientId, @TakeId, @StepName);
    SET @RunLogId = SCOPE_IDENTITY();
END;
GO

CREATE OR ALTER PROCEDURE run.usp_LogEnd
    @RunLogId bigint, @RowsAffected int = NULL, @Status varchar(20) = 'Succeeded', @Message nvarchar(4000) = NULL
AS
/* Purpose: close a run-log row with rows affected and status (Succeeded / Failed). */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    UPDATE run.RunLog SET EndedAt = SYSUTCDATETIME(), RowsAffected = @RowsAffected, Status = @Status, Message = @Message
    WHERE RunLogId = @RunLogId;
END;
GO
