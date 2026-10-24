"""Exercise the shipped snapshot through real Streamlit widget reruns."""
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'


def test_default_view_and_role_filter_are_usable():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == 'MLB Pitching Workload'
    assert app.sidebar.slider[0].value == date(2025, 9, 28)
    assert len(app.dataframe[0].value) > 0
    assert all(metric.value != 'unknown' for metric in app.metric)
    assert app.dataframe[0].value['Last role'].eq('Relief').all()
    app.sidebar.radio[0].set_value('Latest appearance: start').run()
    assert not app.exception
    assert app.dataframe[0].value['Last role'].eq('Start').all()


def test_historical_empty_state_and_partial_coverage():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.slider[0].set_value(date(2025, 3, 18)).run()
    assert not app.exception
    assert any('No recorded pitchers match' in element.value for element in app.info)
    app.sidebar.selectbox[0].set_value('Los Angeles Dodgers').run()
    assert not app.exception
    metrics = {element.label: element.value for element in app.metric}
    assert metrics['Pitches · last 7 days'] == 'unknown'
    assert len(app.warning) > 0


def test_pitcher_selection_drives_traceable_brief_and_exports():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    options = app.selectbox[0].options
    app.selectbox[0].select(options[-1]).run()
    assert not app.exception
    assert options[-1] in app.code[0].value
    assert 'Game exposure only' in app.code[0].value
    assert 'Source' in app.dataframe[1].value
    assert len(app.get('download_button')) >= 4
