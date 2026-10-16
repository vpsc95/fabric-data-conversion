/* =====================================================================
   00_schemas.sql: schemas for the Cogsdale conversion platform database.
   Runs unchanged on Fabric SQL database (Mode A) and SQL Server 2016+ (Mode B).
   ===================================================================== */
SET NOCOUNT ON;
IF SCHEMA_ID('meta')  IS NULL EXEC('CREATE SCHEMA meta');   -- rules, rule overrides, length rules, allowances
IF SCHEMA_ID('xref')  IS NULL EXEC('CREATE SCHEMA xref');   -- crosswalks loaded from clients/<client>/crosswalks/<name>.yaml
IF SCHEMA_ID('ref')   IS NULL EXEC('CREATE SCHEMA ref');    -- CSM setup snapshot (provisional until the client copy arrives)
IF SCHEMA_ID('slv')   IS NULL EXEC('CREATE SCHEMA slv');    -- silver copy of the take (text, as received, with lineage)
IF SCHEMA_ID('gold')  IS NULL EXEC('CREATE SCHEMA gold');   -- UM staging (what the loader passes to the CSM procedures)
IF SCHEMA_ID('csm')   IS NULL EXEC('CREATE SCHEMA csm');    -- CSM state after load, simulated for replays and dry runs
IF SCHEMA_ID('rules') IS NULL EXEC('CREATE SCHEMA rules');  -- validation procedures
IF SCHEMA_ID('run')   IS NULL EXEC('CREATE SCHEMA run');    -- run log, issues, step metrics
IF SCHEMA_ID('recon') IS NULL EXEC('CREATE SCHEMA recon');  -- reconciliation views (received / loaded / failed / totals)
GO
