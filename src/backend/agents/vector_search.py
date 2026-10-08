"""
MarketPulse vector candidate search.

Purpose:
- Accept arbitrary identity/news text.
- Generate an embedding using Ollama.
- Search security_embeddings using pgvector.
- Aggregate identity hits to security-level candidates.
- Never modify security_master.
- Never assign a canonical security_id.

Run from project root:

    python -m backend.agents.vector_search "SGBJUN28"

    python -m backend.agents.vector_search \
        "Sovereign Gold Bonds 2020-21 S"

    python -m backend.agents.vector_search \
        "2.5% Gold Bonds 2028 Series III" --limit 10
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict

import psycopg2

from backend.agents.ollama_embeddings import OllamaEmbeddingClient


EMBEDDING_DIMENSION = 768


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


def validate_embedding(embedding: list[float]) -> None:
    if len(embedding) != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Unexpected embedding dimension: "
            f"{len(embedding)}; expected {EMBEDDING_DIMENSION}"
        )


def vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def search_identity_hits(
    conn,
    embedding: list[float],
    limit: int,
):
    vector_value = vector_literal(embedding)

    sql = """
        WITH query_embedding AS (
            SELECT %s::vector AS embedding
        )
        SELECT
            se.security_id,
            se.identity_type,
            se.identity_text,
            (se.embedding <=> query_embedding.embedding) AS distance,
            sm.isin,
            sm.symbol,
            sm.exchange,
            sm.exchange_tag,
            sm.instrument_name
        FROM security_embeddings se
        CROSS JOIN query_embedding
        LEFT JOIN security_master sm
            ON sm.security_id = se.security_id
        ORDER BY se.embedding <=> query_embedding.embedding
        LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (vector_value, int(limit)))
        return cur.fetchall()


def aggregate_security_candidates(rows):
    """
    Collapse identity-level vector hits into security-level candidates.

    This function does NOT decide whether a security is the correct match.

    It only records:
    - best vector distance
    - all identity hits returned for that security
    - canonical metadata available from security_master
    """

    candidates = {}

    for row in rows:
        (
            security_id,
            identity_type,
            identity_text,
            distance,
            isin,
            symbol,
            exchange,
            exchange_tag,
            instrument_name,
        ) = row

        if security_id not in candidates:
            candidates[security_id] = {
                "security_id": security_id,
                "isin": isin,
                "symbol": symbol,
                "exchange": exchange,
                "exchange_tag": exchange_tag,
                "instrument_name": instrument_name,
                "best_distance": float(distance),
                "identity_hits": [],
            }

        candidate = candidates[security_id]

        distance_value = float(distance)

        if distance_value < candidate["best_distance"]:
            candidate["best_distance"] = distance_value

        candidate["identity_hits"].append(
            {
                "identity_type": identity_type,
                "identity_text": identity_text,
                "distance": distance_value,
            }
        )

    return sorted(
        candidates.values(),
        key=lambda candidate: candidate["best_distance"],
    )


def print_results(
    query: str,
    raw_hits,
    candidates,
) -> None:
    print()
    print("=" * 78)
    print("MARKETPULSE VECTOR SECURITY CANDIDATES")
    print("=" * 78)
    print(f"Query              : {query}")
    print(f"Identity hits      : {len(raw_hits)}")
    print(f"Security candidates: {len(candidates)}")
    print()

    if not candidates:
        print("No vector candidates found.")
        return

    for rank, candidate in enumerate(candidates, start=1):
        print(
            f"[Candidate {rank}] "
            f"best_distance={candidate['best_distance']:.6f}"
        )

        print(
            f"    security_id    : "
            f"{candidate['security_id']}"
        )
        print(
            f"    ISIN           : "
            f"{candidate['isin']}"
        )
        print(
            f"    symbol         : "
            f"{candidate['symbol']}"
        )
        print(
            f"    exchange       : "
            f"{candidate['exchange']}"
        )
        print(
            f"    exchange_tag   : "
            f"{candidate['exchange_tag']}"
        )
        print(
            f"    instrument     : "
            f"{candidate['instrument_name']}"
        )

        print("    identity hits  :")

        for hit in sorted(
            candidate["identity_hits"],
            key=lambda item: item["distance"],
        ):
            print(
                f"        {hit['identity_type']}"
                f" | distance={hit['distance']:.6f}"
                f" | {hit['identity_text']}"
            )

        print()


def parse_args():
    parser = argparse.ArgumentParser(
        description="MarketPulse vector security candidate search"
    )

    parser.add_argument(
        "query",
        help="Text to embed and search",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of identity hits retrieved",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.limit <= 0:
        raise ValueError(
            "--limit must be greater than zero"
        )

    print("=" * 78)
    print("MARKETPULSE VECTOR CANDIDATE SEARCH")
    print("=" * 78)
    print(f"Query              : {args.query}")
    print(
        "Embedding model    : "
        f"{os.getenv('MARKETPULSE_EMBEDDING_MODEL', 'nomic-embed-text')}"
    )
    print(
        f"Embedding dimension: {EMBEDDING_DIMENSION}"
    )
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

        print_results(
            query=args.query,
            raw_hits=raw_hits,
            candidates=candidates,
        )

    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()