"""Offline tests for the history/comparison logic (seen.json). No real API.

Run:  python tests/test_history.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import history  # noqa: E402


def test_mark_new_first_then_seen():
    offers = [{"id": "a"}, {"id": "b"}]
    seen = {}
    n = history.mark_new(offers, seen, today="2026-06-02")
    assert n == 2
    assert all(o["is_new"] for o in offers)
    assert seen == {"a": "2026-06-02", "b": "2026-06-02"}

    # second run: same offers -> none new
    offers2 = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    n2 = history.mark_new(offers2, seen, today="2026-06-03")
    assert n2 == 1  # only "c"
    assert offers2[0]["is_new"] is False
    assert offers2[2]["is_new"] is True


def test_prune_drops_old():
    seen = {
        "old": "2026-01-01",      # >90d before the ref
        "recent": "2026-05-20",
    }
    kept = history.prune(seen, today="2026-06-02", retention_days=90)
    assert "recent" in kept
    assert "old" not in kept


def test_prune_keeps_corrupt_out():
    seen = {"good": "2026-06-01", "broken": "not-a-date"}
    kept = history.prune(seen, today="2026-06-02", retention_days=90)
    assert "good" in kept
    assert "broken" not in kept


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
