"""Builds the Markdown report with the top-N of the scored offers."""

from datetime import datetime

import config


def _pct(key: str, weights: dict) -> str:
    """Factor weight as an integer percentage, from the profile."""
    return f"{round(weights[key] * 100)}%"


def _format_salary(offer: dict) -> str:
    """Readable salary if present, otherwise 'n/a'."""
    lo, hi = offer.get("salary_min"), offer.get("salary_max")
    if not lo and not hi:
        return "n/a"
    if lo and hi:
        return f"{int(lo):,} - {int(hi):,}"
    val = lo or hi
    return f"{int(val):,}"


def _format_list(items: list, empty: str) -> str:
    if items:
        return "\n".join(f"  - {x}" for x in items)
    return f"  - {empty}"


def _format_breakdown(sub: dict, weights: dict) -> str:
    """Per-factor breakdown line, driven by the profile's active factors."""
    return " · ".join(
        f"{config.factor_label(k)} {sub.get(k, 0)} ({_pct(k, weights)})"
        for k in weights)


def _format_offer(rank: int, offer: dict, weights: dict) -> str:
    sub = offer.get("sub_scores", {})
    badge = "🆕 " if offer.get("is_new") else ""

    return (
        f"## {rank}. {badge}{offer['title']} — {offer['company'] or 'Company n/a'}\n\n"
        f"- **Total score:** {offer['total']}/100\n"
        f"- **Location:** {offer['location'] or 'n/a'} "
        f"(country: {offer['country']}, source: {offer['source']})\n"
        f"- **Salary:** {_format_salary(offer)}\n"
        f"- **Breakdown:** {_format_breakdown(sub, weights)}\n"
        f"- **Reasoning:** {offer.get('motivation', '')}\n"
        f"- **Red flags:**\n{_format_list(offer.get('red_flags', []), 'none')}\n"
        f"- **To close the gap:**\n{_format_list(offer.get('gap', []), 'no relevant gap')}\n"
        f"- **Link:** {offer['url']}\n"
    )


def build_report(scored: list[dict], total_fetched: int, profile,
                 total_attempted: int | None = None,
                 new_count: int | None = None) -> str:
    """Builds the full Markdown report.

    `scored` = scored offers (with a 'total' field). `total_fetched` = fetched
    from Adzuna. `total_attempted` = sent to the model (after the cap); if it
    differs from len(scored) some batches failed. `new_count` = offers never
    seen before.
    """
    weights = profile.WEIGHTS
    top_n = getattr(profile, "TOP_N", config.DEFAULT_TOP_N)
    ranked = sorted(scored, key=lambda o: o["total"], reverse=True)[:top_n]
    run_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    skipped = 0
    if total_attempted is not None:
        skipped = total_attempted - len(scored)

    lines = [
        f"# Job offers report — JobScouting ({profile.name})",
        "",
        f"- **Run date:** {run_date}",
        f"- **Offers fetched from Adzuna:** {total_fetched}",
    ]
    if new_count is not None:
        lines.append(f"- **Of which never seen before 🆕:** {new_count}")
    lines.append(f"- **Offers scored by the model:** {len(scored)}")
    if total_attempted is not None:
        lines.append(f"- **Offers attempted (after cap):** {total_attempted}")
    if skipped > 0:
        lines.append(
            f"- **⚠️ Skipped due to scoring error:** {skipped} "
            f"(failed batches — rerun or check the logs)")
    lines += [
        f"- **Shown (top):** {len(ranked)}",
        "",
        "---",
        "",
    ]
    if not ranked:
        lines.append("_No offers scored in this run._")
    else:
        for i, offer in enumerate(ranked, start=1):
            lines.append(_format_offer(i, offer, weights))
    return "\n".join(lines)
