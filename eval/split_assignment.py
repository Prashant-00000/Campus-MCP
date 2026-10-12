"""Stable assignment for newly authored evaluation cases."""

import hashlib


def assign_split(case_id: str) -> str:
    """Assign 80% dev and 20% test using only the immutable case ID."""
    bucket = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8], 16) % 5
    return "test" if bucket == 0 else "dev"
