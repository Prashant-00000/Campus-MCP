"""
Run the Full Red-Team Ablation Study against one real model.

Requires LLM_PROVIDER and LLM_MODEL (or MODEL_A_PROVIDER / MODEL_A_MODEL) in .env
plus the matching API key.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.llm import provider_from_env, LLMProvider
from redteam.runner import RedTeamHarness


def main():
    # Allow MODEL_A_* overrides
    provider_name = os.getenv("MODEL_A_PROVIDER", os.getenv("LLM_PROVIDER", "")).strip()
    model_name = os.getenv("MODEL_A_MODEL", os.getenv("LLM_MODEL", "")).strip()

    if provider_name and model_name:
        llm = LLMProvider(model_name=model_name, provider=provider_name)
    else:
        # Falls through to provider_from_env which raises if vars are missing
        llm = provider_from_env()

    harness = RedTeamHarness(llm=llm)
    harness.run_full_experiment()


if __name__ == "__main__":
    main()
