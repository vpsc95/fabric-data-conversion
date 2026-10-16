/* =====================================================================
   89_take_diff.sql: take-over-take comparison (process P16).
   Takes are ordered by their take date (run.Take, written by the profile step). Issue groups carry a
   signature (module + failed rules + code-level features) that is the same in every take, so the same
   problem keeps its key: a group is new, resolved, grown, shrunk or unchanged against the previous take.
   At record level (every issue that is not expected by design, errors and warnings, by the record's
   natural key): still flagged, fixed since the previous take (in the source), or newly flagged.
   Reporting code for the platform database (LocalDB / Fabric SQL database).
   ===================================================================== */
SET NOCOUNT ON;
GO
CREATE OR ALTER VIEW run.v_TakeSequence AS
SELECT ClientId, TakeId, TakeDate, Simulated,
       LAG(TakeId) OVER (PARTITION BY ClientId ORDER BY TakeDate, TakeId) AS PrevTakeId,
       ROW_NUMBER() OVER (PARTITION BY ClientId ORDER BY TakeDate, TakeId) AS TakeNo
FROM run.Take;
GO
CREATE OR ALTER VIEW recon.v_TakeDiffGroup AS
SELECT s.ClientId, s.TakeId, s.PrevTakeId, x.Module, x.GroupKey, x.RuleSet, x.Features, x.RuleClass,
       x.PrevRecords, x.Records, x.Records - x.PrevRecords AS Change,
       CASE WHEN x.PrevRecords = 0 THEN 'new' WHEN x.Records = 0 THEN 'resolved'
            WHEN x.Records > x.PrevRecords THEN 'grown' WHEN x.Records < x.PrevRecords THEN 'shrunk' ELSE 'unchanged' END AS Status
FROM run.v_TakeSequence AS s
CROSS APPLY (
    SELECT COALESCE(c.Module, p.Module) AS Module, COALESCE(c.GroupKey, p.GroupKey) AS GroupKey,
           COALESCE(c.RuleSet, p.RuleSet) AS RuleSet, COALESCE(c.Features, p.Features) AS Features,
           COALESCE(c.RuleClass, p.RuleClass) AS RuleClass, ISNULL(p.Records, 0) AS PrevRecords, ISNULL(c.Records, 0) AS Records
    FROM (SELECT g.Module, g.GroupKey, g.RuleSet, g.Features, g.RuleClass, g.Records
          FROM recon.v_IssueGroup AS g WHERE g.ClientId = s.ClientId AND g.TakeId = s.TakeId) AS c
    FULL OUTER JOIN
         (SELECT g.Module, g.GroupKey, g.RuleSet, g.Features, g.RuleClass, g.Records
          FROM recon.v_IssueGroup AS g WHERE g.ClientId = s.ClientId AND g.TakeId = s.PrevTakeId) AS p
      ON p.GroupKey = c.GroupKey
) AS x
WHERE s.PrevTakeId IS NOT NULL;
GO
CREATE OR ALTER VIEW recon.v_TakeDiffRecord AS
SELECT s.ClientId, s.TakeId, s.PrevTakeId, x.Module,
       CASE WHEN x.InPrev = 1 AND x.InCur = 1 THEN 'still flagged' WHEN x.InPrev = 1 THEN 'fixed since last take' ELSE 'newly flagged' END AS Status,
       COUNT(*) AS Records
FROM run.v_TakeSequence AS s
CROSS APPLY (
    SELECT COALESCE(c.Module, p.Module) AS Module, COALESCE(c.RecordKey, p.RecordKey) AS RecordKey,
           CASE WHEN p.RecordKey IS NULL THEN 0 ELSE 1 END AS InPrev, CASE WHEN c.RecordKey IS NULL THEN 0 ELSE 1 END AS InCur
    FROM (SELECT DISTINCT i.Module, i.RecordKey FROM run.Issue AS i
          WHERE i.ClientId = s.ClientId AND i.TakeId = s.TakeId AND i.IsExpected = 0) AS c
    FULL OUTER JOIN
         (SELECT DISTINCT i.Module, i.RecordKey FROM run.Issue AS i
          WHERE i.ClientId = s.ClientId AND i.TakeId = s.PrevTakeId AND i.IsExpected = 0) AS p
      ON p.Module = c.Module AND p.RecordKey = c.RecordKey
) AS x
WHERE s.PrevTakeId IS NOT NULL
GROUP BY s.ClientId, s.TakeId, s.PrevTakeId, x.Module,
         CASE WHEN x.InPrev = 1 AND x.InCur = 1 THEN 'still flagged' WHEN x.InPrev = 1 THEN 'fixed since last take' ELSE 'newly flagged' END;
GO
