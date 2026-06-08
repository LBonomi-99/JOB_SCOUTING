"""Offline tests for the JSON parser and the weighted sum. No real API.

Run:  python tests/test_parse.py   (or  python -m tests.test_parse)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
import scorer  # noqa: E402

WEIGHTS = {"tech": 0.45, "salary_seniority": 0.20, "company": 0.15, "location": 0.20}


def test_parse_clean_array():
    out = llm.parse_json('[{"id": "1", "sub_scores": {"tech": 90}}]')
    assert out[0]["id"] == "1"


def test_parse_with_prose_wrapper():
    out = llm.parse_json('Here are the results:\n[{"id": "2"}]\nDone.')
    assert out[0]["id"] == "2"


def test_parse_object():
    out = llm.parse_json('Here:\n{"profile_text": "x", "keywords": ["a"]}\ndone')
    assert out["keywords"] == ["a"]


def test_parse_invalid_raises():
    try:
        llm.parse_json("not a json")
    except ValueError:
        return
    raise AssertionError("should have raised ValueError")


def test_weighted_total():
    sub = {"tech": 100, "salary_seniority": 100, "company": 100, "location": 100}
    assert scorer.weighted_total(sub, WEIGHTS) == 100.0
    sub2 = {"tech": 80, "salary_seniority": 60, "company": 40, "location": 0}
    expected = round(sum(WEIGHTS[k] * sub2[k] for k in WEIGHTS), 1)
    assert scorer.weighted_total(sub2, WEIGHTS) == expected


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
