CREATE TABLE IF NOT EXISTS shared.pipeline_lessons (
    id             SERIAL PRIMARY KEY,
    batch          VARCHAR(100),
    country        VARCHAR(100),
    stage          VARCHAR(30) NOT NULL,
    field          VARCHAR(50),
    pattern        TEXT NOT NULL,
    why_it_matters TEXT,
    what_to_do     TEXT NOT NULL,
    example_before TEXT,
    example_after  TEXT,
    is_active      BOOLEAN DEFAULT true,
    version        INTEGER DEFAULT 1,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_lessons_stage
    ON shared.pipeline_lessons(stage) WHERE is_active = true;
