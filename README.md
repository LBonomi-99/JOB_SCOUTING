# JobScouting

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A tool that fetches job offers from **Adzuna**, scores them with an **LLM
(Claude)** against a **personal profile** (weighted, explainable scoring) and
produces a **Markdown report** with the top-N, the red flags and a **gap
analysis** for each offer. It keeps a **history** of runs and marks offers never
seen before with 🆕.

The profile is **externalized** in a TOML file, so anyone can use it for
themselves without touching the code. You can create the profile from your CV
with a guided wizard or a local web app, no hand-written TOML required.

## Highlights
- **Deterministic hybrid scoring**: the LLM gives 4 sub-scores 0-100, Python
  computes the weighted total, explainable and repeatable.
- **Free LLM**: the `claude_cli` backend uses your subscription (no tokens).
- **Generic**: one TOML profile per person. No scraping, only the Adzuna API.
- **Two ways in**: a local **web app** (default) or a **terminal** wizard.

## Requirements
- Python 3.11+ (TOML parsing uses `tomllib`, stdlib).
- Adzuna credentials (App ID + App Key): https://developer.adzuna.com/
- An LLM backend (default **`claude` CLI**, subscription, free; or the
  token-based API).

## Setup
```bash
pip install -r requirements.txt   # anthropic is only for the API backend
copy .env.example .env            # then fill in ADZUNA_APP_ID and ADZUNA_APP_KEY
```

## Usage
Double-click **`run.bat`** (Windows), or:
```bash
python main.py                              # default: WEB APP in the browser
python main.py --cli                        # onboarding/scoring in the terminal
python main.py --profile profiles/you.toml  # direct scoring on a profile (CLI)
```
**`python main.py` with no arguments** opens the **web app** (`127.0.0.1:5000`):
upload your CV, confirm the fields, run the automation and watch the report and
live log (see "Web app"). It falls back to the **terminal** with `--cli`, or
automatically if you pass a CLI flag (`--profile`, `--init`, `--cv`).

In the **`--cli`** flow:
- if the active profile `profiles/profile.toml` exists -> it asks whether to use it;
- if it does not exist (or you choose "new") -> the **onboarding** starts
  (wizard + CV) which creates it, then **scoring runs automatically**.

Output: `report.md` (latest) + `reports/report-<timestamp>.md` (history).

## Web app (browser)
This is the **default** of `python main.py`. A local interface to upload the CV
and run everything from the browser (`--web` forces it even with other flags):
```bash
pip install -r requirements.txt   # includes flask + markdown
python main.py                    # or: python main.py --web
```
It opens `http://127.0.0.1:5000`: you upload the **CV** (PDF/TXT), the model
extracts the profile, you **confirm** the fields (name, city, keywords as chips,
**how many offers** in the report, **which countries** for remote as checkboxes
with full names, advanced weights), you **run** the automation and see the
**live progress** (SSE) and finally the rendered **report**. It writes the same
`profiles/profile.toml` + `report.md`. `127.0.0.1` only, single-user.

## Onboarding without TOML (recommended)
To create your profile **without writing the file by hand**:
```bash
python main.py --init
```
First a **popup** lets you choose the **CV PDF**: the model extracts name, city,
role, skills, seniority and keywords. Then the wizard asks **only what is
missing** (report language, city confirmation, local radius, how many offers in
the report, remote yes/no and which countries, advanced weights). You confirm
the keywords, the profile is written, and you can launch scoring right away.
- To **skip the popup** pass the CV from the command line (PDF or TXT):
  ```bash
  python main.py --init --cv "path/to/CV.pdf"
  ```
  Useful for headless environments or to repeat the setup.
- If the file picker is unavailable or the PDF is a scan, fall back by pasting
  the CV text into the terminal.
- `rubric` and `weights` are not required: they use the `config.py` defaults
  (`DEFAULT_RUBRIC` / `DEFAULT_WEIGHTS`). The wizard offers an advanced mode to
  customize the weights.
- Extracted keywords pass through a **stoplist** (`config.GENERIC_KEYWORDS`):
  terms that are too generic (e.g. `engineer`, `software`, `automation`) are
  dropped from the narrow query. If they all get dropped, it falls back to the
  original list (narrow them by hand at confirmation). The
  `remote_extra_keywords` are not filtered (intentionally broad bucket).

## Using your own profile (manual)
An alternative to the wizard, for full control:
1. `copy profiles\example.toml profiles\you.toml`
2. Fill in the profile, keywords and sources. `scoring_rubric` and `[weights]`
   are **optional** (defaults apply if absent); if you set them, the weights must
   sum to 1.0.
3. `python main.py --profile profiles/you.toml`

## Scoring backend (`config.py`, `SCORER_BACKEND`)
- `"claude_cli"` (default) — headless `claude` CLI on your **subscription**
  (Pro/Max), no `ANTHROPIC_API_KEY`, zero cost. Single-user, device-bound,
  subject to rate limits.
- `"anthropic_api"` — token-based SDK (`ANTHROPIC_API_KEY` + `pip install
  anthropic`). Recommended for **shared/multi-user** use (the subscription does
  not scale).

## Configuration
- **Global** (`config.py`): backend, model, `MAX_OFFERS_TO_SCORE`, `BATCH_SIZE`,
  `MAX_DAYS_OLD`, `REMOTE_TERMS`, history retention, paths. Profile defaults
  (`DEFAULT_RUBRIC`, `DEFAULT_WEIGHTS`, `DEFAULT_TOP_N`), the `GENERIC_KEYWORDS`
  stoplist used by `--init`, and `REMOTE_COUNTRIES` / `COUNTRY_NAMES`.
- **Per-user** (`profiles/*.toml`): profile, rubric, `[weights]` (tech 45% ·
  salary/seniority 20% · company 15% · location 20% by default), keywords,
  Adzuna sources. The rubric does NOT repeat the weight numbers.
  `[meta].report_top_n` (optional, default `config.DEFAULT_TOP_N` = 15) sets how
  many offers to show in the report.

## Structure
| File | Role |
|------|------|
| `config.py` | Global non-user parameters. |
| `profiles/*.toml` | User profile (profile, rubric, weights, keywords, sources). |
| `profiles/sample.toml` | Fictional ready-to-run example (also the default profile). |
| `profiles/example.toml` | Empty template to copy. |
| `profile_loader.py` | Loads and validates a TOML profile (rubric/weights optional -> defaults). |
| `llm.py` | Reusable LLM backend (CLI/API) + robust JSON parsing. |
| `init_profile.py` | Guided onboarding `--init`: wizard + CV PDF extraction + TOML writer. |
| `adzuna.py` | Adzuna client: fetch, normalization, intra-run dedup, round-robin. |
| `scorer.py` | Batch LLM scoring (via `llm.py`), gap analysis. |
| `history.py` | Dated report history + 🆕 marking of never-seen offers. |
| `report.py` | Markdown top-N report (breakdown, red flags, gap). |
| `main.py` | End-to-end orchestration (`--web` default · `--cli` · `--profile`). |
| `webapp.py` | Local Flask web app (CV upload, SSE, report) — `python main.py`. |
| `templates/index.html` | Single-page web app (3 steps, vanilla JS). |
| `run.bat` | One-click launch (Windows) -> web app. |
| `tests/` | Offline tests (parser, loader, history). |

## Tests
```bash
python tests/test_parse.py
python tests/test_profile_loader.py
python tests/test_history.py
```

## Out of scope
Scraping of any site, scheduling/cron, dedup that skips scoring, email/Telegram
sending, CV/cover-letter generation, feeds other than Adzuna.

## License
[MIT](LICENSE) © 2026 Leonardo Bonomi
