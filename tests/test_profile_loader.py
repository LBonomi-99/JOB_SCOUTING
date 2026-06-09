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
skill_fit = 0.45
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
    assert "skill_fit" in p.WEIGHTS
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


def test_weights_autonormalized():
    # relative weights that do not sum to 1.0 -> normalized.
    raw = _VALID.replace(
        "skill_fit = 0.45\nsalary_seniority = 0.20\ncompany = 0.15\nlocation = 0.20",
        "skill_fit = 2\nlocation = 2")
    p = profile_loader.load_profile(_write(raw))
    assert abs(sum(p.WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(p.WEIGHTS["skill_fit"] - 0.5) < 1e-9
    assert abs(p.WEIGHTS["location"] - 0.5) < 1e-9


def test_alias_tech_to_skill_fit():
    # old TOML using 'tech' still loads, mapped to 'skill_fit'.
    raw = _VALID.replace("skill_fit = 0.45", "tech = 0.45")
    p = profile_loader.load_profile(_write(raw))
    assert "skill_fit" in p.WEIGHTS
    assert "tech" not in p.WEIGHTS


def test_zero_weight_factor_dropped():
    # a factor explicitly set to 0 is not active (dropped, not kept at 0%).
    raw = _VALID.replace("company = 0.15", "company = 0")
    p = profile_loader.load_profile(_write(raw))
    assert "company" not in p.WEIGHTS
    assert abs(sum(p.WEIGHTS.values()) - 1.0) < 1e-9


def test_invalid_factor_rejected():
    raw = _VALID.replace("skill_fit = 0.45", "banana = 0.45")
    try:
        profile_loader.load_profile(_write(raw))
    except profile_loader.ProfileError:
        return
    raise AssertionError("should have rejected an unknown factor key")


def test_custom_factors_and_rubric():
    # a non-tech profile with optional factors; rubric auto-built from them.
    raw = _VALID.replace(
        'scoring_rubric = "test rubric"\n', "").replace(
        "skill_fit = 0.45\nsalary_seniority = 0.20\ncompany = 0.15\nlocation = 0.20",
        "skill_fit = 0.5\nmission = 0.3\nwork_life = 0.2")
    p = profile_loader.load_profile(_write(raw))
    assert set(p.WEIGHTS) == {"skill_fit", "mission", "work_life"}
    assert "mission" in p.SCORING_RUBRIC
    assert "work_life" in p.SCORING_RUBRIC


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
