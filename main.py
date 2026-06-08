"""End-to-end orchestration of JobScouting.

Run:    python main.py [--profile profiles/sample.toml]
Output: report printed to screen + report.md + reports/report-<timestamp>.md
"""

import argparse
import os
import shutil
import sys

from dotenv import load_dotenv

import adzuna
import config
import history
import profile_loader
import report
import scorer


def _force_utf8_io() -> None:
    """Forces stdout/stderr to UTF-8.

    On Windows the console is cp1252 and print() of the report (which contains
    emoji like 🆕) would raise UnicodeEncodeError. errors='replace' avoids any
    residual crash.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def _missing_requirements() -> list[str]:
    """List (empty = ok) of missing prerequisites: Adzuna keys + LLM backend.

    Does not exit: used both by the CLI (fail-fast) and the web app (error in
    the page).
    """
    msgs = []
    for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        if not os.environ.get(k):
            msgs.append(f"missing {k} in .env")
    if config.SCORER_BACKEND == "anthropic_api" and not os.environ.get("ANTHROPIC_API_KEY"):
        msgs.append("missing ANTHROPIC_API_KEY in .env (anthropic_api backend)")
    if config.SCORER_BACKEND == "claude_cli" and shutil.which("claude") is None:
        msgs.append("CLI 'claude' not in PATH (claude_cli backend)")
    return msgs


def _check_keys() -> None:
    """Validates the prerequisites before starting (fail-fast for the CLI)."""
    msgs = _missing_requirements()
    if msgs:
        for m in msgs:
            print(m, file=sys.stderr)
        print("Copy .env.example to .env and fill in the keys "
              "(or change SCORER_BACKEND in config.py).", file=sys.stderr)
        sys.exit(1)
    if config.SCORER_BACKEND == "claude_cli":
        print("[main] scoring backend: claude_cli (subscription, no API key).",
              file=sys.stderr)


def _load_profile(path: str):
    try:
        return profile_loader.load_profile(path)
    except profile_loader.ProfileError as exc:
        print(f"[main] invalid profile: {exc}", file=sys.stderr)
        sys.exit(1)


def fetch_only(profile_path: str = None) -> list[dict]:
    """Smoke test without scoring: fetch + per-source counts (zero LLM cost)."""
    load_dotenv()
    profile = _load_profile(profile_path or config.DEFAULT_PROFILE)
    return adzuna.fetch_all(profile)


def run_pipeline(profile, profile_path: str, echo_report: bool = True) -> str:
    """End-to-end pipeline on an already-loaded profile: fetch -> scoring -> report.

    Assumes load_dotenv() and _check_keys() already done by the caller.
    echo_report: if False does not print the markdown to stdout (used by the web
    app, which renders it as HTML). Returns the report markdown.
    """
    print(f"[main] profile: {profile.name} ({profile_path})", file=sys.stderr)

    print("[main] fetching offers from Adzuna...", file=sys.stderr)
    offers = adzuna.fetch_all(profile)
    total_fetched = len(offers)
    print(f"[main] {total_fetched} unique offers fetched.", file=sys.stderr)

    if not offers:
        print("No offers fetched. Check keys/keywords/sources.",
              file=sys.stderr)

    # History/comparison: mark offers never seen before.
    seen = history.load_seen()
    new_count = history.mark_new(offers, seen)
    print(f"[main] of which never seen before: {new_count}", file=sys.stderr)

    capped = offers[: config.MAX_OFFERS_TO_SCORE]
    if len(capped) < total_fetched:
        print(f"[main] capped at {config.MAX_OFFERS_TO_SCORE} offers to score.",
              file=sys.stderr)

    print("[main] scoring with the model...", file=sys.stderr)
    scored = scorer.score_all(capped, profile)

    md = report.build_report(scored, total_fetched, profile,
                             total_attempted=len(capped), new_count=new_count)

    hist_path = history.save_report(md)

    # Persist the seen ids (pruning the expired ones).
    seen = history.prune(seen)
    history.save_seen(seen)

    if echo_report:
        print("\n" + md)
    print(f"\n[main] report saved to {config.LATEST_REPORT_PATH} and {hist_path}",
          file=sys.stderr)
    return md


def _interactive_profile(cv_path: str) -> str:
    """Startup without --profile: use the active profile or create a new one (onboarding).

    Returns the path of the profile to score. Exits if onboarding is cancelled.
    """
    import init_profile  # lazy: avoids circular import
    active = config.ACTIVE_PROFILE
    if os.path.exists(active):
        if init_profile._ask_yesno(
                f"Found active profile ({active}). Use it? "
                "(n = create a new one)", True):
            return active
    # No active profile, or the user wants a new one: onboarding.
    path = init_profile.run_init(launch_after=False, cv_path=cv_path,
                                 out_path=active)
    if not path:
        print("Onboarding cancelled: no profile to score.", file=sys.stderr)
        sys.exit(1)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="JobScouting — job offer scoring")
    parser.add_argument("--profile", default=None,
                        help="path of the TOML profile. If omitted: interactive "
                             "startup (uses profiles/profile.toml or creates it "
                             "via onboarding)")
    parser.add_argument("--init", action="store_true",
                        help="create a new guided profile (wizard + CV extraction) "
                             "without writing the TOML by hand")
    parser.add_argument("--cv", default=None,
                        help="path of the CV (PDF or TXT) for onboarding: skips "
                             "the file picker popup")
    parser.add_argument("--web", action="store_true",
                        help="force the local web app (default with no other "
                             "flags): upload CV + automation from the browser")
    parser.add_argument("--cli", action="store_true",
                        help="force onboarding/scoring in the terminal instead of "
                             "the browser")
    args = parser.parse_args()
    _force_utf8_io()

    # Default = web. Switches to CLI only with --cli or with flags that imply it
    # (--profile / --init / --cv: terminal operations).
    use_web = args.web or not (args.cli or args.init or args.profile or args.cv)
    if use_web:
        import webapp  # lazy: depends on Flask (extra)
        webapp.serve()
        return

    if args.init:
        import init_profile  # lazy: avoids circular import
        init_profile.run_init(cv_path=args.cv)
        return

    load_dotenv()
    # Explicit --profile: direct scoring. Otherwise interactive startup.
    profile_path = args.profile or _interactive_profile(args.cv)
    _check_keys()
    profile = _load_profile(profile_path)
    run_pipeline(profile, profile_path)


if __name__ == "__main__":
    main()
