# Product stress test

## Decision

Build a public historical demo for reviewing recorded MLB pitching exposure. The first task is to inspect one team's recent usage and trace a total back to actual games. This is a product hypothesis, not evidence of real staff adoption or improved decisions.

Existing Baseball Savant game logs and rolling performance views already solve individual-player lookup. The proposed added value is the team-by-date grid, transparent handling of incomplete data, and a factual briefing that can be checked against the appearance log.

## Questions the first version should answer

- Who pitched on each of the last seven dates?
- How many recorded pitches did each pitcher throw in the last three and seven calendar days?
- What outings account for a selected total?
- How does the latest outing compare with previous appearances in the same observed role?

## Stress cases and resulting changes

| Challenge | Product response |
| --- | --- |
| One start versus two starts nearly doubles weekly pitches | Show appearance counts and same-role outing history; no spike alarm |
| A relief pitcher warms up but never enters | Describe recorded game pitches only; no readiness or availability label |
| A starter acts as an opener | Record Started/Relief per appearance; no permanent role assumption |
| A player is traded | Use last observed team through the selected date; preserve cross-team pitch history |
| A player is optioned or injured after his last game | Call the list recent pitchers, not the active bullpen or current roster |
| Doubleheader | Keep both game IDs; sum pitches by date without calling it two consecutive days |
| Zero outs or zero pitches | Retain the appearance; do not infer absence from numeric zero |
| Missing count or missing game | Withhold affected totals; never turn an unknown into zero |
| Early-season or partial data | Suppress windows outside coverage; show limited same-role history |
| Suspended/resumed game | Flag uncertain timing and withhold affected windows rather than assigning all exposure to the original date |
| Public data are corrected later | State that replay uses currently retrieved historical records |

## Removed from the NBA design

Risk points, red/amber/green states, ACWR, acute/chronic terminology, z-score alarms, and automatic training decisions. Arithmetic can be correct while its health interpretation remains unsupported. No youth Pitch Smart rest table is applied to MLB players.

## A practical usefulness check with Mauro

Use the app on one familiar team and one historical week. Try these tasks without help:

1. Identify who pitched on consecutive dates.
2. Find a pitcher with substantial recent use and open the contributing appearances.
3. Explain the latest outing using the same-role history and produce the briefing.

Target: answer the first two questions within about 30 seconds each, with no confusion between unknown and zero or between exposure and readiness. This is an acceptance target, not a measured result. If the grid does not save lookup work, simplify or stop before adding more metrics.

## Findings during implementation

- The first MLB full-season roster pull omitted 31 Nick Pivetta starts. Independent team-total reconciliation identified the gap; supplementing the player index recovered all appearances.
- Final suspended-game records initially assigned later pitchers to the original date. Those records are now excluded before historical identity, role, and appearance calculations.
- Applying suspended-date uncertainty league-wide blanked 28-day totals on 60% of otherwise eligible dates. The implemented rule scopes uncertainty to the pitchers in each affected game.
- Independent source sums matched 216 real player-window totals. All 4,860 team-game totals reconciled for pitches, outs, and batters faced.
- Functional tests and browser checks passed. Actual user time savings remain unmeasured; a numerical audit does not establish practical usefulness.

The added S&C workflow has a separate [scenario and usefulness review](SC_REVIEW_VALIDATION.md), including real historical cases, implementation fixes, and a five-minute practitioner trial.

## Sources inspected

- NBA app and local source: https://nba-workload.streamlit.app/
- Savant rolling comparisons: https://baseballsavant.mlb.com/leaderboard/rolling
- Statcast definitions: https://baseballsavant.mlb.com/csv-docs
- Pitch Smart scope: https://www.mlb.com/pitch-smart/pitching-guidelines
- MLB schedule and boxscore endpoints, validated by the data refresh and snapshot audit
