"""Force tests to use mock LLM settings before project config loads .env."""

import os

os.environ["OPENAI_MODEL"] = "mock"
for key in (
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
):
    os.environ.pop(key, None)

# Note: the litellm/.env leak (litellm imports dotenv and calls
# load_dotenv() on import) is also defended in src/llm_client.py module
# top via a unittest-aware OPENAI_STREAM pop — unittest discover does NOT
# reliably import the tests package, so this file's pop above is only
# best-effort for "python -m unittest tests.x" style invocations.
