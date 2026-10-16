/* =====================================================================
   80_recon.sql: reconciliation views, in the shape of the go-live integrity report.
   Read by the answer-key check (golden-master-test skill), the triage agent and Power BI.
   ===================================================================== */
SET NOCOUNT ON;
GO
CREATE OR ALTER VIEW recon.v_ModuleSummary
AS
/* Received / loaded / failed per module. Customers: one CSM customer per CustomerID (ID = 1 row). */
SELECT ClientId, TakeId, 'UMRM0101' AS Module, COUNT(*) AS Received, COUNT(DISTINCT CustomerID) AS ReceivedDistinct,
       SUM(CASE WHEN ID = 1 AND isvalid <> 0 THEN 1 ELSE 0 END) AS Loaded, SUM(CASE WHEN ID = 1 AND isvalid = 0 THEN 1 ELSE 0 END) AS Failed
FROM gold.UM_Customer GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UMRM0111', SUM(CASE WHEN ID = 1 THEN 1 ELSE 0 END), SUM(CASE WHEN ID = 1 THEN 1 ELSE 0 END),
       SUM(CASE WHEN ID = 1 AND isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN ID = 1 AND isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_Customer GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UM00600', COUNT(*), COUNT(DISTINCT LocationID), SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_Location GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UM00600H', COUNT(*), COUNT(*), SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_LocationHistory GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UM00400', COUNT(*), COUNT(DISTINCT EquipmentID), SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_Equipment GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UM00300', COUNT(*), COUNT(*), SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_Connection GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UM20400', COUNT(*), COUNT(*), SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_BegBalance GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UM01900', COUNT(*), COUNT(*), SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_Deposit GROUP BY ClientId, TakeId
UNION ALL
SELECT ClientId, TakeId, 'UM30300', COUNT(*), COUNT(*), SUM(CASE WHEN isvalid <> 0 THEN 1 ELSE 0 END), SUM(CASE WHEN isvalid = 0 THEN 1 ELSE 0 END)
FROM gold.UM_HistMR GROUP BY ClientId, TakeId;
GO

CREATE OR ALTER VIEW recon.v_IssueSummary
AS
/* Records per rule; Expected = excluded by design (crosswalk / override, or on an excluded record);
   Actionable = everything else, the list that goes to the client or to Cogsdale to fix. */
SELECT i.ClientId, i.TakeId, i.Module, i.RuleId, MAX(i.Severity) AS Severity,
       COUNT(DISTINCT i.RowId) AS Records,
       COUNT(DISTINCT CASE WHEN i.IsExpected = 1 THEN i.RowId END) AS Expected,
       COUNT(DISTINCT CASE WHEN i.IsExpected = 0 THEN i.RowId END) AS Actionable,
       MAX(r.AnswerKeyRule) AS AnswerKeyRule
FROM run.Issue i
LEFT JOIN meta.RuleCatalog r ON r.RuleId = i.RuleId
GROUP BY i.ClientId, i.TakeId, i.Module, i.RuleId;
GO

CREATE OR ALTER VIEW recon.v_FailedRecords
AS
/* Failed records per module, split into expected (excluded by design) and actionable. */
SELECT ClientId, TakeId, Module,
       COUNT(DISTINCT CASE WHEN Severity = 'E' THEN RowId END) AS FailedRecords,
       COUNT(DISTINCT CASE WHEN Severity = 'E' AND IsExpected = 0 THEN RowId END) AS ActionableFailedRecords
FROM run.Issue GROUP BY ClientId, TakeId, Module;
GO

CREATE OR ALTER VIEW recon.v_ControlTotal
AS
/* Money that loads (isvalid <> 0), by misc charge type / deposit type, as the legacy validation SELECTs. */
SELECT ClientId, TakeId, 'UM20400' AS Module, BBMisType AS Name, COUNT(*) AS Records,
       SUM(TRY_CONVERT(numeric(19,5), BBAmount)) AS Amount
FROM gold.UM_BegBalance WHERE isvalid <> 0 GROUP BY ClientId, TakeId, BBMisType
UNION ALL
SELECT ClientId, TakeId, 'UM01900', DepositID, COUNT(*), SUM(DepositAmount)
FROM gold.UM_Deposit WHERE isvalid <> 0 GROUP BY ClientId, TakeId, DepositID;
GO
