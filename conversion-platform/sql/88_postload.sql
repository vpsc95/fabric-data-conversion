/* =====================================================================
   88_postload.sql: post-load reconciliation against the shadow CSM emulator.
   ===================================================================== */
SET NOCOUNT ON;
GO
CREATE OR ALTER VIEW recon.v_PostLoad
AS
/* Purpose: compare gold-valid rows, load.RowStatus, and conv emulator rows after P11 Load to CSM. */
WITH emulator AS (
    SELECT 'UMRM0101' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.Customer GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UMRM0111' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.CustomerAddress GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UM00600' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.Location GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UM00400' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.Equipment GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UM00300' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.Connection GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UM00600H' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.LocationHistory GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UM20400' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.BegBalance GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UM01900' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.Deposit GROUP BY ClientId, TakeId
    UNION ALL
    SELECT 'UM30300' AS Module, ClientId, TakeId, COUNT(*) AS EmulatorRows FROM conv.HistMR GROUP BY ClientId, TakeId
), totals AS (
    SELECT ClientId, TakeId, 'UM20400' AS Module, 'Z-BEG BAL' AS ControlName, SUM(Amount) AS EmulatorAmount FROM conv.BegBalance GROUP BY ClientId, TakeId
    UNION ALL
    SELECT ClientId, TakeId, 'UM01900', RTRIM(DepositID), SUM(DepositAmount) FROM conv.Deposit GROUP BY ClientId, TakeId, DepositID
)
SELECT s.ClientId, s.TakeId, p.Module, p.ModuleName,
       SUM(CASE WHEN s.Status <> 'skipped_invalid' THEN 1 ELSE 0 END) AS ExpectedToLoad,
       SUM(CASE WHEN s.Status = 'loaded' THEN 1 ELSE 0 END) AS Loaded,
       SUM(CASE WHEN s.Status = 'failed' THEN 1 ELSE 0 END) AS Failed,
       COALESCE(MAX(e.EmulatorRows), 0) AS EmulatorRows,
       SUM(CASE WHEN s.Status <> 'skipped_invalid' THEN 1 ELSE 0 END) - COALESCE(MAX(e.EmulatorRows), 0) AS Variance,
       CAST(NULL AS varchar(30)) AS ControlName,
       CAST(NULL AS numeric(19,5)) AS GoldAmount,
       CAST(NULL AS numeric(19,5)) AS EmulatorAmount,
       CAST(NULL AS numeric(19,5)) AS AmountVariance
FROM load.ProcMap p
JOIN load.RowStatus s ON s.Module = p.Module
LEFT JOIN emulator e ON e.ClientId = s.ClientId AND e.TakeId = s.TakeId AND e.Module = s.Module
GROUP BY s.ClientId, s.TakeId, p.Module, p.ModuleName
UNION ALL
SELECT g.ClientId, g.TakeId, g.Module, 'control total', g.Records, g.Records, 0, g.Records, 0,
       g.Name, g.Amount, COALESCE(t.EmulatorAmount, 0), g.Amount - COALESCE(t.EmulatorAmount, 0)
FROM recon.v_ControlTotal g
LEFT JOIN totals t ON t.ClientId = g.ClientId AND t.TakeId = g.TakeId AND t.Module = g.Module AND t.ControlName = g.Name
WHERE g.Module IN ('UM20400', 'UM01900');
GO
