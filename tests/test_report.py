import pandas as pd

from baseball_workload.report import pitcher_brief


def test_brief_preserves_unknowns_and_includes_scope():
    row = dict(player_name='Example Pitcher', pitches_7d=float('nan'),
               appearances_7d=2, pitches_3d=27, last_date=pd.Timestamp('2025-07-01'),
               role='Relief', last_pitches=15, days_since=0, baseline_median=float('nan'),
               baseline_n=2, notes='One missing pitch count in the seven-day window.')
    result = pitcher_brief(row, '2025-07-01')
    assert 'unknown recorded MLB game pitches' in result
    assert 'across 2 observed appearance(s)' in result
    assert '27 pitches' in result
    assert 'median' not in result
    assert 'do not establish rest' in result
    assert 'One missing pitch count' in result


def test_brief_uses_displayed_baseline_without_inventing_a_rating():
    row = dict(player_name='Example Pitcher', pitches_7d=90, appearances_7d=1,
               pitches_3d=90, last_date=pd.Timestamp('2025-07-01'), role='Start',
               last_pitches=90, days_since=0, baseline_median=85.5, baseline_n=4, notes='')
    result = pitcher_brief(row, '2025-07-01')
    assert 'Previous 4 appearances in that same role: median 85.5 pitches from 4 known counts.' in result
    assert 'risk' not in result.lower()
    assert 'available' not in result.lower()
