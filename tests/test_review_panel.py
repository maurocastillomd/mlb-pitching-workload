"""Usefulness contracts: a concrete review, isolated drafts, honest exports."""
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def fill_review(app):
    widget(app, 'text_input', 'Training decision to work through').set_value('Timing of the next planned strength session').run()
    widget(app, 'text_area', 'Reasoning and context needed').set_value(
        'Practice only: coordinate the planned session with other throwing; preserve the strength objective.'
    ).run()
    widget(app, 'text_input', 'Who follows up?').set_value('S&C coach and pitching coach').run()
    widget(app, 'text_input', 'Next check and when').set_value('Before the next planned lift: confirm throwing and session timing.').run()
    return app


def test_blank_review_does_not_imply_readiness_or_a_training_change():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert widget(app, 'radio', 'Proposed staff decision').value == 'Awaiting context'
    assert len(widget(app, 'multiselect', 'What still needs checking?').value) == 3
    assert widget(app, 'text_input', 'Training decision to work through').value == ''
    assert any('Awaiting context' in item.value for item in app.markdown)
    assert any('not the athlete' in item.value for item in app.caption)


def test_specific_review_and_export_keep_unknowns_and_user_reasoning_separate():
    app = fill_review(AppTest.from_file(str(APP), default_timeout=30).run())
    widget(app, 'radio', 'Proposed staff decision').set_value('Keep planned session').run()
    assert not app.exception
    assert any('open questions remain' in item.value for item in app.markdown)
    exports = '\n'.join(item.value for item in app.text)
    assert '54' in exports and 'Shawn Armstrong' in exports
    assert 'hypothetical' in exports.lower()
    assert 'Timing of the next planned strength session' in exports
    assert 'Before the next planned lift' in exports
    assert 'Other throwing' in exports
    assert widget(app, 'multiselect', 'What still needs checking?').value


def test_review_drafts_do_not_follow_a_different_player_and_are_restored():
    app = fill_review(AppTest.from_file(str(APP), default_timeout=30).run())
    pitcher = widget(app, 'selectbox', 'Pitcher')
    original = pitcher.value
    original_name = 'Shawn Armstrong'
    pitcher.select(pitcher.options[-1]).run()
    assert not app.exception
    assert widget(app, 'text_input', 'Training decision to work through').value == ''
    widget(app, 'text_input', 'Training decision to work through').set_value('Different practice case').run()
    widget(app, 'selectbox', 'Pitcher').select(original_name).run()
    assert widget(app, 'selectbox', 'Pitcher').value == original
    assert widget(app, 'text_input', 'Training decision to work through').value == 'Timing of the next planned strength session'


def test_staff_discussion_is_a_valid_documented_next_action():
    app = fill_review(AppTest.from_file(str(APP), default_timeout=30).run())
    widget(app, 'radio', 'Proposed staff decision').set_value('Discuss with staff first').run()
    assert not app.exception
    assert any('Review note prepared — open questions remain' in item.value for item in app.markdown)
    assert not any('Recognized planning decision' in item.value for item in app.caption)


def test_date_isolation_reset_and_fresh_session():
    app = fill_review(AppTest.from_file(str(APP), default_timeout=30).run())
    app.sidebar.slider[0].set_value(date(2025, 9, 27)).run()
    assert not app.exception
    assert widget(app, 'text_input', 'Training decision to work through').value == ''
    app.sidebar.slider[0].set_value(date(2025, 9, 28)).run()
    widget(app, 'selectbox', 'Pitcher').select('Shawn Armstrong').run()
    assert widget(app, 'text_input', 'Training decision to work through').value == 'Timing of the next planned strength session'
    widget(app, 'button', 'Reset this worksheet').click().run()
    assert not app.exception
    assert widget(app, 'text_input', 'Training decision to work through').value == ''
    assert widget(app, 'radio', 'Proposed staff decision').value == 'Awaiting context'
    fresh = AppTest.from_file(str(APP), default_timeout=30).run()
    assert widget(fresh, 'text_input', 'Training decision to work through').value == ''
