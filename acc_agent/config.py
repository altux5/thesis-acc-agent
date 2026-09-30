"""Configuration and LLM client setup for the ACC CodeAct agent.

The OpenRouter API key is read from the environment (or a local .env file) so it
never has to live in source control.
"""

from __future__ import annotations

import os

from openai import OpenAI

try:
    from dotenv import load_dotenv

    load_dotenv()  # load a local .env file if one exists
except ImportError:  # python-dotenv is optional
    pass

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Override with the MODEL env var, or the --model CLI flag.
# Pick any id from https://openrouter.ai/models
DEFAULT_MODEL = os.environ.get("MODEL", "anthropic/claude-sonnet-4.5")

# Safety caps for the agent loop.
MAX_ITERATIONS = 20  # cap on model calls per run; a run ends earlier once its report is accepted
OUTPUT_CHAR_LIMIT = 6000  # truncate execution output fed back to the model


def load_client() -> OpenAI:
    """Create an OpenAI-compatible client pointed at OpenRouter."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Put it in your environment or a .env "
            "file (see .env.example)."
        )
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
