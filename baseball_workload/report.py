"""Plain-language exports use only the same calculated values as the screen."""
import pandas as pd


def number(value):
    return "unknown" if pd.isna(value) else f"{value:,.0f}"


def pitcher_brief(row, as_of):
    as_of = pd.Timestamp(as_of)
    start = as_of - pd.Timedelta(days=6)
    text = (
        f"{row['player_name']} | through {as_of:%b %d, %Y} (end of day)\n"
        f"{start:%b %d}–{as_of:%b %d}: {number(row['pitches_7d'])} recorded MLB game pitches "
        f"across {number(row['appearances_7d'])} observed appearance(s) with reliable dates. "
        f"Last 3 days: {number(row['pitches_3d'])} pitches.\n"
        f"Latest included appearance: {pd.Timestamp(row['last_date']):%b %d}, "
        f"{str(row['role']).lower()}, {number(row['last_pitches'])} pitches. "
        f"Days since that appearance: {number(row['days_since'])}."
    )
    if pd.notna(row['baseline_median']) and pd.notna(row['last_pitches']):
        text += (
            f"\nPrevious {int(row.get('baseline_appearances', row['baseline_n']))} appearances in that same role: "
            f"median {row['baseline_median']:g} pitches from {int(row['baseline_n'])} known counts."
        )
    if row.get('notes'):
        text += f"\nContext: {row['notes']}"
    return text + (
        "\nGame exposure only. Warm-ups, bullpen sessions, other throwing, training, "
        "and athlete feedback are not included. Days without an MLB appearance do not establish rest."
    )
