"""Code-review quick wins: Markdown escaping in text export, the named highlight,
export state handled through public helpers, and the error log."""
import sys

import pytest

from heddle import error_log, theme
from heddle.export import TextOptions, export_route, export_text, md_escape
from heddle.graph import StoryGraph
from heddle.model import BoardData, CardData, ConnectionData


# ----- Markdown escaping ----------------------------------------------------------------------
def test_md_escape():
    assert md_escape(r"a*b_c [x] #1 \ |t| <b> ~`") == r"a\*b\_c \[x\] \#1 \\ \|t\| \<b\> \~\`"
    assert md_escape("Plain words, 3.5!") == "Plain words, 3.5!"


def test_titles_labels_and_values_are_escaped_but_text_is_not():
    a = CardData(id="a", title="*Act 1* #start", tags=["_draft_"], pov="M[ara]",
                 description="She **runs**.", x=0)
    b = CardData(id="b", title="End", x=300)
    board = BoardData(cards=[a, b], connections=[ConnectionData("a", "b", label="if *brave*")])
    text = export_text(board, StoryGraph(board.cards, board.connections), "Story #1",
                       TextOptions(next_steps=True))
    assert "# Story \\#1" in text
    assert "## \\*Act 1\\* \\#start" in text
    assert "\\_draft\\_" in text and "M\\[ara\\]" in text
    assert "She **runs**." in text            # descriptions keep their own Markdown
    assert "Next: End (if \\*brave\\*)" in text  # arrow labels too
    route = export_route(board, ["a", "b"], ["", "if *brave*"], "Route")
    assert "via “if \\*brave\\*”" in route


# ----- named highlight ------------------------------------------------------------------------
def test_highlight_fields_are_named(scene):
    a = scene.add_card(CardData(title="A"))
    assert scene.highlight is None
    scene.set_highlight({a.card.id}, {"e1"}, a.card.id, "Lit", owner="paths")
    h = scene.highlight
    assert (h.cards, h.arrows, h.focus, h.label, h.owner) == ({a.card.id}, {"e1"}, a.card.id, "Lit", "paths")
    assert scene.highlight_label() == "Lit" and scene.highlight_owner() == "paths"


# ----- export state through public helpers -----------------------------------------------------
def test_theme_temporarily_restores_even_after_an_error():
    before = theme.current()
    other = theme.DARK if before is theme.LIGHT else theme.LIGHT
    with pytest.raises(RuntimeError):
        with theme.temporarily(other):
            assert theme.current() is other
            raise RuntimeError
    assert theme.current() is before


def test_export_view_hides_and_restores_view_state(scene):
    a = scene.add_card(CardData(title="A"))
    b = scene.add_card(CardData(title="B", x=300))
    scene.add_connection(a, b)
    edge = scene.edges[0]
    a.hover_state, edge.hover_state = "port", True
    scene.set_highlight({a.card.id}, label="Lit", owner="paths")
    with scene.export_view(keep_highlight=False):
        assert a.hover_state is None and edge.hover_state is False
        assert scene.highlight is None
    assert a.hover_state == "port" and edge.hover_state is True
    assert scene.highlight.label == "Lit"
    with scene.export_view(keep_highlight=True):
        assert scene.highlight.label == "Lit"


# ----- error log -----------------------------------------------------------------------------------
@pytest.fixture
def no_dialog(monkeypatch):
    shown = []
    monkeypatch.setattr(error_log, "_show_dialog", lambda summary, path: shown.append((summary, path)))
    monkeypatch.setattr(error_log, "_last_dialog", -1e9)
    return shown


def raise_and_report(exc):
    try:
        raise exc
    except BaseException:  # noqa: BLE001 - re-reported like an uncaught error
        error_log.report(*sys.exc_info())


def test_errors_are_logged_and_reported_once_per_burst(qapp, no_dialog):
    raise_and_report(ValueError("bad value"))
    raise_and_report(KeyError("second"))
    qapp.processEvents()
    log = error_log.log_path().read_text(encoding="utf-8")
    assert "ValueError: bad value" in log and "KeyError" in log and "Traceback" in log
    assert [s for s, _ in no_dialog] == ["ValueError: bad value"]  # the burst shows one dialog
    assert no_dialog[0][1] == error_log.log_path()


def test_log_is_kept_small(monkeypatch, no_dialog):
    monkeypatch.setattr(error_log, "MAX_LOG_BYTES", 200)
    for _ in range(5):
        error_log.write_log("x" * 100)
    path = error_log.log_path()
    assert path.stat().st_size < 400 and path.with_name("error.log.old").exists()


def test_ctrl_c_is_not_reported(monkeypatch, no_dialog):
    seen = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: seen.append(a[0]))
    raise_and_report(KeyboardInterrupt())
    assert seen == [KeyboardInterrupt] and not error_log.log_path().exists()


def test_install_routes_uncaught_errors(monkeypatch):
    import threading
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    error_log.install()
    assert sys.excepthook is error_log.report


def test_requirements_pin_the_tested_qt():
    from pathlib import Path

    import PySide6
    lines = [line.strip() for line in (Path(__file__).parents[1] / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    assert lines == [f"PySide6-Essentials=={PySide6.__version__}"]


def test_app_uses_only_the_essential_qt_modules():
    """Everything imported must come from PySide6-Essentials (the add-ons aren't installed)."""
    import re
    from pathlib import Path
    essentials = {"QtCore", "QtGui", "QtWidgets", "QtSvg"}
    root = Path(__file__).parents[1]
    used = set()
    for f in [*root.glob("heddle/*.py"), root / "main.py"]:
        used |= set(re.findall(r"PySide6\.(Qt\w+)", f.read_text(encoding="utf-8")))
    assert used <= essentials, used - essentials
