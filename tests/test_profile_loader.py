"""Offline tests for TOML profile loading/validation.

Run:  python tests/test_profile_loader.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import profile_loader  # noqa: E402

_VALID = """
profile_text = "test profile"
scoring_rubric = "test rubric"
keywords = ["alpha", "beta"]
remote_extra_keywords = ["gamma"]
remote_query_what = "remote"
[meta]
name = "Test User"
[weights]
tech = 0.45
salary_seniority = 0.20
company = 0.15
location = 0.20
[[sources]]
name = "vicino"
country = "it"
where = "Mantova"
distance = 50
remote_filter = false
[[sources]]
name = "remote_de"
country = "de"
remote_filter = true
extra_keywords = true
"""


def _write(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_load_valid():
    p = profile_loader.load_profile(_write(_VALID))
    assert p.name == "Test User"
    assert abs(sum(p.WEIGHTS.values()) - 1.0) < 1e-9
    assert p.KEYWORDS == ["alpha", "beta"]
    assert len(p.SOURCES) == 2


def test_source_resolution():
    p = profile_loader.load_profile(_write(_VALID))
    by_name = {s["name"]: s for s in p.SOURCES}
    # remote source: what="remote", extra_keywords resolved, default pages
    rem = by_name["remote_de"]
    assert rem["what"] == "remote"
    assert rem["extra_keywords"] == ["gamma"]
    assert rem["pages"] == config.MAX_PAGES_REMOTE
    # local source: no what, no extra, local default pages
    loc = by_name["vicino"]
    assert loc["what"] is None
    assert loc["extra_keywords"] == []
    assert loc["pages"] == config.MAX_PAGES_DEFAULT


def test_weights_must_sum_to_one():
    bad = _VALID.replace("location = 0.20", "location = 0.50")
    try:
        profile_loader.load_profile(_write(bad))
    except profile_loader.ProfileError:
        return
    raise AssertionError("should have rejected weights not summing to 1.0")


def test_no_sources_raises():
    bad = _VALID.split("[[sources]]")[0]  # removes all sources
    try:
        profile_loader.load_profile(_write(bad))
    except profile_loader.ProfileError:
        return
    raise AssertionError("should have rejected a profile with no sources")


_MINIMAL = """
profile_text = "minimal profile without rubric or weights"
keywords = ["alpha"]
[meta]
name = "Min User"
[[sources]]
name = "vicino"
country = "it"
where = "Mantova"
distance = 50
remote_filter = false
"""


def test_minimal_uses_defaults():
    p = profile_loader.load_profile(_write(_MINIMAL))
    assert p.SCORING_RUBRIC == config.DEFAULT_RUBRIC
    assert p.WEIGHTS == config.DEFAULT_WEIGHTS
    assert abs(sum(p.WEIGHTS.values()) - 1.0) < 1e-9


def test_sample_profile():
    p = profile_loader.load_profile(config.DEFAULT_PROFILE)
    assert p.name == "Jordan Avery"
    assert len(p.SOURCES) == 4
    assert p.TOP_N == 15
    assert abs(sum(p.WEIGHTS.values()) - 1.0) < 1e-9


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
