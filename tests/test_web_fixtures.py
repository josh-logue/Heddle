"""The web version's shared fixtures are up to date with this core.

web/fixtures holds what the Python core answers for a set of boards; the TypeScript port
must give the same answers (web/tests/fixtures.test.ts). If this fails after a change to
the core, rebuild them (python web/fixtures/build_fixtures.py) and update the TypeScript
to match. Temporary: goes when the Python app is retired.
"""
import importlib.util
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "web" / "fixtures"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_fixtures", FIXTURES / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_web_fixtures_are_up_to_date():
    expected = load_builder().build()
    on_disk = {p.relative_to(FIXTURES).as_posix(): p.read_text(encoding="utf-8")
               for p in FIXTURES.rglob("*.json")}
    stale = sorted(name for name in expected.keys() | on_disk.keys() if expected.get(name) != on_disk.get(name))
    assert not stale, (f"{len(stale)} web fixture file(s) out of date, e.g. {stale[:3]}: "
                       "run python web/fixtures/build_fixtures.py")
