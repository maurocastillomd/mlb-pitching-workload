"""Cached, auditable MLB game-exposure data. No network work at app startup."""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

API = "https://statsapi.mlb.com/api/v1"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
INT_COLUMNS = ["player_id", "team_id", "game_id", "pitches", "outs", "batters_faced", "game_number"]
COLUMNS = ["player_id", "player_name", "team_id", "team", "game_id", "game_date", "is_start", "pitches", "outs", "batters_faced", "game_type", "game_number", "game_start", "date_uncertain", "uncertain_dates"]


def optional_int(value: Any) -> int | None:
    """Missing and invalid counts stay missing; zero is valid."""
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (ValueError, TypeError):
        return None
    if number < 0 or (isinstance(value, float) and value != number):
        return None
    return number


def innings_to_outs(value: Any) -> int | None:
    """MLB innings are baseball notation: 5.2 means 17 outs, not 5.2 innings."""
    if value is None or value == "":
        return None
    pieces = str(value).split(".")
    if len(pieces) > 2 or not pieces[0].isdigit():
        return None
    remainder = pieces[1] if len(pieces) == 2 else "0"
    if remainder not in {"0", "1", "2"}:
        return None
    return int(pieces[0]) * 3 + int(remainder)


def parse_schedule(payload: dict) -> tuple[dict[int, dict], dict]:
    """Use final regular-season games; collapse postponed/resumed duplicates by ID."""
    games: dict[int, dict] = {}
    uncertain_dates: set[str] = set()
    uncertain_game_dates: dict[int, set[str]] = {}
    uncertain_ids: set[int] = set()
    observed_ids: set[int] = set()
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            if game.get("gameType") != "R":
                continue
            game_id = int(game["gamePk"])
            observed_ids.add(game_id)
            official_date = game.get("officialDate", day["date"])
            resumed = any(game.get(key) for key in ("resumeDate", "resumeGameDate", "resumedFrom", "resumedFromDate"))
            if resumed:
                uncertain_ids.add(game_id)
                dates = uncertain_game_dates.setdefault(game_id, set())
                dates.add(official_date)
                for key in ("resumeDate", "resumeGameDate", "resumedFrom", "resumedFromDate", "gameDate"):
                    if game.get(key):
                        dates.add(game[key][:10])
                uncertain_dates.update(dates)
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            candidate = {
                "game_id": game_id,
                "game_date": official_date,
                "game_start": game.get("gameDate", ""),
                "game_number": game.get("gameNumber", 1),
                "home_id": int(game["teams"]["home"]["team"]["id"]),
                "away_id": int(game["teams"]["away"]["team"]["id"]),
                "game_type": "R",
            }
            if game_id not in games or candidate["game_start"] < games[game_id]["game_start"]:
                games[game_id] = candidate
    for game_id, game in games.items():
        game["date_uncertain"] = game_id in uncertain_ids
        game["uncertain_dates"] = ",".join(sorted(uncertain_game_dates.get(game_id, set())))
    return games, {
        "schedule_regular_season_unique_games": len(observed_ids),
        "schedule_final_games": len(games),
        "schedule_nonfinal_games": len(observed_ids - games.keys()),
        "uncertain_game_ids": sorted(uncertain_ids & games.keys()),
        "uncertain_dates": sorted(uncertain_dates),
        "uncertain_game_dates": {str(game_id): sorted(dates) for game_id, dates in sorted(uncertain_game_dates.items()) if game_id in games},
    }


def parse_roster(payload: dict, schedule: dict[int, dict]) -> list[dict]:
    """Full-season rosters hydrate each player's game logs, including traded players."""
    rows = []
    for member in payload.get("roster", []):
        person = member.get("person", {})
        for group in person.get("stats", []):
            if group.get("group", {}).get("displayName") != "pitching":
                continue
            if group.get("type", {}).get("displayName") != "gameLog":
                continue
            for split in group.get("splits", []):
                game_id = split.get("game", {}).get("gamePk")
                if game_id not in schedule or split.get("gameType", "R") != "R":
                    continue
                if split.get("sport", {}).get("id", 1) != 1:
                    continue
                game = schedule[game_id]
                stat = split.get("stat", {})
                # Zero outs/pitches can be legitimate appearances (e.g. an intentional walk).
                if stat.get("gamesPitched") == 0 or stat.get("gamesPlayed") == 0:
                    continue
                team = split.get("team", {})
                player = split.get("player", person)
                outs = optional_int(stat.get("outs"))
                if outs is None:
                    outs = innings_to_outs(stat.get("inningsPitched"))
                starts = optional_int(stat.get("gamesStarted"))
                rows.append({
                    "player_id": int(player["id"]),
                    "player_name": player.get("fullName", person.get("fullName", "Unknown")),
                    "team_id": int(team["id"]),
                    "team": team["name"],
                    "game_id": game_id,
                    "game_date": game["game_date"],
                    "is_start": None if starts is None else starts > 0,
                    "pitches": optional_int(stat.get("numberOfPitches")),
                    "outs": outs,
                    "batters_faced": optional_int(stat.get("battersFaced")),
                    "game_type": "R",
                    "game_number": game["game_number"],
                    "game_start": game["game_start"],
                    "date_uncertain": game["date_uncertain"],
                    "uncertain_dates": game.get("uncertain_dates", ""),
                })
    return rows


def appearances_frame(rows: list[dict]) -> pd.DataFrame:
    """Deduplicate repeated traded-player logs, but reject contradictory records."""
    frame = pd.DataFrame(rows, columns=COLUMNS)
    for col in INT_COLUMNS:
        frame[col] = frame[col].astype("Int64")
    frame["is_start"] = frame["is_start"].astype("boolean")
    frame["date_uncertain"] = frame["date_uncertain"].astype("bool")
    frame = frame.drop_duplicates()
    if frame.duplicated(["game_id", "player_id", "team_id"]).any():
        raise ValueError("Conflicting MLB records for the same pitcher appearance")
    return frame.sort_values(["game_date", "game_start", "game_number", "game_id", "team_id", "player_id"]).reset_index(drop=True)


def parse_team_totals(payload: dict, schedule: dict[int, dict]) -> list[dict]:
    totals = []
    for group in payload.get("stats", []):
        for split in group.get("splits", []):
            game_id = split.get("game", {}).get("gamePk")
            if game_id not in schedule:
                continue
            stat = split.get("stat", {})
            outs = optional_int(stat.get("outs"))
            totals.append({
                "game_id": game_id,
                "team_id": int(split["team"]["id"]),
                "pitches": optional_int(stat.get("numberOfPitches")),
                "outs": outs if outs is not None else innings_to_outs(stat.get("inningsPitched")),
                "batters_faced": optional_int(stat.get("battersFaced")),
            })
    return totals


def missing_pitcher_ids(season_index: dict, observed_ids: set[int]) -> list[int]:
    """Roster history can omit a real player; cross-check the league pitching index."""
    indexed = set()
    for group in season_index.get("stats", []):
        splits = group.get("splits", [])
        if group.get("totalSplits", len(splits)) > len(splits):
            raise ValueError("MLB season pitcher index was truncated; increase the API limit")
        indexed.update(int(split["player"]["id"]) for split in splits if split.get("player"))
    if not indexed:
        raise ValueError("MLB season pitcher index is empty")
    return sorted(indexed - observed_ids)


def audit_coverage(frame: pd.DataFrame, schedule: dict[int, dict], team_totals: list[dict]) -> dict:
    """Reconcile every team-game against independent team logs, not row presence alone."""
    expected = {(gid, game[side]) for gid, game in schedule.items() for side in ("home_id", "away_id")}
    actual = {(int(gid), int(tid)) for gid, tid in frame[["game_id", "team_id"]].itertuples(index=False, name=None)}
    totals = {(row["game_id"], row["team_id"]): row for row in team_totals}
    missing_pairs = sorted(expected - actual)
    missing_totals = sorted(expected - totals.keys())
    unexpected_pairs = sorted(actual - expected)
    mismatches = []
    incomplete_dates = {schedule[gid]["game_date"] for gid, _ in missing_pairs + missing_totals}
    for pair, records in frame.groupby(["game_id", "team_id"]):
        key = (int(pair[0]), int(pair[1]))
        if key not in totals:
            continue
        for metric in ("pitches", "outs", "batters_faced"):
            expected_value = totals[key][metric]
            measured = None if records[metric].isna().any() else int(records[metric].sum())
            if measured is None or expected_value is None or measured != expected_value:
                mismatches.append({"game_id": key[0], "team_id": key[1], "metric": metric, "appearances_total": measured, "team_total": expected_value})
                incomplete_dates.add(schedule[key[0]]["game_date"])
    complete = not (missing_pairs or missing_totals or unexpected_pairs or mismatches)
    return {
        "coverage_status": "complete" if complete else "incomplete",
        "coverage_complete": complete,
        "expected_team_games": len(expected),
        "observed_team_games": len(actual),
        "loaded_games": int(frame["game_id"].nunique()),
        "missing_team_games": [list(pair) for pair in missing_pairs],
        "missing_team_totals": [list(pair) for pair in missing_totals],
        "unexpected_team_games": [list(pair) for pair in unexpected_pairs],
        "reconciliation_mismatches": mismatches,
        "incomplete_dates": sorted(incomplete_dates),
        "missing_values": {metric: int(frame[metric].isna().sum()) for metric in ("pitches", "outs", "batters_faced", "is_start")},
    }


class CachedMLBClient:
    """Read-only requests with persistent compressed cache and modest throttling."""

    def __init__(self, cache_dir: Path, force: bool = False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.force = force
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "BaseballWorkloadDemo/0.1 (historical research; cached requests)"
        self.source_times: list[float] = []

    def get(self, path: str, params: dict) -> dict:
        digest = hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()[:20]
        cached = self.cache_dir / f"{digest}.json.gz"
        if cached.exists() and not self.force:
            self.source_times.append(cached.stat().st_mtime)
            with gzip.open(cached, "rt") as handle:
                return json.load(handle)
        for attempt in range(3):
            try:
                response = self.session.get(API + path, params=params, timeout=60)
                response.raise_for_status()
                payload = response.json()
                if payload.get("message") and "error" in payload.get("message", "").lower():
                    raise ValueError(payload["message"])
                with gzip.open(cached, "wt") as handle:
                    json.dump(payload, handle)
                self.source_times.append(cached.stat().st_mtime)
                time.sleep(0.2)
                return payload
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        raise RuntimeError("Unreachable retry state")


def refresh_snapshot(season: int = 2025, data_dir: Path = DEFAULT_DATA_DIR, force: bool = False, progress: Callable[[str], None] = print) -> dict:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    client = CachedMLBClient(data_dir / "raw", force=force)
    schedule_payload = client.get("/schedule", {"sportId": 1, "season": season, "gameType": "R"})
    schedule, schedule_meta = parse_schedule(schedule_payload)
    if not schedule:
        raise ValueError(f"No final MLB regular-season games found for {season}")
    teams_payload = client.get("/teams", {"sportId": 1, "season": season})
    rows, totals = [], []
    teams = teams_payload.get("teams", [])
    for index, team in enumerate(teams, 1):
        team_id = int(team["id"])
        progress(f"{index}/{len(teams)}: {team['name']}")
        roster = client.get(f"/teams/{team_id}/roster", {
            "rosterType": "fullSeason", "season": season,
            "hydrate": f"person(stats(group=[pitching],type=[gameLog],season={season},gameType=R))",
        })
        rows.extend(parse_roster(roster, schedule))
        team_log = client.get(f"/teams/{team_id}/stats", {
            "stats": "gameLog", "group": "pitching", "season": season, "gameType": "R", "limit": 10000,
        })
        totals.extend(parse_team_totals(team_log, schedule))
    # A verified 2025 edge case: the Padres fullSeason roster omits Nick Pivetta.
    # The league pitching index includes him; hydrate any such missing people.
    season_index = client.get("/stats", {
        "stats": "season", "group": "pitching", "season": season, "sportIds": 1,
        "gameType": "R", "playerPool": "ALL", "limit": 10000,
    })
    supplemental_ids = missing_pitcher_ids(season_index, {row["player_id"] for row in rows})
    for offset in range(0, len(supplemental_ids), 50):
        batch = supplemental_ids[offset:offset + 50]
        progress(f"Supplementing {len(batch)} pitcher(s) missing from full-season roster responses")
        people = client.get("/people", {
            "personIds": ",".join(map(str, batch)),
            "hydrate": f"stats(group=[pitching],type=[gameLog],season={season},gameType=R)",
        })
        rows.extend(parse_roster({"roster": [{"person": person} for person in people.get("people", [])]}, schedule))
    frame = appearances_frame(rows)
    audit = audit_coverage(frame, schedule, totals)
    game_dates = [game["game_date"] for game in schedule.values()]
    metadata = {
        "schema_version": 1,
        "season": season,
        "game_type": "R",
        "source": "MLB Stats API",
        "source_url": API,
        "source_endpoints": ["/schedule", "/teams", "/teams/{id}/roster (fullSeason, hydrated pitcher game logs)", "/teams/{id}/stats (team pitching game logs)", "/stats (league season pitching index)", "/people (supplemental pitcher game logs)"],
        "source_attribution": schedule_payload.get("copyright", "MLB Advanced Media, L.P."),
        "fetched_at": datetime.fromtimestamp(max(client.source_times), timezone.utc).isoformat(),
        "source_fetch_started_at": datetime.fromtimestamp(min(client.source_times), timezone.utc).isoformat(),
        "snapshot_generated_at": datetime.now(timezone.utc).isoformat(),
        "supplemental_pitcher_ids": supplemental_ids,
        "coverage_start": min(game_dates),
        "coverage_end": max(game_dates),
        "appearance_count": len(frame),
        "pitcher_count": int(frame["player_id"].nunique()),
        "team_count": int(frame["team_id"].nunique()),
        "date_basis": "MLB official game date; suspended/resumed games flagged as temporally uncertain",
        "limitations": [
            "Regular-season MLB games only; excludes postseason, minor leagues, warm-ups, bullpen sessions and all other throwing.",
            "Team labels identify the team in that appearance, not current roster or availability.",
            "Pitch totals in suspended/resumed games cannot safely be assigned to a single actual throwing date; affected dates are listed.",
            "Historical replay uses final corrected statistics, not a reconstruction of what was known live on each date.",
        ],
        **schedule_meta,
        **audit,
    }
    # All network/parsing/audit work completes before replacing either snapshot file.
    parquet_temp = data_dir / "appearances.parquet.tmp"
    metadata_temp = data_dir / "metadata.json.tmp"
    frame.to_parquet(parquet_temp, index=False)
    metadata_temp.write_text(json.dumps(metadata, indent=2) + "\n")
    parquet_temp.replace(data_dir / "appearances.parquet")
    metadata_temp.replace(data_dir / "metadata.json")
    return metadata


def load_snapshot(data_dir: Path = DEFAULT_DATA_DIR) -> tuple[pd.DataFrame, dict]:
    data_dir = Path(data_dir)
    frame = pd.read_parquet(data_dir / "appearances.parquet")
    metadata = json.loads((data_dir / "metadata.json").read_text())
    return frame, metadata
