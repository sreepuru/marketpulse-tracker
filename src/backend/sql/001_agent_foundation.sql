-- Additive Phase-1 tables. No changes to market_news/security_master.
-- pgvector is intentionally NOT required by this migration. Vector retrieval can be enabled later.

CREATE TABLE IF NOT EXISTS marketpulse_agent_runs (
    run_id UUID PRIMARY KEY,
    agent_name TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    mode TEXT NOT NULL DEFAULT 'SHADOW',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS marketpulse_agent_results (
    result_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES marketpulse_agent_runs(run_id),
    news_id BIGINT NOT NULL,
    identity_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    decision TEXT NOT NULL,
    predicted_security_id BIGINT,
    confidence NUMERIC(6,5),
    reason TEXT,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    contradictions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mp_agent_results_news ON marketpulse_agent_results(news_id);
CREATE INDEX IF NOT EXISTS idx_mp_agent_results_run ON marketpulse_agent_results(run_id);
CREATE INDEX IF NOT EXISTS idx_mp_agent_results_decision ON marketpulse_agent_results(decision);

CREATE TABLE IF NOT EXISTS marketpulse_agent_candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES marketpulse_agent_runs(run_id),
    news_id BIGINT NOT NULL,
    security_id BIGINT NOT NULL,
    retrieval_method TEXT NOT NULL,
    retrieval_score NUMERIC(8,6),
    retrieval_rank INTEGER,
    verification_decision TEXT,
    verification_confidence NUMERIC(6,5),
    verification_reason TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mp_agent_candidates_news ON marketpulse_agent_candidates(news_id);
CREATE INDEX IF NOT EXISTS idx_mp_agent_candidates_run ON marketpulse_agent_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_mp_agent_candidates_security ON marketpulse_agent_candidates(security_id);

CREATE TABLE IF NOT EXISTS marketpulse_agent_human_labels (
    label_id BIGSERIAL PRIMARY KEY,
    news_id BIGINT NOT NULL,
    agent_result_id BIGINT REFERENCES marketpulse_agent_results(result_id),
    human_decision TEXT NOT NULL,
    correct_security_id BIGINT,
    reason TEXT,
    reviewer TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mp_agent_labels_news ON marketpulse_agent_human_labels(news_id);
