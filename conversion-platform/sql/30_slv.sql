/* =====================================================================
   30_slv.sql: silver copy of a take inside the SQL database.
   Text exactly as received (blank = ''), one table per extract, lineage on every row
   (SourceRow = row number in the extract, after the header). Loaded by the pipeline from the
   lakehouse silver tables; only the columns the conversion SQL uses are copied.
   ===================================================================== */
SET NOCOUNT ON;
-- slv is a disposable copy reloaded every take: recreate a table whose columns changed
IF OBJECT_ID('slv.Customers') IS NOT NULL AND COL_LENGTH('slv.Customers', 'SA_NAME') IS NULL DROP TABLE slv.Customers;
IF OBJECT_ID('slv.Customers') IS NULL
CREATE TABLE slv.Customers (
    TakeId varchar(20) NOT NULL, SourceRow int NOT NULL,
    INCODEACCT nvarchar(20) NOT NULL, SERVICEADDRESS nvarchar(100) NOT NULL, FIRSTNAME nvarchar(100) NOT NULL,
    LASTNAME nvarchar(100) NOT NULL, SOCIAL nvarchar(20) NOT NULL, DOB nvarchar(20) NOT NULL,
    DRIVERSLICENSE nvarchar(50) NOT NULL, DLST nvarchar(40) NOT NULL, ADDRESS1 nvarchar(100) NOT NULL,
    ADDRESS2 nvarchar(100) NOT NULL, ADDRESSATTN nvarchar(100) NOT NULL, CITY nvarchar(60) NOT NULL,
    ST nvarchar(20) NOT NULL, ZIP nvarchar(20) NOT NULL, EMAIL nvarchar(100) NOT NULL,
    PHONENUMBER nvarchar(50) NOT NULL, CELLNUMBER nvarchar(50) NOT NULL, HOMENUMBER nvarchar(50) NOT NULL,
    CUSTOMERCLASS nvarchar(20) NOT NULL, STARTDATE nvarchar(20) NOT NULL, CUSTOMERSTATUS nvarchar(20) NOT NULL,
    SA_NUMBER nvarchar(30) NOT NULL, SA_PREDIR nvarchar(10) NOT NULL, SA_NAME nvarchar(100) NOT NULL,   -- parsed service address
    SA_SUFFIX nvarchar(10) NOT NULL, SA_POSTDIR nvarchar(10) NOT NULL, SA_UNIT nvarchar(60) NOT NULL,
    CONSTRAINT PK_slv_Customers PRIMARY KEY (TakeId, SourceRow)
);
IF OBJECT_ID('slv.Services') IS NULL
CREATE TABLE slv.Services (
    TakeId varchar(20) NOT NULL, SourceRow int NOT NULL,
    ACCOUNTNUM nvarchar(20) NOT NULL, STARTDATE nvarchar(20) NOT NULL,
    DESCRIPTION nvarchar(60) NOT NULL, STATUS nvarchar(20) NOT NULL, [TABLE] nvarchar(30) NOT NULL, METER nvarchar(30) NOT NULL,
    DESCRIPTION2 nvarchar(60) NOT NULL, STATUS2 nvarchar(20) NOT NULL, TABLE2 nvarchar(30) NOT NULL, METER2 nvarchar(30) NOT NULL,
    ACCT nvarchar(20) NOT NULL, STDATE nvarchar(20) NOT NULL,            -- helper columns the client built in Excel
    ACCT_FILL nvarchar(20) NOT NULL, STDATE_FILL nvarchar(20) NOT NULL,  -- the platform's own fill-down (used by gold)
    CONSTRAINT PK_slv_Services PRIMARY KEY (TakeId, SourceRow)
);
IF OBJECT_ID('slv.Balances') IS NULL
CREATE TABLE slv.Balances (
    TakeId varchar(20) NOT NULL, SourceRow int NOT NULL,
    ACCOUNTNUM nvarchar(20) NOT NULL, STATUS nvarchar(20) NOT NULL, BALANCE nvarchar(30) NOT NULL,
    SVC1 nvarchar(30) NOT NULL, BAL1 nvarchar(30) NOT NULL, SVC2 nvarchar(30) NOT NULL, BAL2 nvarchar(30) NOT NULL,
    SVC3 nvarchar(30) NOT NULL, BAL3 nvarchar(30) NOT NULL,
    ACCT nvarchar(20) NOT NULL, ACCT_FILL nvarchar(20) NOT NULL,
    CONSTRAINT PK_slv_Balances PRIMARY KEY (TakeId, SourceRow)
);
IF OBJECT_ID('slv.Deposits') IS NULL
CREATE TABLE slv.Deposits (
    TakeId varchar(20) NOT NULL, SourceRow int NOT NULL,
    ACCOUNTNUM nvarchar(20) NOT NULL, ID nvarchar(10) NOT NULL, RECEIPT nvarchar(30) NOT NULL,
    DEPOSITCODE nvarchar(40) NOT NULL, DEPDATE nvarchar(20) NOT NULL, RECEIVED nvarchar(30) NOT NULL,
    UNBILLED nvarchar(30) NOT NULL, INTERESTAPPLIED nvarchar(30) NOT NULL, TARGETDATE nvarchar(20) NOT NULL,
    REFDATE nvarchar(20) NOT NULL,
    CONSTRAINT PK_slv_Deposits PRIMARY KEY (TakeId, SourceRow)
);
IF OBJECT_ID('slv.Reads') IS NULL
CREATE TABLE slv.Reads (
    TakeId varchar(20) NOT NULL, SourceRow int NOT NULL,
    Account_ID nvarchar(20) NOT NULL, Meter_ID nvarchar(30) NOT NULL, Meter_SN nvarchar(30) NOT NULL,
    Endpoint_SN nvarchar(30) NOT NULL, Read_Time nvarchar(30) NOT NULL, [Read] nvarchar(30) NOT NULL,
    Flow nvarchar(30) NOT NULL, Account_Full_Name nvarchar(100) NOT NULL, Service_Point_Class_Code nvarchar(10) NOT NULL,
    Meter_Manufacturer nvarchar(40) NOT NULL, Meter_Model nvarchar(40) NOT NULL, Meter_Size nvarchar(20) NOT NULL,
    Meter_Size_Desc nvarchar(20) NOT NULL, Dials nvarchar(10) NOT NULL,
    CONSTRAINT PK_slv_Reads PRIMARY KEY (TakeId, SourceRow)
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_slv_Customers_Acct')
    CREATE INDEX IX_slv_Customers_Acct ON slv.Customers (TakeId, INCODEACCT) INCLUDE (CUSTOMERSTATUS, CUSTOMERCLASS);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_slv_Services_Acct')
    CREATE INDEX IX_slv_Services_Acct ON slv.Services (TakeId, ACCT_FILL);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_slv_Services_AcctNum')
    CREATE INDEX IX_slv_Services_AcctNum ON slv.Services (TakeId, ACCOUNTNUM) INCLUDE (STARTDATE);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_slv_Reads_Meter')
    CREATE INDEX IX_slv_Reads_Meter ON slv.Reads (TakeId, Meter_ID) INCLUDE (Service_Point_Class_Code, Meter_Size_Desc);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_slv_Reads_Acct')
    CREATE INDEX IX_slv_Reads_Acct ON slv.Reads (TakeId, Account_ID);
GO
