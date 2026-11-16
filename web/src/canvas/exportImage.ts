// Export the board (or the selected cards) as a PNG or SVG (heddle/export_image.py). The
// same drawing code as the screen, pointed at a bigger canvas or at the SVG writer, with
// the export look: no grid, selection, handles or toggles; fading only if asked for.

import type { Rect } from "../board/metrics.ts";
import type { BoardStore } from "../board/store.ts";
import type { TextMeasurer } from "../board/text.ts";
import { Camera } from "./camera.ts";
import { drawBoard, type ExportLook } from "./draw.ts";
import { SvgContext, SvgPath } from "./svg.ts";
import type { Theme } from "./theme.ts";

export const MARGIN = 30; // around the exported cards, in board units
export const MAX_PNG_SIDE = 16000; // pixels: browsers refuse much bigger canvases
export const MAX_PNG_PIXELS = 120_000_000; // and cap their area too (some well below 16,000²)
export const SCALES = [1, 2, 3] as const;

export interface ImageOptions {
  format: "png" | "svg";
  /** Just the selected cards (and what's in selected groups). */
  selectionOnly: boolean;
  /** PNG only: pixels per board unit. */
  scale: number;
  transparent: boolean;
  /** Use the light theme (for printing). */
  light: boolean;
  /** Keep the filter's and highlight's fading. */
  asShown: boolean;
}

export const DEFAULT_IMAGE_OPTIONS: ImageOptions = {
  format: "png", selectionOnly: false, scale: 2, transparent: false, light: false, asShown: false,
};

/** The cards to export: everything, or the selected ones plus the contents of selected
 *  groups. Cards folded away inside a collapsed group aren't drawn either way. */
export function exportCards(store: BoardStore, selectionOnly: boolean): Set<string> {
  const ids = new Set<string>();
  const add = (id: string) => {
    if (store.boxes.get(id)?.visible) ids.add(id);
  };
  if (!selectionOnly) {
    for (const id of store.boxes.keys()) add(id);
    return ids;
  }
  for (const id of store.selected) {
    add(id);
    for (const d of store.structure.descendants(id)) add(d);
  }
  return ids;
}

/** The area to draw: the cards and the arrows between them, plus a margin. */
export function exportRect(store: BoardStore, ids: ReadonlySet<string>): Rect | null {
  let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
  const take = (x: Rect) => {
    l = Math.min(l, x.x);
    t = Math.min(t, x.y);
    r = Math.max(r, x.x + x.w);
    b = Math.max(b, x.y + x.h);
  };
  for (const id of ids) take(store.boxes.get(id)!);
  for (const a of store.arrows) {
    if (!ids.has(a.from) || !ids.has(a.to)) continue;
    take(a.path.bounds());
    if (a.label) take(a.label);
  }
  if (l === Infinity) return null;
  return { x: l - MARGIN, y: t - MARGIN, w: r - l + 2 * MARGIN, h: b - t + 2 * MARGIN };
}

/** The PNG scale actually used: `scale`, or smaller so the image stays within the
 *  browser's limits. */
export function fittedScale(rect: Rect, scale: number): number {
  const bySide = MAX_PNG_SIDE / Math.max(rect.w, rect.h);
  const byArea = Math.sqrt(MAX_PNG_PIXELS / (rect.w * rect.h));
  return Math.min(scale, bySide, byArea);
}

function setup(store: BoardStore, rect: Rect, opts: ImageOptions, only: Set<string>) {
  const camera = new Camera();
  camera.scale = 1;
  camera.ox = rect.x;
  camera.oy = rect.y;
  camera.width = rect.w;
  camera.height = rect.h;
  const look: ExportLook = { asShown: opts.asShown, transparent: opts.transparent, only: opts.selectionOnly ? only : null };
  return { camera, look };
}

/** The board as an SVG document (null: nothing to export). */
export function renderSvg(store: BoardStore, theme: Theme, m: TextMeasurer, opts: ImageOptions): string | null {
  const ids = exportCards(store, opts.selectionOnly);
  const rect = exportRect(store, ids);
  if (!rect) return null;
  const { camera, look } = setup(store, rect, opts, ids);
  const ctx = new SvgContext();
  drawBoard(ctx as unknown as CanvasRenderingContext2D, {
    store, camera, theme, m, hover: {}, dpr: 1, exporting: look, newPath: () => new SvgPath() as unknown as Path2D,
  });
  return ctx.svg(rect.w, rect.h);
}

export interface Png {
  blob: Blob;
  /** The scale used, when it had to be smaller than asked for. */
  reducedTo: number | null;
}

/** The board as a PNG (null: nothing to export). */
export async function renderPng(store: BoardStore, theme: Theme, m: TextMeasurer, opts: ImageOptions): Promise<Png | null> {
  const ids = exportCards(store, opts.selectionOnly);
  const rect = exportRect(store, ids);
  if (!rect) return null;
  const scale = fittedScale(rect, opts.scale);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(rect.w * scale));
  canvas.height = Math.max(1, Math.round(rect.h * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser couldn't make an image that size.");
  const { camera, look } = setup(store, rect, opts, ids);
  drawBoard(ctx, { store, camera, theme, m, hover: {}, dpr: scale, exporting: look });
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("This browser couldn't make an image that size.");
  return { blob, reducedTo: scale < opts.scale ? scale : null };
}
