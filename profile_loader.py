"""Loading and validation of a user profile from a TOML file.

The profile externalizes everything that used to be hardcoded: profile text,
rubric, weights, keywords and Adzuna sources. This makes JobScouting generic:
anyone creates their own profiles/<name>.toml without touching the code.

TOML is read with tomllib (stdlib Python 3.11+): no new dependency.
"""

import tomllib
from dataclasses import dataclass, field

import config

# Expected weight keys (must match the factors used by the scorer).
REQUIRED_WEIGHT_KEYS = {"tech", "salary_seniority", "company", "location"}


class ProfileError(ValueError):
    """Profile missing, malformed or invalid."""


@dataclass
class Profile:
    name: str
    report_language: str
    PROFILE_TEXT: str
    SCORING_RUBRIC: str
    WEIGHTS: dict
    KEYWORDS: list
    TOP_N: int = config.DEFAULT_TOP_N
    SOURCES: list = field(default_factory=list)


def _build_source(raw: dict, remote_query_what, remote_extra_keywords) -> dict:
    """Normalizes a [[sources]] TOML entry into the dict used by adzuna.py."""
    if not raw.get("name") or not raw.get("country"):
        raise ProfileError(
            f"source without 'name' or 'country': {raw!r}")
    remote_filter = bool(raw.get("remote_filter", False))

    # pages: explicit, otherwise default per source type.
    pages = raw.get("pages")
    if pages is None:
        pages = config.MAX_PAGES_REMOTE if remote_filter else config.MAX_PAGES_DEFAULT

    # what (AND): explicit; otherwise remote_query_what on remote sources.
    what = raw.get("what")
    if what is None and remote_filter and remote_query_what:
        what = remote_query_what

    # extra_keywords: bool flag in the TOML -> list resolved from the profile.
    extra = remote_extra_keywords if raw.get("extra_keywords") else []

    return {
        "name": raw["name"],
        "country": raw["country"],
        "where": raw.get("where"),
        "distance": raw.get("distance", 0),
        "remote_filter": remote_filter,
        "pages": pages,
        "what": what,
        "extra_keywords": list(extra),
    }


def load_profile(path: str) -> Profile:
    """Loads and validates a TOML profile. Raises ProfileError if invalid."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise ProfileError(f"profile not found: {path}")
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"malformed TOML in {path}: {exc}")

    meta = data.get("meta", {})
    name = meta.get("name")
    if not name:
        raise ProfileError("missing [meta].name in the profile")

    profile_text = data.get("profile_text")
    if not profile_text:
        raise ProfileError("missing 'profile_text' in the profile")
    # scoring_rubric and weights are optional: fall back to config defaults.
    rubric = data.get("scoring_rubric") or config.DEFAULT_RUBRIC

    weights = data.get("weights")
    if weights is None:
        weights = dict(config.DEFAULT_WEIGHTS)
    if not isinstance(weights, dict) or set(weights) != REQUIRED_WEIGHT_KEYS:
        raise ProfileError(
            f"[weights] must have exactly the keys {sorted(REQUIRED_WEIGHT_KEYS)}")
    wsum = sum(float(v) for v in weights.values())
    if abs(wsum - 1.0) > 1e-9:
        raise ProfileError(f"weights must sum to 1.0 (current sum: {wsum})")

    keywords = data.get("keywords")
    if not keywords:
        raise ProfileError("'keywords' missing or empty")

    raw_sources = data.get("sources")
    if not raw_sources:
        raise ProfileError("no [[sources]] defined in the profile")

    remote_query_what = data.get("remote_query_what")
    remote_extra = data.get("remote_extra_keywords", [])
    sources = [_build_source(s, remote_query_what, remote_extra)
               for s in raw_sources]

    # report top-N: [meta].report_top_n (or top-level), optional, config default.
    top_n = meta.get("report_top_n", data.get("report_top_n", config.DEFAULT_TOP_N))
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        raise ProfileError(f"report_top_n must be an integer, not {top_n!r}")
    if top_n < 1:
        raise ProfileError("report_top_n must be >= 1")

    return Profile(
        name=name,
        report_language=meta.get("report_language", "english"),
        PROFILE_TEXT=profile_text,
        SCORING_RUBRIC=rubric,
        WEIGHTS={k: float(v) for k, v in weights.items()},
        KEYWORDS=list(keywords),
        TOP_N=top_n,
        SOURCES=sources,
    )
