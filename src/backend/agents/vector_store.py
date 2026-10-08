"""
MarketPulse vector identity store.

Phase 1 responsibilities:
- Read identity fields from security_master.
- Generate embeddings through Ollama.
- Store embeddings in security_embeddings.
- Never modify security_master.
- Never make canonical mapping decisions.

Run from project root:

    python -m backend.agents.vector_store --limit 5 --dry-run

    python -m backend.agents.vector_store --limit 5

"""

from __future__ import annotations

import argparse
import os
from typing import Any

import psycopg2

from backend.agents.ollama_embeddings import OllamaEmbeddingClient


EMBEDDING_DIMENSION = 768


def connect():
    """Create a PostgreSQL connection using the existing MarketPulse pattern."""
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


def load_identities(conn, limit: int) -> list[dict[str, Any]]:
    """
    Load the first active securities and their currently populated
    identity fields.

    We intentionally use only fields that currently contain data.
    """

    sql = """
        SELECT
            security_id,
            instrument_name,
            bse_name,
            bse_symbol
        FROM security_master
        WHERE is_active = TRUE
        ORDER BY security_id
        LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (int(limit),))
        rows = cur.fetchall()

    identities: list[dict[str, Any]] = []

    for security_id, instrument_name, bse_name, bse_symbol in rows:

        if instrument_name:
            identities.append(
                {
                    "security_id": security_id,
                    "identity_type": "INSTRUMENT_NAME",
                    "identity_text": str(instrument_name).strip(),
                    "source": "security_master.instrument_name",
                }
            )

        if bse_name:
            identities.append(
                {
                    "security_id": security_id,
                    "identity_type": "BSE_NAME",
                    "identity_text": str(bse_name).strip(),
                    "source": "security_master.bse_name",
                }
            )

        if bse_symbol:
            identities.append(
                {
                    "security_id": security_id,
                    "identity_type": "BSE_SYMBOL",
                    "identity_text": str(bse_symbol).strip(),
                    "source": "security_master.bse_symbol",
                }
            )

    return identities


def validate_embedding(embedding: list[float]) -> None:
    """Ensure Ollama returned the expected vector dimension."""

    if len(embedding) != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Unexpected embedding dimension: "
            f"{len(embedding)}; expected {EMBEDDING_DIMENSION}"
        )


def insert_embedding(
    conn,
    security_id: int,
    identity_type: str,
    identity_text: str,
    embedding: list[float],
    source: str,
) -> None:
    """Insert one identity embedding."""

    sql = """
        INSERT INTO security_embeddings (
            security_id,
            identity_type,
            identity_text,
            embedding,
            source
        )
        VALUES (%s, %s, %s, %s::vector, %s)
    """

    vector_value = "[" + ",".join(str(x) for x in embedding) + "]"

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                security_id,
                identity_type,
                identity_text,
                vector_value,
                source,
            ),
        )


def already_indexed(
    conn,
    security_id: int,
    identity_type: str,
    identity_text: str,
) -> bool:
    """Check whether this exact identity already has an embedding."""

    sql = """
        SELECT 1
        FROM security_embeddings
        WHERE security_id = %s
          AND identity_type = %s
          AND identity_text = %s
        LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                security_id,
                identity_type,
                identity_text,
            ),
        )

        return cur.fetchone() is not None


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="MarketPulse security identity vector indexer"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of securities to process",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate embeddings but do not write them to PostgreSQL",
    )

    return parser.parse_args()


def main():

    args = parse_args()

    if args.limit <= 0:
        raise ValueError("--limit must be greater than zero")

    print("=" * 70)
    print("MARKETPULSE VECTOR IDENTITY INDEXER")
    print("=" * 70)
    print(f"Securities requested : {args.limit}")
    print(f"Dry run              : {args.dry_run}")
    print(f"Embedding model      : {os.getenv('MARKETPULSE_EMBEDDING_MODEL', 'nomic-embed-text')}")
    print(f"Embedding dimension   : {EMBEDDING_DIMENSION}")
    print()

    client = OllamaEmbeddingClient()

    conn = connect()

    try:
        identities = load_identities(conn, args.limit)

        print(f"Identity records found: {len(identities)}")
        print()

        inserted = 0
        skipped = 0

        for item in identities:

            security_id = item["security_id"]
            identity_type = item["identity_type"]
            identity_text = item["identity_text"]
            source = item["source"]

            print(
                f"[{identity_type}] "
                f"security_id={security_id} "
                f"text={identity_text}"
            )

            if already_indexed(
                conn,
                security_id,
                identity_type,
                identity_text,
            ):
                print("  -> already indexed; skipped")
                skipped += 1
                continue

            embedding = client.embed(identity_text)

            validate_embedding(embedding)

            print(
                f"  -> embedding generated: {len(embedding)} dimensions"
            )

            if args.dry_run:
                print("  -> DRY RUN: not written")
                continue

            insert_embedding(
                conn,
                security_id,
                identity_type,
                identity_text,
                embedding,
                source,
            )

            conn.commit()

            print("  -> stored")
            inserted += 1

        print()
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Identity records : {len(identities)}")
        print(f"Inserted         : {inserted}")
        print(f"Skipped          : {skipped}")
        print(f"Dry run          : {args.dry_run}")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()