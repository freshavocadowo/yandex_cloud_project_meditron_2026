from streamlit.testing.v1 import AppTest


def test_demo_interface_extracts_and_displays_fields():
    app = AppTest.from_file("app.py", default_timeout=40).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "50 / 50"
    assert "processed" in app.session_state
