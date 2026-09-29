import os
import sys
import tempfile

# Make the repo root importable so tests can import the app modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tests always run the app in self-host (BYOK) mode. app.py freezes
# BILLING_ENABLED at import time and load_dotenv never overrides an existing
# variable, so this must be set here — before any test module imports app — or
# the suite's behavior would depend on the developer's personal .env.
os.environ["BILLING_ENABLED"] = "0"

# The self-host pipeline (pipeline/) opens a SQLite file when the app starts.
# Keep it out of the working tree and keep its background loop off in tests.
os.environ.setdefault("PIPELINE_DATA_DIR", tempfile.mkdtemp(prefix="pipeline_test_"))
os.environ.setdefault("PIPELINE_ENABLED", "0")
