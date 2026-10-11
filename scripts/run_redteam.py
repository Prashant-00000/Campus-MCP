"""
Convenience launcher for the Red Team Benchmark & Ablation Study.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from redteam.runner import RedTeamHarness

if __name__ == "__main__":
    harness = RedTeamHarness()
    harness.run_full_experiment()
