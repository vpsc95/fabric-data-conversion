/* =====================================================================
   20_xref_ref.sql: crosswalks (from clients/<client>/crosswalks/<name>.yaml) and the CSM setup snapshot.

   xref.CrosswalkValue stores every crosswalk generically (one row per code and attribute), so a new
   crosswalk is a YAML file, not a schema change. The typed views below make the gold SQL readable.

   ref.SetupValue holds the CSM setup tables the validation rules check against (service types
   UM41000, tariffs UM41301, routes UM40900, connection statuses UM40630). Until the client's CSM
   setup snapshot arrives, the values are PROVISIONAL: each row says where it came from (Source)
   and why (Note), so every number that depends on them is traceable and replaceable.
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('xref.CrosswalkValue') IS NULL
CREATE TABLE xref.CrosswalkValue (
    ClientId    varchar(20)    NOT NULL,
    CrosswalkId varchar(60)    NOT NULL,
    LegacyCode  nvarchar(100)  NOT NULL,
    Attribute   varchar(60)    NOT NULL,     -- 'target' or an extra attribute such as 'category'
    Value       nvarchar(200)  NOT NULL,
    Include     bit            NOT NULL CONSTRAINT DF_xref_CW_Include DEFAULT 1,   -- 0 = excluded on purpose (expected issue)
    Reason      nvarchar(400)  NOT NULL CONSTRAINT DF_xref_CW_Reason DEFAULT N'',
    CONSTRAINT PK_xref_CrosswalkValue PRIMARY KEY (ClientId, CrosswalkId, LegacyCode, Attribute)
);
IF OBJECT_ID('ref.SetupValue') IS NULL
CREATE TABLE ref.SetupValue (
    ClientId    varchar(20)    NOT NULL,
    SetupTable  varchar(20)    NOT NULL,     -- CSM table the value belongs to, e.g. UM41301
    Code        nvarchar(60)   NOT NULL,
    Source      varchar(60)    NOT NULL,     -- csm-snapshot | spec | integrity-report
    Note        nvarchar(400)  NOT NULL CONSTRAINT DF_ref_SetupValue_Note DEFAULT N'',
    CONSTRAINT PK_ref_SetupValue PRIMARY KEY (ClientId, SetupTable, Code)
);
GO

CREATE OR ALTER VIEW xref.v_ServiceCode AS
/* LEFT(DESCRIPTION,3) -> category, residential/commercial service type, fixed tariff (connection_service_code.yaml) */
SELECT ClientId, LegacyCode AS ServiceCode,
       MAX(CASE WHEN Attribute = 'category' THEN Value END)                AS Category,
       MAX(CASE WHEN Attribute = 'service_type_individual' THEN Value END) AS ServiceTypeRes,
       MAX(CASE WHEN Attribute = 'service_type_business' THEN Value END)   AS ServiceTypeCom,
       MAX(CASE WHEN Attribute = 'fixed_tariff' THEN Value END)            AS FixedTariff,
       CAST(MIN(CAST(Include AS int)) AS bit)                              AS Include,
       MAX(Reason)                                                         AS Reason
FROM xref.CrosswalkValue WHERE CrosswalkId = 'connection_service_code'
GROUP BY ClientId, LegacyCode;
GO
CREATE OR ALTER VIEW xref.v_WaterTariff AS
/* Meter_Size_Desc -> water variable tariff (CTAR11) by residential/commercial (meter_size_to_water_tariff.yaml) */
SELECT ClientId, LegacyCode AS MeterSize,
       MAX(CASE WHEN Attribute = 'residential_tariff' THEN Value END) AS ResTariff,
       MAX(CASE WHEN Attribute = 'commercial_tariff' THEN Value END)  AS ComTariff
FROM xref.CrosswalkValue WHERE CrosswalkId = 'meter_size_to_water_tariff'
GROUP BY ClientId, LegacyCode;
GO
CREATE OR ALTER VIEW xref.v_ServiceClass AS
/* UM_Customer.Individual (1 = person, 0 = business) -> sewer variable tariff (customer_individual_to_service_class.yaml) */
SELECT ClientId, LegacyCode AS Individual,
       MAX(CASE WHEN Attribute = 'sewer_variable_tariff' THEN Value END) AS SewerTariff
FROM xref.CrosswalkValue WHERE CrosswalkId = 'customer_individual_to_service_class'
GROUP BY ClientId, LegacyCode;
GO
CREATE OR ALTER VIEW xref.v_EquipmentClass AS
SELECT ClientId, LegacyCode AS MeterSize, Value AS EquClassID
FROM xref.CrosswalkValue WHERE CrosswalkId = 'meter_size_to_equipment_class' AND Attribute = 'target';
GO
CREATE OR ALTER VIEW xref.v_LocationClass AS
SELECT ClientId, LegacyCode AS CustomerClass, Value AS LocationClass
FROM xref.CrosswalkValue WHERE CrosswalkId = 'customer_class_to_location_class' AND Attribute = 'target';
GO
CREATE OR ALTER VIEW xref.v_RouteCity AS
SELECT ClientId, LegacyCode AS RouteID, Value AS City
FROM xref.CrosswalkValue WHERE CrosswalkId = 'route_to_city' AND Attribute = 'target';
GO
CREATE OR ALTER VIEW xref.v_RouteZone AS
SELECT ClientId, LegacyCode AS RouteID, Value AS ZoneID
FROM xref.CrosswalkValue WHERE CrosswalkId = 'route_to_zone' AND Attribute = 'target';
GO
CREATE OR ALTER VIEW xref.v_DepositType AS
SELECT ClientId, LegacyCode AS ServiceType, Value AS DepositID
FROM xref.CrosswalkValue WHERE CrosswalkId = 'deposit_service_type_to_deposit_type' AND Attribute = 'target';
GO
CREATE OR ALTER VIEW xref.v_BalanceConstant AS
SELECT ClientId, LegacyCode AS Setting, Value
FROM xref.CrosswalkValue WHERE CrosswalkId = 'balance_gl_accounts' AND Attribute = 'target';
GO
