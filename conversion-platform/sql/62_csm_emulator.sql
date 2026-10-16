/* =====================================================================
   62_csm_emulator.sql: shadow-mode CSM emulator procedures and master rows.
   Procedure signatures come from docs/legacy-analysis/csm-procedures.json.
   ===================================================================== */
SET NOCOUNT ON;
IF SCHEMA_ID('conv') IS NULL EXEC('CREATE SCHEMA conv');
GO

IF OBJECT_ID('conv.Customer') IS NULL
CREATE TABLE conv.Customer (ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, CustomerID char(15) NOT NULL, FirstName char(30) NOT NULL, LastName char(30) NOT NULL, CustomerClassID char(15) NOT NULL, Individual tinyint NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_Customer_CreatedAt DEFAULT SYSUTCDATETIME(), CONSTRAINT PK_conv_Customer PRIMARY KEY (ClientId, TakeId, CustomerID));
GO

IF OBJECT_ID('conv.CustomerAddress') IS NULL
CREATE TABLE conv.CustomerAddress (ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, CustomerID char(15) NOT NULL, ADRSCODE char(15) NOT NULL, ADDRESS1 char(31) NOT NULL, CityName char(31) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_CustomerAddress_CreatedAt DEFAULT SYSUTCDATETIME(), CONSTRAINT PK_conv_CustomerAddress PRIMARY KEY (ClientId, TakeId, CustomerID, ADRSCODE));
GO

IF OBJECT_ID('conv.Location') IS NULL
CREATE TABLE conv.Location (ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, LocationID char(15) NOT NULL, BillToCust char(15) NOT NULL, LocationClass char(15) NOT NULL, RouteID char(15) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_Location_CreatedAt DEFAULT SYSUTCDATETIME(), CONSTRAINT PK_conv_Location PRIMARY KEY (ClientId, TakeId, LocationID));
GO

IF OBJECT_ID('conv.LocationHistory') IS NULL
CREATE TABLE conv.LocationHistory (LocationHistoryId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_conv_LocationHistory PRIMARY KEY, ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, LocationID char(15) NOT NULL, CustomerID char(15) NOT NULL, RequestID char(15) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_LocationHistory_CreatedAt DEFAULT SYSUTCDATETIME());
GO

IF OBJECT_ID('conv.Equipment') IS NULL
CREATE TABLE conv.Equipment (ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, EquipmentID char(15) NOT NULL, EquipmentClass char(15) NOT NULL, ServiceCategory smallint NOT NULL, SerialNumber char(31) NOT NULL, RemoteID char(20) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_Equipment_CreatedAt DEFAULT SYSUTCDATETIME(), CONSTRAINT PK_conv_Equipment PRIMARY KEY (ClientId, TakeId, EquipmentID));
GO

IF OBJECT_ID('conv.Connection') IS NULL
CREATE TABLE conv.Connection (ConnectionId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_conv_Connection PRIMARY KEY, ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, LocationID char(15) NOT NULL, ServiceType char(15) NOT NULL, EquipmentID char(15) NOT NULL, ConnectStatus smallint NOT NULL, RouteID char(15) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_Connection_CreatedAt DEFAULT SYSUTCDATETIME());
GO

IF OBJECT_ID('conv.BegBalance') IS NULL
CREATE TABLE conv.BegBalance (BegBalanceId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_conv_BegBalance PRIMARY KEY, ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, CustomerID char(15) NOT NULL, LocationID char(15) NOT NULL, Amount numeric(19,5) NOT NULL, MiscChargeType char(15) NOT NULL, ServiceType char(15) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_BegBalance_CreatedAt DEFAULT SYSUTCDATETIME());
GO

IF OBJECT_ID('conv.Deposit') IS NULL
CREATE TABLE conv.Deposit (DepositRowId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_conv_Deposit PRIMARY KEY, ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, CustomerID char(15) NOT NULL, LocationID char(15) NOT NULL, DepositID char(15) NOT NULL, DepositAmount numeric(19,5) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_Deposit_CreatedAt DEFAULT SYSUTCDATETIME());
GO

IF OBJECT_ID('conv.HistMR') IS NULL
CREATE TABLE conv.HistMR (HistMRId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_conv_HistMR PRIMARY KEY, ClientId varchar(20) NOT NULL, TakeId varchar(20) NOT NULL, LocationID char(15) NOT NULL, CustomerID char(15) NOT NULL, EquipmentID char(15) NOT NULL, ReadingDate datetime NOT NULL, ReadingType smallint NOT NULL, Reading numeric(19,5) NOT NULL, Consumption1 numeric(19,5) NOT NULL, CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_conv_HistMR_CreatedAt DEFAULT SYSUTCDATETIME());
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_conv_LocationHistory_Take' AND object_id = OBJECT_ID('conv.LocationHistory'))
CREATE INDEX IX_conv_LocationHistory_Take ON conv.LocationHistory (ClientId, TakeId, LocationID, CustomerID);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_conv_Connection_Take' AND object_id = OBJECT_ID('conv.Connection'))
CREATE UNIQUE INDEX UX_conv_Connection_Take ON conv.Connection (ClientId, TakeId, LocationID, ServiceType, EquipmentID);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_conv_BegBalance_Take' AND object_id = OBJECT_ID('conv.BegBalance'))
CREATE INDEX IX_conv_BegBalance_Take ON conv.BegBalance (ClientId, TakeId, MiscChargeType);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_conv_Deposit_Take' AND object_id = OBJECT_ID('conv.Deposit'))
CREATE INDEX IX_conv_Deposit_Take ON conv.Deposit (ClientId, TakeId, DepositID);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_conv_HistMR_Take' AND object_id = OBJECT_ID('conv.HistMR'))
CREATE INDEX IX_conv_HistMR_Take ON conv.HistMR (ClientId, TakeId, EquipmentID);
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateCustomer
    @CustomerID char(15),
    @umNameTitle smallint = 0,
    @umFirstName char(30) = '',
    @umMiddleName char(15) = '',
    @umLastName char(30) = '',
    @umNameSuffix char(4) = '',
    @umDateOfBirth datetime = '',
    @umPlaceOfWork char(41) = '',
    @umBusinessAs char(30) = '',
    @umSIN char(15) = '',
    @umCustClassID char(15) = '',
    @umAlternateID char(15) = '',
    @umInternetPassword char(15) = '',
    @umDepositReq tinyint = 0,
    @umPenaltyCharged tinyint = 0,
    @umRCollectionProc tinyint = 0,
    @umBudgetBE tinyint = NULL,
    @umPreauthPP tinyint = 0,
    @CUSTDISC smallint = 0,
    @umDelinquencyCode smallint = 0,
    @umPaymentTermID char(15) = '',
    @umTaxSched char(15) = '',
    @umIndividual tinyint = 0,
    @umCBCashOnly tinyint = 0,
    @umCBBilledCustomer tinyint = 0,
    @umUserID char(15) = NULL,
    @umDateCreated datetime = '',
    @umDateModified datetime = '',
    @umUDF1 char(31) = '',
    @umUDF2 char(31) = '',
    @umPymtRestriction tinyint,
    @umExpirationDate datetime,
    @Email char(31) = '',
    @AddInfo varchar(61) = '',
    @scMessage varchar(255) = '' OUTPUT,
    @scError int = 0 OUTPUT
AS
/* Purpose: emulator for customer business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    IF EXISTS (SELECT 1 FROM conv.Customer WHERE ClientId = @ClientId AND TakeId = @TakeId AND CustomerID = @CustomerID)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Submitted customer already exists. (CUSTNMBR = ' + RTRIM(@CustomerID) + ')';
        RETURN;
    END;
    INSERT conv.Customer (ClientId, TakeId, CustomerID, FirstName, LastName, CustomerClassID, Individual) VALUES (@ClientId, @TakeId, @CustomerID, @umFirstName, @umLastName, @umCustClassID, @umIndividual);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateCustomerAddress
    @UserID char(15) = '',
    @CustomerID char(15) = '',
    @ContactPerson char(31) = '',
    @Phone1 char(21) = '',
    @Phone2 char(21) = '',
    @Phone3 char(21) = '',
    @Fax char(21) = '',
    @BillToAddress tinyint = 0,
    @PrintContactPerson tinyint = 0,
    @ADRSCODE char(15) = 'PRIMARY',
    @Phone1Type int = 1,
    @Phone2Type int = 2,
    @Phone3Type int = 3,
    @AddressCateg smallint = 0,
    @StreetNumber char(9) = '',
    @StreetNumberLng int = 0,
    @StreetNumberSuffix char(3) = '',
    @StreetName char(31) = '',
    @StreetType char(7) = '',
    @StreetDirectionP char(3) = '',
    @StreetDirection char(3) = '',
    @AptNumber char(7) = '',
    @AptDesc char(7) = '',
    @UnitDesig char(7) = '',
    @ZipCode char(11) = '',
    @CityName char(31) = '',
    @STATE char(29) = '',
    @COUNTRY char(21) = '',
    @Postal_Walk char(9) = '',
    @PostalWalkVer char(1) = '',
    @CreateDate datetime = '',
    @AptNumberPlus char(7) = '',
    @ADDRESS1 char(31) = '',
    @ADDRESS2 char(31) = '',
    @ADDRESS3 char(31) = '',
    @scMessage varchar(255) = '' OUTPUT,
    @scError int = 0 OUTPUT
AS
/* Purpose: emulator for customer address business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    IF NOT EXISTS (SELECT 1 FROM conv.Customer WHERE ClientId = @ClientId AND TakeId = @TakeId AND CustomerID = @CustomerID)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Submitted customer does not exist. (CUSTNMBR = ' + RTRIM(@CustomerID) + ')';
        RETURN;
    END;
    IF EXISTS (SELECT 1 FROM conv.CustomerAddress WHERE ClientId = @ClientId AND TakeId = @TakeId AND CustomerID = @CustomerID AND ADRSCODE = @ADRSCODE)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Error inserting into UMRM0111 (CUST ADDR). (CUSTNMBR = ' + RTRIM(@CustomerID) + ')';
        RETURN;
    END;
    INSERT conv.CustomerAddress (ClientId, TakeId, CustomerID, ADRSCODE, ADDRESS1, CityName) VALUES (@ClientId, @TakeId, @CustomerID, @ADRSCODE, @ADDRESS1, @CityName);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateLocation
    @UserID char(15) = '',
    @LocationID char(15),
    @LocationType smallint,
    @LocationClass char(15),
    @BudgetPlanEligibility tinyint,
    @AddressType smallint,
    @ZoneID char(15),
    @BillToCust char(15),
    @BillToCustType smallint,
    @Owner char(15),
    @TenantCustNum char(15),
    @AccumType smallint,
    @AccumMasterID char(15),
    @MinBill tinyint,
    @MaxBill tinyint,
    @LastBill char(15),
    @LastStatementDate datetime,
    @LastStatementAmount numeric(19, 5) = 0,
    @ServiceCategory smallint,
    @PenaltyID char(15),
    @RecvAcct int,
    @ElectricTaxSched varchar(15),
    @WaterTaxSched varchar(15),
    @SewerTaxSched varchar(15),
    @GasTaxSched varchar(15),
    @PhoneTaxSched varchar(15),
    @OtherTaxSched varchar(15),
    @PropertyTaxTaxSched varchar(15),
    @CableTaxSched varchar(15),
    @InternetTaxSched varchar(15),
    @FireProtectionTaxSched varchar(15),
    @SanitationTaxSched varchar(15),
    @PropaneTaxSched varchar(15),
    @LocDefined1 char(31),
    @LocDefined2 char(31),
    @ThirdPartyDesc char(31),
    @AddressCateg smallint,
    @StreetNumber char(9),
    @StreetNumberLng int,
    @StreetNumberSuffix char(3),
    @StreetName char(31),
    @StreetType char(7),
    @StreetDirectionP char(3),
    @StreetDirection char(3),
    @AptNumber char(7),
    @AptDesc char(7),
    @UnitDesig char(7),
    @ZipCode char(11),
    @CityName char(31),
    @STATE char(29),
    @COUNTRY char(21),
    @Postal_Walk char(9),
    @PostalWalkVer char(1),
    @CreateDate datetime,
    @AptNumberPlus char(7),
    @ADDRESS1 char(31) = '',
    @ADDRESS2 char(31) = '',
    @ADDRESS3 char(31) = '',
    @ServicePlanNumber char(21) = '',
    @ServiceLotNumber char(21) = '',
    @KeyNum char(21) = '',
    @ResidentialUnits smallint,
    @SICCode char(11) = '',
    @AssessorID char(25) = '',
    @LandParcelID char(25) = '',
    @DefaultInterim tinyint,
    @RouteID char(15) = '',
    @scMessage varchar(255) = '' OUTPUT,
    @scError int = 0 OUTPUT
AS
/* Purpose: emulator for location business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    IF EXISTS (SELECT 1 FROM conv.Location WHERE ClientId = @ClientId AND TakeId = @TakeId AND LocationID = @LocationID)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Submitted location already exists. (LOCATION = ' + RTRIM(@LocationID) + ')';
        RETURN;
    END;
    INSERT conv.Location (ClientId, TakeId, LocationID, BillToCust, LocationClass, RouteID) VALUES (@ClientId, @TakeId, @LocationID, @BillToCust, @LocationClass, @RouteID);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateEquipment
    @UserID char(15) = '',
    @EquipmentID char(15) = '',
    @EquipmentClass char(15) = '',
    @ServiceCategory smallint = 0,
    @ConEst smallint = 0,
    @Installed bit = 0,
    @InstallDate datetime = '',
    @EquipmentLot char(21) = '',
    @SerialNumber char(31) = '',
    @PurchaseDate datetime = '',
    @PurchaseCost numeric(19, 5) = 0,
    @RemovalDate datetime = '',
    @SealedDate datetime = '',
    @TestDueDate datetime = '',
    @DateCreated datetime = '',
    @Kh char(7) = '',
    @Elem char(7) = '',
    @AccuracyClass char(15) = '',
    @PrimaryThru tinyint = 0,
    @SecondaryAmps numeric(19, 5) = 0,
    @SecondaryVolts numeric(19, 5) = 0,
    @EquipmentStatus smallint = 0,
    @InstallableStatus tinyint = 0,
    @UDF1 char(31) = '',
    @UDF2 char(31) = '',
    @RemoteID char(20) = '',
    @LocationID char(15) = '',
    @RInstallationDate datetime = '',
    @RRemovalDate datetime = '',
    @RRemovalReason char(65) = '',
    @RInstallStatus tinyint = 0,
    @RConnectStatus smallint = 0,
    @EqMult numeric(19, 5) = 1,
    @ConnectSeq smallint = 0,
    @TemperCode char(5) = 0,
    @PhysicalLocation char(65) = '',
    @Locator char(21) = '',
    @GISIdentifier char(21) = '',
    @Model char(15) = '',
    @Protection smallint = 0,
    @EqDescription char(65) = '',
    @CumulativeDemand smallint = 0,
    @EquipmentType int = 0,
    @Manufacturer char(30) = '',
    @Diameter numeric(19,5) = 0,
    @NumberOfWires int = 0,
    @Phase int = 0,
    @Voltage numeric(8,2) = 0,
    @Amperage numeric(8,2) = 0,
    @StatisticalNumber char(15) = '',
    @DifferenceReadingsDials int = 0,
    @KWDials int = 0,
    @KVADials int = 0,
    @PFReadingsDials int = 0,
    @LFReadingsDials int = 0,
    @NetMeterReceivedDials int = 0,
    @EquipmentRemote char(1) = '',
    @NetMeterType int = 0,
    @DifferenceReadingsDialDigits varchar(1000) = '',
    @KWDialDigits varchar(1000) = '',
    @KVADialDigits varchar(1000) = '',
    @PFDialDigits varchar(1000) = '',
    @LFDialDigits varchar(1000) = '',
    @NetMeterReceivedDialDigits varchar(1000) = '',
    @DifferenceDialDecimals varchar(1000) = '',
    @KWDialDecimals varchar(1000) = '',
    @KVADialDecimals varchar(1000) = '',
    @PFDialDecimals varchar(1000) = '',
    @LFDialDecimals varchar(1000) = '',
    @NetMeterReceivedDialDecimals varchar(1000) = '',
    @DifferenceReadingDialMultiplier varchar(1000) = '',
    @KWDialMultiplier varchar(1000) = '1',
    @KVADialMultiplier varchar(1000) = '1',
    @PFDialMultiplier varchar(1000) = '1',
    @LFDialMultiplier varchar(1000) = '1',
    @NetMeterReceivedDialMultiplier varchar(1000) = '1',
    @DifferenceReadingsDialRemoteID varchar(1000) = '',
    @KWDialRemoteID varchar(1000) = '',
    @KVADialRemoteID varchar(1000) = '',
    @PFDialRemoteID varchar(1000) = '',
    @LFDialRemoteID varchar(1000) = '',
    @NetMeterReceivedDialRemoteID varchar(1000) = '',
    @DifferenceReadingsDialRemoteType varchar(1000) = '',
    @KWDialRemoteType varchar(1000) = '',
    @KVADialRemoteType varchar(1000) = '',
    @PFDialRemoteType varchar(1000) = '',
    @LFDialRemoteType varchar(1000) = '',
    @NetMeterReceivedDialRemoteType varchar(1000) = '',
    @DifferenceReadingsDialEffectiveDate varchar(1000) = '',
    @KWDialRemoteEffectiveDate varchar(1000) = '',
    @KVADialRemoteEffectiveDate varchar(1000) = '',
    @PFDialRemoteEffectiveDate varchar(1000) = '',
    @LFDialRemoteEffectiveDate varchar(1000) = '',
    @NetMeterReceivedEffectiveDate varchar(1000) = '',
    @DifferenceReadingsDialExcludeUsage int = 2,
    @NetMeterReceivedDialExcludeUsage int = 2,
    @SmartMeter int = 2,
    @AutoConnectDisconnect int = 2,
    @MeterModelCode char(15) = '',
    @ProgramID char(15) = '',
    @RecorderID char(15) = '',
    @DevicePassword char(20) = '',
    @ReadLoadProfile char(1) = '',
    @SelfReadAndTrip int = 0,
    @SelfReadAndTripDay int = 0,
    @DaylightSavingTime int = 0,
    @ResetDemandIndicator int = 0,
    @ExcludeFromEMRExport int = 0,
    @scMessage varchar(255) = '' OUTPUT,
    @scError int = 0 OUTPUT
AS
/* Purpose: emulator for equipment business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    IF EXISTS (SELECT 1 FROM conv.Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId AND EquipmentID = @EquipmentID)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Error inserting into UM00400. (EquipmentID = ' + RTRIM(@EquipmentID) + ')';
        RETURN;
    END;
    IF @EquipmentClass = ''
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Error No Equipment Class. (EquipmentID = ' + RTRIM(@EquipmentID) + ')';
        RETURN;
    END;
    INSERT conv.Equipment (ClientId, TakeId, EquipmentID, EquipmentClass, ServiceCategory, SerialNumber, RemoteID) VALUES (@ClientId, @TakeId, @EquipmentID, @EquipmentClass, @ServiceCategory, @SerialNumber, @RemoteID);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateConnection
    @UserID char(15) = '',
    @LocationID char(15) = '',
    @ServiceType char(15) = '',
    @ServiceCategory smallint = 0,
    @UMMETGRPID char(15) = '',
    @UMMETGRPTYPE smallint = 0,
    @UMMULTGRPID char(15) = '',
    @RouteID char(15) = '',
    @ConnectStatus smallint = 0,
    @TariffID char(15) = '',
    @ConnectionDate datetime = '',
    @DisconnectionDate datetime = '',
    @UMCONNMULT numeric(19, 5) = 1,
    @UMMULTTYPE smallint = 0,
    @EquipmentID char(15) = '',
    @UseAltMeter tinyint = 0,
    @UMSEQNUM numeric(19, 5) = 0,
    @UMFIXEDMULT numeric(19, 5) = 1,
    @umConsumpMult numeric(19, 5) = 1,
    @UMLOSSMULT numeric(19, 5) = 1,
    @UMRNGMINMULT numeric(19, 5) = 1,
    @UMBELONGTO char(15) = '',
    @UserDefined1 char(31) = '',
    @UserDefined2 char(31) = '',
    @Tar11 char(15) = '',
    @Tar12 char(15) = '',
    @Tar13 char(15) = '',
    @UMTaxSched char(15) = '',
    @UMINDX smallint = 0,
    @Imported smallint = 0,
    @DeliveredEquipmentID char(15) = '',
    @inPeriodIndex int = 0,
    @inRate1 char(15) = '',
    @inRate2 char(15) = '',
    @inRate3 char(15) = '',
    @inRate4 char(15) = '',
    @scMessage varchar(255) = '' OUTPUT,
    @scError int = 0 OUTPUT
AS
/* Purpose: emulator for connection business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    IF @LocationID <> '' AND NOT EXISTS (SELECT 1 FROM conv.Location WHERE ClientId = @ClientId AND TakeId = @TakeId AND LocationID = @LocationID)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Error inserting into UM00300. - UM_SC_spBaseCreateConnection (LOCATIONID = ' + RTRIM(@LocationID) + ')';
        RETURN;
    END;
    IF @EquipmentID <> '' AND NOT EXISTS (SELECT 1 FROM conv.Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId AND EquipmentID = @EquipmentID)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'EquipmentID [' + RTRIM(@EquipmentID) + '] has no base connection.';
        RETURN;
    END;
    IF @EquipmentID <> '' AND EXISTS (SELECT 1 FROM conv.Connection WHERE ClientId = @ClientId AND TakeId = @TakeId AND EquipmentID = @EquipmentID AND LocationID = @LocationID AND ServiceType = @ServiceType)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Connection with EquipmentID [' + RTRIM(@EquipmentID) + '] is duplicated.';
        RETURN;
    END;
    INSERT conv.Connection (ClientId, TakeId, LocationID, ServiceType, EquipmentID, ConnectStatus, RouteID) VALUES (@ClientId, @TakeId, @LocationID, @ServiceType, @EquipmentID, @ConnectStatus, @RouteID);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateMoveInCustomers
    @UserID char(15) = '',
    @MoveInCustomerID char(15) = '',
    @LocationID char(15) = '',
    @MoveOutCustomerID char(15) = '',
    @RequestID char(15) = '',
    @ScheduledDate datetime = '',
    @ScheduledTime datetime = '',
    @scMessage varchar(255) OUTPUT,
    @scError int OUTPUT
AS
/* Purpose: emulator for location history business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    INSERT conv.LocationHistory (ClientId, TakeId, LocationID, CustomerID, RequestID) VALUES (@ClientId, @TakeId, @LocationID, @MoveInCustomerID, @RequestID);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateBegBalance
    @CustomerID char(15) = '',
    @LocationID char(15) = '',
    @Amount numeric(19, 5),
    @MiscChargeType char(15) = '',
    @TransDesc char(33) = '',
    @ServiceType char(15) = '',
    @PenaltyDone tinyint = 0,
    @TransDate datetime = '',
    @DueDate datetime = '',
    @TaxSchedule char(15) = '',
    @PaymentType tinyint = 0,
    @DebitAccount int = 0,
    @CreditAccount int = 0,
    @DoNotApplyCreditBalanceToBudget bit = 0,
    @scMessage varchar(255) OUTPUT,
    @scError int OUTPUT
AS
/* Purpose: emulator for beginning balance business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    IF @Amount = 0
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Amount = 0 (LocationID = ' + RTRIM(@LocationID) + ', CustomerID = ' + RTRIM(@CustomerID) + ' )';
        RETURN;
    END;
    INSERT conv.BegBalance (ClientId, TakeId, CustomerID, LocationID, Amount, MiscChargeType, ServiceType) VALUES (@ClientId, @TakeId, @CustomerID, @LocationID, @Amount, @MiscChargeType, @ServiceType);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateDeposit
    @UserID char(15) = '',
    @UserDate datetime = '',
    @CustomerID char(15) = '',
    @LocationID char(15) = '',
    @DocumentDate datetime = '',
    @ServiceCategory smallint = 0,
    @DepositAmount numeric(19, 5) = 0,
    @PaymentDate datetime = '',
    @DepositDocument char(15) = '',
    @DepositID char(15) = '',
    @DepositAmtPaid numeric(19, 5) = 0,
    @scMessage varchar(255) OUTPUT,
    @scError int OUTPUT
AS
/* Purpose: emulator for deposit business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    INSERT conv.Deposit (ClientId, TakeId, CustomerID, LocationID, DepositID, DepositAmount) VALUES (@ClientId, @TakeId, @CustomerID, @LocationID, @DepositID, @DepositAmount);
END;
GO

CREATE OR ALTER PROCEDURE conv.UM_SC_spBaseCreateHistoricalMR
    @UserID char(15) = '',
    @UserDate datetime = '',
    @LocationID char(15) = '',
    @CustomerID char(15) = '',
    @EquipmentID char(15) = '',
    @ReadingDate datetime = '',
    @ReadingType smallint = 0,
    @NumberOfDays smallint = 0,
    @Consumption1 numeric(19, 5) = 0,
    @Consumption2 numeric(19, 5) = 0,
    @Consumption3 numeric(19, 5) = 0,
    @Reading numeric(19, 5) = 0,
    @PreviousReading numeric(19, 5) = 0,
    @BillDocumentNumber char(15) = '',
    @PowerFactor1 numeric(19, 5) = 0,
    @LoadFactor1 numeric(19, 5) = 0,
    @ThermFactor numeric(19,5) = 0,
    @scMessage varchar(255) OUTPUT,
    @scError int OUTPUT
AS
/* Purpose: emulator for historical meter read business-logic procedure in shadow mode.
   Inputs: original CSM signature plus ClientId and TakeId from SESSION_CONTEXT.
   Outputs: mapped conv master rows and scError/scMessage contract where present. */
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ClientId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'ClientId'));
    DECLARE @TakeId varchar(20) = CONVERT(varchar(20), SESSION_CONTEXT(N'TakeId'));
    IF @ClientId IS NULL SET @ClientId = '';
    IF @TakeId IS NULL SET @TakeId = '';
    SET @scError = 0;
    SET @scMessage = '';
    IF NOT EXISTS (SELECT 1 FROM conv.Equipment WHERE ClientId = @ClientId AND TakeId = @TakeId AND EquipmentID = @EquipmentID)
    BEGIN
        SET @scError = 1;
        SET @scMessage = 'Error inserting into UM30300.';
        RETURN;
    END;
    INSERT conv.HistMR (ClientId, TakeId, LocationID, CustomerID, EquipmentID, ReadingDate, ReadingType, Reading, Consumption1) VALUES (@ClientId, @TakeId, @LocationID, @CustomerID, @EquipmentID, @ReadingDate, @ReadingType, @Reading, @Consumption1);
END;
GO
