"""
Root conftest.py — project-wide pytest configuration.

tests/hypertensor/ requires a live Substrate node at ws://127.0.0.1:9944.
It is explicitly excluded from the default Layer-1 in-memory test run.
Run it separately only when a local Substrate node is running.
"""

collect_ignore_glob = ["tests/hypertensor/*"]
