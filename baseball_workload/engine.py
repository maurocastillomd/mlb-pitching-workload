"""Deterministic descriptions of recorded MLB game-pitch exposure.

Calendar windows include the selected date: seven days means [as_of - 6, as_of].
Appearance counts are observed counts. Pitch totals are unavailable whenever a
window has incomplete source coverage, player-specific date uncertainty, or an
appearance lacks a pitch count. One player's uncertain dates do not mask others.
No output estimates readiness, fatigue, injury, or roster membership.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = [
    "player_id", "player_name", "team_id", "team", "game_id", "game_date",
    "is_start", "pitches", "outs", "batters_faced", "game_type",
]
SUMMARY_COLUMNS = [
    "player_id", "player_name", "name", "team_id", "team", "role",
    "last_date", "last_pitches", "last_outs", "days_since",
    "appearances_3d", "pitches_3d", "appearances_7d", "pitches_7d",
    "pitches_14d", "pitches_28d", "previous_7d_pitches", "starts_7d",
    "relief_7d", "consecutive_days", "baseline_n", "baseline_appearances",
    "baseline_median", "last_delta", "notes", "coverage_3d", "coverage_7d",
    "coverage_14d", "coverage_28d", "coverage_previous_7d",
]


def _date(value: Any) -> pd.Timestamp:
    """Preserve the source's official calendar date, without UTC conversion."""
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("A valid calendar date is required.")
    if parsed.tzinfo is not None:
        parsed = parsed.tz_localize(None)
    return parsed.normalize()


def _bool(value: Any, column: str) -> bool:
    if pd.isna(value):
        raise ValueError(f"{column} must not be missing.")
    if value in (True, 1, "True", "true", "1"):
        return True
    if value in (False, 0, "False", "false", "0"):
        return False
    raise ValueError(f"{column} must contain true/false values.")


def prepare_appearances(games: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize one row per pitcher per game, without mutation.

    Exact duplicate rows are safely removed. Conflicting duplicate player/game
    keys, negative/fractional counts, missing identities, and invalid dates fail
    loudly. Zero-pitch and zero-out appearances are valid and retained.
    """
    if not isinstance(games, pd.DataFrame):
        raise TypeError("Appearances must be a pandas DataFrame.")
    frame = games.copy(deep=True)
    if frame.empty and not len(frame.columns):
        frame = pd.DataFrame(columns=REQUIRED_COLUMNS)
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing appearance columns: {', '.join(sorted(missing))}")
    for column in ("player_id", "team_id", "game_id"):
        values = pd.to_numeric(frame[column], errors="raise")
        if values.isna().any() or (values <= 0).any() or (values % 1 != 0).any():
            raise ValueError(f"{column} must contain positive integer identifiers.")
        frame[column] = values.astype("int64")
    for column in ("player_name", "team", "game_type"):
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{column} must not be missing or blank.")
        frame[column] = frame[column].astype(str)
    for column in ("pitches", "outs", "batters_faced"):
        values = pd.to_numeric(frame[column], errors="raise")
        if (values.notna() & ((values < 0) | (values % 1 != 0))).any():
            raise ValueError(f"{column} must contain nonnegative integer counts or missing values.")
        frame[column] = values.astype("Int64")
    frame["game_date"] = pd.to_datetime(frame["game_date"].map(_date))
    frame["is_start"] = frame["is_start"].map(lambda value: _bool(value, "is_start")).astype(bool)
    if "date_uncertain" in frame:
        frame["date_uncertain"] = frame["date_uncertain"].map(
            lambda value: _bool(value, "date_uncertain")
        ).astype(bool)
    else:
        frame["date_uncertain"] = False
    if "game_number" in frame:
        game_numbers = pd.to_numeric(frame["game_number"], errors="raise")
        if (game_numbers.notna() & ((game_numbers < 1) | (game_numbers % 1 != 0))).any():
            raise ValueError("game_number must contain positive integers or missing values.")
        frame["game_number"] = game_numbers.fillna(1).astype("int64")
    else:
        frame["game_number"] = 1
    frame = frame.drop_duplicates()
    duplicate_keys = frame.duplicated(["player_id", "game_id"], keep=False)
    if duplicate_keys.any():
        raise ValueError("Conflicting duplicate appearance rows for the same player and game.")
    return frame.sort_values(
        ["game_date", "game_number", "game_id", "player_id"], kind="stable"
    ).reset_index(drop=True)


def format_outs(outs: Any) -> str:
    """Convert integer outs to baseball IP notation; 20 outs is 6.2, not 6.67."""
    if pd.isna(outs):
        return "—"
    number = float(outs)
    if number < 0 or not number.is_integer():
        raise ValueError("Outs must be a nonnegative integer.")
    return f"{int(number) // 3}.{int(number) % 3}"


def player_history(games: pd.DataFrame, player_id: int, as_of: Any) -> pd.DataFrame:
    """Reliably dated appearances through as_of, across observed MLB teams.

    Final suspended-game totals cannot be allocated to their original date:
    doing so can reveal later participants before they actually appeared.
    Such rows remain in the raw snapshot but never enter historical views.
    """
    frame = prepare_appearances(games)
    history = frame.loc[
        (frame["player_id"] == int(player_id)) & (frame["game_date"] <= _date(as_of))
        & ~frame["date_uncertain"]
    ].copy()
    history["role"] = np.where(history["is_start"], "Start", "Relief")
    history["innings"] = history["outs"].map(format_outs)
    return history.reset_index(drop=True)


def _coverage(
    frame: pd.DataFrame,
    coverage_start: Any,
    coverage_end: Any,
    incomplete_dates: Iterable[Any],
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, set[pd.Timestamp]]:
    start = _date(coverage_start) if coverage_start is not None else None
    end = _date(coverage_end) if coverage_end is not None else None
    if start is not None and end is not None and start > end:
        raise ValueError("coverage_start must be on or before coverage_end.")
    # Callers provide a single player's raw rows. Source failures are global;
    # suspended-game date allocation is local to participating pitchers.
    incomplete = {_date(value) for value in incomplete_dates}
    for _, row in frame.loc[frame["date_uncertain"]].iterrows():
        dates_csv = row.get("uncertain_dates", "")
        dates = [] if pd.isna(dates_csv) else [value.strip() for value in str(dates_csv).split(",") if value.strip()]
        incomplete.update(_date(value) for value in dates)
        incomplete.add(row["game_date"])
    return start, end, incomplete


def _covered(
    first: pd.Timestamp,
    last: pd.Timestamp,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    incomplete: set[pd.Timestamp],
) -> bool:
    return bool(
        start is not None and end is not None and start <= first <= last <= end
        and not any(first <= day <= last for day in incomplete)
    )


def _pitch_sum(rows: pd.DataFrame, complete: bool) -> float:
    if not complete or rows["pitches"].isna().any():
        return np.nan
    return float(rows["pitches"].sum())


def _consecutive_days(
    history: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    incomplete: set[pd.Timestamp],
) -> float:
    """Exact appearance-date streak ending at last recorded appearance.

    Both appearance dates and the preceding non-appearance date require source
    coverage. Two games on the same date count as one consecutive date.
    """
    dates = set(history["game_date"])
    current = history.iloc[-1]["game_date"]
    count = 0
    while current in dates:
        if not _covered(current, current, start, end, incomplete):
            return np.nan
        count += 1
        current -= pd.Timedelta(days=1)
    if not _covered(current, current, start, end, incomplete):
        return np.nan
    return float(count)


def team_summary(
    games: pd.DataFrame,
    as_of: Any,
    team: str | int,
    coverage_start: Any,
    coverage_end: Any,
    incomplete_dates: Iterable[Any] = (),
) -> pd.DataFrame:
    """Recent pitchers grouped by last observed team, never by inferred roster.

    Include players with a reliably dated appearance in the last 28 calendar
    days whose latest included team through as_of matches team (name or numeric team ID). Every
    per-player calculation retains appearances with earlier teams. Latest role
    is the role of the last included outing; mixed roles are stated in notes.
    Uncertain-date rows never determine team, role, counts, or baselines. Their
    original and resumption dates still mask that player's coverage, and unknown
    gaps suppress days_since. Passed incomplete_dates denote global source gaps.

    Baseline: median known pitch counts from the previous up to five same-role
    appearances, excluding the latest outing; require at least three known
    counts. Any incomplete calendar span across those outings suppresses the
    comparison. baseline_n reports usable counts; baseline_appearances includes
    missing counts. Missing values never become zero.
    """
    raw = prepare_appearances(games)
    cutoff = _date(as_of)
    # This cut precedes team, role, streak, and baseline selection.
    raw = raw.loc[raw["game_date"] <= cutoff].copy()
    # Preserve uncertainty from raw records before excluding their participants
    # and statistics from all date-dependent identity and usage calculations.
    global_incomplete = tuple(incomplete_dates)
    _coverage(raw.iloc[:0], coverage_start, coverage_end, global_incomplete)
    frame = raw.loc[~raw["date_uncertain"]].copy()
    if frame.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    latest = frame.groupby("player_id", sort=False).tail(1)
    team_is_id = isinstance(team, (int, np.integer)) or str(team).isdigit()
    matches = latest["team_id"].eq(int(team)) if team_is_id else latest["team"].eq(str(team))
    latest = latest.loc[matches & latest["game_date"].ge(cutoff - pd.Timedelta(days=27))]
    rows: list[dict[str, Any]] = []
    for _, last in latest.iterrows():
        raw_history = raw.loc[raw["player_id"].eq(last["player_id"])]
        start, end, incomplete = _coverage(raw_history, coverage_start, coverage_end, global_incomplete)
        history = frame.loc[frame["player_id"].eq(last["player_id"])]
        recent = history.loc[history["game_date"].ge(cutoff - pd.Timedelta(days=27))]
        role = "Start" if last["is_start"] else "Relief"
        row: dict[str, Any] = {
            "player_id": int(last["player_id"]), "player_name": last["player_name"],
            "name": last["player_name"], "team_id": int(last["team_id"]),
            "team": last["team"], "role": role, "last_date": last["game_date"],
            "last_pitches": float(last["pitches"]) if pd.notna(last["pitches"]) else np.nan,
            "last_outs": float(last["outs"]) if pd.notna(last["outs"]) else np.nan,
            "days_since": (
                int((cutoff - last["game_date"]).days)
                if _covered(last["game_date"], cutoff, start, end, incomplete) else np.nan
            ),
        }
        notes: list[str] = []
        if pd.isna(row["days_since"]):
            notes.append(
                "Incomplete date coverage between the latest included outing and selected date; "
                "days since appearance is unknown."
            )
        for days in (3, 7, 14, 28):
            first = cutoff - pd.Timedelta(days=days - 1)
            window = history.loc[history["game_date"].ge(first)]
            complete = _covered(first, cutoff, start, end, incomplete)
            row[f"coverage_{days}d"] = complete
            row[f"pitches_{days}d"] = _pitch_sum(window, complete)
            if days in (3, 7):
                row[f"appearances_{days}d"] = len(window)
            if days == 7:
                row["starts_7d"] = int(window["is_start"].sum())
                row["relief_7d"] = int((~window["is_start"]).sum())
        previous_start = cutoff - pd.Timedelta(days=13)
        previous_end = cutoff - pd.Timedelta(days=7)
        previous = history.loc[history["game_date"].between(previous_start, previous_end)]
        row["coverage_previous_7d"] = _covered(previous_start, previous_end, start, end, incomplete)
        row["previous_7d_pitches"] = _pitch_sum(previous, row["coverage_previous_7d"])
        row["consecutive_days"] = _consecutive_days(history, start, end, incomplete)

        baseline = history.iloc[:-1]
        baseline = baseline.loc[baseline["is_start"].eq(last["is_start"])].tail(5)
        row["baseline_appearances"] = len(baseline)
        row["baseline_n"] = int(baseline["pitches"].notna().sum())
        baseline_covered = bool(len(baseline)) and _covered(
            baseline.iloc[0]["game_date"], last["game_date"], start, end, incomplete
        )
        row["baseline_median"] = (
            float(baseline["pitches"].median())
            if baseline_covered and row["baseline_n"] >= 3 else np.nan
        )
        row["last_delta"] = row["last_pitches"] - row["baseline_median"]
        if recent["is_start"].nunique() > 1:
            notes.append("Both start and relief appearances in the last 28 days; role shown is latest included outing.")
        if pd.notna(row["consecutive_days"]) and row["consecutive_days"] >= 2:
            notes.append(
                f"Appeared on {int(row['consecutive_days'])} consecutive dates ending {last['game_date']:%b %d}."
            )
        elif pd.isna(row["consecutive_days"]):
            notes.append("Incomplete date coverage prevents an exact consecutive-date count.")
        same_date_count = int(history["game_date"].eq(last["game_date"]).sum())
        if same_date_count > 1:
            notes.append(f"{same_date_count} appearances on the last recorded date; daily totals combine them.")
        missing_recent = int(recent["pitches"].isna().sum())
        if missing_recent:
            notes.append(f"{missing_recent} appearance(s) in the last 28 days missing pitch counts.")
        incomplete_windows = [str(days) for days in (3, 7, 14, 28) if not row[f"coverage_{days}d"]]
        if incomplete_windows:
            notes.append(f"Incomplete coverage for {', '.join(incomplete_windows)}-day windows; counts show recorded appearances only.")
        if row["baseline_n"] < 3:
            notes.append(f"Only {row['baseline_n']} known prior same-role pitch counts; at least 3 required for comparison.")
        elif not baseline_covered:
            notes.append("Incomplete date coverage across the comparison span; outing comparison unavailable.")
        missing_baseline = len(baseline) - row["baseline_n"]
        if missing_baseline:
            notes.append(f"{missing_baseline} of {len(baseline)} prior same-role outings missing pitch counts.")
        if last["game_date"] in incomplete:
            notes.append("The latest included outing falls on a date with incomplete coverage.")
        row["notes"] = " ".join(notes)
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS).sort_values(
        ["last_date", "player_name"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)


def daily_pitch_grid(
    games: pd.DataFrame,
    player_ids: Iterable[int],
    as_of: Any,
    days: int = 7,
    coverage_start: Any = None,
    coverage_end: Any = None,
    incomplete_dates: Iterable[Any] = (),
) -> pd.DataFrame:
    """Daily game-pitch totals, combining same-date doubleheaders.

    Explicit calendar coverage is needed before an absent appearance becomes 0.
    Without coverage bounds, all cells remain unknown (NaN). Uncertain-date game
    totals remain in the raw snapshot and are excluded from dated calculations;
    only their participating players' original/resumption date cells are masked.
    """
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("days must be a positive integer.")
    raw = prepare_appearances(games)
    cutoff = _date(as_of)
    raw = raw.loc[raw["game_date"].le(cutoff)]
    global_incomplete = tuple(incomplete_dates)
    _coverage(raw.iloc[:0], coverage_start, coverage_end, global_incomplete)
    frame = raw.loc[~raw["date_uncertain"]]
    dates = pd.date_range(cutoff - pd.Timedelta(days=days - 1), cutoff, freq="D")
    identities = list(dict.fromkeys(int(value) for value in player_ids))
    grid = pd.DataFrame(np.nan, index=pd.Index(identities, name="player_id"), columns=dates)
    for player_id in identities:
        raw_history = raw.loc[raw["player_id"].eq(player_id)]
        start, end, incomplete = _coverage(raw_history, coverage_start, coverage_end, global_incomplete)
        history = frame.loc[frame["player_id"].eq(player_id)]
        for day in dates:
            if _covered(day, day, start, end, incomplete):
                grid.loc[player_id, day] = _pitch_sum(history.loc[history["game_date"].eq(day)], True)
    return grid
