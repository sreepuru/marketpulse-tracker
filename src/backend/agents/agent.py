from __future__ import annotations

import json
from typing import Any

from .evidence_validator import calculate_candidate_evidence, validate_candidate
from .ollama_client import OllamaClient, OllamaError
from .prompts import IDENTITY_SYSTEM, VERIFIER_SYSTEM


# DeepSeek verification is slower than the lightweight Gemma
# identity extraction. Keep this timeout local to verification rather
# than changing the global Ollama client timeout.
VERIFIER_TIMEOUT_SECONDS = 15


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "news_id",
        "company_name",
        "symbol",
        "exchange",
        "category",
        "asset_category",
        "title",
        "description",
        "published_at",
    ]

    return {
        k: event.get(k)
        for k in keys
        if event.get(k) not in (None, "")
    }


def _compact_candidates_for_verifier(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Build the controlled candidate payload sent to the verifier.

    Only candidate identity fields are supplied. Retrieval metadata is
    intentionally excluded because retrieval score/method is not identity
    evidence and must not influence the verification decision.
    """
    compact: list[dict[str, Any]] = []

    for candidate in candidates:
        compact.append(
            {
                "security_id": candidate.get("security_id"),
                "instrument_name": candidate.get("instrument_name"),
                "symbol": candidate.get("symbol"),
                "exchange": candidate.get("exchange"),
                "asset_category": candidate.get("asset_category"),
                "isin": candidate.get("isin"),
                "bse_scrip_code": candidate.get("bse_scrip_code"),
            }
        )

    return compact



def extract_identity(
    client: OllamaClient,
    event: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract identity evidence from one market-news event.

    This function does not select a security_id and does not perform
    any database writes.
    """
    prompt = json.dumps(
        {"event": _compact_event(event)},
        ensure_ascii=False,
        default=str,
    )

    return client.generate_json(
        client.config.gemma_model,
        IDENTITY_SYSTEM,
        prompt,
    )

def _deterministic_precheck(
    event: dict[str, Any],
    identity: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Resolve a candidate without using an LLM when deterministic evidence
    independently establishes a unique match.

    This is shadow-only. It never writes to market_news/security_master.
    """
    validator_event = _build_validator_event(event, identity)

    evidence_results = []

    for candidate in candidates:
        security_id = candidate.get("security_id")
        if security_id is None:
            continue

        try:
            security_id_int = int(security_id)
        except (TypeError, ValueError):
            continue

        evidence = calculate_candidate_evidence(
            validator_event,
            candidate,
        )

        validation = validate_candidate(evidence)

        evidence_results.append(
            {
                "security_id": security_id_int,
                "name_similarity": evidence.name_similarity,
                "token_overlap": list(evidence.token_overlap),
                "distinctive_overlap": list(evidence.distinctive_overlap),
                "exchange_match": evidence.exchange_match,
                "symbol_match": evidence.symbol_match,
                "isin_match": evidence.isin_match,
                "bse_scrip_match": evidence.bse_scrip_match,
                "hard_conflicts": list(evidence.hard_conflicts),
                "supporting_evidence": list(evidence.supporting_evidence),
                "validator_decision": validation["decision"],
                "validator_reason": validation["reason"],
            }
        )

    eligible = [
        item
        for item in evidence_results
        if item["validator_decision"] == "MATCH_ELIGIBLE"
    ]

    # Exactly one deterministic match.
    if len(eligible) == 1:
        selected = eligible[0]

        return {
            "decision": "MATCH_ELIGIBLE",
            "security_id": selected["security_id"],
            "safe_to_apply": False,
            "requires_llm": False,
            "deterministic_evidence": evidence_results,
            "reason": (
                "Exactly one candidate independently passed the "
                "deterministic evidence validator."
            ),
        }

    # More than one deterministic match means the evidence does not
    # uniquely identify the security.
    if len(eligible) > 1:
        return {
            "decision": "AMBIGUOUS",
            "security_id": None,
            "safe_to_apply": False,
            "requires_llm": True,
            "deterministic_evidence": evidence_results,
            "reason": (
                "Multiple candidates passed the deterministic evidence "
                "validator; LLM verification is required."
            ),
        }

    # No deterministic match.
    return {
        "decision": "NO_DETERMINISTIC_MATCH",
        "security_id": None,
        "safe_to_apply": False,
        "requires_llm": True,
        "deterministic_evidence": evidence_results,
        "reason": (
            "No candidate independently passed the deterministic "
            "evidence validator."
        ),
    }


def verify_candidates(
    client: OllamaClient,
    event: dict[str, Any],
    identity: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Ask DeepSeek to verify a closed candidate set.

    Only the compact candidate representation is sent to the LLM.

    The LLM is never allowed to introduce a security_id that was not
    supplied in `candidates`.

    This function only performs inference. It does not write to the DB.
    """
    compact_candidates = _compact_candidates_for_verifier(
        candidates
    )

    prompt = json.dumps(
        {
            "event": _compact_event(event),
            "identity": identity,
            "candidates": compact_candidates,
        },
        ensure_ascii=False,
        default=str,
    )

    print(f"VERIFIER PROMPT CHARS: {len(prompt):,}")
    print(f"VERIFIER CANDIDATE COUNT: {len(compact_candidates)}")
    print("VERIFIER MODEL:", client.config.verifier_model)
    print("VERIFIER THINK: False")

    return client.generate_json(
        client.config.verifier_model,
        VERIFIER_SYSTEM,
        prompt,
        timeout=VERIFIER_TIMEOUT_SECONDS,
        think=False,
    )


def _candidate_security_ids(
    candidates: list[dict[str, Any]],
) -> set[int]:
    """
    Return the security IDs available to the LLM.

    Invalid/missing IDs are ignored rather than invented.
    """
    result: set[int] = set()

    for candidate in candidates:
        value = candidate.get("security_id")

        try:
            if value is not None:
                result.add(int(value))
        except (TypeError, ValueError):
            continue

    return result


def _normalize_llm_decision(value: Any) -> str:
    decision = str(value or "").strip().upper()

    allowed = {
        "MATCH",
        "AMBIGUOUS",
        "PENDING",
        "NO_MATCH",
    }

    if decision in allowed:
        return decision

    return "PENDING"


def _normalize_llm_security_id(value: Any) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_validator_event(
    event: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, Any]:
    """
    Combine real event fields with model-extracted identity evidence.

    Event fields remain authoritative when they exist.
    Model output is only supplementary evidence.
    """
    result = dict(event)

    if not result.get("company_name"):
        for key in ("entity_name", "issuer_name"):
            value = identity.get(key)
            if value:
                result["company_name"] = value
                break

    if not result.get("symbol") and identity.get("symbol"):
        result["symbol"] = identity["symbol"]

    if not result.get("exchange") and identity.get("exchange"):
        result["exchange"] = identity["exchange"]

    return result


def validate_llm_verification(
    event: dict[str, Any],
    identity: dict[str, Any],
    candidates: list[dict[str, Any]],
    llm_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Independently validate a DeepSeek verification result.

    The LLM result is never trusted by itself.

    A MATCH is only shadow-eligible when our deterministic evidence
    validator independently considers the selected candidate
    MATCH_ELIGIBLE.

    No database writes occur here.
    """
    candidate_ids = _candidate_security_ids(candidates)

    llm_decision = _normalize_llm_decision(
        llm_result.get("decision")
    )

    llm_security_id = _normalize_llm_security_id(
        llm_result.get("security_id")
    )

    if (
        llm_security_id is not None
        and llm_security_id not in candidate_ids
    ):
        return {
            "llm_decision": llm_decision,
            "llm_security_id": llm_security_id,
            "llm_confidence": llm_result.get("confidence"),
            "validated_decision": "ABSTAIN",
            "validated_security_id": None,
            "safe_to_apply": False,
            "candidate_security_ids": sorted(candidate_ids),
            "deterministic_evidence": [],
            "reason": (
                "LLM selected a security_id that was not present "
                "in the supplied candidate set."
            ),
            "llm_result": llm_result,
        }

    validator_event = _build_validator_event(
        event,
        identity,
    )

    evidence_results: list[dict[str, Any]] = []

    for candidate in candidates:
        security_id = candidate.get("security_id")

        if security_id is None:
            continue

        try:
            security_id_int = int(security_id)
        except (TypeError, ValueError):
            continue

        evidence = calculate_candidate_evidence(
            validator_event,
            candidate,
        )

        validation = validate_candidate(evidence)

        evidence_results.append(
            {
                "security_id": security_id_int,
                "name_similarity": evidence.name_similarity,
                "token_overlap": list(evidence.token_overlap),
                "distinctive_overlap": list(
                    evidence.distinctive_overlap
                ),
                "exchange_match": evidence.exchange_match,
                "symbol_match": evidence.symbol_match,
                "isin_match": evidence.isin_match,
                "bse_scrip_match": evidence.bse_scrip_match,
                "hard_conflicts": list(
                    evidence.hard_conflicts
                ),
                "supporting_evidence": list(
                    evidence.supporting_evidence
                ),
                "validator_decision": validation["decision"],
                "validator_reason": validation["reason"],
            }
        )

    selected_evidence = next(
        (
            item
            for item in evidence_results
            if item["security_id"] == llm_security_id
        ),
        None,
    )

    if llm_decision != "MATCH" or llm_security_id is None:
        return {
            "llm_decision": llm_decision,
            "llm_security_id": llm_security_id,
            "llm_confidence": llm_result.get("confidence"),
            "validated_decision": llm_decision,
            "validated_security_id": None,
            "safe_to_apply": False,
            "candidate_security_ids": sorted(candidate_ids),
            "deterministic_evidence": evidence_results,
            "reason": llm_result.get(
                "reason",
                "LLM did not produce a MATCH decision.",
            ),
            "llm_result": llm_result,
        }

    if selected_evidence is None:
        return {
            "llm_decision": llm_decision,
            "llm_security_id": llm_security_id,
            "llm_confidence": llm_result.get("confidence"),
            "validated_decision": "ABSTAIN",
            "validated_security_id": None,
            "safe_to_apply": False,
            "candidate_security_ids": sorted(candidate_ids),
            "deterministic_evidence": evidence_results,
            "reason": (
                "LLM selected a candidate, but deterministic "
                "candidate evidence could not be calculated."
            ),
            "llm_result": llm_result,
        }

    if (
        selected_evidence["validator_decision"]
        != "MATCH_ELIGIBLE"
    ):
        return {
            "llm_decision": llm_decision,
            "llm_security_id": llm_security_id,
            "llm_confidence": llm_result.get("confidence"),
            "validated_decision": "ABSTAIN",
            "validated_security_id": None,
            "safe_to_apply": False,
            "candidate_security_ids": sorted(candidate_ids),
            "deterministic_evidence": evidence_results,
            "reason": (
                "DeepSeek returned MATCH, but the deterministic "
                "evidence validator did not independently authorize "
                "the candidate."
            ),
            "llm_result": llm_result,
        }

    return {
        "llm_decision": "MATCH",
        "llm_security_id": llm_security_id,
        "llm_confidence": llm_result.get("confidence"),
        "validated_decision": "MATCH_ELIGIBLE",
        "validated_security_id": llm_security_id,
        "safe_to_apply": False,
        "candidate_security_ids": sorted(candidate_ids),
        "deterministic_evidence": evidence_results,
        "reason": (
            "LLM MATCH independently supported by the deterministic "
            "evidence validator. Result remains shadow-only."
        ),
        "llm_result": llm_result,
    }


def verify_candidates_shadow(
    client: OllamaClient,
    event: dict[str, Any],
    identity: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:

    if not candidates:
        return {
            "llm_decision": "PENDING",
            "llm_security_id": None,
            "llm_confidence": None,
            "validated_decision": "PENDING",
            "validated_security_id": None,
            "safe_to_apply": False,
            "requires_llm": False,
            "candidate_security_ids": [],
            "deterministic_evidence": [],
            "reason": "No candidates were supplied for verification.",
            "llm_result": None,
        }

    # ------------------------------------------------------------
    # Stage 1: deterministic evidence validation
    # ------------------------------------------------------------
    deterministic = _deterministic_precheck(
        event=event,
        identity=identity,
        candidates=candidates,
    )

    # Exactly one candidate has strong deterministic evidence.
    # Do NOT spend time on the LLM verifier.
    if (
        deterministic["decision"] == "MATCH_ELIGIBLE"
        and deterministic["security_id"] is not None
    ):
        return {
            "llm_decision": None,
            "llm_security_id": None,
            "llm_confidence": None,
            "validated_decision": "MATCH_ELIGIBLE",
            "validated_security_id": deterministic["security_id"],
            "safe_to_apply": False,
            "requires_llm": False,
            "candidate_security_ids": _candidate_security_ids(candidates),
            "deterministic_evidence": deterministic[
                "deterministic_evidence"
            ],
            "reason": deterministic["reason"],
            "llm_result": None,
        }

    # ------------------------------------------------------------
    # Stage 2: configured LLM verifier for unresolved cases
    # ------------------------------------------------------------
    try:
        llm_result = verify_candidates(
            client=client,
            event=event,
            identity=identity,
            candidates=candidates,
        )

    except OllamaError as exc:
        # LLM failure must never become a mapping.
        # Keep the event unresolved and continue safely.
        return {
            "llm_decision": "PENDING",
            "llm_security_id": None,
            "llm_confidence": None,
            "validated_decision": "PENDING",
            "validated_security_id": None,
            "safe_to_apply": False,
            "requires_llm": True,
            "candidate_security_ids": _candidate_security_ids(candidates),
            "deterministic_evidence": deterministic[
                "deterministic_evidence"
            ],
            "reason": "LLM verifier failed or timed out.",
            "llm_result": {
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        }

    # ------------------------------------------------------------
    # Stage 3: deterministic validation of LLM result
    # ------------------------------------------------------------
    result = validate_llm_verification(
        event=event,
        identity=identity,
        candidates=candidates,
        llm_result=llm_result,
    )

    result["requires_llm"] = True

    return result