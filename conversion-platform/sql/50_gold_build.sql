/* =====================================================================
   50_gold_build.sql: build UM staging (gold) for one take from silver (slv) + crosswalks (xref).

   Ported from reviewer's COGS_STAGING procedures (sp_Load_UM_Customer, SP_Load_UM_LOCATIONS,
   sp_Load_UM_EQUIPMENT, sp_Load_UM_CONNECTIONS, sp_Load_UM_BEGBALANCES, sp_Load_UM_DEPOSITS,
   sp_Load_UM_HistMR). The business logic is the same; what changed:
   - no three-part names (COGS_STAGING.dbo...) and no hard-coded CASE lists: code translations come
     from xref (clients/<client>/crosswalks/<name>.yaml), so tailoring a client is a data change;
   - every procedure rebuilds one take (DELETE by ClientId/TakeId, then INSERT), logs to run.RunLog
     and rolls back on error;
   - the account helper columns the client built by hand in Excel (ACCT/STDATE) are replaced by the
     platform's own fill-down (ACCT_FILL/STDATE_FILL; identical on the go-live take);
   - where the legacy UPDATE ... FROM could pick any of several matches, the lowest value is taken
     (deterministic); this is noted at each spot.
   Golden master: clients/<client> replay + .github/skills/golden-master-test.
   ===================================================================== */
SET NOCOUNT ON;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_Customer @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : customer staging (UMRM0101) - one row per account in the CUSTOMERS extract.
   Legacy  : sp_Load_UM_Customer (reviewer 20260121 / 20260126).
   Logic   : CustomerIDX = row order of the extract (SourceRow).
             CustomerID  = CustomerIDX + 100000, except accounts with the same LastName + ADDRESS1
                           (both non-blank) share the lowest CustomerIDX of the group: one CSM
                           customer with several accounts. ID numbers the accounts per CustomerID
                           (ID = 1 is the one CSM loads).
             LocationID  = CustomerIDX + 500000 for ACTIVE accounts, and for a Finaled account that is
                           the only active-or-finaled account at its location (LEFT(acct,7) = route +
                           location); history accounts then point to the current location; at a
                           location with only finaled accounts they take the lowest finaled one.
   Example : 04-0123-00 ACTIVE row 17 -> CustomerID 100017, LocationID 500017; 04-0123-01 Inactive
             at the same location -> LocationID 500017. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_Customer', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId;

        WITH src AS (
            SELECT a.*, CustomerIDX = a.SourceRow,
                   LnKey = UPPER(LTRIM(RTRIM(a.LASTNAME))), A1Key = UPPER(LTRIM(RTRIM(a.ADDRESS1))),
                   Base7 = LEFT(a.INCODEACCT, 7)
            FROM slv.Customers a WHERE a.TakeId = @TakeId
        ), t AS (
            SELECT s.*,
                   CustomerIDNum = CASE WHEN COUNT(*) OVER (PARTITION BY LnKey, A1Key) > 1 AND LnKey <> '' AND A1Key <> ''
                                        THEN MIN(CustomerIDX) OVER (PARTITION BY LnKey, A1Key) ELSE CustomerIDX END + 100000,
                   ActOrFinAtLocation = SUM(CASE WHEN CUSTOMERSTATUS IN ('ACTIVE', 'Finaled') THEN 1 ELSE 0 END) OVER (PARTITION BY Base7)
            FROM src s
        )
        INSERT gold.UM_Customer (ClientId, TakeId, SourceRow, RecordKey, LegacyAcctNo, CustomerID, CustomerIDX, Individual,
               FirstName, LastName, SIN, DateOfBirth, PlaceOfWork, ADDRESS1, ADDRESS2, City, [STATE], Country, Zip, ADRSCODE,
               CustomerClassID, PaymentTermID, Phone1, Phone2, Phone3, Email, ContactPerson, AlternateID, LocationID,
               New_Existing, ID, SecCustIDX)
        SELECT @ClientId, @TakeId, t.SourceRow, t.INCODEACCT, t.INCODEACCT, CAST(t.CustomerIDNum AS varchar(15)), t.CustomerIDX,
               CASE WHEN t.FIRSTNAME = '' AND t.LASTNAME <> '' THEN 0 ELSE 1 END,
               t.FIRSTNAME, t.LASTNAME, REPLACE(REPLACE(t.SOCIAL, '-', ''), ' ', ''),
               CASE WHEN NULLIF(LTRIM(RTRIM(t.DOB)), '') IS NULL THEN NULL
                    WHEN LEN(LTRIM(RTRIM(t.DOB))) = 7 AND LTRIM(RTRIM(t.DOB)) LIKE '[12][0-9][0-9][0-9]-[01][0-9]'
                         THEN TRY_CONVERT(date, LTRIM(RTRIM(t.DOB)) + '-01', 23)
                    ELSE TRY_CONVERT(date, LTRIM(RTRIM(t.DOB)), 23) END,
               CASE WHEN t.FIRSTNAME = '' THEN t.LASTNAME ELSE '' END,                 -- business name goes to PlaceOfWork
               t.ADDRESS1, t.ADDRESS2, t.CITY, t.ST, 'USA', REPLACE(t.ZIP, '-', ''), 'PRIMARY',
               CASE WHEN t.FIRSTNAME = '' AND t.LASTNAME <> '' THEN 'COM' ELSE 'RES' END, 'NET20',
               p1.Phone, p2.Phone, p3.Phone, t.EMAIL, t.ADDRESSATTN,
               LTRIM(RTRIM(t.DRIVERSLICENSE)) + ' ' + LTRIM(RTRIM(t.DLST)),
               CAST(CASE WHEN t.CUSTOMERSTATUS = 'ACTIVE' THEN t.CustomerIDX + 500000
                         WHEN t.CUSTOMERSTATUS = 'Finaled' AND t.ActOrFinAtLocation = 1 THEN t.CustomerIDX + 500000
                         ELSE 0 END AS varchar(15)),
               t.CUSTOMERSTATUS,
               ROW_NUMBER() OVER (PARTITION BY t.CustomerIDNum ORDER BY t.CustomerIDX),
               t.CustomerIDX + 10000                                               -- legacy SecCustIDX + 10000 (identity order)
        FROM t
        CROSS APPLY gold.fn_CleanPhone(t.PHONENUMBER) p1
        CROSS APPLY gold.fn_CleanPhone(t.HOMENUMBER) p2
        CROSS APPLY gold.fn_CleanPhone(t.CELLNUMBER) p3;
        SET @rows = @@ROWCOUNT;

        -- History accounts point to the current location at the same LEFT(acct,7).
        -- (Legacy UPDATE..FROM picks any match when two accounts are active there; lowest is taken.)
        UPDATE h SET LocationID = c.LocationID
        FROM gold.UM_Customer h
        CROSS APPLY (SELECT MIN(c.LocationID) AS LocationID FROM gold.UM_Customer c
                     WHERE c.ClientId = h.ClientId AND c.TakeId = h.TakeId
                       AND LEFT(c.LegacyAcctNo, 7) = LEFT(h.LegacyAcctNo, 7) AND c.LocationID <> '0') c
        WHERE h.ClientId = @ClientId AND h.TakeId = @TakeId AND h.LocationID = '0' AND c.LocationID IS NOT NULL;

        -- Locations with only finaled accounts: finaled accounts take the lowest finaled CustomerIDX + 500000.
        UPDATE f SET LocationID = CAST(x.MinLoc AS varchar(15))
        FROM gold.UM_Customer f
        CROSS APPLY (SELECT MIN(s.SourceRow) + 500000 AS MinLoc FROM slv.Customers s
                     WHERE s.TakeId = f.TakeId AND LEFT(s.INCODEACCT, 7) = LEFT(f.LegacyAcctNo, 7) AND s.CUSTOMERSTATUS = 'FINALED') x
        WHERE f.ClientId = @ClientId AND f.TakeId = @TakeId AND f.New_Existing = 'FINALED' AND f.LocationID = '0' AND x.MinLoc IS NOT NULL;

        -- Repeat the history pointer for the locations just assigned.
        UPDATE h SET LocationID = c.LocationID
        FROM gold.UM_Customer h
        CROSS APPLY (SELECT MIN(c.LocationID) AS LocationID FROM gold.UM_Customer c
                     WHERE c.ClientId = h.ClientId AND c.TakeId = h.TakeId
                       AND LEFT(c.LegacyAcctNo, 7) = LEFT(h.LegacyAcctNo, 7) AND c.LocationID <> '0') c
        WHERE h.ClientId = @ClientId AND h.TakeId = @TakeId AND h.LocationID = '0' AND c.LocationID IS NOT NULL;

        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_Location @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : location staging (UM00600).
   Legacy  : SP_Load_UM_LOCATIONS (reviewer 20260121 / 20260126).
   Logic   : one location per ACTIVE account, plus Finaled accounts at locations with no Active account.
             Non-active bill-to becomes VACANT. City and zone from the route (LEFT(acct,2)); location
             class from the customer class (xref). Double quotes removed from the service address.
             Duplicate LocationIDs (several finaled accounts at one location): the highest account
             number is removed, as the legacy DELETE did. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_Location', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_Location WHERE ClientId = @ClientId AND TakeId = @TakeId;

        INSERT gold.UM_Location (ClientId, TakeId, SourceRow, RecordKey, Legacy_Loc_ID, LocationID, CustomerID, Category,
               SStreetNumber, SStreetName, SStreetDirPF, SStreetType, SAptNo,
               SCity, SState, SCountry, SZip, AdrCategory, ADRSCODE, LocationClass, ThirdPartyDesc, NoResUnits, ZoneID, RouteID,
               SAddress1, UUDF2, ID)
        SELECT @ClientId, @TakeId, a.SourceRow, a.LegacyAcctNo, a.LegacyAcctNo, a.LocationID,
               CASE WHEN b.CUSTOMERSTATUS <> 'ACTIVE' THEN 'VACANT' ELSE a.CustomerID END, '1',
               b.SA_NUMBER, b.SA_NAME, b.SA_PREDIR, b.SA_SUFFIX, b.SA_UNIT,
               rc.City, 'TX', 'USA', '', '1', 'PRIMARY', ISNULL(lc.LocationClass, ''), a.LegacyAcctNo, '1',
               ISNULL(z.ZoneID, ''), LEFT(a.LegacyAcctNo, 2), REPLACE(b.SERVICEADDRESS, '"', ''), b.CUSTOMERSTATUS, a.ID
        FROM gold.UM_Customer a
        JOIN slv.Customers b ON b.TakeId = a.TakeId AND b.INCODEACCT = a.LegacyAcctNo
        LEFT JOIN xref.v_RouteCity rc ON rc.ClientId = a.ClientId AND rc.RouteID = LEFT(a.LegacyAcctNo, 2)
        LEFT JOIN xref.v_RouteZone z ON z.ClientId = a.ClientId AND z.RouteID = LEFT(a.LegacyAcctNo, 2)
        LEFT JOIN xref.v_LocationClass lc ON lc.ClientId = a.ClientId AND lc.CustomerClass = b.CUSTOMERCLASS
        WHERE a.ClientId = @ClientId AND a.TakeId = @TakeId
          AND (b.CUSTOMERSTATUS = 'ACTIVE'
               OR b.INCODEACCT IN (SELECT f.INCODEACCT FROM slv.Customers f
                                   WHERE f.TakeId = @TakeId AND f.CUSTOMERSTATUS IN ('Finaled')
                                     AND LEFT(f.INCODEACCT, 7) NOT IN (SELECT LEFT(x.INCODEACCT, 7) FROM slv.Customers x
                                                                       WHERE x.TakeId = @TakeId AND x.CUSTOMERSTATUS IN ('Active'))));
        SET @rows = @@ROWCOUNT;

        DELETE gold.UM_Location
        WHERE ClientId = @ClientId AND TakeId = @TakeId
          AND Legacy_Loc_ID IN (SELECT MAX(Legacy_Loc_ID) FROM gold.UM_Location
                                WHERE ClientId = @ClientId AND TakeId = @TakeId
                                  AND LocationID IN (SELECT LocationID FROM gold.UM_Location
                                                     WHERE ClientId = @ClientId AND TakeId = @TakeId
                                                     GROUP BY LocationID HAVING COUNT(*) > 1)
                                GROUP BY LocationID);
        SET @rows = @rows - @@ROWCOUNT;
        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_Equipment @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : equipment staging (UM00400): one row per distinct meter in the reads extract for accounts
             that appear in the services report. Defaults: installed, status 1, multiplier 100, RF remote.
   Legacy  : sp_Load_UM_EQUIPMENT (SELECT DISTINCT over reads joined to services by account).
   Note    : DifferenceReadingDials = TRY_CONVERT(INT, 'Dials') in the legacy script converts the literal
             text 'Dials' (always NULL); kept as-is and raised as open question OQ-EQ-DIALS. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_Equipment', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId;
        INSERT gold.UM_Equipment (ClientId, TakeId, RecordKey, LegacyAcctNo, EquipmentID, SerialNo, EquClassID, ServiceCategory,
               ConsEst, Installed, InstallDate, EquipmentStatus, InstallableStatus, EqMult, RemovalDate, Manufacturer, Diameter,
               TOTCONSUMP, RemoteID, RInstallationDate, RemoteType, DifferenceReadingDials, NetMeterType, DifferenceReadingsDialDigits,
               KWDialDigits, DifferenceDialDecimals, KWDialDecimals, DifferenceReadingDialMultiplier, KWDialMultiplier,
               PFDialMultiplier, MODEL)
        SELECT DISTINCT @ClientId, @TakeId, a.Meter_ID + N'|' + a.Account_ID, a.Account_ID, a.Meter_ID, a.Meter_SN, ec.EquClassID, '2',
               '0', 1, c.STARTDATE, 1, '0', 100, '1900-01-01', a.Meter_Manufacturer, a.Meter_Size,
               a.Dials, a.Endpoint_SN, c.STARTDATE, 'RF', TRY_CONVERT(int, NULLIF(LTRIM(RTRIM('Dials')), '')), '2', '1',
               '0', a.Dials, '0', '0', '0',
               '0', a.Meter_Model
        FROM slv.Reads a
        JOIN slv.Services c ON c.TakeId = a.TakeId AND c.ACCOUNTNUM = a.Account_ID
        LEFT JOIN xref.v_EquipmentClass ec ON ec.ClientId = @ClientId AND ec.MeterSize = a.Meter_Size_Desc
        WHERE a.TakeId = @TakeId;
        SET @rows = @@ROWCOUNT;
        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_Connection @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : connection staging (UM00300): one row per service line on the services report (two
             service slots per line), for accounts that have a location.
   Legacy  : sp_Load_UM_CONNECTIONS "New Logic" (reviewer 20260128 / 20260225 / 20260410 / 20260417).
   Logic   : drop PULLED meters, blank descriptions and OFF services; service code = LEFT(DESCRIPTION,3);
             category, service type (residential vs commercial from UM_Customer.Individual) and fixed
             tariff from xref.v_ServiceCode; unmapped codes keep the code as service type (they fail the
             service-type rule by design); water variable tariff from meter size; sewer tariff from
             Individual. Then: add the leading 0 Excel dropped from meter numbers; sewer connections take
             the location's water meter (except flat rates COM/FLT, OQ-CONN-FLATRATE-SEWER); equipment
             with no connection becomes uninstalled / installable.
   Note    : the second service slot joins the reads on METER (not METER2), exactly as the legacy script. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_Connection', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_Connection WHERE ClientId = @ClientId AND TakeId = @TakeId;

        WITH x AS (
            SELECT ACCT = a.ACCT_FILL, b.LocationID, DESCRIPTION = a.DESCRIPTION, c.Service_Point_Class_Code, METER = a.METER,
                   STDATE = a.STDATE_FILL, TBL = a.[TABLE], c.Meter_Size_Desc, ServiceSlot = 1, SourceRow = MIN(a.SourceRow)
            FROM slv.Services a
            JOIN gold.UM_Location b ON b.ClientId = @ClientId AND b.TakeId = @TakeId AND b.Legacy_Loc_ID = a.ACCT_FILL
            LEFT JOIN slv.Reads c ON c.TakeId = a.TakeId AND c.Meter_ID = a.METER
            WHERE a.TakeId = @TakeId AND a.METER <> 'PULLED' AND a.DESCRIPTION <> '' AND a.STATUS <> 'OFF'
            GROUP BY a.ACCT_FILL, b.LocationID, a.DESCRIPTION, c.Service_Point_Class_Code, a.METER, a.STDATE_FILL, a.[TABLE], c.Meter_Size_Desc
            UNION ALL
            SELECT a.ACCT_FILL, b.LocationID, a.DESCRIPTION2, c.Service_Point_Class_Code, a.METER2,
                   a.STDATE_FILL, a.TABLE2, c.Meter_Size_Desc, 2, MIN(a.SourceRow)
            FROM slv.Services a
            JOIN gold.UM_Location b ON b.ClientId = @ClientId AND b.TakeId = @TakeId AND b.Legacy_Loc_ID = a.ACCT_FILL
            LEFT JOIN slv.Reads c ON c.TakeId = a.TakeId AND c.Meter_ID = a.METER
            WHERE a.TakeId = @TakeId AND a.METER2 <> 'PULLED' AND a.DESCRIPTION2 <> '' AND a.STATUS2 <> 'OFF'
            GROUP BY a.ACCT_FILL, b.LocationID, a.DESCRIPTION2, c.Service_Point_Class_Code, a.METER2, a.STDATE_FILL, a.TABLE2, c.Meter_Size_Desc
        )
        INSERT gold.UM_Connection (ClientId, TakeId, SourceRow, ServiceSlot, RecordKey, LegacyAcctNo, Legacy_Loc_ID, LocationID,
               Category, ServiceType, EquipmentID, Alternate, RouteID, ConnStatus, ConnDate, DisconnDate, SEQNO, TariffID, CTAR11,
               Legacy_Service, Legacy_Service_Class, flat_rate)
        SELECT @ClientId, @TakeId, x.SourceRow, x.ServiceSlot,
               x.ACCT + N'|' + LEFT(x.DESCRIPTION, 3) + N'|' + CAST(x.ServiceSlot AS nvarchar(1)) + N'|' + CAST(x.SourceRow AS nvarchar(10)),
               x.ACCT, x.ACCT, x.LocationID,
               ISNULL(sc.Category, '99'),
               CASE WHEN sc.ServiceCode IS NULL THEN LEFT(x.DESCRIPTION, 3)
                    WHEN c.Individual = 1 THEN sc.ServiceTypeRes ELSE sc.ServiceTypeCom END,
               x.METER, '0', LEFT(x.ACCT, 2), '2', x.STDATE, '1900-01-01', '0',
               ISNULL(sc.FixedTariff, ''),
               CASE sc.Category
                    WHEN '2' THEN CASE WHEN c.Individual = 1 THEN ISNULL(wt.ResTariff, 'WR') ELSE ISNULL(wt.ComTariff, 'WC') END
                    WHEN '3' THEN ISNULL(sv.SewerTariff, sv0.SewerTariff)
                    ELSE '' END,
               x.DESCRIPTION, x.Service_Point_Class_Code, x.TBL
        FROM x
        LEFT JOIN gold.UM_Customer c ON c.ClientId = @ClientId AND c.TakeId = @TakeId AND c.LegacyAcctNo = x.ACCT
        LEFT JOIN xref.v_ServiceCode sc ON sc.ClientId = @ClientId AND sc.ServiceCode = LEFT(x.DESCRIPTION, 3) AND sc.Include = 1
        LEFT JOIN xref.v_WaterTariff wt ON wt.ClientId = @ClientId AND wt.MeterSize = x.Meter_Size_Desc
        LEFT JOIN xref.v_ServiceClass sv ON sv.ClientId = @ClientId AND sv.Individual = CAST(c.Individual AS varchar(1)) AND c.Individual = 1
        LEFT JOIN xref.v_ServiceClass sv0 ON sv0.ClientId = @ClientId AND sv0.Individual = '0';
        SET @rows = @@ROWCOUNT;

        -- Excel dropped the leading 0 from meter numbers in the services report: restore it where the
        -- equipment (from the AMI reads) has it.
        UPDATE c SET EquipmentID = '0' + c.EquipmentID
        FROM gold.UM_Connection c
        WHERE c.ClientId = @ClientId AND c.TakeId = @TakeId
          AND c.EquipmentID IN (SELECT RIGHT(e.EquipmentID, LEN(e.EquipmentID) - 1) FROM gold.UM_Equipment e
                                WHERE e.ClientId = @ClientId AND e.TakeId = @TakeId AND e.EquipmentID LIKE '0%');

        -- Sewer is measured by the location's water meter (Alternate = 1), except flat-rate sewer.
        -- (Legacy note: "even with below criteria, one existed with multiple water" - MAX is kept.)
        UPDATE s SET EquipmentID = (SELECT MAX(w.EquipmentID) FROM gold.UM_Connection w
                                    WHERE w.ClientId = s.ClientId AND w.TakeId = s.TakeId AND w.ServiceType LIKE 'WAT%'
                                      AND w.LocationID = s.LocationID AND w.EquipmentID <> ''),
                     Alternate = '1'
        FROM gold.UM_Connection s
        WHERE s.ClientId = @ClientId AND s.TakeId = @TakeId AND s.ServiceType LIKE 'SWR%' AND s.flat_rate NOT IN ('COM', 'FLT');

        -- Equipment with no connection: not installed, installable (DEMO-41804).
        UPDATE gold.UM_Equipment SET Installed = 0, InstallableStatus = '1'
        WHERE ClientId = @ClientId AND TakeId = @TakeId
          AND EquipmentID NOT IN (SELECT EquipmentID FROM gold.UM_Connection
                                  WHERE ClientId = @ClientId AND TakeId = @TakeId AND EquipmentID <> '');
        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_BegBalance @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : beginning balances (UM20400): one Z-BEG BAL misc charge per account balance line.
   Legacy  : sp_Load_UM_BEGBALANCES (reviewer 20260121 / 20260408).
   Logic   : the account's first report line carries BALANCE; blank and zero balances are skipped;
             customer and location come from customer staging; GL accounts and the misc charge type
             come from xref (balance_gl_accounts); dates are the conversion date.
   Note    : the legacy zero test is textual (BALANCE <> '0'); the received text is kept in BBAmount. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int, @conv date = (SELECT ConversionDate FROM meta.Client WHERE ClientId = @ClientId);
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_BegBalance', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_BegBalance WHERE ClientId = @ClientId AND TakeId = @TakeId;
        INSERT gold.UM_BegBalance (ClientId, TakeId, SourceRow, RecordKey, LegacyAcctNo, Legacy_Loc_ID, CustomerID, LocationID,
               BBAmount, BBMisType, BBServiceType, BBTransDesc, BBDate, BBDDate, BBCreditAccount, BBDebitAccount, BBMisTaxSchedule)
        SELECT @ClientId, @TakeId, a.SourceRow, a.ACCT_FILL + N'|' + CAST(a.SourceRow AS nvarchar(10)), a.ACCT_FILL, a.ACCT_FILL,
               c.CustomerID, c.LocationID, a.BALANCE,
               (SELECT Value FROM xref.v_BalanceConstant WHERE ClientId = @ClientId AND Setting = 'BBMisType'), '', '',
               @conv, @conv,
               (SELECT Value FROM xref.v_BalanceConstant WHERE ClientId = @ClientId AND Setting = 'BBCreditAccount'),
               (SELECT Value FROM xref.v_BalanceConstant WHERE ClientId = @ClientId AND Setting = 'BBDebitAccount'), ''
        FROM slv.Balances a
        JOIN gold.UM_Customer c ON c.ClientId = @ClientId AND c.TakeId = @TakeId AND c.LegacyAcctNo = a.ACCT_FILL
        WHERE a.TakeId = @TakeId AND a.BALANCE <> '' AND a.BALANCE <> '0';
        SET @rows = @@ROWCOUNT;
        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_Deposit @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : deposits (UM01900): unrefunded deposits with a positive amount (received + unbilled).
   Legacy  : sp_Load_UM_DEPOSITS (reviewer 20260126).
   Logic   : deposit type from the account's water connection (WATER-COM -> COMM-DEP, otherwise
             RESI-DEP, OQ-DEP-DEFAULT); payment date = deposit date when something was received.
   Note    : like the legacy script, an account with two water connections yields two deposit rows. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int;
    DECLARE @default varchar(30) = (SELECT DepositID FROM xref.v_DepositType WHERE ClientId = @ClientId AND ServiceType LIKE '<%');
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_Deposit', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_Deposit WHERE ClientId = @ClientId AND TakeId = @TakeId;
        INSERT gold.UM_Deposit (ClientId, TakeId, SourceRow, RecordKey, LegacyAcctNo, Legacy_Loc_ID, CustomerID, LocationID,
               DepositAmount, DepositDate, DepositID, Category, DepositPaymentDate, DepositAmtPaid)
        SELECT @ClientId, @TakeId, a.SourceRow, a.ACCOUNTNUM + N'|' + CAST(a.SourceRow AS nvarchar(10)), a.ACCOUNTNUM, a.ACCOUNTNUM,
               b.CustomerID, b.LocationID,
               TRY_CONVERT(numeric(19,5), a.RECEIVED) + TRY_CONVERT(numeric(19,5), a.UNBILLED), a.DEPDATE,
               ISNULL(dt.DepositID, @default), '2',
               CASE WHEN TRY_CONVERT(numeric(19,5), a.RECEIVED) > 0 THEN a.DEPDATE ELSE '1900-01-01' END, a.RECEIVED
        FROM slv.Deposits a
        LEFT JOIN gold.UM_Customer b ON b.ClientId = @ClientId AND b.TakeId = @TakeId AND b.LegacyAcctNo = a.ACCOUNTNUM
        LEFT JOIN gold.UM_Connection d ON d.ClientId = @ClientId AND d.TakeId = @TakeId AND d.LegacyAcctNo = a.ACCOUNTNUM
                                       AND d.ServiceType LIKE 'WAT%'
        LEFT JOIN xref.v_DepositType dt ON dt.ClientId = @ClientId AND dt.ServiceType = d.ServiceType
        WHERE a.TakeId = @TakeId AND a.REFDATE = ''
          AND TRY_CONVERT(numeric(19,5), a.RECEIVED) + TRY_CONVERT(numeric(19,5), a.UNBILLED) > 0;
        SET @rows = @@ROWCOUNT;
        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_LocationHistory @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : location history (UM00600H): past customers moved in and out of a location, so their
             balances and deposits have a customer|location pair in CSM.
   Source  : RECONSTRUCTED. The legacy staging scripts don't include this step; the go-live integrity
             report shows 568 history rows. Working rule (OQ-LOCHIST-1, confirm with reviewer), which
             reproduces the 568: one move-in history record per legacy account that has a beginning
             balance or deposit at a known location where it is not the current bill-to. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_LocationHistory', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_LocationHistory WHERE ClientId = @ClientId AND TakeId = @TakeId;
        INSERT gold.UM_LocationHistory (ClientId, TakeId, RecordKey, CustomerID, LocationID, Reason)
        SELECT @ClientId, @TakeId, p.LegacyAcctNo, p.CustomerID, p.LocationID, MIN(p.Reason)
        FROM (SELECT LegacyAcctNo, CustomerID, LocationID, 'beginning balance' AS Reason FROM gold.UM_BegBalance WHERE ClientId = @ClientId AND TakeId = @TakeId
              UNION ALL
              SELECT LegacyAcctNo, CustomerID, LocationID, 'deposit' FROM gold.UM_Deposit WHERE ClientId = @ClientId AND TakeId = @TakeId) p
        WHERE p.CustomerID IS NOT NULL AND p.LocationID IS NOT NULL AND p.LocationID <> '0'
          AND EXISTS (SELECT 1 FROM gold.UM_Location l WHERE l.ClientId = @ClientId AND l.TakeId = @TakeId AND l.LocationID = p.LocationID)
          AND NOT EXISTS (SELECT 1 FROM gold.UM_Location l WHERE l.ClientId = @ClientId AND l.TakeId = @TakeId
                          AND l.LocationID = p.LocationID AND l.CustomerID = p.CustomerID)
        GROUP BY p.LegacyAcctNo, p.CustomerID, p.LocationID;
        SET @rows = @@ROWCOUNT;
        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_HistMR @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose : historical meter reads (UM30300).
   Legacy  : sp_Load_UM_HistMR (reviewer 20260126 / 20260128 / 20260709).
   Logic   : reads of IDLE accounts are skipped; month-only read dates (yyyy-mm) get day 01; reading
             rounded to 1 decimal (OQ-HISTMR-READ-ROUNDING); consumption = Flow / 100; days since the
             account's previous (earlier) read date, default 1; previous reading by account and date.
   Note    : the legacy NumberOfDays/PreviousReading UPDATEs used correlated lookups; these are window
             functions with the same meaning (ties ordered by source row, so results are repeatable). */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @log bigint, @rows int;
    EXEC run.usp_LogStart @ClientId, @TakeId, 'gold.usp_Build_HistMR', @log OUTPUT;
    BEGIN TRY
        BEGIN TRAN;
        DELETE gold.UM_HistMR WHERE ClientId = @ClientId AND TakeId = @TakeId;
        INSERT gold.UM_HistMR (ClientId, TakeId, SourceRow, RecordKey, LegacyAcctNo, Legacy_Loc_ID, LocationID, CustomerID, EquipmentID,
               ReadingDate, ReadingType, NumberOfDays, Reading, PreviousReading, Consumption1, Consumption2, UMEQUMULT, openread)
        SELECT @ClientId, @TakeId, a.SourceRow, a.Account_ID + N'|' + a.Meter_ID + N'|' + a.Read_Time + N'|' + CAST(a.SourceRow AS nvarchar(10)),
               a.Account_ID, a.Account_ID, b.LocationID, b.CustomerID, a.Meter_ID,
               CASE WHEN LEN(a.Read_Time) = 7 THEN a.Read_Time + '-01' ELSE a.Read_Time END, '1', '',
               -- legacy parity: sp_Load_UM_HistMR rounds and divides through float; numeric(19,5) could change the last digit
               ISNULL(CAST(CAST(ROUND(TRY_CONVERT(float, a.[Read]), 1) AS decimal(18,1)) AS nvarchar(40)), a.[Read]), '',  -- lint-ignore: W107
               CAST(CAST(TRY_CONVERT(float, a.Flow) / 100.0 AS decimal(18,4)) AS varchar(50)),                          -- lint-ignore: W107
               CAST(CAST(TRY_CONVERT(float, a.Flow) / 100.0 AS decimal(18,4)) AS varchar(50)),                          -- lint-ignore: W107
               '100', '0'
        FROM slv.Reads a
        LEFT JOIN gold.UM_Customer b ON b.ClientId = @ClientId AND b.TakeId = @TakeId AND b.LegacyAcctNo = a.Account_ID
        WHERE a.TakeId = @TakeId AND a.Account_Full_Name NOT LIKE '%IDLE%';
        SET @rows = @@ROWCOUNT;

        WITH d AS (   -- distinct read dates per account, so "previous" means an earlier date, as in the legacy OUTER APPLY
            SELECT LegacyAcctNo, ReadingDate, PrevDate = LAG(ReadingDate) OVER (PARTITION BY LegacyAcctNo ORDER BY ReadingDate)
            FROM (SELECT DISTINCT LegacyAcctNo, ReadingDate FROM gold.UM_HistMR
                  WHERE ClientId = @ClientId AND TakeId = @TakeId AND ReadingDate <> '') u
        )
        UPDATE t SET NumberOfDays = CAST(ISNULL(DATEDIFF(DAY, TRY_CONVERT(date, d.PrevDate), TRY_CONVERT(date, t.ReadingDate)), 1) AS varchar(10))
        FROM gold.UM_HistMR t
        LEFT JOIN d ON d.LegacyAcctNo = t.LegacyAcctNo AND d.ReadingDate = t.ReadingDate
        WHERE t.ClientId = @ClientId AND t.TakeId = @TakeId;

        WITH p AS (
            SELECT RowId, Prev = LAG(Reading) OVER (PARTITION BY LegacyAcctNo ORDER BY TRY_CONVERT(date, ReadingDate), SourceRow)
            FROM gold.UM_HistMR WHERE ClientId = @ClientId AND TakeId = @TakeId
        )
        UPDATE t SET PreviousReading = ISNULL(p.Prev, '0')
        FROM gold.UM_HistMR t JOIN p ON p.RowId = t.RowId;
        COMMIT;
        EXEC run.usp_LogEnd @log, @rows;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @msg nvarchar(4000) = ERROR_MESSAGE();
        EXEC run.usp_LogEnd @log, NULL, 'Failed', @msg;
        THROW;
    END CATCH
END;
GO

CREATE OR ALTER PROCEDURE gold.usp_Build_All @ClientId varchar(20), @TakeId varchar(20)
AS
/* Purpose: rebuild every gold table for one take, in dependency order. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    EXEC gold.usp_Build_Customer        @ClientId, @TakeId;
    EXEC gold.usp_Build_Location        @ClientId, @TakeId;
    EXEC gold.usp_Build_Equipment       @ClientId, @TakeId;
    EXEC gold.usp_Build_Connection      @ClientId, @TakeId;
    EXEC gold.usp_Build_BegBalance      @ClientId, @TakeId;
    EXEC gold.usp_Build_Deposit         @ClientId, @TakeId;
    EXEC gold.usp_Build_LocationHistory @ClientId, @TakeId;
    EXEC gold.usp_Build_HistMR          @ClientId, @TakeId;
END;
GO
