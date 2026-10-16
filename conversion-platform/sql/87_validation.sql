/* =====================================================================
   87_validation.sql: the client's validation sample for a take (process P15).
   Each take the client checks converted accounts in TEST / TRAIN. Instead of picking them by hand, the
   platform selects them: the "tall poppies" (largest balances, most services, compound meters, customers
   with several accounts, largest deposits, customers kept only in location history), accounts that did not
   fully convert (so the client sees why), and a random set. The pick inside each group is ordered by a hash
   of take + account, so it is reproducible for a take and rotates from one take to the next.
   recon.v_ValidationSideBySide puts the legacy value (as received) next to the converted value, compared
   the way the field converts (text, phone digits, amount, date, count).
   Reporting code for the platform database (LocalDB / Fabric SQL database), not for client servers.
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('run.ValidationSample') IS NULL
CREATE TABLE run.ValidationSample (
    ClientId     varchar(20)   NOT NULL,
    TakeId       varchar(20)   NOT NULL,
    LegacyAcctNo nvarchar(30)  NOT NULL,
    Stratum      varchar(40)   NOT NULL,
    StratumOrder tinyint       NOT NULL,
    Reason       nvarchar(200) NOT NULL,
    CreatedAt    datetime2(3)  NOT NULL CONSTRAINT DF_ValidationSample_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ValidationSample PRIMARY KEY (ClientId, TakeId, LegacyAcctNo)
);
GO
CREATE OR ALTER PROCEDURE recon.usp_BuildValidationSample
    @ClientId varchar(20), @TakeId varchar(20), @PerStratum int = 5, @Pool int = 25, @Random int = 15
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    CREATE TABLE #cand (Stratum varchar(40) NOT NULL, StratumOrder tinyint NOT NULL, LegacyAcctNo nvarchar(30) NOT NULL,
                        Metric decimal(19, 2) NULL, Reason nvarchar(200) NOT NULL);
    -- 1 largest beginning balances
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT TOP (@Pool) 'Largest balance', 1, LegacyAcctNo, SUM(TRY_CONVERT(decimal(19, 2), BBAmount)), N'among the largest beginning balances'
    FROM gold.UM_BegBalance WHERE ClientId = @ClientId AND TakeId = @TakeId
    GROUP BY LegacyAcctNo ORDER BY SUM(TRY_CONVERT(decimal(19, 2), BBAmount)) DESC, LegacyAcctNo;
    -- 2 most services
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT TOP (@Pool) 'Most services', 2, LegacyAcctNo, COUNT(*), N'among the accounts with the most services'
    FROM gold.UM_Connection WHERE ClientId = @ClientId AND TakeId = @TakeId
    GROUP BY LegacyAcctNo ORDER BY COUNT(*) DESC, LegacyAcctNo;
    -- 3 compound meters (a low-flow register gives a second consumption)
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT 'Compound meter', 3, LegacyAcctNo, NULL, N'has a compound meter (low-flow register)'
    FROM (SELECT DISTINCT LegacyAcctNo FROM gold.UM_HistMR
          WHERE ClientId = @ClientId AND TakeId = @TakeId AND TRY_CONVERT(decimal(19, 4), Consumption2) <> 0) AS x;
    -- 4 one customer with several legacy accounts (the accounts must all land on the same CSM customer)
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT 'Several accounts', 4, c.LegacyAcctNo, m.Accounts, N'customer has several legacy accounts'
    FROM gold.UM_Customer AS c
    JOIN (SELECT CustomerID, COUNT(*) AS Accounts FROM gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId
          GROUP BY CustomerID HAVING COUNT(*) > 1) AS m ON m.CustomerID = c.CustomerID
    WHERE c.ClientId = @ClientId AND c.TakeId = @TakeId;
    -- 5 largest deposits
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT TOP (@Pool) 'Largest deposit', 5, LegacyAcctNo, SUM(TRY_CONVERT(decimal(19, 2), DepositAmount)), N'among the largest deposits'
    FROM gold.UM_Deposit WHERE ClientId = @ClientId AND TakeId = @TakeId
    GROUP BY LegacyAcctNo ORDER BY SUM(TRY_CONVERT(decimal(19, 2), DepositAmount)) DESC, LegacyAcctNo;
    -- 6 customers kept only in location history (balance or deposit, not active)
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT DISTINCT 'History only', 6, c.LegacyAcctNo, NULL, N'kept in location history (balance or deposit, not active)'
    FROM gold.UM_LocationHistory AS h
    JOIN gold.UM_Customer AS c ON c.ClientId = h.ClientId AND c.TakeId = h.TakeId AND c.CustomerID = h.CustomerID
    WHERE h.ClientId = @ClientId AND h.TakeId = @TakeId;
    -- 7 did not fully convert: at least one record failed (the client sees why, and fixes it in the source)
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT 'Did not fully convert', 7, LegacyAcctNo, COUNT(*), N'has records that failed validation'
    FROM (SELECT LegacyAcctNo FROM gold.UM_Connection WHERE ClientId = @ClientId AND TakeId = @TakeId AND isvalid = 0
          UNION ALL SELECT LegacyAcctNo FROM gold.UM_BegBalance WHERE ClientId = @ClientId AND TakeId = @TakeId AND isvalid = 0
          UNION ALL SELECT LegacyAcctNo FROM gold.UM_Deposit WHERE ClientId = @ClientId AND TakeId = @TakeId AND isvalid = 0) AS f
    GROUP BY LegacyAcctNo;
    -- 8 random
    INSERT #cand (Stratum, StratumOrder, LegacyAcctNo, Metric, Reason)
    SELECT 'Random', 8, LegacyAcctNo, NULL, N'random pick for this take'
    FROM gold.UM_Customer WHERE ClientId = @ClientId AND TakeId = @TakeId;

    BEGIN TRY
        BEGIN TRANSACTION;
        DELETE run.ValidationSample WHERE ClientId = @ClientId AND TakeId = @TakeId;
        DECLARE @s tinyint = 1, @n int;
        WHILE @s <= 8
        BEGIN
            SET @n = CASE WHEN @s = 8 THEN @Random ELSE @PerStratum END;
            INSERT run.ValidationSample (ClientId, TakeId, LegacyAcctNo, Stratum, StratumOrder, Reason)
            SELECT TOP (@n) @ClientId, @TakeId, c.LegacyAcctNo, c.Stratum, c.StratumOrder, c.Reason
            FROM #cand AS c
            WHERE c.StratumOrder = @s AND c.LegacyAcctNo <> N''
              AND NOT EXISTS (SELECT 1 FROM run.ValidationSample AS v
                              WHERE v.ClientId = @ClientId AND v.TakeId = @TakeId AND v.LegacyAcctNo = c.LegacyAcctNo)
            ORDER BY HASHBYTES('SHA2_256', CONCAT(@TakeId, N'|', c.LegacyAcctNo));
            SET @s += 1;
        END;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
    DROP TABLE #cand;
END;
GO
CREATE OR ALTER VIEW recon.v_ValidationSideBySide AS
WITH c AS (                                              -- one gold customer row per legacy account
    SELECT g.ClientId, g.TakeId, g.LegacyAcctNo, g.SourceRow, g.FirstName, g.LastName, g.ADDRESS1, g.City, g.STATE, g.Zip, g.Phone1,
           g.Email, g.CustomerClassID
    FROM gold.UM_Customer AS g
), svc AS (
    SELECT ClientId, TakeId, LegacyAcctNo, COUNT(*) AS Received, SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END) AS Converted
    FROM gold.UM_Connection GROUP BY ClientId, TakeId, LegacyAcctNo
), bal AS (
    SELECT b.ClientId, b.TakeId, b.LegacyAcctNo,
           SUM(CASE WHEN b.isvalid <> 0 THEN TRY_CONVERT(decimal(19, 2), b.BBAmount) ELSE 0 END) AS Converted
    FROM gold.UM_BegBalance AS b GROUP BY b.ClientId, b.TakeId, b.LegacyAcctNo
), balsrc AS (                                             -- the report's account balance, once per source line
    SELECT x.ClientId, x.TakeId, x.LegacyAcctNo,
           SUM(TRY_CONVERT(decimal(19, 2), REPLACE(REPLACE(s.BALANCE, N'$', N''), N',', N''))) AS Legacy
    FROM (SELECT DISTINCT ClientId, TakeId, LegacyAcctNo, SourceRow FROM gold.UM_BegBalance) AS x
    JOIN slv.Balances AS s ON s.TakeId = x.TakeId AND s.SourceRow = x.SourceRow
    GROUP BY x.ClientId, x.TakeId, x.LegacyAcctNo
), dep AS (
    SELECT d.ClientId, d.TakeId, d.LegacyAcctNo,
           SUM(CASE WHEN d.isvalid <> 0 THEN TRY_CONVERT(decimal(19, 2), d.DepositAmount) ELSE 0 END) AS Converted
    FROM gold.UM_Deposit AS d GROUP BY d.ClientId, d.TakeId, d.LegacyAcctNo
), depsrc AS (                                             -- received + unbilled, as listed in the deposit report
    SELECT x.ClientId, x.TakeId, x.LegacyAcctNo,
           SUM(ISNULL(TRY_CONVERT(decimal(19, 2), REPLACE(REPLACE(s.RECEIVED, N'$', N''), N',', N'')), 0)
             + ISNULL(TRY_CONVERT(decimal(19, 2), REPLACE(REPLACE(s.UNBILLED, N'$', N''), N',', N'')), 0)) AS Legacy
    FROM (SELECT DISTINCT ClientId, TakeId, LegacyAcctNo, SourceRow FROM gold.UM_Deposit) AS x
    JOIN slv.Deposits AS s ON s.TakeId = x.TakeId AND s.SourceRow = x.SourceRow
    GROUP BY x.ClientId, x.TakeId, x.LegacyAcctNo
), rd AS (                                                 -- the AMI export carries the read month (yyyy-mm)
    SELECT m.ClientId, m.TakeId, m.LegacyAcctNo,
           MAX(LEFT(r.Read_Time, 7)) AS Legacy,
           MAX(CASE WHEN m.isvalid <> 0 THEN CONVERT(char(7), TRY_CONVERT(date, m.ReadingDate), 126) END) AS Converted
    FROM gold.UM_HistMR AS m
    JOIN slv.Reads AS r ON r.TakeId = m.TakeId AND r.SourceRow = m.SourceRow
    GROUP BY m.ClientId, m.TakeId, m.LegacyAcctNo
)
SELECT v.ClientId, v.TakeId, v.LegacyAcctNo, v.Stratum, v.StratumOrder, v.Reason, f.FieldOrder, f.Field, f.CompareAs,
       f.LegacyValue, f.ConvertedValue,
       CASE f.CompareAs
            WHEN 'mapped' THEN NULL                         -- translated through a crosswalk: shown, not compared
            WHEN 'amount' THEN CASE WHEN ISNULL(TRY_CONVERT(decimal(19, 2), f.LegacyValue), 0) = ISNULL(TRY_CONVERT(decimal(19, 2), f.ConvertedValue), 0)
                                    THEN 1 ELSE 0 END
            ELSE CASE WHEN UPPER(LTRIM(RTRIM(ISNULL(f.LegacyValue, N'')))) = UPPER(LTRIM(RTRIM(ISNULL(f.ConvertedValue, N'')))) THEN 1 ELSE 0 END
       END AS Matches
FROM run.ValidationSample AS v
LEFT JOIN c ON c.ClientId = v.ClientId AND c.TakeId = v.TakeId AND c.LegacyAcctNo = v.LegacyAcctNo   -- may be missing from the customer extract
LEFT JOIN slv.Customers AS lc ON lc.TakeId = c.TakeId AND lc.SourceRow = c.SourceRow
LEFT JOIN svc ON svc.ClientId = v.ClientId AND svc.TakeId = v.TakeId AND svc.LegacyAcctNo = v.LegacyAcctNo
LEFT JOIN bal ON bal.ClientId = v.ClientId AND bal.TakeId = v.TakeId AND bal.LegacyAcctNo = v.LegacyAcctNo
LEFT JOIN balsrc ON balsrc.ClientId = v.ClientId AND balsrc.TakeId = v.TakeId AND balsrc.LegacyAcctNo = v.LegacyAcctNo
LEFT JOIN dep ON dep.ClientId = v.ClientId AND dep.TakeId = v.TakeId AND dep.LegacyAcctNo = v.LegacyAcctNo
LEFT JOIN depsrc ON depsrc.ClientId = v.ClientId AND depsrc.TakeId = v.TakeId AND depsrc.LegacyAcctNo = v.LegacyAcctNo
LEFT JOIN rd ON rd.ClientId = v.ClientId AND rd.TakeId = v.TakeId AND rd.LegacyAcctNo = v.LegacyAcctNo
CROSS APPLY (VALUES
    (1,  N'First name',      'text',   CAST(lc.FIRSTNAME AS nvarchar(200)),                 CAST(c.FirstName AS nvarchar(200))),
    (2,  N'Last name',       'text',   CAST(lc.LASTNAME AS nvarchar(200)),                  CAST(c.LastName AS nvarchar(200))),
    (3,  N'Mailing address', 'text',   CAST(lc.ADDRESS1 AS nvarchar(200)),                  CAST(c.ADDRESS1 AS nvarchar(200))),
    (4,  N'City',            'text',   CAST(lc.CITY AS nvarchar(200)),                      CAST(c.City AS nvarchar(200))),
    (5,  N'State',           'text',   CAST(lc.ST AS nvarchar(200)),                        CAST(c.STATE AS nvarchar(200))),
    (6,  N'ZIP',             'text',   CAST(lc.ZIP AS nvarchar(200)),                       CAST(c.Zip AS nvarchar(200))),
    (7,  N'Phone (digits)',  'text',   CAST(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(lc.PHONENUMBER, N'(', N''), N')', N''), N'-', N''), N' ', N''), N'.', N'') AS nvarchar(200)),
                                       CAST(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.Phone1, N'(', N''), N')', N''), N'-', N''), N' ', N''), N'.', N'') AS nvarchar(200))),
    (8,  N'Email',           'text',   CAST(lc.EMAIL AS nvarchar(200)),                     CAST(c.Email AS nvarchar(200))),
    (9,  N'Customer class',  'mapped', CAST(lc.CUSTOMERCLASS AS nvarchar(200)),             CAST(c.CustomerClassID AS nvarchar(200))),
    (10, N'Services',        'amount', CAST(svc.Received AS nvarchar(200)),                 CAST(svc.Converted AS nvarchar(200))),
    (11, N'Balance',         'amount', CAST(balsrc.Legacy AS nvarchar(200)),                CAST(bal.Converted AS nvarchar(200))),
    (12, N'Deposit',         'amount', CAST(depsrc.Legacy AS nvarchar(200)),                CAST(dep.Converted AS nvarchar(200))),
    (13, N'Last read month', 'text',   CAST(rd.Legacy AS nvarchar(200)),                    CAST(rd.Converted AS nvarchar(200)))
) AS f (FieldOrder, Field, CompareAs, LegacyValue, ConvertedValue);
GO
