"""Adzuna client: fetching and normalization of offers.

Only the official Adzuna API. No scraping. Keywords and sources come from the
user profile (profile_loader.Profile), no longer hardcoded.
"""

import os
import sys

import requests

import config

API_BASE = "https://api.adzuna.com/v1/api/jobs"


def _what_or(source: dict, profile) -> str:
    """what_or = profile domain keywords + the source extra_keywords."""
    return " ".join(profile.KEYWORDS + source.get("extra_keywords", []))


def _build_params(source: dict, profile) -> dict:
    """Builds the Adzuna query params for a source."""
    params = {
        "app_id": os.environ["ADZUNA_APP_ID"],
        "app_key": os.environ["ADZUNA_APP_KEY"],
        "results_per_page": config.RESULTS_PER_PAGE,
        "what_or": _what_or(source, profile),
        "max_days_old": config.MAX_DAYS_OLD,
        "content-type": "application/json",
    }
    if source.get("what"):  # AND text, e.g. "remote"
        params["what"] = source["what"]
    if source.get("where"):
        params["where"] = source["where"]
        if source.get("distance"):
            params["distance"] = source["distance"]
    if config.MIN_SALARY:
        params["salary_min"] = config.MIN_SALARY
    return params


def normalize(raw: dict, source: dict) -> dict:
    """Extracts the useful fields from a raw Adzuna result."""
    description = (raw.get("description") or "")[: config.DESCRIPTION_MAX_CHARS]
    return {
        "id": str(raw.get("id", "")),
        "title": raw.get("title", "") or "",
        "company": (raw.get("company") or {}).get("display_name", "") or "",
        "location": (raw.get("location") or {}).get("display_name", "") or "",
        "description": description,
        "url": raw.get("redirect_url", "") or "",
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "created": raw.get("created", "") or "",
        "country": source["country"],
        "source": source["name"],
    }


def _is_remote(offer: dict) -> bool:
    """True if the title or description contains a remote term."""
    haystack = f"{offer['title']} {offer['description']}".lower()
    return any(term in haystack for term in config.REMOTE_TERMS)


def _fetch_page(source: dict, page: int, profile) -> list[dict]:
    """Fetches and normalizes a single page. [] on error (the run continues)."""
    url = f"{API_BASE}/{source['country']}/search/{page}"
    try:
        resp = requests.get(
            url, params=_build_params(source, profile),
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except (requests.RequestException, ValueError) as exc:
        print(f"[adzuna] '{source['name']}' page {page} failed: {exc}",
              file=sys.stderr)
        return []
    return [normalize(raw, source) for raw in results]


def fetch_source(source: dict, profile) -> list[dict]:
    """Fetches N pages for the source and applies the remote filter."""
    offers: list[dict] = []
    for page in range(1, source.get("pages", 1) + 1):
        page_offers = _fetch_page(source, page, profile)
        offers.extend(page_offers)
        if len(page_offers) < config.RESULTS_PER_PAGE:
            break  # last page reached
    if source.get("remote_filter"):
        offers = [o for o in offers if _is_remote(o)]
    return offers


def fetch_all(profile) -> list[dict]:
    """Fetches from all profile sources, dedups by id, round-robin.

    The round-robin order (1 per source per pass) ensures that a downstream cap
    samples all sources fairly, not just the first ones.
    """
    seen: set[str] = set()
    per_source: list[list[dict]] = []
    for source in profile.SOURCES:
        bucket: list[dict] = []
        for offer in fetch_source(source, profile):
            oid = offer["id"]
            if not oid or oid in seen:
                continue
            seen.add(oid)
            bucket.append(offer)
        per_source.append(bucket)
        print(f"[adzuna] '{source['name']}': {len(bucket)} new unique",
              file=sys.stderr)

    merged: list[dict] = []
    i = 0
    while any(i < len(b) for b in per_source):
        for b in per_source:
            if i < len(b):
                merged.append(b[i])
        i += 1
    print(f"[adzuna] total unique (round-robin): {len(merged)}",
          file=sys.stderr)
    return merged
