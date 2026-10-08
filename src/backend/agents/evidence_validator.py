from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


GENERIC_TOKENS = {
    "LIMITED",
    "LTD",
    "PRIVATE",
    "PVT",
    "PUBLIC",
    "PLC",
    "COMPANY",
    "CORPORATION",
    "CORP",
    "INC",
    "INDIA",
    "INDIAN",
    "THE",
    "AND",
    "OF",
}

NAME_ABBREVIATIONS = {
    "COM": "COMMERCIAL",
    "VE": "VEHICLE",
    "CTR": "CONTROL",
    "SYS": "SYSTEM",
    "IND": "INDIA",
    "LTD": "LIMITED",
    "PVT": "PRIVATE",
    "PUB": "PUBLIC",
    "CORP": "CORPORATION",
    "CO": "COMPANY",
}


@dataclass(frozen=True)
class CandidateEvidence:
    security_id: int
    event_name: str
    candidate_name: str
    name_similarity: float
    token_overlap: tuple[str, ...]
    distinctive_overlap: tuple[str, ...]
    exchange_match: bool
    symbol_match: bool
    isin_match: bool
    bse_scrip_match: bool
    hard_conflicts: tuple[str, ...]
    supporting_evidence: tuple[str, ...]


def normalize_name(value: str | None) -> str:
    if not value:
        return ""

    value = str(value).upper().replace("&", " AND ")
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str | None) -> set[str]:
    normalized = normalize_name(value)

    if not normalized:
        return set()

    result = set()

    for token in normalized.split():
        result.add(NAME_ABBREVIATIONS.get(token, token))

    return result


def distinctive_tokens(value: str | None) -> set[str]:
    return {
        token
        for token in tokens(value)
        if token not in GENERIC_TOKENS and len(token) >= 3
    }


def name_similarity(
    event_name: str | None,
    candidate_name: str | None,
) -> float:
    event_tokens = sorted(tokens(event_name))
    candidate_tokens = sorted(tokens(candidate_name))

    if not event_tokens or not candidate_tokens:
        return 0.0

    event_normalized = " ".join(event_tokens)
    candidate_normalized = " ".join(candidate_tokens)

    return round(
        SequenceMatcher(
            None,
            event_normalized,
            candidate_normalized,
        ).ratio(),
        4,
    )


def _first_value(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def calculate_candidate_evidence(
    event: dict[str, Any],
    candidate: dict[str, Any],
) -> CandidateEvidence:
    event_name = _first_value(
        event.get("company_name"),
        event.get("entity_name"),
        event.get("issuer_name"),
        event.get("title"),
    ) or ""

    candidate_name = _first_value(
        candidate.get("instrument_name"),
        candidate.get("nse_name"),
        candidate.get("bse_name"),
        candidate.get("company_name"),
    ) or ""

    event_tokens = tokens(event_name)
    candidate_tokens = tokens(candidate_name)

    overlap = event_tokens & candidate_tokens
    distinctive_overlap = (
        distinctive_tokens(event_name)
        & distinctive_tokens(candidate_name)
    )

    event_exchange = _first_value(event.get("exchange"))
    candidate_exchange = _first_value(candidate.get("exchange"))

    exchange_match = bool(
        event_exchange
        and candidate_exchange
        and event_exchange.upper() == candidate_exchange.upper()
    )

    event_symbol = _first_value(event.get("symbol"))
    candidate_symbol = _first_value(candidate.get("symbol"))

    symbol_match = bool(
        event_symbol
        and candidate_symbol
        and event_symbol.upper() == candidate_symbol.upper()
    )

    event_isin = _first_value(event.get("isin"))
    candidate_isin = _first_value(candidate.get("isin"))

    isin_match = bool(
        event_isin
        and candidate_isin
        and event_isin.upper() == candidate_isin.upper()
    )

    event_bse = _first_value(event.get("bse_scrip_code"))
    candidate_bse = _first_value(candidate.get("bse_scrip_code"))

    bse_scrip_match = bool(
        event_bse
        and candidate_bse
        and event_bse == candidate_bse
    )

    hard_conflicts: list[str] = []
    supporting: list[str] = []

    # Explicit identifiers are authoritative.
    if event_isin and candidate_isin and not isin_match:
        hard_conflicts.append("ISIN_MISMATCH")

    if event_bse and candidate_bse and not bse_scrip_match:
        hard_conflicts.append("BSE_SCRIP_MISMATCH")

    # An explicitly supplied event symbol is authoritative.
    if event_symbol and candidate_symbol and not symbol_match:
        hard_conflicts.append("SYMBOL_MISMATCH")

    # Exchange agreement is supporting evidence.
    if exchange_match:
        supporting.append("EXCHANGE_MATCH")

    if symbol_match:
        supporting.append("SYMBOL_MATCH")

    if isin_match:
        supporting.append("ISIN_MATCH")

    if bse_scrip_match:
        supporting.append("BSE_SCRIP_MATCH")

    if distinctive_overlap:
        supporting.append(
            "DISTINCTIVE_NAME_TOKEN_OVERLAP"
        )

    similarity = name_similarity(event_name, candidate_name)

    if similarity >= 0.85:
        supporting.append("STRONG_NAME_SIMILARITY")
    elif similarity >= 0.70:
        supporting.append("MODERATE_NAME_SIMILARITY")

    # IMPORTANT:
    # event asset_category == OTHER is treated as unresolved/unknown.
    # It is NOT a hard contradiction against a security-master EQUITY.
    event_asset = _first_value(event.get("asset_category"))
    candidate_asset = _first_value(candidate.get("asset_category"))

    if (
        event_asset
        and event_asset.upper() != "OTHER"
        and candidate_asset
        and event_asset.upper() != candidate_asset.upper()
    ):
        hard_conflicts.append("ASSET_CATEGORY_MISMATCH")

    return CandidateEvidence(
        security_id=int(candidate["security_id"]),
        event_name=event_name,
        candidate_name=candidate_name,
        name_similarity=similarity,
        token_overlap=tuple(sorted(overlap)),
        distinctive_overlap=tuple(sorted(distinctive_overlap)),
        exchange_match=exchange_match,
        symbol_match=symbol_match,
        isin_match=isin_match,
        bse_scrip_match=bse_scrip_match,
        hard_conflicts=tuple(hard_conflicts),
        supporting_evidence=tuple(supporting),
    )


def validate_candidate(
    evidence: CandidateEvidence,
) -> dict[str, Any]:
    """
    Initial shadow-mode deterministic gate.

    This is intentionally conservative and is NOT yet the production
    mapping threshold.

    A candidate can be considered MATCH-ELIGIBLE when:
      - there is no hard contradiction, and
      - there is either a strong identifier match, or
        strong issuer-name similarity plus exchange agreement.

    Generic lexical similarity alone is insufficient.
    """

    if evidence.hard_conflicts:
        return {
            "decision": "REJECT",
            "security_id": evidence.security_id,
            "reason": "HARD_CONFLICT",
            "hard_conflicts": list(evidence.hard_conflicts),
            "supporting_evidence": list(evidence.supporting_evidence),
        }

    strong_identifier = (
        evidence.isin_match
        or evidence.bse_scrip_match
        or (
            evidence.symbol_match
            and evidence.exchange_match
        )
    )

    strong_name_match = (
        evidence.name_similarity >= 0.85
        and evidence.exchange_match
    )

    if strong_identifier or strong_name_match:
        return {
            "decision": "MATCH_ELIGIBLE",
            "security_id": evidence.security_id,
            "reason": (
                "STRONG_IDENTIFIER"
                if strong_identifier
                else "STRONG_NAME_AND_EXCHANGE"
            ),
            "hard_conflicts": [],
            "supporting_evidence": list(
                evidence.supporting_evidence
            ),
        }

    return {
        "decision": "ABSTAIN",
        "security_id": evidence.security_id,
        "reason": "INSUFFICIENT_EVIDENCE",
        "hard_conflicts": [],
        "supporting_evidence": list(
            evidence.supporting_evidence
        ),
    }
