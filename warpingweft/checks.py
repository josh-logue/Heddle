"""Story checks (pure Python, no Qt): loose ends and shape of the story.

Run over a board's story graph, or just one group's contents:

* Dead ends: cards that lead nowhere and aren't marked as an ending.
* Starts: cards nothing leads to. Several separate openings in one connected
  chain is flagged; a single start per chain is just listed.
* Endings: cards marked as an ending (a tag or status word, "Ending" by default).
* Not connected: cards with no arrows at all, on a board that has arrows.
* Loops: cards that lead back round to each other.
* Routes: how many distinct ways lead from a start to an end.

With no arrows in scope there's nothing to check (a board used for sorting
rather than story order), and the report says so instead of flagging every card.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .graph import PathCount, StoryGraph
from .model import title_labels

DEFAULT_ENDING_WORD = "Ending"

WARNING = "warning"
INFO = "info"

# kind -> (title, severity), in the order the checks panel lists them
KINDS = {
    "dead_end": ("Dead ends", WARNING),
    "loose_starts": ("Several starts in one chain", WARNING),
    "cycle": ("Loops", WARNING),
    "isolated": ("Not connected", INFO),
    "start": ("Starts", INFO),
    "ending": ("Endings", INFO),
}


@dataclass(frozen=True)
class Finding:
    kind: str                   # a key of KINDS
    cards: tuple[str, ...]      # card ids, in story order
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    paths: PathCount = PathCount(0, False)
    has_arrows: bool = False
    stops: int = 0              # cards (and empty groups) checked

    def of_kind(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    @property
    def warnings(self) -> int:
        return sum(len(f.cards) if f.kind != "cycle" else 1
                   for f in self.findings if KINDS[f.kind][1] == WARNING)


def is_ending(card, word: str = DEFAULT_ENDING_WORD) -> bool:
    """Marked as an ending: a tag, or the status, equal to `word` (ignoring case)."""
    key = word.strip().casefold()
    if not key:
        return False
    return card.status.strip().casefold() == key or any(t.casefold() == key for t in card.tags)


def run_checks(graph: StoryGraph, scope: str | None = None,
               ending_word: str = DEFAULT_ENDING_WORD) -> Report:
    """Check the whole board (scope None) or one group's contents (scope = its id).
    Arrows leaving the group still count: a card whose story carries on outside
    the group isn't a dead end."""
    if scope is None:
        ids = [i for i in graph.nodes() if i not in graph.outside]
    else:
        inside = graph.contents(scope)
        ids = [i for i in graph.nodes() if i in inside and i not in graph.outside]
    rank = {i: n for n, i in enumerate(graph.arrow_order())}
    ordered = sorted(ids, key=lambda i: rank.get(i, len(rank)))
    report = Report(stops=len(ordered))
    report.has_arrows = any(graph.succ[i] or graph.pred[i] for i in ordered)
    if not report.has_arrows:
        return report

    labels = title_labels(graph.cards.values())  # "Warden · East Ward" for repeats

    def title(i: str) -> str:
        return labels.get(i) or graph.cards[i].title or "Untitled"

    linked = [i for i in ordered if graph.succ[i] or graph.pred[i]]
    linked_set = set(linked)
    loose = [i for i in ordered if i not in linked_set]
    endings = [i for i in linked if not graph.succ[i] and is_ending(graph.cards[i], ending_word)]
    ending_set = set(endings)
    dead = [i for i in linked if not graph.succ[i] and i not in ending_set]
    starts = [i for i in linked if not graph.pred[i]]

    for i in dead:
        report.findings.append(Finding("dead_end", (i,), f"“{title(i)}” leads nowhere"))
    # Openings: one start per connected chain is normal; more is worth a look.
    for comp in graph.components(linked):
        members = set(comp)
        comp_starts = [i for i in starts if i in members]
        if len(comp_starts) > 1:
            names = ", ".join(f"“{title(i)}”" for i in comp_starts)
            report.findings.append(Finding(
                "loose_starts", tuple(comp_starts),
                f"{len(comp_starts)} cards start the same chain: {names}"))
    for loop in graph.cycles(ids):
        names = " → ".join(title(i) for i in loop)
        report.findings.append(Finding("cycle", tuple(loop), f"{names} → {title(loop[0])}"))
    for i in loose:
        report.findings.append(Finding("isolated", (i,), f"“{title(i)}” has no arrows"))
    for i in starts:
        report.findings.append(Finding("start", (i,), f"“{title(i)}”"))
    for i in endings:
        report.findings.append(Finding("ending", (i,), f"“{title(i)}”"))
    report.paths = graph.count_paths(ids)
    return report


def summary(report: Report) -> str:
    """One line describing the report, for the top of the checks panel."""
    if not report.has_arrows:
        return "No arrows here, so there's nothing to check."
    starts = len(report.of_kind("start"))
    ends = len(report.of_kind("ending")) + len(report.of_kind("dead_end"))
    n = report.paths.count
    routes = f"{n} route{'s' if n != 1 else ''}" + (" (plus loops)" if report.paths.has_cycles else "")
    problems = report.warnings
    tail = "nothing to fix" if not problems else f"{problems} to look at"
    return (f"{starts} start{'s' if starts != 1 else ''} · {ends} end{'s' if ends != 1 else ''} · "
            f"{routes} · {tail}")
