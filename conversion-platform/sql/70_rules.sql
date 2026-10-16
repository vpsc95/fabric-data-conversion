/* =====================================================================
   70_rules.sql: validation rules (ported from reviewer's "* Validation.sql" scripts).

   How it fits together
   - rules.usp_Flag applies one rule's hits (#hit, created by the caller): one run.Issue row per hit
     with the rule ID, severity and expected flag, and the legacy pattern on the gold row (message
     text appended; E -> isvalid 0, W -> isvalid 2 unless already 0).
   - rules.usp_RunSimpleRules runs every enabled single-table rule of a module (lengths, numeric,
     dates, allowed values). The predicates are metadata (meta.RuleCatalog.ConditionSql from
     rules/catalog.yaml, reviewed by pull request); data values are never concatenated into SQL.
   - rules.usp_Validate_<module> holds the cross-entity rules (not found, duplicates, setup lookups),
     in the legacy script order, then calls the simple rules.
   - Severity, enabled/disabled and "expected by design" come from meta.v_EffectiveRule, so tailoring a
     client is a data change. Every procedure is safe to rerun for the same take.
   ===================================================================== */
SET NOCOUNT ON;
GO

CREATE OR ALTER PROCEDURE rules.usp_Flag @ClientId varchar(20), @TakeId varchar(20), @RuleId varchar(60)
AS
/* Purpose: write the rows in #hit (RowId, IsExpected, Detail) for one rule to run.Issue and the gold table.
   Example: EXEC rules.usp_Flag 'sample', 'go-live', 'CONN_DUPLICATE' after filling #hit. */
BEGIN
    SET NOCOUNT ON;
    DECLARE @sev char(1), @enabled bit, @text nvarchar(400), @module varchar(30), @gold sysname, @sql nvarchar(max);
    SELECT @sev = e.Severity, @enabled = e.Enabled, @text = e.LegacyText, @module = e.Module, @gold = r.GoldTable
    FROM meta.v_EffectiveRule e JOIN meta.RuleCatalog r ON r.RuleId = e.RuleId
    WHERE e.ClientId = @ClientId AND e.RuleId = @RuleId;
    IF @module IS NULL OR @gold IS NULL
    BEGIN
        DECLARE @err nvarchar(300) = N'rules.usp_Flag: rule ' + @RuleId + N' is not in meta.RuleCatalog (or has no gold table) for client ' + @ClientId;
        THROW 50001, @err, 1;
    END;
    IF @enabled = 0 RETURN;
    SET @gold = QUOTENAME(PARSENAME(@gold, 2)) + N'.' + QUOTENAME(PARSENAME(@gold, 1));
    SET @sql = N'
        INSERT run.Issue (ClientId, TakeId, Module, RowId, RecordKey, RuleId, Severity, IsExpected, Detail)
        SELECT @c, @t, @module, g.RowId, g.RecordKey, @rule, @sev, ISNULL(h.IsExpected, 0), ISNULL(h.Detail, N'''')
        FROM #hit h JOIN ' + @gold + N' g ON g.RowId = h.RowId;
        UPDATE g SET isvalid = CASE WHEN @sev = ''E'' THEN 0 WHEN g.isvalid = 1 THEN 2 ELSE g.isvalid END,
                     message = g.message + CASE WHEN LEN(g.message) > 0 THEN N'', '' ELSE N'''' END + @text
        FROM ' + @gold + N' g JOIN #hit h ON h.RowId = g.RowId;';
    EXEC sp_executesql @sql, N'@c varchar(20), @t varchar(20), @module varchar(30), @rule varchar(60), @sev char(1), @text nvarchar(400)',
         @ClientId, @TakeId, @module, @RuleId, @sev, @text;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_RunSimpleRules @ClientId varchar(20), @TakeId varchar(20), @Module varchar(30)
AS
/* Purpose: run every enabled single-table rule of a module. The caller must have created #hit.
   Set-based: one batch is generated from rule metadata (gold table + predicate per rule) and run once;
   rule IDs are quoted, predicates come from the reviewed catalog, data values never enter the SQL. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @sql nvarchar(max) = (
        SELECT N'TRUNCATE TABLE #hit; INSERT #hit (RowId) SELECT RowId FROM '
               + QUOTENAME(PARSENAME(m.GoldTable, 2)) + N'.' + QUOTENAME(PARSENAME(m.GoldTable, 1))
               + N' WHERE ClientId = @c AND TakeId = @t AND (' + m.ConditionSql + N'); EXEC rules.usp_Flag @c, @t, '
               + QUOTENAME(m.RuleId, '''') + N';' + NCHAR(10)
        FROM meta.RuleCatalog m JOIN meta.v_EffectiveRule e ON e.RuleId = m.RuleId AND e.ClientId = @ClientId
        WHERE m.Module = @Module AND m.RuleKind = 'simple' AND e.Enabled = 1 AND m.ConditionSql IS NOT NULL
        ORDER BY m.RuleId
        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)');
    IF @sql IS NOT NULL
        EXEC sp_executesql @sql, N'@c varchar(20), @t varchar(20)', @ClientId, @TakeId;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Reset @ClientId varchar(20), @TakeId varchar(20), @Module varchar(30), @GoldTable sysname
AS
/* Purpose: clear earlier results for one module and take (rerun-safe). */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @sql nvarchar(max) = N'UPDATE ' + QUOTENAME(PARSENAME(@GoldTable, 2)) + N'.' + QUOTENAME(PARSENAME(@GoldTable, 1))
        + N' SET isvalid = 1, message = N'''' WHERE ClientId = @c AND TakeId = @t;';
    EXEC sp_executesql @sql, N'@c varchar(20), @t varchar(20)', @ClientId, @TakeId;
    DELETE run.Issue WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = @Module;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_Customer @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: customer (UMRM0101) and customer address (UMRM0111) rules. Legacy: UM_Customer Validation.sql.
   ADDR_SMARTY_NO_MATCH needs the SmartyStreets output, which is not part of the extracts (allowance). */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'rules.usp_Validate_Customer', @log OUTPUT;
    EXEC rules.usp_Reset @ClientId, @TakeId, 'UMRM0101', 'gold.UM_Customer';
    DELETE run.Issue WHERE ClientId = @ClientId AND TakeId = @TakeId AND Module = 'UMRM0111';
    CREATE TABLE #hit (RowId bigint NOT NULL PRIMARY KEY, IsExpected bit NULL, Detail nvarchar(400) NULL);

    -- The same legacy account twice in the extract
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Customer
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND LegacyAcctNo IN (SELECT LegacyAcctNo FROM gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId
                           GROUP BY LegacyAcctNo HAVING COUNT(*) > 1);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CUST_DUPLICATE_CUSTOMER_STAGE';

    -- Customer number already used in the target company before this conversion
    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Customer
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND CustomerID IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UMRM0101');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CUST_DUPLICATE_CUSTOMER_CSM';

    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UMRM0101';
    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UMRM0111';
    EXEC run.usp_LogEnd @log, NULL;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_Location @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: location (UM00600) rules. Legacy: UM_Locations Validation.sql. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'rules.usp_Validate_Location', @log OUTPUT;
    EXEC rules.usp_Reset @ClientId, @TakeId, 'UM00600', 'gold.UM_Location';
    CREATE TABLE #hit (RowId bigint NOT NULL PRIMARY KEY, IsExpected bit NULL, Detail nvarchar(400) NULL);

    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Location
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND Legacy_Loc_ID IN (SELECT Legacy_Loc_ID FROM gold.UM_Location WHERE ClientId = @ClientId AND TakeId = @TakeId
                            GROUP BY Legacy_Loc_ID HAVING COUNT(*) > 1);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'LOC_DUPLICATE_LOCATION';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Location l
    WHERE l.ClientId = @ClientId AND l.TakeId = @TakeId AND l.CustomerID <> 'VACANT'
      AND l.CustomerID NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UMRM0101')
      AND l.CustomerID NOT IN (SELECT CustomerID FROM gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'LOC_CUSTOMER_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Location
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND RouteID NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM40900');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'LOC_ROUTE_NOT_FOUND';

    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UM00600';
    EXEC run.usp_LogEnd @log, NULL;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_Equipment @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: equipment (UM00400) rules. Legacy: UM_Equipment Validation.sql.
   EQUIP_STATUS_NOT_IN_CSM stays disabled for SAMPLE (commented out in the legacy script). */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'rules.usp_Validate_Equipment', @log OUTPUT;
    EXEC rules.usp_Reset @ClientId, @TakeId, 'UM00400', 'gold.UM_Equipment';
    CREATE TABLE #hit (RowId bigint NOT NULL PRIMARY KEY, IsExpected bit NULL, Detail nvarchar(400) NULL);

    -- The same meter twice in staging (for example two rows with different attributes): neither loads
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Equipment
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND EquipmentID IN (SELECT EquipmentID FROM gold.UM_Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId
                          GROUP BY EquipmentID HAVING COUNT(*) > 1);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'EQUIP_DUPLICATE_ID';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Equipment
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND EquipmentID IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM00400');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'EQUIP_ID_ALREADY_IN_CSM';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Equipment
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND EquClassID NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM40600');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'EQUIP_CLASS_NOT_IN_CSM';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Equipment
    WHERE ClientId = @ClientId AND TakeId = @TakeId AND ISNULL(RemoteID, '') <> ''
      AND RemoteID IN (SELECT RemoteID FROM gold.UM_Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId
                       GROUP BY RemoteID HAVING COUNT(*) > 1);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'EQUIP_DUPLICATE_REMOTE_ID_STAGE';

    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UM00400';
    EXEC run.usp_LogEnd @log, NULL;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_Connection @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: connection (UM00300) rules. Legacy: UM_Connections Validation.sql.
   Expected by design (SAMPLE overrides): service types not set up in CSM (DEMO-41065) and the grinder
   fixed tariff GRP (DEMO-41068). Other issues on those records are marked expected afterwards by
   rules.usp_Validate_All, because the record is excluded anyway. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'rules.usp_Validate_Connection', @log OUTPUT;
    EXEC rules.usp_Reset @ClientId, @TakeId, 'UM00300', 'gold.UM_Connection';
    CREATE TABLE #hit (RowId bigint NOT NULL PRIMARY KEY, IsExpected bit NULL, Detail nvarchar(400) NULL);

    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Connection c
    WHERE c.ClientId = @ClientId AND c.TakeId = @TakeId
      AND c.LocationID NOT IN (SELECT LocationID FROM gold.UM_Location WHERE ClientId = @ClientId AND TakeId = @TakeId)
      AND c.LocationID NOT IN (SELECT umLocationID FROM csm.v_LoadedLocation WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_LOCATION_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId, IsExpected, Detail) SELECT RowId, 1, N'service ' + ServiceType + N' is not converted (by design)'
    FROM gold.UM_Connection
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND ServiceType NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM41000');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_INVALID_SERVICE_TYPE';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId, Detail) SELECT RowId, N'meter ' + ISNULL(EquipmentID, N'(none)') + N' not in equipment'
    FROM gold.UM_Connection
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND ISNULL(EquipmentID, '') NOT IN (SELECT EquipmentID FROM gold.UM_Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId AND isvalid <> 0)
      AND ISNULL(EquipmentID, '') NOT IN (SELECT umEquipmentID FROM csm.v_LoadedEquipment WHERE ClientId = @ClientId AND TakeId = @TakeId)
      AND ServiceType NOT IN ('DRAINAGE FEES');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_EQUIPMENT_NOT_FOUND';

    -- Same location, equipment, alternate and service type more than once (NULL equipment never matches, as in the legacy join)
    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT e.RowId
    FROM gold.UM_Connection e
    JOIN (SELECT LocationID, EquipmentID, Alternate, ServiceType FROM gold.UM_Connection
          WHERE ClientId = @ClientId AND TakeId = @TakeId
          GROUP BY LocationID, EquipmentID, Alternate, ServiceType HAVING COUNT(*) > 1) d
      ON e.LocationID = d.LocationID AND e.EquipmentID = d.EquipmentID AND e.Alternate = d.Alternate AND e.ServiceType = d.ServiceType
    WHERE e.ClientId = @ClientId AND e.TakeId = @TakeId;
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_DUPLICATE';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Connection
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND RouteID NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM40900');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_ROUTE_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Connection
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND ConnStatus NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM40630');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_INVALID_STATUS';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId, Detail) SELECT RowId, N'rate ' + CTAR11 + N' not set up'
    FROM gold.UM_Connection
    WHERE ClientId = @ClientId AND TakeId = @TakeId AND CTAR11 <> ''
      AND CTAR11 NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM41301');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_INVALID_RATE';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId, IsExpected, Detail)
    SELECT RowId, CASE WHEN TariffID = 'GRP' THEN 1 ELSE 0 END, N'tariff ' + TariffID + N' not set up'
    FROM gold.UM_Connection
    WHERE ClientId = @ClientId AND TakeId = @TakeId AND TariffID <> ''
      AND TariffID NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM41301');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'CONN_INVALID_TARIFF';

    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UM00300';
    EXEC run.usp_LogEnd @log, NULL;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_BegBalance @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: beginning balance (UM20400) rules. Legacy: UM_BEGBALANCES Validation.sql. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'rules.usp_Validate_BegBalance', @log OUTPUT;
    EXEC rules.usp_Reset @ClientId, @TakeId, 'UM20400', 'gold.UM_BegBalance';
    CREATE TABLE #hit (RowId bigint NOT NULL PRIMARY KEY, IsExpected bit NULL, Detail nvarchar(400) NULL);

    INSERT #hit (RowId) SELECT RowId FROM gold.UM_BegBalance
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND CustomerID NOT IN (SELECT CustomerID FROM gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId)
      AND CustomerID NOT IN (SELECT custnmbr FROM csm.v_LoadedCustomer WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'BAL_CUSTOMER_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_BegBalance
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND LocationID NOT IN (SELECT LocationID FROM gold.UM_Location WHERE ClientId = @ClientId AND TakeId = @TakeId)
      AND LocationID NOT IN (SELECT umLocationID FROM csm.v_LoadedLocation WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'BAL_LOCATION_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId, Detail) SELECT b.RowId, N'customer ' + ISNULL(b.CustomerID, N'(none)') + N' at location ' + ISNULL(b.LocationID, N'(none)')
    FROM gold.UM_BegBalance b
    WHERE b.ClientId = @ClientId AND b.TakeId = @TakeId
      AND NOT EXISTS (SELECT 1 FROM csm.v_LoadedLocation l WHERE l.ClientId = @ClientId AND l.TakeId = @TakeId
                      AND b.CustomerID = l.umBillToCust AND b.LocationID = l.umLocationID)
      AND NOT EXISTS (SELECT 1 FROM csm.v_LoadedLocationHistory h WHERE h.ClientId = @ClientId AND h.TakeId = @TakeId
                      AND b.CustomerID = h.umBillToCust AND b.LocationID = h.umLocationID);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'BAL_CUST_LOC_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_BegBalance
    WHERE ClientId = @ClientId AND TakeId = @TakeId AND LEN(BBMisType) > 0
      AND BBMisType NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM40700');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'BAL_MISC_CHARGE_CODE_NOT_IN_CSM';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_BegBalance
    WHERE ClientId = @ClientId AND TakeId = @TakeId AND LEN(BBServiceType) > 0
      AND BBServiceType NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM41000');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'BAL_SERVICE_TYPE_NOT_IN_CSM';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_BegBalance
    WHERE ClientId = @ClientId AND TakeId = @TakeId AND LEN(BBMisTaxSchedule) > 0
      AND BBMisTaxSchedule NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'TX00101');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'BAL_TAX_SCHEDULE_NOT_IN_CSM';

    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UM20400';
    EXEC run.usp_LogEnd @log, NULL;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_Deposit @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: deposit (UM01900) rules. Legacy: UM_DEPOSITS Validation.sql. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'rules.usp_Validate_Deposit', @log OUTPUT;
    EXEC rules.usp_Reset @ClientId, @TakeId, 'UM01900', 'gold.UM_Deposit';
    CREATE TABLE #hit (RowId bigint NOT NULL PRIMARY KEY, IsExpected bit NULL, Detail nvarchar(400) NULL);

    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Deposit
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND ((CustomerID NOT IN (SELECT CustomerID FROM gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId)
            AND CustomerID NOT IN (SELECT custnmbr FROM csm.v_LoadedCustomer WHERE ClientId = @ClientId AND TakeId = @TakeId))
           OR CustomerID IS NULL);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'DEP_CUSTOMER_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Deposit
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND LocationID NOT IN (SELECT LocationID FROM gold.UM_Location WHERE ClientId = @ClientId AND TakeId = @TakeId)
      AND LocationID NOT IN (SELECT umLocationID FROM csm.v_LoadedLocation WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'DEP_LOCATION_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId, Detail) SELECT d.RowId, N'customer ' + ISNULL(d.CustomerID, N'(none)') + N' at location ' + ISNULL(d.LocationID, N'(none)')
    FROM gold.UM_Deposit d
    WHERE d.ClientId = @ClientId AND d.TakeId = @TakeId
      AND NOT EXISTS (SELECT 1 FROM csm.v_LoadedLocation l WHERE l.ClientId = @ClientId AND l.TakeId = @TakeId
                      AND d.CustomerID = l.umBillToCust AND d.LocationID = l.umLocationID)
      AND NOT EXISTS (SELECT 1 FROM csm.v_LoadedLocationHistory h WHERE h.ClientId = @ClientId AND h.TakeId = @TakeId
                      AND d.CustomerID = h.umBillToCust AND d.LocationID = h.umLocationID);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'DEP_CUST_LOC_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_Deposit
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND DepositID NOT IN (SELECT Code FROM ref.SetupValue WHERE ClientId = @ClientId AND SetupTable = 'UM41930');
    EXEC rules.usp_Flag @ClientId, @TakeId, 'DEP_ID_NOT_IN_CSM';

    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UM01900';
    EXEC run.usp_LogEnd @log, NULL;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_HistMR @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: historical meter read (UM30300) rules. Legacy: UM_HISTMR Validation.sql.
   The 'D' register override runs before the equipment check, as in the legacy script: a D meter that
   isn't in equipment is replaced by the E meter it was merged into (original ID kept in UMEQUMULT). */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'rules.usp_Validate_HistMR', @log OUTPUT;
    EXEC rules.usp_Reset @ClientId, @TakeId, 'UM30300', 'gold.UM_HistMR';
    CREATE TABLE #hit (RowId bigint NOT NULL PRIMARY KEY, IsExpected bit NULL, Detail nvarchar(400) NULL);

    INSERT #hit (RowId) SELECT RowId FROM gold.UM_HistMR
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND CustomerID NOT IN (SELECT CustomerID FROM gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId)
      AND CustomerID NOT IN (SELECT custnmbr FROM csm.v_LoadedCustomer WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'READ_CUSTOMER_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_HistMR
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND LocationID NOT IN (SELECT LocationID FROM gold.UM_Location WHERE ClientId = @ClientId AND TakeId = @TakeId)
      AND LocationID NOT IN (SELECT umLocationID FROM csm.v_LoadedLocation WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'READ_LOCATION_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT r.RowId
    FROM gold.UM_HistMR r
    WHERE r.ClientId = @ClientId AND r.TakeId = @TakeId
      AND NOT EXISTS (SELECT 1 FROM csm.v_LoadedLocation l WHERE l.ClientId = @ClientId AND l.TakeId = @TakeId
                      AND r.CustomerID = l.umBillToCust AND r.LocationID = l.umLocationID)
      AND NOT EXISTS (SELECT 1 FROM csm.v_LoadedLocationHistory h WHERE h.ClientId = @ClientId AND h.TakeId = @TakeId
                      AND r.CustomerID = h.umBillToCust AND r.LocationID = h.umLocationID);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'READ_CUST_LOC_NOT_FOUND';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId, Detail) SELECT RowId, N'meter ' + EquipmentID + N' replaced by ' + REPLACE(EquipmentID, 'D', 'E')
    FROM gold.UM_HistMR
    WHERE ClientId = @ClientId AND TakeId = @TakeId AND RIGHT(EquipmentID, 1) = 'D'
      AND EquipmentID NOT IN (SELECT EquipmentID FROM gold.UM_Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId AND isvalid <> 0)
      AND EquipmentID NOT IN (SELECT umEquipmentID FROM csm.v_LoadedEquipment WHERE ClientId = @ClientId AND TakeId = @TakeId);
    UPDATE r SET UMEQUMULT = r.EquipmentID, EquipmentID = REPLACE(r.EquipmentID, 'D', 'E')
    FROM gold.UM_HistMR r JOIN #hit h ON h.RowId = r.RowId;
    EXEC rules.usp_Flag @ClientId, @TakeId, 'READ_EQUIPMENT_ID_OVERRIDE';

    TRUNCATE TABLE #hit;
    INSERT #hit (RowId) SELECT RowId FROM gold.UM_HistMR
    WHERE ClientId = @ClientId AND TakeId = @TakeId
      AND EquipmentID NOT IN (SELECT EquipmentID FROM gold.UM_Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId AND isvalid <> 0)
      AND EquipmentID NOT IN (SELECT umEquipmentID FROM csm.v_LoadedEquipment WHERE ClientId = @ClientId AND TakeId = @TakeId);
    EXEC rules.usp_Flag @ClientId, @TakeId, 'READ_EQUIPMENT_NOT_FOUND';

    EXEC rules.usp_RunSimpleRules @ClientId, @TakeId, 'UM30300';
    EXEC run.usp_LogEnd @log, NULL;
END;
GO

CREATE OR ALTER PROCEDURE rules.usp_Validate_All @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: run every module's rules in the legacy order (customers -> locations -> equipment ->
   connections -> balances -> deposits -> reads), then mark every issue on a record that is excluded
   by design as expected too: that record won't load anyway, so its other issues aren't actionable. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    EXEC rules.usp_Validate_Customer   @ClientId, @TakeId;
    EXEC rules.usp_Validate_Location   @ClientId, @TakeId;
    EXEC rules.usp_Validate_Equipment  @ClientId, @TakeId;
    EXEC rules.usp_Validate_Connection @ClientId, @TakeId;
    EXEC rules.usp_Validate_BegBalance @ClientId, @TakeId;
    EXEC rules.usp_Validate_Deposit    @ClientId, @TakeId;
    EXEC rules.usp_Validate_HistMR     @ClientId, @TakeId;

    UPDATE i SET IsExpected = 1,
                 Detail = LEFT(i.Detail + CASE WHEN LEN(i.Detail) > 0 THEN N'; ' ELSE N'' END + N'record excluded by design', 400)
    FROM run.Issue i
    WHERE i.ClientId = @ClientId AND i.TakeId = @TakeId AND i.IsExpected = 0
      AND EXISTS (SELECT 1 FROM run.Issue x WHERE x.ClientId = i.ClientId AND x.TakeId = i.TakeId AND x.Module = i.Module
                  AND x.RowId = i.RowId AND x.IsExpected = 1 AND x.Severity = 'E');

    -- signatures for triage (sql/85_triage.sql), then approved triage decisions (gate 3) that a group is expected by design
    EXEC recon.usp_BuildIssueRecords @ClientId, @TakeId;
    EXEC rules.usp_ApplyTriageDecisions @ClientId, @TakeId;
END;
GO
