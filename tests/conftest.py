"""iter047B2 M9: keep `pytest` runs mock-isolated, matching `unittest discover`.

The canonical runner is `python -m unittest discover -s tests` (AGENTS.md:51),
under which tests/__init__.py + src/config + src/llm_client scrub .env so tests
never hit a real model. Bare `pytest` historically reported 3 spurious failures
(test_env_isolation + test_llm_client_cache x2): pytest wasn't detected as a test
runner, so .env (OPENAI_STREAM=1, API keys) leaked back in — and litellm itself
reloads dotenv on import. This autouse fixture re-asserts mock isolation before
every test so both runners agree. unittest discover does not import conftest, so
this file is pytest-only and never affects the canonical run.
"""

import os

import pytest

_MOCK_SCRUB_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_STREAM",
    "PLANNER_API_KEY",
    "PLANNER_BASE_URL",
    "PLANNER_MODEL",
    "DISABLE_PROMPT_CACHE",
    "WRITE_MAX_TOKENS",
    "WRITE_PROMPT_PROFILE",
)


@pytest.fixture(autouse=True)
def _force_mock_env():
    os.environ["OPENAI_MODEL"] = "mock"
    for key in _MOCK_SCRUB_KEYS:
        os.environ.pop(key, None)
    yield
