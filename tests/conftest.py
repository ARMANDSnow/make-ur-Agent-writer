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
    "AI_DRAW_ENDPOINT",
    "AI_DRAW_BASE_URL",
    "AI_DRAW_MODEL",
    "AI_DRAW_API_KEY",
    "AI_DRAW_RESULT_HOSTS",
    "SD_API_BASE_URL",
    "SD_API_KEY",
    "DISABLE_PROMPT_CACHE",
    "WRITE_MAX_TOKENS",
    "WRITE_PROMPT_PROFILE",
)


def _apply_mock_env() -> None:
    os.environ["OPENAI_MODEL"] = "mock"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    for key in _MOCK_SCRUB_KEYS:
        os.environ.pop(key, None)


# conftest is imported before pytest collects test modules.  Pin mock here so
# import-time LiteLLM initialization cannot observe a real parent environment;
# the fixture below reasserts the same boundary after tests mutate os.environ.
_apply_mock_env()


@pytest.fixture(autouse=True)
def _force_mock_env():
    _apply_mock_env()
    yield
