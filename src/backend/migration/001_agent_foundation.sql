-- MarketPulse Agent Phase 1: additive foundation.
-- Run only after confirming the target PostgreSQL instance and pgvector availability.
-- This migration does NOT alter security_master or market_news and creates no automatic mappings.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS marketpulse_agent_runs (
    run_id UUID PRIMARY KEY,
    agent_name TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    max_steps INTEGER NOT NULL DEFAULT 3,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS marketpulse_agent_tasks (
    task_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES marketpulse_agent_runs(run_id),
    news_id BIGINT,
    task_type TEXT NOT NULL DEFAULT 'IDENTITY_RESEARCH',
    status TEXT NOT NULL DEFAULT 'PENDING',
    priority INTEGER NOT NULL DEFAULT 100,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_status_priority
    ON marketpulse_agent_tasks(status, priority, created_at);

CREATE TABLE IF NOT EXISTS marketpulse_agent_tool_calls (
    tool_call_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES marketpulse_agent_runs(run_id),
    task_id BIGINT REFERENCES marketpulse_agent_tasks(task_id),
    news_id BIGINT,
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    status TEXT NOT NULL,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marketpulse_agent_evidence (
    evidence_id BIGSERIAL PRIMARY KEY,
    run_id UUID REFERENCES marketpulse_agent_runs(run_id),
    task_id BIGINT REFERENCES marketpulse_agent_tasks(task_id),
    news_id BIGINT,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT,
    evidence_type TEXT NOT NULL,
    claim TEXT NOT NULL,
    supports_identity BOOLEAN,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_evidence_news ON marketpulse_agent_evidence(news_id);
CREATE INDEX IF NOT EXISTS idx_agent_evidence_type ON marketpulse_agent_evidence(evidence_type);
CREATE INDEX IF NOT EXISTS idx_agent_evidence_embedding_hnsw
    ON marketpulse_agent_evidence USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS marketpulse_agent_knowledge (
    knowledge_id BIGSERIAL PRIMARY KEY,
    knowledge_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    title TEXT,
    content TEXT NOT NULL,
    source_name TEXT,
    source_url TEXT,
    effective_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_knowledge_type ON marketpulse_agent_knowledge(knowledge_type);
CREATE INDEX IF NOT EXISTS idx_agent_knowledge_entity ON marketpulse_agent_knowledge(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_agent_knowledge_embedding_hnsw
    ON marketpulse_agent_knowledge USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS marketpulse_agent_decisions (
    decision_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES marketpulse_agent_runs(run_id),
    task_id BIGINT REFERENCES marketpulse_agent_tasks(task_id),
    news_id BIGINT,
    decision TEXT NOT NULL,
    security_id BIGINT,
    resolution_status TEXT NOT NULL,
    confidence NUMERIC(6,5),
    identity_continuity TEXT,
    reason TEXT NOT NULL,
    evidence_ids BIGINT[] NOT NULL DEFAULT '{}',
    requires_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_news ON marketpulse_agent_decisions(news_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_decision ON marketpulse_agent_decisions(decision);
