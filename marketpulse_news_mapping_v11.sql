
-- SAFE FIRST PASS:
--   1. Adds mapping/scope columns.
--   2. Classifies obvious market/exchange notices.
--   3. Creates a candidate table for review.
--   4. Does NOT populate market_news.security_id.
--
-- Run once in PostgreSQL.

ALTER TABLE market_news
    ADD COLUMN IF NOT EXISTS news_scope VARCHAR(20),
    ADD COLUMN IF NOT EXISTS mapping_status VARCHAR(30),
    ADD COLUMN IF NOT EXISTS mapping_method VARCHAR(30),
    ADD COLUMN IF NOT EXISTS mapping_confidence NUMERIC(6,3);

CREATE INDEX IF NOT EXISTS idx_market_news_scope
    ON market_news(news_scope);

CREATE INDEX IF NOT EXISTS idx_market_news_mapping_status
    ON market_news(mapping_status);


-- Obvious market/exchange-level notices.
UPDATE market_news
SET
    news_scope = 'MARKET',
    mapping_status = 'NOT_APPLICABLE',
    mapping_method = 'NOTICE_RULE',
    mapping_confidence = 0.99
WHERE
    category = 'NOTICES'
    AND (
        title ~* '\b(SEBI turnover fees|settlement calendar|T-Bill|T-Bills|government securities|commercial paper|currency derivatives|commodity derivatives|electronic gold receipts|daily bulletin|margin reporting schedule)\b'
        OR title ~* '\bBSE\b.{0,60}\b(Index|IPO Index|notice|circular)\b'
        OR title ~* '\bSuspension of Trading\b'
    );


-- Generic BSE/NSE notices whose title does not identify a single stock.
UPDATE market_news
SET
    news_scope = 'MARKET',
    mapping_status = 'NOT_APPLICABLE',
    mapping_method = 'NOTICE_RULE',
    mapping_confidence = 0.95
WHERE
    category = 'NOTICES'
    AND news_scope IS NULL
    AND title IS NOT NULL
    AND title !~* '\b(?:Ltd|Limited|India|Industries|Corporation|Company|Finance|Bank|Pharma|Energy|Steel|Cement|Motors|Power|Technologies|Services|Enterprises)\b';


-- Other non-notice records start as stock candidates because they are
-- company/news feed records. They still require a real security match.
UPDATE market_news
SET
    news_scope = 'STOCK',
    mapping_status = 'PENDING'
WHERE news_scope IS NULL
  AND category <> 'NOTICES'
  AND company_name IS NOT NULL
  AND TRIM(company_name) <> '';


-- Remaining notices are not forced to a stock.
UPDATE market_news
SET
    news_scope = COALESCE(news_scope, 'UNKNOWN'),
    mapping_status = COALESCE(mapping_status, 'UNMAPPED')
WHERE news_scope IS NULL
   OR mapping_status IS NULL;


-- Candidate table: one news record can have multiple candidate securities,
-- but only candidates with the same exchange are generated.
CREATE TABLE IF NOT EXISTS market_news_security_candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    news_id BIGINT NOT NULL
        REFERENCES market_news(news_id)
        ON DELETE CASCADE,
    security_id BIGINT NOT NULL
        REFERENCES security_master(security_id)
        ON DELETE CASCADE,
    match_method VARCHAR(30) NOT NULL,
    match_confidence NUMERIC(6,3) NOT NULL,
    candidate_name TEXT,
    normalized_news_name TEXT,
    normalized_security_name TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(news_id, security_id, match_method)
);

CREATE INDEX IF NOT EXISTS idx_news_security_candidates_news
    ON market_news_security_candidates(news_id);

CREATE INDEX IF NOT EXISTS idx_news_security_candidates_security
    ON market_news_security_candidates(security_id);


-- NSE normalized-name candidates.
-- We strip common feed suffixes such as "- Ex-Date: ...".
-- We intentionally use equality after normalization; no fuzzy matching yet.
INSERT INTO market_news_security_candidates (
    news_id,
    security_id,
    match_method,
    match_confidence,
    candidate_name,
    normalized_news_name,
    normalized_security_name
)
SELECT
    mn.news_id,
    sm.security_id,
    'NORMALIZED_NAME',
    0.90,
    mn.company_name,
    n.normalized_name,
    s.normalized_name
FROM market_news mn
JOIN security_master sm
    ON sm.exchange = mn.exchange
   AND sm.is_active = TRUE
CROSS JOIN LATERAL (
    SELECT LOWER(
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    TRIM(mn.company_name),
                    '\s*-\s*Ex-Date\s*:\s*\d{1,2}[-/]\w+[-/]\d{2,4}\s*$',
                    '',
                    'i'
                ),
                '[^a-zA-Z0-9 ]',
                ' ',
                'g'
            ),
            '\s+',
            ' ',
            'g'
        )
    ) AS normalized_name
) n
CROSS JOIN LATERAL (
    SELECT LOWER(
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                TRIM(sm.instrument_name),
                '[^a-zA-Z0-9 ]',
                ' ',
                'g'
            ),
            '\s+',
            ' ',
            'g'
        )
    ) AS normalized_name
) s
WHERE mn.news_scope = 'STOCK'
  AND mn.exchange = 'NSE'
  AND n.normalized_name <> ''
  AND n.normalized_name = s.normalized_name
ON CONFLICT DO NOTHING;


-- Mark only unique normalized-name candidates as mapped.
-- This still does NOT overwrite security_id when more than one candidate exists.
WITH unique_candidates AS (
    SELECT
        news_id,
        MIN(security_id) AS security_id
    FROM market_news_security_candidates
    GROUP BY news_id
    HAVING COUNT(*) = 1
)
UPDATE market_news mn
SET
    security_id = uc.security_id,
    mapping_status = 'MAPPED',
    mapping_method = 'NORMALIZED_NAME',
    mapping_confidence = 0.90
FROM unique_candidates uc
WHERE mn.news_id = uc.news_id
  AND mn.security_id IS NULL;


-- Candidate records that were not uniquely resolved remain pending/ambiguous.
UPDATE market_news mn
SET mapping_status = CASE
    WHEN EXISTS (
        SELECT 1
        FROM market_news_security_candidates c
        WHERE c.news_id = mn.news_id
    )
    THEN 'AMBIGUOUS'
    ELSE mn.mapping_status
END
WHERE mn.security_id IS NULL
  AND mn.news_scope = 'STOCK';


-- Useful validation.
SELECT
    exchange,
    news_scope,
    mapping_status,
    COUNT(*) AS rows
FROM market_news
GROUP BY exchange, news_scope, mapping_status
ORDER BY exchange, news_scope, mapping_status;


SELECT
    exchange,
    COUNT(*) AS total_news,
    COUNT(*) FILTER (WHERE security_id IS NOT NULL) AS mapped,
    COUNT(*) FILTER (WHERE security_id IS NULL) AS unmapped
FROM market_news
GROUP BY exchange
ORDER BY exchange;