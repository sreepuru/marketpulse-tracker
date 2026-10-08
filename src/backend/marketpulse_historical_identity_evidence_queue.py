"""
MarketPulse - Historical Identity Evidence Queue V1

Purpose
-------
Turn the historical identity review CSV into a structured evidence queue.

This utility is intentionally read-only:
- no market_news updates
- no security_master updates
- no security_identity inserts
- no automatic historical mapping

It prepares the exact research units that can later be verified against
historical exchange/company evidence.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter


FIELDS = [
    "queue_id",
    "exchange",
    "historical_symbol",
    "historical_name",
    "news_count",
    "sample_news_id",
    "candidate_count",
    "candidate_security_id",
    "candidate_current_symbol",
    "candidate_current_name",
    "existing_evidence",
    "evidence_status",
    "evidence_source",
    "evidence_url",
    "evidence_detail",
    "reviewer",
    "review_notes",
]


def read_review(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def make_queue(rows):
    queue = []

    for i, row in enumerate(rows, start=1):
        queue.append({
            "queue_id": f"HIST-{i:04d}",
            "exchange": row.get("exchange", ""),
            "historical_symbol": row.get("historical_symbol", ""),
            "historical_name": row.get("historical_name", ""),
            "news_count": row.get("news_count", ""),
            "sample_news_id": row.get("sample_news_id", ""),
            "candidate_count": row.get("candidate_count", ""),
            "candidate_security_id": row.get("candidate_security_id", ""),
            "candidate_current_symbol": row.get("candidate_current_symbol", ""),
            "candidate_current_name": row.get("candidate_current_name", ""),
            "existing_evidence": row.get("evidence", ""),
            "evidence_status": "RESEARCH_REQUIRED",
            "evidence_source": "",
            "evidence_url": "",
            "evidence_detail": "",
            "reviewer": "",
            "review_notes": "",
        })

    return queue


def write_queue(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Create a read-only historical identity evidence queue."
    )
    parser.add_argument(
        "--input",
        default="marketpulse_historical_identity_review.csv",
        help="Historical identity review CSV.",
    )
    parser.add_argument(
        "--output",
        default="marketpulse_historical_identity_evidence_queue.csv",
        help="Evidence queue CSV.",
    )
    args = parser.parse_args()

    rows = read_review(args.input)
    queue = make_queue(rows)

    write_queue(args.output, queue)

    status_counts = Counter(r["evidence_status"] for r in queue)

    print("=" * 78)
    print("MARKETPULSE HISTORICAL IDENTITY EVIDENCE QUEUE")
    print("=" * 78)
    print(f"Input rows              : {len(rows):,}")
    print(f"Evidence records created: {len(queue):,}")
    for status, count in sorted(status_counts.items()):
        print(f"{status:<24}: {count:,}")
    print()
    print("READ-ONLY: no database tables were modified.")
    print(f"Queue file              : {os.path.abspath(args.output)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
