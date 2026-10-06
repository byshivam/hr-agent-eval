import os

# Unit tests run fully offline with a scripted model — no API key needed.
os.environ.setdefault("LLM_PROVIDER", "stub")
