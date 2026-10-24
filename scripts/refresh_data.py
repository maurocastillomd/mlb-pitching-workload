#!/usr/bin/env python3
"""Refresh a cached historical season. The Streamlit app never calls the API."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baseball_workload.fetch import DEFAULT_DATA_DIR, refresh_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--force", action="store_true", help="Refresh source responses instead of reusing the disk cache")
    args = parser.parse_args()
    metadata = refresh_snapshot(args.season, args.data_dir, args.force)
    print(json.dumps({key: metadata[key] for key in ("season", "coverage_start", "coverage_end", "coverage_status", "appearance_count", "pitcher_count", "loaded_games", "uncertain_game_ids", "missing_values")}, indent=2))
    if not metadata["coverage_complete"]:
        print("WARNING: incomplete coverage. Inspect data/metadata.json before interpreting totals.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
