#!/usr/bin/env python3
"""
MarketPulse Mapping Agent V2.0

Purpose
-------
Add a safe research/evidence layer on top of the existing deterministic V2.2
candidate engine.

Architecture
------------
market_news
    -> V2.2 deterministic candidate engine
    -> Research Provider(s)
    -> Identity Dossier
    -> Canonical verification against security_master
    -> MATCH / REVIEW / NO_CANONICAL_MATCH

Safety rules
------------
1. security_master is the canonical source of truth.
2. This module never writes security_master or market_news.
3. Web research produces evidence, never a security_id directly.
4. A web result cannot become a canonical candidate merely because it contains
   a symbol that happens to exist in security_master.
5. Retrieval score is never mapping confidence.
6. Historical identity may establish an old identity but cannot create a
   current canonical security.
7. MATCH requires canonical verification plus identity continuity evidence.
8. Ambiguous or incomplete evidence becomes REVIEW.
9. Research is bounded by MAX_AGENT_STEPS.
10. ISINs are accepted only after the official MOD-36 check digit validates.

This first V2.0 implementation intentionally keeps public-web research behind
an evidence-only provider interface. Exchange-specific providers can be added
without changing the decision layer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import psycopg2

import marketpulse_mapping_agent_v2_2 as engine


AGENT_NAME = "MarketPulse-Mapping-Agent"
AGENT_VERSION = "2.0.2"
MAX_AGENT_STEPS = 3
AGENT_AUTO_APPLY_ACCURACY_THRESHOLD = 0.90

DECISION_MATCH = "MATCH"
DECISION_REVIEW = "REVIEW"
DECISION_NO_MATCH = "NO_CANONICAL_MATCH"

CONTINUITY_ESTABLISHED = "ESTABLISHED"
CONTINUITY_PLAUSIBLE = "PLAUSIBLE"
CONTINUITY_NOT_ESTABLISHED = "NOT_ESTABLISHED"

SOURCE_EXCHANGE = "EXCHANGE"
SOURCE_HISTORICAL_DB = "HISTORICAL_DB"
SOURCE_SECURITY_MASTER = "SECURITY_MASTER"
SOURCE_PUBLIC_WEB = "PUBLIC_WEB"


# ---------------------------------------------------------------------------
# Identity validation
# ---------------------------------------------------------------------------


def normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    value = str(value).upper().strip()
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_symbol(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))


def normalize_isin(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))


def valid_isin(value: Optional[str]) -> bool:
    """Validate an ISIN using ISO 6166 / MOD-36,11 check digit logic."""
    isin = normalize_isin(value)
    if len(isin) != 12 or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False

    expanded = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in isin)
    total = 0
    # Starting from the rightmost digit, double every second digit.
    for pos, ch in enumerate(reversed(expanded)):
        digit = int(ch)
        if pos % 2 == 1:
            digit *= 2
        total += digit // 10 + digit % 10
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Evidence model
# ---------------------------------------------------------------------------


@dataclass
class ResearchEvidence:
    source_type: str
    source_name: str
    source_url: Optional[str]
    evidence_type: str
    claim: str
    historical_name: Optional[str] = None
    historical_symbol: Optional[str] = None
    current_name: Optional[str] = None
    current_symbol: Optional[str] = None
    isin: Optional[str] = None
    exchange_code: Optional[str] = None
    continuity: Optional[str] = None
    supports_identity: Optional[bool] = None
    notes: Optional[str] = None
    canonical_security_id_hint: Optional[int] = None


@dataclass
class IdentityDossier:
    group_key: str
    historical_name: Optional[str] = None
    historical_symbol: Optional[str] = None
    isin: Optional[str] = None
    exchange: Optional[str] = None
    exchange_code: Optional[str] = None
    current_name: Optional[str] = None
    current_symbol: Optional[str] = None
    continuity: str = CONTINUITY_NOT_ESTABLISHED
    evidence: List[ResearchEvidence] = field(default_factory=list)
    research_success: bool = False
    research_steps: int = 0
    warnings: List[str] = field(default_factory=list)
    news_ids: List[int] = field(default_factory=list)


@dataclass
class CanonicalVerification:
    security_id: int
    matched_fields: List[str]
    security_snapshot: Dict[str, Any]
    continuity_supported: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class AgentDecision:
    decision_id: str
    run_id: str
    group_key: str
    decision: str
    security_id: Optional[int]
    resolution_status: str
    confidence: Optional[float]
    research_success: bool
    research_steps: int
    identity_continuity: str
    identity_dossier: Dict[str, Any]
    canonical_verifications: List[Dict[str, Any]]
    evidence: List[Dict[str, Any]]
    reason: str
    requires_review: bool
    agent_version: str = AGENT_VERSION


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class ResearchProvider:
    name = "BASE"

    def research(
        self,
        group: engine.IdentityGroup,
        dossier: IdentityDossier,
        remaining_steps: int,
    ) -> Tuple[List[ResearchEvidence], int]:
        raise NotImplementedError


class HistoricalIdentityProvider(ResearchProvider):
    """Read-only provider backed by the actual MarketPulse historical evidence table.

    The V2.0.0 implementation queried an older/nonexistent schema
    (identity_type/identity_value). The live V2.2 schema stores:
        historical_symbol
        historical_company_name
        historical_isin
        historical_bse_code
        evidence_source
        evidence_url
        evidence_status
        canonical_security_id
        evidence

    This provider treats canonical_security_id as evidence/hint only. It never
    returns it directly as a mapping decision.
    """

    name = SOURCE_HISTORICAL_DB

    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def _as_dict(raw: Any) -> Dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _first(raw: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
        for key in keys:
            value = raw.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return None

    def research(self, group, dossier, remaining_steps):
        if remaining_steps <= 0:
            return [], 0

        sql = """
            SELECT
                exchange,
                historical_symbol,
                historical_company_name,
                historical_isin,
                historical_bse_code,
                evidence_source,
                evidence_url,
                evidence_status,
                canonical_security_id,
                evidence
            FROM marketpulse_historical_identity_evidence
            WHERE identity_group_key = %s
            ORDER BY updated_at DESC, evidence_id DESC
            LIMIT 20
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, (group.group_key,))
                rows = cur.fetchall()
        except Exception as exc:
            self.conn.rollback()
            # One step was attempted, but surface the failure so the run is
            # diagnosable instead of silently reporting "no research".
            return [
                ResearchEvidence(
                    source_type=SOURCE_HISTORICAL_DB,
                    source_name="marketpulse_historical_identity_evidence",
                    source_url=None,
                    evidence_type="PROVIDER_ERROR",
                    claim="Historical identity provider could not read its configured evidence table.",
                    supports_identity=False,
                    notes=f"{type(exc).__name__}: {exc}",
                )
            ], 1

        evidence: List[ResearchEvidence] = []

        for row in rows:
            (
                exchange,
                historical_symbol,
                historical_company_name,
                historical_isin,
                historical_bse_code,
                evidence_source,
                evidence_url,
                evidence_status,
                canonical_security_id,
                raw,
            ) = row

            raw_dict = self._as_dict(raw)

            # The structured columns are authoritative for their respective
            # historical fields. JSON is only used to enrich continuity/current
            # identity details when such evidence was previously recorded.
            raw_historical_name = self._first(
                raw_dict,
                ["historical_company_name", "historical_name", "company_name"],
            )
            raw_historical_symbol = self._first(
                raw_dict,
                ["historical_symbol", "symbol", "old_symbol"],
            )
            raw_isin = self._first(
                raw_dict,
                ["historical_isin", "isin"],
            )
            raw_current_name = self._first(
                raw_dict,
                ["current_name", "current_company_name", "canonical_name"],
            )
            raw_current_symbol = self._first(
                raw_dict,
                ["current_symbol", "canonical_symbol"],
            )
            raw_exchange_code = self._first(
                raw_dict,
                ["exchange_code", "bse_scrip_code", "bse_code"],
            )
            raw_continuity = self._first(
                raw_dict,
                ["continuity", "identity_continuity"],
            )

            h_name = str(historical_company_name or raw_historical_name or group.company_name or "").strip() or None
            h_symbol = str(historical_symbol or raw_historical_symbol or group.symbol or "").strip() or None

            isin_candidate = historical_isin or raw_isin
            isin = normalize_isin(isin_candidate) if isin_candidate else None
            if isin and not valid_isin(isin):
                isin = None

            status = str(evidence_status or "").upper().strip()
            continuity = None
            if raw_continuity:
                rc = raw_continuity.upper().strip()
                if rc in {
                    CONTINUITY_ESTABLISHED,
                    CONTINUITY_PLAUSIBLE,
                    CONTINUITY_NOT_ESTABLISHED,
                }:
                    continuity = rc
            elif status in {"ESTABLISHED", "VERIFIED", "CANONICAL_VERIFIED"}:
                continuity = CONTINUITY_ESTABLISHED
            elif status in {"RESEARCHED", "SUPPORTED", "PLAUSIBLE"}:
                continuity = CONTINUITY_PLAUSIBLE

            hint = (
                f" canonical_security_id_hint={int(canonical_security_id)}"
                if canonical_security_id is not None
                else ""
            )

            claim_parts = []
            if h_name:
                claim_parts.append(f"historical_name={h_name}")
            if h_symbol:
                claim_parts.append(f"historical_symbol={h_symbol}")
            if isin:
                claim_parts.append(f"isin={isin}")
            if historical_bse_code:
                claim_parts.append(f"bse_code={historical_bse_code}")
            if status:
                claim_parts.append(f"status={status}")

            evidence.append(
                ResearchEvidence(
                    source_type=SOURCE_HISTORICAL_DB,
                    source_name=str(evidence_source or "historical_identity"),
                    source_url=str(evidence_url) if evidence_url else None,
                    evidence_type="HISTORICAL_IDENTITY",
                    claim="; ".join(claim_parts) or "Historical identity evidence row",
                    historical_name=h_name,
                    historical_symbol=h_symbol,
                    current_name=raw_current_name,
                    current_symbol=normalize_symbol(raw_current_symbol) if raw_current_symbol else None,
                    isin=isin,
                    exchange_code=str(historical_bse_code or raw_exchange_code) if (historical_bse_code or raw_exchange_code) else None,
                    continuity=continuity,
                    supports_identity=True,
                    notes=(
                        f"{hint.strip()}; raw_evidence_keys={sorted(raw_dict.keys())}"
                        if hint
                        else f"raw_evidence_keys={sorted(raw_dict.keys())}"
                    ),
                    canonical_security_id_hint=(
                        int(canonical_security_id)
                        if canonical_security_id is not None
                        else None
                    ),
                )
            )

        return evidence, 1


class ExchangeResearchProvider(ResearchProvider):
    """Interface for exchange-specific evidence providers.

    No generic web scraping is performed here. NSE/BSE implementations can be
    plugged in later and must return identity evidence, not canonical IDs.
    """

    name = SOURCE_EXCHANGE

    def research(self, group, dossier, remaining_steps):
        return [], 0


class PublicWebEvidenceProvider(ResearchProvider):
    """Disabled-by-default placeholder for public web research.

    The previous Bing-based versions demonstrated that generic search results
    can contain unrelated symbols. V2.0 therefore does not use generic web
    search as a canonical resolver. A future provider must return evidence
    tied to the searched historical entity and source URL.
    """

    name = SOURCE_PUBLIC_WEB

    def research(self, group, dossier, remaining_steps):
        return [], 0


# ---------------------------------------------------------------------------
# Canonical verification
# ---------------------------------------------------------------------------


class CanonicalVerifier:
    """Verify an identity dossier against active security_master rows."""

    def __init__(self, securities: Sequence[engine.Security]):
        self.securities = list(securities)
        self.by_id = {s.security_id: s for s in securities}

    @staticmethod
    def snapshot(sec: engine.Security) -> Dict[str, Any]:
        return {
            "security_id": sec.security_id,
            "instrument_name": sec.instrument_name,
            "symbol": sec.symbol,
            "nse_symbol": sec.nse_symbol,
            "bse_symbol": sec.bse_symbol,
            "nse_name": sec.nse_name,
            "bse_name": sec.bse_name,
            "exchange": sec.exchange,
            "exchange_tag": sec.exchange_tag,
            "isin": sec.isin,
            "bse_scrip_code": sec.bse_scrip_code,
            "asset_category": sec.asset_category,
            "is_active": sec.is_active,
        }

    def verify(self, dossier: IdentityDossier) -> List[CanonicalVerification]:
        results: Dict[int, CanonicalVerification] = {}

        hinted_ids = {
            int(e.canonical_security_id_hint)
            for e in dossier.evidence
            if e.canonical_security_id_hint is not None
        }

        # A canonical_security_id stored in historical evidence is only a
        # hypothesis. Verify it against the actual active security_master row.
        for hinted_id in hinted_ids:
            sec = self.by_id.get(hinted_id)
            if sec is None:
                continue

            fields: List[str] = []
            reasons: List[str] = []

            target_isin = normalize_isin(dossier.isin)
            target_symbol = normalize_symbol(dossier.current_symbol or dossier.historical_symbol)
            target_name = normalize_text(dossier.current_name or dossier.historical_name)

            if target_isin and valid_isin(target_isin) and normalize_isin(sec.isin) == target_isin:
                fields.append("ISIN")
                reasons.append("Historical evidence hint verified by exact validated ISIN.")
            if target_symbol:
                symbols = {
                    normalize_symbol(sec.symbol),
                    normalize_symbol(sec.nse_symbol),
                    normalize_symbol(sec.bse_symbol),
                }
                symbols.discard("")
                if target_symbol in symbols:
                    fields.append("SYMBOL")
                    reasons.append("Historical evidence hint verified by exact symbol.")
            if target_name:
                names = {
                    normalize_text(sec.instrument_name),
                    normalize_text(sec.nse_name),
                    normalize_text(sec.bse_name),
                }
                names.discard("")
                if target_name in names:
                    fields.append("NAME")
                    reasons.append("Historical evidence hint verified by exact canonical name.")

            if fields:
                results[sec.security_id] = CanonicalVerification(
                    security_id=sec.security_id,
                    matched_fields=fields,
                    security_snapshot=self.snapshot(sec),
                    continuity_supported=False,
                    reasons=reasons,
                )

        target_isin = normalize_isin(dossier.isin)
        target_symbol = normalize_symbol(dossier.current_symbol or dossier.historical_symbol)
        target_name = normalize_text(dossier.current_name or dossier.historical_name)

        for sec in self.securities:
            fields: List[str] = []
            reasons: List[str] = []

            if target_isin and valid_isin(target_isin) and normalize_isin(sec.isin) == target_isin:
                fields.append("ISIN")
                reasons.append("Exact validated ISIN match.")

            symbols = {
                normalize_symbol(sec.symbol),
                normalize_symbol(sec.nse_symbol),
                normalize_symbol(sec.bse_symbol),
            }
            symbols.discard("")
            if target_symbol and target_symbol in symbols:
                fields.append("SYMBOL")
                reasons.append("Exact symbol match in security_master.")

            names = {
                normalize_text(sec.instrument_name),
                normalize_text(sec.nse_name),
                normalize_text(sec.bse_name),
            }
            names.discard("")
            if target_name and target_name in names:
                fields.append("NAME")
                reasons.append("Exact normalized name match in security_master.")

            if fields:
                results[sec.security_id] = CanonicalVerification(
                    security_id=sec.security_id,
                    matched_fields=fields,
                    security_snapshot=self.snapshot(sec),
                    continuity_supported=False,
                    reasons=reasons,
                )

        return list(results.values())


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class MappingAgentV2:
    def __init__(
        self,
        conn,
        indexes,
        providers: Optional[Sequence[ResearchProvider]] = None,
        max_steps: int = MAX_AGENT_STEPS,
    ):
        self.conn = conn
        self.indexes = indexes
        self.verifier = CanonicalVerifier(indexes["by_id"].values())
        self.providers = list(providers or [
            HistoricalIdentityProvider(conn),
            ExchangeResearchProvider(),
        ])
        self.max_steps = max(1, min(int(max_steps), MAX_AGENT_STEPS))

    def initial_dossier(self, group: engine.IdentityGroup) -> IdentityDossier:
        isin = normalize_isin(group.isin)
        if isin and not valid_isin(isin):
            isin = None

        return IdentityDossier(
            group_key=group.group_key,
            historical_name=group.company_name or None,
            historical_symbol=group.symbol or None,
            isin=isin,
            exchange=group.exchange or None,
        )

    def enrich_dossier(
        self,
        dossier: IdentityDossier,
        evidence: Sequence[ResearchEvidence],
        steps: int,
    ) -> IdentityDossier:
        dossier.evidence.extend(evidence)
        dossier.research_steps += steps
        dossier.research_success = dossier.research_success or bool(evidence)

        for item in evidence:
            if item.isin and valid_isin(item.isin):
                dossier.isin = normalize_isin(item.isin)
            if item.current_name:
                dossier.current_name = item.current_name
            if item.current_symbol:
                dossier.current_symbol = normalize_symbol(item.current_symbol)
            if item.exchange_code:
                dossier.exchange_code = item.exchange_code
            if item.continuity == CONTINUITY_ESTABLISHED:
                dossier.continuity = CONTINUITY_ESTABLISHED
            elif (
                item.supports_identity
                and dossier.continuity == CONTINUITY_NOT_ESTABLISHED
            ):
                dossier.continuity = CONTINUITY_PLAUSIBLE

        # Historical evidence by itself cannot establish current continuity.
        # Continuity is established later only after canonical verification.
        if dossier.isin and not valid_isin(dossier.isin):
            dossier.warnings.append("Invalid ISIN evidence discarded.")
            dossier.isin = None

        return dossier

    def research(self, group: engine.IdentityGroup) -> IdentityDossier:
        dossier = self.initial_dossier(group)
        remaining = self.max_steps

        for provider in self.providers:
            if remaining <= 0:
                break
            evidence, used = provider.research(group, dossier, remaining)
            used = max(0, min(int(used), remaining))
            dossier = self.enrich_dossier(dossier, evidence, used)
            remaining -= used

        return dossier

    def decide(
        self,
        run_id: uuid.UUID,
        group: engine.IdentityGroup,
        candidates: Sequence[engine.Candidate],
    ) -> AgentDecision:
        dossier = self.research(group)
        # Preserve event-level membership for audit/persistence.
        dossier.news_ids = list(group.news_ids) if hasattr(group, "news_ids") else []

        # V2.2 candidates are useful evidence but do not automatically become
        # canonical. Add their exact fields to the dossier only when supported
        # by the identity already present in the group.
        verifications = self.verifier.verify(dossier)

        hinted_ids = {
            int(e.canonical_security_id_hint)
            for e in dossier.evidence
            if e.canonical_security_id_hint is not None
        }
        verified_hint_ids = {
            v.security_id
            for v in verifications
            if v.security_id in hinted_ids
            and ("ISIN" in v.matched_fields or "SYMBOL" in v.matched_fields or "NAME" in v.matched_fields)
        }
        if len(verified_hint_ids) == 1:
            dossier.continuity = CONTINUITY_ESTABLISHED
            for v in verifications:
                if v.security_id in verified_hint_ids:
                    v.continuity_supported = True
                    v.reasons.append(
                        "Historical canonical hint independently verified against active security_master."
                    )

        # Existing deterministic candidates are also verified independently.
        candidate_ids = {int(c.security_id) for c in candidates}
        for verification in self.verifier.verify(dossier):
            if verification.security_id in candidate_ids:
                verification.reasons.append("Also present in bounded V2.2 candidate set.")

        evidence = [asdict(e) for e in dossier.evidence]
        evidence.extend({
            "type": "canonical_verification",
            "security_id": v.security_id,
            "matched_fields": v.matched_fields,
            "reasons": v.reasons,
        } for v in verifications)

        # Safe MATCH requires:
        #   * exactly one canonical security
        #   * a strong canonical identifier (validated ISIN or exact symbol)
        #   * identity continuity established
        # Historical evidence alone is never enough.
        strong = [
            v for v in verifications
            if "ISIN" in v.matched_fields or "SYMBOL" in v.matched_fields
        ]

        if len(strong) == 1 and dossier.continuity == CONTINUITY_ESTABLISHED:
            v = strong[0]
            return AgentDecision(
                decision_id=str(uuid.uuid4()),
                run_id=str(run_id),
                group_key=group.group_key,
                decision=DECISION_MATCH,
                security_id=v.security_id,
                resolution_status="CANONICAL_VERIFIED",
                confidence=0.95 if "ISIN" in v.matched_fields else 0.90,
                research_success=dossier.research_success,
                research_steps=dossier.research_steps,
                identity_continuity=dossier.continuity,
                identity_dossier=asdict(dossier),
                canonical_verifications=[asdict(x) for x in verifications],
                evidence=evidence,
                reason="One canonical security is verified by a strong identifier and identity continuity is established.",
                requires_review=False,
            )

        if len(verifications) > 1 or len(strong) > 1 or dossier.continuity == CONTINUITY_PLAUSIBLE:
            return AgentDecision(
                decision_id=str(uuid.uuid4()),
                run_id=str(run_id),
                group_key=group.group_key,
                decision=DECISION_REVIEW,
                security_id=None,
                resolution_status="EVIDENCE_INSUFFICIENT_OR_AMBIGUOUS",
                confidence=None,
                research_success=dossier.research_success,
                research_steps=dossier.research_steps,
                identity_continuity=dossier.continuity,
                identity_dossier=asdict(dossier),
                canonical_verifications=[asdict(x) for x in verifications],
                evidence=evidence,
                reason="Research produced identity evidence, but canonical continuity is not strong and unambiguous enough for automatic matching.",
                requires_review=True,
            )

        return AgentDecision(
            decision_id=str(uuid.uuid4()),
            run_id=str(run_id),
            group_key=group.group_key,
            decision=DECISION_NO_MATCH,
            security_id=None,
            resolution_status=(
                "HISTORICAL_EVIDENCE_ONLY"
                if dossier.research_success
                else "NO_CANONICAL_EVIDENCE"
            ),
            confidence=None,
            research_success=dossier.research_success,
            research_steps=dossier.research_steps,
            identity_continuity=dossier.continuity,
            identity_dossier=asdict(dossier),
            canonical_verifications=[asdict(x) for x in verifications],
            evidence=evidence,
            reason="No single canonical security was verified with sufficient identity-continuity evidence.",
            requires_review=False,
        )


# ---------------------------------------------------------------------------
# Database helpers / CLI
# ---------------------------------------------------------------------------


def connect():
    password = os.getenv("MARKETPULSE_DB_PASSWORD")
    if password is None:
        raise RuntimeError("MARKETPULSE_DB_PASSWORD is not set")
    return psycopg2.connect(
        host=os.getenv("MARKETPULSE_DB_HOST", "localhost"),
        port=int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
        dbname=os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
        user=os.getenv("MARKETPULSE_DB_USER", "postgres"),
        password=password,
    )


def ensure_agent_schema(conn):
    """Ensure audit fields required for Agent validation/user review exist."""
    sql = """
    CREATE TABLE IF NOT EXISTS security_mapping_decisions (
        decision_id BIGSERIAL PRIMARY KEY,
        run_id UUID NOT NULL,
        news_id BIGINT NOT NULL,
        identity_group_key TEXT,
        decision VARCHAR(30) NOT NULL,
        security_id BIGINT,
        confidence NUMERIC(8,6),
        reason TEXT,
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        candidate_security_ids BIGINT[] NOT NULL DEFAULT '{}'::bigint[],
        agent_name VARCHAR(100),
        agent_version VARCHAR(50),
        model_name VARCHAR(150),
        prompt_version VARCHAR(50),
        requires_review BOOLEAN NOT NULL DEFAULT TRUE,
        status VARCHAR(30) NOT NULL DEFAULT 'PENDING_REVIEW',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TIMESTAMP,
        reviewed_by VARCHAR(200),
        final_security_id BIGINT,
        review_outcome VARCHAR(30),
        CONSTRAINT uq_mapping_decision_v2 UNIQUE (run_id, news_id)
    );
    ALTER TABLE security_mapping_decisions ADD COLUMN IF NOT EXISTS final_security_id BIGINT;
    ALTER TABLE security_mapping_decisions ADD COLUMN IF NOT EXISTS review_outcome VARCHAR(30);
    CREATE INDEX IF NOT EXISTS idx_mapping_decisions_agent_review
        ON security_mapping_decisions (review_outcome);
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def validated_agent_accuracy(conn):
    """Return accuracy from explicit human reviews only; unreviewed rows are excluded."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE review_outcome = 'CORRECT'),
                COUNT(*) FILTER (WHERE review_outcome IN ('CORRECT','WRONG'))
            FROM security_mapping_decisions
            WHERE security_id IS NOT NULL
        """)
        correct, reviewed = cur.fetchone()
    if not reviewed:
        return None, 0, 0
    return float(correct) / float(reviewed), int(reviewed), int(correct)


def persist_decisions(conn, decision, previous_status_by_news):
    rows = []
    for news_id in decision.identity_dossier.get("news_ids", []) or []:
        rows.append((
            decision.run_id, news_id, decision.group_key, decision.decision,
            decision.security_id, decision.confidence, decision.reason,
            json.dumps({
                "agent_decision_id": decision.decision_id,
                "previous_mapping_status": previous_status_by_news.get(news_id),
                "identity_dossier": decision.identity_dossier,
                "canonical_verifications": decision.canonical_verifications,
                "evidence": decision.evidence,
            }, default=str),
            decision.agent_version,
            decision.requires_review,
            "AUTO_APPLIED" if decision.decision == DECISION_MATCH else "PENDING_REVIEW",
        ))
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO security_mapping_decisions
              (run_id, news_id, identity_group_key, decision, security_id, confidence, reason, evidence, agent_name, agent_version, requires_review, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
            ON CONFLICT (run_id, news_id) DO NOTHING
        """, [(a,b,c,d,e,f,g,h,AGENT_NAME,i,j,k) for a,b,c,d,e,f,g,h,i,j,k in rows])
    conn.commit()
    return len(rows)


def apply_agent_match(conn, decision, accuracy, threshold):
    if decision.decision != DECISION_MATCH or decision.security_id is None or accuracy is None or accuracy < threshold:
        return 0
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE market_news
            SET security_id = %s, mapping_status = 'MAPPED', mapping_method = 'AGENT', mapping_confidence = %s
            WHERE news_id = ANY(%s)
              AND security_id IS NULL
              AND mapping_status IN ('PENDING','AMBIGUOUS')
        """, (decision.security_id, decision.confidence, list(map(int, decision.identity_dossier.get("news_ids", []) or []))))
        changed = cur.rowcount
        cur.execute("""
            UPDATE security_mapping_decisions
            SET status='AUTO_APPLIED', requires_review=FALSE, final_security_id=security_id
            WHERE run_id=%s AND news_id = ANY(%s)
        """, (decision.run_id, list(map(int, decision.identity_dossier.get("news_ids", []) or []))))
    conn.commit()
    return changed


def filter_agent_scope(conn, groups):
    """Only process events explicitly eligible for Agent mapping."""
    eligible = []
    for group in groups:
        if not group.news_ids:
            continue
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM market_news
                WHERE news_id = ANY(%s)
                  AND security_id IS NULL
                  AND mapping_status IN ('PENDING','AMBIGUOUS')
            """, (list(map(int, group.news_ids)),))
            count = cur.fetchone()[0] or 0
        if int(count) == len(group.news_ids):
            eligible.append(group)
    return eligible


def parse_args():
    p = argparse.ArgumentParser(description="MarketPulse Mapping Agent V2.0")
    p.add_argument("--limit-groups", type=int, default=10)
    p.add_argument("--all-groups", action="store_true")
    p.add_argument("--max-candidates", type=int, default=20)
    p.add_argument("--max-agent-steps", type=int, default=MAX_AGENT_STEPS)
    p.add_argument(
        "--groups",
        nargs="+",
        default=None,
        help="Optional exact identity group keys to test, e.g. NSE:SYMBOL:VALECHAENG",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Print the identity dossier and evidence used for each decision.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    conn = connect()
    try:
        groups = engine.load_identity_groups(
            conn,
            limit_groups=None if args.all_groups else args.limit_groups,
        )
        if args.groups:
            wanted = {str(x).upper() for x in args.groups}
            groups = [g for g in groups if g.group_key.upper() in wanted]
        groups = filter_agent_scope(conn, groups)
        securities = engine.load_securities(conn)
        indexes = engine.build_indexes(securities)
        run_id = uuid.uuid4()
        ensure_agent_schema(conn)
        accuracy, reviewed_count, correct_count = validated_agent_accuracy(conn)
        agent = MappingAgentV2(
            conn,
            indexes,
            max_steps=args.max_agent_steps,
        )

        print("=" * 88)
        print("MARKETPULSE MAPPING AGENT V2.0")
        print("=" * 88)
        print(f"Run ID              : {run_id}")
        print(f"Identity groups     : {len(groups):,}")
        print(f"Active securities   : {len(securities):,}")
        print(f"Max research steps  : {agent.max_steps}")
        print(f"Validated accuracy   : {accuracy if accuracy is not None else 'N/A'} ({correct_count}/{reviewed_count})")
        print(f"Auto-apply threshold : {AGENT_AUTO_APPLY_ACCURACY_THRESHOLD}")
        print("Scope                : PENDING + AMBIGUOUS only")
        print("security_master      : PROTECTED")
        print()

        counts: Dict[str, int] = {}
        for group in groups:
            candidates = engine.retrieve_candidates(
                conn, group, indexes, max_candidates=args.max_candidates
            )
            decision = agent.decide(run_id, group, candidates)
            previous_status_by_news = {}
            with conn.cursor() as cur:
                cur.execute("SELECT news_id, mapping_status FROM market_news WHERE news_id = ANY(%s)", (list(map(int, group.news_ids)),))
                previous_status_by_news = {int(n): st for n, st in cur.fetchall()}
            persisted = persist_decisions(conn, decision, previous_status_by_news)
            applied = apply_agent_match(conn, decision, accuracy, AGENT_AUTO_APPLY_ACCURACY_THRESHOLD)
            counts[decision.decision] = counts.get(decision.decision, 0) + 1

            print(f"{group.group_key}")
            print(f"  decision          : {decision.decision}")
            print(f"  security_id       : {decision.security_id}")
            print(f"  research_success  : {decision.research_success}")
            print(f"  research_steps    : {decision.research_steps}")
            print(f"  continuity        : {decision.identity_continuity}")
            print(f"  evidence_count    : {len(decision.evidence)}")
            if decision.identity_dossier.get("warnings"):
                print(f"  warnings          : {decision.identity_dossier.get('warnings')}")
            print(f"  canonical_matches : {len(decision.canonical_verifications)}")
            print(f"  reason            : {decision.reason}")
            print(f"  decision_rows     : {persisted}")
            print(f"  auto_applied      : {applied}")
            if args.debug:
                print("  dossier           :")
                print(json.dumps(decision.identity_dossier, indent=4, default=str))
                print("  canonical_verify  :")
                print(json.dumps(decision.canonical_verifications, indent=4, default=str))
                print()

        print("Summary")
        print("-" * 40)
        for key in (DECISION_MATCH, DECISION_REVIEW, DECISION_NO_MATCH):
            print(f"{key:<22}: {counts.get(key, 0):,}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()