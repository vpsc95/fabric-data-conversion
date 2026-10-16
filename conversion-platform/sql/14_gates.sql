/* =====================================================================
   14_gates.sql: the six human gates of a take, as data.
   1 spec change (pull request) · 2 low-confidence fixes · 3 triage · 4 load go/no-go · 5 publish ·
   6 take acceptance (sign-off). The platform opens a gate with the evidence the approver needs; a person
   decides; every open and every decision is kept in run.GateEvent (who, when, what they saw, note).
   Gates 4 and 5 hold the pipeline until a decision; a demo run may auto-approve them, and says so.
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('run.Gate') IS NULL
CREATE TABLE run.Gate (
    ClientId   varchar(20)    NOT NULL,
    TakeId     varchar(20)    NOT NULL,
    Gate       tinyint        NOT NULL CONSTRAINT CK_Gate_Gate CHECK (Gate BETWEEN 1 AND 6),
    Status     varchar(20)    NOT NULL CONSTRAINT CK_Gate_Status
               CHECK (Status IN ('not_needed', 'pending', 'approved', 'rejected', 'auto_approved')),
    OpenedAt   datetime2(3)   NOT NULL CONSTRAINT DF_Gate_OpenedAt DEFAULT SYSUTCDATETIME(),
    Evidence   nvarchar(max)  NULL,                 -- JSON: what the approver sees
    DecidedBy  nvarchar(100)  NULL,
    DecidedAt  datetime2(3)   NULL,
    Note       nvarchar(1000) NULL,
    CONSTRAINT PK_Gate PRIMARY KEY (ClientId, TakeId, Gate)
);
IF OBJECT_ID('run.GateEvent') IS NULL
CREATE TABLE run.GateEvent (
    GateEventId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_GateEvent PRIMARY KEY,
    ClientId    varchar(20)    NOT NULL,
    TakeId      varchar(20)    NOT NULL,
    Gate        tinyint        NOT NULL,
    Action      varchar(20)    NOT NULL,             -- opened, not_needed, approved, rejected, auto_approved
    Actor       nvarchar(100)  NOT NULL,
    Evidence    nvarchar(max)  NULL,
    Note        nvarchar(1000) NULL,
    CreatedAt   datetime2(3)   NOT NULL CONSTRAINT DF_GateEvent_CreatedAt DEFAULT SYSUTCDATETIME()
);
GO
CREATE OR ALTER VIEW run.v_Gate AS
SELECT g.ClientId, g.TakeId, g.Gate, n.GateName, n.DecidedByRole, g.Status, g.OpenedAt, g.DecidedBy, g.DecidedAt, g.Note, g.Evidence,
       CASE WHEN g.Status IN ('approved', 'auto_approved', 'not_needed') THEN 1 ELSE 0 END AS IsPassed
FROM run.Gate AS g
JOIN (VALUES (CAST(1 AS tinyint), 'Spec change', 'reviewer (pull request); client for business rules'),
             (CAST(2 AS tinyint), 'Low-confidence fixes', 'Cogsdale analyst; client for names and addresses'),
             (CAST(3 AS tinyint), 'Triage', 'reviewer'),
             (CAST(4 AS tinyint), 'Load go / no-go', 'reviewer or the project manager'),
             (CAST(5 AS tinyint), 'Publish', 'reviewer'),
             (CAST(6 AS tinyint), 'Take acceptance', 'Client and Cogsdale project managers')) AS n (Gate, GateName, DecidedByRole)
  ON n.Gate = g.Gate;
GO
-- Open (or re-open on a rerun) a gate with its evidence. @Status: pending, or not_needed when nothing needs a decision.
CREATE OR ALTER PROCEDURE run.usp_OpenGate
    @ClientId varchar(20), @TakeId varchar(20), @Gate tinyint, @Evidence nvarchar(max), @Status varchar(20) = 'pending',
    @Actor nvarchar(100) = N'platform'
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @Status NOT IN ('pending', 'not_needed')
        THROW 50001, 'A gate opens as pending or not_needed.', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        UPDATE run.Gate
           SET Status = @Status, OpenedAt = SYSUTCDATETIME(), Evidence = @Evidence, DecidedBy = NULL, DecidedAt = NULL, Note = NULL
         WHERE ClientId = @ClientId AND TakeId = @TakeId AND Gate = @Gate;
        IF @@ROWCOUNT = 0
            INSERT run.Gate (ClientId, TakeId, Gate, Status, Evidence) VALUES (@ClientId, @TakeId, @Gate, @Status, @Evidence);
        INSERT run.GateEvent (ClientId, TakeId, Gate, Action, Actor, Evidence)
        VALUES (@ClientId, @TakeId, @Gate, CASE @Status WHEN 'pending' THEN 'opened' ELSE 'not_needed' END, @Actor, @Evidence);
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
GO
-- A person decides a pending gate. @Decision: approved, rejected, or auto_approved (pipeline demo parameter).
CREATE OR ALTER PROCEDURE run.usp_DecideGate
    @ClientId varchar(20), @TakeId varchar(20), @Gate tinyint, @Decision varchar(20), @DecidedBy nvarchar(100), @Note nvarchar(1000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @Decision NOT IN ('approved', 'rejected', 'auto_approved')
        THROW 50002, 'A decision is approved, rejected or auto_approved.', 1;
    IF NULLIF(LTRIM(RTRIM(@DecidedBy)), N'') IS NULL
        THROW 50003, 'Every decision records who made it.', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        UPDATE run.Gate
           SET Status = @Decision, DecidedBy = @DecidedBy, DecidedAt = SYSUTCDATETIME(), Note = @Note
         WHERE ClientId = @ClientId AND TakeId = @TakeId AND Gate = @Gate AND Status = 'pending';
        IF @@ROWCOUNT = 0
            THROW 50004, 'The gate is not open (pending) for this take.', 1;
        INSERT run.GateEvent (ClientId, TakeId, Gate, Action, Actor, Note)
        VALUES (@ClientId, @TakeId, @Gate, @Decision, @DecidedBy, @Note);
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
GO
