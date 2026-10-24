"""S&C planning prompts grounded in recorded games, with no athlete-state model.

The public demo can organize a hypothetical staff conversation. It cannot infer
fatigue, prescribe training, or verify the user's answers to that conversation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


PRACTICE_LABEL = (
    "S&C PRACTICE WORKSHEET — hypothetical planning; "
    "not an actual team or athlete assessment"
)
LIMITATION = (
    "Public game records do not include warm-ups, bullpen sessions, other throwing, "
    "strength or conditioning work, athlete feedback, planned use, or relevant "
    "staff restrictions. Days without an MLB appearance do not establish rest. "
    "These prompts do not determine training readiness or prescribe a session."
)
DECISIONS = ("Awaiting context", "Keep planned session", "Adjust planned session", "Discuss with staff first")


def _known(value: Any) -> bool:
    return value is not None and not pd.isna(value)


def _count(value: Any) -> str:
    return f"{value:,.0f}" if _known(value) else "unknown"


def _text(value: Any) -> str:
    return str(value).strip() if _known(value) else ""


def _questions(fields: Mapping[str, Any]) -> list[str]:
    values = fields.get("open_questions", []) or []
    if isinstance(values, str):
        values = [values]
    return [text for value in values if (text := _text(value))]


def review_context(row: Mapping[str, Any], as_of: Any) -> dict[str, Any]:
    """Describe the engine's values and choose at most three review questions.

    Missing coverage and missing counts remain unknown. A small game total
    never becomes a recommendation to add work, and a large one never becomes
    a recommendation to remove it. The engine owns every numeric calculation.
    """
    cutoff = pd.Timestamp(as_of)
    if pd.isna(cutoff):
        raise ValueError("A valid review date is required.")
    first = cutoff - pd.Timedelta(days=6)
    three_day_first = cutoff - pd.Timedelta(days=2)
    coverage = row.get("coverage_7d")
    complete = _known(coverage) and bool(coverage)
    pitches = row.get("pitches_7d") if complete else None
    coverage_3d = row.get("coverage_3d")
    complete_3d = _known(coverage_3d) and bool(coverage_3d)
    pitches_3d = row.get("pitches_3d") if complete_3d else None

    window = (
        f"{first:%b %d, %Y}–{cutoff:%b %d, %Y}, inclusive: "
        f"{_count(pitches)} recorded MLB game pitches across "
        f"{_count(row.get('appearances_7d'))} observed appearances "
        f"({_count(row.get('starts_7d'))} starts; "
        f"{_count(row.get('relief_7d'))} relief). "
        f"{three_day_first:%b %d}–{cutoff:%b %d}, inclusive: "
        f"{_count(pitches_3d)} game pitches."
    )
    if not complete:
        window += " Seven-day source coverage is incomplete or unknown; appearance counts are observed only."
    elif not _known(pitches):
        window += " At least one game pitch count is missing; the total is unknown."

    last_date = row.get("last_date")
    last_date_text = (
        f"{pd.Timestamp(last_date):%b %d, %Y}" if _known(last_date) else "unknown date"
    )
    latest = (
        f"Latest included appearance: {last_date_text}, "
        f"{_text(row.get('role')).lower() or 'unknown role'}, "
        f"{_count(row.get('last_pitches'))} game pitches. "
        f"Days since that appearance: {_count(row.get('days_since'))}."
    )
    consecutive = row.get("consecutive_days")
    if not _known(consecutive):
        latest += " Consecutive appearance dates: unknown."
    elif consecutive >= 2:
        latest += f" Appeared on {_count(consecutive)} consecutive dates ending on that latest date."

    median, known_counts = row.get("baseline_median"), row.get("baseline_n")
    if _known(median) and _known(known_counts) and known_counts >= 3:
        comparison = (
            f"Previous {_count(row.get('baseline_appearances'))} same-role appearances: "
            f"median {median:g} pitches from {_count(known_counts)} known counts. "
            "This describes outing length, not athlete response."
        )
    else:
        comparison = (
            "Same-role outing comparison is unavailable: "
            f"{_count(known_counts)} known prior pitch counts. "
            "At least three known counts and complete dates are required."
        )

    prompts: list[str] = []
    if not complete or not _known(pitches):
        prompts.append(
            "Which dates or pitch counts are missing? Resolve the source gaps before "
            "using this week for a workload comparison."
        )

    appearances = row.get("appearances_7d")
    sparse = complete and _known(appearances) and (
        appearances == 0 or (_text(row.get("role")) == "Relief" and appearances <= 1)
    )
    if sparse:
        prompts.append(
            "Few or no game appearances do not establish low total work. Check other "
            "throwing, recent training, and athlete feedback before discussing "
            "opportunities to maintain strength, power, or conditioning."
        )

    starts, relief = row.get("starts_7d"), row.get("relief_7d")
    mixed = (
        _known(starts) and _known(relief) and starts > 0 and relief > 0
    ) or "Both start and relief appearances" in _text(row.get("notes"))
    if mixed:
        role_window = "this seven-day window" if (
            _known(starts) and _known(relief) and starts > 0 and relief > 0
        ) else "the last 28 days"
        prompts.append(
            f"With both start and relief appearances recorded in {role_window}, what role and throwing "
            "plan does the pitching staff expect next, and how does the strength or "
            "power session fit that plan?"
        )
    elif _text(row.get("role")) == "Start":
        prompts.append(
            "Confirm the next throwing session and expected outing with the pitching "
            "staff. How does the planned strength or power session fit that schedule?"
        )
    elif sparse:
        prompts.append(
            "Confirm the player's intended role and any planned pitching use with "
            "staff. How does the planned training session fit that context?"
        )
    else:
        days_since = row.get("days_since")
        recent_sequence = (
            not sparse and _known(consecutive) and consecutive >= 2
            and _known(days_since) and days_since <= 2
        )
        sequence = (
            f"Around the consecutive appearances ending {last_date_text}, confirm"
            if recent_sequence else "Confirm"
        )
        prompts.append(
            f"{sequence} warm-ups, other throwing, and expected bullpen use with "
            "the pitching staff before discussing the planned training session."
        )

    if not sparse:
        prompts.append(
            "What other throwing, recent strength or conditioning work, athlete "
            "feedback, and staff restrictions are still unknown? Confirm that "
            "context before discussing whether the planned session needs to change."
        )
    return {"facts": [window, latest, comparison], "prompts": prompts[:3], "limitation": LIMITATION}


def worksheet_status(fields: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Assess note completeness, never the athlete or the training decision.

    An awaiting-context action plan remains awaiting context even if its owner
    and follow-up are documented. Prepared notes retain unresolved questions;
    preparation never represents verification of that context.
    """
    missing = [
        label for key, label in (
            ("focus", "Training focus"),
            ("rationale", "Reasoning / next action"),
            ("owner", "Follow-up owner"),
            ("follow_up", "Follow-up timing and check"),
        ) if not _text(fields.get(key))
    ]
    decision = _text(fields.get("decision")) or DECISIONS[0]
    if decision not in DECISIONS:
        missing.append("Recognized planning decision")
        return "Draft — follow-up incomplete", missing
    if decision == DECISIONS[0]:
        return "Awaiting context", missing
    if missing:
        return "Draft — follow-up incomplete", missing
    if _questions(fields):
        return "Review note prepared — open questions remain", []
    return "Review note prepared", []


def review_note(row: Mapping[str, Any], as_of: Any, fields: Mapping[str, Any]) -> str:
    """Export a draft at any stage, separating source facts from user reasoning."""
    context = review_context(row, as_of)
    status, missing = worksheet_status(fields)
    name = _text(row.get("player_name")) or _text(row.get("name")) or "Unknown player"
    team = _text(row.get("team")) or "Unknown team"
    lines = [
        PRACTICE_LABEL,
        f"Public-record reference: {name} | {team} | through {pd.Timestamp(as_of):%b %d, %Y} (end of day)",
        f"Worksheet status: {status}",
        "This status describes documentation only; it does not validate the training decision.",
        "", "RECORDED MLB GAME FACTS", *[f"- {fact}" for fact in context["facts"]],
    ]
    notes = _text(row.get("notes"))
    if notes:
        lines.append(f"Source notes: {notes}")
    lines.extend(["", "QUESTIONS FOR A STAFF CONVERSATION", *[f"- {prompt}" for prompt in context["prompts"]]])
    lines.extend([
        "", "USER-ENTERED PRACTICE REASONING",
        "The entries below are hypothetical planning notes, not verified information about this player.",
    ])
    for key, label in (
        ("focus", "Training focus"), ("decision", "Planning decision"),
        ("rationale", "Reasoning / next action"), ("owner", "Follow-up owner"),
        ("follow_up", "Follow-up timing and check"),
    ):
        value = _text(fields.get(key)) or (DECISIONS[0] if key == "decision" else "Not entered")
        lines.append(f"{label}:\n  " + value.replace("\n", "\n  "))
    questions = _questions(fields)
    lines.append("Unresolved context questions:")
    lines.extend([f"- {question}" for question in questions] or ["- None marked by the user; this does not verify that context was obtained."])
    lines.extend([
        "", "DOCUMENTATION STILL OPEN",
        *([f"- {item}" for item in missing] or ["- No required worksheet fields remain blank."]),
        "", "SCOPE", context["limitation"],
    ])
    return "\n".join(lines) + "\n"
