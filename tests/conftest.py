import os
import sys
import tempfile

# Make the repo root importable so tests can import the app modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The self-host pipeline (pipeline/) opens a SQLite file when the app starts.
# Keep it out of the working tree and keep its background loop off in tests.
os.environ.setdefault("PIPELINE_DATA_DIR", tempfile.mkdtemp(prefix="pipeline_test_"))
os.environ.setdefault("PIPELINE_ENABLED", "0")
