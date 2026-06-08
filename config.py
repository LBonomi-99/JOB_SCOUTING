"""GLOBAL, non-user configuration for JobScouting.

Only the parameters that do NOT depend on the user profile live here: scoring
backend, model, batching, technical Adzuna limits, remote detection, paths.

Everything user-specific (profile, keywords, sources, weights) lives in the TOML
profile files under profiles/ and is loaded by profile_loader.py.
"""

import os

# --- Scoring backend ---
# "claude_cli"    = headless `claude` CLI (Pro/Max subscription, FREE, no
#                   ANTHROPIC_API_KEY). Single-user, device-bound. Rate limited.
# "anthropic_api" = Anthropic SDK billed per token (needs ANTHROPIC_API_KEY).
#                   Recommended for shared/multi-user use.
SCORER_BACKEND = "claude_cli"

# Model for the token-based API backend.
ANTHROPIC_MODEL = "claude-haiku-4-5"

# Model for the CLI backend: `claude --model` alias ("haiku", "sonnet") or full id.
CLAUDE_CLI_MODEL = "haiku"
CLI_TIMEOUT = 180  # seconds per CLI call

# --- Profile defaults (used when the TOML does not specify them) ---
# Weights of the 4 scoring factors. Must sum to 1.0.
DEFAULT_WEIGHTS = {
    "tech": 0.45,
    "salary_seniority": 0.20,
    "company": 0.15,
    "location": 0.20,
}

# Generic rubric: instructions to the model on how to assign the 4 sub-scores
# 0-100. Applies to any profile; it does not repeat the weight numbers (Python
# applies those).
DEFAULT_RUBRIC = """\
Score every job offer against the profile with FOUR sub-scores, each from 0 to
100. Do NOT compute the total and do NOT weight the factors: a downstream
program applies the weights. Just give an honest, calibrated judgment for each
factor.

1) tech - Technical fit with the candidate's domain and skills.
   - High: roles centered on the candidate's domain and stack.
   - Low: generic roles or roles outside the candidate's real domain.

2) salary_seniority - Consistency with the candidate's experience level.
   - Penalize and raise a red flag if the ad asks for a much higher seniority
     (senior/managerial roles for a junior/mid profile) or much lower. If the
     salary is stated and consistent, score high.

3) company - Quality of company/sector relative to the candidate's interests.
   - High: companies/sectors aligned with the profile.
   - Low: distant sector or unidentifiable company.

4) location - Suitability of the location/work mode given the preferences.
   - Full remote compatible with the preferences = full score.
   - On-site/hybrid in acceptable areas = full or partial.
   - On-site far from home when undesired = low, with a red flag.

Red flags to report when present (list, may be empty):
- "remote" ad that is only nominal (e.g. requires work authorization for a
  country not accessible to the candidate).
- Vague description or typical of a staffing agency, with no role details.
- Clear mismatch with the candidate's domain.
- Required seniority much higher, or managerial role out of target.
- Rigid on-site far from home when undesired.
"""

# Stoplist of keywords too generic for the narrow Adzuna query (used by
# `--init`): on their own they match too many off-target offers and get dropped
# from the `keywords` extracted from the CV. Case-insensitive comparison.
# Tunable: add/remove terms for your domain.
GENERIC_KEYWORDS = {
    "engineer", "engineering", "electrical engineering", "software engineering",
    "software", "software development", "developer", "development", "automation",
    "control systems", "management", "manager", "consultant", "consulting",
    "technician", "analyst", "it", "tech", "technology", "professional",
    "specialist", "operations", "design", "research", "project management",
    # "<x> engineer" role titles too generic (match too many offers).
    # NB: useful domain titles (e.g. "power system engineer") do NOT belong here.
    "electrical engineer", "mechanical engineer", "civil engineer",
    "software engineer", "systems engineer", "system engineer",
    "control engineer", "design engineer", "project engineer", "test engineer",
    "hardware engineer", "field engineer", "application engineer",
    "sales engineer", "process engineer", "automation engineer",
}

# --- Volume and batching ---
MAX_OFFERS_TO_SCORE = 200   # cap of offers scored per run (controls cost)
BATCH_SIZE = 12             # offers per single model call
MAX_TOKENS_PER_BATCH = 4096  # output token ceiling per batch

# --- Adzuna (technical) ---
MAX_DAYS_OLD = 30           # ad freshness
RESULTS_PER_PAGE = 50       # max allowed by Adzuna
DESCRIPTION_MAX_CHARS = 1500  # description truncation to keep tokens down
REQUEST_TIMEOUT = 20        # seconds per HTTP request
MIN_SALARY = None           # optional global salary filter; None = no filter

# --- Remote detection (logic, not a user preference) ---
# Terms that identify a remote ad, localized per language (case-insensitive,
# matched on title+description).
REMOTE_TERMS = [
    # english
    "remote", "full remote", "fully remote", "remote-first", "remote-friendly",
    "work from home", "home office", "homeoffice", "hybrid", "wfh",
    # italian
    "smart working", "da remoto", "lavoro da remoto", "telelavoro", "ibrido",
    "da casa",
    # german
    "homeoffice", "remote-arbeit", "mobiles arbeiten",
    # french
    "teletravail", "télétravail", "a distance", "à distance", "hybride",
    # spanish
    "teletrabajo", "trabajo remoto", "remoto", "hibrido", "híbrido",
    # dutch
    "thuiswerken", "op afstand",
]

# Selectable countries for the remote sources (EU/EEA set accessible from IT
# without work authorization; US excluded). Default: all. The user can narrow
# the selection (--cli wizard or checkboxes in the web app).
REMOTE_COUNTRIES = ["it", "gb", "de", "fr", "nl", "es", "at", "be", "pl", "ch"]

# Full names of the country codes (to show them readably in the UI instead of
# the bare codes).
COUNTRY_NAMES = {
    "it": "Italy", "gb": "United Kingdom", "de": "Germany", "fr": "France",
    "nl": "Netherlands", "es": "Spain", "at": "Austria", "be": "Belgium",
    "pl": "Poland", "ch": "Switzerland",
}


def country_name(code: str) -> str:
    """Full name of the country code, falling back to the uppercase code."""
    return COUNTRY_NAMES.get(code.lower(), code.upper())


# Number of offers shown in the report (top-N). Per-profile override via
# [meta].report_top_n. Used as default when absent.
DEFAULT_TOP_N = 15

# --- Default pagination (per-source override in the profile) ---
MAX_PAGES_DEFAULT = 1   # local sources (near_home / city)
MAX_PAGES_REMOTE = 3    # remote sources: more pages = more material to filter

# --- Paths ---
_HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(_HERE, "profiles")
REPORTS_DIR = os.path.join(_HERE, "reports")
DATA_DIR = os.path.join(_HERE, "data")
SEEN_PATH = os.path.join(DATA_DIR, "seen.json")
LATEST_REPORT_PATH = os.path.join(_HERE, "report.md")

# Default profile for fetch_only / reference (committed, fictional sample).
DEFAULT_PROFILE = os.path.join(PROFILES_DIR, "sample.toml")

# "Active" profile used by `python main.py` without --profile: if missing, the
# interactive startup offers onboarding and writes it here.
ACTIVE_PROFILE = os.path.join(PROFILES_DIR, "profile.toml")

# Days after which a "seen" id is forgotten from seen.json.
SEEN_RETENTION_DAYS = 90
