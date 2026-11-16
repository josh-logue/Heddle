"""The controls, written once in controls.md: shown by the Help window and turned
into the README's Controls section.

    .venv\\Scripts\\python.exe -m heddle.help_text      # refresh the README

The README section sits between the CONTROLS_START / CONTROLS_END markers; a test
fails if it no longer matches controls.md.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CONTROLS_FILE = Path(__file__).with_name("controls.md")
README_FILE = Path(__file__).resolve().parents[1] / "README.md"
CONTROLS_START = "<!-- controls:start (generated from heddle/controls.md: edit that file, then run "\
                 "`python -m heddle.help_text`) -->"
CONTROLS_END = "<!-- controls:end -->"
_ENTRY = re.compile(r"^- \*\*(?P<action>.+?)\*\*: (?P<how>.+)$")


def load_controls() -> str:
    return CONTROLS_FILE.read_text(encoding="utf-8")


def help_markdown(text: str | None = None) -> str:
    """controls.md without its editing note, for the Help window."""
    text = load_controls() if text is None else text
    return re.sub(r"<!--.*?-->\s*", "", text, flags=re.S).strip() + "\n"


def parse(text: str | None = None) -> list[tuple[str, list[tuple[str, str]]]]:
    """[(section, [(action, how), …]), …]. Raises ValueError on a line that isn't a
    heading, an entry or blank, so a slip in controls.md is caught by the tests."""
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for n, line in enumerate(help_markdown(text).splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
            continue
        m = _ENTRY.match(line)
        if m is None or not sections:
            raise ValueError(f"controls.md line {n} isn't '## Section' or '- **Action**: how': {line!r}")
        sections[-1][1].append((m["action"], m["how"]))
    return sections


def readme_section(text: str | None = None) -> str:
    """The README's Controls tables: one per section."""
    out = []
    for section, entries in parse(text):
        out += [f"### {section}", "", "| Action | How |", "|---|---|"]
        out += [f"| {action} | {how.replace('|', '\\|')} |" for action, how in entries]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def readme_with_controls(readme: str, text: str | None = None) -> str:
    """The README text with its generated Controls section brought up to date."""
    start, end = readme.find(CONTROLS_START), readme.find(CONTROLS_END)
    if start < 0 or end < start:
        raise ValueError("README.md has no controls:start / controls:end markers")
    return (readme[:start] + CONTROLS_START + "\n\n" + readme_section(text) + "\n"
            + readme[end:])


def update_readme(path: Path = README_FILE) -> bool:
    """Rewrite the README's Controls section from controls.md. Returns True if it changed."""
    old = path.read_text(encoding="utf-8")
    new = readme_with_controls(old)
    if new != old:
        path.write_text(new, encoding="utf-8")
    return new != old


if __name__ == "__main__":
    changed = update_readme()
    print("README.md controls updated" if changed else "README.md controls already up to date")
    sys.exit(0)
