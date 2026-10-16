/* =====================================================================
   16_cleanse.sql: deterministic cleansing proposals and the low-confidence review queue.

   Purpose
   - Store proposed, deterministic fixes for messy customer and location fields without changing gold staging.
   - Keep analyst/client decisions for gate 2 (low-confidence fixes) and for promoted rules on later takes.
   - Summarize proposal counts by take, module and rule.

   Inputs
   - engine/convplat/cleanse.py writes rows to run.CleanseProposal from gold and silver take data.
   - run.usp_DecideCleanse records an approve/reject decision for one proposal or one rule.

   Outputs
   - run.CleanseProposal: proposal queue with before/after values, confidence, band and decision columns.
   - recon.v_CleanseSummary: counts for gate evidence and analyst review.

   Example
   - EXEC run.usp_DecideCleanse 'sample', 'go-live', 'approved', 'analyst', NULL, 'CLN_EMAIL_CASE', 'UMRM0101';
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('run.CleanseProposal') IS NULL
CREATE TABLE run.CleanseProposal (
    ProposalId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_CleanseProposal PRIMARY KEY,
    ClientId varchar(20) NOT NULL,
    TakeId varchar(20) NOT NULL,
    Module varchar(30) NOT NULL,
    RowId bigint NOT NULL,
    RecordKey nvarchar(200) NOT NULL,
    Field varchar(60) NOT NULL,
    RuleId varchar(80) NOT NULL,
    BeforeValue nvarchar(400) NOT NULL,
    AfterValue nvarchar(400) NOT NULL,
    Confidence decimal(3,2) NOT NULL,
    Band varchar(10) NOT NULL CONSTRAINT CK_CleanseProposal_Band CHECK (Band IN ('high', 'low')),
    Status varchar(30) NOT NULL CONSTRAINT DF_CleanseProposal_Status DEFAULT 'pending'
        CONSTRAINT CK_CleanseProposal_Status CHECK (Status IN ('pending', 'approved', 'rejected', 'auto_applied_next_take')),
    Reason nvarchar(400) NOT NULL,
    CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_CleanseProposal_CreatedAt DEFAULT SYSUTCDATETIME(),
    DecidedBy nvarchar(200) NULL,
    DecidedAt datetime2(3) NULL,
    Note nvarchar(1000) NULL
);
IF COL_LENGTH('run.CleanseProposal', 'ProposalId') IS NOT NULL
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('run.CleanseProposal') AND name = 'IX_CleanseProposal_Take')
        CREATE INDEX IX_CleanseProposal_Take ON run.CleanseProposal (ClientId, TakeId, Module, RuleId, Band, Status) INCLUDE (RowId, Field);
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('run.CleanseProposal') AND name = 'IX_CleanseProposal_Key')
        CREATE INDEX IX_CleanseProposal_Key ON run.CleanseProposal (ClientId, TakeId, Module, RowId, Field, RuleId, Status);
END;
GO

CREATE OR ALTER PROCEDURE run.usp_DecideCleanse
    @ClientId varchar(20),
    @TakeId varchar(20),
    @Decision varchar(30),
    @DecidedBy nvarchar(200),
    @ProposalId bigint = NULL,
    @RuleId varchar(80) = NULL,
    @Module varchar(30) = NULL,
    @Note nvarchar(1000) = NULL
AS
/* Purpose: approve or reject a single cleansing proposal, or every pending proposal for one rule.
   Inputs: client/take, decision, decider, and either @ProposalId or @RuleId (optionally scoped by @Module).
   Output: updated decision columns on run.CleanseProposal. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @Decision NOT IN ('approved', 'rejected', 'auto_applied_next_take')
        THROW 50010, 'run.usp_DecideCleanse: @Decision must be approved, rejected or auto_applied_next_take.', 1;
    IF NULLIF(LTRIM(RTRIM(@DecidedBy)), N'') IS NULL
        THROW 50011, 'run.usp_DecideCleanse: @DecidedBy is required.', 1;
    IF @ProposalId IS NULL AND NULLIF(@RuleId, '') IS NULL
        THROW 50012, 'run.usp_DecideCleanse: pass either @ProposalId or @RuleId.', 1;

    UPDATE run.CleanseProposal
       SET Status = @Decision,
           DecidedBy = @DecidedBy,
           DecidedAt = SYSUTCDATETIME(),
           Note = ISNULL(@Note, N'')
     WHERE ClientId = @ClientId
       AND TakeId = @TakeId
       AND Status = 'pending'
       AND (@ProposalId IS NULL OR ProposalId = @ProposalId)
       AND (@ProposalId IS NOT NULL OR RuleId = @RuleId)
       AND (@Module IS NULL OR Module = @Module);

    IF @@ROWCOUNT = 0
        THROW 50013, 'run.usp_DecideCleanse: no pending proposal matched the decision scope.', 1;
END;
GO

CREATE OR ALTER VIEW recon.v_CleanseSummary
AS
/* Purpose: gate 2 and workbench summary of deterministic cleansing proposals by rule and status. */
SELECT ClientId,
       TakeId,
       Module,
       RuleId,
       COUNT_BIG(*) AS Proposals,
       SUM(CASE WHEN Band = 'high' THEN 1 ELSE 0 END) AS High,
       SUM(CASE WHEN Band = 'low' THEN 1 ELSE 0 END) AS Low,
       SUM(CASE WHEN Status = 'approved' THEN 1 ELSE 0 END) AS Approved,
       SUM(CASE WHEN Status = 'rejected' THEN 1 ELSE 0 END) AS Rejected,
       SUM(CASE WHEN Status = 'pending' THEN 1 ELSE 0 END) AS Pending
FROM run.CleanseProposal
GROUP BY ClientId, TakeId, Module, RuleId;
GO
