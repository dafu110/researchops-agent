CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    document_id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'indexed',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    locator TEXT NOT NULL,
    text TEXT NOT NULL,
    terms TEXT[] NOT NULL DEFAULT '{}',
    embedding vector(384),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS text TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks(document_id);
CREATE INDEX IF NOT EXISTS chunks_tenant_idx ON chunks ((metadata->>'tenant_id'));
CREATE INDEX IF NOT EXISTS chunks_terms_gin_idx ON chunks USING gin(terms);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    user_id TEXT NOT NULL DEFAULT 'local-dev',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trace_steps (
    step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool JSONB NOT NULL,
    status TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    timeout_ms INTEGER NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT NOT NULL,
    cancellable BOOLEAN NOT NULL DEFAULT TRUE,
    recovery_action TEXT,
    output JSONB,
    error TEXT,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL,
    reviewer TEXT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    requester_id TEXT NOT NULL DEFAULT 'local-dev',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_records (
    audit_id TEXT PRIMARY KEY,
    run_id TEXT,
    actor_id TEXT NOT NULL DEFAULT 'local-dev',
    tenant_id TEXT NOT NULL DEFAULT 'default',
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE trace_steps DROP CONSTRAINT IF EXISTS trace_steps_run_id_fkey;
ALTER TABLE runs ALTER COLUMN run_id TYPE TEXT USING run_id::text;
ALTER TABLE trace_steps ALTER COLUMN step_id TYPE TEXT USING step_id::text;
ALTER TABLE trace_steps ALTER COLUMN run_id TYPE TEXT USING run_id::text;
ALTER TABLE approvals ALTER COLUMN approval_id TYPE TEXT USING approval_id::text;
ALTER TABLE approvals ALTER COLUMN run_id TYPE TEXT USING run_id::text;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-dev';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS answer TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS citations JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS plan_details JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS requires_approval BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS approval_id TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS corpus_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'evidence';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS require_citations BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS max_cost_usd DOUBLE PRECISION;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS final_answer JSONB;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE trace_steps ADD COLUMN IF NOT EXISTS input_payload JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE trace_steps ADD COLUMN IF NOT EXISTS output_payload JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE trace_steps ADD COLUMN IF NOT EXISTS model TEXT;
ALTER TABLE trace_steps ADD COLUMN IF NOT EXISTS token_usage JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE trace_steps ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS requester_id TEXT NOT NULL DEFAULT 'local-dev';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trace_steps_run_id_fkey'
    ) THEN
        ALTER TABLE trace_steps
            ADD CONSTRAINT trace_steps_run_id_fkey
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tool_calls_run_id_fkey'
    ) THEN
        ALTER TABLE tool_calls
            ADD CONSTRAINT tool_calls_run_id_fkey
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS runs_tenant_idx ON runs (tenant_id);
CREATE INDEX IF NOT EXISTS trace_steps_run_idx ON trace_steps (run_id, created_at);
CREATE INDEX IF NOT EXISTS tool_calls_run_idx ON tool_calls (run_id, created_at);
CREATE INDEX IF NOT EXISTS tool_calls_idempotency_idx ON tool_calls (run_id, idempotency_key, status);
CREATE INDEX IF NOT EXISTS approvals_run_action_idx ON approvals (run_id, action, tenant_id, status);
CREATE INDEX IF NOT EXISTS approvals_tenant_idx ON approvals (tenant_id);
CREATE INDEX IF NOT EXISTS audit_records_tenant_idx ON audit_records (tenant_id);
CREATE INDEX IF NOT EXISTS audit_records_run_idx ON audit_records (run_id);
CREATE INDEX IF NOT EXISTS audit_records_filters_idx ON audit_records (tenant_id, target, risk_level, status);
