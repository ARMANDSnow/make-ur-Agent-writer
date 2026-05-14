"""Force tests to use mock LLM settings before project config loads .env."""

import os

os.environ["OPENAI_MODEL"] = "mock"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("OPENAI_BASE_URL", None)
