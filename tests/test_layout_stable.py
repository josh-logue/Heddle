"""Auto-arrange gives the same layout every time the app runs. Python hashes strings
differently in each process, so anything that walks a set of card ids can come out in
a different order from one run to the next; ties between cards must be broken by
something that doesn't change (where the cards are, the order of the arrows)."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = """
import json, sys
sys.path.insert(0, {root!r})
from heddle.layout import Node, arrange
ids = ["start", "left", "right", "mid", "tail", "spur", "end"]
nodes = [Node(i, 230, 100) for i in ids]          # all at the same spot: every step a tie
edges = [("start", "left"), ("start", "right"), ("left", "mid"), ("right", "mid"),
         ("mid", "tail"), ("mid", "spur"), ("tail", "end"), ("spur", "end")]
print(json.dumps(arrange(nodes, edges), sort_keys=True))
print(json.dumps(arrange(nodes, edges, vertical=True, by_color=True), sort_keys=True))
"""


def test_auto_arrange_is_the_same_in_every_run():
    code = SCRIPT.format(root=str(ROOT))
    layouts = set()
    for seed in range(8):
        env = {**os.environ, "PYTHONHASHSEED": str(seed)}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                             check=True).stdout
        json.loads(out.splitlines()[0])  # (well-formed)
        layouts.add(out)
    assert len(layouts) == 1
