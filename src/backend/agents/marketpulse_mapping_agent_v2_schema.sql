-- MarketPulse Mapping Agent V2
-- Foundation schema only. No market_news/security_master rows are changed.
-- Safe to run repeatedly.

BEGIN;

CREATE TABLE IF NOT EXISTS security_identity (
    identity_id BIGSERIAL PRIMARY KEY,
    security_id BIGINT NOT NULL,
    identity_type VARCHAR(40) NOT NULL,
    identity_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    exchange VARCHAR(20),
    source VARCHAR(100) NOT NULL,
    confidence NUMERIC(6,5),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from DATE,
    valid_to DATE,
    evidence JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_security_identity_v2
        UNIQUE (security_id, identity_type, normalized_value, exchange)
);

CREATE INDEX IF NOT EXISTS idx_security_identity_v2_lookup
    ON security_identity (identity_type, normalized_value, exchange, is_active);

CREATE INDEX IF NOT EXISTS idx_security_identity_v2_security
    ON security_identity (security_id);

CREATE TABLE IF NOT EXISTS security_mapping_candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    news_id BIGINT NOT NULL,
    identity_group_key TEXT,
    candidate_security_id BIGINT NOT NULL,
    retrieval_method VARCHAR(80) NOT NULL,
    retrieval_rank INTEGER,
    retrieval_score NUMERIC(8,6),
    deterministic_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mapping_candidate_v2
        UNIQUE (run_id, news_id, candidate_security_id, retrieval_method)
);

CREATE INDEX IF NOT EXISTS idx_mapping_candidates_v2_news
    ON security_mapping_candidates (news_id);

CREATE INDEX IF NOT EXISTS idx_mapping_candidates_v2_run
    ON security_mapping_candidates (run_id);

CREATE INDEX IF NOT EXISTS idx_mapping_candidates_v2_security
    ON security_mapping_candidates (candidate_security_id);

CREATE TABLE IF NOT EXISTS security_mapping_decisions (
    decision_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    news_id BIGINT NOT NULL,
    identity_group_key TEXT,
    decision VARCHAR(30) NOT NULL,
    security_id BIGINT,
    confidence NUMERIC(8,6),
    reason TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_security_ids BIGINT[] NOT NULL DEFAULT '{}'::bigint[],
    agent_name VARCHAR(100),
    agent_version VARCHAR(50),
    model_name VARCHAR(150),
    prompt_version VARCHAR(50),
    requires_review BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING_REVIEW',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    reviewed_by VARCHAR(200),
    final_security_id BIGINT,
    review_outcome VARCHAR(30),
    CONSTRAINT uq_mapping_decision_v2
        UNIQUE (run_id, news_id)
);

CREATE INDEX IF NOT EXISTS idx_mapping_decisions_v2_news
    ON security_mapping_decisions (news_id);

CREATE INDEX IF NOT EXISTS idx_mapping_decisions_v2_status
    ON security_mapping_decisions (status);

CREATE INDEX IF NOT EXISTS idx_mapping_decisions_v2_group
    ON security_mapping_decisions (identity_group_key);

ALTER TABLE security_mapping_decisions
    ADD COLUMN IF NOT EXISTS final_security_id BIGINT;

ALTER TABLE security_mapping_decisions
    ADD COLUMN IF NOT EXISTS review_outcome VARCHAR(30);

CREATE INDEX IF NOT EXISTS idx_mapping_decisions_v2_review_outcome
    ON security_mapping_decisions (review_outcome);

COMMIT;
