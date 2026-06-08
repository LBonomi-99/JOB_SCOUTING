"""Scoring of offers with an LLM (Claude), in batches.

Two backends selectable in config.SCORER_BACKEND:
- "claude_cli"    -> headless `claude` CLI (subscription, free, no API key).
- "anthropic_api" -> token-billed Anthropic SDK (needs ANTHROPIC_API_KEY).

For each offer the model returns the 4 sub-scores + reasoning + red flags + gap
(what is missing to be competitive). The total score (0-100) is computed by
Python with the profile weights, deterministically and explainably.

Profile and rubric come from the profile_loader.Profile passed to the functions.
"""

import sys

import config
import llm


def _build_system_prompt(profile) -> str:
    """Builds the system prompt (profile + rubric + JSON schema)."""
    return f"""\
You are an assistant that evaluates job offers for a specific candidate.
ALWAYS reply ONLY with a valid JSON array, with no text before or after, no
markdown. All strings (motivation, red flags, gap) must be in
{profile.report_language}.

{profile.PROFILE_TEXT}

{profile.SCORING_RUBRIC}

For each offer you are given, produce a JSON object with these fields:
{{
  "id": "<offer id, identical to the one received>",
  "sub_scores": {{
    "tech": <integer 0-100>,
    "salary_seniority": <integer 0-100>,
    "company": <integer 0-100>,
    "location": <integer 0-100>
  }},
  "motivation": "<one sentence explaining the judgment>",
  "red_flags": ["<reason NOT to apply>", "..."],
  "gap": ["<what is missing or should be strengthened in the profile to be competitive for this role>", "..."]
}}
Return an array with one object per offer received, in the same order. No extra
fields.
"""


def _format_offers(offers: list[dict]) -> str:
    """Serializes the batch offers for the user message."""
    blocks = []
    for o in offers:
        salary = ""
        if o.get("salary_min") or o.get("salary_max"):
            salary = f"\nSalary: {o.get('salary_min')} - {o.get('salary_max')}"
        blocks.append(
            f"--- OFFER id={o['id']} ---\n"
            f"Title: {o['title']}\n"
            f"Company: {o['company']}\n"
            f"Location: {o['location']}\n"
            f"Country: {o['country']} | Source: {o['source']}{salary}\n"
            f"Description: {o['description']}"
        )
    return "\n\n".join(blocks)


def _call_model(offers: list[dict], profile) -> list[dict]:
    """Scores a batch via llm. Strong directive in the user prompt (applies to
    both backends); the '[' prefill is used only by the API backend."""
    user_prompt = (
        "You are an automated job-offer evaluator. Reply EXCLUSIVELY with a "
        "valid JSON array. Do NOT ask questions. Do NOT add text, explanations "
        "or markdown before or after the array.\n\n"
        "=== OFFERS TO EVALUATE ===\n\n"
        + _format_offers(offers)
        + "\n\nReply now ONLY with the JSON array."
    )
    data = llm.complete_json(
        user_prompt,
        system=_build_system_prompt(profile),
        prefill="[",
    )
    if not isinstance(data, list):
        raise ValueError("Model response is not a valid JSON array")
    return data


def score_batch(offers: list[dict], profile) -> list[dict]:
    """Scores a batch of offers. 1 retry on failure.

    On a double failure returns [] and the batch is skipped (warning to stderr).
    """
    for attempt in (1, 2):
        try:
            return _call_model(offers, profile)
        except Exception as exc:  # no batch should crash the run
            print(f"[scorer] batch failed (attempt {attempt}): "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"[scorer] batch skipped: {len(offers)} offers not scored",
          file=sys.stderr)
    return []


def weighted_total(sub_scores: dict, weights: dict) -> float:
    """Weighted sum of the 4 sub-scores with the profile weights."""
    return round(
        sum(weights[k] * float(sub_scores.get(k, 0)) for k in weights),
        1,
    )


def score_all(offers: list[dict], profile) -> list[dict]:
    """Scores all offers in batches and enriches them with the total score.

    Returns only the offers actually scored (realigned by id), each with:
    total, sub_scores, motivation, red_flags, gap.
    """
    by_id = {o["id"]: o for o in offers}
    scored: list[dict] = []

    for start in range(0, len(offers), config.BATCH_SIZE):
        batch = offers[start:start + config.BATCH_SIZE]
        results = score_batch(batch, profile)
        for r in results:
            oid = str(r.get("id", ""))
            offer = by_id.get(oid)
            if offer is None:
                continue  # unrecognized / hallucinated id: discard
            sub = r.get("sub_scores", {})
            enriched = dict(offer)
            enriched["sub_scores"] = sub
            enriched["total"] = weighted_total(sub, profile.WEIGHTS)
            enriched["motivation"] = r.get("motivation", "")
            enriched["red_flags"] = r.get("red_flags", []) or []
            enriched["gap"] = r.get("gap", []) or []
            scored.append(enriched)
        done = min(start + config.BATCH_SIZE, len(offers))
        print(f"[scorer] scored {len(scored)}/{done} offers",
              file=sys.stderr)

    return scored
