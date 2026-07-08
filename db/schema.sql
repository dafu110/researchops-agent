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
    run_id UUID PRIMARY KEY,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trace_steps (
    step_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id UUID PRIMARY KEY,
    run_id UUID,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL,
    reviewer TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
