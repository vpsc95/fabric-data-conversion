/* =====================================================================================================================
   Conversion MVP: the Fabric SQL database for one take
   ---------------------------------------------------------------------------------------------------------------------
   What replaces what (legacy -> MVP):
     Pre-staging tables loaded by SmartConnect maps 01-05   -> mvp.Customer, mvp.Service, mvp.Balance (notebook 1 fills them)
     Validation scripts, one module at a time                -> mvp.ValidationRule (rules as data) + mvp.usp_RunRules
     SmartList review of failures                            -> mvp.IssueGroup (grouped issues; the AI agent adds its proposal)
     SmartConnect maps 08-16 into CSM                         -> mvp.usp_LoadToCsm into the csm.* stand-in tables
     Counts and control totals by hand                       -> mvp.Record + mvp.ApprovalLog (Power BI reads them live)

   Every table here is mirrored to OneLake automatically by Fabric, so Power BI (Direct Lake) reads it with no copy step.
   Deliberately simple: 3 extracts, 5 rules, a stand-in for CSM. Safe to run again (objects are created only if missing,
   procedures are CREATE OR ALTER, reference rows are inserted only if missing).
   ===================================================================================================================== */
SET NOCOUNT ON;
IF SCHEMA_ID('mvp') IS NULL EXEC (N'CREATE SCHEMA mvp');
IF SCHEMA_ID('csm') IS NULL EXEC (N'CREATE SCHEMA csm');
GO

/* ---------------------------------------------------------------- takes and modules ---------------------------------- */
IF OBJECT_ID('mvp.Take') IS NULL
CREATE TABLE mvp.Take (                       -- one delivery of extracts from the client
    TakeId      varchar(20)   NOT NULL CONSTRAINT PK_mvp_Take PRIMARY KEY,
    TakeDate    date          NOT NULL,
    Description nvarchar(200) NOT NULL CONSTRAINT DF_mvp_Take_Description DEFAULT ''
);
IF OBJECT_ID('mvp.Module') IS NULL
CREATE TABLE mvp.Module (                     -- the three CSM areas the MVP converts
    Module        varchar(20)   NOT NULL CONSTRAINT PK_mvp_Module PRIMARY KEY,   -- Customers, Services, Balances
    CsmTemplate   varchar(20)   NOT NULL,     -- the Cogsdale UM staging layout it feeds
    SourceTable   nvarchar(128) NOT NULL,     -- the staging table the rules read
    RecordKeyExpr nvarchar(200) NOT NULL,     -- how one record is identified in that table (alias r)
    SortOrder     int           NOT NULL
);
GO

/* ---------------------------------------------------------------- staging: written by notebook 1 --------------------- */
IF OBJECT_ID('mvp.Customer') IS NULL
CREATE TABLE mvp.Customer (                   -- CUSTOMERS extract: already a table, one row per account
    TakeId         varchar(20)  NOT NULL,
    SourceRow      int          NOT NULL,     -- row number in the client's file, for tracing
    Account        varchar(20)  NOT NULL,
    LastName       nvarchar(60) NOT NULL CONSTRAINT DF_mvp_Customer_LastName DEFAULT '',
    FirstName      nvarchar(60) NOT NULL CONSTRAINT DF_mvp_Customer_FirstName DEFAULT '',
    DriversLicense varchar(40)  NOT NULL CONSTRAINT DF_mvp_Customer_DriversLicense DEFAULT '',
    DlState        varchar(20)  NOT NULL CONSTRAINT DF_mvp_Customer_DlState DEFAULT '',
    Zip            varchar(12)  NOT NULL CONSTRAINT DF_mvp_Customer_Zip DEFAULT '',
    CustomerClass  varchar(10)  NOT NULL CONSTRAINT DF_mvp_Customer_CustomerClass DEFAULT '',
    CustomerStatus varchar(20)  NOT NULL CONSTRAINT DF_mvp_Customer_CustomerStatus DEFAULT '',
    CONSTRAINT PK_mvp_Customer PRIMARY KEY (TakeId, SourceRow)
);
IF OBJECT_ID('mvp.Service') IS NULL
CREATE TABLE mvp.Service (                    -- UB Services Report: one row per service after the reshape
    TakeId      varchar(20) NOT NULL,
    SourceRow   int         NOT NULL,
    Slot        tinyint     NOT NULL,         -- 1 or 2: the printed report shows two services side by side
    Account     varchar(20) NOT NULL,         -- filled down by the notebook (the client did this by hand in Excel)
    ServiceCode varchar(3)  NOT NULL,         -- e.g. 100
    ServiceText varchar(30) NOT NULL CONSTRAINT DF_mvp_Service_ServiceText DEFAULT '',   -- e.g. 100 - WATER SE
    Status      varchar(10) NOT NULL CONSTRAINT DF_mvp_Service_Status DEFAULT '',
    RateTable   varchar(20) NOT NULL CONSTRAINT DF_mvp_Service_RateTable DEFAULT '',
    Meter       varchar(20) NOT NULL CONSTRAINT DF_mvp_Service_Meter DEFAULT '',
    CONSTRAINT PK_mvp_Service PRIMARY KEY (TakeId, SourceRow, Slot)
);
IF OBJECT_ID('mvp.Balance') IS NULL
CREATE TABLE mvp.Balance (                    -- UB Account Balances report: one row per account line
    TakeId        varchar(20)    NOT NULL,
    SourceRow     int            NOT NULL,
    Account       varchar(20)    NOT NULL,
    AccountStatus varchar(20)    NOT NULL CONSTRAINT DF_mvp_Balance_AccountStatus DEFAULT '',
    Balance       numeric(19, 5) NOT NULL CONSTRAINT DF_mvp_Balance_Balance DEFAULT 0,
    CONSTRAINT PK_mvp_Balance PRIMARY KEY (TakeId, SourceRow)
);
GO

/* ---------------------------------------------------------------- reference data: crosswalk, CSM setup, rules -------- */
IF OBJECT_ID('mvp.ServiceCode') IS NULL
CREATE TABLE mvp.ServiceCode (                -- crosswalk: legacy service code -> CSM service, with the go-live decisions
    ServiceCode varchar(3)    NOT NULL CONSTRAINT PK_mvp_ServiceCode PRIMARY KEY,
    CsmService  varchar(20)   NOT NULL CONSTRAINT DF_mvp_ServiceCode_CsmService DEFAULT '',
    FixedTariff varchar(10)   NOT NULL CONSTRAINT DF_mvp_ServiceCode_FixedTariff DEFAULT '',
    Converts    bit           NOT NULL,
    Reason      nvarchar(300) NOT NULL CONSTRAINT DF_mvp_ServiceCode_Reason DEFAULT ''
);
IF OBJECT_ID('mvp.CsmTariff') IS NULL
CREATE TABLE mvp.CsmTariff (                  -- fixed tariffs set up in CSM (stand-in for the CSM setup tables)
    TariffId    varchar(10)   NOT NULL CONSTRAINT PK_mvp_CsmTariff PRIMARY KEY,
    Description nvarchar(100) NOT NULL CONSTRAINT DF_mvp_CsmTariff_Description DEFAULT ''
);
IF OBJECT_ID('mvp.ValidationRule') IS NULL
CREATE TABLE mvp.ValidationRule (             -- rules as data: add a row to add a check, no code change
    RuleId      varchar(10)    NOT NULL CONSTRAINT PK_mvp_ValidationRule PRIMARY KEY,
    Module      varchar(20)    NOT NULL,
    Description nvarchar(200)  NOT NULL,      -- plain English, shown in the report
    Ticket      varchar(20)    NOT NULL CONSTRAINT DF_mvp_ValidationRule_Ticket DEFAULT '',   -- the client's go-live ticket
    FailsWhen   nvarchar(1000) NOT NULL,      -- SQL condition on the module's staging row (alias r)
    GroupBy     nvarchar(400)  NOT NULL CONSTRAINT DF_mvp_ValidationRule_GroupBy DEFAULT N'''''',   -- code used to group issues
    IsActive    bit            NOT NULL CONSTRAINT DF_mvp_ValidationRule_IsActive DEFAULT 1
);
GO

/* ---------------------------------------------------------------- results: what the report shows -------------------- */
IF OBJECT_ID('mvp.Record') IS NULL
CREATE TABLE mvp.Record (                     -- every record received: Ready, Held back or Loaded
    TakeId    varchar(20)    NOT NULL,
    Module    varchar(20)    NOT NULL,
    RecordKey varchar(30)    NOT NULL,
    Status    varchar(20)    NOT NULL,
    Amount    numeric(19, 5) NOT NULL CONSTRAINT DF_mvp_Record_Amount DEFAULT 0,      -- balances only: the control total
    CONSTRAINT PK_mvp_Record PRIMARY KEY (TakeId, Module, RecordKey)
);
IF OBJECT_ID('mvp.Issue') IS NULL
CREATE TABLE mvp.Issue (                      -- one row per record and broken rule
    TakeId     varchar(20)   NOT NULL,
    RuleId     varchar(10)   NOT NULL,
    Module     varchar(20)   NOT NULL,
    RecordKey  varchar(30)   NOT NULL,
    GroupValue nvarchar(100) NOT NULL CONSTRAINT DF_mvp_Issue_GroupValue DEFAULT '',
    CONSTRAINT PK_mvp_Issue PRIMARY KEY (TakeId, RuleId, RecordKey)
);
IF OBJECT_ID('mvp.IssueGroup') IS NULL
CREATE TABLE mvp.IssueGroup (                 -- issues grouped by rule and code: what the AI agent sees (codes and counts only)
    TakeId          varchar(20)   NOT NULL,
    RuleId          varchar(10)   NOT NULL,
    GroupValue      nvarchar(100) NOT NULL,
    Module          varchar(20)   NOT NULL,
    RuleText        nvarchar(200) NOT NULL,
    Records         int           NOT NULL,
    AiVerdict       varchar(20)   NOT NULL CONSTRAINT DF_mvp_IssueGroup_AiVerdict DEFAULT '',        -- Expected | Needs action
    AiOwner         varchar(20)   NOT NULL CONSTRAINT DF_mvp_IssueGroup_AiOwner DEFAULT '',          -- Client | Cogsdale | None
    AiAction        nvarchar(300) NOT NULL CONSTRAINT DF_mvp_IssueGroup_AiAction DEFAULT '',
    AiClientMessage nvarchar(400) NOT NULL CONSTRAINT DF_mvp_IssueGroup_AiClientMessage DEFAULT '',
    AiReason        nvarchar(400) NOT NULL CONSTRAINT DF_mvp_IssueGroup_AiReason DEFAULT '',
    AiModel         varchar(40)   NOT NULL CONSTRAINT DF_mvp_IssueGroup_AiModel DEFAULT '',
    CONSTRAINT PK_mvp_IssueGroup PRIMARY KEY (TakeId, RuleId, GroupValue)
);
IF OBJECT_ID('mvp.ApprovalLog') IS NULL
CREATE TABLE mvp.ApprovalLog (                -- who approved the load, and the reconciliation at that moment
    ApprovalId      int            IDENTITY(1, 1) NOT NULL CONSTRAINT PK_mvp_ApprovalLog PRIMARY KEY,
    TakeId          varchar(20)    NOT NULL,
    ApprovedBy      nvarchar(100)  NOT NULL,
    ApprovedAt      datetime2(0)   NOT NULL CONSTRAINT DF_mvp_ApprovalLog_ApprovedAt DEFAULT SYSUTCDATETIME(),
    RecordsLoaded   int            NOT NULL,
    RecordsHeldBack int            NOT NULL,
    BalanceReceived numeric(19, 5) NOT NULL,
    BalanceLoaded   numeric(19, 5) NOT NULL,
    BalanceHeldBack numeric(19, 5) NOT NULL
);
GO

/* ---------------------------------------------------------------- csm: stand-in for the CSM CONV database ----------- */
IF OBJECT_ID('csm.Customer') IS NULL
CREATE TABLE csm.Customer (
    TakeId        varchar(20)  NOT NULL,
    Account       varchar(20)  NOT NULL,
    LastName      nvarchar(60) NOT NULL,
    FirstName     nvarchar(60) NOT NULL,
    AlternateId   varchar(15)  NOT NULL,     -- licence + state; CSM holds 15 characters (rule CUST-01)
    Zip           varchar(12)  NOT NULL,
    CustomerClass varchar(10)  NOT NULL,
    LoadedAt      datetime2(0) NOT NULL,
    CONSTRAINT PK_csm_Customer PRIMARY KEY (TakeId, Account)
);
IF OBJECT_ID('csm.Service') IS NULL
CREATE TABLE csm.Service (
    TakeId     varchar(20)  NOT NULL,
    SourceRow  int          NOT NULL,
    Slot       tinyint      NOT NULL,
    Account    varchar(20)  NOT NULL,
    CsmService varchar(20)  NOT NULL,
    RateTable  varchar(20)  NOT NULL,
    Meter      varchar(20)  NOT NULL,
    LoadedAt   datetime2(0) NOT NULL,
    CONSTRAINT PK_csm_Service PRIMARY KEY (TakeId, SourceRow, Slot)
);
IF OBJECT_ID('csm.Balance') IS NULL
CREATE TABLE csm.Balance (
    TakeId   varchar(20)    NOT NULL,
    Account  varchar(20)    NOT NULL,
    Balance  numeric(19, 5) NOT NULL,
    LoadedAt datetime2(0)   NOT NULL,
    CONSTRAINT PK_csm_Balance PRIMARY KEY (TakeId, Account)
);
GO

/* ---------------------------------------------------------------- reference rows (inserted only when missing) -------- */
INSERT mvp.Module (Module, CsmTemplate, SourceTable, RecordKeyExpr, SortOrder)
SELECT v.Module, v.CsmTemplate, v.SourceTable, v.RecordKeyExpr, v.SortOrder
FROM (VALUES ('Customers', 'UMRM0101', N'mvp.Customer', N'CAST(r.SourceRow AS varchar(30))', 1),
             ('Services',  'UM00300',  N'mvp.Service',  N'CONCAT(r.SourceRow, ''-'', r.Slot)', 2),
             ('Balances',  'UM20400',  N'mvp.Balance',  N'CAST(r.SourceRow AS varchar(30))', 3)) AS v (Module, CsmTemplate, SourceTable, RecordKeyExpr, SortOrder)
WHERE NOT EXISTS (SELECT 1 FROM mvp.Module AS m WHERE m.Module = v.Module);

-- The go-live decisions (from the go-live integrity report and the SAMPLE staging scripts)
INSERT mvp.ServiceCode (ServiceCode, CsmService, FixedTariff, Converts, Reason)
SELECT v.ServiceCode, v.CsmService, v.FixedTariff, v.Converts, v.Reason
FROM (VALUES ('100', 'WATER',    '',    1, N''),
             ('200', 'SEWER',    '',    1, N''),
             ('900', 'DRAINAGE', 'DRF', 1, N''),
             ('500', 'GRINDER',  'GRP', 1, N'Grinder: its fixed tariff GRP is deliberately not set up in CSM, so grinder services do not convert (by design, go-live ticket DEMO-41068).'),
             ('105', '',         '',    0, N'Senior discount, not a service: not converted (by design, go-live ticket DEMO-41065).'),
             ('205', '',         '',    0, N'Senior discount, not a service: not converted (by design, go-live ticket DEMO-41065).'),
             ('300', '',         '',    0, N'Not a CSM service: the go-live integrity report lists it as expected (by design, go-live ticket DEMO-41065).'),
             ('400', '',         '',    0, N'Not a CSM service: the go-live integrity report lists it as expected (by design, go-live ticket DEMO-41065).'),
             ('600', '',         '',    0, N'Not a CSM service: the go-live integrity report lists it as expected (by design, go-live ticket DEMO-41065).')
     ) AS v (ServiceCode, CsmService, FixedTariff, Converts, Reason)
WHERE NOT EXISTS (SELECT 1 FROM mvp.ServiceCode AS c WHERE c.ServiceCode = v.ServiceCode);

INSERT mvp.CsmTariff (TariffId, Description)
SELECT v.TariffId, v.Description
FROM (VALUES ('DRF', N'Drainage fee (fixed tariff)')) AS v (TariffId, Description)
WHERE NOT EXISTS (SELECT 1 FROM mvp.CsmTariff AS t WHERE t.TariffId = v.TariffId);

-- Five checks from the go-live issue types (each with the client's ticket), plus one example rule to switch on live
INSERT mvp.ValidationRule (RuleId, Module, Description, Ticket, FailsWhen, GroupBy, IsActive)
SELECT v.RuleId, v.Module, v.Description, v.Ticket, v.FailsWhen, v.GroupBy, v.IsActive
FROM (VALUES
    ('CUST-01', 'Customers', N'Driver''s licence + state is longer than the 15 characters CSM holds (AlternateID)', 'DEMO-40270',
     N'LEN(LTRIM(RTRIM(CONCAT(r.DriversLicense, '' '', r.DlState)))) > 15',
     N'CASE WHEN LEN(r.DlState) > 2 THEN ''licence state written out in full'' ELSE ''licence number too long'' END', 1),
    ('SVC-01', 'Services', N'Service code is not converted to a CSM service', 'DEMO-41065',
     N'NOT EXISTS (SELECT 1 FROM mvp.ServiceCode AS c WHERE c.ServiceCode = r.ServiceCode AND c.Converts = 1)',
     N'r.ServiceText', 1),
    ('SVC-02', 'Services', N'Water service has no meter number', 'DEMO-40265',
     N'r.ServiceCode = ''100'' AND r.Meter = ''''',
     N'CASE r.Slot WHEN 1 THEN ''first service on the report line'' ELSE ''second service on the report line'' END', 1),
    ('SVC-03', 'Services', N'The service''s fixed tariff is not set up in CSM', 'DEMO-41068',
     N'EXISTS (SELECT 1 FROM mvp.ServiceCode AS c WHERE c.ServiceCode = r.ServiceCode AND c.FixedTariff <> '''' AND NOT EXISTS (SELECT 1 FROM mvp.CsmTariff AS t WHERE t.TariffId = c.FixedTariff))',
     N'r.ServiceText', 1),
    ('BAL-01', 'Balances', N'Balance account is not in the customer file', 'DEMO-41070',
     N'NOT EXISTS (SELECT 1 FROM mvp.Customer AS c WHERE c.TakeId = r.TakeId AND c.Account = r.Account)',
     N'''''', 1),
    ('CUST-02', 'Customers', N'Mailing ZIP code is not 5 or 9 digits (example: switch on during the demo)', '',
     N'r.Zip NOT LIKE ''[0-9][0-9][0-9][0-9][0-9]'' AND r.Zip NOT LIKE ''[0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]''',
     N'CASE WHEN r.Zip = '''' THEN ''ZIP blank'' ELSE CONCAT(''ZIP has '', LEN(r.Zip), '' characters'') END', 0)
    ) AS v (RuleId, Module, Description, Ticket, FailsWhen, GroupBy, IsActive)
WHERE NOT EXISTS (SELECT 1 FROM mvp.ValidationRule AS x WHERE x.RuleId = v.RuleId);
GO

/* =====================================================================================================================
   mvp.usp_RunRules: replaces the per-module validation scripts.
   Input:  @TakeId (the take notebook 1 just staged).
   Output: mvp.Record (Ready / Held back), mvp.Issue (one row per broken rule), mvp.IssueGroup (grouped, for the AI agent).
   How:    every staged record starts as Ready; each active row of mvp.ValidationRule becomes one set-based INSERT;
           any record with an issue is held back. Safe to run again for the same take.
   Example: EXEC mvp.usp_RunRules @TakeId = 'go-live';
   ===================================================================================================================== */
CREATE OR ALTER PROCEDURE mvp.usp_RunRules
    @TakeId varchar(20)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRY
        BEGIN TRANSACTION;

        -- 1. Every staged record starts as Ready (a take is a full rebuild, so an earlier load of this take is cleared too)
        DELETE mvp.IssueGroup WHERE TakeId = @TakeId;
        DELETE mvp.Issue      WHERE TakeId = @TakeId;
        DELETE mvp.Record     WHERE TakeId = @TakeId;
        DELETE csm.Customer   WHERE TakeId = @TakeId;
        DELETE csm.Service    WHERE TakeId = @TakeId;
        DELETE csm.Balance    WHERE TakeId = @TakeId;
        INSERT mvp.Record (TakeId, Module, RecordKey, Status)
        SELECT TakeId, 'Customers', CAST(SourceRow AS varchar(30)), 'Ready' FROM mvp.Customer WHERE TakeId = @TakeId;
        INSERT mvp.Record (TakeId, Module, RecordKey, Status)
        SELECT TakeId, 'Services', CONCAT(SourceRow, '-', Slot), 'Ready' FROM mvp.Service WHERE TakeId = @TakeId;
        INSERT mvp.Record (TakeId, Module, RecordKey, Status, Amount)
        SELECT TakeId, 'Balances', CAST(SourceRow AS varchar(30)), 'Ready', Balance FROM mvp.Balance WHERE TakeId = @TakeId;

        -- 2. Run each active rule: one set-based INSERT per rule, built from the rule's row (metadata only, never data values)
        DECLARE @rules TABLE (n int IDENTITY(1, 1) PRIMARY KEY, RuleId varchar(10), Module varchar(20), SourceTable nvarchar(128),
                              RecordKeyExpr nvarchar(200), FailsWhen nvarchar(1000), GroupBy nvarchar(400));
        INSERT @rules (RuleId, Module, SourceTable, RecordKeyExpr, FailsWhen, GroupBy)
        SELECT v.RuleId, v.Module, m.SourceTable, m.RecordKeyExpr, v.FailsWhen, v.GroupBy
        FROM mvp.ValidationRule AS v
        JOIN mvp.Module AS m ON m.Module = v.Module
        WHERE v.IsActive = 1
        ORDER BY v.RuleId;

        DECLARE @i int = 1, @n int = (SELECT COUNT(*) FROM @rules), @sql nvarchar(max), @RuleId varchar(10), @Module varchar(20);
        WHILE @i <= @n
        BEGIN
            SELECT @RuleId = RuleId, @Module = Module,
                   @sql = N'INSERT mvp.Issue (TakeId, RuleId, Module, RecordKey, GroupValue) '
                        + N'SELECT @TakeId, @RuleId, @Module, ' + RecordKeyExpr + N', LEFT(' + GroupBy + N', 100) '
                        + N'FROM ' + QUOTENAME(PARSENAME(SourceTable, 2)) + N'.' + QUOTENAME(PARSENAME(SourceTable, 1)) + N' AS r '
                        + N'WHERE r.TakeId = @TakeId AND (' + FailsWhen + N');'
            FROM @rules WHERE n = @i;
            EXEC sys.sp_executesql @sql, N'@TakeId varchar(20), @RuleId varchar(10), @Module varchar(20)', @TakeId, @RuleId, @Module;
            SET @i += 1;
        END;

        -- 3. A record that breaks any rule is held back from the load
        UPDATE r SET Status = 'Held back'
        FROM mvp.Record AS r
        WHERE r.TakeId = @TakeId
          AND EXISTS (SELECT 1 FROM mvp.Issue AS i WHERE i.TakeId = r.TakeId AND i.Module = r.Module AND i.RecordKey = r.RecordKey);

        -- 4. Group the issues by rule and code: this is what the AI agent and the report see (no record values)
        INSERT mvp.IssueGroup (TakeId, RuleId, GroupValue, Module, RuleText, Records)
        SELECT i.TakeId, i.RuleId, i.GroupValue, i.Module, v.Description, COUNT(*)
        FROM mvp.Issue AS i
        JOIN mvp.ValidationRule AS v ON v.RuleId = i.RuleId
        WHERE i.TakeId = @TakeId
        GROUP BY i.TakeId, i.RuleId, i.GroupValue, i.Module, v.Description;

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
GO

/* =====================================================================================================================
   mvp.usp_LoadToCsm: replaces SmartConnect maps 08-16 (in production: the CSM business-logic procedures, through the
   on-premises data gateway). Runs only after a person approves (pipeline "Approve_and_load", parameter approved_by).
   Input:  @TakeId, @ApprovedBy (who approved; required).
   Output: csm.Customer / csm.Service / csm.Balance (stand-in for CSM), mvp.Record Status = Loaded, one mvp.ApprovalLog row
           with the reconciliation: received = loaded + held back, in records and in balance dollars.
   Example: EXEC mvp.usp_LoadToCsm @TakeId = 'go-live', @ApprovedBy = N'reviewer';
   ===================================================================================================================== */
CREATE OR ALTER PROCEDURE mvp.usp_LoadToCsm
    @TakeId     varchar(20),
    @ApprovedBy nvarchar(100)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF LTRIM(RTRIM(ISNULL(@ApprovedBy, N''))) = N''
        THROW 50001, 'A person must approve the load: set the pipeline parameter approved_by.', 1;
    IF NOT EXISTS (SELECT 1 FROM mvp.Record WHERE TakeId = @TakeId)
        THROW 50002, 'Nothing to load: run the Prepare_take pipeline for this take first.', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @now datetime2(0) = SYSUTCDATETIME();

        -- A rerun replaces this take's rows in CSM (the stand-in is rebuilt per take)
        DELETE csm.Customer WHERE TakeId = @TakeId;
        DELETE csm.Service  WHERE TakeId = @TakeId;
        DELETE csm.Balance  WHERE TakeId = @TakeId;
        UPDATE mvp.Record SET Status = 'Ready' WHERE TakeId = @TakeId AND Status = 'Loaded';

        INSERT csm.Customer (TakeId, Account, LastName, FirstName, AlternateId, Zip, CustomerClass, LoadedAt)
        SELECT c.TakeId, c.Account, c.LastName, c.FirstName, LEFT(LTRIM(RTRIM(CONCAT(c.DriversLicense, ' ', c.DlState))), 15), c.Zip,
               c.CustomerClass, @now
        FROM mvp.Customer AS c
        JOIN mvp.Record AS r ON r.TakeId = c.TakeId AND r.Module = 'Customers' AND r.RecordKey = CAST(c.SourceRow AS varchar(30))
        WHERE c.TakeId = @TakeId AND r.Status = 'Ready';

        INSERT csm.Service (TakeId, SourceRow, Slot, Account, CsmService, RateTable, Meter, LoadedAt)
        SELECT s.TakeId, s.SourceRow, s.Slot, s.Account, x.CsmService, s.RateTable, s.Meter, @now
        FROM mvp.Service AS s
        JOIN mvp.Record AS r ON r.TakeId = s.TakeId AND r.Module = 'Services' AND r.RecordKey = CONCAT(s.SourceRow, '-', s.Slot)
        JOIN mvp.ServiceCode AS x ON x.ServiceCode = s.ServiceCode
        WHERE s.TakeId = @TakeId AND r.Status = 'Ready';

        INSERT csm.Balance (TakeId, Account, Balance, LoadedAt)
        SELECT b.TakeId, b.Account, b.Balance, @now
        FROM mvp.Balance AS b
        JOIN mvp.Record AS r ON r.TakeId = b.TakeId AND r.Module = 'Balances' AND r.RecordKey = CAST(b.SourceRow AS varchar(30))
        WHERE b.TakeId = @TakeId AND r.Status = 'Ready';

        UPDATE mvp.Record SET Status = 'Loaded' WHERE TakeId = @TakeId AND Status = 'Ready';

        -- Reconciliation, recorded with the approval: received = loaded + held back
        INSERT mvp.ApprovalLog (TakeId, ApprovedBy, ApprovedAt, RecordsLoaded, RecordsHeldBack, BalanceReceived, BalanceLoaded, BalanceHeldBack)
        SELECT @TakeId, @ApprovedBy, @now,
               SUM(CASE WHEN Status = 'Loaded' THEN 1 ELSE 0 END),
               SUM(CASE WHEN Status = 'Held back' THEN 1 ELSE 0 END),
               SUM(CASE WHEN Module = 'Balances' THEN Amount ELSE 0 END),
               SUM(CASE WHEN Module = 'Balances' AND Status = 'Loaded' THEN Amount ELSE 0 END),
               SUM(CASE WHEN Module = 'Balances' AND Status = 'Held back' THEN Amount ELSE 0 END)
        FROM mvp.Record
        WHERE TakeId = @TakeId;

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
GO
