"""A team-first, historical view of recorded MLB pitching exposure."""
from pathlib import Path
import json

import altair as alt
import pandas as pd
import streamlit as st

from baseball_workload.engine import (
    daily_pitch_grid, format_outs, player_history, prepare_appearances, team_summary,
)
from baseball_workload.fetch import load_snapshot
from baseball_workload.report import number, pitcher_brief
from baseball_workload.review_panel import render_staff_review

ROOT = Path(__file__).parent
st.set_page_config(page_title="MLB Pitching Workload", page_icon="⚾", layout="wide")


@st.cache_data
def read_data(snapshot_version):
    games, metadata = load_snapshot()
    return prepare_appearances(games), metadata


try:
    snapshot_version = tuple((ROOT / 'data' / name).stat().st_mtime_ns for name in ('appearances.parquet', 'metadata.json'))
    games, meta = read_data(snapshot_version)
except (FileNotFoundError, ValueError) as exc:
    st.title("MLB Pitching Workload")
    st.error(f"The verified data snapshot could not be loaded: {exc}")
    st.info("Run the refresh script described in README.md to create a snapshot.")
    st.stop()

coverage_start = pd.Timestamp(meta['coverage_start']).normalize()
coverage_end = pd.Timestamp(meta['coverage_end']).normalize()
incomplete = sorted(set(meta.get('incomplete_dates', [])))
uncertain_dates = sorted(set(meta.get('uncertain_dates', [])))
first_date, last_date = coverage_start.date(), coverage_end.date()
teams = sorted(games['team'].dropna().unique())

with st.sidebar:
    st.markdown("**MLB / PITCHING**")
    st.caption("A public-data study by Mauro Castillo")
    team = st.selectbox("Team", teams, index=teams.index('Texas Rangers') if 'Texas Rangers' in teams else 0)
    as_of_date = st.slider("Through end of date", first_date, last_date, last_date, format="MMM D, YYYY")
    st.caption("Historical replay. Later appearances are excluded from all calculations.")
    view = st.radio("Pitchers to show", ["Latest appearance: relief", "Latest appearance: start", "All recent pitchers"])
    st.divider()
    st.markdown("**Snapshot coverage**")
    st.write(f"{first_date:%b %d} – {last_date:%b %d, %Y}")
    st.caption(f"{games['game_id'].nunique():,} games · {len(games):,} appearances")
    fetched = meta.get('fetched_at', meta.get('retrieved_at', 'Not recorded'))
    try:
        fetched_label = pd.Timestamp(fetched).tz_convert('America/New_York').strftime('%b %d, %Y · %I:%M %p ET')
    except (ValueError, TypeError):
        fetched_label = str(fetched)
    st.caption(f"Retrieved: {fetched_label}")
    st.caption("Regular-season MLB game records. No live feed or roster feed.")

as_of = pd.Timestamp(as_of_date)
st.caption(f"HISTORICAL DEMO · {coverage_start.year} REGULAR SEASON")
st.title("MLB Pitching Workload")
st.markdown("Recent game use, in context. **Who pitched, how much, and when?**")
st.caption(
    "Game pitches omit warm-ups, bullpen sessions, other throwing, training, and athlete feedback. "
    "This view describes recorded exposure; it does not establish readiness or injury probability."
)

summary = team_summary(games, as_of, team, coverage_start, coverage_end, incomplete)
if view == 'Latest appearance: relief':
    summary = summary[summary['role'] == 'Relief']
elif view == 'Latest appearance: start':
    summary = summary[summary['role'] == 'Start']
summary = summary.sort_values(['pitches_3d', 'appearances_7d', 'player_name'], ascending=[False, False, True], na_position='last')

st.subheader(f"{team} · recent pitchers")
st.write(f"**{as_of - pd.Timedelta(days=6):%b %d} – {as_of:%b %d, %Y}** · through end of selected date")
st.caption(
    "Pitchers with an included appearance in the last 28 days whose last observed MLB team was this team. "
    "This is not an active roster. Totals follow each pitcher across MLB teams; role is their latest appearance."
)

if summary.empty:
    st.info("No recorded pitchers match this team, date, and appearance filter. Choose another view or date.")
    st.stop()

dates = pd.date_range(as_of - pd.Timedelta(days=6), as_of)
if not summary['coverage_7d'].all():
    st.warning("This seven-day window includes incomplete or uncertain dates. A dash means unknown; affected pitch totals are withheld. Appearance counts include loaded, reliably dated records only.")

grid = daily_pitch_grid(games, summary['player_id'].tolist(), as_of, days=7,
                       coverage_start=coverage_start, coverage_end=coverage_end, incomplete_dates=incomplete)
grid = grid.reindex(summary['player_id'])
display = summary.set_index('player_id')[['player_name', 'role']].copy()
for date in dates:
    display[date.strftime('%b %d')] = grid[date]
display['3d pitches'] = summary.set_index('player_id')['pitches_3d']
display['7d pitches'] = summary.set_index('player_id')['pitches_7d']
display['7d recorded apps'] = summary.set_index('player_id')['appearances_7d']
display = display.rename(columns={'player_name': 'Pitcher', 'role': 'Last role'})
date_columns = [d.strftime('%b %d') for d in dates]


def tint(value):
    if pd.isna(value):
        return "background-color: #F1EEE7; color: #665F50"
    if value == 0:
        return "color: #919997"
    strength = min(float(value) / 110, 1)
    return f"background-color: rgba(36,94,87,{0.08 + strength * 0.24:.2f}); font-weight: 600"


styled = display.style.map(tint, subset=date_columns).format(
    {col: '{:.0f}' for col in date_columns + ['3d pitches', '7d pitches', '7d recorded apps']}, na_rep='—'
)
st.dataframe(styled, hide_index=True, height=min(620, 40 + len(display) * 36), width='stretch',
             column_config={'7d recorded apps': st.column_config.NumberColumn('Apps · 7d', help='Loaded appearances with reliable dates; incomplete windows may omit appearances.', width='small')})
st.caption(
    "Cells = recorded game pitches per calendar date. Darker shading = more pitches, with no safety threshold. "
    "0 = zero recorded game pitches on a covered date; — = unknown. Doubleheader appearances are summed by date."
)
st.download_button("Download this view (CSV)", display.to_csv(index=False),
                   file_name=f"{team.replace(' ', '-')}-{as_of:%Y-%m-%d}-pitching.csv", mime='text/csv')

st.divider()
st.subheader("Trace a pitcher’s recent use")
names = summary.set_index('player_id')['player_name'].to_dict()
player_options = list(names)
with_baseline = summary[summary['baseline_median'].notna()]['player_id'].tolist()
default_player = player_options.index(with_baseline[0]) if with_baseline else 0
player_id = st.selectbox('Pitcher', player_options, index=default_player, format_func=lambda value: names[value])
row = summary.loc[summary['player_id'] == player_id].iloc[0]
history = player_history(games, player_id, as_of)
history['Appearance'] = history['is_start'].map({True: 'Started', False: 'Relief'})
history['Innings'] = history['outs'].apply(format_outs)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latest included outing · pitches", number(row['last_pitches']))
c2.metric("Pitches · last 7 days", number(row['pitches_7d']))
c3.metric("Pitches · last 28 days", number(row['pitches_28d']))
c4.metric("Days since appearance", number(row['days_since']))
st.caption(f"Latest included appearance: {pd.Timestamp(row['last_date']):%b %d, %Y} · {row['role'].lower()} · days since appearance does not measure recovery.")

if pd.notna(row['baseline_median']):
    st.write(
        f"**Previous {int(row['baseline_appearances'])} {str(row['role']).lower()} appearances:** "
        f"median **{row['baseline_median']:g} pitches** from {int(row['baseline_n'])} known counts. "
        "This comparison describes game use; outing length also reflects role, tactics, and game events."
    )
else:
    st.caption("Same-role comparison unavailable: at least three prior appearances with known counts and reliable dates are required.")
if row.get('notes'):
    st.info(row['notes'])

recent = history[history['game_date'] >= as_of - pd.Timedelta(days=55)].copy()
recent['Date'] = recent['game_date'].dt.strftime('%b %d')
recent['Game'] = recent['game_id'].astype(str)
recent['Outing'] = recent['Date'] + ' · ' + recent['Game']
date_uncertain = recent.get('date_uncertain', pd.Series(False, index=recent.index)).fillna(False)
chart_data = recent[~date_uncertain & recent['pitches'].notna()].copy()
if not chart_data.empty:
    chart = alt.Chart(chart_data).mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
        x=alt.X('Outing:N', sort=chart_data['Outing'].tolist(), title='Appearance (last 56 days)',
                axis=alt.Axis(labelExpr="split(datum.label, ' · ')[0]", labelAngle=-40)),
        y=alt.Y('pitches:Q', title='Game pitches'),
        color=alt.Color('Appearance:N', scale=alt.Scale(domain=['Started', 'Relief'], range=['#245E57', '#637F98']),
                        legend=alt.Legend(title=None, orient='top')),
        tooltip=[alt.Tooltip('game_date:T', title='Date'), alt.Tooltip('team:N', title='Team'),
                 'Appearance:N', alt.Tooltip('pitches:Q', title='Pitches'), 'Innings:N', alt.Tooltip('Game:N', title='Game ID')],
    ).properties(height=260)
    st.altair_chart(chart, width='stretch')
else:
    st.info("No appearances with known pitch counts and reliable dates in this chart window.")
if date_uncertain.any() or recent['pitches'].isna().any():
    st.caption("Appearances with uncertain dates or missing pitch counts are omitted from the chart and retained in the table below.")

render_staff_review(row, as_of, snapshot_version)

brief = pitcher_brief(row, as_of)
with st.expander("Factual briefing · ready to copy", expanded=False):
    st.code(brief, language=None, wrap_lines=True)
    st.download_button("Download briefing", brief, file_name=f"pitcher-{player_id}-{as_of:%Y-%m-%d}.txt", mime='text/plain')

with st.expander("Appearance log · reproduce the totals", expanded=False):
    st.caption("Reliably dated appearances through the selected date, including appearances with earlier teams. Suspended/resumed game records are excluded. Sources show current official records; historical corrections may have occurred.")
    logs = history.sort_values(['game_date', 'game_number', 'game_id'], ascending=[False, False, False]).copy()
    logs['Source'] = logs['game_id'].map(lambda gid: f"https://www.mlb.com/gameday/{int(gid)}/final/box")
    logs['Date note'] = logs.get('date_uncertain', pd.Series(False, index=logs.index)).map({True: 'Suspended/resumed: date uncertain', False: ''})
    log_columns = ['game_date', 'team', 'Appearance', 'pitches', 'Innings', 'batters_faced', 'game_id', 'Date note', 'Source']
    st.dataframe(logs[log_columns].rename(columns={'game_date': 'Date', 'team': 'Team', 'pitches': 'Pitches', 'batters_faced': 'Batters faced', 'game_id': 'Game ID'}),
                 hide_index=True, width='stretch', column_config={'Source': st.column_config.LinkColumn(display_text='Boxscore')})
    st.download_button("Download pitcher appearances (CSV)", history.to_csv(index=False),
                       file_name=f"pitcher-{player_id}-through-{as_of:%Y-%m-%d}.csv", mime='text/csv')

with st.expander("Methods and data coverage"):
    st.markdown("""
**Windows.** Three days means the selected calendar date and the two dates before it; seven days includes the six before it. All views end at the end of the selected date. These are calendar days, not the last N games.

**Team and role.** Team is the pitcher's last observed team by that date, not a roster assertion. Started/relief describes an appearance; an opener is recorded as a starter. Pitch counts follow the player across MLB teams.

**Comparisons.** The reference is the median of up to five previous appearances in the same observed role, excluding the latest outing. At least three comparable known counts are required. A longer outing or a second start in a week is not automatically a warning.

**Unknowns.** A missing pitch count makes the corresponding pitch total unknown. All appearances in suspended/resumed games are excluded from historical calculations because the final log cannot assign their pitches to actual throwing dates. Windows crossing those dates are withheld for pitchers appearing in the affected game. Broader source gaps withhold totals for everyone. Days since appearance is also unknown if an intervening date is incomplete. Zero-out appearances remain in the data. Innings are stored as outs: 1.2 means one inning and two outs.

**Scope.** Regular-season MLB games only. Minor-league appearances, rehab outings, postseason, warm-ups, bullpen sessions, training, and athlete feedback are not included. An absence from these records cannot establish rest or an injury. This is historical replay using the currently retrieved records, not a reconstruction of every correction available at that time.

**Sources.** [MLB Stats API](https://statsapi.mlb.com/api/v1/teams?sportId=1) supplies game records. [Baseball Savant](https://baseballsavant.mlb.com/) provides complementary performance analysis. This independent demo is not affiliated with MLB.
""")
    if incomplete:
        st.write("Dates with incomplete source coverage:")
        st.write(', '.join(incomplete))
    if uncertain_dates:
        st.write("Suspended/resumed game dates (withheld for affected pitchers):")
        st.write(', '.join(uncertain_dates))
    st.download_button("Download snapshot audit (JSON)", json.dumps(meta, indent=2, default=str), file_name='snapshot-audit.json', mime='application/json')

st.divider()
st.caption("Built by Mauro Castillo · [maurocastillomd.com](https://maurocastillomd.com) · Every summary is calculated from the recorded appearances.")
