/* =====================================================================
   12_profile.sql: chain of custody and take profiles.
   run.Take           every take received, with its date (take-over-take order)
   run.LandingFile    every received file with size and SHA-256, recorded before anything reads it;
                      the reshape step re-checks the hashes, so a take is processed exactly as received.
   run.ColumnProfile  per-column statistics, metadata only: inferred type, blanks, distinct values,
                      lengths, value shapes, and how many codes a code-like column carries.
   run.TakeProfile    the whole profile document (drift compares it with the client's previous take).
   run.DriftFinding   what the approved specs need but did not arrive, and what changed since the
                      previous take; a blocking finding means gate 1 (a spec change) is required.
   ===================================================================== */
SET NOCOUNT ON;
IF OBJECT_ID('run.Take') IS NULL
CREATE TABLE run.Take (                            -- every take the platform has received, in take-date order
    ClientId      varchar(20)    NOT NULL,
    TakeId        varchar(20)    NOT NULL,
    TakeDate      date           NOT NULL,
    Simulated     bit            NOT NULL CONSTRAINT DF_Take_Simulated DEFAULT 0,
    RegisteredAt  datetime2(3)   NOT NULL CONSTRAINT DF_Take_RegisteredAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Take PRIMARY KEY (ClientId, TakeId)
);
IF OBJECT_ID('run.LandingFile') IS NULL
CREATE TABLE run.LandingFile (
    ClientId      varchar(20)    NOT NULL,
    TakeId        varchar(20)    NOT NULL,
    FileName      nvarchar(260)  NOT NULL,
    SizeBytes     bigint         NOT NULL,
    Sha256        char(64)       NOT NULL,
    ModifiedUtc   datetime2(0)   NULL,
    SpecId        varchar(60)    NULL,
    Sheets        nvarchar(1000) NOT NULL CONSTRAINT DF_LandingFile_Sheets DEFAULT N'',
    RecordedAt    datetime2(3)   NOT NULL CONSTRAINT DF_LandingFile_RecordedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_LandingFile PRIMARY KEY (ClientId, TakeId, FileName)
);
IF OBJECT_ID('run.ColumnProfile') IS NULL
CREATE TABLE run.ColumnProfile (
    ClientId      varchar(20)    NOT NULL,
    TakeId        varchar(20)    NOT NULL,
    FileName      nvarchar(260)  NOT NULL,
    SheetName     nvarchar(128)  NOT NULL,
    Position      int            NOT NULL,
    ColumnName    nvarchar(128)  NOT NULL,
    Sanitized     varchar(128)   NOT NULL,
    InferredType  varchar(20)    NOT NULL,
    RowsRead      int            NOT NULL,
    BlankCount    int            NOT NULL,
    DistinctCount int            NOT NULL,
    MinLen        int            NOT NULL,
    MaxLen        int            NOT NULL,
    Shapes        nvarchar(400)  NOT NULL CONSTRAINT DF_ColumnProfile_Shapes DEFAULT N'',
    CodeCount     int            NULL,               -- distinct codes when the column is a code set, else NULL
    CONSTRAINT PK_ColumnProfile PRIMARY KEY (ClientId, TakeId, FileName, SheetName, Position)
);
IF OBJECT_ID('run.TakeProfile') IS NULL
CREATE TABLE run.TakeProfile (
    ClientId      varchar(20)    NOT NULL,
    TakeId        varchar(20)    NOT NULL,
    ProfileJson   nvarchar(max)  NOT NULL,
    CreatedAt     datetime2(3)   NOT NULL CONSTRAINT DF_TakeProfile_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_TakeProfile PRIMARY KEY (ClientId, TakeId)
);
IF OBJECT_ID('run.DriftFinding') IS NULL
CREATE TABLE run.DriftFinding (
    FindingId     bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_DriftFinding PRIMARY KEY,
    ClientId      varchar(20)    NOT NULL,
    TakeId        varchar(20)    NOT NULL,
    Kind          varchar(40)    NOT NULL,
    Severity      varchar(10)    NOT NULL CONSTRAINT CK_DriftFinding_Severity CHECK (Severity IN ('blocking', 'warning', 'info')),
    FileName      nvarchar(260)  NULL,
    ColumnName    nvarchar(128)  NULL,
    Detail        nvarchar(1000) NOT NULL,
    ComparedTo    varchar(20)    NULL,               -- previous take, or NULL for checks against the specs
    CreatedAt     datetime2(3)   NOT NULL CONSTRAINT DF_DriftFinding_CreatedAt DEFAULT SYSUTCDATETIME()
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_DriftFinding_Take' AND object_id = OBJECT_ID('run.DriftFinding'))
CREATE INDEX IX_DriftFinding_Take ON run.DriftFinding (ClientId, TakeId, Severity);
GO
