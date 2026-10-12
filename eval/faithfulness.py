"""Deterministic claim-evidence checks for model answers.

This is a conservative heuristic, not a semantic entailment judge. It extracts
specific identifiers, numbers, dates, emails, and capitalized phrases, then
checks whether each appears in the retrieved tool evidence.
"""

import re
from typing import List, Dict, Any

from eval.scoring import normalize_text


_CANDIDATE_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,\s*\d{4})?\b", re.IGNORECASE),
    re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\b"),
    re.compile(r"\b[A-Z]{1,5}\s?-?\d{2,4}\b"),
    re.compile(r"\b\d+(?:\.\d+)?\b"),
    re.compile(r"\b(?:[A-Z][A-Za-z'-]+)(?:\s+(?:[A-Z][A-Za-z'-]+|&)){1,4}\b"),
)


def extract_claim_tokens(answer: str) -> List[str]:
    """Extract specific-looking claims while ignoring ordinary lowercase prose."""
    found = []
    for pattern in _CANDIDATE_PATTERNS:
        found.extend(pattern.findall(answer or ""))
    unique = {}
    for token in found:
        normalized = normalize_text(token)
        if normalized and len(normalized) > 1:
            unique[normalized] = token
    return list(unique.values())


def assess_faithfulness(answer: str, tool_results: List[str]) -> Dict[str, Any]:
    """Return unsupported claims and their rate against supplied tool evidence."""
    evidence = normalize_text(" ".join(tool_results or []))
    claims = extract_claim_tokens(answer)
    unsupported = [claim for claim in claims if normalize_text(claim) not in evidence]
    rate = len(unsupported) / len(claims) if claims else 0.0
    return {
        "claims_checked": len(claims),
        "unsupported_claims": unsupported,
        "unsupported_claim_rate": round(rate, 4),
    }
