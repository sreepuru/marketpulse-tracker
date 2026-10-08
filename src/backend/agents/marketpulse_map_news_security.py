"""
MarketPulse - News to Security Mapping

Purpose
-------
Resolve market_news STOCK events to security_master.security_id.

This module is intended to be:
1. Run independently against existing events.
2. Used later by the news-ingestion pipeline for newly fetched events.

Safety
------
- Default mode is DRY-RUN.
- Database writes happen only with --apply.
- Market-level events are never mapped to a stock.
- Existing valid security_id values are preserved.
- Same-exchange exact symbol matching is preferred.
- Same-exchange normalized company-name matching is supported.
- Cross-exchange company-name matching is OPTIONAL and disabled by default.
- Ambiguous matches are never automatically assigned.
- For mapped events, asset_category is sourced only from security_master.

Mapping priority
----------------
1. Existing valid security_id
2. Confirmed company-name alias
3. BSE scrip code extracted from title
4. Exact symbol + exchange
4. Exact normalized company name + exchange
5. Exchange-specific alias
6. Exact normalized company name across exchanges
   - only when --allow-cross-exchange is supplied
   - only when exactly one security exists
7. Otherwise:
   - PENDING when there is no candidate
   - AMBIGUOUS when multiple candidates exist

Database tables
---------------
market_news
security_master
market_news_security_candidates
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import psycopg2
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Environment / database
# ---------------------------------------------------------------------------

load_dotenv()


def get_db_connection():
    """
    Create PostgreSQL connection using the existing MarketPulse
    environment-variable convention.
    """

    host = os.getenv("MARKETPULSE_DB_HOST", "localhost")
    port = int(os.getenv("MARKETPULSE_DB_PORT", "5432"))
    database = os.getenv("MARKETPULSE_DB_NAME")
    user = os.getenv("MARKETPULSE_DB_USER")
    password = os.getenv("MARKETPULSE_DB_PASSWORD")

    missing = []

    if not database:
        missing.append("MARKETPULSE_DB_NAME")

    if not user:
        missing.append("MARKETPULSE_DB_USER")

    if password is None:
        missing.append("MARKETPULSE_DB_PASSWORD")

    if missing:
        raise RuntimeError(
            "Missing database environment variables: "
            + ", ".join(missing)
        )

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAPPED = "MAPPED"
PENDING = "PENDING"
AMBIGUOUS = "AMBIGUOUS"
NOT_APPLICABLE = "NOT_APPLICABLE"

STOCK_SCOPE = "STOCK"
MARKET_SCOPE = "MARKET"

CONFIDENCE_EXISTING_SECURITY_ID = 1.00
CONFIDENCE_BSE_SCRIP_CODE = 1.00
CONFIDENCE_EXACT_SYMBOL_EXCHANGE = 0.98
CONFIDENCE_NORMALIZED_NAME = 0.90
CONFIDENCE_CROSS_EXCHANGE_NAME = 0.85

BSE_SCRIP_CODE_PATTERN = re.compile(r"\(([0-9]{5,8})\)")

# Asset classification used by the news/mapping layer.
ASSET_MUTUAL_FUND = "MUTUAL_FUND"
ASSET_ETF = "ETF"
ASSET_BONDS = "BOND"
ASSET_OTHERS = "OTHER"

# Curated deterministic mappings confirmed for the current MarketPulse
# security master. These are aliases from incoming news company names to the
# existing canonical security_id; no new securities are created.
KNOWN_COMPANY_SECURITY_MAP = {
    "AA PLUS TRADELINK LTD": 543319,
    "AADHAAR VENTURES INDIA LTD": 531611,
    "ABHISHEK CORPORATION LIMITED": 532831,
    "VALECHA ENGINEERING LIMITED": 532389,
    "VALUE INDUSTRIES LIMITED": 500945,
    "VIDEOCON INDUSTRIES LIMITED": 511389,
    "VIRYA RESOURCES LTD": 512479,
    "VISESH INFOTECNICS LIMITED": 532411,
    "VISU INTERNATIONAL LIMITED": 590038,
    "WISEC GLOBAL LTD": 511642,
    "XL ENERGY LIMITED": 532788,
    "ZF COMMERCIAL VEHICLE CONTROL SYSTEMS INDIA LIMITED": 533023,
    "ZF COMMERCIAL VEHICLE CONTROL SYSTEMS INDIA LTD": 533023,
}

# 360 ONE Asset Management is an AMC, not an ordinary listed operating
# company for this mapping workflow. Watermarke Estates is treated as
# Others unless a future canonical security record is established.
KNOWN_NON_EQUITY_ASSET_MAP = {
    "360 ONE ASSET MANAGEMENT LIMITED": ASSET_MUTUAL_FUND,
    "WATERMARKE ESTATES PVT LTD": ASSET_OTHERS,
}

# Existing project data contains polluted company names such as:
#
#   "ABC LTD - Ex-Date: 02-Sep-2026"
#
# Remove that suffix before normalisation.
EX_DATE_PATTERN = re.compile(
    r"\s*-\s*Ex[- ]?Date\s*:\s*.*$",
    flags=re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Security:
    security_id: int
    isin: Optional[str]
    asset_category: Optional[str]

    # Existing master fields
    symbol: Optional[str]
    series: Optional[str]
    instrument_id: Optional[int]
    instrument_type: Optional[str]
    instrument_name: Optional[str]
    exchange: Optional[str]
    segment: Optional[str]
    security_category: Optional[str]

    # NSE-specific master fields
    nse_symbol: Optional[str]
    nse_name: Optional[str]
    nse_alias: Optional[str]

    # BSE-specific master fields
    bse_symbol: Optional[str]
    bse_name: Optional[str]
    bse_alias: Optional[str]
    bse_scrip_code: Optional[str]

    # NSE / BSE / BOTH
    exchange_tag: Optional[str]

    is_active: bool

    @property
    def normalized_name(self) -> str:
        return normalize_company_name(self.instrument_name)

    @property
    def normalized_symbol(self) -> str:
        return normalize_symbol(self.symbol)

@dataclass(frozen=True)
class NewsEvent:
    news_id: int
    exchange: Optional[str]
    symbol: Optional[str]
    security_id: Optional[int]
    company_name: Optional[str]
    title: Optional[str]
    news_scope: Optional[str]
    mapping_status: Optional[str]
    mapping_method: Optional[str]
    mapping_confidence: Optional[float]
    asset_category: Optional[str] = None


@dataclass
class Resolution:
    status: str
    security_id: Optional[int]
    mapping_method: Optional[str]
    confidence: Optional[float]
    candidates: List[Tuple[int, str, float]]
    reason: str


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def clean_text(value: Optional[str]) -> str:
    """
    Basic text cleanup.

    Does not attempt aggressive fuzzy matching.
    The first version should remain deterministic and auditable.
    """

    if value is None:
        return ""

    value = str(value).strip()

    if not value:
        return ""

    return value


def normalize_symbol(value: Optional[str]) -> str:
    """
    Normalize stock symbols.

    Example:
        "UJJIVANSFB" -> "UJJIVANSFB"
        " ujjivansfb " -> "UJJIVANSFB"
    """

    value = clean_text(value)

    if not value:
        return ""

    return re.sub(r"[^A-Z0-9]", "", value.upper())


def normalize_company_name(value: Optional[str]) -> str:
    """
    Normalize company names for deterministic exact matching.

    Examples:
        "Sunshield Chemicals Ltd."
        "SUNSHIELD CHEMICALS LTD"
        "Sunshield Chemicals Ltd - Ex-Date: 02-Sep-2026"

    become the same normalized representation.
    """

    value = clean_text(value)

    if not value:
        return ""

    # Remove known feed pollution.
    value = EX_DATE_PATTERN.sub("", value)

    value = value.upper()

    # Replace punctuation/separators with spaces.
    value = re.sub(r"[^A-Z0-9]+", " ", value)

    # Collapse repeated whitespace.
    value = re.sub(r"\s+", " ", value).strip()

    return value


def classify_asset(
    company_name: Optional[str],
    bse_scrip_code: Optional[str] = None,
) -> str:
    """
    Classify an incoming security/news entity using the requested deterministic
    rules, in this precedence order:
      1. BSE/security code beginning with 9 -> Mutual funds
      2. Name containing ETF -> ETF
      3. Name containing Bond -> Bonds
      4. Everything else -> Others

    Known non-equity aliases may be explicitly classified before the generic
    fallback. This function does not infer an equity security from category.
    """
    normalized_name = normalize_company_name(company_name)
    code = normalize_symbol(bse_scrip_code)

    explicit = KNOWN_NON_EQUITY_ASSET_MAP.get(normalized_name)
    if explicit:
        return explicit

    if code.startswith("9"):
        return ASSET_MUTUAL_FUND

    if "ETF" in normalized_name:
        return ASSET_ETF

    if "BOND" in normalized_name:
        return ASSET_BONDS

    return ASSET_OTHERS


def known_company_security_id(company_name: Optional[str]) -> Optional[int]:
    """Return a confirmed curated security_id for a known company alias."""
    return KNOWN_COMPANY_SECURITY_MAP.get(normalize_company_name(company_name))


def extract_bse_scrip_code(title: Optional[str]) -> str:
    """
    Extract a BSE scrip code from the event title.

    Example:
        "Sunshield Chemicals Ltd (530845)"
        -> "530845"

    Returns an empty string when no 5-8 digit parenthesized
    BSE scrip code is present.
    """
    if not title:
        return ""

    match = BSE_SCRIP_CODE_PATTERN.search(str(title))

    if not match:
        return ""

    return match.group(1)


# ---------------------------------------------------------------------------
# Asset category persistence
# ---------------------------------------------------------------------------

def ensure_asset_category_column(conn) -> None:
    """
    Add the dedicated news asset classification column if it does not exist.
    This is intentionally separate from market_news.category, which is the
    existing event/category field used by the application and ML pipeline.
    """
    sql = """
    ALTER TABLE market_news
    ADD COLUMN IF NOT EXISTS asset_category VARCHAR(50);
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


# ---------------------------------------------------------------------------
# Candidate table
# ---------------------------------------------------------------------------

def ensure_candidate_table(conn) -> None:
    """
    Ensure the candidate table exists.

    This follows the existing MarketPulse mapping design.
    """

    sql = """
    CREATE TABLE IF NOT EXISTS market_news_security_candidates (
        candidate_id BIGSERIAL PRIMARY KEY,
        news_id BIGINT NOT NULL,
        security_id BIGINT NOT NULL,
        match_method VARCHAR(100) NOT NULL,
        match_confidence NUMERIC,
        candidate_name TEXT,
        normalized_news_name TEXT,
        normalized_security_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (news_id, security_id, match_method)
    );

    CREATE INDEX IF NOT EXISTS idx_mnsc_news_id
        ON market_news_security_candidates(news_id);

    CREATE INDEX IF NOT EXISTS idx_mnsc_security_id
        ON market_news_security_candidates(security_id);
    """

    with conn.cursor() as cur:
        cur.execute(sql)

    conn.commit()


# ---------------------------------------------------------------------------
# Load security master
# ---------------------------------------------------------------------------

def load_security_master(conn) -> List[Security]:
    """
    Load active securities from security_master.

    The project uses security_master as the canonical security identity
    table. NSE and BSE exchange-specific identity fields are loaded so
    mapping can use the appropriate exchange representation.
    """

    sql = """
    SELECT
        security_id,
        isin,

        symbol,
        series,
        instrument_id,
        instrument_type,
        instrument_name,
        exchange,
        segment,
        security_category,

        nse_symbol,
        nse_name,
        nse_alias,

        bse_symbol,
        bse_name,
        bse_alias,
        bse_scrip_code,

        exchange_tag,
        asset_category,

        is_active
    FROM security_master
    WHERE is_active = TRUE
    ORDER BY security_id;
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    securities = []

    for row in rows:
        securities.append(
            Security(
                security_id=row[0],
                isin=row[1],
                asset_category=row[18],

                symbol=row[2],
                series=row[3],
                instrument_id=row[4],
                instrument_type=row[5],
                instrument_name=row[6],
                exchange=row[7],
                segment=row[8],
                security_category=row[9],

                nse_symbol=row[10],
                nse_name=row[11],
                nse_alias=row[12],

                bse_symbol=row[13],
                bse_name=row[14],
                bse_alias=row[15],
                bse_scrip_code=row[16],

                exchange_tag=row[17],

                is_active=row[19],
            )
        )

    return securities


# ---------------------------------------------------------------------------
# Build indexes
# ---------------------------------------------------------------------------

def build_security_indexes(
    securities: Sequence[Security],
):
    """Build deterministic exchange-specific lookup indexes.

    IMPORTANT: security_master.symbol is the canonical symbol in this project.
    Many master rows have nse_symbol NULL while exchange_tag=BOTH, so the
    canonical symbol must also be indexed for every exchange the security
    supports. This is deterministic identity matching, not fuzzy matching.
    """

    by_security_id: Dict[int, Security] = {}
    by_nse_symbol: Dict[str, List[Security]] = defaultdict(list)
    by_bse_symbol: Dict[str, List[Security]] = defaultdict(list)
    by_nse_name: Dict[str, List[Security]] = defaultdict(list)
    by_bse_name: Dict[str, List[Security]] = defaultdict(list)
    by_nse_alias: Dict[str, List[Security]] = defaultdict(list)
    by_bse_alias: Dict[str, List[Security]] = defaultdict(list)
    by_bse_scrip_code: Dict[str, List[Security]] = defaultdict(list)
    by_name: Dict[str, List[Security]] = defaultdict(list)

    for security in securities:
        by_security_id[security.security_id] = security

        exchange = normalize_symbol(security.exchange)
        exchange_tag = normalize_symbol(security.exchange_tag)
        supports_nse = exchange == "NSE" or exchange_tag in {"NSE", "BOTH"}
        supports_bse = exchange == "BSE" or exchange_tag in {"BSE", "BOTH"}

        nse_symbol = normalize_symbol(security.nse_symbol)
        if nse_symbol:
            by_nse_symbol[nse_symbol].append(security)

        bse_symbol = normalize_symbol(security.bse_symbol)
        if bse_symbol:
            by_bse_symbol[bse_symbol].append(security)

        # Canonical security_master.symbol is also an exchange-supported symbol.
        canonical_symbol = normalize_symbol(security.symbol)
        if canonical_symbol and supports_nse and security not in by_nse_symbol[canonical_symbol]:
            by_nse_symbol[canonical_symbol].append(security)
        if canonical_symbol and supports_bse and security not in by_bse_symbol[canonical_symbol]:
            by_bse_symbol[canonical_symbol].append(security)

        nse_name = normalize_company_name(security.nse_name)
        if nse_name:
            by_nse_name[nse_name].append(security)
            by_name[nse_name].append(security)

        bse_name = normalize_company_name(security.bse_name)
        if bse_name:
            by_bse_name[bse_name].append(security)
            by_name[bse_name].append(security)

        canonical_name = normalize_company_name(security.instrument_name)
        if canonical_name:
            by_name[canonical_name].append(security)
            if supports_nse and security not in by_nse_name[canonical_name]:
                by_nse_name[canonical_name].append(security)
            if supports_bse and security not in by_bse_name[canonical_name]:
                by_bse_name[canonical_name].append(security)

        nse_alias = normalize_company_name(security.nse_alias)
        if nse_alias:
            by_nse_alias[nse_alias].append(security)

        bse_alias = normalize_company_name(security.bse_alias)
        if bse_alias:
            by_bse_alias[bse_alias].append(security)

        bse_scrip_code = normalize_symbol(security.bse_scrip_code)
        if bse_scrip_code:
            by_bse_scrip_code[bse_scrip_code].append(security)

    return (
        by_security_id, by_nse_symbol, by_bse_symbol, by_nse_name,
        by_bse_name, by_nse_alias, by_bse_alias, by_bse_scrip_code, by_name,
    )

# ---------------------------------------------------------------------------
# Load news
# ---------------------------------------------------------------------------

def load_news_events(
    conn,
    only_unmapped: bool = False,
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
) -> List[NewsEvent]:
    """
    Load STOCK news events.

    By default all STOCK events are considered.

    --only-unmapped restricts the run to unresolved equity/Others events.
    Non-equity categories (Mutual funds, ETF, Bonds) are excluded from the
    security-mapping queue.
    """

    conditions = [
        "news_scope = 'STOCK'"
    ]

    params: List[object] = []

    if only_unmapped:
        # Security mapping is performed only for the equity/"Others" bucket.
        # Mutual funds, ETFs and Bonds are classified as non-equity assets and
        # must not remain in the security-mapping queue. NULL is retained here
        # only for forward compatibility with newly ingested events that have
        # not yet been classified.
        conditions.append(
            "(mapping_status IS DISTINCT FROM 'MAPPED' "
            "OR security_id IS NULL)"
        )
        conditions.append(
            "(asset_category = 'OTHER' OR asset_category IS NULL)"
        )

    if start_id is not None:
        conditions.append("news_id >= %s")
        params.append(start_id)

    if end_id is not None:
        conditions.append("news_id <= %s")
        params.append(end_id)

    sql = f"""
    SELECT
        news_id,
        exchange,
        symbol,
        security_id,
        company_name,
        title,
        news_scope,
        mapping_status,
        mapping_method,
        mapping_confidence,
        asset_category
    FROM market_news
    WHERE {' AND '.join(conditions)}
    ORDER BY news_id
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    events = []

    for row in rows:
        events.append(
            NewsEvent(
                news_id=row[0],
                exchange=row[1],
                symbol=row[2],
                security_id=row[3],
                company_name=row[4],
                title=row[5],
                news_scope=row[6],
                mapping_status=row[7],
                mapping_method=row[8],
                mapping_confidence=(
                    float(row[9])
                    if row[9] is not None
                    else None
                ),
                asset_category=row[10],
            )
        )

    return events


def load_unmapped_asset_counts(conn) -> Counter:
    """Return asset-category counts for the current unresolved STOCK queue.

    This intentionally looks at the full unresolved queue so the summary can
    show how many records are classified as non-equity versus the reduced
    equity/Others security-mapping queue.
    """
    sql = """
    SELECT COALESCE(asset_category, 'UNCLASSIFIED'), COUNT(*)
    FROM market_news
    WHERE news_scope = 'STOCK'
      AND (mapping_status IS DISTINCT FROM 'MAPPED' OR security_id IS NULL)
    GROUP BY COALESCE(asset_category, 'UNCLASSIFIED')
    ORDER BY 1;
    """

    result = Counter()
    with conn.cursor() as cur:
        cur.execute(sql)
        for category, count in cur.fetchall():
            result[category] = int(count)
    return result


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def unique_securities(
    securities: Iterable[Security],
) -> List[Security]:
    """
    Remove duplicate security IDs while preserving order.
    """

    seen = set()
    result = []

    for security in securities:
        if security.security_id in seen:
            continue

        seen.add(security.security_id)
        result.append(security)

    return result


def valid_existing_security(
    event: NewsEvent,
    by_security_id: Dict[int, Security],
) -> Optional[Security]:
    """
    Validate an existing market_news.security_id.

    We only accept it when the referenced security exists and is active.
    """

    if event.security_id is None:
        return None

    security = by_security_id.get(event.security_id)

    if security is None:
        return None

    return security


def resolve_security(
    event: NewsEvent,
    by_security_id: Dict[int, Security],
    by_nse_symbol: Dict[str, List[Security]],
    by_bse_symbol: Dict[str, List[Security]],
    by_nse_name: Dict[str, List[Security]],
    by_bse_name: Dict[str, List[Security]],
    by_nse_alias: Dict[str, List[Security]],
    by_bse_alias: Dict[str, List[Security]],
    by_bse_scrip_code: Dict[str, List[Security]],
    by_name: Dict[str, List[Security]],
    allow_cross_exchange: bool = False,
) -> Resolution:
    """
    Resolve one news event using exchange-specific security-master fields.

    Priority:

    1. Existing valid security_id
    2. BSE scrip code
    3. Exchange-specific exact symbol
    4. Exchange-specific normalized company name
    5. Exchange-specific alias
    6. Optional cross-exchange normalized name
    7. PENDING

    Multiple candidates are never automatically assigned.
    """

    exchange = clean_text(event.exchange).upper()

    symbol = normalize_symbol(event.symbol)
    company_name = normalize_company_name(event.company_name)

    # ------------------------------------------------------------------
    # 1. Existing valid security_id
    # ------------------------------------------------------------------

    existing = valid_existing_security(
        event,
        by_security_id,
    )

    if existing is not None:
        return Resolution(
            status=MAPPED,
            security_id=existing.security_id,
            mapping_method="EXISTING_SECURITY_ID",
            confidence=CONFIDENCE_EXISTING_SECURITY_ID,
            candidates=[
                (
                    existing.security_id,
                    existing.instrument_name or "",
                    CONFIDENCE_EXISTING_SECURITY_ID,
                )
            ],
            reason="Existing security_id is valid in security_master.",
        )

    # ------------------------------------------------------------------
    # 2. Confirmed curated company-name mapping
    # ------------------------------------------------------------------
    curated_security_id = known_company_security_id(event.company_name)
    if curated_security_id is not None:
        security = by_security_id.get(curated_security_id)
        if security is not None:
            return Resolution(
                status=MAPPED,
                security_id=security.security_id,
                mapping_method="KNOWN_COMPANY_ALIAS",
                confidence=1.00,
                candidates=[
                    (
                        security.security_id,
                        security.instrument_name
                        or security.bse_name
                        or security.nse_name
                        or "",
                        1.00,
                    )
                ],
                reason="Confirmed MarketPulse company-name alias mapping.",
            )

    # ------------------------------------------------------------------
    # 3. BSE scrip code extracted from title
    # ------------------------------------------------------------------

    if exchange == "BSE":
        bse_scrip_code = extract_bse_scrip_code(event.title)

        if bse_scrip_code:
            scrip_candidates = unique_securities(
                by_bse_scrip_code.get(bse_scrip_code, [])
            )

            if len(scrip_candidates) == 1:
                security = scrip_candidates[0]

                return Resolution(
                    status=MAPPED,
                    security_id=security.security_id,
                    mapping_method="BSE_SCRIP_CODE",
                    confidence=CONFIDENCE_BSE_SCRIP_CODE,
                    candidates=[
                        (
                            security.security_id,
                            security.bse_name
                            or security.instrument_name
                            or "",
                            CONFIDENCE_BSE_SCRIP_CODE,
                        )
                    ],
                    reason=(
                        f"Exact BSE scrip code {bse_scrip_code} "
                        f"extracted from event title."
                    ),
                )

            if len(scrip_candidates) > 1:
                return Resolution(
                    status=AMBIGUOUS,
                    security_id=None,
                    mapping_method="BSE_SCRIP_CODE",
                    confidence=CONFIDENCE_BSE_SCRIP_CODE,
                    candidates=[
                        (
                            security.security_id,
                            security.bse_name
                            or security.instrument_name
                            or "",
                            CONFIDENCE_BSE_SCRIP_CODE,
                        )
                        for security in scrip_candidates
                    ],
                    reason=(
                        f"Multiple active securities have BSE scrip code "
                        f"{bse_scrip_code}."
                    ),
                )

            
    # ------------------------------------------------------------------
    # 4. Exact exchange-specific symbol
    # ------------------------------------------------------------------

    if exchange == "NSE" and symbol:
        symbol_candidates = unique_securities(
            by_nse_symbol.get(symbol, [])
        )
    elif exchange == "BSE" and symbol:
        symbol_candidates = unique_securities(
            by_bse_symbol.get(symbol, [])
        )
    else:
        symbol_candidates = []

    if len(symbol_candidates) == 1:
        security = symbol_candidates[0]

        return Resolution(
            status=MAPPED,
            security_id=security.security_id,
            mapping_method="EXACT_SYMBOL_EXCHANGE",
            confidence=CONFIDENCE_EXACT_SYMBOL_EXCHANGE,
            candidates=[
                (
                    security.security_id,
                    (
                        security.nse_name
                        if exchange == "NSE"
                        else security.bse_name
                    )
                    or security.instrument_name
                    or "",
                    CONFIDENCE_EXACT_SYMBOL_EXCHANGE,
                )
            ],
            reason=f"Exact {exchange} symbol match.",
        )

    if len(symbol_candidates) > 1:
        return Resolution(
            status=AMBIGUOUS,
            security_id=None,
            mapping_method="EXACT_SYMBOL_EXCHANGE",
            confidence=CONFIDENCE_EXACT_SYMBOL_EXCHANGE,
            candidates=[
                (
                    security.security_id,
                    (
                        security.nse_name
                        if exchange == "NSE"
                        else security.bse_name
                    )
                    or security.instrument_name
                    or "",
                    CONFIDENCE_EXACT_SYMBOL_EXCHANGE,
                )
                for security in symbol_candidates
            ],
            reason=f"Multiple active securities have the same {exchange} symbol.",
        )
    
    # ------------------------------------------------------------------
    # 5. Exchange-specific normalized company name
    # ------------------------------------------------------------------

    if exchange == "NSE" and company_name:
        name_candidates = unique_securities(
            by_nse_name.get(company_name, [])
        )

    elif exchange == "BSE" and company_name:
        name_candidates = unique_securities(
            by_bse_name.get(company_name, [])
        )

    else:
        name_candidates = []

    if len(name_candidates) == 1:
        security = name_candidates[0]

        return Resolution(
            status=MAPPED,
            security_id=security.security_id,
            mapping_method="NORMALIZED_NAME",
            confidence=CONFIDENCE_NORMALIZED_NAME,
            candidates=[
                (
                    security.security_id,
                    (
                        security.nse_name
                        if exchange == "NSE"
                        else security.bse_name
                    )
                    or security.instrument_name
                    or "",
                    CONFIDENCE_NORMALIZED_NAME,
                )
            ],
            reason=(
                f"Exact normalized {exchange} company name match."
            ),
        )

    if len(name_candidates) > 1:
        return Resolution(
            status=AMBIGUOUS,
            security_id=None,
            mapping_method="NORMALIZED_NAME",
            confidence=CONFIDENCE_NORMALIZED_NAME,
            candidates=[
                (
                    security.security_id,
                    (
                        security.nse_name
                        if exchange == "NSE"
                        else security.bse_name
                    )
                    or security.instrument_name
                    or "",
                    CONFIDENCE_NORMALIZED_NAME,
                )
                for security in name_candidates
            ],
            reason=(
                f"Multiple active securities have the same normalized "
                f"{exchange} company name."
            ),
        )


    # ------------------------------------------------------------------
    # 6. Exchange-specific alias
    # ------------------------------------------------------------------

    if exchange == "NSE" and company_name:
        alias_candidates = unique_securities(
            by_nse_alias.get(company_name, [])
        )
    elif exchange == "BSE" and company_name:
        alias_candidates = unique_securities(
            by_bse_alias.get(company_name, [])
        )
    else:
        alias_candidates = []

    if len(alias_candidates) == 1:
        security = alias_candidates[0]

        return Resolution(
            status=MAPPED,
            security_id=security.security_id,
            mapping_method="EXCHANGE_ALIAS",
            confidence=0.88,
            candidates=[
                (
                    security.security_id,
                    (
                        security.nse_name
                        if exchange == "NSE"
                        else security.bse_name
                    )
                    or security.instrument_name
                    or "",
                    0.88,
                )
            ],
            reason=f"Exact {exchange} alias match.",
        )

    if len(alias_candidates) > 1:
        return Resolution(
            status=AMBIGUOUS,
            security_id=None,
            mapping_method="EXCHANGE_ALIAS",
            confidence=0.88,
            candidates=[
                (
                    security.security_id,
                    (
                        security.nse_name
                        if exchange == "NSE"
                        else security.bse_name
                    )
                    or security.instrument_name
                    or "",
                    0.88,
                )
                for security in alias_candidates
            ],
            reason=f"Multiple active securities have the same {exchange} alias.",
        )

    # ------------------------------------------------------------------
    # 7. Optional cross-exchange normalized company-name match
    # ------------------------------------------------------------------

    if allow_cross_exchange and company_name:
        cross_exchange_candidates = unique_securities(
            by_name.get(company_name, [])
        )

        if len(cross_exchange_candidates) == 1:
            security = cross_exchange_candidates[0]

            return Resolution(
                status=MAPPED,
                security_id=security.security_id,
                mapping_method="CROSS_EXCHANGE_NAME",
                confidence=CONFIDENCE_CROSS_EXCHANGE_NAME,
                candidates=[
                    (
                        security.security_id,
                        security.instrument_name or "",
                        CONFIDENCE_CROSS_EXCHANGE_NAME,
                    )
                ],
                reason=(
                    "Unique normalized company name across exchanges. "
                    "Cross-exchange matching was explicitly enabled."
                ),
            )

        if len(cross_exchange_candidates) > 1:
            return Resolution(
                status=AMBIGUOUS,
                security_id=None,
                mapping_method="CROSS_EXCHANGE_NAME",
                confidence=CONFIDENCE_CROSS_EXCHANGE_NAME,
                candidates=[
                    (
                        security.security_id,
                        security.instrument_name or "",
                        CONFIDENCE_CROSS_EXCHANGE_NAME,
                    )
                    for security in cross_exchange_candidates
                ],
                reason=(
                    "Company name exists for multiple active securities "
                    "across exchanges."
                ),
            )

    # ------------------------------------------------------------------
    # 8. No match
    # ------------------------------------------------------------------

    return Resolution(
        status=PENDING,
        security_id=None,
        mapping_method=None,
        confidence=None,
        candidates=[],
        reason="No deterministic security match found.",
    )

# ---------------------------------------------------------------------------
# Candidate persistence
# ---------------------------------------------------------------------------

def delete_candidates_for_news(
    conn,
    news_id: int,
) -> None:
    """
    Remove previous generated candidates for one event.

    This keeps the candidate table aligned with the current deterministic
    mapping run.
    """

    sql = """
    DELETE FROM market_news_security_candidates
    WHERE news_id = %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (news_id,))


def insert_candidates(
    conn,
    event: NewsEvent,
    resolution: Resolution,
) -> None:
    """
    Store candidates generated by this mapper.
    """

    if not resolution.candidates:
        return

    normalized_news_name = normalize_company_name(
        event.company_name
    )

    sql = """
    INSERT INTO market_news_security_candidates (
        news_id,
        security_id,
        match_method,
        match_confidence,
        candidate_name,
        normalized_news_name,
        normalized_security_name
    )
    VALUES (
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s
    )
    ON CONFLICT (
        news_id,
        security_id,
        match_method
    )
    DO UPDATE SET
        match_confidence = EXCLUDED.match_confidence,
        candidate_name = EXCLUDED.candidate_name,
        normalized_news_name = EXCLUDED.normalized_news_name,
        normalized_security_name = EXCLUDED.normalized_security_name
    """

    with conn.cursor() as cur:
        for security_id, candidate_name, confidence in resolution.candidates:

            normalized_security_name = normalize_company_name(
                candidate_name
            )

            cur.execute(
                sql,
                (
                    event.news_id,
                    security_id,
                    resolution.mapping_method,
                    confidence,
                    candidate_name,
                    normalized_news_name,
                    normalized_security_name,
                ),
            )


# ---------------------------------------------------------------------------
# Apply mapping
# ---------------------------------------------------------------------------

def update_news_mapping(
    conn,
    event: NewsEvent,
    resolution: Resolution,
    mapped_security: Optional[Security] = None,
) -> None:
    """
    Persist mapping without disturbing an already-valid mapping.

    For a newly resolved mapping, security identity/mapping fields and the
    authoritative security_master.asset_category are persisted together.
    For an existing valid mapping, only asset_category is refreshed from the
    master so the original mapping method/confidence audit is preserved.
    """

    if resolution.status == MAPPED:
        if (
            event.security_id is not None
            and event.mapping_status == MAPPED
            and event.security_id == resolution.security_id
            and mapped_security is not None
        ):
            sql = """
            UPDATE market_news
            SET asset_category = %s
            WHERE news_id = %s
            """
            params = (mapped_security.asset_category, event.news_id)
        else:
            sql = """
            UPDATE market_news
            SET
                security_id = %s,
                mapping_status = 'MAPPED',
                mapping_method = %s,
                mapping_confidence = %s,
                asset_category = %s
            WHERE news_id = %s
            """
            params = (
                resolution.security_id,
                resolution.mapping_method,
                resolution.confidence,
                mapped_security.asset_category if mapped_security is not None else None,
                event.news_id,
            )

    elif resolution.status == AMBIGUOUS:
        sql = """
        UPDATE market_news
        SET
            security_id = NULL,
            mapping_status = 'AMBIGUOUS',
            mapping_method = %s,
            mapping_confidence = %s,
            asset_category = %s
        WHERE news_id = %s
        """
        params = (
            resolution.mapping_method,
            resolution.confidence,
            classify_asset(
                event.company_name,
                extract_bse_scrip_code(event.title) or event.symbol,
            ),
            event.news_id,
        )

    else:
        sql = """
        UPDATE market_news
        SET
            security_id = NULL,
            mapping_status = 'PENDING',
            mapping_method = NULL,
            mapping_confidence = NULL,
            asset_category = %s
        WHERE news_id = %s
        """
        params = (
            classify_asset(
                event.company_name,
                extract_bse_scrip_code(event.title) or event.symbol,
            ),
            event.news_id,
        )

    with conn.cursor() as cur:
        cur.execute(sql, params)


# ---------------------------------------------------------------------------
# Asset classification-only runner
# ---------------------------------------------------------------------------

def classify_assets_only(
    conn,
    events: Sequence[NewsEvent],
    apply_changes: bool,
    progress_every: int = 1000,
) -> Counter:
    """
    Classify STOCK news into market_news.asset_category without touching
    security mapping fields or candidate records.
    """
    counters = Counter()
    total = len(events)

    master_categories: Dict[int, Optional[str]] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT security_id, asset_category FROM security_master"
        )
        for security_id, asset_category in cur.fetchall():
            master_categories[security_id] = asset_category

    sql = """
    UPDATE market_news
    SET asset_category = %s
    WHERE news_id = %s
    """

    for index, event in enumerate(events, start=1):
        if event.news_scope != STOCK_SCOPE:
            counters["SKIPPED_NON_STOCK"] += 1
            continue

        # A mapped event inherits the authoritative category from
        # security_master. Only unresolved events use the legacy fallback.
        if event.security_id is not None and event.security_id in master_categories:
            asset_category = master_categories[event.security_id]
        else:
            code = extract_bse_scrip_code(event.title) or event.symbol
            asset_category = classify_asset(event.company_name, code)

        counters[f"ASSET:{asset_category}"] += 1

        if apply_changes:
            with conn.cursor() as cur:
                cur.execute(sql, (asset_category, event.news_id))

        if progress_every > 0 and index % progress_every == 0:
            if apply_changes:
                conn.commit()
            print(
                f"Progress: {index:,}/{total:,} "
                f"({index / total * 100:.1f}%)"
            )

    if apply_changes:
        conn.commit()

    return counters


# ---------------------------------------------------------------------------
# Mapping runner
# ---------------------------------------------------------------------------

def process_events(
    conn,
    events: Sequence[NewsEvent],
    securities: Sequence[Security],
    apply_changes: bool,
    allow_cross_exchange: bool,
    progress_every: int = 1000,
) -> Counter:
    """
    Process events and return mapping statistics.
    """

    (
        by_security_id,
        by_nse_symbol,
        by_bse_symbol,
        by_nse_name,
        by_bse_name,
        by_nse_alias,
        by_bse_alias,
        by_bse_scrip_code,
        by_name,
    ) = build_security_indexes(securities)

    counters = Counter()

    total = len(events)

    for index, event in enumerate(events, start=1):

        # --------------------------------------------------------------
        # Defensive protection:
        # market-level events should not reach this function because
        # the query selects STOCK only.
        # --------------------------------------------------------------

        if event.news_scope != STOCK_SCOPE:
            counters["SKIPPED_NON_STOCK"] += 1
            continue

        resolution = resolve_security(
            event=event,
            by_security_id=by_security_id,
            by_nse_symbol=by_nse_symbol,
            by_bse_symbol=by_bse_symbol,
            by_nse_name=by_nse_name,
            by_bse_name=by_bse_name,
            by_nse_alias=by_nse_alias,
            by_bse_alias=by_bse_alias,
            by_bse_scrip_code=by_bse_scrip_code,
            by_name=by_name,
            allow_cross_exchange=allow_cross_exchange,
        )

        counters[resolution.status] += 1

        method = resolution.mapping_method or "NONE"

        counters[f"METHOD:{method}"] += 1

        # --------------------------------------------------------------
        # Existing valid mapping
        # --------------------------------------------------------------

        mapped_security = (
            by_security_id.get(resolution.security_id)
            if resolution.status == MAPPED
            else None
        )

        if (
            resolution.status == MAPPED
            and event.security_id == resolution.security_id
            and event.mapping_status == MAPPED
            and mapped_security is not None
            and event.asset_category == mapped_security.asset_category
        ):
            counters["ALREADY_CORRECT"] += 1
        else:
            counters["CHANGED_OR_NEW"] += 1

        # --------------------------------------------------------------
        # Detailed audit output for important unresolved / cross-exchange
        # cases.
        # --------------------------------------------------------------

        if (
            resolution.status != MAPPED
            or resolution.mapping_method == "CROSS_EXCHANGE_NAME"
        ):
            print(
                f"[{resolution.status}] "
                f"news_id={event.news_id} "
                f"exchange={event.exchange} "
                f"symbol={event.symbol} "
                f"company={event.company_name!r} "
                f"security_id={resolution.security_id} "
                f"method={resolution.mapping_method} "
                f"confidence={resolution.confidence} "
                f"reason={resolution.reason}"
            )

        # --------------------------------------------------------------
        # Apply only when explicitly requested.
        # --------------------------------------------------------------

        if apply_changes:
            delete_candidates_for_news(
                conn,
                event.news_id,
            )

            insert_candidates(
                conn,
                event,
                resolution,
            )

            update_news_mapping(
                conn,
                event,
                resolution,
                mapped_security=mapped_security,
            )

        if (
            progress_every > 0
            and index % progress_every == 0
        ):
            if apply_changes:
                conn.commit()

            print(
                f"Progress: {index:,}/{total:,} "
                f"({index / total * 100:.1f}%)"
            )

    if apply_changes:
        conn.commit()

    return counters


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(
    counters: Counter,
    total: int,
    apply_changes: bool,
    allow_cross_exchange: bool,
    classify_only: bool = False,
) -> None:

    print()
    print("=" * 72)
    print("MarketPulse News → Security Mapping Summary")
    print("=" * 72)

    print(f"Mode                  : {'APPLY' if apply_changes else 'DRY-RUN'}")
    print(
        "Cross-exchange match  : "
        f"{'ENABLED' if allow_cross_exchange else 'DISABLED'}"
    )
    print(f"Total events          : {total:,}")
    print()

    if not classify_only:
        print(f"Security-mapping scope : {counters.get('SECURITY_MAPPING_SCOPE', total):,}")
        print(f"Non-equity excluded    : {counters.get('NON_EQUITY_EXCLUDED', 0):,}")
        print()

        print("Unresolved asset classification")
        print("-" * 72)
        unresolved_rows = sorted(
            (
                (key.replace("UNRESOLVED_ASSET:", ""), value)
                for key, value in counters.items()
                if key.startswith("UNRESOLVED_ASSET:")
            ),
            key=lambda item: (-item[1], item[0]),
        )
        for category, count in unresolved_rows:
            print(f"{category:<35} {count:>10,}")
        print()

    print(f"MAPPED                : {counters['MAPPED']:,}")
    print(f"AMBIGUOUS             : {counters['AMBIGUOUS']:,}")
    print(f"PENDING               : {counters['PENDING']:,}")
    print()

    print(f"Already correct       : {counters['ALREADY_CORRECT']:,}")
    if not classify_only:
        print(f"Changed / new         : {counters['CHANGED_OR_NEW']:,}")
        print()

    print("Asset categories")
    print("-" * 72)

    asset_rows = sorted(
        (
            (key.replace("ASSET:", ""), value)
            for key, value in counters.items()
            if key.startswith("ASSET:")
        ),
        key=lambda item: (-item[1], item[0]),
    )

    for category, count in asset_rows:
        print(f"{category:<35} {count:>10,}")

    print()

    if not classify_only:
        print("Mapping methods")
    print("-" * 72)

    if not classify_only:
        method_rows = sorted(
            (
                (key.replace("METHOD:", ""), value)
                for key, value in counters.items()
                if key.startswith("METHOD:")
            ),
            key=lambda item: (-item[1], item[0]),
        )

        for method, count in method_rows:
            print(f"{method:<35} {count:>10,}")

    print("=" * 72)

    if not apply_changes:
        print()
        if classify_only:
            print(
                "DRY-RUN: No asset_category values were changed."
            )
        else:
            print(
                "DRY-RUN: No database mapping fields or candidates were changed."
            )
        print(
            "Use --apply only after reviewing the results."
        )

    print()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Map MarketPulse market_news STOCK events "
            "to security_master securities."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply mapping changes to PostgreSQL. "
            "Without this flag the script is DRY-RUN only."
        ),
    )

    parser.add_argument(
        "--only-unmapped",
        action="store_true",
        help=(
            "Process only events that are not currently mapped "
            "or have no security_id."
        ),
    )

    parser.add_argument(
        "--allow-cross-exchange",
        action="store_true",
        help=(
            "Allow unique normalized company-name matches across exchanges. "
            "Disabled by default."
        ),
    )

    parser.add_argument(
        "--classify-assets-only",
        action="store_true",
        help=(
            "Classify STOCK news into asset_category only. "
            "Does not change security_id, mapping_status, mapping_method, "
            "mapping_confidence, or candidate records."
        ),
    )

    parser.add_argument(
        "--start-id",
        type=int,
        default=None,
        help="Process news_id >= START_ID.",
    )

    parser.add_argument(
        "--end-id",
        type=int,
        default=None,
        help="Process news_id <= END_ID.",
    )

    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N events.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    print()
    print("MarketPulse News → Security Mapping")
    print("------------------------------------")

    if args.classify_assets_only:
        if args.apply:
            print("Mode: ASSET CLASSIFICATION APPLY")
        else:
            print("Mode: ASSET CLASSIFICATION DRY-RUN")
    elif args.apply:
        print("Mode: APPLY")
    else:
        print("Mode: DRY-RUN")

    if args.allow_cross_exchange:
        print("Cross-exchange matching: ENABLED")
    else:
        print("Cross-exchange matching: DISABLED")

    if args.only_unmapped:
        print("Scope: ONLY UNMAPPED")
    else:
        print("Scope: ALL STOCK EVENTS")

    if args.classify_assets_only:
        print("Operation: ASSET CATEGORY ONLY")

    if args.start_id is not None:
        print(f"Start ID: {args.start_id}")

    if args.end_id is not None:
        print(f"End ID: {args.end_id}")

    print()

    conn = None

    try:
        conn = get_db_connection()

        ensure_asset_category_column(conn)
        ensure_candidate_table(conn)

        print("Loading security_master...")

        securities = load_security_master(conn)

        print(
            f"Active securities loaded: {len(securities):,}"
        )

        print("Loading market_news STOCK events...")

        events = load_news_events(
            conn=conn,
            only_unmapped=args.only_unmapped,
            start_id=args.start_id,
            end_id=args.end_id,
        )

        print(
            f"Stock events loaded: {len(events):,}"
        )

        if not args.classify_assets_only:
            if args.only_unmapped:
                unresolved_asset_counts = load_unmapped_asset_counts(conn)
                counters_scope = Counter()
                counters_scope["SECURITY_MAPPING_SCOPE"] = (
                    unresolved_asset_counts.get(ASSET_OTHERS, 0)
                    + unresolved_asset_counts.get("UNCLASSIFIED", 0)
                )
                counters_scope["NON_EQUITY_EXCLUDED"] = (
                    unresolved_asset_counts.get(ASSET_MUTUAL_FUND, 0)
                    + unresolved_asset_counts.get(ASSET_ETF, 0)
                    + unresolved_asset_counts.get(ASSET_BONDS, 0)
                )
                for category, count in unresolved_asset_counts.items():
                    counters_scope[f"UNRESOLVED_ASSET:{category}"] = count
            else:
                counters_scope = Counter({"SECURITY_MAPPING_SCOPE": len(events)})
        else:
            counters_scope = Counter()

        if not events:
            print()
            print("No events found. Nothing to process.")
            return 0

        print()

        if args.classify_assets_only:
            counters = classify_assets_only(
                conn=conn,
                events=events,
                apply_changes=args.apply,
                progress_every=args.progress_every,
            )
        else:
            counters = process_events(
                conn=conn,
                events=events,
                securities=securities,
                apply_changes=args.apply,
                allow_cross_exchange=args.allow_cross_exchange,
                progress_every=args.progress_every,
            )

        counters.update(counters_scope)

        print_summary(
            counters=counters,
            total=len(events),
            apply_changes=args.apply,
            allow_cross_exchange=args.allow_cross_exchange,
            classify_only=args.classify_assets_only,
        )

        return 0

    except KeyboardInterrupt:
        print()
        print("Interrupted by user.")

        if conn is not None:
            conn.rollback()

        return 130

    except Exception as exc:
        if conn is not None:
            conn.rollback()

        print()
        print("ERROR")
        print("-" * 72)
        print(str(exc))
        print()

        return 1

    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())