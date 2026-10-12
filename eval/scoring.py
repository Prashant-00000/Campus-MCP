"""
Text normalization and scoring utilities for evaluation (Grader v2).

Handles Unicode typography variations that commonly appear in LLM responses:
- Non-breaking hyphens (U+2011), en-dashes (U+2013), em-dashes (U+2014), figure dashes (U+2012)
- Narrow no-break spaces (U+202F), non-breaking spaces (U+00A0), thin spaces (U+2009)
- Curly quotes / apostrophes (U+2018, U+2019, U+201C, U+201D)
- Zero-width spaces (U+200B) and byte order marks (U+FEFF)

Supports:
- Atomic fact matching rather than whole rigid phrases.
- Canonical date variant generation (e.g. ISO 2026-11-02 -> November 2, 2026).
- Word-boundary matching for numbers (e.g. \\b401\\b avoids matching 4010).
- Weekday pair normalization (e.g. 'Tue' and 'Thu' matching 'Tuesday & Thursday').
- Historical Grader v1 scoring preserved for audit provenance.
"""

import datetime as dt
import re
import unicodedata
from typing import List, Set

# Hyphens, dashes, and minus variants -> ASCII hyphen-minus '\u002d'
_DASH_PATTERN = re.compile(
    r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d]"
)

# Unicode whitespace variants -> standard ASCII space ' '
_SPACE_PATTERN = re.compile(
    r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]"
)

# Invisible characters to strip completely
_INVISIBLE_PATTERN = re.compile(
    r"[\u200b\u200c\u200d\ufeff]"
)

# Smart quotes -> ASCII quotes
_QUOTE_TABLE = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u00ab": '"',
    "\u00bb": '"',
})

_WEEKDAY_NAMES = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday"
}


def normalize_text(text: str) -> str:
    """
    Normalizes a text string for robust, deterministic fact/string matching.
    
    1. Replaces invisible zero-width characters with empty string.
    2. Replaces all Unicode dash/hyphen variants with ASCII '-'.
    3. Replaces all Unicode whitespace variants with ASCII ' '.
    4. Replaces smart quotes with ASCII quotes.
    5. Applies NFKC decomposition.
    6. Collapses multiple consecutive spaces to a single space.
    7. Converts to lowercase and strips leading/trailing whitespace.
    """
    if not text:
        return ""
    
    # Strip invisible characters
    cleaned = _INVISIBLE_PATTERN.sub("", text)
    
    # Normalize dashes/hyphens
    cleaned = _DASH_PATTERN.sub("-", cleaned)
    
    # Normalize spaces
    cleaned = _SPACE_PATTERN.sub(" ", cleaned)
    
    # Normalize quotes
    cleaned = cleaned.translate(_QUOTE_TABLE)
    
    # Compatibility decomposition
    cleaned = unicodedata.normalize("NFKC", cleaned)
    
    # Ensure any remaining dash-like characters are ASCII hyphen
    cleaned = _DASH_PATTERN.sub("-", cleaned)
    
    # Collapse multiple spaces
    cleaned = re.sub(r" +", " ", cleaned)
    
    return cleaned.lower().strip()


def date_variants(iso_str: str) -> Set[str]:
    """
    Given an ISO date string (e.g. '2026-11-02'), generates canonical textual variants:
    - '2026-11-02'
    - 'November 2, 2026'
    - 'Nov 2, 2026'
    - '2 November 2026'
    """
    iso_clean = iso_str.strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", iso_clean):
            d = dt.date.fromisoformat(iso_clean)
            variants = {
                iso_clean,
                f"{d:%B} {d.day}, {d.year}",
                f"{d:%B} {d.day} {d.year}",
                f"{d:%b} {d.day}, {d.year}",
                f"{d:%b} {d.day} {d.year}",
                f"{d.day} {d:%B} {d.year}",
                f"{d.day} {d:%b} {d.year}",
            }
            return {normalize_text(v) for v in variants}
    except (ValueError, TypeError):
        pass
    return {normalize_text(iso_clean)}


def check_single_fact(norm_answer: str, fact: str) -> bool:
    """
    Checks if an atomic fact is present in the normalized answer:
    1. If fact is an ISO date (e.g. '2026-11-02'), checks any date variant.
    2. If fact is purely numeric (e.g. '401', '210000'), checks word boundaries (\\b401\\b).
    3. If fact is a weekday abbreviation (e.g. 'Tue'), checks both 'tue' and 'tuesday'.
    4. Otherwise, checks standard substring containment.
    """
    fact_str = fact.strip()
    norm_fact = normalize_text(fact_str)
    if not norm_fact:
        return True

    # 1. ISO date variant check
    if re.match(r"^\d{4}-\d{2}-\d{2}$", fact_str):
        variants = date_variants(fact_str)
        return any(v in norm_answer for v in variants)

    # 2. Weekday abbreviation check (e.g. 'Tue', 'Thu')
    if norm_fact in _WEEKDAY_NAMES:
        full_day = _WEEKDAY_NAMES[norm_fact]
        # Match 'tue', 'tuesday', with word boundary or substring
        pattern = rf"\b({norm_fact}|{full_day})\b"
        return bool(re.search(pattern, norm_answer))

    # 3. Numeric match with word boundaries
    if norm_fact.isdigit():
        pattern = rf"\b{re.escape(norm_fact)}\b"
        return bool(re.search(pattern, norm_answer))

    # 4. Standard normalized substring match
    return norm_fact in norm_answer


def check_facts_present(answer: str, required_facts: List[str]) -> bool:
    """
    Grader v2: checks if all required facts are present using atomic fact matching,
    date variant expansion, numeric word boundaries, and Unicode normalization.
    """
    norm_answer = normalize_text(answer)
    for fact in required_facts:
        if not check_single_fact(norm_answer, fact):
            return False
    return True


def check_facts_present_v1(answer: str, required_facts: List[str]) -> bool:
    """
    Grader v1: literal normalized substring matching (preserved for provenance).
    """
    norm_answer = normalize_text(answer)
    for fact in required_facts:
        norm_fact = normalize_text(fact)
        if norm_fact not in norm_answer:
            return False
    return True
