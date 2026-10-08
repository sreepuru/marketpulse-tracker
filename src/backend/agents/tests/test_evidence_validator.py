from agents.evidence_validator import (
    calculate_candidate_evidence,
    validate_candidate,
)


def test_naman_name_match():
    event = {
        "company_name": "Naman Industries Proxima Limited",
        "exchange": "NSE",
        "symbol": None,
        "isin": None,
        "asset_category": "OTHER",
    }

    candidate = {
        "security_id": 2079,
        "instrument_name": "NAMAN INDUSTRE PRXIMA LTD",
        "symbol": "NAMAN",
        "isin": "INE0RJM01010",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)
    result = validate_candidate(evidence)

    assert evidence.exchange_match is True
    assert evidence.name_similarity > 0.85
    assert result["decision"] == "MATCH_ELIGIBLE"


def test_dme_development_is_not_match_eligible():
    event = {
        "company_name": "Dme Development Limited",
        "exchange": "NSE",
        "symbol": None,
        "isin": None,
        "asset_category": "OTHER",
    }

    candidate = {
        "security_id": 910,
        "instrument_name": "EMBASSY DEVELOPMENTS LTD",
        "symbol": "EMBDL",
        "isin": "INE069I01010",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)
    result = validate_candidate(evidence)

    assert evidence.exchange_match is True
    assert evidence.name_similarity < 0.85
    assert result["decision"] == "ABSTAIN"


def test_zf_name_match():
    event = {
        "company_name": "ZF Commercial Vehicle Control Systems India Limited",
        "exchange": "NSE",
        "symbol": None,
        "isin": None,
        "asset_category": "OTHER",
    }

    candidate = {
        "security_id": 3417,
        "instrument_name": "ZF COM VE CTR SYS IND LTD",
        "symbol": "ZFCVINDIA",
        "isin": "INE342J01019",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)
    result = validate_candidate(evidence)

    assert evidence.exchange_match is True
    assert "DISTINCTIVE_NAME_TOKEN_OVERLAP" in evidence.supporting_evidence
    assert result["decision"] == "ABSTAIN" or result["decision"] == "MATCH_ELIGIBLE"


def test_salona_name_match():
    event = {
        "company_name": "Salona Cotspin Limited",
        "exchange": "NSE",
        "symbol": None,
        "isin": None,
        "asset_category": "OTHER",
    }

    candidate = {
        "security_id": 2595,
        "instrument_name": "SALONA COTSPIN LTD.",
        "symbol": "SALONA",
        "isin": "INE498E01010",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)
    result = validate_candidate(evidence)

    assert evidence.exchange_match is True
    assert evidence.name_similarity >= 0.85
    assert "DISTINCTIVE_NAME_TOKEN_OVERLAP" in evidence.supporting_evidence
    assert result["decision"] == "MATCH_ELIGIBLE"


def test_other_asset_category_does_not_create_conflict():
    event = {
        "company_name": "Naman Industries Proxima Limited",
        "exchange": "NSE",
        "asset_category": "OTHER",
    }

    candidate = {
        "security_id": 2079,
        "instrument_name": "NAMAN INDUSTRE PRXIMA LTD",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)

    assert "ASSET_CATEGORY_MISMATCH" not in evidence.hard_conflicts


def test_explicit_isin_mismatch_is_rejected():
    event = {
        "company_name": "Example Company Limited",
        "exchange": "NSE",
        "isin": "INE111111111",
        "asset_category": "EQUITY",
    }

    candidate = {
        "security_id": 9999,
        "instrument_name": "Example Company Limited",
        "exchange": "NSE",
        "isin": "INE222222222",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)
    result = validate_candidate(evidence)

    assert "ISIN_MISMATCH" in evidence.hard_conflicts
    assert result["decision"] == "REJECT"

def test_symbol_match_with_same_exchange_is_match_eligible():
    event = {
        "company_name": "ABC Limited",
        "symbol": "ABC",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    candidate = {
        "security_id": 1001,
        "instrument_name": "ABC LIMITED",
        "symbol": "ABC",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)
    result = validate_candidate(evidence)

    assert evidence.symbol_match is True
    assert evidence.exchange_match is True
    assert result["decision"] == "MATCH_ELIGIBLE"
    assert result["reason"] == "STRONG_IDENTIFIER"


def test_symbol_match_with_different_exchange_is_not_match_eligible():
    event = {
        "company_name": "ABC Limited",
        "symbol": "ABC",
        "exchange": "NSE",
        "asset_category": "EQUITY",
    }

    candidate = {
        "security_id": 1002,
        "instrument_name": "ABC LIMITED",
        "symbol": "ABC",
        "exchange": "BSE",
        "asset_category": "EQUITY",
    }

    evidence = calculate_candidate_evidence(event, candidate)
    result = validate_candidate(evidence)

    assert evidence.symbol_match is True
    assert evidence.exchange_match is False
    assert result["decision"] != "MATCH_ELIGIBLE"   