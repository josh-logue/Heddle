// Export a board as Markdown: a port of heddle/export.py.
//
// Two layouts: a document (groups and cards as headings) and an outline (nested
// bullets). Cards come in story order and branches are spelled out ("Next: Exile (if she
// refuses) · Coronation"). Titles, labels and values are escaped; descriptions and notes
// are left as written.

import type { StoryGraph } from "./graph.ts";
import type { BoardData, CardData } from "./model.ts";
import { casefold, collapseSpaces, rstrip, splitLines, strip } from "./pystr.ts";

export const DOCUMENT = "document";
export const OUTLINE = "outline";

export interface TextOptions {
  layout: typeof DOCUMENT | typeof OUTLINE;
  descriptions: boolean;
  details: boolean; // POV, characters, locations, status, tags
  notes: boolean;
  next_steps: boolean; // where each card leads (branches and arrow labels)
}

export const DEFAULT_TEXT_OPTIONS: Readonly<TextOptions> = {
  layout: DOCUMENT, descriptions: true, details: true, notes: false, next_steps: true,
};

const MARKDOWN_SPECIAL = /([\\`*_[\]<>#|~])/g;

/** Plain text made safe to drop into a Markdown line. */
export function mdEscape(text: string): string {
  return text.replace(MARKDOWN_SPECIAL, "\\$1");
}

function titleOf(card: CardData): string {
  return mdEscape(collapseSpaces(card.title)) || "Untitled";
}

function values(list: readonly string[]): string {
  return list.map(mdEscape).join(", ");
}

function detailParts(card: CardData): string[] {
  const parts: string[] = [];
  if (card.pov) parts.push(`**POV:** ${mdEscape(card.pov)}`);
  const others = card.characters.filter((c) => casefold(c) !== casefold(card.pov));
  if (others.length) parts.push(`**Characters:** ${values(others)}`);
  if (card.locations.length) parts.push(`**Locations:** ${values(card.locations)}`);
  if (card.status) parts.push(`**Status:** ${mdEscape(card.status)}`);
  if (card.tags.length) parts.push(`**Tags:** ${values(card.tags)}`);
  return parts;
}

function quoted(notes: string): string[] {
  return [...splitLines(strip(notes)).map((line) => (line ? "> " + line : ">")), ""];
}

/** Python's "\n".join(lines).rstrip() + "\n". */
function finish(lines: string[]): string {
  return rstrip(lines.join("\n")) + "\n";
}

class Exporter {
  private readonly cards: Map<string, CardData>;
  private readonly labels: Map<string, string>;
  private readonly children: Map<string, string[]>;
  private readonly include: Set<string> | null = null;

  constructor(board: BoardData, private readonly graph: StoryGraph, private readonly opt: TextOptions,
              include: Iterable<string> | null) {
    this.cards = new Map(board.cards.map((c) => [c.id, c]));
    this.labels = new Map(board.connections.map((c) => [c.id, mdEscape(collapseSpaces(c.label))]));
    // Story order, a group where its first card comes; strand cards aren't part of it.
    this.children = new Map();
    for (const [parent, kids] of graph.outline()) {
      this.children.set(parent, kids.filter((k) => this.cards.has(k) && this.cards.get(k)!.kind !== "strand"));
    }
    if (include !== null) {
      const chosen = [...include];
      const keep = new Set(chosen);
      for (const cid of chosen) for (const i of graph.contents(cid)) keep.add(i);
      for (const i of graph.containersOf(keep)) keep.add(i);
      this.include = keep;
    }
  }

  private kept(cid: string): boolean {
    return this.include === null || this.include.has(cid);
  }

  /** 'Next: A (label) · B', or '' when the only way on is simply the next card listed. */
  private nextSteps(cid: string, following: string | undefined): string {
    const steps: [string, string][] = [];
    for (const nxt of this.graph.succ.get(cid) ?? []) {
      const labels = this.graph.stepArrows(cid, nxt).map((a) => this.labels.get(a) ?? "");
      steps.push([nxt, labels.find((x) => x) ?? ""]);
    }
    if (!steps.length) return "";
    if (steps.length === 1 && !steps[0]![1] && steps[0]![0] === following) return "";
    const shown = steps.map(([n, label]) =>
      label ? `${titleOf(this.cards.get(n)!)} (${label})` : titleOf(this.cards.get(n)!));
    return "Next: " + shown.join(" · ");
  }

  /** [card id, depth] for everything kept, groups before their contents. */
  private walk(parent = "", depth = 0, out: [string, number][] = []): [string, number][] {
    for (const cid of this.children.get(parent) ?? []) {
      if (!this.kept(cid)) continue;
      out.push([cid, depth]);
      if (this.children.get(cid)?.length) this.walk(cid, depth + 1, out);
    }
    return out;
  }

  render(heading: string): string {
    const items = this.walk();
    const listed = items.map(([cid]) => cid).filter((cid) => !this.children.get(cid)?.length);
    const following = new Map<string, string>();
    for (let k = 0; k + 1 < listed.length; k++) following.set(listed[k]!, listed[k + 1]!);
    const lines = [`# ${mdEscape(heading)}`, ""];
    for (const [cid, depth] of items) {
      const card = this.cards.get(cid)!;
      const isGroup = Boolean(this.children.get(cid)?.length) || card.kind === "group";
      const nxt = this.opt.next_steps ? this.nextSteps(cid, following.get(cid)) : "";
      lines.push(...(this.opt.layout === OUTLINE
        ? this.outlineLines(card, depth, isGroup, nxt)
        : this.documentLines(card, depth, isGroup, nxt)));
    }
    return finish(lines);
  }

  private documentLines(card: CardData, depth: number, isGroup: boolean, nxt: string): string[] {
    const level = Math.min(depth + 2, 6);
    const out = [`${"#".repeat(level)} ${titleOf(card)}`, ""];
    const parts = detailParts(card);
    if (this.opt.details && parts.length) out.push(parts.join(" · "), "");
    if (this.opt.descriptions && !isGroup && strip(card.description)) out.push(strip(card.description), "");
    if (this.opt.notes && strip(card.notes)) out.push(...quoted(card.notes));
    if (nxt) out.push(`*${nxt}*`, "");
    return out;
  }

  private outlineLines(card: CardData, depth: number, isGroup: boolean, nxt: string): string[] {
    const pad = "  ".repeat(depth);
    let head = `${pad}- **${titleOf(card)}**`;
    if (this.opt.descriptions && !isGroup && strip(card.description)) head += `: ${collapseSpaces(card.description)}`;
    const out = [head];
    const sub = pad + "  - ";
    if (this.opt.details) out.push(...detailParts(card).map((p) => sub + p));
    if (this.opt.notes && strip(card.notes)) out.push(sub + "*Notes:* " + collapseSpaces(card.notes));
    if (nxt) out.push(sub + nxt);
    return out;
  }
}

/** The board (or just the cards in `include`, with the groups holding them) as Markdown,
 *  in story order. */
export function exportText(
  board: BoardData, graph: StoryGraph, heading: string,
  options: Partial<TextOptions> = {}, include: Iterable<string> | null = null,
): string {
  return new Exporter(board, graph, { ...DEFAULT_TEXT_OPTIONS, ...options }, include).render(heading);
}

/** A route read in the Path Reader, step by step, with the arrow label that led to each
 *  step. */
export function exportRoute(
  board: BoardData, route: readonly string[], via: readonly string[], heading: string,
  options: Partial<TextOptions> = {},
): string {
  const opt = { ...DEFAULT_TEXT_OPTIONS, ...options };
  const cards = new Map(board.cards.map((c) => [c.id, c]));
  const lines = [`# ${mdEscape(heading)}`, ""];
  const n = Math.min(route.length, via.length);
  for (let k = 0; k < n; k++) {
    const label = mdEscape(via[k]!);
    const card = cards.get(route[k]!);
    if (card === undefined) continue;
    const num = k + 1;
    if (opt.layout === OUTLINE) {
      let head = `${num}. **${titleOf(card)}**`;
      if (label && opt.next_steps) head += ` *(via “${label}”)*`;
      if (opt.descriptions && strip(card.description)) head += `: ${collapseSpaces(card.description)}`;
      lines.push(head);
      if (opt.details) lines.push(...detailParts(card).map((p) => "   - " + p));
      if (opt.notes && strip(card.notes)) lines.push("   - *Notes:* " + collapseSpaces(card.notes));
      continue;
    }
    lines.push(`## ${num}. ${titleOf(card)}`, "");
    if (label && opt.next_steps) lines.push(`*via “${label}”*`, "");
    const parts = detailParts(card);
    if (opt.details && parts.length) lines.push(parts.join(" · "), "");
    if (opt.descriptions && strip(card.description)) lines.push(strip(card.description), "");
    if (opt.notes && strip(card.notes)) lines.push(...quoted(card.notes));
  }
  return finish(lines);
}
