"""
Statistical utilities for evaluation and red-teaming.
Computes Wilson 95% Confidence Intervals for binomial proportions.
"""

import math
from typing import Tuple

def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Computes the Wilson score interval for a binomial proportion.
    Unlike standard normal approximation, Wilson behaves properly near 0% and 100%
    and for small sample sizes.
    """
    if total <= 0:
        return 0.0, 0.0

    # z value for two-sided confidence level
    # 0.95 -> 1.95996
    z = 1.95996 if confidence == 0.95 else 1.64485
    p_hat = successes / total
    z2 = z * z
    n = total

    denominator = 1.0 + z2 / n
    center_adjusted = (p_hat + z2 / (2 * n)) / denominator
    spread = (z / denominator) * math.sqrt((p_hat * (1 - p_hat) / n) + (z2 / (4 * n * n)))

    lower = max(0.0, center_adjusted - spread)
    upper = min(1.0, center_adjusted + spread)
    return round(lower * 100, 2), round(upper * 100, 2)

def format_ci(successes: int, total: int) -> str:
    """Formats percentage and Wilson 95% CI as a clean string: e.g. '85.2% [72.1, 93.4]'."""
    if total <= 0:
        return "N/A"
    pct = round((successes / total) * 100, 1)
    low, high = wilson_score_interval(successes, total)
    return f"{pct}% [{low}%, {high}%]"
