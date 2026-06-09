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

# --- Scoring factors (catalog: the single source of truth) ---
# Each factor: label (UI) + weight (default) + rubric (model-facing description,
# without numbering: build_rubric() adds it). The scorer, the report, the loader
# validation and the UI are all driven by this catalog, so the tool is not tied
# to tech roles: a profile activates the factors it wants and weights them.
#
# Sweet spot: 4-6 ACTIVE factors per profile (not how many are in the catalog).
# Beyond ~8 the weights get diluted, the LLM calibrates each factor worse, and
# output tokens/latency grow with little signal gained. See MAX_RECOMMENDED_FACTORS.
FACTORS = {
    # --- core (active by default) ---
    "skill_fit": {
        "label": "Skill & domain fit", "weight": 0.45,
        "rubric": "skill_fit - Fit with the candidate's role, skills and domain. "
                  "High: roles centered on the candidate's domain and stack. "
                  "Low: generic roles or roles outside the candidate's real domain.",
    },
    "salary_seniority": {
        "label": "Seniority & salary", "weight": 0.20,
        "rubric": "salary_seniority - Consistency with the candidate's experience "
                  "level and pay. Penalize and raise a red flag if the ad asks for "
                  "a much higher seniority (senior/managerial for a junior/mid "
                  "profile) or much lower. If salary is stated and consistent, "
                  "score high.",
    },
    "company": {
        "label": "Company & sector", "weight": 0.15,
        "rubric": "company - Quality of the company/sector relative to the "
                  "candidate's interests. High: aligned companies/sectors. Low: "
                  "distant sector or unidentifiable company.",
    },
    "location": {
        "label": "Location & work mode", "weight": 0.20,
        "rubric": "location - Suitability of the location/work mode given the "
                  "preferences. Full remote compatible = full score; on-site/hybrid "
                  "in acceptable areas = full or partial; undesired on-site far "
                  "from home = low, with a red flag.",
    },
    # --- optional (weight 0, selectable) ---
    "culture_values": {
        "label": "Culture & values", "weight": 0.0,
        "rubric": "culture_values - Fit with the company culture and values shown "
                  "in the ad (team, ways of working, stated values).",
    },
    "growth": {
        "label": "Career growth", "weight": 0.0,
        "rubric": "growth - Career growth and learning opportunities "
                  "(progression, training, mentoring, scope of the role).",
    },
    "work_life": {
        "label": "Work-life balance", "weight": 0.0,
        "rubric": "work_life - Work-life balance signals (hours, flexibility, "
                  "on-call load, overtime culture).",
    },
    "contract": {
        "label": "Contract type", "weight": 0.0,
        "rubric": "contract - Match of the contract type with the candidate's "
                  "preference (permanent, fixed-term, contract, part-time, intern).",
    },
    "industry": {
        "label": "Industry / sector", "weight": 0.0,
        "rubric": "industry - Fit with a preferred industry/sector beyond the "
                  "role itself.",
    },
    "mission": {
        "label": "Mission & impact", "weight": 0.0,
        "rubric": "mission - Mission and social impact (non-profit, public "
                  "benefit, meaningfulness of the work).",
    },
    "sustainability": {
        "label": "Sustainability", "weight": 0.0,
        "rubric": "sustainability - Environmental/ESG profile of the company "
                  "(sustainability commitments, green sector).",
    },
    "benefits": {
        "label": "Benefits & perks", "weight": 0.0,
        "rubric": "benefits - Quality of benefits and perks (insurance, leave, "
                  "bonus, equity, allowances).",
    },
    "stability": {
        "label": "Company stability", "weight": 0.0,
        "rubric": "stability - Company stability, size and stage relative to the "
                  "candidate's preference (startup vs scale-up vs corporate).",
    },
}

# Core factors active when a profile does not specify [weights].
DEFAULT_FACTORS = ["skill_fit", "salary_seniority", "company", "location"]

# Backward-compat aliases for renamed factor keys (old TOML -> catalog key).
FACTOR_ALIASES = {"tech": "skill_fit"}

# Soft cap: a warning is logged if a profile activates more than this many
# factors. Recommended sweet spot is 4-6 (see the FACTORS note above).
MAX_RECOMMENDED_FACTORS = 8

# Fixed parts of the rubric, around the per-factor descriptions.
RUBRIC_HEADER = (
    "Score every job offer against the profile with the sub-scores below, each "
    "from 0 to 100. Do NOT compute the total and do NOT weight the factors: a "
    "downstream program applies the weights. Just give an honest, calibrated "
    "judgment for each factor."
)
RUBRIC_REDFLAGS = """\
Red flags to report when present (list, may be empty):
- "remote" ad that is only nominal (e.g. requires work authorization for a
  country not accessible to the candidate).
- Vague description or typical of a staffing agency, with no role details.
- Clear mismatch with the candidate's domain.
- Required seniority much higher, or managerial role out of target.
- Rigid on-site far from home when undesired."""


def factor_label(key: str) -> str:
    """UI label of a factor, falling back to the key itself."""
    return FACTORS.get(key, {}).get("label", key)


def default_weights() -> dict:
    """Default weights = the core factors with their catalog weights."""
    return {k: FACTORS[k]["weight"] for k in DEFAULT_FACTORS}


def build_rubric(factor_keys) -> str:
    """Builds the model-facing rubric from the active factors (numbered).

    Unknown keys are skipped (mirrors factor_label's graceful fallback) so a bad
    caller cannot crash rubric generation.
    """
    known = [k for k in factor_keys if k in FACTORS]
    lines = [RUBRIC_HEADER, ""]
    for i, k in enumerate(known, 1):
        lines.append(f"{i}) {FACTORS[k]['rubric']}")
        lines.append("")
    lines.append(RUBRIC_REDFLAGS)
    return "\n".join(lines)


# Backward-compat aliases (some code/tests still reference these names).
DEFAULT_WEIGHTS = default_weights()
DEFAULT_RUBRIC = build_rubric(DEFAULT_FACTORS)

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
