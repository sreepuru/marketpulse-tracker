"""Safe issuer/entity extraction and name normalization for MarketPulse events."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

LEGAL_SUFFIXES = (
    "PRIVATE LIMITED", "PUBLIC LIMITED", "PVT LIMITED", "PVT LTD",
    "PRIVATE LTD", "LIMITED", "LTD", "INCORPORATED", "INC", "CORPORATION", "CORP",
    "COMPANY", "CO", "PLC",
)

# Phrases that commonly begin immediately after the issuer in exchange notices.
_BOUNDARY = re.compile(
    r"\s+(?:has|have|had)\s+(?:informed|submitted|announced|intimated|disclosed|provided|uploaded|filed)\b"
    r"|\s+(?:regarding|about|on|for)\s+(?:the|its|their)\b"
    r"|\s*\|\s*SUBJECT\s*:",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class EntityExtraction:
    raw: Optional[str]
    normalized: Optional[str]
    base_name: Optional[str]
    method: str
    confidence: float


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).upper().replace("&", " AND ")
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def strip_legal_suffix(name: str) -> str:
    value = normalize_name(name)
    changed = True
    while changed and value:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if value == suffix:
                return value
            pattern = r"\s+" + re.escape(suffix) + r"$"
            new_value = re.sub(pattern, "", value).strip()
            if new_value != value:
                value = new_value
                changed = True
                break
    return value


def name_variants(name: str | None) -> list[str]:
    normalized = normalize_name(name)
    if not normalized:
        return []
    variants = [normalized]
    base = strip_legal_suffix(normalized)
    if base and base not in variants:
        variants.append(base)
    # Common legal-suffix spelling variant; retain the full name as well.
    if normalized.endswith(" LIMITED"):
        v = normalized[:-len(" LIMITED")] + " LTD"
        if v not in variants:
            variants.append(v)
    elif normalized.endswith(" CORPORATION"):
        v = normalized[:-len(" CORPORATION")] + " CORP"
        if v not in variants:
            variants.append(v)
    return variants


def _candidate_prefix(text: str) -> str:
    # Titles often put the issuer first. Stop before known exchange-notice phrases.
    first_line = text.splitlines()[0].strip()
    match = _BOUNDARY.search(first_line)
    if match:
        return first_line[:match.start()].strip(" -:|,")
    # Handle the common '<issuer> | SUBJECT:' form.
    if "|" in first_line:
        return first_line.split("|", 1)[0].strip(" -:,")
    return ""


def extract_company_name(title: str | None, description: str | None = None) -> EntityExtraction:
    """Extract a likely issuer from exchange-style event text.

    This is deliberately conservative. Returning no entity is safer than inventing one.
    """
    title = (title or "").strip()
    description = (description or "").strip()
    text = title or description
    if not text:
        return EntityExtraction(None, None, None, "NONE", 0.0)

    candidate = _candidate_prefix(text)
    if candidate:
        normalized = normalize_name(candidate)
        if len(normalized.split()) >= 2:
            return EntityExtraction(candidate, normalized, strip_legal_suffix(normalized), "TITLE_PREFIX", 0.85)

    # Conservative sentence pattern: issuer followed by an exchange-notice verb.
    m = re.match(
        r"^(.{2,120}?)\s+(?:has|have|had)\s+(?:informed|submitted|announced|intimated|disclosed|provided|uploaded|filed)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip(" -:|,")
        normalized = normalize_name(candidate)
        if len(normalized.split()) >= 2:
            return EntityExtraction(candidate, normalized, strip_legal_suffix(normalized), "NOTICE_VERB", 0.90)

    return EntityExtraction(None, None, None, "NONE", 0.0)
