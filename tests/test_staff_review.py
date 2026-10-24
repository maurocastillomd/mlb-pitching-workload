"""Adversarial checks on public-game facts and hypothetical staff decisions."""

from copy import deepcopy

import pandas as pd
import pytest

from baseball_workload.staff_review import (
    PRACTICE_LABEL, review_context, review_note, worksheet_status,
)


@pytest.fixture
def row():
    return dict(
        player_name="Public Pitcher", team="Example Team", role="Relief",
        pitches_3d=26, pitches_7d=54, appearances_7d=3, starts_7d=0,
        relief_7d=3, last_date=pd.Timestamp("2025-09-28"), last_pitches=26,
        days_since=0, consecutive_days=2, baseline_n=5,
        baseline_appearances=5, baseline_median=14., coverage_7d=True,
        coverage_3d=True, notes="",
    )


@pytest.fixture
def fields():
    return dict(
        focus="Strength session timing", open_questions=[],
        decision="Keep planned session", rationale="Discuss the schedule with staff.",
        owner="S&C coach", follow_up="Before today's lift: confirm next throwing session.",
    )


def test_facts_use_inclusive_dates_same_role_and_known_counts(row):
    context = review_context(row, "2025-09-28")
    facts = " ".join(context["facts"])
    assert "Sep 22, 2025–Sep 28, 2025, inclusive" in facts
    assert "54 recorded MLB game pitches" in facts
    assert "0 starts; 3 relief" in facts
    assert "Sep 26–Sep 28, inclusive: 26 game pitches" in facts
    assert "2 consecutive dates ending on that latest date" in facts
    assert "median 14 pitches from 5 known counts" in facts
    assert len(context["facts"]) == 3
    assert len(context["prompts"]) <= 3


def test_zero_game_exposure_is_not_a_training_prescription(row):
    row.update(pitches_7d=0, pitches_3d=0, appearances_7d=0, relief_7d=0,
               last_date=pd.Timestamp("2025-09-15"), days_since=13, consecutive_days=1)
    context = review_context(row, "2025-09-28")
    text = " ".join(context["prompts"])
    assert "do not establish low total work" in text
    assert "other throwing, recent training, and athlete feedback" in text
    assert "opportunities to maintain strength, power, or conditioning" in text
    assert "add work" not in text
    assert "recovered" not in text
    assert "rested" not in text


def test_missing_coverage_overrides_zero_and_does_not_call_it_a_quiet_week(row):
    row.update(coverage_7d=False, coverage_3d=False, pitches_7d=0,
               pitches_3d=0, appearances_7d=0, relief_7d=0,
               days_since=float("nan"), consecutive_days=float("nan"))
    context = review_context(row, "2025-09-28")
    facts = " ".join(context["facts"])
    assert "unknown recorded MLB game pitches" in facts
    assert "inclusive: unknown game pitches" in facts
    assert "Days since that appearance: unknown" in facts
    assert "Consecutive appearance dates: unknown" in facts
    assert "missing" in context["prompts"][0]
    assert "Few or no" not in " ".join(context["prompts"])


def test_missing_count_remains_unknown_when_dates_are_complete(row):
    row["pitches_7d"] = float("nan")
    context = review_context(row, "2025-09-28")
    assert "total is unknown" in context["facts"][0]
    assert "Resolve the source gaps" in context["prompts"][0]


def test_one_baseline_count_cannot_produce_a_median_comparison(row):
    row.update(baseline_n=1, baseline_appearances=1, baseline_median=90)
    facts = " ".join(review_context(row, "2025-09-28")["facts"])
    assert "comparison is unavailable: 1 known prior pitch counts" in facts
    assert "median 90" not in facts


@pytest.mark.parametrize("missing", [None, float("nan"), pd.NA])
def test_missing_scalars_are_unknown_without_boolean_errors(row, missing):
    row.update(coverage_7d=missing, coverage_3d=missing, consecutive_days=missing,
               baseline_n=missing, baseline_median=missing, last_date=missing)
    context = review_context(pd.Series(row), "2025-09-28")
    assert "unknown date" in context["facts"][1]
    assert "unknown recorded MLB game pitches" in context["facts"][0]


def test_starter_prompt_connects_pitching_plan_and_physical_preparation(row):
    row.update(role="Start", starts_7d=1, relief_7d=0, appearances_7d=1)
    prompts = " ".join(review_context(row, "2025-09-28")["prompts"])
    assert "next throwing session and expected outing" in prompts
    assert "strength or power session" in prompts


@pytest.mark.parametrize("mixed", [dict(starts_7d=1, relief_7d=1),
    dict(notes="Both start and relief appearances in the last 28 days; role shown is latest included outing.")])
def test_mixed_role_requires_clarification_instead_of_assuming_a_rotation(row, mixed):
    row.update(mixed)
    prompts = " ".join(review_context(row, "2025-09-28")["prompts"])
    assert "what role and throwing plan" in prompts


def test_consecutive_relief_prompts_other_throwing_and_planned_use(row):
    prompts = " ".join(review_context(row, "2025-09-28")["prompts"])
    assert "Around the consecutive appearances" in prompts
    assert "ending Sep 28, 2025" in prompts
    assert "warm-ups, other throwing, and expected bullpen use" in prompts
    for prescription in ("reduce training", "skip lifting", "high risk", "fatigued"):
        assert prescription not in prompts


def test_empty_or_whitespace_note_is_never_prepared():
    assert worksheet_status({})[0] == "Awaiting context"
    status, missing = worksheet_status(dict(decision="Keep planned session", focus=" ",
        rationale="\n", owner="", follow_up=""))
    assert status == "Draft — follow-up incomplete"
    assert len(missing) == 4


@pytest.mark.parametrize("decision", ["Keep planned session", "Adjust planned session", "Discuss with staff first"])
def test_complete_note_status_describes_documentation(fields, decision):
    fields["decision"] = decision
    assert worksheet_status(fields) == ("Review note prepared", [])


def test_open_questions_remain_visible_without_forcing_every_unknown_resolved(fields):
    fields["open_questions"] = ["Other throwing"]
    status, missing = worksheet_status(fields)
    assert status == "Review note prepared — open questions remain"
    assert missing == []


def test_old_consecutive_dates_do_not_drive_todays_review(row):
    row.update(last_date=pd.Timestamp("2025-09-16"), days_since=12,
               consecutive_days=2, appearances_7d=0, pitches_7d=0, relief_7d=0)
    context = review_context(row, "2025-09-28")
    assert "Few or no game appearances" in context["prompts"][0]
    assert "Around the consecutive" not in " ".join(context["prompts"])
    assert "Sep 16, 2025" in context["facts"][1]


def test_sparse_relief_record_does_not_assume_bullpen_membership(row):
    row.update(appearances_7d=1, relief_7d=1, pitches_7d=3, last_pitches=3)
    prompts = " ".join(review_context(row, "2025-09-28")["prompts"])
    assert "intended role and any planned pitching use" in prompts
    assert "expected bullpen use" not in prompts


def test_awaiting_context_remains_awaiting_even_with_documented_next_action(fields):
    fields["decision"] = "Awaiting context"
    assert worksheet_status(fields)[0] == "Awaiting context"


def test_unrecognized_decision_cannot_prepare_note(fields):
    fields["decision"] = "Cleared"
    status, missing = worksheet_status(fields)
    assert status == "Draft — follow-up incomplete"
    assert "Recognized planning decision" in missing


def test_export_keeps_real_facts_separate_from_user_entered_practice_reasoning(row, fields):
    fields.update(decision="Awaiting context", open_questions=["Other throwing", "Athlete feedback"],
                  rationale="Ask the pitching coach.\n<script>literal text</script>")
    original_row, original_fields = deepcopy(row), deepcopy(fields)
    note = review_note(row, "2025-09-28", fields)
    assert note.startswith(PRACTICE_LABEL)
    assert note.index("RECORDED MLB GAME FACTS") < note.index("USER-ENTERED PRACTICE REASONING")
    assert "not verified information about this player" in note
    assert "\n  <script>literal text</script>" in note
    assert "- Other throwing\n- Athlete feedback" in note
    assert "Unresolved context questions" in note
    assert "do not establish rest" in note
    assert "documentation only" in note
    assert row == original_row and fields == original_fields


def test_blank_draft_is_exportable_and_shows_missing_fields(row):
    note = review_note(row, "2025-09-28", {})
    assert "Worksheet status: Awaiting context" in note
    assert "Training focus:\n  Not entered" in note
    assert "DOCUMENTATION STILL OPEN\n- Training focus" in note
    assert "No required worksheet fields remain blank" not in note


def test_complete_export_still_does_not_verify_context(row, fields):
    note = review_note(row, "2025-09-28", fields)
    assert "Review note prepared" in note
    assert "this does not verify that context was obtained" in note
    assert "does not validate the training decision" in note
