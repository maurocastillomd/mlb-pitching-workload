"""Adversarial cases that can otherwise silently distort pitching summaries."""

import unittest

import pandas as pd

from baseball_workload.engine import (
    daily_pitch_grid, format_outs, player_history, prepare_appearances, team_summary,
)


def outing(day, pitches=20, *, player=1, game=None, team="A", team_id=10,
           start=False, outs=3, game_number=1, uncertain=False, uncertain_dates=""):
    return {
        "player_id": player, "player_name": f"Pitcher {player}",
        "team_id": team_id, "team": team, "game_id": game or int(day.replace("-", "")),
        "game_date": day, "is_start": start, "pitches": pitches, "outs": outs,
        "batters_faced": 4, "game_type": "R", "game_number": game_number,
        "date_uncertain": uncertain, "uncertain_dates": uncertain_dates,
    }


def summary(rows, as_of="2025-06-30", team="A", coverage_start="2025-03-01",
            coverage_end="2025-09-30", incomplete_dates=()):
    return team_summary(pd.DataFrame(rows), as_of, team, coverage_start,
                        coverage_end, incomplete_dates)


class PreparationTests(unittest.TestCase):
    def test_exact_duplicates_removed_and_input_unchanged(self):
        data = pd.DataFrame([outing("2025-06-30")] * 2)
        original = data.copy(deep=True)
        self.assertEqual(len(prepare_appearances(data)), 1)
        pd.testing.assert_frame_equal(data, original)

    def test_conflicting_duplicates_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            prepare_appearances(pd.DataFrame([outing("2025-06-30", 20), outing("2025-06-30", 21)]))

    def test_negative_and_fractional_counts_rejected(self):
        for field, value in [("pitches", -1), ("outs", -1), ("outs", 6.2), ("pitches", 1.5)]:
            row = outing("2025-06-30")
            row[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                prepare_appearances(pd.DataFrame([row]))

    def test_missing_id_and_unrecognized_boolean_rejected(self):
        for field, value in [("player_id", None), ("is_start", "maybe")]:
            row = outing("2025-06-30")
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare_appearances(pd.DataFrame([row]))

    def test_zero_pitches_zero_outs_retained(self):
        result = summary([outing("2025-06-30", pitches=0, outs=0)]).iloc[0]
        self.assertEqual(result.appearances_3d, 1)
        self.assertEqual(result.last_outs, 0)
        self.assertEqual(result.pitches_3d, 0)

    def test_innings_format_uses_outs_not_decimal_arithmetic(self):
        self.assertEqual(format_outs(20), "6.2")
        self.assertEqual(format_outs(0), "0.0")
        self.assertEqual(format_outs(None), "—")
        with self.assertRaises(ValueError):
            format_outs(6.2)

    def test_empty_frame_has_consistent_schema(self):
        data = prepare_appearances(pd.DataFrame())
        self.assertTrue(data.empty)
        self.assertIn("pitches", data)
        self.assertTrue(team_summary(data, "2025-06-30", "A", "2025-03-01", "2025-09-30").empty)


class WindowTests(unittest.TestCase):
    def test_inclusive_windows_and_previous_week_do_not_overlap(self):
        rows = [outing("2025-06-16", 100), outing("2025-06-17", 11),
                outing("2025-06-23", 12), outing("2025-06-24", 13),
                outing("2025-06-27", 14), outing("2025-06-28", 15),
                outing("2025-06-30", 16), outing("2025-07-01", 900)]
        row = summary(rows).iloc[0]
        self.assertEqual(row.pitches_3d, 31)
        self.assertEqual(row.appearances_3d, 2)
        self.assertEqual(row.pitches_7d, 58)
        self.assertEqual(row.previous_7d_pitches, 23)
        self.assertEqual(row.pitches_14d, 81)
        self.assertEqual(row.pitches_28d, 181)

    def test_partial_season_start_not_zero_filled(self):
        row = summary([outing("2025-06-30", 20)], coverage_start="2025-06-27").iloc[0]
        self.assertEqual(row.pitches_3d, 20)
        self.assertTrue(pd.isna(row.pitches_7d))
        self.assertFalse(row.coverage_7d)
        self.assertEqual(row.appearances_7d, 1)
        self.assertIn("recorded appearances only", row.notes)

    def test_after_coverage_end_no_false_zero(self):
        row = summary([outing("2025-06-25", 20)], coverage_end="2025-06-29").iloc[0]
        self.assertTrue(pd.isna(row.pitches_3d))
        self.assertFalse(row.coverage_3d)

    def test_missing_pitch_count_poison_only_affected_windows(self):
        row = summary([outing("2025-06-25", None), outing("2025-06-30", 19)]).iloc[0]
        self.assertEqual(row.pitches_3d, 19)
        self.assertTrue(pd.isna(row.pitches_7d))
        self.assertEqual(row.appearances_7d, 2)
        self.assertIn("1 appearance(s)", row.notes)

    def test_empty_complete_window_is_zero(self):
        row = summary([outing("2025-06-20", 20)]).iloc[0]
        self.assertEqual(row.pitches_3d, 0)
        self.assertEqual(row.pitches_7d, 0)
        self.assertEqual(row.appearances_7d, 0)

    def test_missing_calendar_date_affects_even_players_without_that_day(self):
        row = summary([outing("2025-06-30", 20)], incomplete_dates=["2025-06-29"]).iloc[0]
        self.assertTrue(pd.isna(row.pitches_3d))
        self.assertTrue(pd.isna(row.consecutive_days))

    def test_28_day_activity_cutoff(self):
        rows = [outing("2025-06-02", player=1), outing("2025-06-03", player=2)]
        self.assertEqual(summary(rows).player_id.tolist(), [2])

    def test_uncertain_game_masks_only_participating_player(self):
        rows = [outing("2025-06-25", 18, player=1), outing("2025-06-25", 22, player=2),
                outing("2025-06-27", 99, player=1, uncertain=True,
                       uncertain_dates="2025-06-27,2025-06-29")]
        result = summary(rows).set_index("player_id")
        self.assertTrue(pd.isna(result.loc[1, "pitches_7d"]))
        self.assertTrue(pd.isna(result.loc[1, "days_since"]))
        self.assertFalse(result.loc[1, "coverage_3d"])
        self.assertEqual(result.loc[2, "pitches_7d"], 22)
        self.assertEqual(result.loc[2, "pitches_28d"], 22)
        self.assertEqual(result.loc[2, "days_since"], 5)
        self.assertTrue(result.loc[2, "coverage_3d"])

    def test_future_resumption_does_not_mask_earlier_reliable_interval(self):
        rows = [outing("2025-06-10", 99, uncertain=True,
                       uncertain_dates="2025-06-10,2025-07-02"), outing("2025-06-29", 20)]
        row = summary(rows).iloc[0]
        self.assertEqual(row.pitches_3d, 20)
        self.assertEqual(row.days_since, 1)
        self.assertTrue(row.coverage_7d)


class ChronologyTests(unittest.TestCase):
    def test_future_trade_cannot_change_current_team_role_or_baseline(self):
        rows = [outing("2025-06-10", 10), outing("2025-06-15", 20),
                outing("2025-06-20", 30), outing("2025-06-30", 40)]
        baseline = summary(rows)
        rows.append(outing("2025-07-01", 500, team="B", team_id=20, start=True))
        pd.testing.assert_frame_equal(summary(rows), baseline)

    def test_trade_uses_latest_observed_team_but_keeps_earlier_team_exposure(self):
        rows = [outing("2025-06-28", 18), outing("2025-06-30", 22, team="B", team_id=20)]
        self.assertTrue(summary(rows, team="A").empty)
        row = summary(rows, team="B").iloc[0]
        self.assertEqual(row.pitches_3d, 40)
        self.assertEqual(summary(rows, team=20).iloc[0].player_id, 1)

    def test_doubleheader_game_number_overrides_game_id_order(self):
        rows = [outing("2025-06-30", 10, game=999, game_number=1),
                outing("2025-06-30", 15, game=998, game_number=2)]
        row = summary(rows).iloc[0]
        self.assertEqual(row.last_pitches, 15)
        self.assertEqual(row.pitches_3d, 25)
        self.assertEqual(row.appearances_3d, 2)
        self.assertEqual(row.consecutive_days, 1)

    def test_consecutive_appearance_dates_and_recency_separate(self):
        rows = [outing("2025-06-26"), outing("2025-06-27", game=99),
                outing("2025-06-27", game=100, game_number=2), outing("2025-06-28")]
        row = summary(rows).iloc[0]
        self.assertEqual(row.consecutive_days, 3)
        self.assertEqual(row.days_since, 2)
        self.assertIn("ending Jun 28", row.notes)

    def test_unknown_day_before_streak_does_not_infer_nonappearance(self):
        row = summary([outing("2025-06-29"), outing("2025-06-30")], coverage_start="2025-06-29").iloc[0]
        self.assertTrue(pd.isna(row.consecutive_days))

    def test_player_history_clips_future_and_preserves_zero_outs(self):
        rows = [outing("2025-06-30", outs=0), outing("2025-07-01", outs=18)]
        history = player_history(pd.DataFrame(rows), 1, "2025-06-30")
        self.assertEqual(len(history), 1)
        self.assertEqual(history.iloc[0].innings, "0.0")

    def test_suspended_game_cannot_introduce_later_participant_into_history(self):
        # Final row includes a pitcher who appeared only when the game resumed
        # in July; the API assigns it the original June game date.
        rows = [outing("2025-06-10", player=99, uncertain=True),
                outing("2025-06-30", player=1)]
        self.assertEqual(summary(rows).player_id.tolist(), [1])
        self.assertTrue(player_history(pd.DataFrame(rows), 99, "2025-06-30").empty)
        self.assertTrue(summary([rows[0]]).empty)

    def test_uncertain_row_cannot_change_last_team_role_counts_or_latest_outing(self):
        rows = [outing("2025-06-28", 18, team="A", team_id=10),
                outing("2025-06-29", 97, team="B", team_id=20, start=True, uncertain=True)]
        row = summary(rows, team="A").iloc[0]
        self.assertTrue(summary(rows, team="B").empty)
        self.assertEqual(row.team, "A")
        self.assertEqual(row.role, "Relief")
        self.assertEqual(row.last_date, pd.Timestamp("2025-06-28"))
        self.assertEqual(row.last_pitches, 18)
        self.assertEqual(row.appearances_3d, 1)
        self.assertEqual(row.starts_7d, 0)
        self.assertEqual(row.relief_7d, 1)
        self.assertTrue(pd.isna(row.days_since))
        self.assertIn("days since appearance is unknown", row.notes)

    def test_incomplete_interval_after_latest_included_outing_hides_gap(self):
        rows = [outing("2025-06-25", 22)]
        row = summary(rows, incomplete_dates=["2025-06-27"]).iloc[0]
        self.assertTrue(pd.isna(row.days_since))
        self.assertEqual(row.last_date, pd.Timestamp("2025-06-25"))
        self.assertEqual(row.last_pitches, 22)
        self.assertEqual(summary(rows, incomplete_dates=["2025-06-24"]).iloc[0].days_since, 5)

    def test_uncertain_future_date_cannot_change_earlier_output(self):
        rows = [outing("2025-06-20", 18), outing("2025-06-29", 22)]
        baseline = summary(rows)
        rows.append(outing("2025-07-01", 91, team="B", team_id=20, start=True, uncertain=True))
        pd.testing.assert_frame_equal(summary(rows, incomplete_dates=["2025-07-01"]), baseline)
        self.assertEqual(len(player_history(pd.DataFrame(rows), 1, "2025-06-30")), 2)

    def test_uncertain_row_cannot_make_inactive_pitcher_recent(self):
        rows = [outing("2025-05-01"), outing("2025-06-29", uncertain=True)]
        self.assertTrue(summary(rows).empty)


class BaselineTests(unittest.TestCase):
    def test_latest_excluded_and_only_last_five_same_role_used(self):
        rows = [outing(f"2025-06-{day:02d}", pitches) for day, pitches in
                [(1, 900), (5, 10), (10, 20), (15, 30), (20, 40), (25, 50), (30, 80)]]
        row = summary(rows).iloc[0]
        self.assertEqual(row.baseline_n, 5)
        self.assertEqual(row.baseline_median, 30)
        self.assertEqual(row.last_delta, 50)

    def test_role_change_excludes_other_role_and_notes_mix(self):
        rows = [outing("2025-06-10", 90, start=True), outing("2025-06-20", 100, start=True),
                outing("2025-06-25", 110, start=True), outing("2025-06-30", 15)]
        row = summary(rows).iloc[0]
        self.assertEqual(row.role, "Relief")
        self.assertEqual(row.baseline_n, 0)
        self.assertTrue(pd.isna(row.baseline_median))
        self.assertIn("Both start and relief", row.notes)

    def test_baseline_missing_counts_explicit_and_three_known_required(self):
        rows = [outing("2025-06-10", 10), outing("2025-06-15", None),
                outing("2025-06-20", 20), outing("2025-06-25", 30), outing("2025-06-30", 40)]
        row = summary(rows).iloc[0]
        self.assertEqual(row.baseline_n, 3)
        self.assertEqual(row.baseline_appearances, 4)
        self.assertEqual(row.baseline_median, 20)
        self.assertIn("1 of 4", row.notes)
        rows[0]["pitches"] = None
        self.assertTrue(pd.isna(summary(rows).iloc[0].baseline_median))

    def test_incomplete_gap_between_baseline_outings_suppresses_comparison(self):
        rows = [outing("2025-06-10"), outing("2025-06-15"), outing("2025-06-20"), outing("2025-06-30")]
        row = summary(rows, incomplete_dates=["2025-06-17"]).iloc[0]
        self.assertEqual(row.baseline_n, 3)
        self.assertTrue(pd.isna(row.baseline_median))
        self.assertTrue(pd.isna(row.last_delta))

    def test_uncertain_outing_dates_suppress_timing_metrics(self):
        rows = [outing("2025-06-10"), outing("2025-06-15"), outing("2025-06-20"),
                outing("2025-06-30", uncertain=True)]
        row = summary(rows).iloc[0]
        self.assertTrue(pd.isna(row.pitches_3d))
        self.assertTrue(pd.isna(row.baseline_median))
        self.assertTrue(pd.isna(row.days_since))
        self.assertEqual(row.consecutive_days, 1)
        self.assertEqual(row.last_date, pd.Timestamp("2025-06-20"))
        self.assertEqual(row.baseline_n, 2)
        self.assertEqual(row.last_pitches, 20)

    def test_uncertain_row_excluded_from_baseline_appearance_count(self):
        rows = [outing("2025-06-10", 10), outing("2025-06-15", 20),
                outing("2025-06-20", 99, uncertain=True), outing("2025-06-25", 30),
                outing("2025-06-30", 40)]
        row = summary(rows).iloc[0]
        self.assertEqual(row.baseline_n, 3)
        self.assertEqual(row.baseline_appearances, 3)
        self.assertTrue(pd.isna(row.baseline_median))

    def test_resumption_date_masks_baseline_gap_only_for_affected_player(self):
        rows = []
        for player in (1, 2):
            rows.extend([outing("2025-06-15", 10, player=player),
                         outing("2025-06-20", 20, player=player),
                         outing("2025-06-25", 30, player=player),
                         outing("2025-06-30", 40, player=player)])
        rows.append(outing("2025-06-01", 99, player=1, uncertain=True,
                           uncertain_dates="2025-06-01,2025-06-23"))
        result = summary(rows).set_index("player_id")
        self.assertTrue(pd.isna(result.loc[1, "baseline_median"]))
        self.assertEqual(result.loc[2, "baseline_median"], 20)
        self.assertEqual(result.loc[2, "last_delta"], 20)


class DailyGridTests(unittest.TestCase):
    def test_uncertain_game_masks_only_affected_player_on_both_dates(self):
        rows = [outing("2025-06-28", 97, uncertain=True, uncertain_dates="2025-06-28,2025-06-29"),
                outing("2025-06-30", 22)]
        grid = daily_pitch_grid(pd.DataFrame(rows), [1, 2], "2025-06-30", days=3,
                                coverage_start="2025-06-01", coverage_end="2025-06-30")
        self.assertTrue(pd.isna(grid.loc[1, "2025-06-28"]))
        self.assertTrue(pd.isna(grid.loc[1, "2025-06-29"]))
        self.assertEqual(grid.loc[2, "2025-06-28"], 0)
        self.assertEqual(grid.loc[2, "2025-06-29"], 0)
        self.assertEqual(grid.loc[1, "2025-06-30"], 22)
        self.assertEqual(grid.loc[2, "2025-06-30"], 0)

    def test_uncertainty_without_new_csv_field_still_masks_original_date(self):
        row = outing("2025-06-30", 97, uncertain=True)
        del row["uncertain_dates"]
        grid = daily_pitch_grid(pd.DataFrame([row]), [1, 2], "2025-06-30", days=1,
                                coverage_start="2025-06-01", coverage_end="2025-06-30")
        self.assertTrue(pd.isna(grid.loc[1, "2025-06-30"]))
        self.assertEqual(grid.loc[2, "2025-06-30"], 0)

    def test_global_source_gap_masks_every_player(self):
        rows = [outing("2025-06-30", 22, player=1), outing("2025-06-30", 18, player=2)]
        grid = daily_pitch_grid(pd.DataFrame(rows), [1, 2], "2025-06-30", days=1,
                                coverage_start="2025-06-01", coverage_end="2025-06-30",
                                incomplete_dates=["2025-06-30"])
        self.assertTrue(grid.isna().all().all())

    def test_doubleheader_summed_no_appearance_zero_missing_count_unknown(self):
        rows = [outing("2025-06-29", None, player=2), outing("2025-06-30", 10, game=1),
                outing("2025-06-30", 15, game=2, game_number=2)]
        grid = daily_pitch_grid(pd.DataFrame(rows), [1, 2, 3], "2025-06-30", days=3,
                                coverage_start="2025-06-01", coverage_end="2025-06-30")
        self.assertEqual(grid.loc[1, "2025-06-30"], 25)
        self.assertEqual(grid.loc[1, "2025-06-29"], 0)
        self.assertTrue(pd.isna(grid.loc[2, "2025-06-29"]))
        self.assertEqual(grid.loc[3, "2025-06-30"], 0)

    def test_partial_coverage_and_incomplete_dates_are_unknown_for_every_player(self):
        grid = daily_pitch_grid(pd.DataFrame([outing("2025-06-30")]), [1], "2025-06-30", days=3,
                                coverage_start="2025-06-29", coverage_end="2025-06-30",
                                incomplete_dates=["2025-06-29"])
        self.assertTrue(pd.isna(grid.loc[1, "2025-06-28"]))
        self.assertTrue(pd.isna(grid.loc[1, "2025-06-29"]))
        self.assertEqual(grid.loc[1, "2025-06-30"], 20)

    def test_omitted_coverage_never_invents_zero(self):
        grid = daily_pitch_grid(pd.DataFrame([outing("2025-06-30")]), [1], "2025-06-30")
        self.assertTrue(grid.isna().all().all())

    def test_empty_data_with_explicit_coverage_can_show_zero(self):
        grid = daily_pitch_grid(pd.DataFrame(), [1], "2025-06-30", days=1,
                                coverage_start="2025-06-30", coverage_end="2025-06-30")
        self.assertEqual(grid.iloc[0, 0], 0)

    def test_invalid_days_and_coverage_fail_loudly(self):
        for days in [0, -1, 2.5, True]:
            with self.subTest(days=days), self.assertRaises(ValueError):
                daily_pitch_grid(pd.DataFrame(), [], "2025-06-30", days=days)
        with self.assertRaises(ValueError):
            daily_pitch_grid(pd.DataFrame(), [], "2025-06-30", coverage_start="2025-07-01",
                             coverage_end="2025-06-30")


if __name__ == "__main__":
    unittest.main()
