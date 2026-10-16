/* =====================================================================
   66_load.sql: metadata-driven SmartConnect replacement loader.
   It prepares row status, calls CSM emulator procedures, and logs progress.
   ===================================================================== */
SET NOCOUNT ON;
IF SCHEMA_ID('load') IS NULL EXEC('CREATE SCHEMA load');
GO
IF OBJECT_ID('load.ProcMap') IS NULL
CREATE TABLE load.ProcMap (Module varchar(30) NOT NULL CONSTRAINT PK_load_ProcMap PRIMARY KEY, ModuleName varchar(60) NOT NULL, ProcedureName sysname NOT NULL, LoadOrder int NOT NULL, GoldTable sysname NOT NULL, RowKeyColumn sysname NOT NULL, ValidFilter nvarchar(200) NOT NULL, OrderByClause nvarchar(400) NOT NULL, ParallelSafe varchar(20) NOT NULL, PartitionKey sysname NOT NULL, FastPath bit NOT NULL CONSTRAINT DF_load_ProcMap_FastPath DEFAULT 0);
IF OBJECT_ID('load.ParamMap') IS NULL
CREATE TABLE load.ParamMap (Module varchar(30) NOT NULL, ParameterName sysname NOT NULL, SourceColumn sysname NULL, ConstantValue nvarchar(200) NULL, SqlType varchar(60) NOT NULL, Direction varchar(10) NOT NULL, CONSTRAINT PK_load_ParamMap PRIMARY KEY (Module, ParameterName));
IF OBJECT_ID('load.RowStatus') IS NULL
CREATE TABLE load.RowStatus (ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, Module varchar(30) NOT NULL, GoldRowId bigint NOT NULL, RowKey nvarchar(200) NOT NULL, Status varchar(20) NOT NULL CONSTRAINT CK_load_RowStatus_Status CHECK (Status IN ('pending','loaded','failed','skipped_invalid')), scError int NULL, scMessage varchar(255) NULL, Attempts int NOT NULL CONSTRAINT DF_load_RowStatus_Attempts DEFAULT 0, LastAttemptAt datetime2(3) NULL, LoadedAt datetime2(3) NULL, CONSTRAINT PK_load_RowStatus PRIMARY KEY (ClientId, TakeId, Module, GoldRowId));
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_load_RowStatus_ModuleStatus' AND object_id = OBJECT_ID('load.RowStatus'))
CREATE INDEX IX_load_RowStatus_ModuleStatus ON load.RowStatus (ClientId, TakeId, Module, Status) INCLUDE (Attempts, RowKey);
GO

CREATE OR ALTER PROCEDURE load.usp_PrepareTake @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: initialize loader row statuses and clear emulator rows for one take. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'load.usp_PrepareTake', @log OUTPUT;
    BEGIN TRY
        DELETE load.RowStatus WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.HistMR WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.Deposit WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.BegBalance WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.LocationHistory WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.Connection WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.Location WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.CustomerAddress WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DELETE conv.Customer WHERE ClientId = @ClientId AND TakeId = @TakeId;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UMRM0101', g.RowId, CONVERT(nvarchar(200), g.[CustomerID]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UMRM0101' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_Customer g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND ID = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UMRM0111', g.RowId, CONVERT(nvarchar(200), g.[CustomerID]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UMRM0111' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_Customer g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND ID = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UM00600', g.RowId, CONVERT(nvarchar(200), g.[LocationID]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UM00600' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_Location g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND 1 = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UM00400', g.RowId, CONVERT(nvarchar(200), g.[EquipmentID]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UM00400' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_Equipment g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND 1 = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UM00300', g.RowId, CONVERT(nvarchar(200), g.[RecordKey]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UM00300' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_Connection g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND 1 = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UM00600H', g.RowId, CONVERT(nvarchar(200), g.[RecordKey]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UM00600H' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_LocationHistory g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND 1 = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UM20400', g.RowId, CONVERT(nvarchar(200), g.[RecordKey]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UM20400' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_BegBalance g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND 1 = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UM01900', g.RowId, CONVERT(nvarchar(200), g.[RecordKey]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UM01900' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_Deposit g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND 1 = 1;
        INSERT load.RowStatus (ClientId, TakeId, Module, GoldRowId, RowKey, Status)
        SELECT g.ClientId, g.TakeId, 'UM30300', g.RowId, CONVERT(nvarchar(200), g.[RecordKey]), CASE WHEN g.isvalid <> 0 AND NOT EXISTS (SELECT 1 FROM run.Issue i WHERE i.ClientId = g.ClientId AND i.TakeId = g.TakeId AND i.Module = 'UM30300' AND i.RowId = g.RowId AND i.Severity = 'E') THEN 'pending' ELSE 'skipped_invalid' END FROM gold.UM_HistMR g WHERE g.ClientId = @ClientId AND g.TakeId = @TakeId AND 1 = 1;
        EXEC run.usp_LogEnd @log, @@ROWCOUNT, 'Succeeded', NULL;
    END TRY
    BEGIN CATCH
        DECLARE @PrepareError nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @PrepareError;
        THROW;
    END CATCH
END;
GO

IF OBJECT_ID('load.FastPathCheck') IS NULL
CREATE TABLE load.FastPathCheck (FastPathCheckId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_load_FastPathCheck PRIMARY KEY, ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, Module varchar(30) NOT NULL, SampleRows int NOT NULL, RowByRowRows int NOT NULL, SetBasedRows int NOT NULL, DifferenceRows int NOT NULL, Passed bit NOT NULL, CheckedAt datetime2(3) NOT NULL CONSTRAINT DF_load_FastPathCheck_CheckedAt DEFAULT SYSUTCDATETIME(), Message nvarchar(4000) NOT NULL);
GO
CREATE OR ALTER PROCEDURE load.usp_CheckHistMRFastPath @ClientId varchar(20), @TakeId varchar(20), @SampleRows int = 2000
AS
/* Purpose: prove the historical-read set-based fast path matches row-by-row emulator calls on a sample. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rb int = 0, @sb int = 0, @diff int = 0;
    DECLARE @rbClient varchar(20) = LEFT(@ClientId, 12) + '_rb';
    DECLARE @sbClient varchar(20) = LEFT(@ClientId, 12) + '_sb';
    DECLARE @checkTake varchar(20) = LEFT(@TakeId, 17) + '_c';
    EXEC run.usp_LogStart @ClientId, @TakeId, 'load.usp_CheckHistMRFastPath', @log OUTPUT;
    BEGIN TRY
        IF EXISTS (SELECT 1 FROM load.FastPathCheck WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = 'UM30300' AND SampleRows = @SampleRows AND Passed = 1)
        BEGIN
            EXEC run.usp_LogEnd @log, 0, 'Succeeded', 'Historical read fast-path check already passed.';
            RETURN;
        END;
        DELETE conv.HistMR WHERE ClientId IN (@rbClient, @sbClient) AND TakeId = @checkTake;
        DELETE conv.Equipment WHERE ClientId IN (@rbClient, @sbClient) AND TakeId = @checkTake;
        INSERT conv.Equipment (ClientId, TakeId, EquipmentID, EquipmentClass, ServiceCategory, SerialNumber, RemoteID)
        SELECT @rbClient, @checkTake, EquipmentID, EquipmentClass, ServiceCategory, SerialNumber, RemoteID FROM conv.Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId;
        INSERT conv.Equipment (ClientId, TakeId, EquipmentID, EquipmentClass, ServiceCategory, SerialNumber, RemoteID)
        SELECT @sbClient, @checkTake, EquipmentID, EquipmentClass, ServiceCategory, SerialNumber, RemoteID FROM conv.Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DECLARE @LocationID char(15), @CustomerID char(15), @EquipmentID char(15), @ReadingDate datetime, @ReadingType smallint, @NumberOfDays smallint, @Consumption1 numeric(19,5), @Consumption2 numeric(19,5), @Consumption3 numeric(19,5), @Reading numeric(19,5), @PreviousReading numeric(19,5), @scMessage varchar(255), @scError int;
        DECLARE c_load_hist_check CURSOR LOCAL FAST_FORWARD FOR
        SELECT TOP (2000) LEFT(COALESCE(g.LocationID, ''), 15), LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(g.EquipmentID, ''), 15), COALESCE(TRY_CONVERT(datetime, g.ReadingDate), CONVERT(datetime, '19000101', 112)), COALESCE(TRY_CONVERT(smallint, g.ReadingType), 0), COALESCE(TRY_CONVERT(smallint, g.NumberOfDays), 0), COALESCE(TRY_CONVERT(numeric(19,5), g.Consumption1), 0), COALESCE(TRY_CONVERT(numeric(19,5), g.Consumption2), 0), 0, COALESCE(TRY_CONVERT(numeric(19,5), g.Reading), 0), COALESCE(TRY_CONVERT(numeric(19,5), g.PreviousReading), 0)
        FROM load.RowStatus s JOIN gold.UM_HistMR g ON g.RowId = s.GoldRowId
        WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM30300' AND s.Status IN ('pending','failed','loaded')
        ORDER BY g.EquipmentID, g.ReadingDate, g.RowId;
        EXEC sys.sp_set_session_context @key = N'ClientId', @value = @rbClient;
        EXEC sys.sp_set_session_context @key = N'TakeId', @value = @checkTake;
        OPEN c_load_hist_check;
        FETCH NEXT FROM c_load_hist_check INTO @LocationID, @CustomerID, @EquipmentID, @ReadingDate, @ReadingType, @NumberOfDays, @Consumption1, @Consumption2, @Consumption3, @Reading, @PreviousReading;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @scMessage = ''; SET @scError = 0;
            EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateHistoricalMR @UserID=@UserID, @UserDate=@UserDate, @LocationID=@LocationID, @CustomerID=@CustomerID, @EquipmentID=@EquipmentID, @ReadingDate=@ReadingDate, @ReadingType=@ReadingType, @NumberOfDays=@NumberOfDays, @Consumption1=@Consumption1, @Consumption2=@Consumption2, @Consumption3=@Consumption3, @Reading=@Reading, @PreviousReading=@PreviousReading, @BillDocumentNumber=@BillDocumentNumber, @PowerFactor1=@PowerFactor1, @LoadFactor1=@LoadFactor1, @ThermFactor=@ThermFactor, @scMessage=@scMessage OUTPUT, @scError=@scError OUTPUT', N'@UserID char(15), @UserDate datetime, @LocationID char(15), @CustomerID char(15), @EquipmentID char(15), @ReadingDate datetime, @ReadingType smallint, @NumberOfDays smallint, @Consumption1 numeric(19,5), @Consumption2 numeric(19,5), @Consumption3 numeric(19,5), @Reading numeric(19,5), @PreviousReading numeric(19,5), @BillDocumentNumber char(15), @PowerFactor1 numeric(19,5), @LoadFactor1 numeric(19,5), @ThermFactor numeric(19,5), @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @UserID = '', @UserDate = @ReadingDate, @LocationID = @LocationID, @CustomerID = @CustomerID, @EquipmentID = @EquipmentID, @ReadingDate = @ReadingDate, @ReadingType = @ReadingType, @NumberOfDays = @NumberOfDays, @Consumption1 = @Consumption1, @Consumption2 = @Consumption2, @Consumption3 = @Consumption3, @Reading = @Reading, @PreviousReading = @PreviousReading, @BillDocumentNumber = '', @PowerFactor1 = 0, @LoadFactor1 = 0, @ThermFactor = 0, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT;
            SET @rb = @rb + CASE WHEN COALESCE(@scError, 0) = 0 THEN 1 ELSE 0 END;
            FETCH NEXT FROM c_load_hist_check INTO @LocationID, @CustomerID, @EquipmentID, @ReadingDate, @ReadingType, @NumberOfDays, @Consumption1, @Consumption2, @Consumption3, @Reading, @PreviousReading;
        END;
        CLOSE c_load_hist_check;
        DEALLOCATE c_load_hist_check;
        INSERT conv.HistMR (ClientId, TakeId, LocationID, CustomerID, EquipmentID, ReadingDate, ReadingType, Reading, Consumption1)
        SELECT TOP (2000) @sbClient, @checkTake, LEFT(COALESCE(g.LocationID, ''), 15), LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(g.EquipmentID, ''), 15), COALESCE(TRY_CONVERT(datetime, g.ReadingDate), CONVERT(datetime, '19000101', 112)), COALESCE(TRY_CONVERT(smallint, g.ReadingType), 0), COALESCE(TRY_CONVERT(numeric(19,5), g.Reading), 0), COALESCE(TRY_CONVERT(numeric(19,5), g.Consumption1), 0)
        FROM load.RowStatus s JOIN gold.UM_HistMR g ON g.RowId = s.GoldRowId WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM30300' AND s.Status IN ('pending','failed','loaded') ORDER BY g.EquipmentID, g.ReadingDate, g.RowId;
        SET @sb = @@ROWCOUNT;
        WITH rb AS (SELECT LocationID, CustomerID, EquipmentID, ReadingDate, ReadingType, Reading, Consumption1, COUNT(*) AS Cnt FROM conv.HistMR WHERE ClientId = @rbClient AND TakeId = @checkTake GROUP BY LocationID, CustomerID, EquipmentID, ReadingDate, ReadingType, Reading, Consumption1),
             sb AS (SELECT LocationID, CustomerID, EquipmentID, ReadingDate, ReadingType, Reading, Consumption1, COUNT(*) AS Cnt FROM conv.HistMR WHERE ClientId = @sbClient AND TakeId = @checkTake GROUP BY LocationID, CustomerID, EquipmentID, ReadingDate, ReadingType, Reading, Consumption1),
             d AS (SELECT * FROM rb EXCEPT SELECT * FROM sb UNION ALL SELECT * FROM sb EXCEPT SELECT * FROM rb)
        SELECT @diff = COUNT(*) FROM d;
        INSERT load.FastPathCheck (ClientId, TakeId, Module, SampleRows, RowByRowRows, SetBasedRows, DifferenceRows, Passed, Message) VALUES (@ClientId, @TakeId, 'UM30300', @SampleRows, @rb, @sb, @diff, CASE WHEN @diff = 0 AND @rb = @sb THEN 1 ELSE 0 END, CASE WHEN @diff = 0 AND @rb = @sb THEN N'historical read fast path matches row-by-row sample' ELSE N'historical read fast path mismatch' END);
        DELETE conv.HistMR WHERE ClientId IN (@rbClient, @sbClient) AND TakeId = @checkTake;
        DELETE conv.Equipment WHERE ClientId IN (@rbClient, @sbClient) AND TakeId = @checkTake;
        IF @diff <> 0 OR @rb <> @sb RAISERROR('Historical read fast-path equivalence check failed.', 16, 1);
        EXEC sys.sp_set_session_context @key = N'ClientId', @value = @ClientId;
        EXEC sys.sp_set_session_context @key = N'TakeId', @value = @TakeId;
        EXEC run.usp_LogEnd @log, @rb, 'Succeeded', 'Historical read fast-path equivalence check passed.';
    END TRY
    BEGIN CATCH
        DECLARE @CheckError nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @CheckError;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE load.usp_LoadModule @ClientId varchar(20), @TakeId varchar(20), @Module varchar(30), @MaxRows int = NULL, @Mode varchar(10) = 'row'
AS
/* Purpose: load one module by explicit metadata order, recording row-level outcomes. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int = 0;
    DECLARE @StepName varchar(128) = 'load.usp_LoadModule.' + @Module;
    EXEC run.usp_LogStart @ClientId, @TakeId, @StepName, @log OUTPUT;
    EXEC sys.sp_set_session_context @key = N'ClientId', @value = @ClientId;
    EXEC sys.sp_set_session_context @key = N'TakeId', @value = @TakeId;
    BEGIN TRY
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UMRM0101'
        BEGIN
            INSERT conv.Customer (ClientId, TakeId, CustomerID, FirstName, LastName, CustomerClassID, Individual)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(CONVERT(varchar(4000), g.FirstName), ''), 30), LEFT(COALESCE(CONVERT(varchar(4000), g.LastName), ''), 30), LEFT(COALESCE(g.CustomerClassID, ''), 15), COALESCE(TRY_CONVERT(tinyint, g.Individual), 0)
            FROM load.RowStatus s JOIN gold.UM_Customer g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UMRM0101' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UMRM0111'
        BEGIN
            INSERT conv.CustomerAddress (ClientId, TakeId, CustomerID, ADRSCODE, ADDRESS1, CityName)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(g.ADRSCODE, ''), 15), LEFT(COALESCE(CONVERT(varchar(4000), g.ADDRESS1), ''), 31), LEFT(COALESCE(CONVERT(varchar(4000), g.City), ''), 31)
            FROM load.RowStatus s JOIN gold.UM_Customer g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UMRM0111' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UM00600'
        BEGIN
            INSERT conv.Location (ClientId, TakeId, LocationID, BillToCust, LocationClass, RouteID)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.LocationID, ''), 15), LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(g.LocationClass, ''), 15), LEFT(COALESCE(g.RouteID, ''), 15)
            FROM load.RowStatus s JOIN gold.UM_Location g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00600' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UM00400'
        BEGIN
            INSERT conv.Equipment (ClientId, TakeId, EquipmentID, EquipmentClass, ServiceCategory, SerialNumber, RemoteID)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.EquipmentID, ''), 15), LEFT(COALESCE(g.EquClassID, ''), 15), COALESCE(TRY_CONVERT(smallint, g.ServiceCategory), 0), LEFT(COALESCE(CONVERT(varchar(4000), g.SerialNo), ''), 31), LEFT(COALESCE(g.RemoteID, ''), 20)
            FROM load.RowStatus s JOIN gold.UM_Equipment g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00400' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UM00300'
        BEGIN
            INSERT conv.Connection (ClientId, TakeId, LocationID, ServiceType, EquipmentID, ConnectStatus, RouteID)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.LocationID, ''), 15), LEFT(COALESCE(g.ServiceType, ''), 15), LEFT(COALESCE(g.EquipmentID, ''), 15), COALESCE(TRY_CONVERT(smallint, g.ConnStatus), 0), LEFT(COALESCE(g.RouteID, ''), 15)
            FROM load.RowStatus s JOIN gold.UM_Connection g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00300' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UM00600H'
        BEGIN
            INSERT conv.LocationHistory (ClientId, TakeId, LocationID, CustomerID, RequestID)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.LocationID, ''), 15), LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(CONVERT(varchar(4000), g.RecordKey), ''), 15)
            FROM load.RowStatus s JOIN gold.UM_LocationHistory g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00600H' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UM20400'
        BEGIN
            INSERT conv.BegBalance (ClientId, TakeId, CustomerID, LocationID, Amount, MiscChargeType, ServiceType)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(g.LocationID, ''), 15), COALESCE(TRY_CONVERT(numeric(19,5), g.BBAmount), 0), LEFT(COALESCE(g.BBMisType, ''), 15), LEFT(COALESCE(g.BBServiceType, ''), 15)
            FROM load.RowStatus s JOIN gold.UM_BegBalance g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM20400' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Mode = 'fast' AND @MaxRows IS NULL AND @Module = 'UM01900'
        BEGIN
            INSERT conv.Deposit (ClientId, TakeId, CustomerID, LocationID, DepositID, DepositAmount)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(g.LocationID, ''), 15), LEFT(COALESCE(g.DepositID, ''), 15), g.DepositAmount
            FROM load.RowStatus s JOIN gold.UM_Deposit g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM01900' AND s.Status IN ('pending','failed') AND s.Attempts < 3;
            SET @rows = @@ROWCOUNT;
            UPDATE load.RowStatus SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND Status IN ('pending','failed') AND Attempts < 3;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Set-based emulator fast path.';
            RETURN;
        END;
        IF @Module = 'UM30300'
        BEGIN
            EXEC load.usp_CheckHistMRFastPath @ClientId, @TakeId, 2000;
            DECLARE @todo_UM30300 TABLE (GoldRowId bigint NOT NULL PRIMARY KEY);
            INSERT @todo_UM30300 (GoldRowId)
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END) s.GoldRowId
            FROM load.RowStatus s JOIN gold.UM_HistMR g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM30300' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.EquipmentID, g.ReadingDate, g.RowId;
            INSERT conv.HistMR (ClientId, TakeId, LocationID, CustomerID, EquipmentID, ReadingDate, ReadingType, Reading, Consumption1)
            SELECT @ClientId, @TakeId, LEFT(COALESCE(g.LocationID, ''), 15), LEFT(COALESCE(g.CustomerID, ''), 15), LEFT(COALESCE(g.EquipmentID, ''), 15), COALESCE(TRY_CONVERT(datetime, g.ReadingDate), CONVERT(datetime, '19000101', 112)), COALESCE(TRY_CONVERT(smallint, g.ReadingType), 0), COALESCE(TRY_CONVERT(numeric(19,5), g.Reading), 0), COALESCE(TRY_CONVERT(numeric(19,5), g.Consumption1), 0)
            FROM @todo_UM30300 t JOIN gold.UM_HistMR g ON g.RowId = t.GoldRowId
            WHERE 1 = 1;
            SET @rows = @@ROWCOUNT;
            UPDATE s SET Status = 'loaded', scError = 0, scMessage = '', Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = SYSUTCDATETIME() FROM load.RowStatus s JOIN @todo_UM30300 t ON t.GoldRowId = s.GoldRowId WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM30300';
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', 'Fast path; equivalent to emulator historical-read insert for validated rows.';
            RETURN;
        END;
        IF @Module = 'UMRM0101'
        BEGIN
            DECLARE @v_UMRM0101_GoldRowId bigint;
            DECLARE @v_UMRM0101_CustomerID char(15);
            DECLARE @v_UMRM0101_umNameTitle smallint;
            DECLARE @v_UMRM0101_umFirstName char(30);
            DECLARE @v_UMRM0101_umMiddleName char(15);
            DECLARE @v_UMRM0101_umLastName char(30);
            DECLARE @v_UMRM0101_umNameSuffix char(4);
            DECLARE @v_UMRM0101_umDateOfBirth datetime;
            DECLARE @v_UMRM0101_umPlaceOfWork char(41);
            DECLARE @v_UMRM0101_umBusinessAs char(30);
            DECLARE @v_UMRM0101_umSIN char(15);
            DECLARE @v_UMRM0101_umCustClassID char(15);
            DECLARE @v_UMRM0101_umAlternateID char(15);
            DECLARE @v_UMRM0101_umInternetPassword char(15);
            DECLARE @v_UMRM0101_umDepositReq tinyint;
            DECLARE @v_UMRM0101_umPenaltyCharged tinyint;
            DECLARE @v_UMRM0101_umRCollectionProc tinyint;
            DECLARE @v_UMRM0101_umBudgetBE tinyint;
            DECLARE @v_UMRM0101_umPreauthPP tinyint;
            DECLARE @v_UMRM0101_CUSTDISC smallint;
            DECLARE @v_UMRM0101_umDelinquencyCode smallint;
            DECLARE @v_UMRM0101_umPaymentTermID char(15);
            DECLARE @v_UMRM0101_umTaxSched char(15);
            DECLARE @v_UMRM0101_umIndividual tinyint;
            DECLARE @v_UMRM0101_umCBCashOnly tinyint;
            DECLARE @v_UMRM0101_umCBBilledCustomer tinyint;
            DECLARE @v_UMRM0101_umUserID char(15);
            DECLARE @v_UMRM0101_umDateCreated datetime;
            DECLARE @v_UMRM0101_umDateModified datetime;
            DECLARE @v_UMRM0101_umUDF1 char(31);
            DECLARE @v_UMRM0101_umUDF2 char(31);
            DECLARE @v_UMRM0101_umPymtRestriction tinyint;
            DECLARE @v_UMRM0101_umExpirationDate datetime;
            DECLARE @v_UMRM0101_Email char(31);
            DECLARE @v_UMRM0101_AddInfo varchar(61);
            DECLARE @v_UMRM0101_scMessage varchar(255);
            DECLARE @v_UMRM0101_scError int;
            DECLARE c_load_UMRM0101 CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [CustomerID],
                   0 AS [umNameTitle],
                   LEFT(COALESCE(CONVERT(varchar(4000), [FirstName]), ''), 30) AS [umFirstName],
                   LEFT(COALESCE(CONVERT(varchar(4000), [MiddleName]), ''), 15) AS [umMiddleName],
                   LEFT(COALESCE(CONVERT(varchar(4000), [LastName]), ''), 30) AS [umLastName],
                   '' AS [umNameSuffix],
                   COALESCE(TRY_CONVERT(datetime, [DateOfBirth]), CONVERT(datetime, '19000101', 112)) AS [umDateOfBirth],
                   LEFT(COALESCE(CONVERT(varchar(4000), [PlaceOfWork]), ''), 41) AS [umPlaceOfWork],
                   '' AS [umBusinessAs],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SIN]), ''), 15) AS [umSIN],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerClassID]), ''), 15) AS [umCustClassID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [AlternateID]), ''), 15) AS [umAlternateID],
                   '' AS [umInternetPassword],
                   0 AS [umDepositReq],
                   0 AS [umPenaltyCharged],
                   0 AS [umRCollectionProc],
                   0 AS [umBudgetBE],
                   0 AS [umPreauthPP],
                   0 AS [CUSTDISC],
                   0 AS [umDelinquencyCode],
                   LEFT(COALESCE(CONVERT(varchar(4000), [PaymentTermID]), ''), 15) AS [umPaymentTermID],
                   '' AS [umTaxSched],
                   COALESCE(TRY_CONVERT(tinyint, [Individual]), 0) AS [umIndividual],
                   0 AS [umCBCashOnly],
                   0 AS [umCBBilledCustomer],
                   '' AS [umUserID],
                   CONVERT(datetime, '19000101', 112) AS [umDateCreated],
                   CONVERT(datetime, '19000101', 112) AS [umDateModified],
                   '' AS [umUDF1],
                   '' AS [umUDF2],
                   0 AS [umPymtRestriction],
                   CONVERT(datetime, '19000101', 112) AS [umExpirationDate],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Email]), ''), 31) AS [Email],
                   '' AS [AddInfo]
            FROM load.RowStatus s JOIN gold.UM_Customer g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UMRM0101' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.CustomerID;
            OPEN c_load_UMRM0101;
            FETCH NEXT FROM c_load_UMRM0101 INTO @v_UMRM0101_GoldRowId, @v_UMRM0101_CustomerID, @v_UMRM0101_umNameTitle, @v_UMRM0101_umFirstName, @v_UMRM0101_umMiddleName, @v_UMRM0101_umLastName, @v_UMRM0101_umNameSuffix, @v_UMRM0101_umDateOfBirth, @v_UMRM0101_umPlaceOfWork, @v_UMRM0101_umBusinessAs, @v_UMRM0101_umSIN, @v_UMRM0101_umCustClassID, @v_UMRM0101_umAlternateID, @v_UMRM0101_umInternetPassword, @v_UMRM0101_umDepositReq, @v_UMRM0101_umPenaltyCharged, @v_UMRM0101_umRCollectionProc, @v_UMRM0101_umBudgetBE, @v_UMRM0101_umPreauthPP, @v_UMRM0101_CUSTDISC, @v_UMRM0101_umDelinquencyCode, @v_UMRM0101_umPaymentTermID, @v_UMRM0101_umTaxSched, @v_UMRM0101_umIndividual, @v_UMRM0101_umCBCashOnly, @v_UMRM0101_umCBBilledCustomer, @v_UMRM0101_umUserID, @v_UMRM0101_umDateCreated, @v_UMRM0101_umDateModified, @v_UMRM0101_umUDF1, @v_UMRM0101_umUDF2, @v_UMRM0101_umPymtRestriction, @v_UMRM0101_umExpirationDate, @v_UMRM0101_Email, @v_UMRM0101_AddInfo;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UMRM0101_scError = 0;
                SET @v_UMRM0101_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateCustomer @CustomerID = @CustomerID, @umNameTitle = @umNameTitle, @umFirstName = @umFirstName, @umMiddleName = @umMiddleName, @umLastName = @umLastName, @umNameSuffix = @umNameSuffix, @umDateOfBirth = @umDateOfBirth, @umPlaceOfWork = @umPlaceOfWork, @umBusinessAs = @umBusinessAs, @umSIN = @umSIN, @umCustClassID = @umCustClassID, @umAlternateID = @umAlternateID, @umInternetPassword = @umInternetPassword, @umDepositReq = @umDepositReq, @umPenaltyCharged = @umPenaltyCharged, @umRCollectionProc = @umRCollectionProc, @umBudgetBE = @umBudgetBE, @umPreauthPP = @umPreauthPP, @CUSTDISC = @CUSTDISC, @umDelinquencyCode = @umDelinquencyCode, @umPaymentTermID = @umPaymentTermID, @umTaxSched = @umTaxSched, @umIndividual = @umIndividual, @umCBCashOnly = @umCBCashOnly, @umCBBilledCustomer = @umCBBilledCustomer, @umUserID = @umUserID, @umDateCreated = @umDateCreated, @umDateModified = @umDateModified, @umUDF1 = @umUDF1, @umUDF2 = @umUDF2, @umPymtRestriction = @umPymtRestriction, @umExpirationDate = @umExpirationDate, @Email = @Email, @AddInfo = @AddInfo, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@CustomerID char(15), @umNameTitle smallint, @umFirstName char(30), @umMiddleName char(15), @umLastName char(30), @umNameSuffix char(4), @umDateOfBirth datetime, @umPlaceOfWork char(41), @umBusinessAs char(30), @umSIN char(15), @umCustClassID char(15), @umAlternateID char(15), @umInternetPassword char(15), @umDepositReq tinyint, @umPenaltyCharged tinyint, @umRCollectionProc tinyint, @umBudgetBE tinyint, @umPreauthPP tinyint, @CUSTDISC smallint, @umDelinquencyCode smallint, @umPaymentTermID char(15), @umTaxSched char(15), @umIndividual tinyint, @umCBCashOnly tinyint, @umCBBilledCustomer tinyint, @umUserID char(15), @umDateCreated datetime, @umDateModified datetime, @umUDF1 char(31), @umUDF2 char(31), @umPymtRestriction tinyint, @umExpirationDate datetime, @Email char(31), @AddInfo varchar(61), @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @CustomerID = @v_UMRM0101_CustomerID, @umNameTitle = @v_UMRM0101_umNameTitle, @umFirstName = @v_UMRM0101_umFirstName, @umMiddleName = @v_UMRM0101_umMiddleName, @umLastName = @v_UMRM0101_umLastName, @umNameSuffix = @v_UMRM0101_umNameSuffix, @umDateOfBirth = @v_UMRM0101_umDateOfBirth, @umPlaceOfWork = @v_UMRM0101_umPlaceOfWork, @umBusinessAs = @v_UMRM0101_umBusinessAs, @umSIN = @v_UMRM0101_umSIN, @umCustClassID = @v_UMRM0101_umCustClassID, @umAlternateID = @v_UMRM0101_umAlternateID, @umInternetPassword = @v_UMRM0101_umInternetPassword, @umDepositReq = @v_UMRM0101_umDepositReq, @umPenaltyCharged = @v_UMRM0101_umPenaltyCharged, @umRCollectionProc = @v_UMRM0101_umRCollectionProc, @umBudgetBE = @v_UMRM0101_umBudgetBE, @umPreauthPP = @v_UMRM0101_umPreauthPP, @CUSTDISC = @v_UMRM0101_CUSTDISC, @umDelinquencyCode = @v_UMRM0101_umDelinquencyCode, @umPaymentTermID = @v_UMRM0101_umPaymentTermID, @umTaxSched = @v_UMRM0101_umTaxSched, @umIndividual = @v_UMRM0101_umIndividual, @umCBCashOnly = @v_UMRM0101_umCBCashOnly, @umCBBilledCustomer = @v_UMRM0101_umCBBilledCustomer, @umUserID = @v_UMRM0101_umUserID, @umDateCreated = @v_UMRM0101_umDateCreated, @umDateModified = @v_UMRM0101_umDateModified, @umUDF1 = @v_UMRM0101_umUDF1, @umUDF2 = @v_UMRM0101_umUDF2, @umPymtRestriction = @v_UMRM0101_umPymtRestriction, @umExpirationDate = @v_UMRM0101_umExpirationDate, @Email = @v_UMRM0101_Email, @AddInfo = @v_UMRM0101_AddInfo, @scMessage = @v_UMRM0101_scMessage OUTPUT, @scError = @v_UMRM0101_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UMRM0101_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UMRM0101_scError, 0), scMessage = @v_UMRM0101_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UMRM0101_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UMRM0101_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UMRM0101_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UMRM0101 INTO @v_UMRM0101_GoldRowId, @v_UMRM0101_CustomerID, @v_UMRM0101_umNameTitle, @v_UMRM0101_umFirstName, @v_UMRM0101_umMiddleName, @v_UMRM0101_umLastName, @v_UMRM0101_umNameSuffix, @v_UMRM0101_umDateOfBirth, @v_UMRM0101_umPlaceOfWork, @v_UMRM0101_umBusinessAs, @v_UMRM0101_umSIN, @v_UMRM0101_umCustClassID, @v_UMRM0101_umAlternateID, @v_UMRM0101_umInternetPassword, @v_UMRM0101_umDepositReq, @v_UMRM0101_umPenaltyCharged, @v_UMRM0101_umRCollectionProc, @v_UMRM0101_umBudgetBE, @v_UMRM0101_umPreauthPP, @v_UMRM0101_CUSTDISC, @v_UMRM0101_umDelinquencyCode, @v_UMRM0101_umPaymentTermID, @v_UMRM0101_umTaxSched, @v_UMRM0101_umIndividual, @v_UMRM0101_umCBCashOnly, @v_UMRM0101_umCBBilledCustomer, @v_UMRM0101_umUserID, @v_UMRM0101_umDateCreated, @v_UMRM0101_umDateModified, @v_UMRM0101_umUDF1, @v_UMRM0101_umUDF2, @v_UMRM0101_umPymtRestriction, @v_UMRM0101_umExpirationDate, @v_UMRM0101_Email, @v_UMRM0101_AddInfo;
            END;
            CLOSE c_load_UMRM0101;
            DEALLOCATE c_load_UMRM0101;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        IF @Module = 'UMRM0111'
        BEGIN
            DECLARE @v_UMRM0111_GoldRowId bigint;
            DECLARE @v_UMRM0111_UserID char(15);
            DECLARE @v_UMRM0111_CustomerID char(15);
            DECLARE @v_UMRM0111_ContactPerson char(31);
            DECLARE @v_UMRM0111_Phone1 char(21);
            DECLARE @v_UMRM0111_Phone2 char(21);
            DECLARE @v_UMRM0111_Phone3 char(21);
            DECLARE @v_UMRM0111_Fax char(21);
            DECLARE @v_UMRM0111_BillToAddress tinyint;
            DECLARE @v_UMRM0111_PrintContactPerson tinyint;
            DECLARE @v_UMRM0111_ADRSCODE char(15);
            DECLARE @v_UMRM0111_Phone1Type int;
            DECLARE @v_UMRM0111_Phone2Type int;
            DECLARE @v_UMRM0111_Phone3Type int;
            DECLARE @v_UMRM0111_AddressCateg smallint;
            DECLARE @v_UMRM0111_StreetNumber char(9);
            DECLARE @v_UMRM0111_StreetNumberLng int;
            DECLARE @v_UMRM0111_StreetNumberSuffix char(3);
            DECLARE @v_UMRM0111_StreetName char(31);
            DECLARE @v_UMRM0111_StreetType char(7);
            DECLARE @v_UMRM0111_StreetDirectionP char(3);
            DECLARE @v_UMRM0111_StreetDirection char(3);
            DECLARE @v_UMRM0111_AptNumber char(7);
            DECLARE @v_UMRM0111_AptDesc char(7);
            DECLARE @v_UMRM0111_UnitDesig char(7);
            DECLARE @v_UMRM0111_ZipCode char(11);
            DECLARE @v_UMRM0111_CityName char(31);
            DECLARE @v_UMRM0111_STATE char(29);
            DECLARE @v_UMRM0111_COUNTRY char(21);
            DECLARE @v_UMRM0111_Postal_Walk char(9);
            DECLARE @v_UMRM0111_PostalWalkVer char(1);
            DECLARE @v_UMRM0111_CreateDate datetime;
            DECLARE @v_UMRM0111_AptNumberPlus char(7);
            DECLARE @v_UMRM0111_ADDRESS1 char(31);
            DECLARE @v_UMRM0111_ADDRESS2 char(31);
            DECLARE @v_UMRM0111_ADDRESS3 char(31);
            DECLARE @v_UMRM0111_scMessage varchar(255);
            DECLARE @v_UMRM0111_scError int;
            DECLARE c_load_UMRM0111 CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   '' AS [UserID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [CustomerID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ContactPerson]), ''), 31) AS [ContactPerson],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Phone1]), ''), 21) AS [Phone1],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Phone2]), ''), 21) AS [Phone2],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Phone3]), ''), 21) AS [Phone3],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Fax]), ''), 21) AS [Fax],
                   0 AS [BillToAddress],
                   COALESCE(TRY_CONVERT(tinyint, [ContactPerson]), 0) AS [PrintContactPerson],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ADRSCODE]), ''), 15) AS [ADRSCODE],
                   COALESCE(TRY_CONVERT(int, [Phone1]), 1) AS [Phone1Type],
                   COALESCE(TRY_CONVERT(int, [Phone2]), 2) AS [Phone2Type],
                   COALESCE(TRY_CONVERT(int, [Phone3]), 3) AS [Phone3Type],
                   0 AS [AddressCateg],
                   '' AS [StreetNumber],
                   0 AS [StreetNumberLng],
                   '' AS [StreetNumberSuffix],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ADDRESS1]), ''), 31) AS [StreetName],
                   '' AS [StreetType],
                   '' AS [StreetDirectionP],
                   '' AS [StreetDirection],
                   '' AS [AptNumber],
                   '' AS [AptDesc],
                   '' AS [UnitDesig],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Zip]), ''), 11) AS [ZipCode],
                   LEFT(COALESCE(CONVERT(varchar(4000), [City]), ''), 31) AS [CityName],
                   LEFT(COALESCE(CONVERT(varchar(4000), [STATE]), ''), 29) AS [STATE],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Country]), ''), 21) AS [COUNTRY],
                   '' AS [Postal_Walk],
                   '' AS [PostalWalkVer],
                   CONVERT(datetime, '19000101', 112) AS [CreateDate],
                   '' AS [AptNumberPlus],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ADDRESS1]), ''), 31) AS [ADDRESS1],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ADDRESS2]), ''), 31) AS [ADDRESS2],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ADDRESS3]), ''), 31) AS [ADDRESS3]
            FROM load.RowStatus s JOIN gold.UM_Customer g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UMRM0111' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.CustomerID, g.ADRSCODE;
            OPEN c_load_UMRM0111;
            FETCH NEXT FROM c_load_UMRM0111 INTO @v_UMRM0111_GoldRowId, @v_UMRM0111_UserID, @v_UMRM0111_CustomerID, @v_UMRM0111_ContactPerson, @v_UMRM0111_Phone1, @v_UMRM0111_Phone2, @v_UMRM0111_Phone3, @v_UMRM0111_Fax, @v_UMRM0111_BillToAddress, @v_UMRM0111_PrintContactPerson, @v_UMRM0111_ADRSCODE, @v_UMRM0111_Phone1Type, @v_UMRM0111_Phone2Type, @v_UMRM0111_Phone3Type, @v_UMRM0111_AddressCateg, @v_UMRM0111_StreetNumber, @v_UMRM0111_StreetNumberLng, @v_UMRM0111_StreetNumberSuffix, @v_UMRM0111_StreetName, @v_UMRM0111_StreetType, @v_UMRM0111_StreetDirectionP, @v_UMRM0111_StreetDirection, @v_UMRM0111_AptNumber, @v_UMRM0111_AptDesc, @v_UMRM0111_UnitDesig, @v_UMRM0111_ZipCode, @v_UMRM0111_CityName, @v_UMRM0111_STATE, @v_UMRM0111_COUNTRY, @v_UMRM0111_Postal_Walk, @v_UMRM0111_PostalWalkVer, @v_UMRM0111_CreateDate, @v_UMRM0111_AptNumberPlus, @v_UMRM0111_ADDRESS1, @v_UMRM0111_ADDRESS2, @v_UMRM0111_ADDRESS3;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UMRM0111_scError = 0;
                SET @v_UMRM0111_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateCustomerAddress @UserID = @UserID, @CustomerID = @CustomerID, @ContactPerson = @ContactPerson, @Phone1 = @Phone1, @Phone2 = @Phone2, @Phone3 = @Phone3, @Fax = @Fax, @BillToAddress = @BillToAddress, @PrintContactPerson = @PrintContactPerson, @ADRSCODE = @ADRSCODE, @Phone1Type = @Phone1Type, @Phone2Type = @Phone2Type, @Phone3Type = @Phone3Type, @AddressCateg = @AddressCateg, @StreetNumber = @StreetNumber, @StreetNumberLng = @StreetNumberLng, @StreetNumberSuffix = @StreetNumberSuffix, @StreetName = @StreetName, @StreetType = @StreetType, @StreetDirectionP = @StreetDirectionP, @StreetDirection = @StreetDirection, @AptNumber = @AptNumber, @AptDesc = @AptDesc, @UnitDesig = @UnitDesig, @ZipCode = @ZipCode, @CityName = @CityName, @STATE = @STATE, @COUNTRY = @COUNTRY, @Postal_Walk = @Postal_Walk, @PostalWalkVer = @PostalWalkVer, @CreateDate = @CreateDate, @AptNumberPlus = @AptNumberPlus, @ADDRESS1 = @ADDRESS1, @ADDRESS2 = @ADDRESS2, @ADDRESS3 = @ADDRESS3, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@UserID char(15), @CustomerID char(15), @ContactPerson char(31), @Phone1 char(21), @Phone2 char(21), @Phone3 char(21), @Fax char(21), @BillToAddress tinyint, @PrintContactPerson tinyint, @ADRSCODE char(15), @Phone1Type int, @Phone2Type int, @Phone3Type int, @AddressCateg smallint, @StreetNumber char(9), @StreetNumberLng int, @StreetNumberSuffix char(3), @StreetName char(31), @StreetType char(7), @StreetDirectionP char(3), @StreetDirection char(3), @AptNumber char(7), @AptDesc char(7), @UnitDesig char(7), @ZipCode char(11), @CityName char(31), @STATE char(29), @COUNTRY char(21), @Postal_Walk char(9), @PostalWalkVer char(1), @CreateDate datetime, @AptNumberPlus char(7), @ADDRESS1 char(31), @ADDRESS2 char(31), @ADDRESS3 char(31), @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @UserID = @v_UMRM0111_UserID, @CustomerID = @v_UMRM0111_CustomerID, @ContactPerson = @v_UMRM0111_ContactPerson, @Phone1 = @v_UMRM0111_Phone1, @Phone2 = @v_UMRM0111_Phone2, @Phone3 = @v_UMRM0111_Phone3, @Fax = @v_UMRM0111_Fax, @BillToAddress = @v_UMRM0111_BillToAddress, @PrintContactPerson = @v_UMRM0111_PrintContactPerson, @ADRSCODE = @v_UMRM0111_ADRSCODE, @Phone1Type = @v_UMRM0111_Phone1Type, @Phone2Type = @v_UMRM0111_Phone2Type, @Phone3Type = @v_UMRM0111_Phone3Type, @AddressCateg = @v_UMRM0111_AddressCateg, @StreetNumber = @v_UMRM0111_StreetNumber, @StreetNumberLng = @v_UMRM0111_StreetNumberLng, @StreetNumberSuffix = @v_UMRM0111_StreetNumberSuffix, @StreetName = @v_UMRM0111_StreetName, @StreetType = @v_UMRM0111_StreetType, @StreetDirectionP = @v_UMRM0111_StreetDirectionP, @StreetDirection = @v_UMRM0111_StreetDirection, @AptNumber = @v_UMRM0111_AptNumber, @AptDesc = @v_UMRM0111_AptDesc, @UnitDesig = @v_UMRM0111_UnitDesig, @ZipCode = @v_UMRM0111_ZipCode, @CityName = @v_UMRM0111_CityName, @STATE = @v_UMRM0111_STATE, @COUNTRY = @v_UMRM0111_COUNTRY, @Postal_Walk = @v_UMRM0111_Postal_Walk, @PostalWalkVer = @v_UMRM0111_PostalWalkVer, @CreateDate = @v_UMRM0111_CreateDate, @AptNumberPlus = @v_UMRM0111_AptNumberPlus, @ADDRESS1 = @v_UMRM0111_ADDRESS1, @ADDRESS2 = @v_UMRM0111_ADDRESS2, @ADDRESS3 = @v_UMRM0111_ADDRESS3, @scMessage = @v_UMRM0111_scMessage OUTPUT, @scError = @v_UMRM0111_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UMRM0111_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UMRM0111_scError, 0), scMessage = @v_UMRM0111_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UMRM0111_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UMRM0111_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UMRM0111_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UMRM0111 INTO @v_UMRM0111_GoldRowId, @v_UMRM0111_UserID, @v_UMRM0111_CustomerID, @v_UMRM0111_ContactPerson, @v_UMRM0111_Phone1, @v_UMRM0111_Phone2, @v_UMRM0111_Phone3, @v_UMRM0111_Fax, @v_UMRM0111_BillToAddress, @v_UMRM0111_PrintContactPerson, @v_UMRM0111_ADRSCODE, @v_UMRM0111_Phone1Type, @v_UMRM0111_Phone2Type, @v_UMRM0111_Phone3Type, @v_UMRM0111_AddressCateg, @v_UMRM0111_StreetNumber, @v_UMRM0111_StreetNumberLng, @v_UMRM0111_StreetNumberSuffix, @v_UMRM0111_StreetName, @v_UMRM0111_StreetType, @v_UMRM0111_StreetDirectionP, @v_UMRM0111_StreetDirection, @v_UMRM0111_AptNumber, @v_UMRM0111_AptDesc, @v_UMRM0111_UnitDesig, @v_UMRM0111_ZipCode, @v_UMRM0111_CityName, @v_UMRM0111_STATE, @v_UMRM0111_COUNTRY, @v_UMRM0111_Postal_Walk, @v_UMRM0111_PostalWalkVer, @v_UMRM0111_CreateDate, @v_UMRM0111_AptNumberPlus, @v_UMRM0111_ADDRESS1, @v_UMRM0111_ADDRESS2, @v_UMRM0111_ADDRESS3;
            END;
            CLOSE c_load_UMRM0111;
            DEALLOCATE c_load_UMRM0111;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        IF @Module = 'UM00600'
        BEGIN
            DECLARE @v_UM00600_GoldRowId bigint;
            DECLARE @v_UM00600_UserID char(15);
            DECLARE @v_UM00600_LocationID char(15);
            DECLARE @v_UM00600_LocationType smallint;
            DECLARE @v_UM00600_LocationClass char(15);
            DECLARE @v_UM00600_BudgetPlanEligibility tinyint;
            DECLARE @v_UM00600_AddressType smallint;
            DECLARE @v_UM00600_ZoneID char(15);
            DECLARE @v_UM00600_BillToCust char(15);
            DECLARE @v_UM00600_BillToCustType smallint;
            DECLARE @v_UM00600_Owner char(15);
            DECLARE @v_UM00600_TenantCustNum char(15);
            DECLARE @v_UM00600_AccumType smallint;
            DECLARE @v_UM00600_AccumMasterID char(15);
            DECLARE @v_UM00600_MinBill tinyint;
            DECLARE @v_UM00600_MaxBill tinyint;
            DECLARE @v_UM00600_LastBill char(15);
            DECLARE @v_UM00600_LastStatementDate datetime;
            DECLARE @v_UM00600_LastStatementAmount numeric(19, 5);
            DECLARE @v_UM00600_ServiceCategory smallint;
            DECLARE @v_UM00600_PenaltyID char(15);
            DECLARE @v_UM00600_RecvAcct int;
            DECLARE @v_UM00600_ElectricTaxSched varchar(15);
            DECLARE @v_UM00600_WaterTaxSched varchar(15);
            DECLARE @v_UM00600_SewerTaxSched varchar(15);
            DECLARE @v_UM00600_GasTaxSched varchar(15);
            DECLARE @v_UM00600_PhoneTaxSched varchar(15);
            DECLARE @v_UM00600_OtherTaxSched varchar(15);
            DECLARE @v_UM00600_PropertyTaxTaxSched varchar(15);
            DECLARE @v_UM00600_CableTaxSched varchar(15);
            DECLARE @v_UM00600_InternetTaxSched varchar(15);
            DECLARE @v_UM00600_FireProtectionTaxSched varchar(15);
            DECLARE @v_UM00600_SanitationTaxSched varchar(15);
            DECLARE @v_UM00600_PropaneTaxSched varchar(15);
            DECLARE @v_UM00600_LocDefined1 char(31);
            DECLARE @v_UM00600_LocDefined2 char(31);
            DECLARE @v_UM00600_ThirdPartyDesc char(31);
            DECLARE @v_UM00600_AddressCateg smallint;
            DECLARE @v_UM00600_StreetNumber char(9);
            DECLARE @v_UM00600_StreetNumberLng int;
            DECLARE @v_UM00600_StreetNumberSuffix char(3);
            DECLARE @v_UM00600_StreetName char(31);
            DECLARE @v_UM00600_StreetType char(7);
            DECLARE @v_UM00600_StreetDirectionP char(3);
            DECLARE @v_UM00600_StreetDirection char(3);
            DECLARE @v_UM00600_AptNumber char(7);
            DECLARE @v_UM00600_AptDesc char(7);
            DECLARE @v_UM00600_UnitDesig char(7);
            DECLARE @v_UM00600_ZipCode char(11);
            DECLARE @v_UM00600_CityName char(31);
            DECLARE @v_UM00600_STATE char(29);
            DECLARE @v_UM00600_COUNTRY char(21);
            DECLARE @v_UM00600_Postal_Walk char(9);
            DECLARE @v_UM00600_PostalWalkVer char(1);
            DECLARE @v_UM00600_CreateDate datetime;
            DECLARE @v_UM00600_AptNumberPlus char(7);
            DECLARE @v_UM00600_ADDRESS1 char(31);
            DECLARE @v_UM00600_ADDRESS2 char(31);
            DECLARE @v_UM00600_ADDRESS3 char(31);
            DECLARE @v_UM00600_ServicePlanNumber char(21);
            DECLARE @v_UM00600_ServiceLotNumber char(21);
            DECLARE @v_UM00600_KeyNum char(21);
            DECLARE @v_UM00600_ResidentialUnits smallint;
            DECLARE @v_UM00600_SICCode char(11);
            DECLARE @v_UM00600_AssessorID char(25);
            DECLARE @v_UM00600_LandParcelID char(25);
            DECLARE @v_UM00600_DefaultInterim tinyint;
            DECLARE @v_UM00600_RouteID char(15);
            DECLARE @v_UM00600_scMessage varchar(255);
            DECLARE @v_UM00600_scError int;
            DECLARE c_load_UM00600 CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   '' AS [UserID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [LocationID]), ''), 15) AS [LocationID],
                   0 AS [LocationType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [LocationClass]), ''), 15) AS [LocationClass],
                   0 AS [BudgetPlanEligibility],
                   0 AS [AddressType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ZoneID]), ''), 15) AS [ZoneID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [BillToCust],
                   0 AS [BillToCustType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [Owner],
                   '' AS [TenantCustNum],
                   0 AS [AccumType],
                   '' AS [AccumMasterID],
                   0 AS [MinBill],
                   0 AS [MaxBill],
                   '' AS [LastBill],
                   CONVERT(datetime, '19000101', 112) AS [LastStatementDate],
                   0 AS [LastStatementAmount],
                   0 AS [ServiceCategory],
                   '' AS [PenaltyID],
                   0 AS [RecvAcct],
                   '' AS [ElectricTaxSched],
                   '' AS [WaterTaxSched],
                   '' AS [SewerTaxSched],
                   '' AS [GasTaxSched],
                   '' AS [PhoneTaxSched],
                   '' AS [OtherTaxSched],
                   '' AS [PropertyTaxTaxSched],
                   '' AS [CableTaxSched],
                   '' AS [InternetTaxSched],
                   '' AS [FireProtectionTaxSched],
                   '' AS [SanitationTaxSched],
                   '' AS [PropaneTaxSched],
                   LEFT(COALESCE(CONVERT(varchar(4000), [UUDF1]), ''), 31) AS [LocDefined1],
                   LEFT(COALESCE(CONVERT(varchar(4000), [UUDF2]), ''), 31) AS [LocDefined2],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ThirdPartyDesc]), ''), 31) AS [ThirdPartyDesc],
                   0 AS [AddressCateg],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SStreetNumber]), ''), 9) AS [StreetNumber],
                   0 AS [StreetNumberLng],
                   '' AS [StreetNumberSuffix],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SStreetName]), ''), 31) AS [StreetName],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SStreetType]), ''), 7) AS [StreetType],
                   '' AS [StreetDirectionP],
                   '' AS [StreetDirection],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SAptNo]), ''), 7) AS [AptNumber],
                   '' AS [AptDesc],
                   '' AS [UnitDesig],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SZip]), ''), 11) AS [ZipCode],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SCity]), ''), 31) AS [CityName],
                   '' AS [STATE],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SCountry]), ''), 21) AS [COUNTRY],
                   '' AS [Postal_Walk],
                   '' AS [PostalWalkVer],
                   CONVERT(datetime, '19000101', 112) AS [CreateDate],
                   '' AS [AptNumberPlus],
                   '' AS [ADDRESS1],
                   '' AS [ADDRESS2],
                   '' AS [ADDRESS3],
                   '' AS [ServicePlanNumber],
                   '' AS [ServiceLotNumber],
                   '' AS [KeyNum],
                   COALESCE(TRY_CONVERT(smallint, [NoResUnits]), 0) AS [ResidentialUnits],
                   '' AS [SICCode],
                   '' AS [AssessorID],
                   '' AS [LandParcelID],
                   0 AS [DefaultInterim],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RouteID]), ''), 15) AS [RouteID]
            FROM load.RowStatus s JOIN gold.UM_Location g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00600' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.LocationID;
            OPEN c_load_UM00600;
            FETCH NEXT FROM c_load_UM00600 INTO @v_UM00600_GoldRowId, @v_UM00600_UserID, @v_UM00600_LocationID, @v_UM00600_LocationType, @v_UM00600_LocationClass, @v_UM00600_BudgetPlanEligibility, @v_UM00600_AddressType, @v_UM00600_ZoneID, @v_UM00600_BillToCust, @v_UM00600_BillToCustType, @v_UM00600_Owner, @v_UM00600_TenantCustNum, @v_UM00600_AccumType, @v_UM00600_AccumMasterID, @v_UM00600_MinBill, @v_UM00600_MaxBill, @v_UM00600_LastBill, @v_UM00600_LastStatementDate, @v_UM00600_LastStatementAmount, @v_UM00600_ServiceCategory, @v_UM00600_PenaltyID, @v_UM00600_RecvAcct, @v_UM00600_ElectricTaxSched, @v_UM00600_WaterTaxSched, @v_UM00600_SewerTaxSched, @v_UM00600_GasTaxSched, @v_UM00600_PhoneTaxSched, @v_UM00600_OtherTaxSched, @v_UM00600_PropertyTaxTaxSched, @v_UM00600_CableTaxSched, @v_UM00600_InternetTaxSched, @v_UM00600_FireProtectionTaxSched, @v_UM00600_SanitationTaxSched, @v_UM00600_PropaneTaxSched, @v_UM00600_LocDefined1, @v_UM00600_LocDefined2, @v_UM00600_ThirdPartyDesc, @v_UM00600_AddressCateg, @v_UM00600_StreetNumber, @v_UM00600_StreetNumberLng, @v_UM00600_StreetNumberSuffix, @v_UM00600_StreetName, @v_UM00600_StreetType, @v_UM00600_StreetDirectionP, @v_UM00600_StreetDirection, @v_UM00600_AptNumber, @v_UM00600_AptDesc, @v_UM00600_UnitDesig, @v_UM00600_ZipCode, @v_UM00600_CityName, @v_UM00600_STATE, @v_UM00600_COUNTRY, @v_UM00600_Postal_Walk, @v_UM00600_PostalWalkVer, @v_UM00600_CreateDate, @v_UM00600_AptNumberPlus, @v_UM00600_ADDRESS1, @v_UM00600_ADDRESS2, @v_UM00600_ADDRESS3, @v_UM00600_ServicePlanNumber, @v_UM00600_ServiceLotNumber, @v_UM00600_KeyNum, @v_UM00600_ResidentialUnits, @v_UM00600_SICCode, @v_UM00600_AssessorID, @v_UM00600_LandParcelID, @v_UM00600_DefaultInterim, @v_UM00600_RouteID;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UM00600_scError = 0;
                SET @v_UM00600_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateLocation @UserID = @UserID, @LocationID = @LocationID, @LocationType = @LocationType, @LocationClass = @LocationClass, @BudgetPlanEligibility = @BudgetPlanEligibility, @AddressType = @AddressType, @ZoneID = @ZoneID, @BillToCust = @BillToCust, @BillToCustType = @BillToCustType, @Owner = @Owner, @TenantCustNum = @TenantCustNum, @AccumType = @AccumType, @AccumMasterID = @AccumMasterID, @MinBill = @MinBill, @MaxBill = @MaxBill, @LastBill = @LastBill, @LastStatementDate = @LastStatementDate, @LastStatementAmount = @LastStatementAmount, @ServiceCategory = @ServiceCategory, @PenaltyID = @PenaltyID, @RecvAcct = @RecvAcct, @ElectricTaxSched = @ElectricTaxSched, @WaterTaxSched = @WaterTaxSched, @SewerTaxSched = @SewerTaxSched, @GasTaxSched = @GasTaxSched, @PhoneTaxSched = @PhoneTaxSched, @OtherTaxSched = @OtherTaxSched, @PropertyTaxTaxSched = @PropertyTaxTaxSched, @CableTaxSched = @CableTaxSched, @InternetTaxSched = @InternetTaxSched, @FireProtectionTaxSched = @FireProtectionTaxSched, @SanitationTaxSched = @SanitationTaxSched, @PropaneTaxSched = @PropaneTaxSched, @LocDefined1 = @LocDefined1, @LocDefined2 = @LocDefined2, @ThirdPartyDesc = @ThirdPartyDesc, @AddressCateg = @AddressCateg, @StreetNumber = @StreetNumber, @StreetNumberLng = @StreetNumberLng, @StreetNumberSuffix = @StreetNumberSuffix, @StreetName = @StreetName, @StreetType = @StreetType, @StreetDirectionP = @StreetDirectionP, @StreetDirection = @StreetDirection, @AptNumber = @AptNumber, @AptDesc = @AptDesc, @UnitDesig = @UnitDesig, @ZipCode = @ZipCode, @CityName = @CityName, @STATE = @STATE, @COUNTRY = @COUNTRY, @Postal_Walk = @Postal_Walk, @PostalWalkVer = @PostalWalkVer, @CreateDate = @CreateDate, @AptNumberPlus = @AptNumberPlus, @ADDRESS1 = @ADDRESS1, @ADDRESS2 = @ADDRESS2, @ADDRESS3 = @ADDRESS3, @ServicePlanNumber = @ServicePlanNumber, @ServiceLotNumber = @ServiceLotNumber, @KeyNum = @KeyNum, @ResidentialUnits = @ResidentialUnits, @SICCode = @SICCode, @AssessorID = @AssessorID, @LandParcelID = @LandParcelID, @DefaultInterim = @DefaultInterim, @RouteID = @RouteID, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@UserID char(15), @LocationID char(15), @LocationType smallint, @LocationClass char(15), @BudgetPlanEligibility tinyint, @AddressType smallint, @ZoneID char(15), @BillToCust char(15), @BillToCustType smallint, @Owner char(15), @TenantCustNum char(15), @AccumType smallint, @AccumMasterID char(15), @MinBill tinyint, @MaxBill tinyint, @LastBill char(15), @LastStatementDate datetime, @LastStatementAmount numeric(19, 5), @ServiceCategory smallint, @PenaltyID char(15), @RecvAcct int, @ElectricTaxSched varchar(15), @WaterTaxSched varchar(15), @SewerTaxSched varchar(15), @GasTaxSched varchar(15), @PhoneTaxSched varchar(15), @OtherTaxSched varchar(15), @PropertyTaxTaxSched varchar(15), @CableTaxSched varchar(15), @InternetTaxSched varchar(15), @FireProtectionTaxSched varchar(15), @SanitationTaxSched varchar(15), @PropaneTaxSched varchar(15), @LocDefined1 char(31), @LocDefined2 char(31), @ThirdPartyDesc char(31), @AddressCateg smallint, @StreetNumber char(9), @StreetNumberLng int, @StreetNumberSuffix char(3), @StreetName char(31), @StreetType char(7), @StreetDirectionP char(3), @StreetDirection char(3), @AptNumber char(7), @AptDesc char(7), @UnitDesig char(7), @ZipCode char(11), @CityName char(31), @STATE char(29), @COUNTRY char(21), @Postal_Walk char(9), @PostalWalkVer char(1), @CreateDate datetime, @AptNumberPlus char(7), @ADDRESS1 char(31), @ADDRESS2 char(31), @ADDRESS3 char(31), @ServicePlanNumber char(21), @ServiceLotNumber char(21), @KeyNum char(21), @ResidentialUnits smallint, @SICCode char(11), @AssessorID char(25), @LandParcelID char(25), @DefaultInterim tinyint, @RouteID char(15), @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @UserID = @v_UM00600_UserID, @LocationID = @v_UM00600_LocationID, @LocationType = @v_UM00600_LocationType, @LocationClass = @v_UM00600_LocationClass, @BudgetPlanEligibility = @v_UM00600_BudgetPlanEligibility, @AddressType = @v_UM00600_AddressType, @ZoneID = @v_UM00600_ZoneID, @BillToCust = @v_UM00600_BillToCust, @BillToCustType = @v_UM00600_BillToCustType, @Owner = @v_UM00600_Owner, @TenantCustNum = @v_UM00600_TenantCustNum, @AccumType = @v_UM00600_AccumType, @AccumMasterID = @v_UM00600_AccumMasterID, @MinBill = @v_UM00600_MinBill, @MaxBill = @v_UM00600_MaxBill, @LastBill = @v_UM00600_LastBill, @LastStatementDate = @v_UM00600_LastStatementDate, @LastStatementAmount = @v_UM00600_LastStatementAmount, @ServiceCategory = @v_UM00600_ServiceCategory, @PenaltyID = @v_UM00600_PenaltyID, @RecvAcct = @v_UM00600_RecvAcct, @ElectricTaxSched = @v_UM00600_ElectricTaxSched, @WaterTaxSched = @v_UM00600_WaterTaxSched, @SewerTaxSched = @v_UM00600_SewerTaxSched, @GasTaxSched = @v_UM00600_GasTaxSched, @PhoneTaxSched = @v_UM00600_PhoneTaxSched, @OtherTaxSched = @v_UM00600_OtherTaxSched, @PropertyTaxTaxSched = @v_UM00600_PropertyTaxTaxSched, @CableTaxSched = @v_UM00600_CableTaxSched, @InternetTaxSched = @v_UM00600_InternetTaxSched, @FireProtectionTaxSched = @v_UM00600_FireProtectionTaxSched, @SanitationTaxSched = @v_UM00600_SanitationTaxSched, @PropaneTaxSched = @v_UM00600_PropaneTaxSched, @LocDefined1 = @v_UM00600_LocDefined1, @LocDefined2 = @v_UM00600_LocDefined2, @ThirdPartyDesc = @v_UM00600_ThirdPartyDesc, @AddressCateg = @v_UM00600_AddressCateg, @StreetNumber = @v_UM00600_StreetNumber, @StreetNumberLng = @v_UM00600_StreetNumberLng, @StreetNumberSuffix = @v_UM00600_StreetNumberSuffix, @StreetName = @v_UM00600_StreetName, @StreetType = @v_UM00600_StreetType, @StreetDirectionP = @v_UM00600_StreetDirectionP, @StreetDirection = @v_UM00600_StreetDirection, @AptNumber = @v_UM00600_AptNumber, @AptDesc = @v_UM00600_AptDesc, @UnitDesig = @v_UM00600_UnitDesig, @ZipCode = @v_UM00600_ZipCode, @CityName = @v_UM00600_CityName, @STATE = @v_UM00600_STATE, @COUNTRY = @v_UM00600_COUNTRY, @Postal_Walk = @v_UM00600_Postal_Walk, @PostalWalkVer = @v_UM00600_PostalWalkVer, @CreateDate = @v_UM00600_CreateDate, @AptNumberPlus = @v_UM00600_AptNumberPlus, @ADDRESS1 = @v_UM00600_ADDRESS1, @ADDRESS2 = @v_UM00600_ADDRESS2, @ADDRESS3 = @v_UM00600_ADDRESS3, @ServicePlanNumber = @v_UM00600_ServicePlanNumber, @ServiceLotNumber = @v_UM00600_ServiceLotNumber, @KeyNum = @v_UM00600_KeyNum, @ResidentialUnits = @v_UM00600_ResidentialUnits, @SICCode = @v_UM00600_SICCode, @AssessorID = @v_UM00600_AssessorID, @LandParcelID = @v_UM00600_LandParcelID, @DefaultInterim = @v_UM00600_DefaultInterim, @RouteID = @v_UM00600_RouteID, @scMessage = @v_UM00600_scMessage OUTPUT, @scError = @v_UM00600_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UM00600_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UM00600_scError, 0), scMessage = @v_UM00600_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UM00600_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00600_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00600_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UM00600 INTO @v_UM00600_GoldRowId, @v_UM00600_UserID, @v_UM00600_LocationID, @v_UM00600_LocationType, @v_UM00600_LocationClass, @v_UM00600_BudgetPlanEligibility, @v_UM00600_AddressType, @v_UM00600_ZoneID, @v_UM00600_BillToCust, @v_UM00600_BillToCustType, @v_UM00600_Owner, @v_UM00600_TenantCustNum, @v_UM00600_AccumType, @v_UM00600_AccumMasterID, @v_UM00600_MinBill, @v_UM00600_MaxBill, @v_UM00600_LastBill, @v_UM00600_LastStatementDate, @v_UM00600_LastStatementAmount, @v_UM00600_ServiceCategory, @v_UM00600_PenaltyID, @v_UM00600_RecvAcct, @v_UM00600_ElectricTaxSched, @v_UM00600_WaterTaxSched, @v_UM00600_SewerTaxSched, @v_UM00600_GasTaxSched, @v_UM00600_PhoneTaxSched, @v_UM00600_OtherTaxSched, @v_UM00600_PropertyTaxTaxSched, @v_UM00600_CableTaxSched, @v_UM00600_InternetTaxSched, @v_UM00600_FireProtectionTaxSched, @v_UM00600_SanitationTaxSched, @v_UM00600_PropaneTaxSched, @v_UM00600_LocDefined1, @v_UM00600_LocDefined2, @v_UM00600_ThirdPartyDesc, @v_UM00600_AddressCateg, @v_UM00600_StreetNumber, @v_UM00600_StreetNumberLng, @v_UM00600_StreetNumberSuffix, @v_UM00600_StreetName, @v_UM00600_StreetType, @v_UM00600_StreetDirectionP, @v_UM00600_StreetDirection, @v_UM00600_AptNumber, @v_UM00600_AptDesc, @v_UM00600_UnitDesig, @v_UM00600_ZipCode, @v_UM00600_CityName, @v_UM00600_STATE, @v_UM00600_COUNTRY, @v_UM00600_Postal_Walk, @v_UM00600_PostalWalkVer, @v_UM00600_CreateDate, @v_UM00600_AptNumberPlus, @v_UM00600_ADDRESS1, @v_UM00600_ADDRESS2, @v_UM00600_ADDRESS3, @v_UM00600_ServicePlanNumber, @v_UM00600_ServiceLotNumber, @v_UM00600_KeyNum, @v_UM00600_ResidentialUnits, @v_UM00600_SICCode, @v_UM00600_AssessorID, @v_UM00600_LandParcelID, @v_UM00600_DefaultInterim, @v_UM00600_RouteID;
            END;
            CLOSE c_load_UM00600;
            DEALLOCATE c_load_UM00600;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        IF @Module = 'UM00400'
        BEGIN
            DECLARE @v_UM00400_GoldRowId bigint;
            DECLARE @v_UM00400_UserID char(15);
            DECLARE @v_UM00400_EquipmentID char(15);
            DECLARE @v_UM00400_EquipmentClass char(15);
            DECLARE @v_UM00400_ServiceCategory smallint;
            DECLARE @v_UM00400_ConEst smallint;
            DECLARE @v_UM00400_Installed bit;
            DECLARE @v_UM00400_InstallDate datetime;
            DECLARE @v_UM00400_EquipmentLot char(21);
            DECLARE @v_UM00400_SerialNumber char(31);
            DECLARE @v_UM00400_PurchaseDate datetime;
            DECLARE @v_UM00400_PurchaseCost numeric(19, 5);
            DECLARE @v_UM00400_RemovalDate datetime;
            DECLARE @v_UM00400_SealedDate datetime;
            DECLARE @v_UM00400_TestDueDate datetime;
            DECLARE @v_UM00400_DateCreated datetime;
            DECLARE @v_UM00400_Kh char(7);
            DECLARE @v_UM00400_Elem char(7);
            DECLARE @v_UM00400_AccuracyClass char(15);
            DECLARE @v_UM00400_PrimaryThru tinyint;
            DECLARE @v_UM00400_SecondaryAmps numeric(19, 5);
            DECLARE @v_UM00400_SecondaryVolts numeric(19, 5);
            DECLARE @v_UM00400_EquipmentStatus smallint;
            DECLARE @v_UM00400_InstallableStatus tinyint;
            DECLARE @v_UM00400_UDF1 char(31);
            DECLARE @v_UM00400_UDF2 char(31);
            DECLARE @v_UM00400_RemoteID char(20);
            DECLARE @v_UM00400_LocationID char(15);
            DECLARE @v_UM00400_RInstallationDate datetime;
            DECLARE @v_UM00400_RRemovalDate datetime;
            DECLARE @v_UM00400_RRemovalReason char(65);
            DECLARE @v_UM00400_RInstallStatus tinyint;
            DECLARE @v_UM00400_RConnectStatus smallint;
            DECLARE @v_UM00400_EqMult numeric(19, 5);
            DECLARE @v_UM00400_ConnectSeq smallint;
            DECLARE @v_UM00400_TemperCode char(5);
            DECLARE @v_UM00400_PhysicalLocation char(65);
            DECLARE @v_UM00400_Locator char(21);
            DECLARE @v_UM00400_GISIdentifier char(21);
            DECLARE @v_UM00400_Model char(15);
            DECLARE @v_UM00400_Protection smallint;
            DECLARE @v_UM00400_EqDescription char(65);
            DECLARE @v_UM00400_CumulativeDemand smallint;
            DECLARE @v_UM00400_EquipmentType int;
            DECLARE @v_UM00400_Manufacturer char(30);
            DECLARE @v_UM00400_Diameter numeric(19,5);
            DECLARE @v_UM00400_NumberOfWires int;
            DECLARE @v_UM00400_Phase int;
            DECLARE @v_UM00400_Voltage numeric(8,2);
            DECLARE @v_UM00400_Amperage numeric(8,2);
            DECLARE @v_UM00400_StatisticalNumber char(15);
            DECLARE @v_UM00400_DifferenceReadingsDials int;
            DECLARE @v_UM00400_KWDials int;
            DECLARE @v_UM00400_KVADials int;
            DECLARE @v_UM00400_PFReadingsDials int;
            DECLARE @v_UM00400_LFReadingsDials int;
            DECLARE @v_UM00400_NetMeterReceivedDials int;
            DECLARE @v_UM00400_EquipmentRemote char(1);
            DECLARE @v_UM00400_NetMeterType int;
            DECLARE @v_UM00400_DifferenceReadingsDialDigits varchar(1000);
            DECLARE @v_UM00400_KWDialDigits varchar(1000);
            DECLARE @v_UM00400_KVADialDigits varchar(1000);
            DECLARE @v_UM00400_PFDialDigits varchar(1000);
            DECLARE @v_UM00400_LFDialDigits varchar(1000);
            DECLARE @v_UM00400_NetMeterReceivedDialDigits varchar(1000);
            DECLARE @v_UM00400_DifferenceDialDecimals varchar(1000);
            DECLARE @v_UM00400_KWDialDecimals varchar(1000);
            DECLARE @v_UM00400_KVADialDecimals varchar(1000);
            DECLARE @v_UM00400_PFDialDecimals varchar(1000);
            DECLARE @v_UM00400_LFDialDecimals varchar(1000);
            DECLARE @v_UM00400_NetMeterReceivedDialDecimals varchar(1000);
            DECLARE @v_UM00400_DifferenceReadingDialMultiplier varchar(1000);
            DECLARE @v_UM00400_KWDialMultiplier varchar(1000);
            DECLARE @v_UM00400_KVADialMultiplier varchar(1000);
            DECLARE @v_UM00400_PFDialMultiplier varchar(1000);
            DECLARE @v_UM00400_LFDialMultiplier varchar(1000);
            DECLARE @v_UM00400_NetMeterReceivedDialMultiplier varchar(1000);
            DECLARE @v_UM00400_DifferenceReadingsDialRemoteID varchar(1000);
            DECLARE @v_UM00400_KWDialRemoteID varchar(1000);
            DECLARE @v_UM00400_KVADialRemoteID varchar(1000);
            DECLARE @v_UM00400_PFDialRemoteID varchar(1000);
            DECLARE @v_UM00400_LFDialRemoteID varchar(1000);
            DECLARE @v_UM00400_NetMeterReceivedDialRemoteID varchar(1000);
            DECLARE @v_UM00400_DifferenceReadingsDialRemoteType varchar(1000);
            DECLARE @v_UM00400_KWDialRemoteType varchar(1000);
            DECLARE @v_UM00400_KVADialRemoteType varchar(1000);
            DECLARE @v_UM00400_PFDialRemoteType varchar(1000);
            DECLARE @v_UM00400_LFDialRemoteType varchar(1000);
            DECLARE @v_UM00400_NetMeterReceivedDialRemoteType varchar(1000);
            DECLARE @v_UM00400_DifferenceReadingsDialEffectiveDate varchar(1000);
            DECLARE @v_UM00400_KWDialRemoteEffectiveDate varchar(1000);
            DECLARE @v_UM00400_KVADialRemoteEffectiveDate varchar(1000);
            DECLARE @v_UM00400_PFDialRemoteEffectiveDate varchar(1000);
            DECLARE @v_UM00400_LFDialRemoteEffectiveDate varchar(1000);
            DECLARE @v_UM00400_NetMeterReceivedEffectiveDate varchar(1000);
            DECLARE @v_UM00400_DifferenceReadingsDialExcludeUsage int;
            DECLARE @v_UM00400_NetMeterReceivedDialExcludeUsage int;
            DECLARE @v_UM00400_SmartMeter int;
            DECLARE @v_UM00400_AutoConnectDisconnect int;
            DECLARE @v_UM00400_MeterModelCode char(15);
            DECLARE @v_UM00400_ProgramID char(15);
            DECLARE @v_UM00400_RecorderID char(15);
            DECLARE @v_UM00400_DevicePassword char(20);
            DECLARE @v_UM00400_ReadLoadProfile char(1);
            DECLARE @v_UM00400_SelfReadAndTrip int;
            DECLARE @v_UM00400_SelfReadAndTripDay int;
            DECLARE @v_UM00400_DaylightSavingTime int;
            DECLARE @v_UM00400_ResetDemandIndicator int;
            DECLARE @v_UM00400_ExcludeFromEMRExport int;
            DECLARE @v_UM00400_scMessage varchar(255);
            DECLARE @v_UM00400_scError int;
            DECLARE c_load_UM00400 CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   '' AS [UserID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [EquipmentID]), ''), 15) AS [EquipmentID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [EquClassID]), ''), 15) AS [EquipmentClass],
                   COALESCE(TRY_CONVERT(smallint, [ServiceCategory]), 0) AS [ServiceCategory],
                   COALESCE(TRY_CONVERT(smallint, [ConsEst]), 0) AS [ConEst],
                   COALESCE(TRY_CONVERT(bit, [Installed]), 0) AS [Installed],
                   COALESCE(TRY_CONVERT(datetime, [InstallDate]), CONVERT(datetime, '19000101', 112)) AS [InstallDate],
                   '' AS [EquipmentLot],
                   LEFT(COALESCE(CONVERT(varchar(4000), [SerialNo]), ''), 31) AS [SerialNumber],
                   CONVERT(datetime, '19000101', 112) AS [PurchaseDate],
                   0 AS [PurchaseCost],
                   COALESCE(TRY_CONVERT(datetime, [RemovalDate]), CONVERT(datetime, '19000101', 112)) AS [RemovalDate],
                   CONVERT(datetime, '19000101', 112) AS [SealedDate],
                   CONVERT(datetime, '19000101', 112) AS [TestDueDate],
                   CONVERT(datetime, '19000101', 112) AS [DateCreated],
                   '' AS [Kh],
                   '' AS [Elem],
                   '' AS [AccuracyClass],
                   0 AS [PrimaryThru],
                   0 AS [SecondaryAmps],
                   0 AS [SecondaryVolts],
                   COALESCE(TRY_CONVERT(smallint, [EquipmentStatus]), 0) AS [EquipmentStatus],
                   COALESCE(TRY_CONVERT(tinyint, [InstallableStatus]), 0) AS [InstallableStatus],
                   '' AS [UDF1],
                   '' AS [UDF2],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RemoteID]), ''), 20) AS [RemoteID],
                   '' AS [LocationID],
                   COALESCE(TRY_CONVERT(datetime, [RInstallationDate]), CONVERT(datetime, '19000101', 112)) AS [RInstallationDate],
                   CONVERT(datetime, '19000101', 112) AS [RRemovalDate],
                   '' AS [RRemovalReason],
                   0 AS [RInstallStatus],
                   0 AS [RConnectStatus],
                   COALESCE(TRY_CONVERT(numeric(19, 5), [EqMult]), 1) AS [EqMult],
                   0 AS [ConnectSeq],
                   0 AS [TemperCode],
                   LEFT(COALESCE(CONVERT(varchar(4000), [PhysicalLocation]), ''), 65) AS [PhysicalLocation],
                   '' AS [Locator],
                   '' AS [GISIdentifier],
                   LEFT(COALESCE(CONVERT(varchar(4000), [MODEL]), ''), 15) AS [Model],
                   0 AS [Protection],
                   '' AS [EqDescription],
                   0 AS [CumulativeDemand],
                   0 AS [EquipmentType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [Manufacturer]), ''), 30) AS [Manufacturer],
                   COALESCE(TRY_CONVERT(numeric(19,5), [Diameter]), 0) AS [Diameter],
                   0 AS [NumberOfWires],
                   0 AS [Phase],
                   0 AS [Voltage],
                   0 AS [Amperage],
                   '' AS [StatisticalNumber],
                   COALESCE(TRY_CONVERT(int, [DifferenceReadingDials]), 0) AS [DifferenceReadingsDials],
                   0 AS [KWDials],
                   0 AS [KVADials],
                   0 AS [PFReadingsDials],
                   0 AS [LFReadingsDials],
                   0 AS [NetMeterReceivedDials],
                   '' AS [EquipmentRemote],
                   0 AS [NetMeterType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [DifferenceReadingsDialDigits]), ''), 1000) AS [DifferenceReadingsDialDigits],
                   LEFT(COALESCE(CONVERT(varchar(4000), [KWDialDigits]), ''), 1000) AS [KWDialDigits],
                   '' AS [KVADialDigits],
                   '' AS [PFDialDigits],
                   '' AS [LFDialDigits],
                   '' AS [NetMeterReceivedDialDigits],
                   LEFT(COALESCE(CONVERT(varchar(4000), [DifferenceDialDecimals]), ''), 1000) AS [DifferenceDialDecimals],
                   LEFT(COALESCE(CONVERT(varchar(4000), [KWDialDecimals]), ''), 1000) AS [KWDialDecimals],
                   '' AS [KVADialDecimals],
                   '' AS [PFDialDecimals],
                   '' AS [LFDialDecimals],
                   '' AS [NetMeterReceivedDialDecimals],
                   LEFT(COALESCE(CONVERT(varchar(4000), [DifferenceReadingDialMultiplier]), ''), 1000) AS [DifferenceReadingDialMultiplier],
                   LEFT(COALESCE(CONVERT(varchar(4000), [KWDialMultiplier]), ''), 1000) AS [KWDialMultiplier],
                   '1' AS [KVADialMultiplier],
                   LEFT(COALESCE(CONVERT(varchar(4000), [PFDialMultiplier]), ''), 1000) AS [PFDialMultiplier],
                   '1' AS [LFDialMultiplier],
                   '1' AS [NetMeterReceivedDialMultiplier],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RemoteID]), ''), 1000) AS [DifferenceReadingsDialRemoteID],
                   '' AS [KWDialRemoteID],
                   '' AS [KVADialRemoteID],
                   '' AS [PFDialRemoteID],
                   '' AS [LFDialRemoteID],
                   '' AS [NetMeterReceivedDialRemoteID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RemoteType]), ''), 1000) AS [DifferenceReadingsDialRemoteType],
                   '' AS [KWDialRemoteType],
                   '' AS [KVADialRemoteType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RemoteType]), ''), 1000) AS [PFDialRemoteType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RemoteType]), ''), 1000) AS [LFDialRemoteType],
                   '' AS [NetMeterReceivedDialRemoteType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RInstallationDate]), ''), 1000) AS [DifferenceReadingsDialEffectiveDate],
                   '' AS [KWDialRemoteEffectiveDate],
                   '' AS [KVADialRemoteEffectiveDate],
                   '' AS [PFDialRemoteEffectiveDate],
                   '' AS [LFDialRemoteEffectiveDate],
                   '' AS [NetMeterReceivedEffectiveDate],
                   2 AS [DifferenceReadingsDialExcludeUsage],
                   2 AS [NetMeterReceivedDialExcludeUsage],
                   2 AS [SmartMeter],
                   2 AS [AutoConnectDisconnect],
                   LEFT(COALESCE(CONVERT(varchar(4000), [MODEL]), ''), 15) AS [MeterModelCode],
                   '' AS [ProgramID],
                   '' AS [RecorderID],
                   '' AS [DevicePassword],
                   '' AS [ReadLoadProfile],
                   0 AS [SelfReadAndTrip],
                   0 AS [SelfReadAndTripDay],
                   0 AS [DaylightSavingTime],
                   0 AS [ResetDemandIndicator],
                   0 AS [ExcludeFromEMRExport]
            FROM load.RowStatus s JOIN gold.UM_Equipment g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00400' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.EquClassID, g.EquipmentID;
            OPEN c_load_UM00400;
            FETCH NEXT FROM c_load_UM00400 INTO @v_UM00400_GoldRowId, @v_UM00400_UserID, @v_UM00400_EquipmentID, @v_UM00400_EquipmentClass, @v_UM00400_ServiceCategory, @v_UM00400_ConEst, @v_UM00400_Installed, @v_UM00400_InstallDate, @v_UM00400_EquipmentLot, @v_UM00400_SerialNumber, @v_UM00400_PurchaseDate, @v_UM00400_PurchaseCost, @v_UM00400_RemovalDate, @v_UM00400_SealedDate, @v_UM00400_TestDueDate, @v_UM00400_DateCreated, @v_UM00400_Kh, @v_UM00400_Elem, @v_UM00400_AccuracyClass, @v_UM00400_PrimaryThru, @v_UM00400_SecondaryAmps, @v_UM00400_SecondaryVolts, @v_UM00400_EquipmentStatus, @v_UM00400_InstallableStatus, @v_UM00400_UDF1, @v_UM00400_UDF2, @v_UM00400_RemoteID, @v_UM00400_LocationID, @v_UM00400_RInstallationDate, @v_UM00400_RRemovalDate, @v_UM00400_RRemovalReason, @v_UM00400_RInstallStatus, @v_UM00400_RConnectStatus, @v_UM00400_EqMult, @v_UM00400_ConnectSeq, @v_UM00400_TemperCode, @v_UM00400_PhysicalLocation, @v_UM00400_Locator, @v_UM00400_GISIdentifier, @v_UM00400_Model, @v_UM00400_Protection, @v_UM00400_EqDescription, @v_UM00400_CumulativeDemand, @v_UM00400_EquipmentType, @v_UM00400_Manufacturer, @v_UM00400_Diameter, @v_UM00400_NumberOfWires, @v_UM00400_Phase, @v_UM00400_Voltage, @v_UM00400_Amperage, @v_UM00400_StatisticalNumber, @v_UM00400_DifferenceReadingsDials, @v_UM00400_KWDials, @v_UM00400_KVADials, @v_UM00400_PFReadingsDials, @v_UM00400_LFReadingsDials, @v_UM00400_NetMeterReceivedDials, @v_UM00400_EquipmentRemote, @v_UM00400_NetMeterType, @v_UM00400_DifferenceReadingsDialDigits, @v_UM00400_KWDialDigits, @v_UM00400_KVADialDigits, @v_UM00400_PFDialDigits, @v_UM00400_LFDialDigits, @v_UM00400_NetMeterReceivedDialDigits, @v_UM00400_DifferenceDialDecimals, @v_UM00400_KWDialDecimals, @v_UM00400_KVADialDecimals, @v_UM00400_PFDialDecimals, @v_UM00400_LFDialDecimals, @v_UM00400_NetMeterReceivedDialDecimals, @v_UM00400_DifferenceReadingDialMultiplier, @v_UM00400_KWDialMultiplier, @v_UM00400_KVADialMultiplier, @v_UM00400_PFDialMultiplier, @v_UM00400_LFDialMultiplier, @v_UM00400_NetMeterReceivedDialMultiplier, @v_UM00400_DifferenceReadingsDialRemoteID, @v_UM00400_KWDialRemoteID, @v_UM00400_KVADialRemoteID, @v_UM00400_PFDialRemoteID, @v_UM00400_LFDialRemoteID, @v_UM00400_NetMeterReceivedDialRemoteID, @v_UM00400_DifferenceReadingsDialRemoteType, @v_UM00400_KWDialRemoteType, @v_UM00400_KVADialRemoteType, @v_UM00400_PFDialRemoteType, @v_UM00400_LFDialRemoteType, @v_UM00400_NetMeterReceivedDialRemoteType, @v_UM00400_DifferenceReadingsDialEffectiveDate, @v_UM00400_KWDialRemoteEffectiveDate, @v_UM00400_KVADialRemoteEffectiveDate, @v_UM00400_PFDialRemoteEffectiveDate, @v_UM00400_LFDialRemoteEffectiveDate, @v_UM00400_NetMeterReceivedEffectiveDate, @v_UM00400_DifferenceReadingsDialExcludeUsage, @v_UM00400_NetMeterReceivedDialExcludeUsage, @v_UM00400_SmartMeter, @v_UM00400_AutoConnectDisconnect, @v_UM00400_MeterModelCode, @v_UM00400_ProgramID, @v_UM00400_RecorderID, @v_UM00400_DevicePassword, @v_UM00400_ReadLoadProfile, @v_UM00400_SelfReadAndTrip, @v_UM00400_SelfReadAndTripDay, @v_UM00400_DaylightSavingTime, @v_UM00400_ResetDemandIndicator, @v_UM00400_ExcludeFromEMRExport;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UM00400_scError = 0;
                SET @v_UM00400_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateEquipment @UserID = @UserID, @EquipmentID = @EquipmentID, @EquipmentClass = @EquipmentClass, @ServiceCategory = @ServiceCategory, @ConEst = @ConEst, @Installed = @Installed, @InstallDate = @InstallDate, @EquipmentLot = @EquipmentLot, @SerialNumber = @SerialNumber, @PurchaseDate = @PurchaseDate, @PurchaseCost = @PurchaseCost, @RemovalDate = @RemovalDate, @SealedDate = @SealedDate, @TestDueDate = @TestDueDate, @DateCreated = @DateCreated, @Kh = @Kh, @Elem = @Elem, @AccuracyClass = @AccuracyClass, @PrimaryThru = @PrimaryThru, @SecondaryAmps = @SecondaryAmps, @SecondaryVolts = @SecondaryVolts, @EquipmentStatus = @EquipmentStatus, @InstallableStatus = @InstallableStatus, @UDF1 = @UDF1, @UDF2 = @UDF2, @RemoteID = @RemoteID, @LocationID = @LocationID, @RInstallationDate = @RInstallationDate, @RRemovalDate = @RRemovalDate, @RRemovalReason = @RRemovalReason, @RInstallStatus = @RInstallStatus, @RConnectStatus = @RConnectStatus, @EqMult = @EqMult, @ConnectSeq = @ConnectSeq, @TemperCode = @TemperCode, @PhysicalLocation = @PhysicalLocation, @Locator = @Locator, @GISIdentifier = @GISIdentifier, @Model = @Model, @Protection = @Protection, @EqDescription = @EqDescription, @CumulativeDemand = @CumulativeDemand, @EquipmentType = @EquipmentType, @Manufacturer = @Manufacturer, @Diameter = @Diameter, @NumberOfWires = @NumberOfWires, @Phase = @Phase, @Voltage = @Voltage, @Amperage = @Amperage, @StatisticalNumber = @StatisticalNumber, @DifferenceReadingsDials = @DifferenceReadingsDials, @KWDials = @KWDials, @KVADials = @KVADials, @PFReadingsDials = @PFReadingsDials, @LFReadingsDials = @LFReadingsDials, @NetMeterReceivedDials = @NetMeterReceivedDials, @EquipmentRemote = @EquipmentRemote, @NetMeterType = @NetMeterType, @DifferenceReadingsDialDigits = @DifferenceReadingsDialDigits, @KWDialDigits = @KWDialDigits, @KVADialDigits = @KVADialDigits, @PFDialDigits = @PFDialDigits, @LFDialDigits = @LFDialDigits, @NetMeterReceivedDialDigits = @NetMeterReceivedDialDigits, @DifferenceDialDecimals = @DifferenceDialDecimals, @KWDialDecimals = @KWDialDecimals, @KVADialDecimals = @KVADialDecimals, @PFDialDecimals = @PFDialDecimals, @LFDialDecimals = @LFDialDecimals, @NetMeterReceivedDialDecimals = @NetMeterReceivedDialDecimals, @DifferenceReadingDialMultiplier = @DifferenceReadingDialMultiplier, @KWDialMultiplier = @KWDialMultiplier, @KVADialMultiplier = @KVADialMultiplier, @PFDialMultiplier = @PFDialMultiplier, @LFDialMultiplier = @LFDialMultiplier, @NetMeterReceivedDialMultiplier = @NetMeterReceivedDialMultiplier, @DifferenceReadingsDialRemoteID = @DifferenceReadingsDialRemoteID, @KWDialRemoteID = @KWDialRemoteID, @KVADialRemoteID = @KVADialRemoteID, @PFDialRemoteID = @PFDialRemoteID, @LFDialRemoteID = @LFDialRemoteID, @NetMeterReceivedDialRemoteID = @NetMeterReceivedDialRemoteID, @DifferenceReadingsDialRemoteType = @DifferenceReadingsDialRemoteType, @KWDialRemoteType = @KWDialRemoteType, @KVADialRemoteType = @KVADialRemoteType, @PFDialRemoteType = @PFDialRemoteType, @LFDialRemoteType = @LFDialRemoteType, @NetMeterReceivedDialRemoteType = @NetMeterReceivedDialRemoteType, @DifferenceReadingsDialEffectiveDate = @DifferenceReadingsDialEffectiveDate, @KWDialRemoteEffectiveDate = @KWDialRemoteEffectiveDate, @KVADialRemoteEffectiveDate = @KVADialRemoteEffectiveDate, @PFDialRemoteEffectiveDate = @PFDialRemoteEffectiveDate, @LFDialRemoteEffectiveDate = @LFDialRemoteEffectiveDate, @NetMeterReceivedEffectiveDate = @NetMeterReceivedEffectiveDate, @DifferenceReadingsDialExcludeUsage = @DifferenceReadingsDialExcludeUsage, @NetMeterReceivedDialExcludeUsage = @NetMeterReceivedDialExcludeUsage, @SmartMeter = @SmartMeter, @AutoConnectDisconnect = @AutoConnectDisconnect, @MeterModelCode = @MeterModelCode, @ProgramID = @ProgramID, @RecorderID = @RecorderID, @DevicePassword = @DevicePassword, @ReadLoadProfile = @ReadLoadProfile, @SelfReadAndTrip = @SelfReadAndTrip, @SelfReadAndTripDay = @SelfReadAndTripDay, @DaylightSavingTime = @DaylightSavingTime, @ResetDemandIndicator = @ResetDemandIndicator, @ExcludeFromEMRExport = @ExcludeFromEMRExport, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@UserID char(15), @EquipmentID char(15), @EquipmentClass char(15), @ServiceCategory smallint, @ConEst smallint, @Installed bit, @InstallDate datetime, @EquipmentLot char(21), @SerialNumber char(31), @PurchaseDate datetime, @PurchaseCost numeric(19, 5), @RemovalDate datetime, @SealedDate datetime, @TestDueDate datetime, @DateCreated datetime, @Kh char(7), @Elem char(7), @AccuracyClass char(15), @PrimaryThru tinyint, @SecondaryAmps numeric(19, 5), @SecondaryVolts numeric(19, 5), @EquipmentStatus smallint, @InstallableStatus tinyint, @UDF1 char(31), @UDF2 char(31), @RemoteID char(20), @LocationID char(15), @RInstallationDate datetime, @RRemovalDate datetime, @RRemovalReason char(65), @RInstallStatus tinyint, @RConnectStatus smallint, @EqMult numeric(19, 5), @ConnectSeq smallint, @TemperCode char(5), @PhysicalLocation char(65), @Locator char(21), @GISIdentifier char(21), @Model char(15), @Protection smallint, @EqDescription char(65), @CumulativeDemand smallint, @EquipmentType int, @Manufacturer char(30), @Diameter numeric(19,5), @NumberOfWires int, @Phase int, @Voltage numeric(8,2), @Amperage numeric(8,2), @StatisticalNumber char(15), @DifferenceReadingsDials int, @KWDials int, @KVADials int, @PFReadingsDials int, @LFReadingsDials int, @NetMeterReceivedDials int, @EquipmentRemote char(1), @NetMeterType int, @DifferenceReadingsDialDigits varchar(1000), @KWDialDigits varchar(1000), @KVADialDigits varchar(1000), @PFDialDigits varchar(1000), @LFDialDigits varchar(1000), @NetMeterReceivedDialDigits varchar(1000), @DifferenceDialDecimals varchar(1000), @KWDialDecimals varchar(1000), @KVADialDecimals varchar(1000), @PFDialDecimals varchar(1000), @LFDialDecimals varchar(1000), @NetMeterReceivedDialDecimals varchar(1000), @DifferenceReadingDialMultiplier varchar(1000), @KWDialMultiplier varchar(1000), @KVADialMultiplier varchar(1000), @PFDialMultiplier varchar(1000), @LFDialMultiplier varchar(1000), @NetMeterReceivedDialMultiplier varchar(1000), @DifferenceReadingsDialRemoteID varchar(1000), @KWDialRemoteID varchar(1000), @KVADialRemoteID varchar(1000), @PFDialRemoteID varchar(1000), @LFDialRemoteID varchar(1000), @NetMeterReceivedDialRemoteID varchar(1000), @DifferenceReadingsDialRemoteType varchar(1000), @KWDialRemoteType varchar(1000), @KVADialRemoteType varchar(1000), @PFDialRemoteType varchar(1000), @LFDialRemoteType varchar(1000), @NetMeterReceivedDialRemoteType varchar(1000), @DifferenceReadingsDialEffectiveDate varchar(1000), @KWDialRemoteEffectiveDate varchar(1000), @KVADialRemoteEffectiveDate varchar(1000), @PFDialRemoteEffectiveDate varchar(1000), @LFDialRemoteEffectiveDate varchar(1000), @NetMeterReceivedEffectiveDate varchar(1000), @DifferenceReadingsDialExcludeUsage int, @NetMeterReceivedDialExcludeUsage int, @SmartMeter int, @AutoConnectDisconnect int, @MeterModelCode char(15), @ProgramID char(15), @RecorderID char(15), @DevicePassword char(20), @ReadLoadProfile char(1), @SelfReadAndTrip int, @SelfReadAndTripDay int, @DaylightSavingTime int, @ResetDemandIndicator int, @ExcludeFromEMRExport int, @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @UserID = @v_UM00400_UserID, @EquipmentID = @v_UM00400_EquipmentID, @EquipmentClass = @v_UM00400_EquipmentClass, @ServiceCategory = @v_UM00400_ServiceCategory, @ConEst = @v_UM00400_ConEst, @Installed = @v_UM00400_Installed, @InstallDate = @v_UM00400_InstallDate, @EquipmentLot = @v_UM00400_EquipmentLot, @SerialNumber = @v_UM00400_SerialNumber, @PurchaseDate = @v_UM00400_PurchaseDate, @PurchaseCost = @v_UM00400_PurchaseCost, @RemovalDate = @v_UM00400_RemovalDate, @SealedDate = @v_UM00400_SealedDate, @TestDueDate = @v_UM00400_TestDueDate, @DateCreated = @v_UM00400_DateCreated, @Kh = @v_UM00400_Kh, @Elem = @v_UM00400_Elem, @AccuracyClass = @v_UM00400_AccuracyClass, @PrimaryThru = @v_UM00400_PrimaryThru, @SecondaryAmps = @v_UM00400_SecondaryAmps, @SecondaryVolts = @v_UM00400_SecondaryVolts, @EquipmentStatus = @v_UM00400_EquipmentStatus, @InstallableStatus = @v_UM00400_InstallableStatus, @UDF1 = @v_UM00400_UDF1, @UDF2 = @v_UM00400_UDF2, @RemoteID = @v_UM00400_RemoteID, @LocationID = @v_UM00400_LocationID, @RInstallationDate = @v_UM00400_RInstallationDate, @RRemovalDate = @v_UM00400_RRemovalDate, @RRemovalReason = @v_UM00400_RRemovalReason, @RInstallStatus = @v_UM00400_RInstallStatus, @RConnectStatus = @v_UM00400_RConnectStatus, @EqMult = @v_UM00400_EqMult, @ConnectSeq = @v_UM00400_ConnectSeq, @TemperCode = @v_UM00400_TemperCode, @PhysicalLocation = @v_UM00400_PhysicalLocation, @Locator = @v_UM00400_Locator, @GISIdentifier = @v_UM00400_GISIdentifier, @Model = @v_UM00400_Model, @Protection = @v_UM00400_Protection, @EqDescription = @v_UM00400_EqDescription, @CumulativeDemand = @v_UM00400_CumulativeDemand, @EquipmentType = @v_UM00400_EquipmentType, @Manufacturer = @v_UM00400_Manufacturer, @Diameter = @v_UM00400_Diameter, @NumberOfWires = @v_UM00400_NumberOfWires, @Phase = @v_UM00400_Phase, @Voltage = @v_UM00400_Voltage, @Amperage = @v_UM00400_Amperage, @StatisticalNumber = @v_UM00400_StatisticalNumber, @DifferenceReadingsDials = @v_UM00400_DifferenceReadingsDials, @KWDials = @v_UM00400_KWDials, @KVADials = @v_UM00400_KVADials, @PFReadingsDials = @v_UM00400_PFReadingsDials, @LFReadingsDials = @v_UM00400_LFReadingsDials, @NetMeterReceivedDials = @v_UM00400_NetMeterReceivedDials, @EquipmentRemote = @v_UM00400_EquipmentRemote, @NetMeterType = @v_UM00400_NetMeterType, @DifferenceReadingsDialDigits = @v_UM00400_DifferenceReadingsDialDigits, @KWDialDigits = @v_UM00400_KWDialDigits, @KVADialDigits = @v_UM00400_KVADialDigits, @PFDialDigits = @v_UM00400_PFDialDigits, @LFDialDigits = @v_UM00400_LFDialDigits, @NetMeterReceivedDialDigits = @v_UM00400_NetMeterReceivedDialDigits, @DifferenceDialDecimals = @v_UM00400_DifferenceDialDecimals, @KWDialDecimals = @v_UM00400_KWDialDecimals, @KVADialDecimals = @v_UM00400_KVADialDecimals, @PFDialDecimals = @v_UM00400_PFDialDecimals, @LFDialDecimals = @v_UM00400_LFDialDecimals, @NetMeterReceivedDialDecimals = @v_UM00400_NetMeterReceivedDialDecimals, @DifferenceReadingDialMultiplier = @v_UM00400_DifferenceReadingDialMultiplier, @KWDialMultiplier = @v_UM00400_KWDialMultiplier, @KVADialMultiplier = @v_UM00400_KVADialMultiplier, @PFDialMultiplier = @v_UM00400_PFDialMultiplier, @LFDialMultiplier = @v_UM00400_LFDialMultiplier, @NetMeterReceivedDialMultiplier = @v_UM00400_NetMeterReceivedDialMultiplier, @DifferenceReadingsDialRemoteID = @v_UM00400_DifferenceReadingsDialRemoteID, @KWDialRemoteID = @v_UM00400_KWDialRemoteID, @KVADialRemoteID = @v_UM00400_KVADialRemoteID, @PFDialRemoteID = @v_UM00400_PFDialRemoteID, @LFDialRemoteID = @v_UM00400_LFDialRemoteID, @NetMeterReceivedDialRemoteID = @v_UM00400_NetMeterReceivedDialRemoteID, @DifferenceReadingsDialRemoteType = @v_UM00400_DifferenceReadingsDialRemoteType, @KWDialRemoteType = @v_UM00400_KWDialRemoteType, @KVADialRemoteType = @v_UM00400_KVADialRemoteType, @PFDialRemoteType = @v_UM00400_PFDialRemoteType, @LFDialRemoteType = @v_UM00400_LFDialRemoteType, @NetMeterReceivedDialRemoteType = @v_UM00400_NetMeterReceivedDialRemoteType, @DifferenceReadingsDialEffectiveDate = @v_UM00400_DifferenceReadingsDialEffectiveDate, @KWDialRemoteEffectiveDate = @v_UM00400_KWDialRemoteEffectiveDate, @KVADialRemoteEffectiveDate = @v_UM00400_KVADialRemoteEffectiveDate, @PFDialRemoteEffectiveDate = @v_UM00400_PFDialRemoteEffectiveDate, @LFDialRemoteEffectiveDate = @v_UM00400_LFDialRemoteEffectiveDate, @NetMeterReceivedEffectiveDate = @v_UM00400_NetMeterReceivedEffectiveDate, @DifferenceReadingsDialExcludeUsage = @v_UM00400_DifferenceReadingsDialExcludeUsage, @NetMeterReceivedDialExcludeUsage = @v_UM00400_NetMeterReceivedDialExcludeUsage, @SmartMeter = @v_UM00400_SmartMeter, @AutoConnectDisconnect = @v_UM00400_AutoConnectDisconnect, @MeterModelCode = @v_UM00400_MeterModelCode, @ProgramID = @v_UM00400_ProgramID, @RecorderID = @v_UM00400_RecorderID, @DevicePassword = @v_UM00400_DevicePassword, @ReadLoadProfile = @v_UM00400_ReadLoadProfile, @SelfReadAndTrip = @v_UM00400_SelfReadAndTrip, @SelfReadAndTripDay = @v_UM00400_SelfReadAndTripDay, @DaylightSavingTime = @v_UM00400_DaylightSavingTime, @ResetDemandIndicator = @v_UM00400_ResetDemandIndicator, @ExcludeFromEMRExport = @v_UM00400_ExcludeFromEMRExport, @scMessage = @v_UM00400_scMessage OUTPUT, @scError = @v_UM00400_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UM00400_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UM00400_scError, 0), scMessage = @v_UM00400_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UM00400_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00400_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00400_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UM00400 INTO @v_UM00400_GoldRowId, @v_UM00400_UserID, @v_UM00400_EquipmentID, @v_UM00400_EquipmentClass, @v_UM00400_ServiceCategory, @v_UM00400_ConEst, @v_UM00400_Installed, @v_UM00400_InstallDate, @v_UM00400_EquipmentLot, @v_UM00400_SerialNumber, @v_UM00400_PurchaseDate, @v_UM00400_PurchaseCost, @v_UM00400_RemovalDate, @v_UM00400_SealedDate, @v_UM00400_TestDueDate, @v_UM00400_DateCreated, @v_UM00400_Kh, @v_UM00400_Elem, @v_UM00400_AccuracyClass, @v_UM00400_PrimaryThru, @v_UM00400_SecondaryAmps, @v_UM00400_SecondaryVolts, @v_UM00400_EquipmentStatus, @v_UM00400_InstallableStatus, @v_UM00400_UDF1, @v_UM00400_UDF2, @v_UM00400_RemoteID, @v_UM00400_LocationID, @v_UM00400_RInstallationDate, @v_UM00400_RRemovalDate, @v_UM00400_RRemovalReason, @v_UM00400_RInstallStatus, @v_UM00400_RConnectStatus, @v_UM00400_EqMult, @v_UM00400_ConnectSeq, @v_UM00400_TemperCode, @v_UM00400_PhysicalLocation, @v_UM00400_Locator, @v_UM00400_GISIdentifier, @v_UM00400_Model, @v_UM00400_Protection, @v_UM00400_EqDescription, @v_UM00400_CumulativeDemand, @v_UM00400_EquipmentType, @v_UM00400_Manufacturer, @v_UM00400_Diameter, @v_UM00400_NumberOfWires, @v_UM00400_Phase, @v_UM00400_Voltage, @v_UM00400_Amperage, @v_UM00400_StatisticalNumber, @v_UM00400_DifferenceReadingsDials, @v_UM00400_KWDials, @v_UM00400_KVADials, @v_UM00400_PFReadingsDials, @v_UM00400_LFReadingsDials, @v_UM00400_NetMeterReceivedDials, @v_UM00400_EquipmentRemote, @v_UM00400_NetMeterType, @v_UM00400_DifferenceReadingsDialDigits, @v_UM00400_KWDialDigits, @v_UM00400_KVADialDigits, @v_UM00400_PFDialDigits, @v_UM00400_LFDialDigits, @v_UM00400_NetMeterReceivedDialDigits, @v_UM00400_DifferenceDialDecimals, @v_UM00400_KWDialDecimals, @v_UM00400_KVADialDecimals, @v_UM00400_PFDialDecimals, @v_UM00400_LFDialDecimals, @v_UM00400_NetMeterReceivedDialDecimals, @v_UM00400_DifferenceReadingDialMultiplier, @v_UM00400_KWDialMultiplier, @v_UM00400_KVADialMultiplier, @v_UM00400_PFDialMultiplier, @v_UM00400_LFDialMultiplier, @v_UM00400_NetMeterReceivedDialMultiplier, @v_UM00400_DifferenceReadingsDialRemoteID, @v_UM00400_KWDialRemoteID, @v_UM00400_KVADialRemoteID, @v_UM00400_PFDialRemoteID, @v_UM00400_LFDialRemoteID, @v_UM00400_NetMeterReceivedDialRemoteID, @v_UM00400_DifferenceReadingsDialRemoteType, @v_UM00400_KWDialRemoteType, @v_UM00400_KVADialRemoteType, @v_UM00400_PFDialRemoteType, @v_UM00400_LFDialRemoteType, @v_UM00400_NetMeterReceivedDialRemoteType, @v_UM00400_DifferenceReadingsDialEffectiveDate, @v_UM00400_KWDialRemoteEffectiveDate, @v_UM00400_KVADialRemoteEffectiveDate, @v_UM00400_PFDialRemoteEffectiveDate, @v_UM00400_LFDialRemoteEffectiveDate, @v_UM00400_NetMeterReceivedEffectiveDate, @v_UM00400_DifferenceReadingsDialExcludeUsage, @v_UM00400_NetMeterReceivedDialExcludeUsage, @v_UM00400_SmartMeter, @v_UM00400_AutoConnectDisconnect, @v_UM00400_MeterModelCode, @v_UM00400_ProgramID, @v_UM00400_RecorderID, @v_UM00400_DevicePassword, @v_UM00400_ReadLoadProfile, @v_UM00400_SelfReadAndTrip, @v_UM00400_SelfReadAndTripDay, @v_UM00400_DaylightSavingTime, @v_UM00400_ResetDemandIndicator, @v_UM00400_ExcludeFromEMRExport;
            END;
            CLOSE c_load_UM00400;
            DEALLOCATE c_load_UM00400;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        IF @Module = 'UM00300'
        BEGIN
            DECLARE @v_UM00300_GoldRowId bigint;
            DECLARE @v_UM00300_UserID char(15);
            DECLARE @v_UM00300_LocationID char(15);
            DECLARE @v_UM00300_ServiceType char(15);
            DECLARE @v_UM00300_ServiceCategory smallint;
            DECLARE @v_UM00300_UMMETGRPID char(15);
            DECLARE @v_UM00300_UMMETGRPTYPE smallint;
            DECLARE @v_UM00300_UMMULTGRPID char(15);
            DECLARE @v_UM00300_RouteID char(15);
            DECLARE @v_UM00300_ConnectStatus smallint;
            DECLARE @v_UM00300_TariffID char(15);
            DECLARE @v_UM00300_ConnectionDate datetime;
            DECLARE @v_UM00300_DisconnectionDate datetime;
            DECLARE @v_UM00300_UMCONNMULT numeric(19, 5);
            DECLARE @v_UM00300_UMMULTTYPE smallint;
            DECLARE @v_UM00300_EquipmentID char(15);
            DECLARE @v_UM00300_UseAltMeter tinyint;
            DECLARE @v_UM00300_UMSEQNUM numeric(19, 5);
            DECLARE @v_UM00300_UMFIXEDMULT numeric(19, 5);
            DECLARE @v_UM00300_umConsumpMult numeric(19, 5);
            DECLARE @v_UM00300_UMLOSSMULT numeric(19, 5);
            DECLARE @v_UM00300_UMRNGMINMULT numeric(19, 5);
            DECLARE @v_UM00300_UMBELONGTO char(15);
            DECLARE @v_UM00300_UserDefined1 char(31);
            DECLARE @v_UM00300_UserDefined2 char(31);
            DECLARE @v_UM00300_Tar11 char(15);
            DECLARE @v_UM00300_Tar12 char(15);
            DECLARE @v_UM00300_Tar13 char(15);
            DECLARE @v_UM00300_UMTaxSched char(15);
            DECLARE @v_UM00300_UMINDX smallint;
            DECLARE @v_UM00300_Imported smallint;
            DECLARE @v_UM00300_DeliveredEquipmentID char(15);
            DECLARE @v_UM00300_inPeriodIndex int;
            DECLARE @v_UM00300_inRate1 char(15);
            DECLARE @v_UM00300_inRate2 char(15);
            DECLARE @v_UM00300_inRate3 char(15);
            DECLARE @v_UM00300_inRate4 char(15);
            DECLARE @v_UM00300_scMessage varchar(255);
            DECLARE @v_UM00300_scError int;
            DECLARE c_load_UM00300 CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   '' AS [UserID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [LocationID]), ''), 15) AS [LocationID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [ServiceType]), ''), 15) AS [ServiceType],
                   COALESCE(TRY_CONVERT(smallint, [Category]), 0) AS [ServiceCategory],
                   '' AS [UMMETGRPID],
                   0 AS [UMMETGRPTYPE],
                   '' AS [UMMULTGRPID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RouteID]), ''), 15) AS [RouteID],
                   COALESCE(TRY_CONVERT(smallint, [ConnStatus]), 0) AS [ConnectStatus],
                   LEFT(COALESCE(CONVERT(varchar(4000), [TariffID]), ''), 15) AS [TariffID],
                   COALESCE(TRY_CONVERT(datetime, [ConnDate]), CONVERT(datetime, '19000101', 112)) AS [ConnectionDate],
                   COALESCE(TRY_CONVERT(datetime, [DisconnDate]), CONVERT(datetime, '19000101', 112)) AS [DisconnectionDate],
                   1 AS [UMCONNMULT],
                   0 AS [UMMULTTYPE],
                   LEFT(COALESCE(CONVERT(varchar(4000), [EquipmentID]), ''), 15) AS [EquipmentID],
                   0 AS [UseAltMeter],
                   COALESCE(TRY_CONVERT(numeric(19, 5), [SEQNO]), 0) AS [UMSEQNUM],
                   1 AS [UMFIXEDMULT],
                   1 AS [umConsumpMult],
                   1 AS [UMLOSSMULT],
                   1 AS [UMRNGMINMULT],
                   '' AS [UMBELONGTO],
                   '' AS [UserDefined1],
                   '' AS [UserDefined2],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CTAR11]), ''), 15) AS [Tar11],
                   '' AS [Tar12],
                   '' AS [Tar13],
                   '' AS [UMTaxSched],
                   0 AS [UMINDX],
                   0 AS [Imported],
                   '' AS [DeliveredEquipmentID],
                   0 AS [inPeriodIndex],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CTAR11]), ''), 15) AS [inRate1],
                   '' AS [inRate2],
                   '' AS [inRate3],
                   '' AS [inRate4]
            FROM load.RowStatus s JOIN gold.UM_Connection g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00300' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.LocationID, g.Alternate, g.SEQNO, g.ServiceType;
            OPEN c_load_UM00300;
            FETCH NEXT FROM c_load_UM00300 INTO @v_UM00300_GoldRowId, @v_UM00300_UserID, @v_UM00300_LocationID, @v_UM00300_ServiceType, @v_UM00300_ServiceCategory, @v_UM00300_UMMETGRPID, @v_UM00300_UMMETGRPTYPE, @v_UM00300_UMMULTGRPID, @v_UM00300_RouteID, @v_UM00300_ConnectStatus, @v_UM00300_TariffID, @v_UM00300_ConnectionDate, @v_UM00300_DisconnectionDate, @v_UM00300_UMCONNMULT, @v_UM00300_UMMULTTYPE, @v_UM00300_EquipmentID, @v_UM00300_UseAltMeter, @v_UM00300_UMSEQNUM, @v_UM00300_UMFIXEDMULT, @v_UM00300_umConsumpMult, @v_UM00300_UMLOSSMULT, @v_UM00300_UMRNGMINMULT, @v_UM00300_UMBELONGTO, @v_UM00300_UserDefined1, @v_UM00300_UserDefined2, @v_UM00300_Tar11, @v_UM00300_Tar12, @v_UM00300_Tar13, @v_UM00300_UMTaxSched, @v_UM00300_UMINDX, @v_UM00300_Imported, @v_UM00300_DeliveredEquipmentID, @v_UM00300_inPeriodIndex, @v_UM00300_inRate1, @v_UM00300_inRate2, @v_UM00300_inRate3, @v_UM00300_inRate4;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UM00300_scError = 0;
                SET @v_UM00300_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateConnection @UserID = @UserID, @LocationID = @LocationID, @ServiceType = @ServiceType, @ServiceCategory = @ServiceCategory, @UMMETGRPID = @UMMETGRPID, @UMMETGRPTYPE = @UMMETGRPTYPE, @UMMULTGRPID = @UMMULTGRPID, @RouteID = @RouteID, @ConnectStatus = @ConnectStatus, @TariffID = @TariffID, @ConnectionDate = @ConnectionDate, @DisconnectionDate = @DisconnectionDate, @UMCONNMULT = @UMCONNMULT, @UMMULTTYPE = @UMMULTTYPE, @EquipmentID = @EquipmentID, @UseAltMeter = @UseAltMeter, @UMSEQNUM = @UMSEQNUM, @UMFIXEDMULT = @UMFIXEDMULT, @umConsumpMult = @umConsumpMult, @UMLOSSMULT = @UMLOSSMULT, @UMRNGMINMULT = @UMRNGMINMULT, @UMBELONGTO = @UMBELONGTO, @UserDefined1 = @UserDefined1, @UserDefined2 = @UserDefined2, @Tar11 = @Tar11, @Tar12 = @Tar12, @Tar13 = @Tar13, @UMTaxSched = @UMTaxSched, @UMINDX = @UMINDX, @Imported = @Imported, @DeliveredEquipmentID = @DeliveredEquipmentID, @inPeriodIndex = @inPeriodIndex, @inRate1 = @inRate1, @inRate2 = @inRate2, @inRate3 = @inRate3, @inRate4 = @inRate4, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@UserID char(15), @LocationID char(15), @ServiceType char(15), @ServiceCategory smallint, @UMMETGRPID char(15), @UMMETGRPTYPE smallint, @UMMULTGRPID char(15), @RouteID char(15), @ConnectStatus smallint, @TariffID char(15), @ConnectionDate datetime, @DisconnectionDate datetime, @UMCONNMULT numeric(19, 5), @UMMULTTYPE smallint, @EquipmentID char(15), @UseAltMeter tinyint, @UMSEQNUM numeric(19, 5), @UMFIXEDMULT numeric(19, 5), @umConsumpMult numeric(19, 5), @UMLOSSMULT numeric(19, 5), @UMRNGMINMULT numeric(19, 5), @UMBELONGTO char(15), @UserDefined1 char(31), @UserDefined2 char(31), @Tar11 char(15), @Tar12 char(15), @Tar13 char(15), @UMTaxSched char(15), @UMINDX smallint, @Imported smallint, @DeliveredEquipmentID char(15), @inPeriodIndex int, @inRate1 char(15), @inRate2 char(15), @inRate3 char(15), @inRate4 char(15), @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @UserID = @v_UM00300_UserID, @LocationID = @v_UM00300_LocationID, @ServiceType = @v_UM00300_ServiceType, @ServiceCategory = @v_UM00300_ServiceCategory, @UMMETGRPID = @v_UM00300_UMMETGRPID, @UMMETGRPTYPE = @v_UM00300_UMMETGRPTYPE, @UMMULTGRPID = @v_UM00300_UMMULTGRPID, @RouteID = @v_UM00300_RouteID, @ConnectStatus = @v_UM00300_ConnectStatus, @TariffID = @v_UM00300_TariffID, @ConnectionDate = @v_UM00300_ConnectionDate, @DisconnectionDate = @v_UM00300_DisconnectionDate, @UMCONNMULT = @v_UM00300_UMCONNMULT, @UMMULTTYPE = @v_UM00300_UMMULTTYPE, @EquipmentID = @v_UM00300_EquipmentID, @UseAltMeter = @v_UM00300_UseAltMeter, @UMSEQNUM = @v_UM00300_UMSEQNUM, @UMFIXEDMULT = @v_UM00300_UMFIXEDMULT, @umConsumpMult = @v_UM00300_umConsumpMult, @UMLOSSMULT = @v_UM00300_UMLOSSMULT, @UMRNGMINMULT = @v_UM00300_UMRNGMINMULT, @UMBELONGTO = @v_UM00300_UMBELONGTO, @UserDefined1 = @v_UM00300_UserDefined1, @UserDefined2 = @v_UM00300_UserDefined2, @Tar11 = @v_UM00300_Tar11, @Tar12 = @v_UM00300_Tar12, @Tar13 = @v_UM00300_Tar13, @UMTaxSched = @v_UM00300_UMTaxSched, @UMINDX = @v_UM00300_UMINDX, @Imported = @v_UM00300_Imported, @DeliveredEquipmentID = @v_UM00300_DeliveredEquipmentID, @inPeriodIndex = @v_UM00300_inPeriodIndex, @inRate1 = @v_UM00300_inRate1, @inRate2 = @v_UM00300_inRate2, @inRate3 = @v_UM00300_inRate3, @inRate4 = @v_UM00300_inRate4, @scMessage = @v_UM00300_scMessage OUTPUT, @scError = @v_UM00300_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UM00300_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UM00300_scError, 0), scMessage = @v_UM00300_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UM00300_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00300_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00300_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UM00300 INTO @v_UM00300_GoldRowId, @v_UM00300_UserID, @v_UM00300_LocationID, @v_UM00300_ServiceType, @v_UM00300_ServiceCategory, @v_UM00300_UMMETGRPID, @v_UM00300_UMMETGRPTYPE, @v_UM00300_UMMULTGRPID, @v_UM00300_RouteID, @v_UM00300_ConnectStatus, @v_UM00300_TariffID, @v_UM00300_ConnectionDate, @v_UM00300_DisconnectionDate, @v_UM00300_UMCONNMULT, @v_UM00300_UMMULTTYPE, @v_UM00300_EquipmentID, @v_UM00300_UseAltMeter, @v_UM00300_UMSEQNUM, @v_UM00300_UMFIXEDMULT, @v_UM00300_umConsumpMult, @v_UM00300_UMLOSSMULT, @v_UM00300_UMRNGMINMULT, @v_UM00300_UMBELONGTO, @v_UM00300_UserDefined1, @v_UM00300_UserDefined2, @v_UM00300_Tar11, @v_UM00300_Tar12, @v_UM00300_Tar13, @v_UM00300_UMTaxSched, @v_UM00300_UMINDX, @v_UM00300_Imported, @v_UM00300_DeliveredEquipmentID, @v_UM00300_inPeriodIndex, @v_UM00300_inRate1, @v_UM00300_inRate2, @v_UM00300_inRate3, @v_UM00300_inRate4;
            END;
            CLOSE c_load_UM00300;
            DEALLOCATE c_load_UM00300;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        IF @Module = 'UM00600H'
        BEGIN
            DECLARE @v_UM00600H_GoldRowId bigint;
            DECLARE @v_UM00600H_UserID char(15);
            DECLARE @v_UM00600H_MoveInCustomerID char(15);
            DECLARE @v_UM00600H_LocationID char(15);
            DECLARE @v_UM00600H_MoveOutCustomerID char(15);
            DECLARE @v_UM00600H_RequestID char(15);
            DECLARE @v_UM00600H_ScheduledDate datetime;
            DECLARE @v_UM00600H_ScheduledTime datetime;
            DECLARE @v_UM00600H_scMessage varchar(255);
            DECLARE @v_UM00600H_scError int;
            DECLARE c_load_UM00600H CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   '' AS [UserID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [MoveInCustomerID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [LocationID]), ''), 15) AS [LocationID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [MoveOutCustomerID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [RecordKey]), ''), 15) AS [RequestID],
                   CONVERT(datetime, '19000101', 112) AS [ScheduledDate],
                   CONVERT(datetime, '19000101', 112) AS [ScheduledTime]
            FROM load.RowStatus s JOIN gold.UM_LocationHistory g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM00600H' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.LocationID, g.CustomerID;
            OPEN c_load_UM00600H;
            FETCH NEXT FROM c_load_UM00600H INTO @v_UM00600H_GoldRowId, @v_UM00600H_UserID, @v_UM00600H_MoveInCustomerID, @v_UM00600H_LocationID, @v_UM00600H_MoveOutCustomerID, @v_UM00600H_RequestID, @v_UM00600H_ScheduledDate, @v_UM00600H_ScheduledTime;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UM00600H_scError = 0;
                SET @v_UM00600H_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateMoveInCustomers @UserID = @UserID, @MoveInCustomerID = @MoveInCustomerID, @LocationID = @LocationID, @MoveOutCustomerID = @MoveOutCustomerID, @RequestID = @RequestID, @ScheduledDate = @ScheduledDate, @ScheduledTime = @ScheduledTime, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@UserID char(15), @MoveInCustomerID char(15), @LocationID char(15), @MoveOutCustomerID char(15), @RequestID char(15), @ScheduledDate datetime, @ScheduledTime datetime, @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @UserID = @v_UM00600H_UserID, @MoveInCustomerID = @v_UM00600H_MoveInCustomerID, @LocationID = @v_UM00600H_LocationID, @MoveOutCustomerID = @v_UM00600H_MoveOutCustomerID, @RequestID = @v_UM00600H_RequestID, @ScheduledDate = @v_UM00600H_ScheduledDate, @ScheduledTime = @v_UM00600H_ScheduledTime, @scMessage = @v_UM00600H_scMessage OUTPUT, @scError = @v_UM00600H_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UM00600H_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UM00600H_scError, 0), scMessage = @v_UM00600H_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UM00600H_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00600H_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM00600H_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UM00600H INTO @v_UM00600H_GoldRowId, @v_UM00600H_UserID, @v_UM00600H_MoveInCustomerID, @v_UM00600H_LocationID, @v_UM00600H_MoveOutCustomerID, @v_UM00600H_RequestID, @v_UM00600H_ScheduledDate, @v_UM00600H_ScheduledTime;
            END;
            CLOSE c_load_UM00600H;
            DEALLOCATE c_load_UM00600H;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        IF @Module = 'UM20400'
        BEGIN
            DECLARE @v_UM20400_GoldRowId bigint;
            DECLARE @v_UM20400_CustomerID char(15);
            DECLARE @v_UM20400_LocationID char(15);
            DECLARE @v_UM20400_Amount numeric(19, 5);
            DECLARE @v_UM20400_MiscChargeType char(15);
            DECLARE @v_UM20400_TransDesc char(33);
            DECLARE @v_UM20400_ServiceType char(15);
            DECLARE @v_UM20400_PenaltyDone tinyint;
            DECLARE @v_UM20400_TransDate datetime;
            DECLARE @v_UM20400_DueDate datetime;
            DECLARE @v_UM20400_TaxSchedule char(15);
            DECLARE @v_UM20400_PaymentType tinyint;
            DECLARE @v_UM20400_DebitAccount int;
            DECLARE @v_UM20400_CreditAccount int;
            DECLARE @v_UM20400_DoNotApplyCreditBalanceToBudget bit;
            DECLARE @v_UM20400_scMessage varchar(255);
            DECLARE @v_UM20400_scError int;
            DECLARE c_load_UM20400 CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [CustomerID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [LocationID]), ''), 15) AS [LocationID],
                   COALESCE(TRY_CONVERT(numeric(19, 5), [BBAmount]), 0) AS [Amount],
                   LEFT(COALESCE(CONVERT(varchar(4000), [BBMisType]), ''), 15) AS [MiscChargeType],
                   LEFT(COALESCE(CONVERT(varchar(4000), [BBTransDesc]), ''), 33) AS [TransDesc],
                   LEFT(COALESCE(CONVERT(varchar(4000), [BBServiceType]), ''), 15) AS [ServiceType],
                   0 AS [PenaltyDone],
                   COALESCE(TRY_CONVERT(datetime, [BBDate]), CONVERT(datetime, '19000101', 112)) AS [TransDate],
                   COALESCE(TRY_CONVERT(datetime, [BBDDate]), CONVERT(datetime, '19000101', 112)) AS [DueDate],
                   LEFT(COALESCE(CONVERT(varchar(4000), [BBMisTaxSchedule]), ''), 15) AS [TaxSchedule],
                   0 AS [PaymentType],
                   COALESCE(TRY_CONVERT(int, [BBDebitAccount]), 0) AS [DebitAccount],
                   COALESCE(TRY_CONVERT(int, [BBCreditAccount]), 0) AS [CreditAccount],
                   0 AS [DoNotApplyCreditBalanceToBudget]
            FROM load.RowStatus s JOIN gold.UM_BegBalance g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM20400' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.CustomerID, g.LocationID, g.RowId;
            OPEN c_load_UM20400;
            FETCH NEXT FROM c_load_UM20400 INTO @v_UM20400_GoldRowId, @v_UM20400_CustomerID, @v_UM20400_LocationID, @v_UM20400_Amount, @v_UM20400_MiscChargeType, @v_UM20400_TransDesc, @v_UM20400_ServiceType, @v_UM20400_PenaltyDone, @v_UM20400_TransDate, @v_UM20400_DueDate, @v_UM20400_TaxSchedule, @v_UM20400_PaymentType, @v_UM20400_DebitAccount, @v_UM20400_CreditAccount, @v_UM20400_DoNotApplyCreditBalanceToBudget;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UM20400_scError = 0;
                SET @v_UM20400_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateBegBalance @CustomerID = @CustomerID, @LocationID = @LocationID, @Amount = @Amount, @MiscChargeType = @MiscChargeType, @TransDesc = @TransDesc, @ServiceType = @ServiceType, @PenaltyDone = @PenaltyDone, @TransDate = @TransDate, @DueDate = @DueDate, @TaxSchedule = @TaxSchedule, @PaymentType = @PaymentType, @DebitAccount = @DebitAccount, @CreditAccount = @CreditAccount, @DoNotApplyCreditBalanceToBudget = @DoNotApplyCreditBalanceToBudget, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@CustomerID char(15), @LocationID char(15), @Amount numeric(19, 5), @MiscChargeType char(15), @TransDesc char(33), @ServiceType char(15), @PenaltyDone tinyint, @TransDate datetime, @DueDate datetime, @TaxSchedule char(15), @PaymentType tinyint, @DebitAccount int, @CreditAccount int, @DoNotApplyCreditBalanceToBudget bit, @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @CustomerID = @v_UM20400_CustomerID, @LocationID = @v_UM20400_LocationID, @Amount = @v_UM20400_Amount, @MiscChargeType = @v_UM20400_MiscChargeType, @TransDesc = @v_UM20400_TransDesc, @ServiceType = @v_UM20400_ServiceType, @PenaltyDone = @v_UM20400_PenaltyDone, @TransDate = @v_UM20400_TransDate, @DueDate = @v_UM20400_DueDate, @TaxSchedule = @v_UM20400_TaxSchedule, @PaymentType = @v_UM20400_PaymentType, @DebitAccount = @v_UM20400_DebitAccount, @CreditAccount = @v_UM20400_CreditAccount, @DoNotApplyCreditBalanceToBudget = @v_UM20400_DoNotApplyCreditBalanceToBudget, @scMessage = @v_UM20400_scMessage OUTPUT, @scError = @v_UM20400_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UM20400_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UM20400_scError, 0), scMessage = @v_UM20400_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UM20400_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM20400_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM20400_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UM20400 INTO @v_UM20400_GoldRowId, @v_UM20400_CustomerID, @v_UM20400_LocationID, @v_UM20400_Amount, @v_UM20400_MiscChargeType, @v_UM20400_TransDesc, @v_UM20400_ServiceType, @v_UM20400_PenaltyDone, @v_UM20400_TransDate, @v_UM20400_DueDate, @v_UM20400_TaxSchedule, @v_UM20400_PaymentType, @v_UM20400_DebitAccount, @v_UM20400_CreditAccount, @v_UM20400_DoNotApplyCreditBalanceToBudget;
            END;
            CLOSE c_load_UM20400;
            DEALLOCATE c_load_UM20400;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        IF @Module = 'UM01900'
        BEGIN
            DECLARE @v_UM01900_GoldRowId bigint;
            DECLARE @v_UM01900_UserID char(15);
            DECLARE @v_UM01900_UserDate datetime;
            DECLARE @v_UM01900_CustomerID char(15);
            DECLARE @v_UM01900_LocationID char(15);
            DECLARE @v_UM01900_DocumentDate datetime;
            DECLARE @v_UM01900_ServiceCategory smallint;
            DECLARE @v_UM01900_DepositAmount numeric(19, 5);
            DECLARE @v_UM01900_PaymentDate datetime;
            DECLARE @v_UM01900_DepositDocument char(15);
            DECLARE @v_UM01900_DepositID char(15);
            DECLARE @v_UM01900_DepositAmtPaid numeric(19, 5);
            DECLARE @v_UM01900_scMessage varchar(255);
            DECLARE @v_UM01900_scError int;
            DECLARE c_load_UM01900 CURSOR LOCAL FAST_FORWARD FOR
            SELECT TOP (CASE WHEN @MaxRows IS NULL THEN 2147483647 ELSE @MaxRows END)
                   s.GoldRowId,
                   '' AS [UserID],
                   COALESCE(TRY_CONVERT(datetime, [DepositDate]), CONVERT(datetime, '19000101', 112)) AS [UserDate],
                   LEFT(COALESCE(CONVERT(varchar(4000), [CustomerID]), ''), 15) AS [CustomerID],
                   LEFT(COALESCE(CONVERT(varchar(4000), [LocationID]), ''), 15) AS [LocationID],
                   COALESCE(TRY_CONVERT(datetime, [DepositDate]), CONVERT(datetime, '19000101', 112)) AS [DocumentDate],
                   COALESCE(TRY_CONVERT(smallint, [Category]), 0) AS [ServiceCategory],
                   COALESCE(TRY_CONVERT(numeric(19, 5), [DepositAmount]), 0) AS [DepositAmount],
                   COALESCE(TRY_CONVERT(datetime, [DepositPaymentDate]), CONVERT(datetime, '19000101', 112)) AS [PaymentDate],
                   '' AS [DepositDocument],
                   LEFT(COALESCE(CONVERT(varchar(4000), [DepositID]), ''), 15) AS [DepositID],
                   COALESCE(TRY_CONVERT(numeric(19, 5), [DepositAmtPaid]), 0) AS [DepositAmtPaid]
            FROM load.RowStatus s JOIN gold.UM_Deposit g ON g.RowId = s.GoldRowId
            WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.Module = 'UM01900' AND s.Status IN ('pending','failed') AND s.Attempts < 3
            ORDER BY g.CustomerID, g.LocationID, g.RowId;
            OPEN c_load_UM01900;
            FETCH NEXT FROM c_load_UM01900 INTO @v_UM01900_GoldRowId, @v_UM01900_UserID, @v_UM01900_UserDate, @v_UM01900_CustomerID, @v_UM01900_LocationID, @v_UM01900_DocumentDate, @v_UM01900_ServiceCategory, @v_UM01900_DepositAmount, @v_UM01900_PaymentDate, @v_UM01900_DepositDocument, @v_UM01900_DepositID, @v_UM01900_DepositAmtPaid;
            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @v_UM01900_scError = 0;
                SET @v_UM01900_scMessage = '';
                BEGIN TRY
                    EXEC sys.sp_executesql N'EXEC conv.UM_SC_spBaseCreateDeposit @UserID = @UserID, @UserDate = @UserDate, @CustomerID = @CustomerID, @LocationID = @LocationID, @DocumentDate = @DocumentDate, @ServiceCategory = @ServiceCategory, @DepositAmount = @DepositAmount, @PaymentDate = @PaymentDate, @DepositDocument = @DepositDocument, @DepositID = @DepositID, @DepositAmtPaid = @DepositAmtPaid, @scMessage = @scMessage OUTPUT, @scError = @scError OUTPUT', N'@UserID char(15), @UserDate datetime, @CustomerID char(15), @LocationID char(15), @DocumentDate datetime, @ServiceCategory smallint, @DepositAmount numeric(19, 5), @PaymentDate datetime, @DepositDocument char(15), @DepositID char(15), @DepositAmtPaid numeric(19, 5), @scMessage varchar(255) OUTPUT, @scError int OUTPUT', @UserID = @v_UM01900_UserID, @UserDate = @v_UM01900_UserDate, @CustomerID = @v_UM01900_CustomerID, @LocationID = @v_UM01900_LocationID, @DocumentDate = @v_UM01900_DocumentDate, @ServiceCategory = @v_UM01900_ServiceCategory, @DepositAmount = @v_UM01900_DepositAmount, @PaymentDate = @v_UM01900_PaymentDate, @DepositDocument = @v_UM01900_DepositDocument, @DepositID = @v_UM01900_DepositID, @DepositAmtPaid = @v_UM01900_DepositAmtPaid, @scMessage = @v_UM01900_scMessage OUTPUT, @scError = @v_UM01900_scError OUTPUT;
                    UPDATE load.RowStatus SET Status = CASE WHEN COALESCE(@v_UM01900_scError, 0) = 0 THEN 'loaded' ELSE 'failed' END, scError = COALESCE(@v_UM01900_scError, 0), scMessage = @v_UM01900_scMessage, Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME(), LoadedAt = CASE WHEN COALESCE(@v_UM01900_scError, 0) = 0 THEN SYSUTCDATETIME() ELSE LoadedAt END WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM01900_GoldRowId;
                END TRY
                BEGIN CATCH
                    UPDATE load.RowStatus SET Status = 'failed', scError = ERROR_NUMBER(), scMessage = LEFT(ERROR_MESSAGE(), 255), Attempts = Attempts + 1, LastAttemptAt = SYSUTCDATETIME() WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module AND GoldRowId = @v_UM01900_GoldRowId;
                END CATCH
                SET @rows = @rows + 1;
                FETCH NEXT FROM c_load_UM01900 INTO @v_UM01900_GoldRowId, @v_UM01900_UserID, @v_UM01900_UserDate, @v_UM01900_CustomerID, @v_UM01900_LocationID, @v_UM01900_DocumentDate, @v_UM01900_ServiceCategory, @v_UM01900_DepositAmount, @v_UM01900_PaymentDate, @v_UM01900_DepositDocument, @v_UM01900_DepositID, @v_UM01900_DepositAmtPaid;
            END;
            CLOSE c_load_UM01900;
            DEALLOCATE c_load_UM01900;
            EXEC run.usp_LogEnd @log, @rows, 'Succeeded', NULL;
            RETURN;
        END;
        RAISERROR('Unknown module for load.usp_LoadModule.', 16, 1);
    END TRY
    BEGIN CATCH
        DECLARE @LoadError nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, @rows, 'Failed', @LoadError;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE load.usp_LoadAll @ClientId varchar(20), @TakeId varchar(20), @Mode varchar(10) = 'row'
AS
/* Purpose: run all CSM load modules in the recommended order. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @Module varchar(30);
    DECLARE c_load_all CURSOR LOCAL FAST_FORWARD FOR SELECT Module FROM load.ProcMap ORDER BY LoadOrder;
    OPEN c_load_all;
    FETCH NEXT FROM c_load_all INTO @Module;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC load.usp_LoadModule @ClientId, @TakeId, @Module, NULL, @Mode;
        FETCH NEXT FROM c_load_all INTO @Module;
    END;
    CLOSE c_load_all;
    DEALLOCATE c_load_all;
END;
GO
