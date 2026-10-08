"""
MarketPulse Vector Evidence Bundle
----------------------------------

Builds an auditable evidence bundle from:

1. Vector/RAG retrieval
2. Candidate aggregation
3. Canonical security_master verification

Design principles:
- security_master remains the canonical source
- vector similarity is retrieval evidence only
- no security_id assignment is performed here
- no writes are performed
- ambiguous results remain REVIEW
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2

from backend.agents.ollama_embeddings import OllamaEmbeddingClient
from backend.agents.vector_search import (
    aggregate_security_candidates,
    search_identity_hits,
)
from backend.agents.vector_candidate_verifier import (
    resolve_results,
    verify_candidates,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = os.getenv(
    "MARKETPULSE_EMBEDDING_MODEL",
    "nomic-embed-text",
)

EMBEDDING_DIMENSION = 768


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def connect():
    """
    Open a PostgreSQL connection.

    This module performs read-only operations only.
    """

    password = os.getenv("MARKETPULSE_DB_PASSWORD")

    if not password:
        raise RuntimeError(
            "MARKETPULSE_DB_PASSWORD environment variable is required."
        )

    return psycopg2.connect(
        host=os.getenv("MARKETPULSE_DB_HOST", "localhost"),
        port=int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
        dbname=os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
        user=os.getenv("MARKETPULSE_DB_USER", "postgres"),
        password=password,
    )


# ---------------------------------------------------------------------------
# Canonical security lookup
# ---------------------------------------------------------------------------

def load_security(
    conn,
    security_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Load canonical security identity from security_master.
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
            valid_from,
            valid_to,
            is_active,
            nse_name,
            nse_short_name,
            nse_alias,
            nse_symbol,
            bse_name,
            bse_short_name,
            bse_alias,
            bse_symbol,
            bse_scrip_code,
            exchange_tag,
            asset_category
        FROM security_master
        WHERE security_id = %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (security_id,))
        row = cur.fetchone()

        if row is None:
            return None

        columns = [description[0] for description in cur.description]

    return dict(zip(columns, row))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize_value(value: Any) -> Any:
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


def serialize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: serialize_value(value)
        for key, value in record.items()
    }


# ---------------------------------------------------------------------------
# Canonical identity evidence
# ---------------------------------------------------------------------------

def build_canonical_identity_evidence(
    security: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Preserve the canonical identity fields exactly as stored
    in security_master.

    Missing exchange-specific fields remain null.
    """

    return {
        "security_id": security.get("security_id"),
        "isin": security.get("isin"),
        "symbol": security.get("symbol"),
        "series": security.get("series"),
        "instrument_name": security.get("instrument_name"),
        "exchange": security.get("exchange"),
        "exchange_tag": security.get("exchange_tag"),

        "nse": {
            "name": security.get("nse_name"),
            "short_name": security.get("nse_short_name"),
            "alias": security.get("nse_alias"),
            "symbol": security.get("nse_symbol"),
        },

        "bse": {
            "name": security.get("bse_name"),
            "short_name": security.get("bse_short_name"),
            "alias": security.get("bse_alias"),
            "symbol": security.get("bse_symbol"),
            "scrip_code": security.get("bse_scrip_code"),
        },

        "validity": {
            "valid_from": serialize_value(
                security.get("valid_from")
            ),
            "valid_to": serialize_value(
                security.get("valid_to")
            ),
            "is_active": security.get("is_active"),
        },

        "instrument": {
            "instrument_id": security.get("instrument_id"),
            "instrument_type": security.get("instrument_type"),
            "asset_category": security.get("asset_category"),
            "segment": security.get("segment"),
            "security_category": security.get(
                "security_category"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Identity retrieval evidence
# ---------------------------------------------------------------------------

def build_identity_hit_evidence(
    identity_hits: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Preserve vector retrieval evidence.

    Distance is retrieval evidence only.
    It is NOT converted into a confidence score.
    """

    evidence = []

    for hit in identity_hits:
        evidence.append(
            {
                "identity_type": hit.get(
                    "identity_type"
                ),
                "identity_text": hit.get(
                    "identity_text"
                ),
                "distance": hit.get(
                    "distance"
                ),
            }
        )

    return evidence


# ---------------------------------------------------------------------------
# Candidate evidence
# ---------------------------------------------------------------------------

def build_candidate_evidence(
    conn,
    candidate: Dict[str, Any],
    verification_candidate: Optional[Dict[str, Any]],
) -> Dict[str, Any]:

    security_id = candidate.get("security_id")

    security = load_security(
        conn,
        security_id,
    )

    if security is None:
        return {
            "security_id": security_id,
            "status": "INVALID_CANONICAL_REFERENCE",
            "reason": (
                "The vector candidate references a "
                "security_id that does not exist in "
                "security_master."
            ),
            "vector_evidence": {
                "best_distance": candidate.get(
                    "best_distance"
                ),
                "identity_hits": build_identity_hit_evidence(
                    candidate.get("identity_hits", [])
                ),
            },
        }

    verification_candidate = (
        verification_candidate or {}
    )

    return {
        "security_id": security_id,

        "status": verification_candidate.get(
            "status",
            "REVIEW",
        ),

        "verification": {
            "matched_field": verification_candidate.get(
                "matched_field"
            ),
            "matched_value": verification_candidate.get(
                "matched_value"
            ),
            "reason": verification_candidate.get(
                "reason"
            ),
        },

        "vector_evidence": {
            "best_distance": candidate.get(
                "best_distance"
            ),
            "identity_hits": build_identity_hit_evidence(
                candidate.get("identity_hits", [])
            ),
        },

        "canonical_identity":
            build_canonical_identity_evidence(
                security
            ),
    }


# ---------------------------------------------------------------------------
# Evidence Bundle
# ---------------------------------------------------------------------------

def build_evidence_bundle(
    query: str,
    candidates: List[Dict[str, Any]],
    verification_results: List[Dict[str, Any]],
    verification_result: Dict[str, Any],
) -> Dict[str, Any]:

    conn = connect()

    try:
        verification_by_security_id = {
            item.get("security_id"): item
            for item in verification_results
        }

        candidate_evidence = []

        for candidate in candidates:

            security_id = candidate.get(
                "security_id"
            )

            candidate_evidence.append(
                build_candidate_evidence(
                    conn=conn,
                    candidate=candidate,
                    verification_candidate=
                        verification_by_security_id.get(
                            security_id
                        ),
                )
            )

    finally:
        conn.close()

    return {
        "evidence_bundle_version": "1.0",

        "created_at":
            datetime.now(timezone.utc).isoformat(),

        "query": query,

        "retrieval": {
            "method":
                "pgvector_cosine_distance",

            "embedding_provider":
                "Ollama",

            "embedding_model":
                EMBEDDING_MODEL,

            "embedding_dimension":
                EMBEDDING_DIMENSION,

            "candidate_count":
                len(candidates),
        },

        "canonical_source": {
            "table":
                "security_master",

            "role":
                "canonical_security_identity",
        },

        "resolution": {
            "status":
                verification_result.get(
                    "overall_status"
                ),

            "reason":
                verification_result.get(
                    "reason"
                ),
        },

        "candidates":
            candidate_evidence,

        "rules": {
            "vector_similarity_is_canonical_proof":
                False,

            "security_master_is_canonical":
                True,

            "writes_performed":
                False,

            "security_id_assigned":
                False,
        },
    }


# ---------------------------------------------------------------------------
# Main evidence pipeline
# ---------------------------------------------------------------------------

def generate_evidence_bundle(
    query: str,
    limit: int = 10,
) -> Dict[str, Any]:

    if not query or not query.strip():
        raise ValueError(
            "Query cannot be empty."
        )

    # --------------------------------------------------
    # 1. Generate query embedding
    # --------------------------------------------------

    embedding_client = OllamaEmbeddingClient(
        model=EMBEDDING_MODEL
    )

    embedding = embedding_client.embed(
        query.strip()
    )

    if len(embedding) != EMBEDDING_DIMENSION:
        raise RuntimeError(
            "Unexpected embedding dimension: "
            f"{len(embedding)}; expected "
            f"{EMBEDDING_DIMENSION}"
        )

    # --------------------------------------------------
    # 2. Vector retrieval
    # --------------------------------------------------

    conn = connect()

    try:

        identity_hits = search_identity_hits(
            conn=conn,
            embedding=embedding,
            limit=limit,
        )

    finally:
        conn.close()

    # --------------------------------------------------
    # 3. Security-level aggregation
    # --------------------------------------------------

    candidates = aggregate_security_candidates(
        identity_hits
    )

    # --------------------------------------------------
    # 4. Canonical verification
    # --------------------------------------------------

    verification_conn = connect()
    try:
        verification_results = verify_candidates(
            verification_conn,
            query,
            candidates,
        )
    finally:
        verification_conn.close()

    verification_result = resolve_results(
        verification_results
    )

    # --------------------------------------------------
    # 5. Build auditable evidence bundle
    # --------------------------------------------------

    return build_evidence_bundle(
    query=query,
    candidates=candidates,
    verification_results=verification_results,
    verification_result=verification_result,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Build an auditable MarketPulse "
            "vector evidence bundle."
        )
    )

    parser.add_argument(
        "query",
        help="Entity/company/security query text",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help=(
            "Maximum number of vector identity "
            "hits to retrieve"
        ),
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )

    return parser.parse_args()


def main():

    args = parse_args()

    bundle = generate_evidence_bundle(
        query=args.query,
        limit=args.limit,
    )

    if args.pretty:

        print(
            json.dumps(
                bundle,
                indent=2,
                default=serialize_value,
            )
        )

    else:

        print(
            json.dumps(
                bundle,
                default=serialize_value,
            )
        )


if __name__ == "__main__":
    main()