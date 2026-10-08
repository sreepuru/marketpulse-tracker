"""
MarketPulse canonical verification for vector candidates.

Purpose:
- Accept vector-retrieved security candidates.
- Verify candidates against security_master.
- Use deterministic identity evidence where available.
- Return MATCH, REVIEW, or NO_CANONICAL_MATCH.
- Never modify security_master.
- Never assign a security_id to market_news.

This is a verification layer, not a replacement for the
existing deterministic Mapping Agent.
"""

from __future__ import annotations

import argparse
import os

import psycopg2

from backend.agents.ollama_embeddings import OllamaEmbeddingClient
from backend.agents.vector_search import (
    aggregate_security_candidates,
    search_identity_hits,
    validate_embedding,
)


def connect():
    password = os.getenv("MARKETPULSE_DB_PASSWORD")

    if password is None:
        raise RuntimeError(
            "MARKETPULSE_DB_PASSWORD is not set"
        )

    return psycopg2.connect(
        host=os.getenv("MARKETPULSE_DB_HOST", "localhost"),
        port=int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
        dbname=os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
        user=os.getenv("MARKETPULSE_DB_USER", "postgres"),
        password=password,
    )


def normalize(value: str | None) -> str:
    if not value:
        return ""

    return " ".join(
        value.upper().strip().split()
    )


def load_security(conn, security_id: int):
    sql = """
        SELECT
            security_id,
            isin,
            symbol,
            exchange,
            exchange_tag,
            instrument_name,
            nse_name,
            nse_short_name,
            nse_alias,
            nse_symbol,
            bse_name,
            bse_short_name,
            bse_alias,
            bse_symbol,
            bse_scrip_code
        FROM security_master
        WHERE security_id = %s
          AND is_active = TRUE
        LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(sql, (security_id,))
        return cur.fetchone()


def verify_candidate(
    query: str,
    candidate: dict,
    security_row,
):
    """
    Deterministic verification of one vector candidate.

    Important:
    vector similarity is NOT used as a canonical identity proof.

    Returns:
        {
            "status": "MATCH" | "REVIEW" | "NO_CANONICAL_MATCH",
            ...
        }
    """

    if security_row is None:
        return {
            "status": "NO_CANONICAL_MATCH",
            "security_id": candidate["security_id"],
            "reason": "security_id not found or inactive in security_master",
        }

    (
        security_id,
        isin,
        symbol,
        exchange,
        exchange_tag,
        instrument_name,
        nse_name,
        nse_short_name,
        nse_alias,
        nse_symbol,
        bse_name,
        bse_short_name,
        bse_alias,
        bse_symbol,
        bse_scrip_code,
    ) = security_row

    query_norm = normalize(query)

    exact_fields = [
        ("ISIN", isin),
        ("SYMBOL", symbol),
        ("NSE_SYMBOL", nse_symbol),
        ("BSE_SYMBOL", bse_symbol),
        ("INSTRUMENT_NAME", instrument_name),
        ("NSE_NAME", nse_name),
        ("NSE_SHORT_NAME", nse_short_name),
        ("NSE_ALIAS", nse_alias),
        ("BSE_NAME", bse_name),
        ("BSE_SHORT_NAME", bse_short_name),
        ("BSE_ALIAS", bse_alias),
        ("BSE_SCRIP_CODE", bse_scrip_code),
    ]

    exact_matches = []

    for field_name, field_value in exact_fields:
        if field_value and normalize(str(field_value)) == query_norm:
            exact_matches.append(
                {
                    "field": field_name,
                    "value": field_value,
                }
            )

    if len(exact_matches) == 1:
        match = exact_matches[0]

        return {
            "status": "MATCH",
            "security_id": security_id,
            "isin": isin,
            "symbol": symbol,
            "exchange": exchange,
            "exchange_tag": exchange_tag,
            "matched_field": match["field"],
            "matched_value": match["value"],
            "reason": (
                "exact canonical identity match"
            ),
        }

    if len(exact_matches) > 1:
        return {
            "status": "MATCH",
            "security_id": security_id,
            "isin": isin,
            "symbol": symbol,
            "exchange": exchange,
            "exchange_tag": exchange_tag,
            "matched_field": "MULTIPLE",
            "matched_value": query,
            "reason": (
                "multiple canonical identity fields "
                "match the same security"
            ),
        }

    return {
        "status": "REVIEW",
        "security_id": security_id,
        "isin": isin,
        "symbol": symbol,
        "exchange": exchange,
        "exchange_tag": exchange_tag,
        "matched_field": None,
        "matched_value": None,
        "reason": (
            "vector candidate has no exact canonical "
            "identity match for the supplied query"
        ),
    }


def verify_candidates(
    conn,
    query: str,
    candidates: list[dict],
):
    results = []

    for candidate in candidates:
        security_row = load_security(
            conn,
            candidate["security_id"],
        )

        result = verify_candidate(
            query=query,
            candidate=candidate,
            security_row=security_row,
        )

        result["best_distance"] = candidate[
            "best_distance"
        ]

        result["identity_hits"] = candidate[
            "identity_hits"
        ]

        results.append(result)

    return results

def retrieve_and_verify_vector_candidates(
    conn,
    query: str,
    limit: int = 10,
):
    """
    Retrieve vector candidates and verify them against security_master.

    This function is an orchestration layer only.

    It:
    1. Generates the query embedding.
    2. Validates the embedding dimension.
    3. Retrieves identity-level pgvector hits.
    4. Aggregates them into security-level candidates.
    5. Verifies each candidate against canonical security_master identity.

    It does NOT:
    - modify security_master
    - modify market_news
    - assign security_id
    - make the final Mapping Agent decision
    """

    if not query or not query.strip():
        raise ValueError("query must not be empty")

    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    client = OllamaEmbeddingClient()

    embedding = client.embed(query)

    validate_embedding(embedding)

    raw_hits = search_identity_hits(
        conn=conn,
        embedding=embedding,
        limit=limit,
    )

    vector_candidates = aggregate_security_candidates(
        raw_hits
    )

    verified_candidates = verify_candidates(
        conn=conn,
        query=query,
        candidates=vector_candidates,
    )

    resolution = resolve_results(
        verified_candidates
    )

    return {
        "query": query,
        "embedding_model": os.getenv(
            "MARKETPULSE_EMBEDDING_MODEL",
            "nomic-embed-text",
        ),
        "embedding_dimension": len(embedding),
        "retrieval_source": "pgvector",
        "candidate_count": len(verified_candidates),
        "raw_identity_hit_count": len(raw_hits),
        "candidates": verified_candidates,
        "resolution": resolution,
        "writes": False,
        "security_id_assigned": False,
    }



def resolve_results(results):
    """
    Decide the overall verification outcome.

    Rules:
    - One canonical exact MATCH -> MATCH.
    - Multiple canonical exact MATCH candidates -> REVIEW.
    - No exact match but candidates exist -> REVIEW.
    - No candidates -> NO_CANONICAL_MATCH.
    """

    matches = [
        result
        for result in results
        if result["status"] == "MATCH"
    ]

    if len(matches) == 1:
        result = dict(matches[0])
        result["overall_status"] = "MATCH"
        return result

    if len(matches) > 1:
        return {
            "overall_status": "REVIEW",
            "reason": (
                "multiple vector candidates have "
                "exact canonical identity matches"
            ),
            "matches": matches,
        }

    if results:
        return {
            "overall_status": "REVIEW",
            "reason": (
                "vector candidates were found, but "
                "none has an exact canonical identity match"
            ),
            "candidates": results,
        }

    return {
        "overall_status": "NO_CANONICAL_MATCH",
        "reason": "no vector candidates were retrieved",
    }


def print_results(
    query: str,
    candidates,
    results,
    resolution,
):
    print()
    print("=" * 78)
    print("MARKETPULSE CANONICAL VECTOR VERIFICATION")
    print("=" * 78)
    print(f"Query              : {query}")
    print(f"Vector candidates  : {len(candidates)}")
    print()

    for index, result in enumerate(
        results,
        start=1,
    ):
        print(
            f"[Candidate {index}] "
            f"status={result['status']}"
        )
        print(
            f"    security_id    : "
            f"{result['security_id']}"
        )
        print(
            f"    ISIN           : "
            f"{result['isin']}"
        )
        print(
            f"    symbol         : "
            f"{result['symbol']}"
        )
        print(
            f"    exchange       : "
            f"{result['exchange']}"
        )
        print(
            f"    exchange_tag   : "
            f"{result['exchange_tag']}"
        )
        print(
            f"    distance       : "
            f"{result['best_distance']:.6f}"
        )
        print(
            f"    matched_field  : "
            f"{result['matched_field']}"
        )
        print(
            f"    reason         : "
            f"{result['reason']}"
        )
        print()

    print("=" * 78)
    print(
        f"OVERALL STATUS: "
        f"{resolution['overall_status']}"
    )
    print(
        f"REASON        : "
        f"{resolution['reason']}"
    )
    print("=" * 78)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "MarketPulse vector candidate "
            "canonical verification"
        )
    )

    parser.add_argument(
        "query",
        help="Identity or news text to verify",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum vector identity hits",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.limit <= 0:
        raise ValueError(
            "--limit must be greater than zero"
        )

    print("=" * 78)
    print("MARKETPULSE VECTOR + CANONICAL VERIFIER")
    print("=" * 78)
    print(f"Query              : {args.query}")
    print(
        "Embedding model    : "
        f"{os.getenv('MARKETPULSE_EMBEDDING_MODEL', 'nomic-embed-text')}"
    )
    print("Embedding dimension : 768")
    print(
        f"Identity hit limit : {args.limit}"
    )
    print()

    client = OllamaEmbeddingClient()

    print("Generating query embedding...")

    embedding = client.embed(args.query)

    validate_embedding(embedding)

    print(
        f"Embedding generated: "
        f"{len(embedding)} dimensions"
    )

    conn = None

    try:
        conn = connect()

        print("Searching pgvector...")

        raw_hits = search_identity_hits(
            conn=conn,
            embedding=embedding,
            limit=args.limit,
        )

        candidates = aggregate_security_candidates(
            raw_hits
        )

        print(
            f"Security candidates: "
            f"{len(candidates)}"
        )

        print(
            "Running canonical security_master "
            "verification..."
        )

        results = verify_candidates(
            conn=conn,
            query=args.query,
            candidates=candidates,
        )

        resolution = resolve_results(results)

        print_results(
            query=args.query,
            candidates=candidates,
            results=results,
            resolution=resolution,
        )

    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()