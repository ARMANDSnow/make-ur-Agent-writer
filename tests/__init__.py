"""Force tests to use mock LLM settings before project config loads .env."""

import os

os.environ["OPENAI_MODEL"] = "mock"
os.environ["PLANNER_MODEL"] = "mock"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
os.environ["DRAGON_RAJA_SKIP_DOTENV"] = "1"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
for key in (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_STREAM",
    "PLANNER_API_KEY",
    "PLANNER_BASE_URL",
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
