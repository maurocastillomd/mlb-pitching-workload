from copy import deepcopy

import pandas as pd
import pytest

from baseball_workload.fetch import appearances_frame, audit_coverage, innings_to_outs, missing_pitcher_ids, optional_int, parse_roster, parse_schedule


def game(game_id=1, date="2025-04-01", status="Final", number=1, **extras):
    return {"gamePk": game_id, "officialDate": date, "gameDate": date + "T18:00:00Z", "gameType": "R", "gameNumber": number,
            "status": {"abstractGameState": status}, "teams": {"home": {"team": {"id": 140}}, "away": {"team": {"id": 111}}}, **extras}


def scheduled(*games):
    return parse_schedule({"dates": [{"date": "2025-04-01", "games": list(games)}]})


def roster(game_id=1, team_id=140, **stats):
    return {"roster": [{"person": {"id": 7, "fullName": "Sample Pitcher", "stats": [{
        "type": {"displayName": "gameLog"}, "group": {"displayName": "pitching"},
        "splits": [{"game": {"gamePk": game_id}, "team": {"id": team_id, "name": "Example"}, "gameType": "R", "stat": stats}],
    }]}}]}


@pytest.mark.parametrize("value,expected", [("5.2", 17), ("0.0", 0), ("0.1", 1), ("9", 27), (None, None), ("1.3", None), ("1.25", None), ("-1.0", None)])
def test_innings_not_decimal(value, expected):
    assert innings_to_outs(value) == expected


def test_missing_count_does_not_become_zero():
    schedule, _ = scheduled(game())
    rows = parse_roster(roster(inningsPitched="0.0", gamesPlayed=1, gamesStarted=0, battersFaced=1), schedule)
    assert rows[0]["pitches"] is None
    assert rows[0]["outs"] == 0
    assert rows[0]["is_start"] is False
    assert optional_int(0) == 0
    assert optional_int(-1) is None
    assert optional_int(2.5) is None


def test_zero_pitch_zero_out_appearance_survives():
    schedule, _ = scheduled(game())
    rows = parse_roster(roster(numberOfPitches=0, outs=0, gamesPlayed=1, gamesStarted=0, battersFaced=1), schedule)
    assert len(rows) == 1
    assert rows[0]["pitches"] == 0


def test_doubleheaders_survive_and_nonfinal_is_excluded():
    schedule, meta = scheduled(game(1, number=1), game(2, number=2), game(3, status="Preview"))
    first = parse_roster(roster(1, numberOfPitches=12, gamesPlayed=1), schedule)
    second = parse_roster(roster(2, numberOfPitches=14, gamesPlayed=1), schedule)
    assert len(appearances_frame(first + second)) == 2
    assert [r["game_number"] for r in first + second] == [1, 2]
    assert parse_roster(roster(3, gamesPlayed=1), schedule) == []
    assert meta["schedule_final_games"] == 2
    assert meta["schedule_nonfinal_games"] == 1


def test_traded_player_repeated_rosters_are_deduplicated_not_cross_team_erased():
    schedule, _ = scheduled(game(1), game(2))
    first = parse_roster(roster(1, 140, numberOfPitches=12), schedule)
    second = parse_roster(roster(2, 111, numberOfPitches=19), schedule)
    frame = appearances_frame(first + second + first)
    assert len(frame) == 2
    assert set(frame["team_id"]) == {111, 140}
    conflicting = deepcopy(first)
    conflicting[0]["pitches"] = 13
    with pytest.raises(ValueError, match="Conflicting"):
        appearances_frame(first + conflicting)


def test_suspended_resumed_schedule_deduplicates_and_flags_both_dates():
    original = game(1, "2025-05-19", resumeGameDate="2025-05-21")
    resumed = game(1, "2025-05-19", gameDate="2025-05-21T17:00:00Z", resumedFromDate="2025-05-19")
    schedule, meta = scheduled(original, resumed)
    assert len(schedule) == 1
    assert schedule[1]["date_uncertain"] is True
    assert meta["uncertain_dates"] == ["2025-05-19", "2025-05-21"]
    rows = parse_roster(roster(1, numberOfPitches=15), schedule)
    assert rows[0]["date_uncertain"] is True
    assert rows[0]["uncertain_dates"] == "2025-05-19,2025-05-21"


def test_suspended_date_association_is_specific_to_each_game():
    first = game(1, "2025-05-19", resumeGameDate="2025-05-21")
    second = game(2, "2025-06-06", resumeGameDate="2025-06-07")
    regular = game(3, "2025-06-06")
    schedule, meta = scheduled(first, second, regular)
    assert meta["uncertain_game_dates"] == {"1": ["2025-05-19", "2025-05-21"], "2": ["2025-06-06", "2025-06-07"]}
    assert meta["uncertain_dates"] == ["2025-05-19", "2025-05-21", "2025-06-06", "2025-06-07"]
    first_rows = parse_roster(roster(1, numberOfPitches=15), schedule)
    second_rows = parse_roster(roster(2, numberOfPitches=15), schedule)
    regular_rows = parse_roster(roster(3, numberOfPitches=15), schedule)
    assert first_rows[0]["uncertain_dates"] == "2025-05-19,2025-05-21"
    assert second_rows[0]["uncertain_dates"] == "2025-06-06,2025-06-07"
    assert regular_rows[0]["uncertain_dates"] == ""


def test_coverage_reconciles_both_teams_and_detects_missing_pitcher():
    schedule, _ = scheduled(game())
    rows = []
    for team_id in (140, 111):
        rows.extend(parse_roster(roster(1, team_id, numberOfPitches=90, outs=27, battersFaced=30, gamesStarted=1), schedule))
    frame = appearances_frame(rows)
    totals = [{"game_id": 1, "team_id": team, "pitches": 90, "outs": 27, "batters_faced": 30} for team in (140, 111)]
    assert audit_coverage(frame, schedule, totals)["coverage_complete"]
    missing_team = audit_coverage(frame[frame.team_id == 140], schedule, totals)
    assert not missing_team["coverage_complete"]
    assert missing_team["missing_team_games"] == [[1, 111]]
    frame.loc[frame.team_id == 140, "pitches"] = 70
    mismatch = audit_coverage(frame, schedule, totals)
    assert not mismatch["coverage_complete"]
    assert mismatch["reconciliation_mismatches"][0]["metric"] == "pitches"
    assert mismatch["incomplete_dates"] == ["2025-04-01"]


def test_coverage_never_sums_missing_as_zero():
    schedule, _ = scheduled(game())
    rows = parse_roster(roster(1, 140, outs=0, battersFaced=1), schedule)
    frame = appearances_frame(rows)
    audit = audit_coverage(frame, schedule, [{"game_id": 1, "team_id": 140, "pitches": 0, "outs": 0, "batters_faced": 1}])
    assert audit["missing_values"]["pitches"] == 1
    assert audit["reconciliation_mismatches"][0]["appearances_total"] is None
    assert not audit["coverage_complete"]


def test_league_index_recovers_missing_roster_player():
    index = {"stats": [{"totalSplits": 2, "splits": [{"player": {"id": 7}}, {"player": {"id": 601713}}]}]}
    assert missing_pitcher_ids(index, {7}) == [601713]
    index["stats"][0]["totalSplits"] = 3
    with pytest.raises(ValueError, match="truncated"):
        missing_pitcher_ids(index, {7})
