"""Session-only S&C reasoning worksheet for a public historical demo."""
from hashlib import sha256

import pandas as pd
import streamlit as st

from .staff_review import DECISIONS, review_context, review_note, worksheet_status


OPEN_QUESTIONS = [
    'Other throwing and the pitching staff’s plan',
    'Recent strength, power, and running work',
    'Athlete feedback and relevant staff guidance',
]
DEFAULTS = {
    'focus': '', 'open_questions': OPEN_QUESTIONS, 'decision': DECISIONS[0],
    'rationale': '', 'owner': '', 'follow_up': '',
}


def render_staff_review(row, as_of, snapshot_version):
    """Separate public facts from hypothetical entries; never persist to disk."""
    as_of = pd.Timestamp(as_of)
    context = review_context(row, as_of)
    identity = f"{row['player_id']}|{row['team_id']}|{as_of.date()}|{snapshot_version}"
    case = sha256(identity.encode()).hexdigest()[:20]
    drafts = st.session_state.setdefault('sc_review_drafts', {})
    draft = drafts.setdefault(case, {key: list(value) if isinstance(value, list) else value for key, value in DEFAULTS.items()})

    def widget_key(field):
        key = f'sc_{case}_{field}'
        if key not in st.session_state:
            st.session_state[key] = draft[field]
        return key

    def keep(field):
        # Callbacks save before a team/player/date rerun removes unused widgets.
        drafts[case][field] = st.session_state[f'sc_{case}_{field}']

    def reset_case():
        drafts[case] = {key: list(value) if isinstance(value, list) else value for key, value in DEFAULTS.items()}
        for field in DEFAULTS:
            st.session_state.pop(f'sc_{case}_{field}', None)

    with st.container(border=True):
        st.subheader('S&C staff review')
        st.caption(
            f"{row['player_name']} · historical data through {as_of:%b %d, %Y}. "
            'Use this to work through the next planned training session.'
        )
        facts_col, questions_col = st.columns(2)
        with facts_col:
            st.markdown('**Observed game context**')
            for fact in context['facts']:
                st.markdown(f'- {fact}')
        with questions_col:
            st.markdown('**Questions before training**')
            for prompt in context['prompts']:
                st.markdown(f'- {prompt}')
        st.caption(context['limitation'])

        with st.expander('Draft an S&C review', expanded=True):
            st.caption(
                'Practice worksheet: enter hypothetical planning notes, not actual athlete health information. '
                'Drafts are temporary and separate for each pitcher and date. '
                'Download to keep them; refreshing or closing this page may clear them.'
            )
            st.text_input(
                'Training decision to work through', key=widget_key('focus'),
                placeholder='e.g. Timing and dose of the next planned lower-body strength session',
                max_chars=250, on_change=keep, args=('focus',),
            )
            st.multiselect(
                'What still needs checking?', OPEN_QUESTIONS, key=widget_key('open_questions'),
                help='Keep unresolved questions visible. Removing one means you resolved it in your practice scenario; it does not verify information about the real player.',
                on_change=keep, args=('open_questions',),
            )
            st.radio('Proposed staff decision', DECISIONS, key=widget_key('decision'), horizontal=True,
                     on_change=keep, args=('decision',))
            st.text_area(
                'Reasoning and context needed', key=widget_key('rationale'), height=90, max_chars=2000,
                placeholder='Explain the question or proposed decision. Include what is unknown and the training objective you want to preserve.',
                on_change=keep, args=('rationale',),
            )
            owner_col, follow_col = st.columns([1, 2])
            with owner_col:
                st.text_input('Who follows up?', key=widget_key('owner'), max_chars=150,
                              placeholder='e.g. S&C coach + pitching coach', on_change=keep, args=('owner',))
            with follow_col:
                st.text_input('Next check and when', key=widget_key('follow_up'), max_chars=350,
                              placeholder='e.g. Confirm other throwing and planned use before the next lift',
                              on_change=keep, args=('follow_up',))

            fields = {field: st.session_state[f'sc_{case}_{field}'] for field in DEFAULTS}
            status, missing = worksheet_status(fields)
            st.markdown(f'**Worksheet: {status}**')
            if missing:
                st.caption('To make this review actionable: ' + '; '.join(missing) + '.')
            st.caption('Worksheet status describes the note, not the athlete’s readiness or clearance.')
            note = review_note(row, as_of, fields)
            download_col, reset_col = st.columns([2, 1])
            with download_col:
                st.download_button(
                    'Download S&C review (.txt)', note,
                    file_name=f"sc-practice-{row['player_id']}-{as_of:%Y-%m-%d}.txt", mime='text/plain',
                    key=f'sc_{case}_download', on_click='ignore',
                )
            with reset_col:
                st.button('Reset this worksheet', key=f'sc_{case}_reset', on_click=reset_case)
            with st.expander('Preview S&C review note'):
                st.text(note)
