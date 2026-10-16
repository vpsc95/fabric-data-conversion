/* =====================================================================
   60_csm.sql: CSM state as the validation rules see it, for replays and dry runs.

   The legacy rules check two kinds of CSM data:
   - what already existed in the company BEFORE this conversion ("Duplicate Customer Code in CSM",
     "umEquipmentID already in CSM"): ref.SetupValue tables UMRM0101 / UM00400 (empty for a new client);
   - what earlier modules LOADED ("Customer | Location Code NOT in Active or History"): simulated from
     gold - a record loads when it has no error (isvalid <> 0), as the go-live integrity report counts it.
   On a live run against the client's SQL Server (Mode B) these views are replaced by the real CSM tables.
   ===================================================================== */
SET NOCOUNT ON;
GO
CREATE OR ALTER VIEW csm.v_LoadedCustomer AS          -- UMRM0101 after the customer load
SELECT DISTINCT ClientId, TakeId, CustomerID AS custnmbr FROM gold.UM_Customer WHERE isvalid <> 0;
GO
CREATE OR ALTER VIEW csm.v_LoadedLocation AS          -- UM00600 after the location load (current bill-to)
SELECT ClientId, TakeId, LocationID AS umLocationID, CustomerID AS umBillToCust FROM gold.UM_Location WHERE isvalid <> 0;
GO
CREATE OR ALTER VIEW csm.v_LoadedLocationHistory AS   -- UM00600H after the move-in history load
SELECT ClientId, TakeId, LocationID AS umLocationID, CustomerID AS umBillToCust FROM gold.UM_LocationHistory WHERE isvalid <> 0;
GO
CREATE OR ALTER VIEW csm.v_LoadedEquipment AS         -- UM00400 after the equipment load
SELECT DISTINCT ClientId, TakeId, EquipmentID AS umEquipmentID FROM gold.UM_Equipment WHERE isvalid <> 0;
GO
