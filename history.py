"""History and run-to-run comparison.

- seen.json: maps adzuna_id -> first-seen date (YYYY-MM-DD).
- Marks offers never seen before (offer["is_new"]) for the report badge.
  NB: it does NOT skip scoring (it is not a dedup): it re-scores everything and
  only marks.
- Saves each report both as reports/report-<timestamp>.md (history) and as
  report.md (latest, handy for run.bat).
- Forgets ids older than SEEN_RETENTION_DAYS (avoids unbounded growth).
"""

import json
import os
from datetime import date, datetime, timedelta

import config


def load_seen(path: str = None) -> dict:
    """Loads seen.json (id -> ISO date). {} if missing or corrupt."""
    path = path or config.SEEN_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def mark_new(offers: list[dict], seen: dict, today: str = None) -> int:
    """Marks offer['is_new'] and updates `seen`. Returns how many are new."""
    today = today or date.today().isoformat()
    new_count = 0
    for offer in offers:
        oid = offer.get("id", "")
        if oid and oid not in seen:
            offer["is_new"] = True
            seen[oid] = today
            new_count += 1
        else:
            offer["is_new"] = False
    return new_count


def prune(seen: dict, today: str = None,
          retention_days: int = None) -> dict:
    """Removes ids older than retention_days. Returns the pruned dict."""
    retention_days = retention_days or config.SEEN_RETENTION_DAYS
    ref = datetime.fromisoformat(today).date() if today else date.today()
    cutoff = ref - timedelta(days=retention_days)
    kept = {}
    for oid, seen_on in seen.items():
        try:
            d = datetime.fromisoformat(seen_on).date()
        except (ValueError, TypeError):
            continue  # corrupt date: discard
        if d >= cutoff:
            kept[oid] = seen_on
    return kept


def save_seen(seen: dict, path: str = None) -> None:
    """Persists seen.json (creates the folder if needed)."""
    path = path or config.SEEN_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, ensure_ascii=False, indent=2)


def save_report(md: str, reports_dir: str = None,
                latest_path: str = None) -> str:
    """Saves the report to the dated history and as report.md. Returns the history path."""
    reports_dir = reports_dir or config.REPORTS_DIR
    latest_path = latest_path or config.LATEST_REPORT_PATH
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    hist_path = os.path.join(reports_dir, f"report-{ts}.md")
    for p in (hist_path, latest_path):
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(md)
    return hist_path
