from __future__ import annotations

from agents.agent import validate_llm_verification



def _event() -> dict:
    return {
        "news_id": 4,
        "company_name": "Naman Industries Proxima Limited",
        "symbol": None,
        "exchange": "NSE",
        "category": "ANNOUNCEMENTS",
        "asset_category": "OTHER",
        "title": "Naman Industries Proxima Limited",
        "description": (
            "Naman Industries Proxima Limited has informed the Exchange "
            "about Copy of Newspaper Publication"
        ),
    }


def _identity() -> dict:
    return {
        "entity_name": "Naman Industries Proxima Limited",
        "issuer_name": "Naman Industries Proxima Limited",
        "symbol": None,
        "isin": None,
        "bse_scrip_code": None,
        "instrument_type": "OTHER",
        "asset_category": "OTHER",
        "exchange": "NSE",
        "confidence": 1.0,
    }


def _candidate(
    security_id: int,
    instrument_name: str,
    symbol: str | None = None,
    exchange: str = "NSE",
    asset_category: str = "EQUITY",
) -> dict:
    return {
        "security_id": security_id,
        "instrument_name": instrument_name,
        "symbol": symbol,
        "exchange": exchange,
        "asset_category": asset_category,
        "isin": None,
        "bse_scrip_code": None,
    }


def test_llm_match_with_strong_evidence_is_shadow_eligible():
    candidates = [
        _candidate(
            2079,
            "NAMAN INDUSTRE PRXIMA LTD",
            symbol="NAMAN",
        ),
        _candidate(
            2485,
            "RATNAMANI MET & TUB LTD.",
            symbol="RATNAMANI",
        ),
    ]

    llm_result = {
        "decision": "MATCH",
        "security_id": 2079,
        "confidence": 0.95,
        "evidence": ["Strong company-name match"],
        "contradictions": [],
        "reason": "Candidate matches the issuer identity.",
    }

    result = validate_llm_verification(
        _event(),
        _identity(),
        candidates,
        llm_result,
    )

    assert result["llm_decision"] == "MATCH"
    assert result["llm_security_id"] == 2079
    assert result["validated_decision"] == "MATCH_ELIGIBLE"
    assert result["validated_security_id"] == 2079

    # Shadow mode must never authorize a production write.
    assert result["safe_to_apply"] is False


def test_llm_cannot_select_security_outside_candidate_pool():
    candidates = [
        _candidate(
            2079,
            "NAMAN INDUSTRE PRXIMA LTD",
        ),
    ]

    llm_result = {
        "decision": "MATCH",
        "security_id": 999999,
        "confidence": 1.0,
        "evidence": ["Invented candidate"],
        "contradictions": [],
        "reason": "Invalid test candidate.",
    }

    result = validate_llm_verification(
        _event(),
        _identity(),
        candidates,
        llm_result,
    )

    assert result["validated_decision"] == "ABSTAIN"
    assert result["validated_security_id"] is None
    assert result["safe_to_apply"] is False


def test_llm_match_is_rejected_when_deterministic_validator_abstains():
    candidates = [
        _candidate(
            910,
            "EMBASSY DEVELOPMENTS LTD",
            symbol="EMBASSY",
        ),
    ]

    llm_result = {
        "decision": "MATCH",
        "security_id": 910,
        "confidence": 0.99,
        "evidence": ["Similar company name"],
        "contradictions": [],
        "reason": "LLM believes this is the issuer.",
    }

    result = validate_llm_verification(
        _event(),
        _identity(),
        candidates,
        llm_result,
    )

    assert result["llm_decision"] == "MATCH"
    assert result["llm_security_id"] == 910
    assert result["validated_decision"] == "ABSTAIN"
    assert result["validated_security_id"] is None
    assert result["safe_to_apply"] is False


def test_pending_remains_pending():
    candidates = [
        _candidate(
            910,
            "EMBASSY DEVELOPMENTS LTD",
        ),
    ]

    llm_result = {
        "decision": "PENDING",
        "security_id": None,
        "confidence": 0.40,
        "evidence": [],
        "contradictions": [],
        "reason": "Insufficient evidence.",
    }

    result = validate_llm_verification(
        _event(),
        _identity(),
        candidates,
        llm_result,
    )

    assert result["validated_decision"] == "PENDING"
    assert result["validated_security_id"] is None
    assert result["safe_to_apply"] is False


def test_ambiguous_remains_ambiguous():
    candidates = [
        _candidate(910, "EMBASSY DEVELOPMENTS LTD"),
        _candidate(757, "DEE DEVELOPMENT ENG LTD"),
    ]

    llm_result = {
        "decision": "AMBIGUOUS",
        "security_id": None,
        "confidence": 0.50,
        "evidence": ["Multiple plausible names"],
        "contradictions": [],
        "reason": "Cannot distinguish candidates.",
    }

    result = validate_llm_verification(
        _event(),
        _identity(),
        candidates,
        llm_result,
    )

    assert result["validated_decision"] == "AMBIGUOUS"
    assert result["validated_security_id"] is None
    assert result["safe_to_apply"] is False


def test_invalid_llm_decision_is_normalized_to_pending():
    candidates = [
        _candidate(
            2079,
            "NAMAN INDUSTRE PRXIMA LTD",
        ),
    ]

    llm_result = {
        "decision": "MAGIC_MATCH",
        "security_id": 2079,
        "confidence": 1.0,
        "evidence": [],
        "contradictions": [],
        "reason": "Invalid decision for contract test.",
    }

    result = validate_llm_verification(
        _event(),
        _identity(),
        candidates,
        llm_result,
    )

    assert result["llm_decision"] == "PENDING"
    assert result["validated_decision"] == "PENDING"
    assert result["safe_to_apply"] is False


def test_no_candidates_returns_pending_without_llm():
    from agents.agent import verify_candidates_shadow

    class FailingClient:
        def __getattr__(self, name):
            raise AssertionError(
                "LLM client should not be called when there are no candidates"
            )

    result = verify_candidates_shadow(
        client=FailingClient(),
        event=_event(),
        identity=_identity(),
        candidates=[],
    )

    assert result["validated_decision"] == "PENDING"
    assert result["validated_security_id"] is None
    assert result["safe_to_apply"] is False