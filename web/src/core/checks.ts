// Story checks: loose ends and the shape of the story. A port of heddle/checks.py.
//
// Run over a board's story graph, or one group's contents. With no arrows in scope
// there's nothing to check, and the report says so instead of flagging every card.

import type { PathCount, StoryGraph } from "./graph.ts";
import { titleLabels, type CardData } from "./model.ts";
import { casefold, sortedBy, strip } from "./pystr.ts";

export const DEFAULT_ENDING_WORD = "Ending";
export const WARNING = "warning";
export const INFO = "info";

/** kind -> [title, severity], in the order the checks panel lists them. */
export const KINDS = new Map<string, readonly [string, string]>([
  ["dead_end", ["Dead ends", WARNING]],
  ["loose_starts", ["Several starts in one chain", WARNING]],
  ["cycle", ["Loops", WARNING]],
  ["isolated", ["Not connected", INFO]],
  ["start", ["Starts", INFO]],
  ["ending", ["Endings", INFO]],
]);

export interface Finding {
  kind: string;
  cards: readonly string[];
  message: string;
}

export class Report {
  findings: Finding[] = [];
  paths: PathCount = { count: 0, has_cycles: false };
  has_arrows = false;
  stops = 0;

  ofKind(kind: string): Finding[] {
    return this.findings.filter((f) => f.kind === kind);
  }

  get warnings(): number {
    let n = 0;
    for (const f of this.findings) {
      if (KINDS.get(f.kind)![1] === WARNING) n += f.kind !== "cycle" ? f.cards.length : 1;
    }
    return n;
  }
}

/** Marked as an ending: a tag, or the status, equal to `word` (ignoring case). */
export function isEnding(card: CardData, word = DEFAULT_ENDING_WORD): boolean {
  const key = casefold(strip(word));
  if (!key) return false;
  return casefold(strip(card.status)) === key || card.tags.some((t) => casefold(t) === key);
}

/** Check the whole board (scope null) or one group's contents (scope = its id). Arrows
 *  leaving the group still count. */
export function runChecks(graph: StoryGraph, scope: string | null = null, endingWord = DEFAULT_ENDING_WORD): Report {
  let ids: string[];
  if (scope === null) {
    ids = graph.nodes().filter((i) => !graph.outside.has(i));
  } else {
    const inside = graph.contents(scope);
    ids = graph.nodes().filter((i) => inside.has(i) && !graph.outside.has(i));
  }
  const rank = new Map(graph.arrowOrder().map((i, n) => [i, n]));
  const ordered = sortedBy(ids, (i) => rank.get(i) ?? rank.size);
  const report = new Report();
  report.stops = ordered.length;
  const hasArrows = (i: string) => graph.succ.get(i)!.length > 0 || graph.pred.get(i)!.length > 0;
  report.has_arrows = ordered.some(hasArrows);
  if (!report.has_arrows) return report;

  const labels = titleLabels(graph.cards.values()); // "Warden · East Ward" for repeats
  const title = (i: string) => labels.get(i) || graph.cards.get(i)!.title || "Untitled";

  const linked = ordered.filter(hasArrows);
  const linkedSet = new Set(linked);
  const loose = ordered.filter((i) => !linkedSet.has(i));
  const endings = linked.filter((i) => !graph.succ.get(i)!.length && isEnding(graph.cards.get(i)!, endingWord));
  const endingSet = new Set(endings);
  const dead = linked.filter((i) => !graph.succ.get(i)!.length && !endingSet.has(i));
  const starts = linked.filter((i) => !graph.pred.get(i)!.length);

  for (const i of dead) report.findings.push({ kind: "dead_end", cards: [i], message: `“${title(i)}” leads nowhere` });
  // Openings: one start per connected chain is normal; more is worth a look.
  for (const comp of graph.components(linked)) {
    const members = new Set(comp);
    const compStarts = starts.filter((i) => members.has(i));
    if (compStarts.length > 1) {
      const names = compStarts.map((i) => `“${title(i)}”`).join(", ");
      report.findings.push({
        kind: "loose_starts", cards: compStarts,
        message: `${compStarts.length} cards start the same chain: ${names}`,
      });
    }
  }
  for (const loop of graph.cycles(ids)) {
    const names = loop.map(title).join(" → ");
    report.findings.push({ kind: "cycle", cards: loop, message: `${names} → ${title(loop[0]!)}` });
  }
  for (const i of loose) report.findings.push({ kind: "isolated", cards: [i], message: `“${title(i)}” has no arrows` });
  for (const i of starts) report.findings.push({ kind: "start", cards: [i], message: `“${title(i)}”` });
  for (const i of endings) report.findings.push({ kind: "ending", cards: [i], message: `“${title(i)}”` });
  report.paths = graph.countPaths(ids);
  return report;
}

/** One line describing the report, for the top of the checks panel. */
export function summary(report: Report): string {
  if (!report.has_arrows) return "No arrows here, so there's nothing to check.";
  const starts = report.ofKind("start").length;
  const ends = report.ofKind("ending").length + report.ofKind("dead_end").length;
  const n = report.paths.count;
  const routes = `${n} route${n !== 1 ? "s" : ""}` + (report.paths.has_cycles ? " (plus loops)" : "");
  const problems = report.warnings;
  const tail = !problems ? "nothing to fix" : `${problems} to look at`;
  return `${starts} start${starts !== 1 ? "s" : ""} · ${ends} end${ends !== 1 ? "s" : ""} · ${routes} · ${tail}`;
}
