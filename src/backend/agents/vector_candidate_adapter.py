"""
MarketPulse Vector Candidate Adapter
------------------------------------

Converts Vector/RAG evidence into the existing
Mapping Agent V2.2 Candidate contract.

Important:
- This is a candidate adapter only.
- It does NOT perform canonical mapping.
- It does NOT modify market_news.
- It does NOT modify security_master.
- Vector similarity remains retrieval evidence.
- The existing Mapping Agent remains responsible
  for downstream canonical decisioning.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.agents.marketpulse_mapping_agent_v2_2 import (
    Candidate,
    CANDIDATE_INSTRUMENT_FAMILY,
    CANDIDATE_TOKEN_OVERLAP,
    STATUS_NEEDS_REVIEW,
)


VECTOR_METHOD = "VECTOR_RAG"

VECTOR_RETRIEVAL_SCORE_NOTE = (
    "Vector similarity retrieval score only; "
    "not mapping confidence."
)


def _safe_float(value: Any) -> float:
    """
    Convert a retrieval distance into a float.

    pgvector cosine distance:
        lower distance = closer vector match

    The existing Mapping Agent uses higher scores
    as better retrieval ranking, so we convert:

        retrieval_score = 1 - cosine_distance

    This is ONLY a ranking transformation.

    It must not be interpreted as confidence.
    """

    if value is None:
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def vector_distance_to_retrieval_score(
    distance: Any,
) -> float:
    """
    Convert cosine distance to a descending retrieval score.

    Example:

        distance = 0.0
        score    = 1.0

        distance = 0.20
        score    = 0.80

    This is a retrieval ranking score only.
    """

    numeric_distance = _safe_float(distance)

    score = 1.0 - numeric_distance

    return max(0.0, min(1.0, score))


def classify_vector_candidate(
    candidate: Dict[str, Any],
) -> tuple[str, str, str]:
    """
    Classify vector retrieval evidence separately from
    deterministic candidate classifications.

    Vector retrieval does not establish canonical identity.
    """

    return (
        "VECTOR_IDENTITY",
        "vector_identity",
        (
            "Candidate retrieved through vector similarity "
            "to stored security identity. Canonical identity "
            "must be verified independently."
        ),
    )



def build_vector_candidate(
    candidate: Dict[str, Any],
) -> Candidate:
    """
    Convert one Evidence Bundle candidate into
    the existing V2.2 Candidate structure.
    """

    security_id = candidate.get(
        "security_id"
    )

    vector_evidence = candidate.get(
        "vector_evidence",
        {},
    )

    best_distance = vector_evidence.get(
        "best_distance"
    )

    retrieval_score = vector_distance_to_retrieval_score(
        best_distance
    )

    candidate_type, matched_field, match_reason = (
        classify_vector_candidate(candidate)
    )

    evidence = {
        "retrieval_source": "pgvector",
        "retrieval_method": VECTOR_METHOD,
        "embedding_provider": "Ollama",
        "embedding_model": "nomic-embed-text",
        "embedding_dimension": 768,
        "best_distance": best_distance,
        "retrieval_score_note": VECTOR_RETRIEVAL_SCORE_NOTE,
        "identity_hits": vector_evidence.get(
            "identity_hits",
            [],
        ),
        "canonical_status": candidate.get(
            "status"
        ),
        "verification": candidate.get(
            "verification",
            {},
        ),
    }

    return Candidate(
        security_id=int(security_id),
        method=VECTOR_METHOD,
        score=retrieval_score,
        evidence=evidence,
        candidate_type=candidate_type,
        matched_field=matched_field,
        match_reason=match_reason,
        candidate_status=STATUS_NEEDS_REVIEW,
    )


def adapt_evidence_bundle(
    evidence_bundle: Dict[str, Any],
) -> List[Candidate]:
    """
    Convert all Evidence Bundle candidates into
    Mapping Agent V2.2 Candidate objects.

    Candidates remain retrieval candidates.
    """

    candidates = []

    for candidate in evidence_bundle.get(
        "candidates",
        [],
    ):
        candidates.append(
            build_vector_candidate(
                candidate
            )
        )

    return candidates


def merge_candidates(
    deterministic_candidates: List[Candidate],
    vector_candidates: List[Candidate],
    max_candidates: int = 20,
) -> List[Candidate]:
    """
    Merge deterministic and vector candidates.

    If the same security_id is found by both methods,
    retain the deterministic candidate because it has
    the stronger existing retrieval semantics.

    Vector evidence remains available as a separate
    candidate when it identifies a different security.

    No canonical decision is made here.
    """

    merged: Dict[int, Candidate] = {}

    for candidate in deterministic_candidates:
        merged[candidate.security_id] = candidate

    for candidate in vector_candidates:

        existing = merged.get(
            candidate.security_id
        )

        if existing is None:
            merged[
                candidate.security_id
            ] = candidate
            continue

        # Keep the existing deterministic candidate.
        #
        # We deliberately do not combine the two scores
        # because they come from different retrieval
        # systems and are not directly comparable.
        #
        # The vector evidence can be persisted separately
        # in the later integration layer.

    ordered = sorted(
        merged.values(),
        key=lambda candidate: (
            -candidate.score,
            candidate.security_id,
        ),
    )

    return ordered[:max_candidates]