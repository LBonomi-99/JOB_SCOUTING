"""Guided creation of a JobScouting profile without writing the TOML by hand.

Command:  python main.py --init

Division of responsibilities:
- LLM (llm.py)  -> extracts the subjective part from the CV PDF: prose profile,
                   seniority, domain keywords.
- Wizard        -> collects the factual part (city, country code, remote,
                   language) that the model should not guess.
- Defaults      -> scoring_rubric and weights come from the config.py defaults
                   (rubric always; weights unless advanced mode).

Output: profiles/<slug>.toml; optionally launches scoring immediately.
"""

import json
import os
import re
import shutil
import sys

from dotenv import load_dotenv

import config
import llm
import profile_loader


# --------------------------------------------------------------------------- #
# Input helpers
# --------------------------------------------------------------------------- #
def _input(prompt: str = "") -> str:
    """input() cleaned of BOM and zero-width chars (robust to pasted/piped stdin).

    Handles both the proper BOM (U+FEFF) and the UTF-8 BOM decoded as mojibake
    (\\xef\\xbb\\xbf), which can appear at the head of piped stdin.
    """
    raw = input(prompt)
    if raw[:1] == "﻿":
        raw = raw[1:]
    if raw[:3] == "\xef\xbb\xbf":
        raw = raw[3:]
    return "".join(ch for ch in raw if ch not in "﻿​‌‍").strip()


def _ask(prompt: str, default: str = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = _input(f"{prompt}{suffix}: ")
    return val or (default or "")


def _ask_required(prompt: str) -> str:
    while True:
        val = _input(f"{prompt}: ")
        if val:
            return val
        print("  (required field)")


def _ask_yesno(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    val = _input(f"{prompt} [{d}]: ").lower()
    if not val:
        return default
    return val in ("y", "yes")


def _ask_int(prompt: str, default: int) -> int:
    while True:
        val = _input(f"{prompt} [{default}]: ")
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            print("  (enter a whole number)")


def _ask_float(prompt: str, default: float) -> float:
    while True:
        val = _input(f"{prompt} [{default}]: ")
        if not val:
            return default
        try:
            return float(val.replace(",", "."))
        except ValueError:
            print("  (enter a number, e.g. 0.45)")


def _ask_countries() -> list:
    """Remote country selection: shows all with full names. ENTER = all.

    Accepts numbers (1,3,5), codes (it,de) or partial names, comma-separated.
    """
    codes = list(config.REMOTE_COUNTRIES)
    print("  Countries for remote offers (ENTER = all):")
    for i, c in enumerate(codes, 1):
        print(f"    {i}. {config.country_name(c)} ({c})")
    raw = _input("  Choose (e.g. 1,3 or it,de) [all]: ")
    if not raw:
        return codes
    chosen = []
    for tok in raw.replace(";", ",").split(","):
        t = tok.strip().lower()
        if not t:
            continue
        if t.isdigit() and 1 <= int(t) <= len(codes):
            code = codes[int(t) - 1]
        elif t in codes:
            code = t
        else:
            code = next((c for c in codes
                         if t in config.country_name(c).lower()), None)
        if code and code not in chosen:
            chosen.append(code)
    if not chosen:
        print("  (no valid country recognized: using all)")
        return codes
    return chosen


def _ask_factors() -> dict:
    """Advanced mode: pick which scoring factors to use + their relative weights.

    Weights are relative (any numbers) and auto-normalized to sum 1.0. Returns a
    {factor_key: normalized_weight} dict. ENTER on the factor prompt = the core
    defaults.
    """
    keys = list(config.FACTORS)
    print("  Scoring factors (ENTER = the 4 core defaults):")
    for i, k in enumerate(keys, 1):
        core = " [core]" if k in config.DEFAULT_FACTORS else ""
        print(f"    {i}. {config.factor_label(k)} ({k}){core}")
    print(f"  Tip: 4-6 active factors work best "
          f"(max {config.MAX_RECOMMENDED_FACTORS} recommended).")
    raw = _input("  Choose factors (e.g. 1,4,skill_fit) [core]: ")
    if not raw:
        chosen = list(config.DEFAULT_FACTORS)
    else:
        chosen = []
        for tok in raw.replace(";", ",").split(","):
            t = tok.strip().lower()
            if not t:
                continue
            if t.isdigit() and 1 <= int(t) <= len(keys):
                k = keys[int(t) - 1]
            elif t in config.FACTORS:
                k = t
            else:
                k = config.FACTOR_ALIASES.get(t)
            if k and k not in chosen:
                chosen.append(k)
        if not chosen:
            print("  (no valid factor recognized: using core)")
            chosen = list(config.DEFAULT_FACTORS)

    print("  Relative weights (any numbers, auto-normalized to 100%):")
    weights = {k: _ask_float(f"  weight {config.factor_label(k)}",
                             config.FACTORS[k]["weight"] or 1.0) for k in chosen}
    total = sum(weights.values()) or 1.0
    return {k: round(v / total, 4) for k, v in weights.items()}


# --------------------------------------------------------------------------- #
# Backend check
# --------------------------------------------------------------------------- #
def _check_backend() -> None:
    """Checks that the configured LLM backend is usable (fail-fast)."""
    if config.SCORER_BACKEND == "claude_cli":
        if shutil.which("claude") is None:
            print("CLI 'claude' not found in PATH but SCORER_BACKEND="
                  "'claude_cli'.", file=sys.stderr)
            print("Install/log in to Claude Code, or switch to "
                  "SCORER_BACKEND='anthropic_api' in config.py.", file=sys.stderr)
            sys.exit(1)
    elif config.SCORER_BACKEND == "anthropic_api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("SCORER_BACKEND='anthropic_api' but ANTHROPIC_API_KEY missing "
                  "in .env.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"unknown SCORER_BACKEND: {config.SCORER_BACKEND}",
              file=sys.stderr)
        sys.exit(1)


# --------------------------------------------------------------------------- #
# CV: PDF popup -> pypdf, with paste-text fallback
# --------------------------------------------------------------------------- #
def _pick_pdf() -> str:
    """Opens a file picker to choose the CV PDF. None if unavailable."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select the CV (PDF)",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
        )
        root.destroy()
        return path or None
    except Exception:
        return None


def _extract_pdf_text(path: str) -> str:
    """Extracts text from a text-based PDF with pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _paste_text() -> str:
    """Fallback: paste the CV/description in the terminal, end with 'END'."""
    print("Paste your CV or a description of yourself.")
    print("When done, type a line with only END and press ENTER.")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def _read_cv_file(path: str) -> str:
    """Reads the CV text from an explicit path (PDF via pypdf, otherwise TXT)."""
    if path.lower().endswith(".pdf"):
        return _extract_pdf_text(path)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _get_cv_text(cv_path: str = None) -> str:
    """Obtains the CV text.

    With an explicit `cv_path` (--cv flag) it skips the popup; on error or empty
    text it falls back to manual paste. Without a path: PDF popup -> pypdf ->
    paste fallback.
    """
    if cv_path:
        print(f"[init] CV from --cv: {cv_path}", file=sys.stderr)
        try:
            text = _read_cv_file(cv_path)
        except Exception as exc:
            print(f"[init] failed to read CV: {exc}", file=sys.stderr)
            text = ""
        if text.strip():
            return text
        print("[init] no text from the given CV. Falling back to manual paste.",
              file=sys.stderr)
        return _paste_text()

    path = _pick_pdf()
    if path:
        print(f"[init] CV selected: {path}", file=sys.stderr)
        try:
            text = _extract_pdf_text(path)
        except ImportError:
            print("pypdf not installed. Run: pip install pypdf",
                  file=sys.stderr)
            text = ""
        except Exception as exc:
            print(f"[init] PDF extraction failed: {exc}", file=sys.stderr)
            text = ""
        if text.strip():
            return text
        print("[init] no extractable text in the PDF (maybe a scan). "
              "Falling back to manual paste.", file=sys.stderr)
    else:
        print("[init] file picker unavailable or cancelled.", file=sys.stderr)
    return _paste_text()


# --------------------------------------------------------------------------- #
# Profile extraction via LLM
# --------------------------------------------------------------------------- #
def _extract_profile(cv_text: str, language: str) -> dict:
    """Extracts from the CV: name, city, country, profile, seniority and keywords.

    profile_text does NOT include the location/preferences section: it is added
    later deterministically (it depends on the wizard answers).
    """
    system = (
        "You are an assistant that extracts a structured professional profile "
        "from a CV. ALWAYS reply ONLY with a valid JSON object, with no text "
        "before or after, no markdown."
    )
    user_prompt = f"""\
From the CV below extract the data for a job-offer scoring system.
Return ONLY this JSON object (no extra fields):
{{
  "name": "<full name from the CV, '' if absent>",
  "city": "<city of residence from the CV, '' if not inferable>",
  "country": "<2-letter Adzuna country code of residence (e.g. it, de, gb, fr), '' if unsure>",
  "profile_text": "<prose description of the candidate in {language}: current role, experience, skills and stack, education, languages, seniority. Do NOT include location or remote-work preferences: they are added separately.>",
  "seniority": "<junior | mid | senior, with estimated years>",
  "keywords": ["<5 to 8 NARROW domain keywords, in English, for the Adzuna query>"],
  "remote_extra_keywords": ["<3 to 5 broader keywords, in English>"]
}}

CV:
\"\"\"
{cv_text}
\"\"\"
"""
    data = llm.complete_json(user_prompt, system=system, prefill="{")
    if not isinstance(data, dict):
        raise ValueError("the model did not return a JSON object")

    profile_text = (data.get("profile_text") or "").strip()
    keywords = [str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()]
    extra = [str(k).strip() for k in (data.get("remote_extra_keywords") or [])
             if str(k).strip()]
    if not profile_text or not keywords:
        raise ValueError("incomplete extraction (empty profile_text or keywords)")
    return {
        "name": (data.get("name") or "").strip(),
        "city": (data.get("city") or "").strip(),
        "country": (data.get("country") or "").strip().lower(),
        "profile_text": profile_text,
        "seniority": (data.get("seniority") or "").strip(),
        "keywords": keywords,
        "remote_extra_keywords": extra,
    }


# --------------------------------------------------------------------------- #
# Fallback for keywords that are too broad
# --------------------------------------------------------------------------- #
def _filter_broad(keywords: list) -> tuple:
    """Splits usable keywords from those too generic (case-insensitive).

    The stoplist is config.GENERIC_KEYWORDS (tunable). The `remote_extra_keywords`
    are NOT filtered: they are the broad bucket by design.
    """
    generic = {t.lower() for t in config.GENERIC_KEYWORDS}
    kept, dropped = [], []
    for k in keywords:
        (dropped if k.strip().lower() in generic else kept).append(k)
    return kept, dropped


# --------------------------------------------------------------------------- #
# TOML rendering
# --------------------------------------------------------------------------- #
def _toml_str(s: str) -> str:
    """TOML basic string: json.dumps produces compatible escaping."""
    return json.dumps(s, ensure_ascii=False)


def _toml_array(items: list) -> str:
    return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in items) + "]"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "profile"


def _render_toml(*, name, language, city, country, distance, remote,
                 remote_countries, keywords, remote_extra_keywords,
                 profile_text, weights, top_n=None) -> str:
    # profile_text in a triple-quote block: neutralize backslash and delimiter.
    safe = profile_text.replace("\\", "\\\\").replace('"""', "'''")

    out = [
        "# Profile generated by: python main.py --init",
        "# Editable by hand. scoring_rubric uses the config.py default",
        "# (DEFAULT_RUBRIC). Weights use DEFAULT_WEIGHTS if [weights] is absent.",
        "",
        f'profile_text = """\n{safe}\n"""',
        "",
        f"keywords = {_toml_array(keywords)}",
    ]
    if remote:
        if remote_extra_keywords:
            out.append(f"remote_extra_keywords = {_toml_array(remote_extra_keywords)}")
        out.append('remote_query_what = "remote"')

    out += ["", "[meta]", f"name = {_toml_str(name)}",
            f"report_language = {_toml_str(language)}"]
    if top_n is not None:
        out.append(f"report_top_n = {int(top_n)}")

    if weights is not None:
        out += ["", "[weights]"]
        out += [f"{k} = {weights[k]}" for k in weights]

    out += ["", "# --- Adzuna sources ---", "[[sources]]",
            'name = "near_home"', f"country = {_toml_str(country)}",
            f"where = {_toml_str(city)}", f"distance = {distance}",
            "remote_filter = false"]

    for c in remote_countries:
        out += ["", "[[sources]]", f'name = "remote_{c}"',
                f"country = {_toml_str(c)}", "remote_filter = true",
                "extra_keywords = true"]

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_init(launch_after: bool = True, cv_path: str = None,
             out_path: str = None) -> str:
    """Creates a guided profile. Returns the written path, or None if cancelled.

    out_path: if given, always writes there (fixed path) instead of deriving it
    from the name.
    """
    print("=== JobScouting — guided profile creation ===\n")
    load_dotenv()
    _check_backend()

    # 1) CV -> text (first of all: the CV drives the extraction).
    print("To begin we need your CV: role, skills and keywords are extracted "
          "from it.")
    cv_text = _get_cv_text(cv_path)
    if not cv_text.strip():
        print("No CV text provided. Aborting.", file=sys.stderr)
        sys.exit(1)

    # 2) Extraction from the CV (the report language is used for profile_text).
    language = _ask("Report language", "english")
    print("[init] extracting the profile from the CV with the model...",
          file=sys.stderr)
    try:
        extracted = _extract_profile(cv_text, language)
    except Exception as exc:
        print(f"[init] extraction failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        sys.exit(1)

    # 3) Fill only the info the CV did not provide.
    name = extracted["name"]
    if name:
        print(f"[init] name from CV: {name}", file=sys.stderr)
    else:
        name = _ask_required("Full name (not found in the CV)")
    # City: confirm with the extracted default (the CV may show the work location
    # instead of residence, and it drives the local search -> better to confirm).
    city = _ask("City of residence", extracted["city"] or None)
    if not city:
        city = _ask_required("City of residence")
    country = extracted["country"] or "it"
    distance = _ask_int("Local search radius (km)", 50)
    top_n = _ask_int("How many offers to show in the report", config.DEFAULT_TOP_N)
    remote = _ask_yesno("Also search for full remote work?", True)
    remote_countries = []
    if remote:
        remote_countries = _ask_countries()
    weights = None
    if _ask_yesno("Customize the scoring factors and weights? (advanced)", False):
        weights = _ask_factors()

    # 4) Location/remote preferences: added to the profile deterministically.
    remote_desc = ("also looking for full remote work (EU)" if remote
                   else "prefers on-site or hybrid near home")
    profile_text = (extracted["profile_text"].rstrip()
                    + f"\n\nLocation and preferences: lives in {city}; {remote_desc}.")

    # 5) Fallback for keywords that are too broad + confirm/edit.
    keywords, dropped = _filter_broad(extracted["keywords"])
    if dropped:
        print(f"[init] keywords too generic, dropped: {', '.join(dropped)}",
              file=sys.stderr)
    if not keywords:
        # all generic: do not end up with no query, keep the originals.
        keywords = extracted["keywords"]
        print("[init] all keywords were generic: keeping the original list. "
              "Narrow them by hand below.", file=sys.stderr)

    print("\n--- Extracted profile " + "-" * 30)
    print(profile_text)
    if extracted["seniority"]:
        print(f"\nSeniority: {extracted['seniority']}")
    print(f"\nKeywords: {', '.join(keywords)}")
    print("-" * 50)
    new_kw = _ask("ENTER to accept the keywords, or paste new ones "
                  "(comma-separated)", "")
    if new_kw.strip():
        keywords = [k.strip() for k in new_kw.split(",") if k.strip()]

    # 6) Render + write. Remote sources: only the selected countries.
    toml_str = _render_toml(
        name=name, language=language, city=city, country=country,
        distance=distance, remote=remote, remote_countries=remote_countries,
        keywords=keywords, remote_extra_keywords=extracted["remote_extra_keywords"],
        profile_text=profile_text, weights=weights, top_n=top_n,
    )
    path = out_path or os.path.join(config.PROFILES_DIR, f"{_slugify(name)}.toml")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path) and not _ask_yesno(
            f"{path} already exists. Overwrite?", False):
        print("Cancelled (profile not written).")
        return None
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(toml_str)
    print(f"\n[init] profile saved to {path}")

    # 7) Validation: it must load.
    try:
        profile = profile_loader.load_profile(path)
    except profile_loader.ProfileError as exc:
        print(f"[init] WARNING: the generated profile is invalid: {exc}",
              file=sys.stderr)
        print("Open the file and fix it by hand.", file=sys.stderr)
        return None

    # 8) Optionally launch scoring.
    if launch_after and _ask_yesno("\nLaunch scoring now?", True):
        import main  # lazy: avoids circular import
        main._check_keys()
        main.run_pipeline(profile, path)
    elif launch_after:
        print(f"To run later: python main.py --profile {path}")
    return path
