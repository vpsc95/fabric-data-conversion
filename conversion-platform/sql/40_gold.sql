/* =====================================================================
   40_gold.sql: UM staging tables (gold). One table per CSM module, one row per record the loader
   will pass to the CSM business-logic procedure.

   Deliberate choices
   - Column names match reviewer's COGS_STAGING tables, so the familiar SmartList / SELECT habits still work.
   - isvalid (1 = valid, 2 = warning, 0 = error) and message keep the legacy pattern; every issue is
     ALSO written once to run.Issue with its rule ID (that's what triage and Power BI read).
   - Text columns are wider than the CSM fields so over-length values survive long enough to be
     flagged; the loader applies LEFT(value, length) explicitly.
   - NULLs are kept where the legacy staging produced them (LEFT JOIN misses), because the legacy
     rules depend on NULL behaviour (for example "Customer Code is NULL"). The loader converts to
     GP conventions ('' / 0 / 1900-01-01) at the CSM boundary.
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('gold.UM_Customer') IS NULL
CREATE TABLE gold.UM_Customer (                      -- UMRM0101 customer (+ UMRM0111 address fields)
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_Customer PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, SourceRow int NOT NULL, RecordKey nvarchar(200) NOT NULL,
    LegacyAcctNo nvarchar(20) NOT NULL, CustomerID varchar(15) NOT NULL, CustomerIDX int NOT NULL, Individual tinyint NOT NULL,
    FirstName nvarchar(100) NOT NULL, MiddleName nvarchar(30) NOT NULL CONSTRAINT DF_gc_Middle DEFAULT N'',
    LastName nvarchar(100) NOT NULL, SIN nvarchar(20) NOT NULL, DateOfBirth date NULL, PlaceOfWork nvarchar(100) NOT NULL,
    ADDRESS1 nvarchar(100) NOT NULL, ADDRESS2 nvarchar(100) NOT NULL, ADDRESS3 nvarchar(100) NOT NULL CONSTRAINT DF_gc_A3 DEFAULT N'',
    City nvarchar(60) NOT NULL, [STATE] nvarchar(40) NOT NULL, Country varchar(10) NOT NULL, Zip nvarchar(20) NOT NULL,
    ADRSCODE varchar(15) NOT NULL, CustomerClassID varchar(15) NOT NULL, PaymentTermID varchar(21) NOT NULL,
    Phone1 nvarchar(60) NOT NULL, Phone2 nvarchar(60) NOT NULL, Phone3 nvarchar(60) NOT NULL, Fax nvarchar(30) NOT NULL CONSTRAINT DF_gc_Fax DEFAULT N'',
    Email nvarchar(100) NOT NULL, ContactPerson nvarchar(100) NOT NULL, AlternateID nvarchar(100) NOT NULL,
    LocationID varchar(15) NOT NULL, New_Existing nvarchar(20) NOT NULL, ID int NOT NULL, SecCustIDX int NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_gc_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_gc_msg DEFAULT N''
);
IF OBJECT_ID('gold.UM_Location') IS NULL
CREATE TABLE gold.UM_Location (                      -- UM00600 location
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_Location PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, SourceRow int NOT NULL, RecordKey nvarchar(200) NOT NULL,
    Legacy_Loc_ID nvarchar(20) NOT NULL, LocationID varchar(15) NOT NULL, CustomerID varchar(15) NOT NULL, Category varchar(5) NOT NULL,
    SStreetNumber nvarchar(30) NOT NULL CONSTRAINT DF_gl_SNo DEFAULT N'', SStreetName nvarchar(100) NOT NULL CONSTRAINT DF_gl_SName DEFAULT N'',
    SStreetDirPF nvarchar(20) NOT NULL CONSTRAINT DF_gl_SDir DEFAULT N'', SStreetType nvarchar(20) NOT NULL CONSTRAINT DF_gl_SType DEFAULT N'',
    SAptNo nvarchar(30) NOT NULL CONSTRAINT DF_gl_SApt DEFAULT N'',
    SCity nvarchar(60) NULL, SState varchar(10) NOT NULL, SCountry varchar(10) NOT NULL, SZip nvarchar(20) NOT NULL,
    AdrCategory varchar(5) NOT NULL, ADRSCODE varchar(15) NOT NULL, LocationClass varchar(20) NOT NULL, ThirdPartyDesc nvarchar(30) NOT NULL,
    NoResUnits varchar(10) NOT NULL, ZoneID varchar(15) NOT NULL, RouteID varchar(15) NOT NULL, SAddress1 nvarchar(200) NOT NULL,
    UUDF1 nvarchar(150) NOT NULL CONSTRAINT DF_gl_U1 DEFAULT N'', UUDF2 nvarchar(150) NOT NULL, ID int NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_gl_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_gl_msg DEFAULT N''
);
IF OBJECT_ID('gold.UM_Equipment') IS NULL
CREATE TABLE gold.UM_Equipment (                     -- UM00400 equipment (meters)
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_Equipment PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, RecordKey nvarchar(200) NOT NULL,
    LegacyAcctNo nvarchar(20) NOT NULL, EquipmentID nvarchar(30) NOT NULL, SerialNo nvarchar(40) NOT NULL, EquClassID varchar(15) NULL,
    ServiceCategory varchar(5) NOT NULL, ConsEst varchar(5) NOT NULL, Installed tinyint NOT NULL, InstallDate nvarchar(20) NOT NULL,
    EquipmentStatus smallint NOT NULL, InstallableStatus varchar(5) NOT NULL, EqMult smallint NOT NULL, RemovalDate varchar(10) NOT NULL,
    Manufacturer nvarchar(40) NOT NULL, Diameter nvarchar(20) NOT NULL, TOTCONSUMP nvarchar(10) NOT NULL,
    EqDescription nvarchar(100) NOT NULL CONSTRAINT DF_ge_Desc DEFAULT N'', PhysicalLocation nvarchar(100) NOT NULL CONSTRAINT DF_ge_Phys DEFAULT N'',
    RemoteID nvarchar(30) NOT NULL, RInstallationDate nvarchar(20) NOT NULL, RemoteType varchar(10) NOT NULL, DifferenceReadingDials int NULL,
    NetMeterType varchar(5) NOT NULL, DifferenceReadingsDialDigits varchar(10) NOT NULL, KWDialDigits varchar(10) NOT NULL,
    DifferenceDialDecimals nvarchar(10) NOT NULL, KWDialDecimals varchar(10) NOT NULL, DifferenceReadingDialMultiplier varchar(10) NOT NULL,
    KWDialMultiplier varchar(10) NOT NULL, PFDialMultiplier varchar(10) NOT NULL, MODEL nvarchar(40) NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_ge_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_ge_msg DEFAULT N''
);
IF OBJECT_ID('gold.UM_Connection') IS NULL
CREATE TABLE gold.UM_Connection (                    -- UM00300 connection (service at a location)
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_Connection PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, SourceRow int NOT NULL, ServiceSlot tinyint NOT NULL, RecordKey nvarchar(200) NOT NULL,
    LegacyAcctNo nvarchar(20) NOT NULL, Legacy_Loc_ID nvarchar(20) NOT NULL, LocationID varchar(15) NULL, Category varchar(5) NOT NULL,
    ServiceType nvarchar(30) NOT NULL, EquipmentID nvarchar(30) NULL, Alternate varchar(5) NOT NULL, RouteID varchar(15) NOT NULL,
    ConnStatus varchar(5) NOT NULL, ConnDate nvarchar(20) NOT NULL, DisconnDate varchar(10) NOT NULL, SEQNO varchar(10) NOT NULL,
    TariffID varchar(20) NOT NULL, CTAR11 varchar(20) NOT NULL, Legacy_Service nvarchar(60) NOT NULL, Legacy_Service_Class nvarchar(10) NULL,
    flat_rate nvarchar(30) NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_gn_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_gn_msg DEFAULT N''
);
IF OBJECT_ID('gold.UM_BegBalance') IS NULL
CREATE TABLE gold.UM_BegBalance (                    -- UM20400 beginning balance
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_BegBalance PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, SourceRow int NOT NULL, RecordKey nvarchar(200) NOT NULL,
    LegacyAcctNo nvarchar(20) NOT NULL, Legacy_Loc_ID nvarchar(20) NOT NULL, CustomerID varchar(15) NULL, LocationID varchar(15) NULL,
    BBAmount nvarchar(30) NOT NULL, BBMisType varchar(30) NOT NULL, BBServiceType varchar(30) NOT NULL, BBTransDesc nvarchar(60) NOT NULL,
    BBDate datetime NOT NULL, BBDDate datetime NOT NULL, BBCreditAccount varchar(10) NOT NULL, BBDebitAccount varchar(10) NOT NULL,
    BBMisTaxSchedule varchar(30) NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_gb_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_gb_msg DEFAULT N''
);
IF OBJECT_ID('gold.UM_Deposit') IS NULL
CREATE TABLE gold.UM_Deposit (                       -- UM01900 deposit
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_Deposit PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, SourceRow int NOT NULL, RecordKey nvarchar(200) NOT NULL,
    LegacyAcctNo nvarchar(20) NOT NULL, Legacy_Loc_ID nvarchar(20) NOT NULL, CustomerID varchar(15) NULL, LocationID varchar(15) NULL,
    DepositAmount numeric(19,5) NOT NULL, DepositDate nvarchar(20) NOT NULL, DepositID varchar(30) NOT NULL, Category varchar(5) NOT NULL,
    DepositPaymentDate nvarchar(20) NOT NULL, DepositAmtPaid nvarchar(30) NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_gd_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_gd_msg DEFAULT N''
);
IF OBJECT_ID('gold.UM_HistMR') IS NULL
CREATE TABLE gold.UM_HistMR (                        -- UM30300 historical meter read
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_HistMR PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, SourceRow int NOT NULL, RecordKey nvarchar(200) NOT NULL,
    LegacyAcctNo nvarchar(20) NOT NULL, Legacy_Loc_ID nvarchar(20) NOT NULL, LocationID varchar(15) NULL, CustomerID varchar(15) NULL,
    EquipmentID nvarchar(30) NOT NULL, ReadingDate nvarchar(30) NOT NULL, ReadingType varchar(5) NOT NULL, NumberOfDays varchar(10) NOT NULL,
    Reading nvarchar(40) NOT NULL, PreviousReading nvarchar(40) NOT NULL, Consumption1 varchar(50) NULL, Consumption2 varchar(50) NULL,
    UMEQUMULT nvarchar(30) NOT NULL, openread varchar(5) NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_gh_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_gh_msg DEFAULT N''
);
IF OBJECT_ID('gold.UM_LocationHistory') IS NULL
CREATE TABLE gold.UM_LocationHistory (               -- UM00600H location history (past customers moved in and out)
    RowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_gold_UM_LocationHistory PRIMARY KEY,
    ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, RecordKey nvarchar(200) NOT NULL,
    CustomerID varchar(15) NOT NULL, LocationID varchar(15) NOT NULL, Reason varchar(60) NOT NULL,
    isvalid tinyint NOT NULL CONSTRAINT DF_gx_isvalid DEFAULT 1, message nvarchar(2000) NOT NULL CONSTRAINT DF_gx_msg DEFAULT N''
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_gold_Customer_Acct')
    CREATE INDEX IX_gold_Customer_Acct ON gold.UM_Customer (ClientId, TakeId, LegacyAcctNo) INCLUDE (CustomerID, LocationID, Individual);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_gold_Location_Legacy')
    CREATE INDEX IX_gold_Location_Legacy ON gold.UM_Location (ClientId, TakeId, Legacy_Loc_ID) INCLUDE (LocationID, CustomerID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_gold_Equipment_Id')
    CREATE INDEX IX_gold_Equipment_Id ON gold.UM_Equipment (ClientId, TakeId, EquipmentID) INCLUDE (isvalid);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_gold_Connection_Loc')
    CREATE INDEX IX_gold_Connection_Loc ON gold.UM_Connection (ClientId, TakeId, LocationID) INCLUDE (ServiceType, EquipmentID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_gold_HistMR_Equip')
    CREATE INDEX IX_gold_HistMR_Equip ON gold.UM_HistMR (ClientId, TakeId, EquipmentID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_gold_HistMR_CustLoc')
    CREATE INDEX IX_gold_HistMR_CustLoc ON gold.UM_HistMR (ClientId, TakeId, CustomerID, LocationID);
GO

CREATE OR ALTER FUNCTION gold.fn_CleanPhone (@v nvarchar(100))
RETURNS TABLE
AS
/* Purpose: legacy phone cleanup from sp_Load_UM_Customer: keep the text before the first space or
   comma (whichever comes first), then remove - ( ) and spaces. Inline TVF, so it's set-based.
   Example: '(nnn) nnn-nnnn cell' -> '(nnn)' -> 'nnn'   (as the legacy script did) */
RETURN SELECT Phone = REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(
    CASE WHEN CHARINDEX(' ', @v) > 0 AND (CHARINDEX(',', @v) = 0 OR CHARINDEX(' ', @v) < CHARINDEX(',', @v))
              THEN LEFT(@v, CHARINDEX(' ', @v) - 1)
         WHEN CHARINDEX(',', @v) > 0 THEN LEFT(@v, CHARINDEX(',', @v) - 1)
         ELSE @v END)), '-', ''), '(', ''), ')', ''), ' ', '');
GO
