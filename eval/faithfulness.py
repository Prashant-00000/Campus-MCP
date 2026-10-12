"""Deterministic claim-evidence checks for model answers.

This is a conservative heuristic, not a semantic entailment judge. It extracts
specific identifiers, numbers, dates, emails, and capitalized phrases, then
checks whether each appears in the retrieved tool evidence.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any

from eval.scoring import normalize_text


_CANDIDATE_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,\s*\d{4})?\b", re.IGNORECASE),
    re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\b"),
    re.compile(r"\b[A-Z]{1,5}\s?-?\d{2,4}\b"),
    re.compile(r"(?<![\d,$.])\b\d+(?:\.\d+)?\b"),
    re.compile(r"\b(?:[A-Z][A-Za-z'-]+)(?:\s+(?:[A-Z][A-Za-z'-]+|&)){1,4}\b"),
)
_NON_CLAIM_PHRASES = {"research focus", "office hours", "total revenue", "top product"}
_SEMANTIC_ALIASES = {
    "computer science department": ("cs", "computer science"),
    "artificial intelligence": ("ai",),
}


def extract_claim_tokens(answer: str) -> List[str]:
    """Extract specific-looking claims while ignoring ordinary lowercase prose."""
    found = []
    for pattern in _CANDIDATE_PATTERNS:
        found.extend(pattern.findall(answer or ""))
    code_numbers = {
        re.search(r"\d+", normalize_text(token)).group(0)
        for token in found
        if re.search(r"[A-Za-z]\s?-?\d+", normalize_text(token))
    }
    unique = {}
    for token in found:
        normalized = normalize_text(token)
        if normalized.startswith("id ") and normalized[3:].replace(" ", "").isdigit():
            continue
        if normalized in _NON_CLAIM_PHRASES:
            continue
        if normalized.isdigit() and normalized in code_numbers:
            continue
        if normalized and len(normalized) > 1:
            unique[normalized] = token
    return list(unique.values())


def _canonical_number(value: str):
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    return format(number, "f").rstrip("0").rstrip(".") or "0"


def _normalized_evidence(text: str) -> str:
    return normalize_text(text).replace("_", " ")


def _days_supported(claim: str, evidence: str) -> bool:
    aliases = {
        "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
    }
    claim_norm = normalize_text(claim)
    evidence_norm = normalize_text(evidence)
    for full_day, short_day in aliases.items():
        claim_norm = claim_norm.replace(full_day, short_day)
    return claim_norm != normalize_text(claim) and all(
        day in evidence_norm for day in re.findall(r"\b(?:mon|tue|wed|thu|fri|sat|sun)\b", claim_norm)
    )


def _claim_supported(claim: str, evidence: str) -> bool:
    claim_norm = _normalized_evidence(claim)
    evidence_norm = _normalized_evidence(evidence)
    if claim_norm in evidence_norm:
        return True
    if claim_norm in _SEMANTIC_ALIASES and any(
        re.search(rf"\b{re.escape(alias)}\b", evidence_norm)
        for alias in _SEMANTIC_ALIASES[claim_norm]
    ):
        return True
    if _days_supported(claim, evidence):
        return True
    claim_number = _canonical_number(claim)
    if claim_number is not None:
        evidence_numbers = {
            _canonical_number(token)
            for token in re.findall(r"\$?\d[\d,]*(?:\.\d+)?", evidence)
        }
        return claim_number in evidence_numbers
    return False


def assess_faithfulness(answer: str, tool_results: List[str]) -> Dict[str, Any]:
    """Return unsupported claims and their rate against supplied tool evidence."""
    evidence = " ".join(tool_results or [])
    claims = extract_claim_tokens(answer)
    unsupported = [claim for claim in claims if not _claim_supported(claim, evidence)]
    rate = len(unsupported) / len(claims) if claims else 0.0
    return {
        "claims_checked": len(claims),
        "unsupported_claims": unsupported,
        "unsupported_claim_rate": round(rate, 4),
    }
