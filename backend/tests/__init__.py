import logging

# Phase 2 tests deliberately trigger ingestion failures; keep their expected tracebacks out of the test output.
logging.getLogger("knowledge.ingest").setLevel(logging.CRITICAL)
