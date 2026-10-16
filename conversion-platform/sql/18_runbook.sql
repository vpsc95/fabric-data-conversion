/* =====================================================================
   18_runbook.sql: machine-readable conversion runbook and per-take execution state.
   Purpose: stores the generalized 54-step conversion execution sequence as metadata and
   records how a take progressed through the prototype runbook executor.
   Spec file: clients/<client>/runbook.yaml.
   Inputs: YAML runbook metadata, take id, run.RunLog, run.StepMetric and optional run.Gate.
   Outputs: meta.RunbookStep and run.RunbookStepRun rows used by generated integrity reports.
   Example: engine\runbook.py --target localdb --database CogsConvReport --client-dir clients\sample --take go-live.
   ===================================================================== */
SET NOCOUNT ON;

IF OBJECT_ID('meta.RunbookStep') IS NULL
CREATE TABLE meta.RunbookStep (
    ClientId      varchar(20)    NOT NULL,
    StepNo        int            NOT NULL,
    Block         char(1)        NOT NULL,
    Title         nvarchar(220)  NOT NULL,
    Kind          varchar(20)    NOT NULL,
    Executor      nvarchar(220)  NOT NULL,
    PrototypeMode varchar(20)    NOT NULL,
    CONSTRAINT PK_RunbookStep PRIMARY KEY (ClientId, StepNo),
    CONSTRAINT CK_RunbookStep_Block CHECK (Block IN ('A','B','C','D','E','F','G')),
    CONSTRAINT CK_RunbookStep_Kind CHECK (Kind IN ('automated','check','manual','approval')),
    CONSTRAINT CK_RunbookStep_PrototypeMode CHECK (PrototypeMode IN ('implemented','simulated','eliminated','manual'))
);

IF OBJECT_ID('run.RunbookStepRun') IS NULL
CREATE TABLE run.RunbookStepRun (
    ClientId  varchar(20)    NOT NULL,
    TakeId    varchar(20)    NOT NULL,
    StepNo    int            NOT NULL,
    Status    varchar(20)    NOT NULL,
    StartedAt datetime2(3)   NULL,
    EndedAt   datetime2(3)   NULL,
    Evidence  nvarchar(1000) NOT NULL CONSTRAINT DF_RunbookStepRun_Evidence DEFAULT N'',
    Message   nvarchar(1000) NOT NULL CONSTRAINT DF_RunbookStepRun_Message DEFAULT N'',
    CONSTRAINT PK_RunbookStepRun PRIMARY KEY (ClientId, TakeId, StepNo),
    CONSTRAINT CK_RunbookStepRun_Status CHECK (Status IN ('done','simulated','eliminated','waiting','skipped','failed'))
);
GO
