from __future__ import annotations

import json
import sys
from typing import Any

from psycopg2.extras import RealDictCursor

from .agent import (
    extract_identity,
    verify_candidates_shadow,
    _deterministic_precheck,
)

from .ollama_client import OllamaClient, OllamaConfig
from .marketpulse_mapping_agent_v2_2 import (
    build_indexes,
    connect,
    load_identity_groups,
    load_securities,
    retrieve_candidates,
)


NEWS_IDS = [4, 6, 7, 8, 11]


def load_events(conn, news_ids: list[int]) -> dict[int, dict[str, Any]]:
    sql = """
        SELECT
            news_id,
            exchange,
            symbol,
            security_id,
            company_name,
            category,
            title,
            description,
            published_at,
            mapping_status,
            asset_category
        FROM market_news
        WHERE news_id = ANY(%s)
        ORDER BY news_id
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (news_ids,))
        rows = cur.fetchall()

    return {int(row["news_id"]): dict(row) for row in rows}


def candidate_to_dict(candidate, security_by_id) -> dict[str, Any]:
    security = security_by_id.get(candidate.security_id)

    if security is None:
        raise RuntimeError(
            f"Candidate security_id={candidate.security_id} "
            "was not found in security_master."
        )

    # Only send actual security_master evidence to the LLM.
    # Retrieval metadata is included separately and is NOT treated as
    # event evidence.
    return {
        "security_id": security.security_id,
        "isin": security.isin,
        "symbol": security.symbol,
        "instrument_name": security.instrument_name,
        "exchange": security.exchange,
        "nse_symbol": security.nse_symbol,
        "nse_name": security.nse_name,
        "nse_short_name": security.nse_short_name,
        "nse_alias": security.nse_alias,
        "bse_symbol": security.bse_symbol,
        "bse_name": security.bse_name,
        "bse_short_name": security.bse_short_name,
        "bse_alias": security.bse_alias,
        "bse_scrip_code": security.bse_scrip_code,
        "exchange_tag": security.exchange_tag,
        "asset_category": security.asset_category,
        "is_active": security.is_active,

        # Retrieval evidence is explicitly labelled as retrieval evidence.
        "retrieval": {
            "method": candidate.method,
            "score": candidate.score,
            "candidate_status": candidate.candidate_status,
            "evidence": candidate.evidence,
        },
    }


def main() -> None:
    print("=" * 80)
    print("MARKETPULSE — FIVE EVENT SHADOW VERIFICATION")
    print("=" * 80)
    print()
    print("News IDs:", NEWS_IDS)
    print("Mode: SHADOW ONLY")
    print("Database writes: NONE")
    print("Vector retrieval: DISABLED FOR THIS TEST")
    print()

    # DeepSeek previously needed more than the default 120 seconds for
    # richer verifier prompts, so use a 300-second timeout for this test.
    client = OllamaClient(
        OllamaConfig(
            timeout_seconds=300,
        )
    )

    conn = connect()

    try:
        events = load_events(conn, NEWS_IDS)

        if len(events) != len(NEWS_IDS):
            missing = sorted(set(NEWS_IDS) - set(events))
            raise RuntimeError(
                f"Missing requested news IDs: {missing}"
            )

        groups = load_identity_groups(conn)

        group_by_news_id = {}

        for group in groups:
            for news_id in group.news_ids:
                if news_id in NEWS_IDS:
                    group_by_news_id[news_id] = group

        securities = load_securities(conn)
        indexes = build_indexes(securities)
        security_by_id = indexes["by_id"]

        print(f"Active securities loaded: {len(securities):,}")
        print()

        results = []

        for news_id in NEWS_IDS:
            event = events[news_id]
            group = group_by_news_id.get(news_id)

            print("-" * 80)
            print(f"NEWS ID: {news_id}")
            print(f"Company : {event.get('company_name')}")
            print(f"Exchange: {event.get('exchange')}")
            print(f"Title   : {event.get('title')}")
            print()

            if group is None:
                print("No unresolved identity group found.")
                print("Skipping.")
                continue

            # ----------------------------------------------------------
            # 1. Gemma identity extraction
            # ----------------------------------------------------------
            print("1. Gemma identity extraction...")

            identity = extract_identity(
                client,
                event,
            )

            print(
                json.dumps(
                    identity,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

            # ----------------------------------------------------------
            # 2. Existing V2.2 deterministic candidate retrieval
            # ----------------------------------------------------------
            print()
            print("2. V2.2 deterministic candidate retrieval...")

            deterministic_candidates = retrieve_candidates(
                conn,
                group,
                indexes,
                max_candidates=10,
            )

            print(
                f"Candidates retrieved: "
                f"{len(deterministic_candidates)}"
            )

            candidates = [
                candidate_to_dict(
                    candidate,
                    security_by_id,
                )
                for candidate in deterministic_candidates
            ]

            for candidate in candidates:
                print(
                    "  "
                    f"{candidate['security_id']}: "
                    f"{candidate['instrument_name']} | "
                    f"{candidate['exchange']} | "
                    f"method={candidate['retrieval']['method']} | "
                    f"score={candidate['retrieval']['score']}"
                )

            # ----------------------------------------------------------
            # 3. DeepSeek + deterministic safety validation
            # ----------------------------------------------------------
            print()
            print("3. Deterministic precheck...")

            deterministic = _deterministic_precheck(
                event=event,
                identity=identity,
                candidates=candidates,
            )

            print(
                json.dumps(
                    deterministic,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

            if deterministic.get("requires_llm"):
                print()
                print("4. DeepSeek candidate verification...")

                shadow = verify_candidates_shadow(
                    client=client,
                    event=event,
                    identity=identity,
                    candidates=candidates,
                )
            else:
                print()
                print("4. DeepSeek candidate verification: SKIPPED")
                
                shadow = {
                    "llm_decision": None,
                    "llm_security_id": None,
                    "llm_confidence": None,
                    "validated_decision": deterministic["decision"],
                    "validated_security_id": deterministic["security_id"],
                    "safe_to_apply": False,
                    "requires_llm": False,
                    "candidate_security_ids": [
                        c["security_id"]
                        for c in candidates
                    ],
                    "deterministic_evidence": deterministic[
                        "deterministic_evidence"
                    ],
                    "reason": deterministic["reason"],
                    "llm_result": None,
                }

            print()
            print("SHADOW RESULT:")
            print(
                json.dumps(
                    shadow,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

            results.append(
                {
                    "news_id": news_id,
                    "company_name": event.get("company_name"),
                    "identity": identity,
                    "candidate_security_ids": [
                        c["security_id"]
                        for c in candidates
                    ],
                    "shadow": shadow,
                }
            )

            print()

        # --------------------------------------------------------------
        # Final compact report
        # --------------------------------------------------------------
        print()
        print("=" * 80)
        print("FINAL SHADOW SUMMARY")
        print("=" * 80)

        for result in results:
            shadow = result["shadow"]

            print(
                f"news_id={result['news_id']} | "
                f"LLM={shadow.get('llm_decision')} "
                f"{shadow.get('llm_security_id')} | "
                f"VALIDATED={shadow.get('validated_decision')} "
                f"{shadow.get('validated_security_id')} | "
                f"SAFE_TO_APPLY={shadow.get('safe_to_apply')}"
            )

        print()
        print("DATABASE WRITES: NONE")
        print("=" * 80)

        # Intentionally do not persist `results`.
        # This first run is a console-only shadow experiment.

    finally:
        conn.close()


if __name__ == "__main__":
    main()