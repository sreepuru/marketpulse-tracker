"""
MarketPulse - Mapping Agent V2 Foundation

Purpose
-------
Build candidate identities for unresolved STOCK news before any LLM reasoning.

Design
------
1. security_master remains the canonical source of truth.
2. Existing deterministic mapper is not replaced by this file.
3. This module groups recurring unresolved identities.
4. Candidate retrieval is bounded to a small set per identity.
5. No fuzzy auto-mapping and no writes to market_news/security_master.
6. Candidate persistence requires explicit --persist-candidates.
7. --init creates only the V2 agent tables.
8. LangGraph/LLM reasoning is intentionally a later stage; this first
   implementation establishes and audits the identity/candidate layer.

Candidate retrieval
-------------------
- persisted security_identity exact identity
- same-exchange exact normalized name
- exact historical/identity retrieval
- unique exact-name fallback
- conservative token retrieval for multi-token names
- candidate cap per identity

The candidate engine is deliberately deterministic. Splink will be used in
the next stage to score the bounded candidate set rather than comparing every
news event with every security.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from difflib import SequenceMatcher

from backend.agents.vector_candidate_verifier import (
    retrieve_and_verify_vector_candidates,
)

import psycopg2
from dotenv import load_dotenv


ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
load_dotenv(os.path.join(ROOT, ".env"))

AGENT_NAME = "MarketPulse-Mapping-Agent-V2"
AGENT_VERSION = "0.1.0"
SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "marketpulse_mapping_agent_v2_schema.sql")

# The schema is normally kept beside this script. If the standalone .py file
# is copied without the .sql companion, use the embedded schema so --init
# remains self-contained.
EMBEDDED_SCHEMA = "-- MarketPulse Mapping Agent V2\n-- Foundation schema only. No market_news/security_master rows are changed.\n-- Safe to run repeatedly.\n\nBEGIN;\n\nCREATE TABLE IF NOT EXISTS security_identity (\n    identity_id BIGSERIAL PRIMARY KEY,\n    security_id BIGINT NOT NULL,\n    identity_type VARCHAR(40) NOT NULL,\n    identity_value TEXT NOT NULL,\n    normalized_value TEXT NOT NULL,\n    exchange VARCHAR(20),\n    source VARCHAR(100) NOT NULL,\n    confidence NUMERIC(6,5),\n    is_active BOOLEAN NOT NULL DEFAULT TRUE,\n    valid_from DATE,\n    valid_to DATE,\n    evidence JSONB,\n    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    CONSTRAINT uq_security_identity_v2\n        UNIQUE (security_id, identity_type, normalized_value, exchange)\n);\n\nCREATE INDEX IF NOT EXISTS idx_security_identity_v2_lookup\n    ON security_identity (identity_type, normalized_value, exchange, is_active);\n\nCREATE INDEX IF NOT EXISTS idx_security_identity_v2_security\n    ON security_identity (security_id);\n\nCREATE TABLE IF NOT EXISTS security_mapping_candidates (\n    candidate_id BIGSERIAL PRIMARY KEY,\n    run_id UUID NOT NULL,\n    news_id BIGINT NOT NULL,\n    identity_group_key TEXT,\n    candidate_security_id BIGINT NOT NULL,\n    retrieval_method VARCHAR(80) NOT NULL,\n    retrieval_rank INTEGER,\n    retrieval_score NUMERIC(8,6),\n    deterministic_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,\n    candidate_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,\n    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    CONSTRAINT uq_mapping_candidate_v2\n        UNIQUE (run_id, news_id, candidate_security_id, retrieval_method)\n);\n\nCREATE INDEX IF NOT EXISTS idx_mapping_candidates_v2_news\n    ON security_mapping_candidates (news_id);\n\nCREATE INDEX IF NOT EXISTS idx_mapping_candidates_v2_run\n    ON security_mapping_candidates (run_id);\n\nCREATE INDEX IF NOT EXISTS idx_mapping_candidates_v2_security\n    ON security_mapping_candidates (candidate_security_id);\n\nCREATE TABLE IF NOT EXISTS security_mapping_decisions (\n    decision_id BIGSERIAL PRIMARY KEY,\n    run_id UUID NOT NULL,\n    news_id BIGINT NOT NULL,\n    identity_group_key TEXT,\n    decision VARCHAR(30) NOT NULL,\n    security_id BIGINT,\n    confidence NUMERIC(8,6),\n    reason TEXT,\n    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,\n    candidate_security_ids BIGINT[] NOT NULL DEFAULT '{}'::bigint[],\n    agent_name VARCHAR(100),\n    agent_version VARCHAR(50),\n    model_name VARCHAR(150),\n    prompt_version VARCHAR(50),\n    requires_review BOOLEAN NOT NULL DEFAULT TRUE,\n    status VARCHAR(30) NOT NULL DEFAULT 'PENDING_REVIEW',\n    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    reviewed_at TIMESTAMP,\n    reviewed_by VARCHAR(200),\n    CONSTRAINT uq_mapping_decision_v2\n        UNIQUE (run_id, news_id)\n);\n\nCREATE INDEX IF NOT EXISTS idx_mapping_decisions_v2_news\n    ON security_mapping_decisions (news_id);\n\nCREATE INDEX IF NOT EXISTS idx_mapping_decisions_v2_status\n    ON security_mapping_decisions (status);\n\nCREATE INDEX IF NOT EXISTS idx_mapping_decisions_v2_group\n    ON security_mapping_decisions (identity_group_key);\n\n\nCREATE TABLE IF NOT EXISTS marketpulse_historical_identity_evidence (\n    evidence_id BIGSERIAL PRIMARY KEY,\n    identity_group_key TEXT NOT NULL,\n    exchange VARCHAR(20),\n    historical_symbol TEXT,\n    historical_company_name TEXT,\n    historical_isin TEXT,\n    historical_bse_code TEXT,\n    evidence_source VARCHAR(200) NOT NULL,\n    evidence_url TEXT,\n    evidence_status VARCHAR(40) NOT NULL DEFAULT 'RESEARCH_REQUIRED',\n    canonical_security_id BIGINT,\n    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,\n    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    CONSTRAINT uq_historical_identity_evidence_v2\n        UNIQUE (\n            identity_group_key,\n            historical_symbol,\n            historical_isin,\n            evidence_source\n        )\n);\n\nCREATE INDEX IF NOT EXISTS idx_historical_identity_evidence_v2_group\n    ON marketpulse_historical_identity_evidence (identity_group_key);\n\nCREATE INDEX IF NOT EXISTS idx_historical_identity_evidence_v2_symbol\n    ON marketpulse_historical_identity_evidence (historical_symbol);\n\nCREATE INDEX IF NOT EXISTS idx_historical_identity_evidence_v2_canonical\n    ON marketpulse_historical_identity_evidence (canonical_security_id);\n\nCREATE TABLE IF NOT EXISTS marketpulse_issuer_identity (\n    issuer_id BIGSERIAL PRIMARY KEY,\n    normalized_issuer_name TEXT NOT NULL,\n    issuer_name TEXT NOT NULL,\n    issuer_type VARCHAR(40) NOT NULL DEFAULT 'ISSUER',\n    evidence_source VARCHAR(200),\n    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,\n    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    CONSTRAINT uq_marketpulse_issuer_identity_v2\n        UNIQUE (normalized_issuer_name)\n);\n\nCREATE INDEX IF NOT EXISTS idx_marketpulse_issuer_identity_v2_name\n    ON marketpulse_issuer_identity (normalized_issuer_name);\n\nCOMMIT;\n"

IDENTITY_TYPES = {
    "NAME",
    "ALIAS",
    "HISTORICAL_NAME",
    "SYMBOL",
    "HISTORICAL_SYMBOL",
    "ISIN",
    "BSE_CODE",
}

# ---------------------------------------------------------------------------
# Candidate diagnostics
# ---------------------------------------------------------------------------

CANDIDATE_EXACT_ENTITY = "EXACT_ENTITY"
CANDIDATE_ISSUER_FAMILY = "ISSUER_FAMILY"
CANDIDATE_INSTRUMENT_FAMILY = "INSTRUMENT_FAMILY"
CANDIDATE_TOKEN_OVERLAP = "TOKEN_OVERLAP"
CANDIDATE_ACRONYM_OVERLAP = "ACRONYM_OVERLAP"
CANDIDATE_CROSS_EXCHANGE = "CROSS_EXCHANGE"

STATUS_STRONG_CANDIDATE = "STRONG_CANDIDATE"
STATUS_FAMILY_CANDIDATE = "FAMILY_CANDIDATE"
STATUS_WEAK_CANDIDATE = "WEAK_CANDIDATE"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_FALSE_POSITIVE = "FALSE_POSITIVE"

STATUS_EXACT_CANONICAL = "EXACT_CANONICAL"
STATUS_CANONICAL_CANDIDATE = "CANONICAL_CANDIDATE"
STATUS_ISSUER_FAMILY = "ISSUER_FAMILY"
STATUS_INSTRUMENT_FAMILY = "INSTRUMENT_FAMILY"
STATUS_HISTORICAL_EVIDENCE = "HISTORICAL_EVIDENCE"
STATUS_WEAK_RETRIEVAL = "WEAK_RETRIEVAL"
STATUS_RESEARCH_REQUIRED = "RESEARCH_REQUIRED"
STATUS_NO_CANONICAL_MATCH = "NO_CANONICAL_MATCH"


IDENTITY_HISTORICAL_SYMBOL = "HISTORICAL_SYMBOL"
IDENTITY_ISSUER_NAME = "ISSUER_NAME"
IDENTITY_SPECIFIC_INSTRUMENT = "SPECIFIC_INSTRUMENT"
IDENTITY_COMPANY_NAME = "COMPANY_NAME"

GENERIC_ISSUER_TOKENS = {
    "ASSET",
    "MANAGEMENT",
    "COMPANY",
    "LIMITED",
    "PRIVATE",
    "PUBLIC",
    "MUTUAL",
    "FUND",
    "AMC",
    "LIFE",
    "INVESTMENT",
    "MANAGERS",
    "MANAGER",
}

GENERIC_COMPANY_TOKENS = {
    "LIMITED",
    "LTD",
    "PRIVATE",
    "PVT",
    "PUBLIC",
    "PUB",
    "COMPANY",
    "CO",
    "CORPORATION",
    "CORP",
    "INDIA",
    "INDIAN",
    "INC",
    "PLC",

    "DEVELOPMENT",
    "DEVELOPMENTS",
    "ENTERPRISE",
    "ENTERPRISES",
    "INDUSTRIES",
    "INDUSTRIAL",
    "INDUSTRIALS",
    "SERVICES",
    "SERVICE",
    "SOLUTIONS",
    "SYSTEMS",
    "SYSTEM",
    "TECHNOLOGIES",
    "TECHNOLOGY",
    "INFRA",
    "INFRASTRUCTURE",
    "PROJECTS",
    "PROJECT",
    "HOLDINGS",
    "GROUP",
    "GLOBAL",
    "INTERNATIONAL",
}

GENERIC_INSTRUMENT_TOKENS = {
    "FUND",
    "INTERVAL",
    "DIRECT",
    "REGULAR",
    "GROWTH",
    "DIVIDEND",
    "PAYOUT",
    "PLAN",
    "OPTION",
    "SERIES",
    "ISSUE",
    "PRICE",
    "ETF",
}


STOPWORDS = {
    "THE", "AND", "OF", "FOR", "IN", "ON", "AT",
    "LIMITED", "LTD", "PRIVATE", "PVT", "PUBLIC", "PUB",
    "COMPANY", "CO", "CORPORATION", "CORP", "INDIA",
    "INDIAN", "INC", "PLC",
}


@dataclass(frozen=True)
class Security:
    security_id: int
    isin: Optional[str]
    symbol: Optional[str]
    instrument_name: Optional[str]
    exchange: Optional[str]
    nse_symbol: Optional[str]
    nse_name: Optional[str]
    nse_short_name: Optional[str]
    nse_alias: Optional[str]
    bse_symbol: Optional[str]
    bse_name: Optional[str]
    bse_short_name: Optional[str]
    bse_alias: Optional[str]
    bse_scrip_code: Optional[str]
    exchange_tag: Optional[str]
    asset_category: Optional[str]
    is_active: bool


@dataclass(frozen=True)
class IdentityGroup:
    group_key: str
    company_name: str
    normalized_name: str
    exchange: str
    symbol: str
    isin: str
    news_ids: Tuple[int, ...]
    sample_title: str


@dataclass
class Candidate:
    security_id: int
    method: str
    score: float
    evidence: str

    # Candidate diagnostics.
    # These describe WHY the candidate was retrieved.
    candidate_type: str = "UNKNOWN"
    matched_field: str = ""
    match_reason: str = ""

    # Review classification is deliberately separate from retrieval score.
    # Retrieval score is NOT mapping confidence.
    candidate_status: str = "NEEDS_REVIEW"


def connect():
    password = os.getenv("MARKETPULSE_DB_PASSWORD")
    if password is None:
        raise RuntimeError("MARKETPULSE_DB_PASSWORD is not set")

    return psycopg2.connect(
        host=os.getenv("MARKETPULSE_DB_HOST", "localhost"),
        port=int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
        dbname=os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
        user=os.getenv("MARKETPULSE_DB_USER", "postgres"),
        password=password,
    )


def normalize(value: Optional[str]) -> str:
    if value is None:
        return ""
    value = str(value).upper().strip()
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_symbol(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize(value))


def normalize_isin(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize(value))


def meaningful_tokens(value: str) -> Tuple[str, ...]:
    tokens = [
        t for t in normalize(value).split()
        if len(t) >= 3 and t not in STOPWORDS
    ]
    return tuple(dict.fromkeys(tokens))


def acronym(value: str) -> str:
    tokens = meaningful_tokens(value)
    return "".join(t[0] for t in tokens if t)

# ---------------------------------------------------------------
# 8. Conservative name-similarity retrieval
# ---------------------------------------------------------------

def name_similarity(left: str, right: str) -> float:
    left_normalized = normalize(left)
    right_normalized = normalize(right)

    if not left_normalized or not right_normalized:
        return 0.0

    return SequenceMatcher(
        None,
        left_normalized,
        right_normalized,
    ).ratio()

def identity_group_key(exchange: str, normalized_name: str, symbol: str, isin: str) -> str:
    # Strong identifiers get their own group key. Otherwise group recurring
    # company identities by exchange + normalized name.
    if isin:
        return f"ISIN:{isin}"
    if symbol:
        return f"{exchange}:SYMBOL:{symbol}"
    return f"{exchange}:NAME:{normalized_name}"


def load_securities(conn) -> List[Security]:
    sql = """
    SELECT
        security_id,
        isin,
        symbol,
        instrument_name,
        exchange,
        nse_symbol,
        nse_name,
        nse_short_name,
        nse_alias,
        bse_symbol,
        bse_name,
        bse_short_name,
        bse_alias,
        bse_scrip_code,
        exchange_tag,
        asset_category,
        is_active
    FROM security_master
    WHERE is_active = TRUE
    ORDER BY security_id
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        return [Security(*row) for row in cur.fetchall()]


def load_identity_groups(
    conn,
    limit_groups: Optional[int] = None,
) -> List[IdentityGroup]:
    """
    Load unresolved STOCK events and collapse recurring identities.

    We deliberately do not classify or remap anything here.
    """
    sql = """
    SELECT
        news_id,
        COALESCE(exchange, ''),
        COALESCE(symbol, ''),
        COALESCE(company_name, ''),
        COALESCE(title, '')
    FROM market_news
    WHERE news_scope = 'STOCK'
      AND (mapping_status IS DISTINCT FROM 'MAPPED' OR security_id IS NULL)
    ORDER BY news_id
    """

    groups: Dict[str, dict] = {}

    with conn.cursor() as cur:
        cur.execute(sql)
        for news_id, exchange, symbol, company_name, title in cur.fetchall():
            exchange = normalize(exchange)
            symbol = normalize_symbol(symbol)
            normalized_name = normalize(company_name)
            # market_news does not carry an ISIN column in the current schema.
            # ISIN remains available from security_master and the persisted
            # security_identity layer; it is not inferred from news here.
            isin = ""

            # A completely empty identity should not be sent to an agent.
            if not normalized_name and not symbol and not isin:
                continue

            key = identity_group_key(
                exchange,
                normalized_name,
                symbol,
                isin,
            )

            if key not in groups:
                groups[key] = {
                    "company_name": company_name.strip(),
                    "normalized_name": normalized_name,
                    "exchange": exchange,
                    "symbol": symbol,
                    "isin": isin,
                    "news_ids": [],
                    "sample_title": title.strip(),
                }

            groups[key]["news_ids"].append(int(news_id))

    items = [
        IdentityGroup(
            group_key=key,
            company_name=value["company_name"],
            normalized_name=value["normalized_name"],
            exchange=value["exchange"],
            symbol=value["symbol"],
            isin=value["isin"],
            news_ids=tuple(value["news_ids"]),
            sample_title=value["sample_title"],
        )
        for key, value in groups.items()
    ]

    items.sort(key=lambda x: (-len(x.news_ids), x.group_key))

    if limit_groups is not None:
        items = items[:limit_groups]

    return items


def build_indexes(securities: Sequence[Security]):
    by_id = {s.security_id: s for s in securities}

    exact_name = defaultdict(list)
    exact_name_any = defaultdict(list)
    exact_isin = defaultdict(list)
    exact_symbol_nse = defaultdict(list)
    exact_symbol_bse = defaultdict(list)
    exact_bse_code = defaultdict(list)
    token_index = defaultdict(set)
    acronym_index = defaultdict(set)

    for sec in securities:
        if sec.isin:
            exact_isin[normalize_isin(sec.isin)].append(sec.security_id)

        values = [
            (sec.nse_name, "NSE"),
            (sec.bse_name, "BSE"),
            (sec.nse_short_name, "NSE"),
            (sec.bse_short_name, "BSE"),
            (sec.nse_alias, "NSE"),
            (sec.bse_alias, "BSE"),
            (sec.instrument_name, normalize(sec.exchange_tag or "")),
        ]

        for value, exchange in values:
            key = normalize(value)
            if not key:
                continue
            exact_name[(exchange, key)].append(sec.security_id)
            exact_name_any[key].append(sec.security_id)

            for token in meaningful_tokens(key):
                token_index[token].add(sec.security_id)

            ac = acronym(key)
            if len(ac) >= 2:
                acronym_index[ac].add(sec.security_id)

        if sec.nse_symbol:
            exact_symbol_nse[normalize_symbol(sec.nse_symbol)].append(sec.security_id)

        if sec.bse_symbol:
            exact_symbol_bse[normalize_symbol(sec.bse_symbol)].append(sec.security_id)

        canonical_symbol = normalize_symbol(sec.symbol)
        exchange_tag = normalize(sec.exchange_tag)
        exchange = normalize(sec.exchange)

        if canonical_symbol and (
            exchange == "NSE" or exchange_tag in {"NSE", "BOTH"}
        ):
            exact_symbol_nse[canonical_symbol].append(sec.security_id)

        if canonical_symbol and (
            exchange == "BSE" or exchange_tag in {"BSE", "BOTH"}
        ):
            exact_symbol_bse[canonical_symbol].append(sec.security_id)

        if sec.bse_scrip_code:
            exact_bse_code[normalize_symbol(sec.bse_scrip_code)].append(
                sec.security_id
            )

    return {
        "by_id": by_id,
        "exact_name": exact_name,
        "exact_name_any": exact_name_any,
        "exact_isin": exact_isin,
        "exact_symbol_nse": exact_symbol_nse,
        "exact_symbol_bse": exact_symbol_bse,
        "exact_bse_code": exact_bse_code,
        "token_index": token_index,
        "acronym_index": acronym_index,
    }


def load_persisted_identity_candidates(conn, group: IdentityGroup):
    """
    Read only confirmed active identities.

    security_identity is an identity/index layer; security_master remains
    authoritative for the actual security record.
    """
    values = [
        group.normalized_name,
        group.symbol,
        group.isin,
    ]

    sql = """
    SELECT DISTINCT security_id, identity_type, normalized_value, exchange
    FROM security_identity
    WHERE is_active = TRUE
      AND normalized_value = ANY(%s)
    """

    result = []

    with conn.cursor() as cur:
        cur.execute(sql, ([v for v in values if v],))
        for row in cur.fetchall():
            result.append(row)

    return result


def build_candidate_diagnostics(method: str, evidence: dict) -> Tuple[str, str, str]:
    """Describe retrieval evidence; does not determine mapping correctness."""
    m = (method or "").upper()
    if m == "EXACT_ISIN":
        return CANDIDATE_EXACT_ENTITY, "isin", "Exact ISIN match."
    if m == "EXACT_EXCHANGE_SYMBOL":
        return CANDIDATE_EXACT_ENTITY, "symbol", "Exact exchange symbol match."
    if m == "PERSISTED_IDENTITY":
        return CANDIDATE_EXACT_ENTITY, "security_identity", "Confirmed persisted security identity."
    if m == "EXACT_EXCHANGE_NAME":
        return CANDIDATE_EXACT_ENTITY, "company_name", "Exact normalized name on the same exchange."
    if m in {"EXACT_NAME_ANY_EXCHANGE", "EXACT_NAME_AMBIGUOUS"}:
        return CANDIDATE_CROSS_EXCHANGE, "company_name", "Exact normalized name across exchange representation."
    if "TOKEN" in m:
        matched = evidence.get("matched_tokens")
        tokens = evidence.get("query_tokens") or []
        reason = f"Token overlap: {matched}/{len(tokens)} meaningful query tokens matched." if matched is not None else "Candidate retrieved through token overlap."
        return CANDIDATE_TOKEN_OVERLAP, "instrument_name", reason
    if "ACRONYM" in m:
        return CANDIDATE_ACRONYM_OVERLAP, "acronym", "Candidate retrieved through acronym overlap."
    return "UNKNOWN", "", "Candidate retrieved by deterministic candidate engine."


def classify_candidate(candidate: Candidate) -> str:
    """Classify retrieval evidence conservatively; not a mapping verdict."""
    if candidate.candidate_type == CANDIDATE_EXACT_ENTITY:
        return STATUS_STRONG_CANDIDATE
    if candidate.candidate_type in (CANDIDATE_ISSUER_FAMILY, CANDIDATE_INSTRUMENT_FAMILY):
        return STATUS_FAMILY_CANDIDATE
    if candidate.candidate_type in (CANDIDATE_TOKEN_OVERLAP, CANDIDATE_ACRONYM_OVERLAP):
        return STATUS_WEAK_CANDIDATE
    return STATUS_NEEDS_REVIEW


def classify_identity_group(group: IdentityGroup) -> str:
    """
    Classify the unresolved identity before candidate retrieval.

    This is intentionally conservative. It controls retrieval strategy only;
    it does not establish the canonical security.
    """
    if group.symbol:
        return IDENTITY_HISTORICAL_SYMBOL

    name = normalize(group.normalized_name)
    tokens = set(meaningful_tokens(name))

    if (
        "AMC" in tokens
        or "ASSET MANAGEMENT" in name
        or "ASSET MANAGERS" in name
        or "FUNDS MANAGEMENT" in name
        or "INVESTMENT MANAGERS" in name
    ):
        return IDENTITY_ISSUER_NAME

    if tokens & GENERIC_INSTRUMENT_TOKENS:
        return IDENTITY_SPECIFIC_INSTRUMENT

    return IDENTITY_COMPANY_NAME


def distinctive_tokens(value: str, identity_type: str) -> Tuple[str, ...]:
    tokens = meaningful_tokens(value)

    if identity_type == IDENTITY_ISSUER_NAME:
        excluded = GENERIC_ISSUER_TOKENS
    elif identity_type == IDENTITY_SPECIFIC_INSTRUMENT:
        excluded = GENERIC_INSTRUMENT_TOKENS
    elif identity_type == IDENTITY_COMPANY_NAME:
        excluded = GENERIC_COMPANY_TOKENS
    else:
        excluded = set()

    return tuple(
        token
        for token in tokens
        if token not in excluded
    )



def candidate_resolution_status(
    candidate: Candidate,
    group: IdentityGroup,
    security: Security,
) -> str:
    """Assign an evidence-oriented review status, never an auto-map decision."""
    method = (candidate.method or "").upper()

    if method in {
        "EXACT_ISIN",
        "EXACT_EXCHANGE_SYMBOL",
        "PERSISTED_IDENTITY",
    }:
        return STATUS_EXACT_CANONICAL

    if method == "EXACT_NAME_ANY_EXCHANGE":
        if (security.asset_category or "").upper() == "EQUITY":
            return STATUS_CANONICAL_CANDIDATE
        return STATUS_RESEARCH_REQUIRED

    if method == "EXACT_EXCHANGE_NAME":
        if group.symbol:
            return STATUS_CANONICAL_CANDIDATE
        return STATUS_RESEARCH_REQUIRED

    if method == "NAME_SIMILARITY_RETRIEVAL":
        return STATUS_RESEARCH_REQUIRED

    if candidate.candidate_type == CANDIDATE_ISSUER_FAMILY:
        return STATUS_ISSUER_FAMILY

    if candidate.candidate_type == CANDIDATE_INSTRUMENT_FAMILY:
        return STATUS_INSTRUMENT_FAMILY

    if candidate.candidate_type in (
        CANDIDATE_TOKEN_OVERLAP,
        CANDIDATE_ACRONYM_OVERLAP,
    ):
        return STATUS_WEAK_RETRIEVAL

    return STATUS_RESEARCH_REQUIRED


def retrieve_candidates(
    conn,
    group: IdentityGroup,
    indexes,
    max_candidates: int = 20,
) -> List[Candidate]:
    by_id = indexes["by_id"]
    candidates: Dict[int, Candidate] = {}
    identity_type = classify_identity_group(group)

    def add(
        security_id: int,
        method: str,
        score: float,
        evidence: dict,
    ):
        sec = by_id.get(security_id)
        if sec is None:
            return

        # Exchange compatibility is evidence, not a blind hard filter for
        # historical identities. Strong identifiers are allowed to bridge
        # current exchange representation.
        evidence = dict(evidence)
        evidence.setdefault("identity_type", identity_type)

        candidate_type, matched_field, match_reason = build_candidate_diagnostics(method, evidence)

        # Retrieval method alone cannot tell us whether a token match is a
        # company/entity candidate, issuer-family candidate, or instrument-
        # family candidate. The identity class supplies that context.
        if "TOKEN" in (method or "").upper():
            if identity_type == IDENTITY_ISSUER_NAME:
                candidate_type = CANDIDATE_ISSUER_FAMILY
                matched_field = "issuer_tokens"
                match_reason = "Issuer-family candidate retrieved from distinctive issuer tokens."
            elif identity_type == IDENTITY_SPECIFIC_INSTRUMENT:
                candidate_type = CANDIDATE_INSTRUMENT_FAMILY
                matched_field = "instrument_tokens"
                match_reason = "Instrument-family candidate retrieved from distinctive instrument tokens."
        existing = candidates.get(security_id)

        if existing is None or score > existing.score:
            candidates[security_id] = Candidate(
                security_id=security_id,
                method=method,
                score=score,
                evidence=evidence,
                candidate_type=candidate_type,
                matched_field=matched_field,
                match_reason=match_reason,
                candidate_status=STATUS_NEEDS_REVIEW,
            )

    # ---------------------------------------------------------------
    # 1. Persisted identity layer
    # ---------------------------------------------------------------
    for security_id, identity_type, normalized_value, exchange in (
        load_persisted_identity_candidates(conn, group)
    ):
        add(
            security_id,
            "PERSISTED_IDENTITY",
            1.00,
            {
                "identity_type": identity_type,
                "normalized_value": normalized_value,
                "exchange": exchange,
            },
        )

    # ---------------------------------------------------------------
    # 2. Exact ISIN
    # ---------------------------------------------------------------
    if group.isin:
        for sid in indexes["exact_isin"].get(group.isin, []):
            add(
                sid,
                "EXACT_ISIN",
                1.00,
                {"isin": group.isin},
            )

    # ---------------------------------------------------------------
    # 3. Exact exchange symbol
    # ---------------------------------------------------------------
    if group.symbol:
        symbol_index = (
            indexes["exact_symbol_nse"]
            if group.exchange == "NSE"
            else indexes["exact_symbol_bse"]
            if group.exchange == "BSE"
            else {}
        )

        for sid in symbol_index.get(group.symbol, []):
            add(
                sid,
                "EXACT_EXCHANGE_SYMBOL",
                0.98,
                {
                    "exchange": group.exchange,
                    "symbol": group.symbol,
                },
            )

    # ---------------------------------------------------------------
    # 4. Exact BSE code only when supplied as a real group identity.
    # The caller can add title-code extraction later; six-digit title
    # numbers are not assumed to be BSE equity codes.
    # ---------------------------------------------------------------

    # ---------------------------------------------------------------
    # 5. Exact same-exchange name
    # ---------------------------------------------------------------
    if group.normalized_name:
        for sid in indexes["exact_name"].get(
            (group.exchange, group.normalized_name),
            [],
        ):
            add(
                sid,
                "EXACT_EXCHANGE_NAME",
                0.96,
                {
                    "exchange": group.exchange,
                    "normalized_name": group.normalized_name,
                },
            )

    # ---------------------------------------------------------------
    # 6. Strict name fallback
    # ---------------------------------------------------------------
    # For historical symbols such as KSOILS / LEEL / PUNJLLOYD, generic
    # token retrieval is unsafe: a single common word can produce many
    # unrelated active securities. First allow an exact name match across
    # exchanges only when it is unique. This is candidate retrieval, not an
    # automatic mapping decision.
    if group.normalized_name:
        exact_any = list(dict.fromkeys(
            indexes["exact_name_any"].get(group.normalized_name, [])
        ))
        if len(exact_any) == 1:
            sid = exact_any[0]
            add(
                sid,
                "EXACT_NAME_ANY_EXCHANGE",
                0.94,
                {
                    "normalized_name": group.normalized_name,
                    "news_exchange": group.exchange,
                },
            )
        elif len(exact_any) > 1:
            # Preserve ambiguity. All exact-name candidates are retained,
            # but with a lower retrieval score and explicit evidence.
            for sid in exact_any[:max_candidates]:
                add(
                    sid,
                    "EXACT_NAME_AMBIGUOUS",
                    0.92,
                    {
                        "normalized_name": group.normalized_name,
                        "news_exchange": group.exchange,
                        "exact_name_candidate_count": len(exact_any),
                    },
                )

    # ---------------------------------------------------------------
    # 7. Identity-aware token retrieval
    # ---------------------------------------------------------------
    # Historical symbol identities are NEVER sent through generic token
    # retrieval. A historical symbol needs historical-identity evidence.
    #
    # Issuer names use distinctive issuer tokens only. Generic words such as
    # ASSET / MANAGEMENT / FUND must not independently generate candidates.
    #
    # Specific instrument/fund names require stronger token coverage because
    # partial overlap is especially prone to matching unrelated funds.
    query_tokens = meaningful_tokens(group.normalized_name)
    distinctive = distinctive_tokens(group.normalized_name, identity_type)

    allow_token_retrieval = (
        identity_type != IDENTITY_HISTORICAL_SYMBOL
        and len(query_tokens) >= 2
        and len(distinctive) >= 1
    )

    if allow_token_retrieval:
        token_hits = Counter()

        for token in distinctive:
            for sid in indexes["token_index"].get(token, set()):
                token_hits[sid] += 1

        required_coverage = (
            0.75
            if identity_type == IDENTITY_SPECIFIC_INSTRUMENT
            else 0.50
        )

        for sid, hit_count in token_hits.most_common():
            coverage = hit_count / len(distinctive)

            if coverage < required_coverage:
                continue

            sec = by_id[sid]
            sec_name = normalize(sec.instrument_name or "")
            if not sec_name:
                continue

            exchange_match = (
                not group.exchange
                or normalize(sec.exchange) == group.exchange
                or group.exchange in normalize(sec.exchange_tag)
                or normalize(sec.exchange_tag) == "BOTH"
            )

            if not exchange_match:
                continue

            # Candidate retrieval remains deliberately bounded. Scores rank
            # candidates; they are never interpreted as mapping confidence.
            base = 0.55 if identity_type == IDENTITY_ISSUER_NAME else 0.60
            score = min(0.84, base + 0.25 * coverage)

            add(
                sid,
                "STRICT_TOKEN_RETRIEVAL",
                score,
                {
                    "query_tokens": list(query_tokens),
                    "distinctive_tokens": list(distinctive),
                    "matched_tokens": hit_count,
                    "token_coverage": round(coverage, 4),
                    "required_coverage": required_coverage,
                    "candidate_name": sec.instrument_name,
                    "exchange_match": True,
                    "identity_type": identity_type,
                },
            )

 # ---------------------------------------------------------------
    # 8. Conservative name-similarity retrieval
    # ---------------------------------------------------------------
    # This is candidate retrieval only. It does NOT establish canonical
    # identity and must never trigger an automatic mapping.
    #
    # Scope:
    # - company-name identities only
    # - same exchange only
    # - high full-name similarity only
    # - bounded number of candidates
    #
    # This catches controlled spelling/abbreviation differences such as:
    #   NAMAN INDUSTRIES PROXIMA LIMITED
    #   NAMAN INDUSTRE PRXIMA LTD
    #
    # Retrieval score is ranking evidence, NOT mapping confidence.

    if (
        group.normalized_name
        and identity_type == IDENTITY_COMPANY_NAME
        and group.exchange
    ):
        similarity_candidates = []

        for sid, sec in by_id.items():
            if not sec.instrument_name:
                continue

            sec_exchange = normalize(sec.exchange or "")
            if sec_exchange != group.exchange:
                continue

            similarity = name_similarity(
                group.normalized_name,
                sec.instrument_name,
            )

            if similarity < 0.85:
                continue

            similarity_candidates.append(
                (
                    similarity,
                    sid,
                    sec.instrument_name,
                )
            )

        similarity_candidates.sort(
            key=lambda item: (-item[0], item[1])
        )

        for similarity, sid, candidate_name in similarity_candidates[:5]:
            add(
                sid,
                "NAME_SIMILARITY_RETRIEVAL",
                round(similarity, 4),
                {
                    "event_name": group.normalized_name,
                    "candidate_name": candidate_name,
                    "name_similarity": round(similarity, 4),
                    "exchange_match": True,
                    "identity_type": identity_type,
                    "retrieval_only": True,
                },
            )

    # ---------------------------------------------------------------
    # 9. Acronym retrieval disabled for symbol-led historical groups.
    # Acronyms are too collision-prone at this stage and will be introduced
    # later only as an explicit secondary retrieval signal.
    # ---------------------------------------------------------------

    # Classify only after the complete candidate set has been generated.
    # Retrieval score remains a ranking score, not confidence.
    for candidate in candidates.values():
        candidate.candidate_status = classify_candidate(candidate)

        sec = by_id.get(candidate.security_id)
        if sec is not None:
            candidate.candidate_status = candidate_resolution_status(
                candidate,
                group,
                sec,
            )

    # Sort by retrieval score, then deterministic security_id.
    ordered = sorted(
        candidates.values(),
        key=lambda c: (-c.score, c.security_id),
    )

    return ordered[:max_candidates]


def merge_candidate_sources(
    deterministic_candidates: Sequence[Candidate],
    vector_candidates: Sequence[Candidate],
    max_candidates: int = 20,
) -> List[Candidate]:
    """
    Merge deterministic and vector retrieval results by security_id.

    Rules:
    - Preserve deterministic candidate evidence.
    - Preserve vector retrieval evidence.
    - Never let vector retrieval override deterministic status.
    - Vector retrieval score is ranking-only.
    - Vector-only candidates remain NEEDS_REVIEW.
    - No security_id assignment occurs here.
    """

    merged: Dict[int, Candidate] = {}

    # ---------------------------------------------------------------
    # 1. Start with deterministic candidates.
    # ---------------------------------------------------------------
    for candidate in deterministic_candidates:
        merged[candidate.security_id] = Candidate(
            security_id=candidate.security_id,
            method=candidate.method,
            score=candidate.score,
            evidence=dict(candidate.evidence or {}),
            candidate_type=candidate.candidate_type,
            matched_field=candidate.matched_field,
            match_reason=candidate.match_reason,
            candidate_status=candidate.candidate_status,
        )

    # ---------------------------------------------------------------
    # 2. Add vector candidates.
    # ---------------------------------------------------------------
    for vector_candidate in vector_candidates:
        existing = merged.get(vector_candidate.security_id)

        if existing is None:
            # Vector-only candidate.
            merged[vector_candidate.security_id] = Candidate(
                security_id=vector_candidate.security_id,
                method="VECTOR_RAG",
                score=vector_candidate.score,
                evidence={
                    "deterministic": {},
                    "vector": dict(vector_candidate.evidence or {}),
                },
                candidate_type=vector_candidate.candidate_type,
                matched_field=vector_candidate.matched_field,
                match_reason=vector_candidate.match_reason,
                candidate_status=STATUS_NEEDS_REVIEW,
            )
            continue

        # -----------------------------------------------------------
        # Same security found by both retrieval systems.
        # Preserve both evidence sources.
        # -----------------------------------------------------------
        existing.evidence = {
            "deterministic": (
                existing.evidence
                if isinstance(existing.evidence, dict)
                else {}
            ),
            "vector": dict(vector_candidate.evidence or {}),
        }

        # Keep the deterministic retrieval method/status.
        # Vector similarity must not upgrade or downgrade it.
        existing.match_reason = (
            f"{existing.match_reason} "
            "Vector retrieval also identified this security; "
            "vector similarity remains retrieval evidence only."
        ).strip()

    # ---------------------------------------------------------------
    # 3. Rank the merged candidate set.
    #
    # Deterministic retrieval score remains the primary ranking signal
    # when deterministic evidence exists. Vector-only candidates use
    # their vector retrieval score.
    # ---------------------------------------------------------------
    ordered = sorted(
        merged.values(),
        key=lambda c: (-c.score, c.security_id),
    )

    return ordered[:max_candidates]

def build_vector_query(group: IdentityGroup) -> str:
    """
    Build the identity text used for vector retrieval.

    Vector retrieval is an evidence-generation layer only.
    It does not establish canonical identity.

    Query priority:
    1. Symbol when present.
    2. Normalized company/instrument name.
    3. Empty query when no usable identity exists.

    The sample news title is intentionally not included at this
    stage so that vector retrieval remains focused on the identity
    representation rather than the full news narrative.
    """

    if group.symbol:
        return group.symbol.strip()

    if group.normalized_name:
        return group.normalized_name.strip()

    return ""


def retrieve_vector_candidates_for_group(
    conn,
    group: IdentityGroup,
    max_candidates: int = 10,
) -> List[Candidate]:
    """
    Retrieve vector/RAG candidates for one identity group.

    The vector layer is an optional retrieval signal. If PostgreSQL cannot
    load pgvector or the vector retrieval is otherwise unavailable, return
    an empty candidate list and let the deterministic Mapping Agent continue.

    This function:
    - reads security identity evidence through pgvector
    - performs canonical verification against security_master
    - converts the Evidence Bundle into V2.2 Candidate objects
    - never modifies market_news
    - never modifies security_master
    - never assigns security_id
    """

    query = build_vector_query(group)

    if not query:
        return []

    try:
        evidence_bundle = retrieve_and_verify_vector_candidates(
            conn=conn,
            query=query,
            limit=max_candidates,
        )

    except Exception as exc:
        conn.rollback()

        print(
            "[VECTOR_RAG] Vector retrieval unavailable; "
            "continuing with deterministic candidates only. "
            f"Reason: {exc}"
        )
        return []

    # Import locally to avoid a circular module dependency.
    from backend.agents.vector_candidate_adapter import (
        adapt_evidence_bundle,
    )

    return adapt_evidence_bundle(evidence_bundle)


def candidate_snapshot(sec: Security) -> dict:
    return {
        "security_id": sec.security_id,
        "instrument_name": sec.instrument_name,
        "symbol": sec.symbol,
        "nse_symbol": sec.nse_symbol,
        "bse_symbol": sec.bse_symbol,
        "exchange": sec.exchange,
        "exchange_tag": sec.exchange_tag,
        "asset_category": sec.asset_category,
        "isin": sec.isin,
        "bse_scrip_code": sec.bse_scrip_code,
        "is_active": sec.is_active,
    }


def ensure_v2_schema(conn):
    with open(SCHEMA_FILE, "r", encoding="utf-8") as fh:
        sql = fh.read()

    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def persist_candidates(
    conn,
    run_id: uuid.UUID,
    groups: Sequence[IdentityGroup],
    candidate_map: Dict[str, List[Candidate]],
    securities: Dict[int, Security],
):
    sql = """
    INSERT INTO security_mapping_candidates (
        run_id,
        news_id,
        identity_group_key,
        candidate_security_id,
        retrieval_method,
        retrieval_rank,
        retrieval_score,
        deterministic_evidence,
        retrieval_evidence,
        candidate_snapshot
    )
    VALUES (
        %s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb
    )
    ON CONFLICT DO NOTHING
    """

    rows = []

    for group in groups:
        candidates = candidate_map.get(group.group_key, [])

        for news_id in group.news_ids:
            for rank, candidate in enumerate(candidates, start=1):
                rows.append(
                    (
                        str(run_id),
                        news_id,
                        group.group_key,
                        candidate.security_id,
                        candidate.method,
                        rank,
                        candidate.score,
                        json.dumps(
                            candidate.evidence
                            if candidate.method != "VECTOR_RAG"
                            else {}
                        ),
                        json.dumps(
                            candidate.evidence
                            if candidate.method == "VECTOR_RAG"
                            else {}
                        ),
                        json.dumps(
                            candidate_snapshot(
                                securities[candidate.security_id]
                            )
                        ),
                    )
                )

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, row)

    conn.commit()
    return len(rows)


def persist_historical_identity_research_queue(
    conn,
    groups: Sequence[IdentityGroup],
):
    """Queue historical symbols for external evidence research only."""
    sql = """
    INSERT INTO marketpulse_historical_identity_evidence (
        identity_group_key,
        exchange,
        historical_symbol,
        historical_company_name,
        historical_isin,
        historical_bse_code,
        evidence_source,
        evidence_status,
        evidence
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
    ON CONFLICT DO NOTHING
    """

    rows = []
    for group in groups:
        if classify_identity_group(group) != IDENTITY_HISTORICAL_SYMBOL:
            continue
        rows.append(
            (
                group.group_key,
                group.exchange,
                group.symbol,
                group.company_name,
                group.isin or None,
                None,
                "MARKETPULSE_RESEARCH_QUEUE",
                STATUS_RESEARCH_REQUIRED,
                json.dumps({
                    "news_event_count": len(group.news_ids),
                    "sample_title": group.sample_title,
                    "resolution_rule": (
                        "Research historical exchange identity before "
                        "attempting canonical security mapping."
                    ),
                }),
            )
        )

    if not rows:
        return 0

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, row)
    conn.commit()
    return len(rows)


def persist_issuer_research_queue(
    conn,
    groups: Sequence[IdentityGroup],
):
    """Persist issuer identities without asserting a security_id."""
    sql = """
    INSERT INTO marketpulse_issuer_identity (
        normalized_issuer_name,
        issuer_name,
        issuer_type,
        evidence_source,
        evidence
    )
    VALUES (%s,%s,%s,%s,%s::jsonb)
    ON CONFLICT (normalized_issuer_name) DO NOTHING
    """

    rows = []
    for group in groups:
        if classify_identity_group(group) != IDENTITY_ISSUER_NAME:
            continue
        rows.append(
            (
                group.normalized_name,
                group.company_name,
                "ISSUER",
                "MARKETPULSE_IDENTITY_CLASSIFIER",
                json.dumps({
                    "identity_group_key": group.group_key,
                    "exchange": group.exchange,
                    "news_event_count": len(group.news_ids),
                    "sample_title": group.sample_title,
                }),
            )
        )

    if not rows:
        return 0

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, row)
    conn.commit()
    return len(rows)


def print_report(
    run_id: uuid.UUID,
    groups: Sequence[IdentityGroup],
    candidate_map: Dict[str, List[Candidate]],
    persisted: bool,
):
    total_events = sum(len(g.news_ids) for g in groups)
    candidate_counts = [len(candidate_map.get(g.group_key, [])) for g in groups]

    print()
    print("=" * 78)
    print("MARKETPULSE MAPPING AGENT V2 - CANDIDATE ENGINE")
    print("=" * 78)
    print(f"Run ID                  : {run_id}")
    print(f"Agent                   : {AGENT_NAME}")
    print(f"Version                 : {AGENT_VERSION}")
    print(f"Identity groups         : {len(groups):,}")
    print(f"News events represented : {total_events:,}")
    print(
        f"Groups with candidates  : "
        f"{sum(1 for n in candidate_counts if n > 0):,}"
    )
    print(
        f"Groups without candidates: "
        f"{sum(1 for n in candidate_counts if n == 0):,}"
    )
    print(
        f"Average candidates/group: "
        f"{sum(candidate_counts) / max(len(candidate_counts), 1):.2f}"
    )
    print(f"Candidates persisted    : {'YES' if persisted else 'NO'}")
    print("=" * 78)

    print()
    print("Top recurring unresolved identities")
    print("-" * 78)

    for group in groups:
        candidates = candidate_map.get(group.group_key, [])
        identity_type = classify_identity_group(group)
        print(
            f"{group.group_key:<55} "
            f"events={len(group.news_ids):>4} "
            f"candidates={len(candidates):>2} "
            f"identity={identity_type}"
        )

        for candidate in candidates[:5]:
            print(
                f"    -> {candidate.security_id:<8} "
                f"{candidate.method:<25} "
                f"retrieval={candidate.score:.3f} "
                f"type={candidate.candidate_type:<20} "
                f"status={candidate.candidate_status}"
            )
            print(
                f"       matched={candidate.matched_field or '-'} "
                f"reason={candidate.match_reason}"
            )

    print()
    identity_counts = Counter(classify_identity_group(g) for g in groups)
    print("Identity classification")
    print("-" * 78)
    for identity_type, count in sorted(identity_counts.items()):
        print(f"{identity_type:<28} {count:>6}")

    print()
    print("IMPORTANT: retrieval scores are candidate-ranking scores only.")
    print("They are NOT mapping confidence and must not trigger auto-apply.")

def print_vector_report(
    groups: Sequence[IdentityGroup],
    vector_candidate_map: Dict[str, List[Candidate]],
):
    print()
    print("=" * 78)
    print("MARKETPULSE VECTOR RETRIEVAL - STEP 1")
    print("=" * 78)

    groups_with_vectors = sum(
        1
        for group in groups
        if vector_candidate_map.get(group.group_key)
    )

    total_vector_candidates = sum(
        len(vector_candidate_map.get(group.group_key, []))
        for group in groups
    )

    print(
        f"Groups with vector candidates : "
        f"{groups_with_vectors:,}"
    )

    print(
        f"Vector candidates             : "
        f"{total_vector_candidates:,}"
    )

    print("=" * 78)
    print()

    for group in groups:
        candidates = vector_candidate_map.get(
            group.group_key,
            [],
        )

        if not candidates:
            continue

        query = build_vector_query(group)

        print(
            f"{group.group_key:<55} "
            f"query={query}"
        )

        for candidate in candidates[:5]:
            print(
                f"    -> {candidate.security_id:<8} "
                f"{candidate.method:<15} "
                f"retrieval={candidate.score:.6f} "
                f"type={candidate.candidate_type:<18} "
                f"status={candidate.candidate_status}"
            )

            print(
                f"       distance="
                f"{candidate.evidence.get('best_distance')} "
                f"canonical="
                f"{candidate.evidence.get('canonical_status')}"
            )


def parse_args():
    parser = argparse.ArgumentParser(
        description="MarketPulse Mapping Agent V2 candidate engine"
    )

    parser.add_argument(
        "--init",
        action="store_true",
        help="Create the V2 identity/candidate/decision tables.",
    )

    parser.add_argument(
        "--persist-candidates",
        action="store_true",
        help="Persist generated candidates. Does not modify market_news or security_master.",
    )

    parser.add_argument(
        "--limit-groups",
        type=int,
        default=100,
        help="Maximum recurring identity groups to process.",
    )

    parser.add_argument(
        "--max-candidates",
        type=int,
        default=20,
        help="Maximum candidates retained per identity group.",
    )

    parser.add_argument(
        "--all-groups",
        action="store_true",
        help="Process all unresolved identity groups.",
    )

    parser.add_argument(
        "--persist-research-queue",
        action="store_true",
        help=(
            "Persist historical-identity research and issuer identity queues. "
            "Does not modify market_news or security_master."
        ),
    )

    return parser.parse_args()


def main():
    args = parse_args()

    conn = connect()

    try:
        if args.init:
            ensure_v2_schema(conn)
            print("Mapping Agent V2 schema: READY")

        groups = load_identity_groups(
            conn,
            limit_groups=None if args.all_groups else args.limit_groups,
        )

        securities = load_securities(conn)
        indexes = build_indexes(securities)
        security_by_id = indexes["by_id"]

        print(f"Active securities loaded: {len(securities):,}")
        print(f"Unresolved identity groups selected: {len(groups):,}")

        run_id = uuid.uuid4()

        # Deterministic candidates remain the primary V2.2 candidate map.
        candidate_map = {}

        # Vector candidates are deliberately maintained separately.
        # They are retrieval evidence only and are not merged into the
        # deterministic candidate set at this stage.
        vector_candidate_map = {}

        for index, group in enumerate(groups, start=1):
            deterministic_candidates = retrieve_candidates(
                conn,
                group,
                indexes,
                max_candidates=args.max_candidates,
            )

            vector_candidates = retrieve_vector_candidates_for_group(
                conn,
                group,
                max_candidates=args.max_candidates,
            )

            candidate_map[group.group_key] = merge_candidate_sources(
                deterministic_candidates,
                vector_candidates,
                max_candidates=args.max_candidates,
            )

            vector_candidate_map[group.group_key] = vector_candidates

            if index % 100 == 0:
                print(
                    f"Candidate progress: {index:,}/{len(groups):,}"
                )

        persisted = False

        if args.persist_research_queue:
            historical_count = persist_historical_identity_research_queue(
                conn,
                groups,
            )
            issuer_count = persist_issuer_research_queue(
                conn,
                groups,
            )
            print(
                f"Historical research queue rows persisted: "
                f"{historical_count:,}"
            )
            print(
                f"Issuer identity rows persisted: "
                f"{issuer_count:,}"
            )

        if args.persist_candidates:
            if not args.init:
                # Schema may already exist; proceed.
                pass

            count = persist_candidates(
                conn,
                run_id,
                groups,
                candidate_map,
                security_by_id,
            )
            print(f"Candidate rows persisted: {count:,}")
            persisted = True

        print_report(
            run_id,
            groups,
            candidate_map,
            persisted,
        )

        print_vector_report(
        groups,
        vector_candidate_map,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()